"""Static MolViewSpec MVSJ/MVSX importer."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import posixpath
import re
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claimtrace.errors import SecurityError
from claimtrace.importers.base import ExtractedFact, ImportResult
from claimtrace.models import (
    CompletionTask,
    ExtractionConfidence,
    MVSXInventory,
    MVSXMember,
    NativeReference,
    ObservedSceneOperation,
    RawNativeObservation,
    ResourceReference,
    SemanticLayer,
    SourceLocation,
)
from claimtrace.models.semantic_layer import (
    ClaimCriticalStatus,
    ConfidenceValue,
    MeaningStatus,
    ReviewStatus,
    SupportStatus,
    TargetResolutionStatus,
)
from claimtrace.visual_semantics import suggest_visual_encoding


SUPPORTED_NODE_KINDS = {
    "root",
    "download",
    "parse",
    "coordinates",
    "structure",
    "transform",
    "instance",
    "component",
    "component_from_uri",
    "component_from_source",
    "representation",
    "volume",
    "volume_representation",
    "color",
    "color_from_uri",
    "color_from_source",
    "clip",
    "opacity",
    "label",
    "label_from_uri",
    "label_from_source",
    "tooltip",
    "tooltip_from_uri",
    "tooltip_from_source",
    "focus",
    "camera",
    "canvas",
    "primitives",
    "primitives_from_uri",
    "primitive",
}

OPERATION_BY_KIND = {
    "representation": "represented",
    "volume_representation": "volume_displayed",
    "color": "colored",
    "color_from_uri": "colored",
    "color_from_source": "colored",
    "clip": "clipped",
    "opacity": "opacity_changed",
    "label": "labeled",
    "label_from_uri": "labeled",
    "label_from_source": "labeled",
    "tooltip": "annotated",
    "tooltip_from_uri": "annotated",
    "tooltip_from_source": "annotated",
    "focus": "focused",
    "camera": "camera_changed",
    "canvas": "canvas_changed",
    "primitive": "primitive_overlay",
    "primitives_from_uri": "primitive_overlay",
    "transform": "transformed",
    "instance": "instanced",
}

RESOURCE_NODE_KINDS = {
    "download",
    "component_from_uri",
    "color_from_uri",
    "label_from_uri",
    "tooltip_from_uri",
    "primitives_from_uri",
}

NATIVE_REF_NODE_KINDS = {"structure", "component", "component_from_uri", "component_from_source", "volume", "instance"}

VISUAL_MEANING_KINDS = {
    "representation",
    "volume_representation",
    "color",
    "color_from_uri",
    "color_from_source",
    "opacity",
    "label",
    "label_from_uri",
    "label_from_source",
    "tooltip",
    "tooltip_from_uri",
    "tooltip_from_source",
    "primitive",
    "primitives",
    "primitives_from_uri",
}

ALLOWED_COMPRESSION = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
MAX_MEMBERS = 1000
MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
MAX_INDEX_BYTES = 32 * 1024 * 1024


@dataclass
class MVSReadResult:
    data: Any
    inventory: MVSXInventory | None = None
    member_bytes: dict[str, bytes] = field(default_factory=dict)
    scene_entry: str | None = None
    format_status: str = "standard"
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WalkItem:
    node: dict[str, Any]
    pointer: str
    context: dict[str, Any]
    source_path: str | None = None
    parent_kind: str | None = None


@dataclass(frozen=True)
class WalkIssue:
    value: Any
    pointer: str
    reason: str
    source_path: str | None = None


@dataclass(frozen=True)
class MVSRoot:
    pointer: str
    root: dict[str, Any]
    snapshot_index: int | None = None
    snapshot_metadata: dict[str, Any] = field(default_factory=dict)


REQUIRED_PARAMS: dict[str, tuple[str, ...]] = {
    "download": ("url",),
    "parse": ("format",),
    "structure": ("type",),
    "representation": ("type",),
    "camera": ("target", "position"),
    "color": ("color",),
    "label": ("text",),
    "opacity": ("opacity",),
    "component_from_uri": ("uri",),
    "color_from_uri": ("uri",),
    "label_from_uri": ("uri",),
    "tooltip_from_uri": ("uri",),
    "primitives_from_uri": ("uri",),
    "primitive": ("kind",),
}

# A deliberately small, high-confidence subset of the official v1 parent rules.
# Nodes outside this table are still preserved and shallowly interpreted; this is
# not presented as full JSON-Schema validation.
PARENT_KINDS: dict[str, set[str | None]] = {
    "root": {None},
    "download": {"root"},
    "parse": {"download"},
    "coordinates": {"parse"},
    "structure": {"parse"},
    "component": {"structure"},
    "component_from_uri": {"structure"},
    "component_from_source": {"structure"},
    "representation": {"component", "component_from_uri", "component_from_source"},
    "color": {"representation", "volume_representation"},
    "color_from_uri": {"representation", "volume_representation"},
    "color_from_source": {"representation", "volume_representation"},
    "camera": {"root"},
    "canvas": {"root"},
    "primitive": {"primitives"},
}


class MolViewSpecImporter:
    name = "molviewspec"
    stability = "stable"

    def detect(self, path: Path) -> float:
        return 0.98 if path.suffix.lower() in {".mvsj", ".mvsx"} else 0.0

    def import_into(self, path: Path, artifact_id: str, semantic: SemanticLayer) -> ImportResult:
        read_result = read_mvs(path, artifact_id)
        if read_result.inventory:
            semantic.mvsx_inventories.append(read_result.inventory)
        facts: list[ExtractedFact] = []
        warnings = list(read_result.warnings)
        artifact_path = _artifact_path(semantic, artifact_id)
        roots, envelope_issues = _roots(read_result.data, artifact_id, read_result.scene_entry)
        metadata = read_result.data.get("metadata") if isinstance(read_result.data, dict) else None
        if isinstance(metadata, dict):
            _record_document_metadata(semantic, artifact_id, metadata, read_result)
            facts.append(_document_metadata_fact(artifact_id, metadata, read_result.scene_entry, len(facts) + 1))
        elif metadata is not None:
            envelope_issues.append(
                (
                    SourceLocation(artifact_id=artifact_id, json_pointer="/metadata", path=read_result.scene_entry),
                    json.dumps(metadata, ensure_ascii=False)[:500],
                    "invalid_mvs_metadata",
                )
            )
        multiple_roots = len(roots) > 1 or any(root.snapshot_index is not None for root in roots)
        scene_ids = {
            root.pointer: _scene_for_root(semantic, artifact_id, root, multiple_roots)
            for root in roots
        }
        fallback_scene_id = (
            next(iter(scene_ids.values()))
            if scene_ids
            else _ensure_scene(semantic, artifact_id)
        )
        for location, native_text, reason in envelope_issues:
            raw = _raw_observation(artifact_id, location, native_text, reason, fallback_scene_id)
            semantic.raw_native_observations.append(raw)
            facts.append(_raw_fact(raw, len(facts) + 1))
        if read_result.format_status == "nonstandard_single_mvsj":
            raw = _raw_observation(
                artifact_id,
                SourceLocation(artifact_id=artifact_id, path=read_result.scene_entry),
                read_result.scene_entry or "unknown",
                "nonstandard_mvsx_scene_entry",
                fallback_scene_id,
            )
            semantic.raw_native_observations.append(raw)
            facts.append(_raw_fact(raw, len(facts) + 1))
        for root_entry in roots:
            scene_id = scene_ids[root_entry.pointer]
            for item in walk_tree(
                root_entry.root,
                root_entry.pointer,
                source_path=read_result.scene_entry,
            ):
                if isinstance(item, WalkIssue):
                    raw = _raw_observation(
                        artifact_id,
                        SourceLocation(artifact_id=artifact_id, json_pointer=item.pointer, path=item.source_path),
                        json.dumps(item.value, sort_keys=True, ensure_ascii=False)[:500],
                        item.reason,
                        scene_id,
                    )
                    semantic.raw_native_observations.append(raw)
                    facts.append(_raw_fact(raw, len(facts) + 1))
                    continue
                kind = str(item.node.get("kind", item.node.get("type", "unknown")))
                location = _item_location(artifact_id, item)
                if kind not in SUPPORTED_NODE_KINDS:
                    raw = _raw_observation(
                        artifact_id,
                        location,
                        json.dumps(_node_without_children(item.node), sort_keys=True),
                        "unknown_mvs_node",
                        scene_id,
                    )
                    semantic.raw_native_observations.append(raw)
                    facts.append(_raw_fact(raw, len(facts) + 1))
                    continue
                schema_issue = _shallow_schema_issue(kind, item)
                if schema_issue:
                    raw = _raw_observation(
                        artifact_id,
                        location,
                        json.dumps(_node_without_children(item.node), sort_keys=True, ensure_ascii=False),
                        schema_issue,
                        scene_id,
                    )
                    semantic.raw_native_observations.append(raw)
                    facts.append(_raw_fact(raw, len(facts) + 1))
                    continue
                if kind in RESOURCE_NODE_KINDS:
                    resource = _resource_reference(
                        artifact_id,
                        item,
                        read_result.inventory,
                        read_result.scene_entry,
                        artifact_path,
                    )
                    if resource:
                        semantic.resource_references.append(resource)
                        _mark_inventory_reference(read_result.inventory, resource, item.pointer)
                if kind in NATIVE_REF_NODE_KINDS:
                    semantic.native_references.append(_native_reference(artifact_id, item))
                if kind in OPERATION_BY_KIND:
                    op = _observed_operation(artifact_id, scene_id, item, kind)
                    semantic.observed_scene_operations.append(op)
                    if op.operation == "camera_changed" and kind == "camera":
                        _record_mvs_camera(semantic, scene_id, item)
                    facts.append(_operation_fact(op, item, len(facts) + 1))
                elif kind in {
                    "download",
                    "parse",
                    "coordinates",
                    "structure",
                    "component",
                    "volume",
                    "root",
                    "primitives",
                }:
                    facts.append(_metadata_fact(artifact_id, item, len(facts) + 1))
        tasks = _completion_tasks_for_mvs(semantic)
        return ImportResult(importer_name=self.name, facts=facts, tasks=tasks, warnings=warnings)


def read_mvs(path: Path, artifact_id: str) -> MVSReadResult:
    if path.suffix.lower() == ".mvsj":
        try:
            return MVSReadResult(data=json.loads(path.read_text(encoding="utf-8-sig")))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid MolViewSpec JSON {path} at line {exc.lineno}, column {exc.colno}: {exc.msg}."
            ) from exc
        except UnicodeDecodeError as exc:
            raise ValueError(f"MolViewSpec JSON must be UTF-8 text: {path} ({exc}).") from exc
    try:
        return _read_mvsx(path, artifact_id)
    except zipfile.BadZipFile as exc:
        raise SecurityError(f"MVSX file is not a readable ZIP archive: {path}") from exc


def _read_mvsx(path: Path, artifact_id: str) -> MVSReadResult:
    members: list[MVSXMember] = []
    member_bytes: dict[str, bytes] = {}
    scene_payload: bytes | None = None
    normalized_seen: set[str] = set()
    dirs: set[str] = set()
    files: set[str] = set()
    total_size = 0
    scene_entry: str | None = None
    format_status = "standard"
    warnings: list[str] = []
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_MEMBERS:
            raise SecurityError(f"MVSX archive has too many members: {len(infos)}")
        normalized_infos = [(info, _normalize_member_name(info.filename)) for info in infos]
        top_level = [normalized for info, normalized in normalized_infos if not info.is_dir() and normalized == "index.mvsj"]
        mvsj_entries = [normalized for info, normalized in normalized_infos if not info.is_dir() and normalized.lower().endswith(".mvsj")]
        if len(top_level) == 1:
            scene_entry = "index.mvsj"
            extras = [name for name in mvsj_entries if name != scene_entry]
            if extras:
                warnings.append(
                    "Additional .mvsj members were inventoried but not parsed: " + ", ".join(extras[:5])
                )
        elif not top_level and len(mvsj_entries) == 1:
            scene_entry = mvsj_entries[0]
            format_status = "nonstandard_single_mvsj"
            warnings.append(
                f"Static review used {scene_entry}; standard MVSX replay requires a top-level index.mvsj."
            )
        elif not mvsj_entries:
            raise SecurityError(
                "MVSX archive has no scene entry. Add a top-level file named index.mvsj and rebuild the ZIP."
            )
        else:
            names = ", ".join(mvsj_entries[:5])
            raise SecurityError(
                "MVSX archive has no unambiguous top-level index.mvsj. "
                f"Found these .mvsj files: {names}. Put the intended scene at index.mvsj in the archive root."
            )
        for info, normalized in normalized_infos:
            if normalized in normalized_seen:
                raise SecurityError(f"MVSX archive has duplicate normalized member path: {normalized}")
            normalized_seen.add(normalized)
            is_dir = info.is_dir()
            if _is_symlink(info):
                raise SecurityError(f"MVSX archive member is a symlink: {info.filename}")
            if info.compress_type not in ALLOWED_COMPRESSION:
                raise SecurityError(f"MVSX archive member uses unsupported compression: {info.filename}")
            if info.file_size > MAX_MEMBER_BYTES:
                raise SecurityError(f"MVSX archive member is too large: {info.filename}")
            total_size += info.file_size
            if total_size > MAX_TOTAL_BYTES:
                raise SecurityError("MVSX archive total uncompressed size is too large")
            if info.compress_size and info.file_size / max(info.compress_size, 1) > MAX_COMPRESSION_RATIO:
                raise SecurityError(f"MVSX archive member compression ratio is too high: {info.filename}")
            _check_collisions(normalized, is_dir, dirs, files)
            digest: str | None = None
            if not is_dir:
                scene_chunks: list[bytes] = []
                if normalized == scene_entry and info.file_size > MAX_INDEX_BYTES:
                    raise SecurityError(f"MVSX scene entry is too large: {scene_entry}")
                hasher = hashlib.sha256()
                with archive.open(info) as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        hasher.update(chunk)
                        if normalized == scene_entry:
                            scene_chunks.append(chunk)
                digest = hasher.hexdigest()
                if normalized == scene_entry:
                    scene_payload = b"".join(scene_chunks)
                    member_bytes[normalized] = scene_payload
            members.append(
                MVSXMember(
                    member_id=_stable_id("mvsx-member", artifact_id, normalized),
                    original_name=info.filename,
                    normalized_name=normalized,
                    is_dir=is_dir,
                    sha256=digest,
                    crc32=f"0x{info.CRC:08x}",
                    byte_size=info.file_size,
                    compressed_size=info.compress_size,
                    compression_method=_compression_name(info.compress_type),
                    external_attr=info.external_attr,
                    media_type=_media_type(normalized),
                )
            )
    if not scene_payload:
        raise SecurityError(f"MVSX scene entry is empty: {scene_entry}")
    try:
        data = json.loads(scene_payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SecurityError(f"MVSX scene entry {scene_entry} is not valid UTF-8 JSON: {exc}") from exc
    inventory = MVSXInventory(
        artifact_id=artifact_id,
        scene_entry=scene_entry,
        format_status=format_status,
        members=members,
    )
    return MVSReadResult(
        data=data,
        inventory=inventory,
        member_bytes=member_bytes,
        scene_entry=scene_entry,
        format_status=format_status,
        warnings=warnings,
    )


def _roots(
    data: Any,
    artifact_id: str,
    source_path: str | None = None,
) -> tuple[list[MVSRoot], list[tuple[SourceLocation, str, str]]]:
    issues: list[tuple[SourceLocation, str, str]] = []
    if isinstance(data, dict) and isinstance(data.get("root"), dict):
        root = data["root"]
        if root.get("kind") != "root":
            issues.append(
                (
                    SourceLocation(artifact_id=artifact_id, json_pointer="/root/kind", path=source_path),
                    json.dumps(root, ensure_ascii=False),
                    "invalid_mvs_root_kind",
                )
            )
            return [], issues
        return [MVSRoot(pointer="/root", root=root)], issues
    if isinstance(data, dict) and isinstance(data.get("snapshots"), list):
        roots: list[MVSRoot] = []
        for index, snapshot in enumerate(data["snapshots"]):
            pointer = f"/snapshots/{index}"
            if not isinstance(snapshot, dict):
                issues.append(
                    (
                        SourceLocation(artifact_id=artifact_id, json_pointer=pointer, path=source_path),
                        json.dumps(snapshot, ensure_ascii=False),
                        "invalid_mvs_snapshot",
                    )
                )
                continue
            root = snapshot.get("root")
            if not isinstance(root, dict):
                issues.append(
                    (
                        SourceLocation(artifact_id=artifact_id, json_pointer=f"{pointer}/root", path=source_path),
                        json.dumps(root, ensure_ascii=False),
                        "invalid_mvs_snapshot_root",
                    )
                )
                continue
            if root.get("kind") != "root":
                issues.append(
                    (
                        SourceLocation(artifact_id=artifact_id, json_pointer=f"{pointer}/root/kind", path=source_path),
                        json.dumps(root, ensure_ascii=False),
                        "invalid_mvs_root_kind",
                    )
                )
                continue
            roots.append(
                MVSRoot(
                    pointer=f"{pointer}/root",
                    root=root,
                    snapshot_index=index,
                    snapshot_metadata={key: value for key, value in snapshot.items() if key != "root"},
                )
            )
        if not roots and not issues:
            issues.append(
                (
                    SourceLocation(artifact_id=artifact_id, json_pointer="/snapshots", path=source_path),
                    "[]",
                    "invalid_mvs_snapshots",
                )
            )
        return roots, issues
    if isinstance(data, dict) and data.get("kind") == "root":
        return [MVSRoot(pointer="/", root=data)], issues
    issues.append(
        (
            SourceLocation(artifact_id=artifact_id, json_pointer="/", path=source_path),
            json.dumps(data, ensure_ascii=False)[:500],
            "invalid_mvs_envelope",
        )
    )
    return [], issues


def walk_tree(
    root: dict[str, Any],
    pointer: str = "/root",
    context: dict[str, Any] | None = None,
    *,
    source_path: str | None = None,
    parent_kind: str | None = None,
):
    context = dict(context or {})
    current = _node_without_children(root)
    kind = str(current.get("kind", current.get("type", "unknown")))
    next_context = _update_context(context, kind, current, pointer)
    yield WalkItem(
        node=current,
        pointer=pointer,
        context=next_context,
        source_path=source_path,
        parent_kind=parent_kind,
    )
    children = root.get("children")
    if children is None:
        return
    if isinstance(children, list):
        for index, child in enumerate(children):
            if isinstance(child, dict):
                yield from walk_tree(
                    child,
                    f"{pointer}/children/{index}",
                    next_context,
                    source_path=source_path,
                    parent_kind=kind,
                )
            else:
                yield WalkIssue(
                    value=child,
                    pointer=f"{pointer}/children/{index}",
                    reason="invalid_mvs_child",
                    source_path=source_path,
                )
    else:
        yield WalkIssue(
            value=children,
            pointer=f"{pointer}/children",
            reason="invalid_mvs_children",
            source_path=source_path,
        )


def _update_context(context: dict[str, Any], kind: str, node: dict[str, Any], pointer: str) -> dict[str, Any]:
    updated = dict(context)
    params = node.get("params", {}) if isinstance(node.get("params"), dict) else {}
    if kind == "download":
        updated["resource_uri"] = params.get("url") or node.get("url")
    elif kind == "parse":
        updated["parse_format"] = params.get("format") or node.get("format")
    elif kind == "structure":
        updated["structure_pointer"] = pointer
        updated["structure_params"] = params
    elif kind in {"component", "component_from_uri", "component_from_source"}:
        updated["component_pointer"] = pointer
        updated["selector"] = params.get("selector") or node.get("selector") or params.get("field_values")
    elif kind == "representation":
        updated["representation"] = params.get("type") or node.get("type")
    elif kind == "volume":
        updated["volume_pointer"] = pointer
    return updated


def _artifact_path(semantic: SemanticLayer, artifact_id: str) -> str | None:
    artifact = next((item for item in semantic.artifacts if item.id == artifact_id), None)
    return artifact.path if artifact is not None else None


def _item_location(artifact_id: str, item: WalkItem) -> SourceLocation:
    return SourceLocation(
        artifact_id=artifact_id,
        json_pointer=item.pointer,
        path=item.source_path,
    )


def _record_document_metadata(
    semantic: SemanticLayer,
    artifact_id: str,
    metadata: dict[str, Any],
    read_result: MVSReadResult,
) -> None:
    record = {
        "artifact_id": artifact_id,
        "scene_entry": read_result.scene_entry,
        "metadata": metadata,
    }
    records = semantic.package.extensions.setdefault("molviewspec_documents", [])
    if isinstance(records, list) and not any(
        isinstance(item, dict) and item.get("artifact_id") == artifact_id
        for item in records
    ):
        records.append(record)
    title = metadata.get("title")
    if semantic.package.title == "Untitled ClaimTrace package" and isinstance(title, str) and title.strip():
        semantic.package.title = title.strip()
    description = metadata.get("description")
    if semantic.package.description is None and isinstance(description, str) and description.strip():
        semantic.package.description = description.strip()


def _document_metadata_fact(
    artifact_id: str,
    metadata: dict[str, Any],
    source_path: str | None,
    index: int,
) -> ExtractedFact:
    confidence = ExtractionConfidence(
        level=ConfidenceValue.high,
        score=0.95,
        basis=["literal_mvs_document_metadata", "json_pointer"],
    )
    return ExtractedFact(
        fact_id=f"fact-mvs-{index:04d}",
        tool="molviewspec",
        artifact_id=artifact_id,
        source_location=SourceLocation(
            artifact_id=artifact_id,
            json_pointer="/metadata",
            path=source_path,
        ).model_dump(mode="json", exclude_none=True),
        native_command="document:metadata",
        native_value=metadata,
        normalized_target={"object_type": "molviewspec.metadata", "json_pointer": "/metadata"},
        normalized_value={"metadata": metadata},
        support_status=SupportStatus.supported_shallow.value,
        confidence=confidence.model_dump(mode="json", exclude_none=True),
        review_status=ReviewStatus.auto_extracted.value,
    )


def _scene_for_root(
    semantic: SemanticLayer,
    artifact_id: str,
    root: MVSRoot,
    multiple_roots: bool,
) -> str:
    if not multiple_roots:
        scene_id = _ensure_scene(semantic, artifact_id)
        scene = next(scene for scene in semantic.scenes if scene.id == scene_id)
    else:
        from claimtrace.models import Scene

        scene_id = _stable_id("scene", "molviewspec", artifact_id, root.pointer)
        scene = next((item for item in semantic.scenes if item.id == scene_id), None)
        if scene is None:
            nested_metadata = (
                root.snapshot_metadata.get("metadata")
                if isinstance(root.snapshot_metadata.get("metadata"), dict)
                else {}
            )
            title = root.snapshot_metadata.get("title") or nested_metadata.get("title")
            description = root.snapshot_metadata.get("description") or nested_metadata.get("description")
            label = title or description or f"MolViewSpec snapshot {(root.snapshot_index or 0) + 1}"
            scene = Scene(
                id=scene_id,
                description=str(label),
                native_artifact_ids=[artifact_id],
                review_status=ReviewStatus.needs_review,
            )
            semantic.scenes.append(scene)
    scene.extensions["molviewspec_root"] = {
        "json_pointer": root.pointer,
        "snapshot_index": root.snapshot_index,
        "snapshot_metadata": root.snapshot_metadata,
    }
    return scene.id


def _shallow_schema_issue(kind: str, item: WalkItem) -> str | None:
    params = item.node.get("params") if isinstance(item.node.get("params"), dict) else {}
    missing = [
        key
        for key in REQUIRED_PARAMS.get(kind, ())
        if params.get(key, item.node.get(key)) is None
    ]
    if missing:
        return "missing_required_mvs_params:" + ",".join(missing)
    allowed_parents = PARENT_KINDS.get(kind)
    if allowed_parents is not None and item.parent_kind not in allowed_parents:
        parent = item.parent_kind or "document_root"
        return f"invalid_mvs_parent:{kind}_under_{parent}"
    return None


def _operation_for_mvs_item(kind: str, node: dict[str, Any]) -> str:
    if kind != "primitive":
        return OPERATION_BY_KIND[kind]
    params = node.get("params", {}) if isinstance(node.get("params"), dict) else {}
    primitive_kind = str(params.get("kind") or node.get("kind") or "")
    if primitive_kind in {"distance_measurement", "angle_measurement"}:
        return "measurement_intent"
    if primitive_kind == "label":
        return "labeled"
    return "primitive_overlay"


def _record_mvs_camera(semantic: SemanticLayer, scene_id: str, item: WalkItem) -> None:
    scene = next((value for value in semantic.scenes if value.id == scene_id), None)
    if scene is None:
        return
    params = item.node.get("params", {}) if isinstance(item.node.get("params"), dict) else {}
    scene.camera["molviewspec"] = {
        "params": params,
        "json_pointer": item.pointer,
        "source_path": item.source_path,
        "status": "statically_recorded_not_rendered",
    }


def _resource_reference(
    artifact_id: str,
    item: WalkItem,
    inventory: MVSXInventory | None,
    scene_entry: str | None,
    artifact_path: str | None,
) -> ResourceReference | None:
    uri = _resource_uri(item.node)
    if not uri:
        return None
    uri_kind, archive_name = _uri_kind(uri, inventory, scene_entry)
    member_id = None
    if inventory and uri_kind == "archive_member":
        member = next(
            (member for member in inventory.members if member.normalized_name == archive_name),
            None,
        )
        member_id = member.member_id if member else None
    if uri_kind in {"archive_member", "data"}:
        fetch_status = "not_applicable"
        fixity_status = "available"
    else:
        fetch_status = "not_fetched"
        fixity_status = "unknown"
    base_uri = None
    if uri_kind == "relative":
        base_uri = artifact_path
    elif uri_kind in {"archive_member", "missing_archive_member"}:
        base_uri = scene_entry or "index.mvsj"
    return ResourceReference(
        resource_ref_id=_stable_id("resource", "molviewspec", artifact_id, item.pointer, uri),
        artifact_id=artifact_id,
        uri=uri,
        uri_kind=uri_kind,
        base_uri=base_uri,
        mvsx_member_id=member_id,
        fetch_status=fetch_status,
        fixity_status=fixity_status,
        source_location=_item_location(artifact_id, item),
    )


def _native_reference(artifact_id: str, item: WalkItem) -> NativeReference:
    expression = _native_expression(item)
    return NativeReference(
        native_ref_id=_stable_id("native-ref", "molviewspec", artifact_id, item.pointer, expression),
        source_location=_item_location(artifact_id, item),
        native_expression=expression,
        ref_type=f"mvs_{item.node.get('kind', 'unknown')}",
        stable_identity=None,
        identity_status="unresolved",
        claim_critical=ClaimCriticalStatus.unknown,
        review_status=ReviewStatus.needs_review,
        target_resolution_status=TargetResolutionStatus.expression_only,
    )


def _observed_operation(artifact_id: str, scene_id: str, item: WalkItem, kind: str) -> ObservedSceneOperation:
    operation = _operation_for_mvs_item(kind, item.node)
    target = _target_from_context(item)
    op_id = _stable_id("op", "molviewspec", artifact_id, item.pointer, kind, target, json.dumps(item.node, sort_keys=True))
    details = {
        "scene_id": scene_id,
        "kind": kind,
        "context": item.context,
        "params": item.node.get("params", {}) if isinstance(item.node.get("params"), dict) else {},
    }
    suggestion = suggest_visual_encoding(operation, target, details, item.node)
    return ObservedSceneOperation(
        operation_id=op_id,
        operation=operation,
        target=target,
        details=details,
        auto_annotation=suggestion.auto_annotation,
        candidate_meaning=suggestion.candidate_meaning,
        meaning_confidence=suggestion.meaning_confidence,
        meaning_basis=suggestion.meaning_basis,
        needs_author_confirmation=suggestion.needs_author_confirmation,
        source_location=_item_location(artifact_id, item),
        native_command=f"node:{kind}",
        native_value=item.node,
        support_status=SupportStatus.supported_shallow,
        extraction_confidence=ExtractionConfidence(
            level=ConfidenceValue.medium,
            score=0.68,
            basis=["mvs_node_kind_recognized", "json_pointer", "full_schema_not_validated"],
        ),
        review_status=ReviewStatus.auto_extracted,
        meaning_status=suggestion.meaning_status,
        target_resolution_status=TargetResolutionStatus.expression_only if target else TargetResolutionStatus.not_checked,
    )


def _raw_observation(
    artifact_id: str,
    location: SourceLocation,
    native_text: str,
    reason: str,
    scene_id: str,
) -> RawNativeObservation:
    return RawNativeObservation(
        raw_id=_stable_id("raw", "molviewspec", artifact_id, location.json_pointer or "", reason, native_text),
        artifact_id=artifact_id,
        source_location=location,
        native_text=native_text,
        reason=reason,
        support_status=SupportStatus.raw_unsupported,
        extraction_confidence=ExtractionConfidence(level=ConfidenceValue.low, score=0.2, basis=["mvs_raw_boundary"]),
        may_affect_scene_id=scene_id,
        claim_critical=ClaimCriticalStatus.unknown,
        review_status=ReviewStatus.needs_review,
    )


def _operation_fact(op: ObservedSceneOperation, item: WalkItem, index: int) -> ExtractedFact:
    return ExtractedFact(
        fact_id=f"fact-mvs-{index:04d}",
        tool="molviewspec",
        artifact_id=op.source_location.artifact_id or "",
        source_location=op.source_location.model_dump(mode="json", exclude_none=True),
        native_command=op.native_command or "",
        native_value=item.node,
        normalized_target={"operation_id": op.operation_id, "target": op.target},
        normalized_value={
            "operation": op.operation,
            "meaning_status": op.meaning_status.value,
            "auto_annotation": op.auto_annotation,
            "candidate_meaning": op.candidate_meaning,
            "needs_author_confirmation": op.needs_author_confirmation,
        },
        support_status=op.support_status.value,
        confidence=op.extraction_confidence.model_dump(mode="json", exclude_none=True),
        review_status=op.review_status.value,
    )


def _metadata_fact(artifact_id: str, item: WalkItem, index: int) -> ExtractedFact:
    kind = str(item.node.get("kind", "unknown"))
    confidence = ExtractionConfidence(
        level=ConfidenceValue.medium,
        score=0.68,
        basis=["mvs_node_kind_recognized", "full_schema_not_validated"],
    )
    return ExtractedFact(
        fact_id=f"fact-mvs-{index:04d}",
        tool="molviewspec",
        artifact_id=artifact_id,
        source_location=_item_location(artifact_id, item).model_dump(mode="json", exclude_none=True),
        native_command=f"node:{kind}",
        native_value=item.node,
        normalized_target={"object_type": f"molviewspec.{kind}", "json_pointer": item.pointer},
        normalized_value={"node_kind": kind, "context": item.context},
        support_status=SupportStatus.supported_shallow.value,
        confidence=confidence.model_dump(mode="json", exclude_none=True),
        review_status=ReviewStatus.auto_extracted.value,
    )


def _raw_fact(raw: RawNativeObservation, index: int) -> ExtractedFact:
    return ExtractedFact(
        fact_id=f"fact-mvs-{index:04d}",
        tool="molviewspec",
        artifact_id=raw.artifact_id,
        source_location=raw.source_location.model_dump(mode="json", exclude_none=True),
        native_command=raw.native_text,
        native_value={"raw": raw.native_text, "reason": raw.reason},
        normalized_target={"raw_id": raw.raw_id},
        normalized_value={"raw": True},
        support_status=raw.support_status.value,
        confidence=raw.extraction_confidence.model_dump(mode="json", exclude_none=True),
        review_status=raw.review_status.value,
    )


def _ensure_scene(semantic: SemanticLayer, artifact_id: str) -> str:
    if semantic.scenes:
        scene = semantic.scenes[0]
        if artifact_id not in scene.native_artifact_ids:
            scene.native_artifact_ids.append(artifact_id)
        return scene.id
    from claimtrace.models import Scene

    scene = Scene(
        id="scene:native:1",
        description="Scene statically extracted from native viewer artifact.",
        native_artifact_ids=[artifact_id],
        review_status=ReviewStatus.needs_review,
    )
    semantic.scenes.append(scene)
    return scene.id


def _completion_tasks_for_mvs(semantic: SemanticLayer) -> list[CompletionTask]:
    tasks: list[CompletionTask] = []
    visual_ops = [
        op
        for op in semantic.observed_scene_operations
        if op.meaning_status in {MeaningStatus.requires_user_completion, MeaningStatus.tool_suggested_meaning}
        or op.auto_annotation
        or op.candidate_meaning
    ]
    if visual_ops:
        tasks.append(
            CompletionTask(
                id="task:mvs-visual-encoding-meanings",
                section="scene",
                question="Review low-confidence or claim-critical MolViewSpec color, label, representation or annotation suggestions.",
                target_json_pointer="/visual_encoding_semantics",
                field_use="ClaimTrace already extracted the MolViewSpec scene operations and suggested conservative meanings; author review is needed only for figure-central or uncertain meanings.",
                examples=[f"{op.operation_id}: {op.candidate_meaning or 'mark presentation only'}" for op in visual_ops[:2]],
                accepted_values=["tool_suggested_meaning", "user_confirmed_meaning", "user_declared_no_scientific_meaning"],
                blocking=False,
            )
        )
    if semantic.resource_references:
        tasks.append(
            CompletionTask(
                id="task:mvs-resource-bindings",
                section="evidence",
                question="Which MolViewSpec resources should travel with the package, and which are just scene references?",
                target_json_pointer="/resource_references",
                field_use="This helps readers know which structures, maps or annotations they need to inspect.",
                examples=["resource:... include as figure data", "resource:... scene reference only"],
                accepted_values=["figure_central", "not_figure_central", "recorded_reason"],
                blocking=False,
            )
        )
    return tasks


def _normalize_member_name(name: str) -> str:
    if not name:
        raise SecurityError("MVSX archive member name is empty")
    if "\\" in name:
        raise SecurityError(f"MVSX archive member uses backslash path separators: {name}")
    if name.startswith("/") or name.startswith("//") or re.match(r"^[A-Za-z]:", name):
        raise SecurityError(f"MVSX archive member path is absolute or drive-qualified: {name}")
    normalized = posixpath.normpath(name)
    if normalized in {"", "."}:
        raise SecurityError(f"MVSX archive member path is empty after normalization: {name}")
    if normalized.startswith("../") or normalized == ".." or "/../" in f"/{normalized}/":
        raise SecurityError(f"MVSX archive member path escapes archive root: {name}")
    return normalized


def _check_collisions(normalized: str, is_dir: bool, dirs: set[str], files: set[str]) -> None:
    parts = normalized.rstrip("/").split("/")
    for index in range(1, len(parts)):
        prefix = "/".join(parts[:index])
        if prefix in files:
            raise SecurityError(f"MVSX archive has directory/file collision at {prefix}")
    if is_dir:
        if normalized in files:
            raise SecurityError(f"MVSX archive has file/directory collision at {normalized}")
        dirs.add(normalized.rstrip("/"))
    else:
        if normalized in dirs:
            raise SecurityError(f"MVSX archive has directory/file collision at {normalized}")
        files.add(normalized)


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == stat.S_IFLNK


def _compression_name(value: int) -> str:
    return {
        zipfile.ZIP_STORED: "stored",
        zipfile.ZIP_DEFLATED: "deflated",
    }.get(value, f"method:{value}")


def _media_type(name: str) -> str:
    media, _ = mimetypes.guess_type(name)
    return media or "application/octet-stream"


def _node_without_children(node: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in node.items() if key != "children"}


def _resource_uri(node: dict[str, Any]) -> str | None:
    params = node.get("params", {}) if isinstance(node.get("params"), dict) else {}
    value = params.get("url") or params.get("uri") or node.get("url") or node.get("uri")
    return str(value) if value else None


def _uri_kind(
    uri: str,
    inventory: MVSXInventory | None,
    scene_entry: str | None,
) -> tuple[str, str | None]:
    if uri.startswith(("http://", "https://", "ftp://")):
        return "remote", None
    if uri.startswith("file://"):
        return "file", None
    if uri.startswith("data:"):
        return "data", None
    if inventory:
        try:
            base = posixpath.dirname(scene_entry or "index.mvsj")
            normalized = _normalize_member_name(posixpath.join(base, uri))
        except SecurityError:
            return "unknown", None
        if any(member.normalized_name == normalized for member in inventory.members):
            return "archive_member", normalized
        return "missing_archive_member", normalized
    return "relative", None


def _mark_inventory_reference(inventory: MVSXInventory | None, resource: ResourceReference, pointer: str) -> None:
    if not inventory or not resource.mvsx_member_id:
        return
    for member in inventory.members:
        if member.member_id == resource.mvsx_member_id:
            member.referenced = True
            if pointer not in member.referenced_by_json_pointers:
                member.referenced_by_json_pointers.append(pointer)


def _native_expression(item: WalkItem) -> str:
    params = item.node.get("params", {}) if isinstance(item.node.get("params"), dict) else {}
    selector = params.get("selector") or item.node.get("selector") or params.get("field_values")
    if selector:
        return json.dumps(selector, sort_keys=True) if not isinstance(selector, str) else selector
    return item.pointer


def _target_from_context(item: WalkItem) -> str:
    params = item.node.get("params", {}) if isinstance(item.node.get("params"), dict) else {}
    value = (
        params.get("selector")
        or item.node.get("selector")
        or item.context.get("selector")
        or item.context.get("structure_pointer")
        or item.context.get("volume_pointer")
        or ""
    )
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"{prefix}:{digest}"
