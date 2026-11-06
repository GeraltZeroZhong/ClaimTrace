"""A loopback-only HTTP interface over the existing ClaimTrace package API.

Native scene files are inspected by the static importers, never executed. Reading
or validating an existing package does not change it.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import mimetypes
import re
import shutil
import tempfile
import threading
import webbrowser
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, quote, urlsplit
from uuid import uuid4

from PIL import Image, ImageDraw

from claimtrace import _simple_yaml
from claimtrace.api import ClaimTracePackage, init_package, load_package
from claimtrace.completion import (
    apply_answers,
    check_answers,
    dump_package_answer_template,
    ensure_scene_for_images,
)
from claimtrace.errors import ClaimTraceError, SecurityError
from claimtrace.constants import COMPLETION_TASKS_PATH, EXTRACTION_REPORT_PATH, EXPORT_MARKER_FILENAME
from claimtrace.export.directory import _copy_package
from claimtrace.importers.base import default_importers, detect_importer
from claimtrace.models.semantic_layer import (
    ArtifactKind,
    ArtifactRole,
    Claim,
    ClaimType,
    ConfidenceValue,
    Entity,
    Evidence,
    EvidenceKind,
    MeaningStatus,
    ProvenancedString,
    ReviewStatus,
    Scene,
    SourceType,
    SoftwareEnvironment,
    Uncertainty,
    VisualEncodingSemantics,
    utc_now,
)
from claimtrace.package.layout import append_extraction_report, read_completion_tasks, update_completion_tasks, write_completion_tasks
from claimtrace.package.paths import ensure_relative_path, resolve_package_path
from claimtrace.package.registry import destination_for, infer_role, replay_destination_for
from claimtrace.workflow import LIFECYCLE_LABELS, build_workflow


MAX_REQUEST_BYTES = 64 * 1024 * 1024
MAX_TEXT_PREVIEW_BYTES = 512 * 1024
NATIVE_SUFFIXES = {".pml", ".cxc", ".mvsj", ".mvsx"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".webp", ".svg"}
STATIC_FILES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/style.css": "style.css",
}


class RequestError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _required_text(data: dict[str, Any], key: str, *, limit: int = 20000) -> str:
    value = data.get(key)
    label = {
        "claim_text": "the claim",
        "figure_ref": "a figure or panel label",
        "method_name": "how this was checked",
        "result_summary": "what you found",
        "statement": "a limitation",
        "path": "the package folder",
        "name": "a filename",
        "text": "the answers",
    }.get(key, key.replace("_", " "))
    if not isinstance(value, str) or not value.strip() or value.strip().lower() == "unknown":
        raise RequestError(f"Enter {label}.")
    if len(value) > limit:
        raise RequestError(f"Keep {label} within {limit:,} characters.")
    return value.strip()


def _string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RequestError(f"{name} must be a list of IDs.")
    return list(dict.fromkeys(value))


def _draft_mode(data: dict[str, Any]) -> bool:
    value = data.get("save_draft", False)
    if not isinstance(value, bool):
        raise RequestError("Choose whether to save a draft.")
    return value


def _draft_text(data: dict[str, Any], key: str, *, limit: int = 20000) -> str:
    value = data.get(key, "")
    if not isinstance(value, str) or len(value) > limit:
        raise RequestError(f"Enter text within {limit:,} characters for {key.replace('_', ' ')}.")
    return value.strip() or "unknown"


def _reject_constant(value: str) -> None:
    raise RequestError(f"Use a finite number in place of {value}.")


def _deny_credential_path(path: str) -> None:
    parts = {part.lower() for part in Path(path).parts}
    protected = {
        ".ssh",
        ".aws",
        ".codex",
        ".azure",
        ".kube",
        ".env",
        "id_rsa",
        "id_ed25519",
        "auth.json",
        "credentials",
        "credentials.json",
    }
    if parts & protected:
        raise SecurityError("Choose a research file. Credential files are protected.")


def _decode_uploads(data: dict[str, Any], staging: Path) -> list[Path]:
    files = data.get("files")
    if not isinstance(files, list) or not files:
        raise RequestError("Choose at least one file to import.")
    if len(files) > 128:
        raise RequestError("Import at most 128 files at a time.")
    paths: list[Path] = []
    names: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise RequestError("Each file needs a name and base64 content.")
        name = ensure_relative_path(_required_text(item, "name", limit=1000))
        _deny_credential_path(name)
        if name.casefold() in names:
            raise RequestError(f"Choose each filename once: {name}")
        names.add(name.casefold())
        content = item.get("content")
        if not isinstance(content, str):
            raise RequestError(f"Choose {name} again to include its file contents.")
        try:
            payload = base64.b64decode(content, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise RequestError(f"Choose {name} again to upload its file contents.") from exc
        path = resolve_package_path(staging, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        paths.append(path)
    return paths


class Application:
    """One active package; all requests are serialized against this state."""

    def __init__(
        self, package: Path | None = None, workspace: Path | None = None, *, interface: str = "gui"
    ):
        if interface not in {"gui", "cli"}:
            raise ValueError("Choose the gui or cli authoring interface.")
        self.interface = interface
        self.lock = threading.RLock()
        self.workspace = (workspace or Path.cwd() / "claimtrace-workspace").resolve()
        self.package: ClaimTracePackage | None = None
        if package is not None:
            self.open(package)

    def open(self, root: Path) -> None:
        root = root.expanduser().resolve()
        # load_package is also used by trusted Python callers. The HTTP entry
        # point additionally enforces the validator's manifest path boundary.
        manifest = resolve_package_path(root, "semantic_layer.json")
        if not manifest.is_file() or manifest.stat().st_size > MAX_REQUEST_BYTES:
            raise RequestError("Choose a ClaimTrace folder containing semantic_layer.json.")
        package = load_package(root)
        self.package = package

    def require_package(self) -> ClaimTracePackage:
        if self.package is None:
            raise RequestError("Open a package or choose files to begin.", 409)
        # Honor edits made by the CLI or another local editor between requests.
        self.open(self.package.root)
        assert self.package is not None
        return self.package

    def check_package_context(self, expected: Any) -> None:
        """Reject a browser action whose displayed package is no longer active."""
        current = str(self.package.root) if self.package is not None else None
        if expected != current:
            raise RequestError(
                "The active package changed in another tab. Your entries have not been saved. "
                "Keep this form open and reopen its package in another tab, then retry; "
                "or close the form and refresh to use the current package.",
                409,
            )

    @contextmanager
    def edit_package(self) -> Iterator[str | None]:
        """Save edits to a received export in a verified working copy."""
        package = self.require_package()
        if not self.is_exported(package):
            yield None
            return
        report = package.validate(mode="draft")
        if report.overall_status == "fail":
            blockers = [item.message for item in report.findings
                        if item.status == "FAIL" and item.severity == "ERROR"
                        and "draft" in item.blocks_modes]
            raise RequestError(
                " ".join(blockers[:2]) + " Open the original download to create a working copy."
            )
        self.workspace.mkdir(parents=True, exist_ok=True)
        destination = self.workspace / f"{package.root.name}-working-{uuid4().hex[:8]}"
        destination.mkdir()
        try:
            _copy_package(package.root, destination)
            self.open(destination)
            yield str(package.root)
        except Exception:
            self.package = package
            shutil.rmtree(destination)
            raise

    @staticmethod
    def is_exported(package: ClaimTracePackage) -> bool:
        return (package.root / EXPORT_MARKER_FILENAME).exists() or (package.root / "checksums/sha256.txt").exists()

    def state(self) -> dict[str, Any]:
        if self.package is None:
            return {"root": None, "semantic": None, "report": None, "audit": None, "workflow": None}
        package = self.require_package()
        mode = package.semantic_layer.extensions.get("gui_lifecycle", "draft")
        if mode not in LIFECYCLE_LABELS:
            mode = "draft"
        report = package.validate(mode=mode)
        from claimtrace.gui.audit import build_audit
        from claimtrace.proposals import stored_proposals

        audit = build_audit(package.root, package.semantic_layer, report)
        return {
            "root": str(package.root),
            "is_exported": self.is_exported(package),
            "semantic": package.semantic_layer.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
            "audit": audit,
            "workflow": build_workflow(package.semantic_layer, report, audit),
            "proposals": stored_proposals(package.semantic_layer),
        }

    def proposals(self) -> list[dict[str, Any]]:
        from claimtrace.proposals import stored_proposals

        return stored_proposals(self.require_package().semantic_layer)

    def review_proposal(self, data: dict[str, Any]) -> None:
        from claimtrace.proposals import review_proposal

        review_proposal(
            self.require_package(), _required_text(data, "id"),
            decision=_required_text(data, "decision"),
            reviewer=_required_text(data, "reviewer"),
            note=str(data.get("note") or ""), changes=data.get("changes"),
        )

    def set_lifecycle(self, data: dict[str, Any]) -> None:
        mode = data.get("mode")
        if mode not in LIFECYCLE_LABELS:
            raise RequestError("Choose Working draft, Lab handoff, External review, or Archive.")
        package = self.require_package()
        package.semantic_layer.extensions["gui_lifecycle"] = mode
        package.save()

    def save_context(self, data: dict[str, Any]) -> None:
        """Record guided handoff context without exposing the full CAL document."""
        package = self.require_package()
        semantic = package.semantic_layer.model_copy(deep=True)
        timestamp = utc_now()
        changed: list[str] = []
        if "reuse" in data:
            value = data["reuse"]
            if not isinstance(value, dict):
                raise RequestError("Provide the reuse details as a record.")
            if "license" in value:
                semantic.reuse.license = _draft_text(value, "license", limit=2000)
            if "citation" in value:
                semantic.reuse.citation = _draft_text(value, "citation", limit=4000)
            if "restrictions" in value:
                semantic.reuse.restrictions = _string_list(value["restrictions"], "restrictions")
            semantic.reuse.reviewer = self.interface
            semantic.reuse.reviewed_at = timestamp
            changed.append("reuse")
        if "software" in data:
            value = data["software"]
            if not isinstance(value, dict):
                raise RequestError("Provide the software name and version as a record.")
            existing = next((item for item in semantic.software_environment if item.id == value.get("id")), None)
            if value.get("id") and existing is None:
                raise RequestError("Choose software from the current package.")
            software = SoftwareEnvironment(
                **{
                    **(existing.model_dump() if existing else {}),
                    "id": existing.id if existing else f"software:{self.interface}:{uuid4().hex[:12]}",
                    "name": _required_text({"software_name": value.get("name")}, "software_name", limit=500),
                    "version": _draft_text(value, "version", limit=500),
                    "command": value.get("command", existing.command if existing else None) or None,
                    "extensions": {**(existing.extensions if existing else {}), "source_type": "user_asserted", "reviewer": self.interface, "reviewed_at": timestamp},
                }
            )
            if existing:
                semantic.software_environment[semantic.software_environment.index(existing)] = software
            else:
                semantic.software_environment.append(software)
            changed.append(software.id)
        if "scene" in data:
            value = data["scene"]
            if not isinstance(value, dict):
                raise RequestError("Choose a scene and its view details.")
            scene = next((item for item in semantic.scenes if item.id == value.get("id")), None)
            if scene is None:
                raise RequestError("Choose a scene from the current package.")
            if "view_kind" in value:
                kind = value["view_kind"]
                if kind not in {"molecular", "plot", "figure_assembly"}:
                    raise RequestError("Choose Molecular view, Analysis plot, or Figure assembly.")
                if kind != "molecular" and scene.native_artifact_ids:
                    raise RequestError("Use a figure image for a plot or figure assembly.")
                scene.extensions["view_kind"] = kind
            if "camera_context" in value:
                context = _draft_text(value, "camera_context", limit=4000)
                if context == "unknown":
                    scene.camera.pop("author_context", None)
                    scene.extensions.pop("gui_camera_context", None)
                else:
                    scene.camera["author_context"] = context
                    scene.extensions["gui_camera_context"] = {"source_type": "user_asserted", "reviewer": self.interface, "reviewed_at": timestamp}
            visibility = value.get("visibility", [])
            if not isinstance(visibility, list):
                raise RequestError("Provide the hidden scene details as a list.")
            for row in visibility:
                index = row.get("index") if isinstance(row, dict) else None
                if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(scene.visibility):
                    raise RequestError("Choose a visibility record from this scene.")
                reason = _draft_text(row, "reason", limit=4000)
                scene.visibility[index].reason = reason
                scene.visibility[index].review_status = (
                    ReviewStatus.needs_review if reason == "unknown" else ReviewStatus.confirmed
                )
            changed.append(scene.id)
        reviews = data.get("raw_reviews", [])
        if not isinstance(reviews, list):
            raise RequestError("Provide source review decisions as a list.")
        raw_by_id = {item.raw_id: item for item in semantic.raw_native_observations}
        for value in reviews:
            if not isinstance(value, dict) or value.get("raw_id") not in raw_by_id:
                raise RequestError("Choose preserved source content from this package.")
            resolution = value.get("resolution")
            if resolution not in {"reviewed_no_claim_impact", "no_scene_effect", "not_applicable"}:
                raise RequestError("Choose a source review decision.")
            reason = _required_text(value, "reason", limit=4000)
            raw = raw_by_id[value["raw_id"]]
            raw.resolution = resolution
            raw.review_status = ReviewStatus.confirmed
            semantic.add_activity(f"{self.interface}_review_source", reason, generated_ids=[raw.raw_id], resolution=resolution, reviewer=self.interface)
            changed.append(raw.raw_id)
        if not changed:
            raise RequestError("Add the context you want to save.")
        semantic.add_activity(
            f"{self.interface}_record_context", "Recorded author context for scene inspection and handoff.",
            generated_ids=[item for item in changed if item != "reuse"],
            updated_sections=["reuse"] if "reuse" in changed else [],
        )
        package.semantic_layer = semantic
        package.save()

    def export_zip(self, data: dict[str, Any]) -> tuple[bytes, str]:
        package = self.require_package()
        mode = data.get("mode", package.semantic_layer.extensions.get("gui_lifecycle", "draft"))
        if mode not in LIFECYCLE_LABELS:
            raise RequestError("Choose Working draft, Lab handoff, External review, or Archive.")
        slug = re.sub(r"[^a-z0-9]+", "-", package.semantic_layer.package.title.lower()).strip("-")[:60] or "claimtrace"
        filename = f"{slug}-{mode}.zip"
        with tempfile.TemporaryDirectory(prefix="claimtrace-download-") as directory:
            path = package.export(Path(directory) / filename, mode=mode, zip_output=True)
            return path.read_bytes(), filename

    def import_files(self, data: dict[str, Any]) -> None:
        title = str(data.get("title") or "Untitled figure")[:1000]
        output = data.get("out")
        if output is not None and not isinstance(output, str):
            raise RequestError("Enter a local folder path for the package.")
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "figure"
        root = (
            Path(output).expanduser().resolve()
            if output
            else self.workspace / f"{slug}-{uuid4().hex[:8]}"
        )
        with tempfile.TemporaryDirectory(prefix="claimtrace-upload-") as directory:
            paths = _decode_uploads(data, Path(directory))
            natives = [path for path in paths if path.suffix.lower() in NATIVE_SUFFIXES]
            images = [path for path in paths if path.suffix.lower() in IMAGE_SUFFIXES]
            artifacts = [path for path in paths if path not in natives and path not in images]
            package = init_package(
                native=natives, image=images, artifacts=artifacts, out=root, title=title
            )
        self.package = package

    def save_claim(self, data: dict[str, Any]) -> None:
        package = self.require_package()
        semantic = package.semantic_layer
        draft = _draft_mode(data)
        text = _draft_text(data, "claim_text") if draft else _required_text(data, "claim_text")
        existing = None
        if data.get("id"):
            existing = next((claim for claim in semantic.claims if claim.id == data["id"]), None)
            if existing is None:
                raise RequestError("Refresh the package and select a claim.", 404)
        scene_ids = _string_list(
            data.get("scene_ids", existing.scene_ids if existing else []), "scene_ids"
        )
        known = {scene.id for scene in semantic.scenes}
        if not set(scene_ids) <= known:
            raise RequestError("Choose scenes from the current package.")
        if not scene_ids and not draft:
            raise RequestError("Link the claim to at least one scene.")
        claim_type = ClaimType(
            data.get("claim_type", existing.claim_type if existing else "unknown")
        )
        figure_ref = (_draft_text if draft else _required_text)(data, "figure_ref", limit=500)
        review_status = ReviewStatus.needs_review if draft else ReviewStatus.confirmed
        provenance = ProvenancedString(
            value=text,
            source_type=SourceType.user_asserted,
            confidence=ConfidenceValue.unknown,
            review_status=review_status,
            reviewer=self.interface,
            reviewed_at=None if draft else utc_now(),
        )
        if existing:
            existing.claim_text = provenance
            existing.claim_type = claim_type
            existing.figure_ref = figure_ref
            existing.scene_ids = scene_ids
            existing.review_status = review_status
            existing.claim_status = "draft" if draft else "reviewable"
            claim = existing
        else:
            claim = Claim(
                id=f"claim:{self.interface}:{uuid4().hex[:12]}",
                claim_text=provenance,
                claim_type=claim_type,
                figure_ref=figure_ref,
                scene_ids=scene_ids,
                scope="panel",
                claim_status="draft" if draft else "reviewable",
                review_status=review_status,
            )
            semantic.claims.append(claim)
        semantic.add_activity(
            f"{self.interface}_edit_claim" if existing else f"{self.interface}_add_claim",
            f"Saved author assertion {claim.id}.",
            generated_ids=[claim.id],
        )
        package.save()

    def save_evidence(self, data: dict[str, Any]) -> None:
        package = self.require_package()
        semantic = package.semantic_layer
        claim = next((item for item in semantic.claims if item.id == data.get("claim_id")), None)
        if claim is None:
            raise RequestError("Choose a claim before adding evidence.")
        source_ids = _string_list(data.get("source_artifact_ids", []), "source_artifact_ids")
        if not set(source_ids) <= {item.id for item in semantic.artifacts}:
            raise RequestError("Choose source files from this package or upload new files.")
        draft = _draft_mode(data)
        method = (_draft_text if draft else _required_text)(data, "method_name", limit=1000)
        result = (_draft_text if draft else _required_text)(data, "result_summary")
        maps = {}
        for field in ("thresholds", "units", "parameters"):
            value = data.get(field, {})
            if not isinstance(value, dict):
                raise RequestError(f"{field} must be a JSON object.")
            maps[field] = value
        existing = next((item for item in semantic.evidence if item.id == data.get("id")), None)
        if data.get("id") and (
            existing is None
            or claim.id not in existing.claim_ids
            and existing.id not in claim.evidence_ids
        ):
            raise RequestError("Choose evidence linked to this claim.")
        targets = {}
        for field, known in (
            ("target_selection_ids", {item.id for item in semantic.selections}),
            ("target_entity_ids", {item.id for item in semantic.entities}),
        ):
            values = _string_list(
                data.get(field, getattr(existing, field) if existing else []), field
            )
            if not set(values) <= known:
                raise RequestError("Choose molecules or regions saved in this package.")
            targets[field] = values
        evidence = Evidence(
            **{
                **(existing.model_dump() if existing else {}),
                "id": existing.id if existing else f"evidence:{self.interface}:{uuid4().hex[:12]}",
                "claim_ids": list(dict.fromkeys(existing.claim_ids + [claim.id]))
                if existing
                else [claim.id],
                "evidence_kind": EvidenceKind(data.get("evidence_kind", "manual_rationale")),
                "method_name": method,
                "result_summary": result,
                "source_artifact_ids": source_ids,
                **targets,
                "review_status": ReviewStatus.needs_review if draft else ReviewStatus.confirmed,
                "reviewer": self.interface,
                "reviewed_at": None if draft else utc_now(),
                "generated_by": f"author via ClaimTrace {self.interface.upper()}",
                **maps,
            }
        )
        fallback_role = {
            EvidenceKind.contact_table: "contact_table",
            EvidenceKind.external_validation: "validation_report",
        }.get(evidence.evidence_kind, "evidence_document")
        with self._upload_transaction(
            package, data, optional=True, fallback_role=fallback_role
        ) as uploaded_ids:
            source_ids = list(dict.fromkeys(source_ids + uploaded_ids))
            evidence.source_artifact_ids = source_ids
            classified = []
            for artifact in semantic.artifacts:
                if artifact.id in source_ids and artifact.role == ArtifactRole.generic:
                    artifact.role = ArtifactRole(fallback_role)
                    classified.append(artifact.id)
            activity = semantic.add_activity(
                f"{self.interface}_edit_evidence" if existing else f"{self.interface}_add_evidence",
                f"Saved evidence {evidence.id}.",
                used_artifact_ids=source_ids,
                generated_ids=[evidence.id],
                classified_source_ids=classified,
                source_role=fallback_role,
            )
            evidence.provenance_id = activity.id
            if existing:
                semantic.evidence[semantic.evidence.index(existing)] = evidence
            else:
                semantic.evidence.append(evidence)
            if evidence.id not in claim.evidence_ids:
                claim.evidence_ids.append(evidence.id)
            package.save()

    def save_uncertainty(self, data: dict[str, Any]) -> None:
        package = self.require_package()
        semantic = package.semantic_layer
        claim = next((item for item in semantic.claims if item.id == data.get("claim_id")), None)
        if claim is None:
            raise RequestError("Choose a claim before adding a limitation.")
        existing = next((item for item in semantic.uncertainty if item.id == data.get("id")), None)
        if data.get("id") and (
            existing is None
            or claim.id not in existing.claim_ids
            and existing.id not in claim.uncertainty_ids
        ):
            raise RequestError("Choose a limitation linked to this claim.")
        uncertainty = Uncertainty(
            **{
                **(existing.model_dump() if existing else {}),
                "id": existing.id if existing else f"uncertainty:{self.interface}:{uuid4().hex[:12]}",
                "claim_ids": list(dict.fromkeys(existing.claim_ids + [claim.id]))
                if existing
                else [claim.id],
                "statement": _required_text(data, "statement"),
                "category": str(data.get("category") or "general"),
                "review_status": ReviewStatus.confirmed,
                "reviewer": self.interface,
                "reviewed_at": utc_now(),
            }
        )
        if existing:
            semantic.uncertainty[semantic.uncertainty.index(existing)] = uncertainty
        else:
            semantic.uncertainty.append(uncertainty)
        if uncertainty.id not in claim.uncertainty_ids:
            claim.uncertainty_ids.append(uncertainty.id)
        semantic.add_activity(
            f"{self.interface}_record_uncertainty",
            f"Recorded author limitation {uncertainty.id}.",
            generated_ids=[uncertainty.id],
        )
        package.save()

    def save_identities(self, data: dict[str, Any]) -> None:
        """Record author-supplied identities and visual meanings for one claim."""
        from claimtrace.gui.audit import build_audit

        package = self.require_package()
        semantic = package.semantic_layer
        claim = next((item for item in semantic.claims if item.id == data.get("claim_id")), None)
        if claim is None:
            raise RequestError("Choose a claim before describing its scene labels.")
        identities = data.get("identities", [])
        meanings = data.get("visual_meanings", [])
        if not isinstance(identities, list) or not isinstance(meanings, list):
            raise RequestError("Provide a list of scene labels and visual meanings.")
        if not identities and not meanings:
            raise RequestError("Describe a selection or visual meaning before saving.")
        scenes = [item for item in semantic.scenes if item.id in claim.scene_ids]
        selection_ids = {sid for scene in scenes for sid in scene.selection_ids}
        selections = {item.id: item for item in semantic.selections if item.id in selection_ids}
        structure_ids = {
            item.id for item in semantic.artifacts if item.role == ArtifactRole.structure
        }
        audit = build_audit(package.root, semantic, package.validate(mode="archive"))
        claim_audit = next(item for item in audit["claims"] if item["id"] == claim.id)
        operation_ids = set(claim_audit["operation_ids"])
        operations = {
            item.operation_id: item
            for item in semantic.observed_scene_operations
            if item.operation_id in operation_ids
        }

        def concrete_text(row: dict[str, Any], key: str, label: str) -> str:
            value = _required_text(row, key, limit=2000)
            if value.lower() in {
                "none",
                "null",
                "n/a",
                "na",
                "unspecified",
            } or value.lower().startswith(("todo", "tbd")):
                raise RequestError(f"Enter {label} in your own words.")
            return value

        # Validate the complete submission before changing any semantic record.
        prepared_identities = []
        seen_selections = set()
        for row in identities:
            if not isinstance(row, dict) or row.get("selection_id") not in selections:
                raise RequestError("Choose a selection from this claim's scene.")
            selection = selections[row["selection_id"]]
            if selection.id in seen_selections:
                raise RequestError("Describe each selection once.")
            seen_selections.add(selection.id)
            entity_type = row.get("entity_type")
            if entity_type not in {"ligand", "residue", "model", "other"}:
                raise RequestError("Choose ligand, residue, model, or other for the selection.")
            label = concrete_text(row, "label", "the molecule or residue identity")
            sources = _string_list(row.get("source_artifact_ids", []), "source_artifact_ids")
            if not sources or not set(sources) <= structure_ids:
                raise RequestError("Choose the structure file containing this selection.")
            prepared_identities.append((selection, entity_type, label, sources))
        prepared_meanings = []
        seen_operations = set()
        for row in meanings:
            if not isinstance(row, dict) or row.get("operation_id") not in operations:
                raise RequestError("Choose a color, label, or representation from this claim's scene.")
            operation = operations[row["operation_id"]]
            if operation.operation not in {"colored", "labeled", "represented", "displayed"}:
                raise RequestError("Choose a color, label, or representation to describe.")
            if operation.operation_id in seen_operations:
                raise RequestError("Describe each color, label, or representation once.")
            seen_operations.add(operation.operation_id)
            presentation_only = row.get("presentation_only", False)
            if not isinstance(presentation_only, bool):
                raise RequestError("Choose whether this visual cue is used for display styling.")
            meaning = concrete_text(row, "meaning", "the meaning of this color, label, or representation")
            prepared_meanings.append((operation, meaning, presentation_only))

        timestamp = utc_now()
        generated_ids = []
        used_artifact_ids = set()
        for selection, entity_type, label, sources in prepared_identities:
            marker = {"claim_id": claim.id, "selection_id": selection.id}
            entity = next(
                (
                    item
                    for item in semantic.entities
                    if item.extensions.get("gui_identity") == marker
                ),
                None,
            )
            native_ids = (
                [selection.source_artifact_id]
                if selection.source_artifact_id
                else [
                    aid
                    for scene in scenes
                    if selection.id in scene.selection_ids
                    for aid in scene.native_artifact_ids
                ]
            )
            source_ids = list(dict.fromkeys(sources + native_ids))
            native_paths = [
                item.path or item.id for item in semantic.artifacts if item.id in native_ids
            ]
            values = {
                "entity_type": entity_type,
                "label": label,
                "stable_identity": f"{' / '.join(native_paths) or selection.id} | {selection.native_selector.value} | {label}",
                "source_artifact_ids": source_ids,
                "review_status": ReviewStatus.confirmed,
                "extensions": {
                    **(entity.extensions if entity else {}),
                    "gui_identity": marker,
                    "source_type": SourceType.user_asserted.value,
                    "reviewer": self.interface,
                    "reviewed_at": timestamp,
                },
            }
            if entity is None:
                entity = Entity(id=f"entity:{self.interface}:{uuid4().hex[:12]}", **values)
                semantic.entities.append(entity)
            else:
                for key, value in values.items():
                    setattr(entity, key, value)
            if entity.id not in selection.entity_ids:
                selection.entity_ids.append(entity.id)
            selection.review_status = ReviewStatus.confirmed
            for scene in scenes:
                if selection.id in scene.selection_ids and entity.id not in scene.entity_ids:
                    scene.entity_ids.append(entity.id)
            for evidence in semantic.evidence:
                if (
                    (claim.id in evidence.claim_ids or evidence.id in claim.evidence_ids)
                    and selection.id in evidence.target_selection_ids
                    and entity.id not in evidence.target_entity_ids
                ):
                    evidence.target_entity_ids.append(entity.id)
            generated_ids.append(entity.id)
            used_artifact_ids.update(source_ids)
        for operation, meaning, presentation_only in prepared_meanings:
            remaining_meanings = []
            for item in semantic.visual_encoding_semantics:
                if operation.operation_id not in item.operation_ids:
                    remaining_meanings.append(item)
                    continue
                remaining_ids = [oid for oid in item.operation_ids if oid != operation.operation_id]
                if remaining_ids:
                    remaining_meanings.append(
                        item.model_copy(update={"operation_ids": remaining_ids})
                    )
            semantic.visual_encoding_semantics = remaining_meanings
            status = (
                MeaningStatus.user_declared_no_scientific_meaning
                if presentation_only
                else MeaningStatus.user_confirmed_meaning
            )
            semantic.visual_encoding_semantics.append(
                VisualEncodingSemantics(
                    operation_ids=[operation.operation_id],
                    encoding_type={"colored": "color", "labeled": "label"}.get(
                        operation.operation, "representation"
                    ),
                    meaning_status=status,
                    meaning=None if presentation_only else meaning,
                    no_scientific_meaning_reason=meaning if presentation_only else None,
                    reviewer=self.interface,
                    reviewed_at=timestamp,
                )
            )
            operation.review_status = ReviewStatus.confirmed
            operation.meaning_status = status
            operation.needs_author_confirmation = False
            generated_ids.append(operation.operation_id)
            if operation.source_location.artifact_id:
                used_artifact_ids.add(operation.source_location.artifact_id)
        semantic.add_activity(
            f"{self.interface}_describe_scene_labels",
            f"Recorded author identities and visual meanings for {claim.id}.",
            used_artifact_ids=sorted(used_artifact_ids),
            generated_ids=generated_ids,
        )
        package.save()

    def attach(self, data: dict[str, Any]) -> None:
        package = self.require_package()
        role = data.get("role") or None
        if role is not None:
            ArtifactRole(role)
        scene_id = data.get("scene_id") or None
        new_scene = data.get("new_scene", False)
        if not isinstance(new_scene, bool) or new_scene and (scene_id or role != "render_image"):
            raise RequestError("Choose a new figure scene or an existing scene for these images.")
        if scene_id and scene_id not in {scene.id for scene in package.semantic_layer.scenes}:
            raise RequestError("Choose a scene from the current package.")
        claim = next((item for item in package.semantic_layer.claims if item.id == data.get("claim_id")), None)
        if data.get("claim_id") and (claim is None or role != "render_image"):
            raise RequestError("Choose the claim for this figure.")
        image_ids = _string_list(data.get("artifact_ids", []), "artifact_ids")
        if image_ids:
            known_images = {
                item.id for item in package.semantic_layer.artifacts
                if item.role == ArtifactRole.render_image
            }
            if role != "render_image" or not set(image_ids) <= known_images:
                raise RequestError("Choose figure images from this package.")
            if not scene_id and not new_scene and len(package.semantic_layer.scenes) > 1:
                raise RequestError("Choose the scene for these images.")
        created_scene = Scene(
            id=f"scene:{self.interface}:{uuid4().hex[:12]}",
            description="Static image scene requiring author completion.",
            review_status=ReviewStatus.needs_review,
        ) if new_scene else None
        if created_scene is not None:
            scene_id = created_scene.id
        with self._upload_transaction(
            package, data, role=role, scene_id=scene_id, optional=bool(image_ids),
            created_scene=created_scene,
        ) as uploaded_ids:
            if image_ids:
                ensure_scene_for_images(package.semantic_layer, image_ids, scene_id=scene_id)
                package.semantic_layer.add_activity(
                    f"{self.interface}_link_figure", "Linked existing figure images to the selected scene.",
                    used_artifact_ids=image_ids,
                )
                package.save()
            if claim is not None:
                figures = set(image_ids + uploaded_ids)
                linked = [scene.id for scene in package.semantic_layer.scenes
                          if figures.intersection(scene.render_artifact_ids)]
                claim.scene_ids = list(dict.fromkeys(claim.scene_ids + linked))
                package.save()

    def _import_attached_scene(
        self, package: ClaimTracePackage, artifact: Any, scene_id: str | None
    ) -> None:
        """Import a later native scene, optionally completing an image-only scene."""
        semantic = package.semantic_layer
        if any(artifact.id in scene.native_artifact_ids for scene in semantic.scenes):
            return
        target = next((scene for scene in semantic.scenes if scene.id == scene_id), None)
        if target and target.native_artifact_ids:
            raise RequestError("Add this native file as a new scene, then choose its claim links.")
        previous = {scene.id for scene in semantic.scenes}
        path = resolve_package_path(package.root, artifact.path)
        importer = detect_importer(path, default_importers(include_experimental=False))
        result = importer.import_into(path, artifact.id, semantic)
        imported = [scene for scene in semantic.scenes if scene.id not in previous]
        if target:
            if len(imported) != 1:
                raise RequestError("Import these snapshots as new scenes, then link the relevant scene to the claim.")
            scene = imported[0]
            old_id = scene.id
            scene.id = target.id
            scene.render_artifact_ids = list(dict.fromkeys(target.render_artifact_ids + scene.render_artifact_ids))
            scene.entity_ids = list(dict.fromkeys(target.entity_ids + scene.entity_ids))
            scene.selection_ids = list(dict.fromkeys(target.selection_ids + scene.selection_ids))
            scene.extensions = {**target.extensions, **scene.extensions}
            if not scene.camera:
                scene.camera = target.camera
            semantic.scenes = [scene if item is target else item for item in semantic.scenes if item is not scene]
            for operation in semantic.observed_scene_operations:
                if operation.details.get("scene_id") == old_id:
                    operation.details["scene_id"] = scene.id
            for observation in semantic.raw_native_observations:
                if observation.may_affect_scene_id == old_id:
                    observation.may_affect_scene_id = scene.id
        append_extraction_report(package.root, result.importer_name, result.fact_dicts())
        existing_tasks = read_completion_tasks(package.root)
        existing_ids = {task.id for task in existing_tasks}
        write_completion_tasks(package.root, existing_tasks + [task for task in result.tasks if task.id not in existing_ids])
        semantic.add_activity(
            "static_import",
            f"Imported {artifact.path} with {result.importer_name}.",
            used_artifact_ids=[artifact.id],
            importer=result.importer_name,
            warnings=result.warnings,
        )
        package.save()

    @contextmanager
    def _upload_transaction(
        self,
        package: ClaimTracePackage,
        data: dict[str, Any],
        *,
        role: str | None = None,
        scene_id: str | None = None,
        fallback_role: str | None = None,
        optional: bool = False,
        created_scene: Scene | None = None,
    ) -> Iterator[list[str]]:
        """Keep uploaded files and their related edits in one recoverable save."""
        with tempfile.TemporaryDirectory(prefix="claimtrace-attach-") as directory:
            paths = (
                []
                if optional and ("files" not in data or data["files"] == [])
                else _decode_uploads(data, Path(directory))
            )
            originals = {
                resolve_package_path(package.root, relative): (
                    resolve_package_path(package.root, relative).read_bytes()
                    if resolve_package_path(package.root, relative).exists() else None
                )
                for relative in ("semantic_layer.json", COMPLETION_TASKS_PATH, EXTRACTION_REPORT_PATH)
            }
            new_targets: set[Path] = set()
            artifact_ids: list[str] = []
            try:
                if created_scene is not None:
                    package.semantic_layer.scenes.append(created_scene)
                # Parse native resource references before registering their files.
                for path in sorted(paths, key=lambda item: item.suffix.lower() not in NATIVE_SUFFIXES):
                    inferred = infer_role(path, role)
                    if inferred == ArtifactRole.generic and fallback_role:
                        inferred = ArtifactRole(fallback_role)
                    relative = replay_destination_for(package.semantic_layer, path)
                    target = resolve_package_path(
                        package.root, relative or destination_for(inferred, path)
                    )
                    if not target.exists():
                        new_targets.add(target)
                    artifact = package.add_artifact(
                        path, role=inferred,
                        scene_id=scene_id if inferred == ArtifactRole.render_image else None,
                    )
                    if path.suffix.lower() in NATIVE_SUFFIXES:
                        self._import_attached_scene(package, artifact, scene_id)
                    artifact_ids.append(artifact.id)
                yield artifact_ids
            except Exception:
                # Registration refuses to replace existing, different payloads.
                # Roll back only files this request created and the manifest.
                for target in new_targets:
                    if target.is_file() and not target.is_symlink():
                        target.unlink()
                for path, original in originals.items():
                    if original is None:
                        path.unlink(missing_ok=True)
                    else:
                        path.write_bytes(original)
                self.package = load_package(package.root)
                raise

    def answers_text(self, *, source: str = "current") -> str:
        package = self.require_package()
        path = resolve_package_path(package.root, "answers.yml")
        saved_text = None
        if path.exists():
            if not path.is_file() or path.stat().st_size > MAX_REQUEST_BYTES:
                raise RequestError("answers.yml must be a regular text file below 64 MiB.")
            saved_text = path.read_text(encoding="utf-8")
        if source == "saved":
            if saved_text is None:
                raise RequestError("Save the answers to create answers.yml.", 404)
            return saved_text
        if source != "current":
            raise RequestError("Choose current or saved answers.")
        semantic = package.semantic_layer
        template = dump_package_answer_template(semantic, semantic.package.profile)
        answers = _simple_yaml.loads(template)
        saved = {}
        if saved_text is not None:
            try:
                parsed = _simple_yaml.loads(saved_text)
                saved = parsed if isinstance(parsed, dict) else {}
            except ValueError:
                # The original remains available verbatim through source=saved.
                # A broken draft must not hide the current package records.
                pass
        # Saved answers remain a separate document. Current records own every
        # editable value; retain only supplemental notes beside matching records.
        sections = {
            "package", "claim", "claims", "evidence", "uncertainty", "artifacts",
            "entities", "selections", "scene", "scenes", "reuse", "software",
            "answer_schema", "native_identity_mappings", "scene_semantics_by_operation",
            "raw_resolutions", "resource_bindings", "evidence_bindings", "waivers",
        }
        for key, value in saved.items():
            if key not in sections:
                answers.setdefault(key, value)

        def record_key(item: Any) -> tuple[Any, ...] | None:
            if not isinstance(item, dict):
                return None
            for key in ("id", "native_ref_id", "raw_id", "resource_ref_id", "binding_id"):
                if isinstance(item.get(key), str) and item[key]:
                    return (key, item[key])
            for key in ("scene_ids", "operation_ids"):
                if isinstance(item.get(key), list) and item[key] and all(
                    isinstance(value, str) for value in item[key]
                ):
                    return (key, *item[key])
            return None

        def with_notes(current: dict[str, Any], previous: Any) -> dict[str, Any]:
            notes = dict(previous) if isinstance(previous, dict) else {}
            # These input aliases attach files. Replaying an older alias could
            # restore a source deliberately removed in a guided form.
            # An omitted operation setting also leaves its current value intact.
            for key in {
                "source_artifact_paths", "source_artifact_roles", "claim_critical",
                *VisualEncodingSemantics.model_fields,
            }:
                notes.pop(key, None)
            return {**notes, **current}

        for section, current in list(answers.items()):
            if section not in sections:
                continue
            previous = saved.get(section)
            if isinstance(current, dict):
                answers[section] = with_notes(current, previous)
            elif isinstance(current, list):
                old_records = previous if isinstance(previous, list) else []
                by_key = {
                    record_key(item): item for item in old_records if record_key(item) is not None
                }
                answers[section] = [
                    with_notes(item, by_key.get(record_key(item)))
                    if isinstance(item, dict) else item
                    for item in current
                ]
        header = template[: template.find("package:")]
        return header + _simple_yaml.dumps(answers)

    def save_answers(self, data: dict[str, Any]) -> None:
        package = self.require_package()
        text = _required_text(data, "text", limit=MAX_REQUEST_BYTES)
        answers = _simple_yaml.loads(text)
        if not isinstance(answers, dict):
            raise RequestError("Answers must contain a YAML mapping at the top level.")
        problems = check_answers(
            answers, package.semantic_layer, root=package.root, answer_base=package.root
        )
        if problems:
            raise RequestError(
                "Update answers.yml:\n" + "\n".join(f"- {problem}" for problem in problems)
            )
        for item in answers.get("artifacts", []):
            if isinstance(item, dict) and item.get("path"):
                _deny_credential_path(str(item["path"]))
        for item in answers.get("evidence", []):
            if isinstance(item, dict):
                for path in item.get("source_artifact_paths", []):
                    _deny_credential_path(str(path))
        # Check the output path before applying any author changes.
        output = resolve_package_path(package.root, "answers.yml")
        apply_answers(package.root, package.semantic_layer, answers, answer_base=package.root)
        package.save()
        update_completion_tasks(package.root, package.semantic_layer, answers)
        output.write_text(text + ("" if text.endswith("\n") else "\n"), encoding="utf-8")

    def demo(self) -> None:
        """Create an explicitly synthetic example; no scientific evidence is invented."""
        with tempfile.TemporaryDirectory(prefix="claimtrace-demo-") as directory:
            source = Path(directory)
            (source / "demo.pml").write_text(
                "# SYNTHETIC teaching fixture with illustrative coordinates.\n"
                "load synthetic.pdb, demo\nselect ligand, resn LIG\n"
                "select site, chain A and resi 42+85+117\nshow sticks, ligand or site\n"
                "color orange, ligand\ncolor teal, site\n"
                "distance contacts, ligand, site\nzoom ligand or site\n",
                encoding="utf-8",
            )
            (source / "synthetic.pdb").write_text(
                "HEADER    SYNTHETIC TEACHING FIXTURE - ILLUSTRATIVE COORDINATES\n"
                "ATOM      1  CA  ASP A  42       0.000   0.000   0.000  1.00 20.00           C\n"
                "ATOM      2  CA  SER A  85       5.000   0.000   0.000  1.00 20.00           C\n"
                "ATOM      3  CA  TYR A 117       2.500   4.000   0.000  1.00 20.00           C\n"
                "HETATM    4  C1  LIG B   1       2.500   1.500   0.000  1.00 20.00           C\nEND\n",
                encoding="utf-8",
            )
            canvas = Image.new("RGB", (960, 600), "#f8f7f3")
            draw = ImageDraw.Draw(canvas)
            draw.text(
                (32, 24),
                "SYNTHETIC TEACHING DIAGRAM",
                fill="#4e5b59",
            )
            draw.text(
                (32, 48),
                "Illustrative coordinates and contacts",
                fill="#707b78",
            )
            nodes = [(250, 225, "A / ASP 42"), (695, 230, "A / SER 85"), (475, 450, "A / TYR 117")]
            for x, y, label in nodes:
                draw.line((480, 285, x, y), fill="#c8ceca", width=2)
                draw.ellipse((x - 24, y - 24, x + 24, y + 24), fill="#32766e")
                draw.text((x - 45, y + 38), label, fill="#3e504a")
            draw.ellipse((438, 243, 522, 327), fill="#ca934a")
            draw.text((462, 280), "LIG", fill="#ffffff")
            draw.text(
                (32, 560),
                "Audit exercise: add the contact cutoff, evidence and limitations.",
                fill="#707b78",
            )
            canvas.save(source / "synthetic-panel.png")
            root = self.workspace / f"synthetic-demo-{uuid4().hex[:8]}"
            package = init_package(
                native=source / "demo.pml",
                image=source / "synthetic-panel.png",
                artifacts=[source / "synthetic.pdb"],
                out=root,
                title="Ligand pose · teaching example",
            )
        package.semantic_layer.extensions["gui_demo"] = True
        package.semantic_layer.extensions["demo_notice"] = (
            "Synthetic teaching example with illustrative coordinates and contacts."
        )
        package.add_claim(
            "The ligand pose is supported by contacts with the highlighted binding-site residues.",
            claim_type="ligand_binding_pose",
            figure_ref="Synthetic panel A",
        )
        selection_claim = package.add_claim(
            "The highlighted residues define the ligand-contacting selection used in this view.",
            claim_type="selection_highlight",
            figure_ref="Synthetic panel A",
        )
        # The importer records a command's measurement intent, not an observed
        # distance. Linking that incomplete record demonstrates the cutoff gap.
        for evidence in package.semantic_layer.evidence:
            evidence.claim_ids = [selection_claim.id]
            selection_claim.evidence_ids.append(evidence.id)
        package.save()
        self.package = package

    def example(self, data: dict[str, Any]) -> None:
        from claimtrace.gui.examples import create_example

        self.package = create_example(_required_text(data, "id", limit=100), self.workspace)


class ClaimTraceServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], application: Application):
        self.application = application
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server: ClaimTraceServer
    server_version = "ClaimTrace"

    def log_message(self, format: str, *args: Any) -> None:
        # Do not put user artifact paths or query values into an access log.
        return

    def _boundary(self) -> None:
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host", "").lower()
        if host not in hosts:
            raise RequestError("This interface accepts only its local loopback address.", 403)
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{host}":
            raise RequestError("Open ClaimTrace at its local address to make changes.", 403)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise RequestError("Open ClaimTrace at its local address to make changes.", 403)

    def _headers(
        self, content_type: str, length: int, status: int = 200, *, filename: str | None = None,
        preview_truncated: bool = False,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if preview_truncated:
            self.send_header("X-ClaimTrace-Preview", "partial")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'",
        )
        if filename:
            self.send_header(
                "Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename, safe='')}"
            )
        self.end_headers()

    def _bytes(
        self, value: bytes, content_type: str, *, filename: str | None = None, status: int = 200,
        preview_truncated: bool = False,
    ) -> None:
        self._headers(content_type, len(value), status, filename=filename, preview_truncated=preview_truncated)
        self.wfile.write(value)

    def _json(self, value: Any, status: int = 200) -> None:
        self._bytes(
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            "application/json; charset=utf-8",
            status=status,
        )

    def _error(self, exc: Exception) -> None:
        status = (
            exc.status
            if isinstance(exc, RequestError)
            else 403
            if isinstance(exc, SecurityError)
            else 400
        )
        self._json({"error": str(exc)}, status)

    def do_GET(self) -> None:
        try:
            self._boundary()
            with self.server.application.lock:
                self._get()
        except (RequestError, ClaimTraceError, ValueError, OSError, KeyError, TypeError) as exc:
            self._error(exc)

    def _get(self) -> None:
        request = urlsplit(self.path)
        path = request.path
        app = self.server.application
        query = parse_qs(request.query, keep_blank_values=True)
        if path in {"/api/answers", "/api/artifact", "/api/source", "/api/audit"} and "package_root" in query:
            app.check_package_context(query["package_root"][0])
        if path in STATIC_FILES:
            source = Path(__file__).parent / "static" / STATIC_FILES[path]
            if not source.is_file():
                raise RequestError("Reinstall ClaimTrace to restore its GUI files.", 404)
            media = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
            self._bytes(
                source.read_bytes(),
                media + ("; charset=utf-8" if media.startswith("text/") else ""),
            )
        elif path == "/api/state":
            self._json(app.state())
        elif path == "/api/examples":
            from claimtrace.gui.examples import example_catalog

            self._json({"examples": example_catalog()})
        elif path == "/api/answers":
            source = parse_qs(request.query).get("source", ["current"])[0]
            text = app.answers_text(source=source)
            package = app.require_package()
            self._json(
                {
                    "text": text,
                    "source": source,
                    "saved_available": resolve_package_path(package.root, "answers.yml").is_file(),
                }
            )
        elif path in {"/api/artifact", "/api/source"}:
            self._artifact(parse_qs(request.query))
        elif path == "/api/audit":
            audit = app.state()["audit"]
            if audit is None:
                raise RequestError("Open a package before exporting its audit.", 409)
            if parse_qs(request.query).get("format", ["json"])[0] == "md":
                from claimtrace.gui.audit import export_markdown

                self._bytes(
                    export_markdown(audit).encode("utf-8"),
                    "text/markdown; charset=utf-8",
                    filename="claimtrace-audit.md",
                )
            else:
                self._bytes(
                    (json.dumps(audit, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                    "application/json; charset=utf-8",
                    filename="claimtrace-audit.json",
                )
        else:
            raise RequestError("Page unavailable. Open ClaimTrace at its local address.", 404)

    def _artifact(self, query: dict[str, list[str]]) -> None:
        package = self.server.application.require_package()
        artifact_id = query.get("id", [""])[0]
        artifact = next(
            (item for item in package.semantic_layer.artifacts if item.id == artifact_id), None
        )
        if artifact is None or artifact.kind != ArtifactKind.local_attached or not artifact.path:
            raise RequestError("Attach this file to the current package to open it.", 404)
        _deny_credential_path(artifact.path)
        path = resolve_package_path(package.root, artifact.path)
        if not path.is_file():
            raise RequestError("Attach the file again to restore access.", 404)
        if query.get("download") == ["1"]:
            self._headers("application/octet-stream", path.stat().st_size, filename=path.name)
            with path.open("rb") as handle:
                shutil.copyfileobj(handle, self.wfile)
            return
        suffix = path.suffix.lower()
        if artifact.role == ArtifactRole.render_image and suffix in IMAGE_SUFFIXES - {".svg"}:
            if suffix in {".tif", ".tiff"}:
                with Image.open(path) as raster:
                    output = io.BytesIO()
                    raster.convert("RGB").save(output, format="PNG")
                self._bytes(output.getvalue(), "image/png")
            else:
                self._headers(
                    mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                    path.stat().st_size,
                )
                with path.open("rb") as handle:
                    shutil.copyfileobj(handle, self.wfile)
        elif suffix == ".svg" and artifact.role == ArtifactRole.render_image:
            # Inline SVG can contain active content. Browser image elements can
            # display it, and sandbox CSP also protects direct navigation.
            content = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy", "sandbox; default-src 'none'; style-src 'unsafe-inline'"
            )
            self.end_headers()
            self.wfile.write(content)
        else:
            with path.open("rb") as handle:
                content = handle.read(MAX_TEXT_PREVIEW_BYTES + 1)
            if b"\x00" in content:
                raise RequestError(
                    "Download this file to open it in its original application.", 415
                )
            text = content[:MAX_TEXT_PREVIEW_BYTES].decode("utf-8", errors="replace")
            self._bytes(text.encode("utf-8"), "text/plain; charset=utf-8",
                        preview_truncated=len(content) > MAX_TEXT_PREVIEW_BYTES)

    def do_POST(self) -> None:
        try:
            self._boundary()
            if (
                self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                != "application/json"
            ):
                raise RequestError("Use application/json for local GUI changes.", 415)
            if self.headers.get("Transfer-Encoding"):
                raise RequestError("Send the request with Content-Length.", 400)
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise RequestError("Invalid Content-Length.") from exc
            if length < 0 or length > MAX_REQUEST_BYTES:
                raise RequestError(
                    "Choose a smaller upload or use claimtrace add-artifact for larger files. The upload limit is 64 MiB.",
                    413,
                )
            data = json.loads(self.rfile.read(length), parse_constant=_reject_constant)
            if not isinstance(data, dict):
                raise RequestError("Request body must be a JSON object.")
            app = self.server.application
            with app.lock:
                path = urlsplit(self.path).path
                edits = {
                    "/api/claim": app.save_claim,
                    "/api/evidence": app.save_evidence,
                    "/api/uncertainty": app.save_uncertainty,
                    "/api/identities": app.save_identities,
                    "/api/attach": app.attach,
                    "/api/answers": app.save_answers,
                    "/api/lifecycle": app.set_lifecycle,
                    "/api/context": app.save_context,
                    "/api/proposal-review": app.review_proposal,
                }
                if (path in edits or path in {"/api/export", "/api/validate"}) and "package_root" in data:
                    app.check_package_context(data["package_root"])
                if path in edits:
                    with app.edit_package() as source:
                        edits[path](data)
                        state = app.state()
                    if source:
                        state["working_copy_from"] = source
                    self._json(state)
                    return
                if path == "/api/open":
                    app.open(Path(_required_text(data, "path", limit=4000)))
                elif path == "/api/import":
                    app.import_files(data)
                elif path == "/api/demo":
                    app.demo()
                elif path == "/api/example":
                    app.example(data)
                elif path == "/api/export":
                    content, filename = app.export_zip(data)
                    self._bytes(content, "application/zip", filename=filename)
                    return
                elif path != "/api/validate":
                    raise RequestError("Action unavailable. Refresh ClaimTrace and try again.", 404)
                self._json(app.state())
        except (RequestError, ClaimTraceError, ValueError, OSError, KeyError, TypeError) as exc:
            self._error(exc)


def create_server(
    package: Path | None = None, port: int = 8765, *, workspace: Path | None = None
) -> ClaimTraceServer:
    """Create a loopback server; port=0 selects an unused port for integration tests."""
    return ClaimTraceServer(("127.0.0.1", port), Application(package, workspace))


def serve(
    package: Path | None = None, port: int = 8765, open_browser: bool = True,
    *, initial_view: str | None = None,
) -> None:
    """Run the local GUI until interrupted."""
    server = create_server(package, port)
    url = f"http://127.0.0.1:{server.server_port}"
    if initial_view in {"prepare", "review", "export"}:
        url += f"/?view={initial_view}"
    print(
        f"ClaimTrace GUI: {url}\nLocal files stay on this computer. Press Ctrl+C to stop.",
        flush=True,
    )
    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
