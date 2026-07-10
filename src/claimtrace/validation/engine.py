"""Validation engine for ClaimTrace packages."""

from __future__ import annotations

import json
import re
import stat
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import jsonschema

from claimtrace._finite import ensure_finite
from claimtrace.constants import CAL_SCHEMA_VERSION, EXPORT_MARKER_FILENAME, SEMANTIC_LAYER_FILENAME
from claimtrace.errors import SecurityError
from claimtrace.importers.molviewspec import read_mvs
from claimtrace.models import SemanticLayer
from claimtrace.models.semantic_layer import (
    ArtifactKind,
    ArtifactRole,
    ClaimCriticalStatus,
    ClaimType,
    EvidenceKind,
    MeaningStatus,
    ReviewStatus,
)
from claimtrace.models.validation import SemanticLayerRef, ValidationFinding, ValidationReport
from claimtrace.package.checksums import (
    directory_size,
    file_size,
    is_sha256_digest,
    sha256_directory,
    sha256_file,
)
from claimtrace.package.layout import load_semantic_layer
from claimtrace.package.paths import ensure_relative_path, resolve_package_path, safe_walk
from claimtrace.package.resources import (
    resource_matching_artifacts,
    resource_uri_summary,
)
from claimtrace.schemas import semantic_layer_schema
from claimtrace.validation.findings import finding
from claimtrace.validation.rules import waiver_covers

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret)[\"'\s:=]+[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    re.compile(r"(?i)\bpassword\s*[:=]\s*[\"']?[^\s\"']{8,}"),
    re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^/\s:@]+:[^@\s/]+@"),
    re.compile(r"(?i)\bhttps?://[^/\s:@]+:[^@\s/]+@"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"/home/[A-Za-z0-9_.-]+/"),
    re.compile(r"/Users/[A-Za-z0-9_.-]+/"),
    re.compile(r"(?i)[A-Z]:[\\/]Users[\\/][^\\/\s]+[\\/]"),
]
MAX_PRIVACY_SCAN_BYTES = 2 * 1024 * 1024
MAX_SEMANTIC_LAYER_BYTES = 32 * 1024 * 1024
MAX_CHECKSUM_MANIFEST_BYTES = 16 * 1024 * 1024
VALIDATION_MODES = {"draft", "internal", "share", "archive"}


def validate_package(root: Path, mode: str = "draft", *, revalidation: dict[str, object] | None = None) -> ValidationReport:
    if mode not in VALIDATION_MODES:
        choices = ", ".join(sorted(VALIDATION_MODES))
        raise ValueError(f"Unknown validation mode: {mode}. Choose one of: {choices}.")
    root = Path(root)
    semantic_path = root / SEMANTIC_LAYER_FILENAME
    findings: list[ValidationFinding] = []
    if not root.exists() or not semantic_path.exists():
        semantic_ref = SemanticLayerRef(path=SEMANTIC_LAYER_FILENAME, sha256="", schema_version="unknown")
        return _report(
            package_id=root.name,
            semantic_ref=semantic_ref,
            mode=mode,
            findings=[
                finding(
                    "G0.PACKAGE.MISSING",
                    "G0_PARSEABLE",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "INTEGRITY_ERROR",
                    f"No ClaimTrace package was found at {root}.",
                    pointer="/",
                    blocks=["draft", "internal", "share", "archive"],
                    fix=f"Run `claimtrace init --native <file.pml> --image <figure.png> --out {root}` or check the package path.",
                )
            ],
            semantic=None,
            root=root,
            revalidation=revalidation,
        )
    try:
        semantic_stat = semantic_path.lstat()
        if not stat.S_ISREG(semantic_stat.st_mode) or semantic_path.is_symlink():
            raise SecurityError("semantic_layer.json must be a regular file, not a link or special file")
        if semantic_stat.st_size > MAX_SEMANTIC_LAYER_BYTES:
            raise SecurityError(
                f"semantic_layer.json exceeds the {MAX_SEMANTIC_LAYER_BYTES // (1024 * 1024)} MiB safety limit"
            )
    except (OSError, SecurityError) as exc:
        rule_id = "SECURITY.PATH.SEMANTIC_FILE"
        message = f"Cannot read the canonical manifest safely: {exc}"
        try:
            if semantic_path.is_symlink() and not semantic_path.resolve().is_relative_to(root.resolve()):
                rule_id = "SECURITY.PATH.TRAVERSAL"
                message = "semantic_layer.json must not resolve outside the package directory."
        except OSError:
            pass
        semantic_ref = SemanticLayerRef(path=SEMANTIC_LAYER_FILENAME, sha256="", schema_version="unknown")
        return _report(
            package_id=root.name,
            semantic_ref=semantic_ref,
            mode=mode,
            findings=[
                finding(
                    rule_id,
                    "G0_PARSEABLE",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "SECURITY_BLOCKER",
                    message,
                    pointer="/semantic_layer.json",
                    blocks=["draft", "internal", "share", "archive"],
                    fix="Replace it with a regular, package-local ClaimTrace semantic_layer.json file.",
                )
            ],
            semantic=None,
            root=root,
            revalidation=revalidation,
        )
    try:
        root_resolved = root.resolve()
        semantic_resolved = semantic_path.resolve()
        if not semantic_resolved.is_relative_to(root_resolved):
            semantic_ref = SemanticLayerRef(path=SEMANTIC_LAYER_FILENAME, sha256="", schema_version="unknown")
            return _report(
                package_id=root.name,
                semantic_ref=semantic_ref,
                mode=mode,
                findings=[
                    finding(
                        "SECURITY.PATH.TRAVERSAL",
                        "G2_FIXITY",
                        "L0_PACKAGE_INTEGRITY",
                        "ERROR",
                        "SECURITY_BLOCKER",
                        "semantic_layer.json must not resolve outside the package directory.",
                        pointer="/",
                        blocks=["draft", "internal", "share", "archive"],
                        fix="Replace the symlink with a package-local semantic_layer.json file.",
                    )
                ],
                semantic=None,
                root=root,
                revalidation=revalidation,
            )
    except OSError as exc:
        semantic_ref = SemanticLayerRef(path=SEMANTIC_LAYER_FILENAME, sha256="", schema_version="unknown")
        return _report(
            package_id=root.name,
            semantic_ref=semantic_ref,
            mode=mode,
            findings=[
                finding(
                    "SECURITY.PATH.TRAVERSAL",
                    "G2_FIXITY",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "SECURITY_BLOCKER",
                    f"semantic_layer.json path could not be resolved safely: {exc}",
                    pointer="/",
                    blocks=["draft", "internal", "share", "archive"],
                    fix="Replace the semantic layer path with a regular package-local file.",
                )
            ],
            semantic=None,
            root=root,
            revalidation=revalidation,
        )
    try:
        raw = ensure_finite(
            json.loads(
                semantic_path.read_text(encoding="utf-8"),
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"non-finite numeric constant {value} is not valid JSON")
                ),
            )
        )
    except Exception as exc:
        semantic_ref = SemanticLayerRef(path=SEMANTIC_LAYER_FILENAME, sha256="", schema_version="unknown")
        return _report(
            package_id=root.name,
            semantic_ref=semantic_ref,
            mode=mode,
            findings=[
                finding(
                    "G0.PARSEABLE",
                    "G0_PARSEABLE",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "INTEGRITY_ERROR",
                    f"semantic_layer.json cannot be parsed: {exc}",
                    blocks=["draft", "internal", "share", "archive"],
                    fix="Write valid JSON and include schema_version.",
                )
            ],
            semantic=None,
            root=root,
            revalidation=revalidation,
        )
    if not isinstance(raw, dict):
        semantic_ref = SemanticLayerRef(path=SEMANTIC_LAYER_FILENAME, sha256="", schema_version="unknown")
        return _report(
            package_id=root.name,
            semantic_ref=semantic_ref,
            mode=mode,
            findings=[
                finding(
                    "G1.SCHEMA",
                    "G1_SCHEMA",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "INTEGRITY_ERROR",
                    "semantic_layer.json must contain a JSON object.",
                    pointer="/",
                    blocks=["draft", "internal", "share", "archive"],
                    fix="Write a ClaimTrace semantic_layer.json object with schema_version and package metadata.",
                )
            ],
            semantic=None,
            root=root,
            revalidation=revalidation,
        )
    semantic_hash = sha256_file(semantic_path) if semantic_path.exists() else ""
    schema_version = str(raw.get("schema_version", "unknown"))
    semantic_ref = SemanticLayerRef(
        path=SEMANTIC_LAYER_FILENAME,
        sha256=semantic_hash,
        schema_version=schema_version,
    )
    if schema_version != CAL_SCHEMA_VERSION:
        findings.append(
            finding(
                "G0.PARSEABLE",
                "G0_PARSEABLE",
                "L0_PACKAGE_INTEGRITY",
                "ERROR",
                "INTEGRITY_ERROR",
                f"Unsupported schema_version {schema_version}.",
                pointer="/schema_version",
                blocks=["draft", "internal", "share", "archive"],
                fix="Migrate or rewrite the CAL to schema version 0.1.0.",
            )
        )
        semantic = None
    else:
        try:
            jsonschema.Draft202012Validator(semantic_layer_schema()).validate(raw)
        except jsonschema.ValidationError as exc:
            findings.append(
                finding(
                    "G1.SCHEMA",
                    "G1_SCHEMA",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "INTEGRITY_ERROR",
                    f"JSON Schema validation failed: {exc.message}",
                    pointer="/" + "/".join(str(part) for part in exc.absolute_path),
                    blocks=["draft", "internal", "share", "archive"],
                    fix="Update semantic_layer.json to match the CAL schema.",
                )
            )
        try:
            semantic = load_semantic_layer(root)
        except Exception as exc:
            findings.append(
                finding(
                    "G1.SCHEMA",
                    "G1_SCHEMA",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "INTEGRITY_ERROR",
                    f"Pydantic model validation failed: {exc}",
                    blocks=["draft", "internal", "share", "archive"],
                )
            )
            semantic = None
    if semantic is not None:
        tree_findings = _package_tree_findings(root)
        findings.extend(tree_findings)
        if not tree_findings:
            findings.extend(_checksum_manifest_findings(root))
        findings.extend(_fixity_findings(root, semantic))
        findings.extend(_reference_findings(semantic))
        findings.extend(_claim_findings(semantic))
        findings.extend(_visibility_findings(semantic))
        findings.extend(_native_scene_anchor_findings(semantic, mode))
        if not tree_findings:
            findings.extend(_privacy_findings(root, semantic, mode))
        _apply_waivers(findings, semantic, mode)
    return _report(
        package_id=semantic.package.package_id if semantic else root.name,
        semantic_ref=semantic_ref,
        mode=mode,
        findings=findings,
        semantic=semantic,
        root=root,
        revalidation=revalidation,
    )


def _fixity_findings(root: Path, semantic: SemanticLayer) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    for index, artifact in enumerate(semantic.artifacts):
        pointer = f"/artifacts/{index}"
        kind_errors: list[str] = []
        if artifact.kind == ArtifactKind.remote:
            if not artifact.url:
                kind_errors.append("remote artifacts require url")
            if artifact.path:
                kind_errors.append("remote artifacts cannot use a package path")
            if artifact.included:
                kind_errors.append("remote artifacts must have included=false")
        elif artifact.kind == ArtifactKind.local_attached:
            if not artifact.path:
                kind_errors.append("attached artifacts require a package path")
            if not artifact.included:
                kind_errors.append("attached artifacts must have included=true")
            if artifact.url:
                kind_errors.append("attached artifacts cannot use url")
        elif artifact.kind == ArtifactKind.local_detached:
            if not artifact.path:
                kind_errors.append("detached artifacts require a recorded path")
            if artifact.included:
                kind_errors.append("detached artifacts must have included=false")
        if kind_errors:
            findings.append(
                finding(
                    "G2.ARTIFACT.KIND_INCONSISTENT",
                    "G2_FIXITY",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "INTEGRITY_ERROR",
                    f"Artifact {artifact.id} has inconsistent kind metadata: {'; '.join(kind_errors)}.",
                    pointer=pointer,
                    blocks=["draft", "internal", "share", "archive"],
                    fix="Make kind, path/url and included describe the same attached, detached or remote state.",
                )
            )
        if artifact.sha256 is not None and not is_sha256_digest(artifact.sha256):
            findings.append(
                finding(
                    "G2.FIXITY.INVALID_SHA256",
                    "G2_FIXITY",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "INTEGRITY_ERROR",
                    f"Artifact {artifact.id} has a malformed expected SHA-256 digest.",
                    pointer=f"{pointer}/sha256",
                    blocks=["draft", "internal", "share", "archive"],
                    fix="Record exactly 64 hexadecimal SHA-256 characters, or remove the invalid value.",
                )
            )
        if artifact.kind == ArtifactKind.remote:
            if not artifact.sha256:
                findings.append(
                    finding(
                        "G2.FIXITY.REMOTE_UNAVAILABLE",
                        "G2_FIXITY",
                        "L0_PACKAGE_INTEGRITY",
                        "WARNING",
                        "DISCLOSURE_WARNING",
                        f"Remote file {artifact.id} is listed without an expected checksum.",
                        pointer=pointer,
                        blocks=["archive"],
                        waivable=True,
                        fix="Record an expected checksum or a reason for leaving it detached.",
                    )
                )
            continue
        if not artifact.path:
            findings.append(
                finding(
                    "G2.FIXITY.MISSING_PATH",
                    "G2_FIXITY",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "INTEGRITY_ERROR",
                        f"Local file {artifact.id} needs a package-relative path.",
                    pointer=f"{pointer}/path",
                    blocks=["draft", "internal", "share", "archive"],
                )
            )
            continue
        try:
            ensure_relative_path(artifact.path)
            path = resolve_package_path(root, artifact.path)
        except Exception as exc:
            findings.append(
                finding(
                    "SECURITY.PATH.TRAVERSAL",
                    "G2_FIXITY",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "SECURITY_BLOCKER",
                    f"File path needs to stay inside the package: {exc}",
                    pointer=f"{pointer}/path",
                    blocks=["draft", "internal", "share", "archive"],
                    fix="Use a package-relative path with no .. or absolute prefix.",
                )
            )
            continue
        if artifact.kind == ArtifactKind.local_detached:
            if not artifact.sha256:
                findings.append(
                    finding(
                        "G2.FIXITY.DETACHED_UNAVAILABLE",
                        "G2_FIXITY",
                        "L0_PACKAGE_INTEGRITY",
                        "WARNING",
                        "DISCLOSURE_WARNING",
                        f"Detached file {artifact.id} is listed without an expected checksum.",
                        pointer=pointer,
                        blocks=["archive"],
                        waivable=True,
                        fix="Record the expected checksum, attach the file, or record why this file remains detached.",
                    )
                )
            continue
        if not path.exists():
            findings.append(
                finding(
                    "G2.FIXITY.MISSING_FILE",
                    "G2_FIXITY",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "INTEGRITY_ERROR",
                    f"Package file is missing: {artifact.path}",
                    pointer=pointer,
                    blocks=["draft", "internal", "share", "archive"],
                    fix="Restore the file at this package path or re-register the artifact.",
                )
            )
            continue
        if artifact.role == ArtifactRole.render_image:
            try:
                from claimtrace.importers.image import inspect_image

                inspect_image(path)
            except (OSError, ValueError) as exc:
                findings.append(
                    finding(
                        "G2.RENDER.INVALID_IMAGE",
                        "G2_FIXITY",
                        "L2_VISUAL_REPRODUCIBILITY",
                        "ERROR",
                        "INTEGRITY_ERROR",
                        f"Rendered panel cannot be opened as a valid image: {artifact.path} ({exc})",
                        pointer=pointer,
                        blocks=["draft", "internal", "share", "archive"],
                        fix="Replace the file with a valid PNG, JPEG, GIF, TIFF, WebP or well-formed SVG and re-register it.",
                    )
                )
        if path.is_file() or path.is_dir():
            actual_hash = sha256_directory(path) if path.is_dir() else sha256_file(path)
            actual_size = directory_size(path) if path.is_dir() else file_size(path)
            if artifact.sha256 != actual_hash:
                findings.append(
                    finding(
                        "G2.FIXITY.HASH_MISMATCH",
                        "G2_FIXITY",
                        "L0_PACKAGE_INTEGRITY",
                        "ERROR",
                        "INTEGRITY_ERROR",
                        f"File checksum changed for {artifact.path}.",
                        pointer=f"{pointer}/sha256",
                        blocks=["draft", "internal", "share", "archive"],
                        fix="Re-register the artifact or restore the original file.",
                    )
                )
            if artifact.byte_size != actual_size:
                findings.append(
                    finding(
                        "G2.FIXITY.SIZE_MISMATCH",
                        "G2_FIXITY",
                        "L0_PACKAGE_INTEGRITY",
                        "ERROR",
                        "INTEGRITY_ERROR",
                        f"File size changed for {artifact.path}.",
                        pointer=f"{pointer}/byte_size",
                        blocks=["draft", "internal", "share", "archive"],
                        fix="Re-register the artifact or restore the original file.",
                    )
                )
    for inventory_index, inventory in enumerate(semantic.mvsx_inventories):
        for member_index, member in enumerate(inventory.members):
            if member.sha256 is not None and not is_sha256_digest(member.sha256):
                findings.append(
                    finding(
                        "G2.FIXITY.INVALID_SHA256",
                        "G2_FIXITY",
                        "L0_PACKAGE_INTEGRITY",
                        "ERROR",
                        "INTEGRITY_ERROR",
                        f"MVSX member {member.member_id} has a malformed SHA-256 digest.",
                        pointer=f"/mvsx_inventories/{inventory_index}/members/{member_index}/sha256",
                        blocks=["draft", "internal", "share", "archive"],
                        fix="Re-import the MVSX archive to recompute its member checksum.",
                    )
                )
    findings.extend(_mvsx_inventory_integrity_findings(root, semantic))
    return findings


def _mvsx_inventory_integrity_findings(
    root: Path,
    semantic: SemanticLayer,
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    artifact_by_id = {artifact.id: artifact for artifact in semantic.artifacts}
    for index, inventory in enumerate(semantic.mvsx_inventories):
        artifact = artifact_by_id.get(inventory.artifact_id)
        pointer = f"/mvsx_inventories/{index}"
        if artifact is None or artifact.kind != ArtifactKind.local_attached or not artifact.path:
            continue
        try:
            archive_path = resolve_package_path(root, artifact.path)
            actual = read_mvs(archive_path, artifact.id).inventory
            if actual is None:
                raise ValueError("artifact is not an MVSX archive")
            recorded_members = sorted(
                (member.normalized_name, member.is_dir, member.sha256, member.byte_size)
                for member in inventory.members
            )
            actual_members = sorted(
                (member.normalized_name, member.is_dir, member.sha256, member.byte_size)
                for member in actual.members
            )
            matches = (
                inventory.scene_entry == actual.scene_entry
                and inventory.format_status == actual.format_status
                and recorded_members == actual_members
            )
        except Exception as exc:
            matches = False
            detail = str(exc)
        else:
            detail = "recorded inventory differs from the current archive"
        if not matches:
            findings.append(
                finding(
                    "G2.FIXITY.MVSX_INVENTORY_MISMATCH",
                    "G2_FIXITY",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "INTEGRITY_ERROR",
                    f"MVSX inventory cannot be verified: {detail}.",
                    pointer=pointer,
                    blocks=["draft", "internal", "share", "archive"],
                    fix="Re-register the MVSX archive to rebuild its member inventory.",
                )
            )
    return findings


def _package_tree_findings(root: Path) -> list[ValidationFinding]:
    try:
        paths = list(safe_walk(root, include_directories=True))
    except (OSError, SecurityError) as exc:
        return [
            finding(
                "SECURITY.PATH.SYMLINK",
                "G2_FIXITY",
                "L0_PACKAGE_INTEGRITY",
                "ERROR",
                "SECURITY_BLOCKER",
                f"Package tree cannot be traversed safely: {exc}",
                pointer="/",
                blocks=["draft", "internal", "share", "archive"],
                fix="Replace symbolic links or special paths with regular package-local files.",
            )
        ]
    portable_paths: dict[str, str] = {}
    for path in paths:
        relative = path.relative_to(root.resolve()).as_posix()
        portable = unicodedata.normalize("NFC", relative).casefold()
        previous = portable_paths.get(portable)
        if previous is not None and previous != relative:
            return [
                finding(
                    "SECURITY.PATH.PORTABILITY_COLLISION",
                    "G2_FIXITY",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "SECURITY_BLOCKER",
                    f"Package paths collide on case-insensitive filesystems: {previous} and {relative}.",
                    pointer="/",
                    blocks=["draft", "internal", "share", "archive"],
                    fix="Rename one file so normalized, case-insensitive paths are unique.",
                )
            ]
        portable_paths[portable] = relative
    return []


def _checksum_manifest_findings(root: Path) -> list[ValidationFinding]:
    """Verify an exported package manifest when one is present.

    Working packages do not receive a manifest until export. Once present, the
    manifest is an integrity boundary: every listed file must still exist and
    match, and every package file except the manifest itself must be listed.
    """

    manifest = root / "checksums" / "sha256.txt"
    if not manifest.exists():
        if (root / EXPORT_MARKER_FILENAME).exists():
            return [
                finding(
                    "G2.FIXITY.MANIFEST_MISSING",
                    "G2_FIXITY",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "INTEGRITY_ERROR",
                    "This exported package is missing checksums/sha256.txt.",
                    pointer="/checksums/sha256.txt",
                    blocks=["draft", "internal", "share", "archive"],
                    fix="Restore the checksum manifest or re-export the original package.",
                )
            ]
        return []
    findings: list[ValidationFinding] = []
    expected: dict[str, str] = {}
    try:
        if manifest.is_symlink():
            raise ValueError("checksum manifest must be a regular package file")
        manifest_stat = manifest.lstat()
        if not stat.S_ISREG(manifest_stat.st_mode):
            raise ValueError("checksum manifest must be a regular package file")
        if manifest_stat.st_size > MAX_CHECKSUM_MANIFEST_BYTES:
            raise ValueError("checksum manifest exceeds the 16 MiB safety limit")
        for line_no, raw_line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw_line.strip():
                continue
            if "  " not in raw_line:
                raise ValueError(f"line {line_no} does not use '<sha256>  <path>' format")
            digest, relative = raw_line.split("  ", 1)
            if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
                raise ValueError(f"line {line_no} has an invalid SHA256 digest")
            ensure_relative_path(relative)
            if relative == "checksums/sha256.txt":
                raise ValueError("the checksum manifest cannot list itself")
            if relative in expected:
                raise ValueError(f"duplicate checksum entry: {relative}")
            expected[relative] = digest.lower()
    except Exception as exc:
        return [
            finding(
                "G2.FIXITY.MANIFEST_INVALID",
                "G2_FIXITY",
                "L0_PACKAGE_INTEGRITY",
                "ERROR",
                "INTEGRITY_ERROR",
                f"checksums/sha256.txt cannot be verified: {exc}",
                pointer="/checksums/sha256.txt",
                blocks=["draft", "internal", "share", "archive"],
                fix="Re-export the package to regenerate its checksum manifest.",
            )
        ]

    actual_files: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative != "checksums/sha256.txt":
            actual_files.add(relative)
    for relative, expected_digest in sorted(expected.items()):
        try:
            path = resolve_package_path(root, relative)
            if not path.is_file() or path.is_symlink():
                raise FileNotFoundError(relative)
            actual_digest = sha256_file(path)
        except Exception:
            findings.append(
                finding(
                    "G2.FIXITY.MANIFEST_FILE_MISSING",
                    "G2_FIXITY",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "INTEGRITY_ERROR",
                    f"Checksum manifest entry is missing or unsafe: {relative}.",
                    pointer="/checksums/sha256.txt",
                    blocks=["draft", "internal", "share", "archive"],
                    fix="Restore the exported file or re-export the package.",
                )
            )
            continue
        if actual_digest != expected_digest:
            findings.append(
                finding(
                    "G2.FIXITY.MANIFEST_HASH_MISMATCH",
                    "G2_FIXITY",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "INTEGRITY_ERROR",
                    f"Exported file no longer matches checksums/sha256.txt: {relative}.",
                    pointer="/checksums/sha256.txt",
                    blocks=["draft", "internal", "share", "archive"],
                    fix="Restore the exported file or re-export the package.",
                )
            )
    for relative in sorted(actual_files - set(expected)):
        findings.append(
            finding(
                "G2.FIXITY.MANIFEST_UNLISTED_FILE",
                "G2_FIXITY",
                "L0_PACKAGE_INTEGRITY",
                "ERROR",
                "INTEGRITY_ERROR",
                f"Exported package contains a file not covered by its checksum manifest: {relative}.",
                pointer="/checksums/sha256.txt",
                blocks=["draft", "internal", "share", "archive"],
                fix="Remove the unexpected file or re-export the package.",
            )
        )
    return findings


def _reference_findings(semantic: SemanticLayer) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    artifact_id_counts: dict[str, int] = {}
    for artifact in semantic.artifacts:
        artifact_id_counts[artifact.id] = artifact_id_counts.get(artifact.id, 0) + 1
    for artifact_id, count in sorted(artifact_id_counts.items()):
        if count > 1:
            findings.append(
                finding(
                    "G3.REFERENCE.DUPLICATE_ARTIFACT_ID",
                    "G3_REFERENCE",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "INTEGRITY_ERROR",
                    f"Artifact ID {artifact_id} is used by {count} different artifact records.",
                    pointer="/artifacts",
                    blocks=["draft", "internal", "share", "archive"],
                    fix="Assign a unique artifact ID to each distinct package path, then update its references.",
                )
            )
    claim_ids = {item.id for item in semantic.claims}
    scene_ids = {item.id for item in semantic.scenes}
    evidence_ids = {item.id for item in semantic.evidence}
    uncertainty_ids = {item.id for item in semantic.uncertainty}
    entity_ids = {item.id for item in semantic.entities}
    selection_ids = {item.id for item in semantic.selections}
    artifact_ids = {item.id for item in semantic.artifacts}
    operation_ids = {item.operation_id for item in semantic.observed_scene_operations}
    native_ref_ids = {item.native_ref_id for item in semantic.native_references}
    raw_ids = {item.raw_id for item in semantic.raw_native_observations}
    resource_ref_ids = {item.resource_ref_id for item in semantic.resource_references}
    binding_ids = {item.binding_id for item in semantic.evidence_bindings}
    software_ids = {item.id for item in semantic.software_environment}
    activity_ids = {item.id for item in semantic.provenance.activities}
    agent_ids = {item.id for item in semantic.provenance.agents}
    member_ids = {
        member.member_id
        for inventory in semantic.mvsx_inventories
        for member in inventory.members
    }
    all_object_ids = (
        claim_ids
        | scene_ids
        | evidence_ids
        | uncertainty_ids
        | entity_ids
        | selection_ids
        | artifact_ids
        | operation_ids
        | native_ref_ids
        | raw_ids
        | resource_ref_ids
        | binding_ids
        | software_ids
        | activity_ids
        | agent_ids
        | member_ids
    )
    duplicate_collections = [
        ("claims", semantic.claims, "id"),
        ("scenes", semantic.scenes, "id"),
        ("evidence", semantic.evidence, "id"),
        ("uncertainty", semantic.uncertainty, "id"),
        ("entities", semantic.entities, "id"),
        ("selections", semantic.selections, "id"),
        ("observed_scene_operations", semantic.observed_scene_operations, "operation_id"),
        ("native_references", semantic.native_references, "native_ref_id"),
        ("raw_native_observations", semantic.raw_native_observations, "raw_id"),
        ("resource_references", semantic.resource_references, "resource_ref_id"),
        ("evidence_bindings", semantic.evidence_bindings, "binding_id"),
        ("software_environment", semantic.software_environment, "id"),
        ("provenance/agents", semantic.provenance.agents, "id"),
        ("provenance/activities", semantic.provenance.activities, "id"),
    ]
    for collection_name, collection, attribute in duplicate_collections:
        counts: dict[str, int] = {}
        for value in collection:
            identifier = str(getattr(value, attribute))
            counts[identifier] = counts.get(identifier, 0) + 1
        for identifier, count in sorted(counts.items()):
            if count > 1:
                findings.append(
                    finding(
                        "G3.REFERENCE.DUPLICATE_ID",
                        "G3_REFERENCE",
                        "L0_PACKAGE_INTEGRITY",
                        "ERROR",
                        "INTEGRITY_ERROR",
                        f"ID {identifier} appears {count} times in {collection_name}.",
                        pointer=f"/{collection_name}",
                        blocks=["draft", "internal", "share", "archive"],
                        fix="Assign a unique ID to each record, then update references to it.",
                    )
                )
    claims_by_id = {item.id: item for item in semantic.claims}
    evidence_by_id = {item.id: item for item in semantic.evidence}
    uncertainty_by_id = {item.id: item for item in semantic.uncertainty}
    for field_name, values in (
        ("path", [item.path for item in semantic.artifacts if item.path]),
        ("url", [item.url for item in semantic.artifacts if item.url]),
    ):
        counts: dict[str, int] = {}
        for value in values:
            normalized = str(value).replace("\\", "/")
            counts[normalized] = counts.get(normalized, 0) + 1
        for value, count in sorted(counts.items()):
            if count > 1:
                findings.append(
                    finding(
                        "G3.REFERENCE.DUPLICATE_ARTIFACT_LOCATION",
                        "G3_REFERENCE",
                        "L0_PACKAGE_INTEGRITY",
                        "ERROR",
                        "INTEGRITY_ERROR",
                        f"Artifact {field_name} {value} is used by {count} records.",
                        pointer="/artifacts",
                        blocks=["draft", "internal", "share", "archive"],
                        fix="Keep one artifact record per package path or remote URL.",
                    )
                )
    for index, claim in enumerate(semantic.claims):
        _missing_refs(findings, claim.scene_ids, scene_ids, f"/claims/{index}/scene_ids", "scene")
        _missing_refs(findings, claim.evidence_ids, evidence_ids, f"/claims/{index}/evidence_ids", "evidence")
        _missing_refs(findings, claim.uncertainty_ids, uncertainty_ids, f"/claims/{index}/uncertainty_ids", "uncertainty")
        claim_source = getattr(claim.claim_text, "source_location", None)
        if claim_source is not None and claim_source.artifact_id is not None:
            _missing_refs(
                findings,
                [claim_source.artifact_id],
                artifact_ids,
                f"/claims/{index}/claim_text/source_location/artifact_id",
                "source artifact",
            )
        for evidence_id in claim.evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is not None and claim.id not in evidence.claim_ids:
                findings.append(
                    finding(
                        "G3.REFERENCE.INCONSISTENT",
                        "G3_REFERENCE",
                        "L0_PACKAGE_INTEGRITY",
                        "ERROR",
                        "INTEGRITY_ERROR",
                        f"Claim {claim.id} links evidence {evidence_id}, but that evidence does not link back to the claim.",
                        pointer=f"/claims/{index}/evidence_ids",
                        blocks=["draft", "internal", "share", "archive"],
                        fix="Make claim.evidence_ids and evidence.claim_ids describe the same relationship.",
                    )
                )
        for uncertainty_id in claim.uncertainty_ids:
            uncertainty = uncertainty_by_id.get(uncertainty_id)
            if uncertainty is not None and claim.id not in uncertainty.claim_ids:
                findings.append(
                    finding(
                        "G3.REFERENCE.INCONSISTENT",
                        "G3_REFERENCE",
                        "L0_PACKAGE_INTEGRITY",
                        "ERROR",
                        "INTEGRITY_ERROR",
                        f"Claim {claim.id} links uncertainty {uncertainty_id}, but that note does not link back to the claim.",
                        pointer=f"/claims/{index}/uncertainty_ids",
                        blocks=["draft", "internal", "share", "archive"],
                        fix="Make claim.uncertainty_ids and uncertainty.claim_ids describe the same relationship.",
                    )
                )
    for index, scene in enumerate(semantic.scenes):
        _missing_refs(findings, scene.native_artifact_ids, artifact_ids, f"/scenes/{index}/native_artifact_ids", "artifact")
        _missing_refs(findings, scene.render_artifact_ids, artifact_ids, f"/scenes/{index}/render_artifact_ids", "artifact")
        _missing_refs(findings, scene.selection_ids, selection_ids, f"/scenes/{index}/selection_ids", "selection")
        _missing_refs(findings, scene.entity_ids, entity_ids, f"/scenes/{index}/entity_ids", "entity")
        for visibility_index, visibility in enumerate(scene.visibility):
            if visibility.entity_id is not None:
                _missing_refs(
                    findings,
                    [visibility.entity_id],
                    entity_ids,
                    f"/scenes/{index}/visibility/{visibility_index}/entity_id",
                    "entity",
                )
            if visibility.selection_id is not None:
                _missing_refs(
                    findings,
                    [visibility.selection_id],
                    selection_ids,
                    f"/scenes/{index}/visibility/{visibility_index}/selection_id",
                    "selection",
                )
    for index, entity in enumerate(semantic.entities):
        _missing_refs(
            findings,
            entity.source_artifact_ids,
            artifact_ids,
            f"/entities/{index}/source_artifact_ids",
            "artifact",
        )
    for index, selection in enumerate(semantic.selections):
        _missing_refs(
            findings,
            selection.entity_ids,
            entity_ids,
            f"/selections/{index}/entity_ids",
            "entity",
        )
        if selection.source_artifact_id is not None:
            _missing_refs(
                findings,
                [selection.source_artifact_id],
                artifact_ids,
                f"/selections/{index}/source_artifact_id",
                "artifact",
            )
        selector_source = getattr(selection.native_selector, "source_location", None)
        if selector_source is not None and selector_source.artifact_id is not None:
            _missing_refs(
                findings,
                [selector_source.artifact_id],
                artifact_ids,
                f"/selections/{index}/native_selector/source_location/artifact_id",
                "source artifact",
            )
    for index, evidence in enumerate(semantic.evidence):
        _missing_refs(findings, evidence.claim_ids, claim_ids, f"/evidence/{index}/claim_ids", "claim")
        _missing_refs(findings, evidence.source_artifact_ids, artifact_ids, f"/evidence/{index}/source_artifact_ids", "artifact")
        _missing_refs(findings, evidence.target_entity_ids, entity_ids, f"/evidence/{index}/target_entity_ids", "entity")
        _missing_refs(findings, evidence.target_selection_ids, selection_ids, f"/evidence/{index}/target_selection_ids", "selection")
        if evidence.provenance_id is not None:
            _missing_refs(
                findings,
                [evidence.provenance_id],
                activity_ids,
                f"/evidence/{index}/provenance_id",
                "provenance activity",
            )
        for claim_id in evidence.claim_ids:
            claim = claims_by_id.get(claim_id)
            if claim is not None and evidence.id not in claim.evidence_ids:
                findings.append(
                    finding(
                        "G3.REFERENCE.INCONSISTENT",
                        "G3_REFERENCE",
                        "L0_PACKAGE_INTEGRITY",
                        "ERROR",
                        "INTEGRITY_ERROR",
                        f"Evidence {evidence.id} links claim {claim_id}, but that claim does not link back to the evidence.",
                        pointer=f"/evidence/{index}/claim_ids",
                        blocks=["draft", "internal", "share", "archive"],
                        fix="Make claim.evidence_ids and evidence.claim_ids describe the same relationship.",
                    )
                )
    for index, uncertainty in enumerate(semantic.uncertainty):
        _missing_refs(
            findings,
            uncertainty.claim_ids,
            claim_ids,
            f"/uncertainty/{index}/claim_ids",
            "claim",
        )
        for claim_id in uncertainty.claim_ids:
            claim = claims_by_id.get(claim_id)
            if claim is not None and uncertainty.id not in claim.uncertainty_ids:
                findings.append(
                    finding(
                        "G3.REFERENCE.INCONSISTENT",
                        "G3_REFERENCE",
                        "L0_PACKAGE_INTEGRITY",
                        "ERROR",
                        "INTEGRITY_ERROR",
                        f"Uncertainty {uncertainty.id} links claim {claim_id}, but that claim does not link back to the note.",
                        pointer=f"/uncertainty/{index}/claim_ids",
                        blocks=["draft", "internal", "share", "archive"],
                        fix="Make claim.uncertainty_ids and uncertainty.claim_ids describe the same relationship.",
                    )
                )
    for index, item in enumerate(semantic.visual_encoding_semantics):
        _missing_refs(
            findings,
            item.operation_ids,
            operation_ids,
            f"/visual_encoding_semantics/{index}/operation_ids",
            "scene operation",
        )
    for index, binding in enumerate(semantic.evidence_bindings):
        if binding.claim_id is not None:
            _missing_refs(
                findings,
                [binding.claim_id],
                claim_ids,
                f"/evidence_bindings/{index}/claim_id",
                "claim",
            )
        _missing_refs(
            findings,
            binding.operation_ids,
            operation_ids,
            f"/evidence_bindings/{index}/operation_ids",
            "scene operation",
        )
        _missing_refs(
            findings,
            binding.resource_ref_ids,
            resource_ref_ids,
            f"/evidence_bindings/{index}/resource_ref_ids",
            "resource reference",
        )
        _missing_refs(
            findings,
            binding.evidence_artifact_ids,
            artifact_ids,
            f"/evidence_bindings/{index}/evidence_artifact_ids",
            "artifact",
        )
    for index, raw in enumerate(semantic.raw_native_observations):
        _missing_refs(
            findings,
            [raw.artifact_id],
            artifact_ids,
            f"/raw_native_observations/{index}/artifact_id",
            "artifact",
        )
        if raw.may_affect_scene_id is not None:
            _missing_refs(
                findings,
                [raw.may_affect_scene_id],
                scene_ids,
                f"/raw_native_observations/{index}/may_affect_scene_id",
                "scene",
            )
    for index, resource in enumerate(semantic.resource_references):
        if resource.artifact_id is not None:
            _missing_refs(
                findings,
                [resource.artifact_id],
                artifact_ids,
                f"/resource_references/{index}/artifact_id",
                "artifact",
            )
        if resource.mvsx_member_id is not None:
            _missing_refs(
                findings,
                [resource.mvsx_member_id],
                member_ids,
                f"/resource_references/{index}/mvsx_member_id",
                "MVSX member",
            )
    for index, inventory in enumerate(semantic.mvsx_inventories):
        _missing_refs(
            findings,
            [inventory.artifact_id],
            artifact_ids,
            f"/mvsx_inventories/{index}/artifact_id",
            "artifact",
        )
        member_counts: dict[str, int] = {}
        for member in inventory.members:
            member_counts[member.member_id] = member_counts.get(member.member_id, 0) + 1
        for member_id, count in sorted(member_counts.items()):
            if count > 1:
                findings.append(
                    finding(
                        "G3.REFERENCE.DUPLICATE_ID",
                        "G3_REFERENCE",
                        "L0_PACKAGE_INTEGRITY",
                        "ERROR",
                        "INTEGRITY_ERROR",
                        f"MVSX member ID {member_id} appears {count} times in one inventory.",
                        pointer=f"/mvsx_inventories/{index}/members",
                        blocks=["draft", "internal", "share", "archive"],
                        fix="Re-import the archive so each member receives a unique ID.",
                    )
                )
    for index, activity in enumerate(semantic.provenance.activities):
        if activity.agent_id is not None:
            _missing_refs(
                findings,
                [activity.agent_id],
                agent_ids,
                f"/provenance/activities/{index}/agent_id",
                "agent",
            )
        _missing_refs(
            findings,
            activity.used_artifact_ids,
            artifact_ids,
            f"/provenance/activities/{index}/used_artifact_ids",
            "artifact",
        )
        _missing_refs(
            findings,
            activity.generated_ids,
            all_object_ids,
            f"/provenance/activities/{index}/generated_ids",
            "generated object",
        )
    anchor_ids = all_object_ids
    for index, waiver in enumerate(semantic.provenance.waivers):
        if (
            not _text_is_recorded(waiver.reason)
            or not _text_is_recorded(waiver.reviewer)
            or not _is_rfc3339_timestamp(waiver.reviewed_at or waiver.timestamp)
        ):
            findings.append(
                finding(
                    "G3.WAIVER.REVIEW_INVALID",
                    "G3_REFERENCE",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "INTEGRITY_ERROR",
                    "A waiver needs a concrete reason, reviewer and valid review timestamp.",
                    pointer=f"/provenance/waivers/{index}",
                    blocks=["draft", "internal", "share", "archive"],
                    fix="Record who reviewed the waiver, why it is justified and when it was reviewed.",
                )
            )
        if waiver.anchor_id is not None:
            _missing_refs(
                findings,
                [waiver.anchor_id],
                anchor_ids,
                f"/provenance/waivers/{index}/anchor_id",
                "waiver anchor",
            )
        elif waiver.scope not in {"package", "global", "all"}:
            findings.append(
                finding(
                    "G3.WAIVER.SCOPE_INVALID",
                    "G3_REFERENCE",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "INTEGRITY_ERROR",
                    "A waiver without anchor_id must explicitly use package, global or all scope.",
                    pointer=f"/provenance/waivers/{index}",
                    blocks=["draft", "internal", "share", "archive"],
                    fix="Add a valid anchor_id, or explicitly set scope to package for a rule-wide waiver.",
                )
            )
    for collection_name, collection in (
        ("observed_scene_operations", semantic.observed_scene_operations),
        ("native_references", semantic.native_references),
        ("raw_native_observations", semantic.raw_native_observations),
        ("resource_references", semantic.resource_references),
    ):
        for index, value in enumerate(collection):
            source_artifact_id = getattr(value.source_location, "artifact_id", None)
            if source_artifact_id is not None:
                _missing_refs(
                    findings,
                    [source_artifact_id],
                    artifact_ids,
                    f"/{collection_name}/{index}/source_location/artifact_id",
                    "source artifact",
                )
    return findings


def _missing_refs(
    findings: list[ValidationFinding],
    refs: list[str],
    valid: set[str],
    pointer: str,
    label: str,
) -> None:
    for ref in refs:
        if ref not in valid:
            findings.append(
                finding(
                    "G3.REFERENCE.MISSING",
                    "G3_REFERENCE",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "INTEGRITY_ERROR",
                    f"Package points to a missing {label} id: {ref}",
                    pointer=pointer,
                    blocks=["draft", "internal", "share", "archive"],
                    fix="Correct the ID or add the referenced object.",
                )
            )


def _claim_findings(semantic: SemanticLayer) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    if not semantic.claims:
        findings.append(
            finding(
                "CLAIM.BASIC.MISSING",
                "G4_CLAIM_RULES",
                "L1_SEMANTIC_LINKABILITY",
                "ERROR",
                "REVIEWABILITY_ERROR",
                "Add the main figure message before sharing this package.",
                pointer="/claims",
                blocks=["share", "archive"],
                claim_critical=True,
                fix="Edit the package's existing answers.yml, then run `claimtrace complete <package> --check-answers <package>/answers.yml` and apply it.",
            )
        )
        return findings
    for index, claim in enumerate(semantic.claims):
        pointer = f"/claims/{index}"
        if not _text_is_recorded(claim.claim_text.value):
            findings.append(
                finding(
                    "CLAIM.BASIC.TEXT",
                    "G4_CLAIM_RULES",
                    "L1_SEMANTIC_LINKABILITY",
                    "ERROR",
                    "REVIEWABILITY_ERROR",
                    f"Claim {claim.id} still needs the main figure message.",
                    pointer=f"{pointer}/claim_text/value",
                    blocks=["share", "archive"],
                    claim_critical=True,
                    fix="Fill `claim.claim_text` in answers.yml, then apply the answers file.",
                )
            )
        if not (
            claim.review_status in {ReviewStatus.confirmed, ReviewStatus.human_accepted}
            and claim.claim_text.review_status
            in {ReviewStatus.confirmed, ReviewStatus.human_accepted}
            and _text_is_recorded(claim.claim_text.reviewer)
            and _is_rfc3339_timestamp(claim.claim_text.reviewed_at)
        ):
            findings.append(
                finding(
                    "CLAIM.BASIC.AUTHOR_REVIEW",
                    "G4_CLAIM_RULES",
                    "L3_CLAIM_EVIDENCE",
                    "ERROR",
                    "REVIEWABILITY_ERROR",
                    f"Claim {claim.id} has not been recorded as an author-reviewed statement.",
                    pointer=f"{pointer}/claim_text/review_status",
                    blocks=["share", "archive"],
                    claim_critical=True,
                    fix="Apply answers.yml with a reviewer identity, or confirm the claim text and record an RFC 3339 review time.",
                )
            )
        if not _text_is_recorded(claim.figure_ref):
            findings.append(
                finding(
                    "CLAIM.BASIC.FIGURE",
                    "G4_CLAIM_RULES",
                    "L1_SEMANTIC_LINKABILITY",
                    "ERROR",
                    "REVIEWABILITY_ERROR",
                    f"Claim {claim.id} needs a figure or panel label.",
                    pointer=f"{pointer}/figure_ref",
                    blocks=["share", "archive"],
                    claim_critical=True,
                    fix="Fill `claim.figure_ref` with a label such as Figure 1A.",
                )
            )
        if not claim.scene_ids:
            findings.append(
                finding(
                    "CLAIM.BASIC.SCENE",
                    "G4_CLAIM_RULES",
                    "L1_SEMANTIC_LINKABILITY",
                    "ERROR",
                    "REVIEWABILITY_ERROR",
                    f"Claim {claim.id} needs to be linked to a scene in this package.",
                    pointer=f"{pointer}/scene_ids",
                    blocks=["share", "archive"],
                    claim_critical=True,
                    fix="Apply answers again or add the scene id under this claim.",
                )
            )
        if not claim.evidence_ids:
            findings.append(
                finding(
                    "CLAIM.BASIC.EVIDENCE",
                    "G4_CLAIM_RULES",
                    "L3_CLAIM_EVIDENCE",
                    "ERROR",
                    "REVIEWABILITY_ERROR",
                    f"Claim {claim.id} needs at least one supporting file or note before archive export.",
                    pointer=f"{pointer}/evidence_ids",
                    blocks=["archive"],
                    claim_critical=True,
                    waivable=True,
                    fix="Add an evidence entry, or record a reason explaining why no separate evidence file is needed.",
                )
            )
        for evidence_id in claim.evidence_ids:
            evidence = next((item for item in semantic.evidence if item.id == evidence_id), None)
            if evidence is not None and not evidence.source_artifact_ids:
                findings.append(
                    finding(
                        "CLAIM.EVIDENCE.SOURCE_MISSING",
                        "G4B_EVIDENCE_MINIMUMS",
                        "L3_CLAIM_EVIDENCE",
                        "ERROR",
                        "REVIEWABILITY_ERROR",
                        f"Evidence {evidence.id} has no linked source file or package artifact.",
                        pointer=f"/evidence/{semantic.evidence.index(evidence)}/source_artifact_ids",
                        blocks=["archive"],
                        claim_critical=True,
                        waivable=True,
                        fix="Link a source artifact, add source_artifact_paths in answers.yml, or record why this is a note-only evidence item.",
                    )
                )
            if evidence is not None and not _summary_is_recorded(evidence):
                findings.append(
                    finding(
                        "CLAIM.EVIDENCE.SUMMARY_MISSING",
                        "G4B_EVIDENCE_MINIMUMS",
                        "L3_CLAIM_EVIDENCE",
                        "ERROR",
                        "REVIEWABILITY_ERROR",
                        f"Evidence {evidence.id} needs a concrete result summary before archive export.",
                        pointer=f"/evidence/{semantic.evidence.index(evidence)}/result_summary",
                        blocks=["archive"],
                        claim_critical=True,
                        waivable=True,
                        fix="Describe what the linked source shows, without overstating the scientific conclusion.",
                    )
                )
            if evidence is not None and not _evidence_is_author_reviewed(evidence):
                findings.append(
                    finding(
                        "CLAIM.EVIDENCE.REVIEW_REQUIRED",
                        "G4B_EVIDENCE_MINIMUMS",
                        "L3_CLAIM_EVIDENCE",
                        "ERROR",
                        "REVIEWABILITY_ERROR",
                        f"Evidence {evidence.id} is still an unreviewed or automatically extracted observation.",
                        pointer=f"/evidence/{semantic.evidence.index(evidence)}/review_status",
                        blocks=["archive"],
                        claim_critical=True,
                        waivable=True,
                        fix="Have an author review the evidence entry and record confirmed or human_accepted status.",
                    )
                )
        for uncertainty_id in claim.uncertainty_ids:
            uncertainty = next(
                (item for item in semantic.uncertainty if item.id == uncertainty_id),
                None,
            )
            if uncertainty is not None and not _uncertainty_is_complete(uncertainty):
                findings.append(
                    finding(
                        "CLAIM.UNCERTAINTY.REVIEW_REQUIRED",
                        "G4B_EVIDENCE_MINIMUMS",
                        "L3_CLAIM_EVIDENCE",
                        "ERROR",
                        "REVIEWABILITY_ERROR",
                        f"Uncertainty note {uncertainty.id} still needs a concrete author-reviewed statement.",
                        pointer=f"/uncertainty/{semantic.uncertainty.index(uncertainty)}",
                        blocks=["archive"],
                        claim_critical=True,
                        waivable=True,
                        fix="Replace TODO/unknown text with a useful caveat and record author review.",
                    )
                )
        if claim.claim_type == ClaimType.simple_structure_view and not _has_packaged_structure(semantic):
            findings.append(
                finding(
                    "CLAIM.SIMPLE.REQUIRED_STRUCTURE",
                    "G4B_EVIDENCE_MINIMUMS",
                    "L3_CLAIM_EVIDENCE",
                    "ERROR",
                    "REVIEWABILITY_ERROR",
                    f"Claim {claim.id} is a simple structure view but no structure file is linked in the package.",
                    pointer=f"{pointer}/claim_type",
                    blocks=["archive"],
                    claim_critical=True,
                    waivable=True,
                    fix="Add a PDB/mmCIF/BCIF artifact, or record why the native/render files are sufficient.",
                )
            )
        if claim.claim_type == ClaimType.simple_structure_view:
            claim_scenes = [scene for scene in semantic.scenes if scene.id in claim.scene_ids]
            attached_render_ids = {
                artifact.id
                for artifact in semantic.artifacts
                if artifact.role == ArtifactRole.render_image
                and artifact.kind == ArtifactKind.local_attached
                and artifact.included
                and is_sha256_digest(artifact.sha256)
            }
            if not any(
                attached_render_ids.intersection(scene.render_artifact_ids)
                for scene in claim_scenes
            ):
                findings.append(
                    finding(
                        "CLAIM.SIMPLE.REQUIRED_RENDER",
                        "G4B_EVIDENCE_MINIMUMS",
                        "L2_VISUAL_REPRODUCIBILITY",
                        "ERROR",
                        "REVIEWABILITY_ERROR",
                        f"Claim {claim.id} is a publication view but no rendered panel is linked.",
                        pointer=f"{pointer}/scene_ids",
                        blocks=["archive"],
                        claim_critical=True,
                        waivable=True,
                        fix="Add the rendered panel, or document why a native-only archive is intentional.",
                    )
                )
            if not any(scene.camera for scene in claim_scenes):
                findings.append(
                    finding(
                        "CLAIM.SIMPLE.REQUIRED_CAMERA",
                        "G4B_EVIDENCE_MINIMUMS",
                        "L2_VISUAL_REPRODUCIBILITY",
                        "ERROR",
                        "REVIEWABILITY_ERROR",
                        f"Claim {claim.id} has no captured camera/view state.",
                        pointer=f"{pointer}/scene_ids",
                        blocks=["archive"],
                        claim_critical=True,
                        waivable=True,
                        fix="Include set_view/camera state, or document why viewpoint is not part of the claim.",
                    )
                )
        if claim.claim_type == ClaimType.selection_highlight:
            selection_ids = _selection_ids_for_claim(semantic, claim)
            if not selection_ids:
                findings.append(
                    finding(
                        "CLAIM.SELECTION.REQUIRED_SELECTION",
                        "G4B_EVIDENCE_MINIMUMS",
                        "L1_SEMANTIC_LINKABILITY",
                        "ERROR",
                        "REVIEWABILITY_ERROR",
                        f"Claim {claim.id} is a selection highlight but no selection is linked to the claim scene.",
                        pointer=f"{pointer}/scene_ids",
                        blocks=["archive"],
                        claim_critical=True,
                        waivable=True,
                        fix="Link the highlighted native selection to this claim, or choose a different claim_type.",
                    )
                )
            for selection_id in selection_ids:
                selection = next((item for item in semantic.selections if item.id == selection_id), None)
                mapped_entities = (
                    [entity for entity in semantic.entities if entity.id in selection.entity_ids]
                    if selection is not None
                    else []
                )
                has_reviewed_identity = any(
                    entity.review_status in {ReviewStatus.confirmed, ReviewStatus.human_accepted}
                    and (
                        _text_is_recorded(entity.stable_identity)
                        or _text_is_recorded(entity.label)
                    )
                    for entity in mapped_entities
                )
                if selection is not None and not has_reviewed_identity:
                    findings.append(
                        finding(
                            "CLAIM.SELECTION.IDENTITY_MISSING",
                            "G4B_EVIDENCE_MINIMUMS",
                            "L1_SEMANTIC_LINKABILITY",
                            "ERROR",
                            "REVIEWABILITY_ERROR",
                            f"Highlighted selection {selection.name} needs an entity mapping or stable identity context.",
                            pointer=f"/selections/{semantic.selections.index(selection)}/entity_ids",
                            blocks=["archive"],
                            claim_critical=True,
                            waivable=True,
                            fix="Map the selection to an entity/residue/ligand entry, or document why the native selector is sufficient.",
                        )
                    )
        if claim.claim_type == ClaimType.ligand_binding_pose and not _has_ligand_evidence(semantic, claim.id):
            findings.append(
                finding(
                    "CLAIM.LIGAND.REQUIRED_CONTACTS",
                    "G4B_EVIDENCE_MINIMUMS",
                    "L3_CLAIM_EVIDENCE",
                    "ERROR",
                    "CLAIM_EVIDENCE_ERROR",
                    "For a ligand-binding panel, add structured contact/distance evidence or linked external validation.",
                    pointer=f"{pointer}/evidence_ids",
                    blocks=["share", "archive"],
                    claim_critical=True,
                    waivable=True,
                    fix="Link a structure plus contact table/measured distances with method and cutoff, or a relevant validation report.",
                )
            )
        if claim.claim_type == ClaimType.ligand_binding_pose:
            linked_evidence = [item for item in semantic.evidence if claim.id in item.claim_ids]
            linked_entity_ids = {
                entity_id for item in linked_evidence for entity_id in item.target_entity_ids
            }
            linked_entities = [item for item in semantic.entities if item.id in linked_entity_ids]
            has_ligand_identity = any(
                item.entity_type.lower() == "ligand" and _text_is_recorded(item.stable_identity)
                for item in linked_entities
            )
            has_site_identity = any(
                item.entity_type.lower() in {"residue", "residue_set", "binding_site", "binding-site"}
                and _text_is_recorded(item.stable_identity)
                for item in linked_entities
            )
            if not (has_ligand_identity and has_site_identity):
                findings.append(
                    finding(
                        "CLAIM.LIGAND.IDENTITY_CONTEXT",
                        "G4B_EVIDENCE_MINIMUMS",
                        "L1_SEMANTIC_LINKABILITY",
                        "ERROR",
                        "CLAIM_EVIDENCE_ERROR",
                        "A ligand-binding claim needs stable ligand and binding-site/residue identities linked to its evidence.",
                        pointer=f"{pointer}/evidence_ids",
                        blocks=["archive"],
                        claim_critical=True,
                        waivable=True,
                        fix="Add ligand and residue entities with stable identities, then target them from the evidence entry.",
                    )
                )
        if claim.claim_type == ClaimType.trajectory_mechanism:
            roles = _package_roles(semantic)
            has_analysis = any(
                _trajectory_analysis_is_complete(semantic, item, claim.id)
                for item in semantic.evidence
            )
            if "trajectory" not in roles or "topology" not in roles or not has_analysis:
                findings.append(
                    finding(
                        "CLAIM.TRAJECTORY.REQUIRED_CONTEXT",
                        "G4B_EVIDENCE_MINIMUMS",
                        "L3_CLAIM_EVIDENCE",
                        "ERROR",
                        "CLAIM_EVIDENCE_ERROR",
                        "A trajectory-mechanism claim needs trajectory, topology and linked trajectory-analysis evidence with method, frame/sampling and replicate context.",
                        pointer=f"{pointer}/evidence_ids",
                        blocks=["share", "archive"],
                        claim_critical=True,
                        waivable=True,
                        fix="Attach trajectory/topology files and record the analysis method, selected frames/sampling window and replicate count.",
                    )
                )
        if claim.claim_type in {ClaimType.cryo_em_map_fit, ClaimType.xray_density_support}:
            package_roles = _package_roles(semantic)
            has_map = "map" in package_roles
            has_structure = "structure" in package_roles
            has_density_evidence = any(
                _density_evidence_is_complete(semantic, item, claim.id)
                for item in semantic.evidence
            )
            if not has_map or not has_structure or not has_density_evidence:
                findings.append(
                    finding(
                        "CLAIM.DENSITY.REQUIRED_CONTEXT",
                        "G4B_EVIDENCE_MINIMUMS",
                        "L3_CLAIM_EVIDENCE",
                        "ERROR",
                        "CLAIM_EVIDENCE_ERROR",
                        "A map/density claim needs an attached map and fitted structure plus linked density/map-fit evidence with method and contour/fit parameters.",
                        pointer=f"{pointer}/evidence_ids",
                        blocks=["share", "archive"],
                        claim_critical=True,
                        waivable=True,
                        fix="Attach the map and fitted structure, then link both from evidence with contour/isovalue and method context.",
                    )
                )
        if claim.claim_type == ClaimType.computed_model_claim:
            has_structure = "structure" in _package_roles(semantic)
            has_validation = any(
                _computed_model_evidence_is_complete(semantic, item, claim.id)
                for item in semantic.evidence
            )
            if not has_structure or not has_validation:
                findings.append(
                    finding(
                        "CLAIM.COMPUTED_MODEL.REQUIRED_VALIDATION",
                        "G4B_EVIDENCE_MINIMUMS",
                        "L3_CLAIM_EVIDENCE",
                        "ERROR",
                        "CLAIM_EVIDENCE_ERROR",
                        "A computed-model claim needs the model plus confidence/validation evidence explicitly linked to that model and claim.",
                        pointer=f"{pointer}/evidence_ids",
                        blocks=["share", "archive"],
                        claim_critical=True,
                        waivable=True,
                        fix="Attach a confidence/validation report and link it as external_validation evidence.",
                    )
                )
        if claim.claim_type == ClaimType.model_comparison:
            structure_count = len(
                _structure_digests_for_source_ids(
                    semantic,
                    {artifact.id for artifact in semantic.artifacts},
                )
            )
            has_comparison_evidence = any(
                _model_comparison_evidence_is_complete(semantic, item, claim.id)
                for item in semantic.evidence
            )
            if structure_count < 2 or not has_comparison_evidence:
                findings.append(
                    finding(
                        "CLAIM.MODEL_COMPARISON.REQUIRED_CONTEXT",
                        "G4B_EVIDENCE_MINIMUMS",
                        "L3_CLAIM_EVIDENCE",
                        "ERROR",
                        "CLAIM_EVIDENCE_ERROR",
                        "A model-comparison claim needs at least two structures and a named comparison method whose evidence links both structure files.",
                        pointer=f"{pointer}/evidence_ids",
                        blocks=["archive"],
                        claim_critical=True,
                        waivable=True,
                        fix="Attach both compared models and record the comparison method/metric.",
                    )
                )
        if claim.claim_type in {
            ClaimType.ligand_binding_pose,
            ClaimType.cryo_em_map_fit,
            ClaimType.xray_density_support,
            ClaimType.trajectory_mechanism,
        } and not claim.uncertainty_ids:
            findings.append(
                finding(
                    "CLAIM.UNCERTAINTY.MISSING",
                    "G4B_EVIDENCE_MINIMUMS",
                    "L3_CLAIM_EVIDENCE",
                    "WARNING",
                    "EVIDENCE_LIMITATION_WARNING",
                    f"Claim {claim.id} would benefit from a short caveat or alternative-explanation note.",
                    pointer=f"{pointer}/uncertainty_ids",
                    blocks=["archive"],
                    waivable=True,
                    fix="Add a caveat, or record a reason that no caveat is needed for this package.",
                )
            )
    return findings


def _selection_ids_for_claim(semantic: SemanticLayer, claim: Any) -> set[str]:
    scene_ids = set(claim.scene_ids)
    return {
        selection_id
        for scene in semantic.scenes
        if not scene_ids or scene.id in scene_ids
        for selection_id in scene.selection_ids
    }


def _has_ligand_evidence(semantic: SemanticLayer, claim_id: str) -> bool:
    for evidence in semantic.evidence:
        if (
            claim_id not in evidence.claim_ids
            or not evidence.source_artifact_ids
            or not _summary_is_recorded(evidence)
            or not _evidence_is_author_reviewed(evidence)
        ):
            continue
        source_roles = _evidence_source_roles(semantic, evidence)
        has_structure = "structure" in source_roles
        has_target = bool(evidence.target_entity_ids or evidence.target_selection_ids)
        has_method = _method_is_recorded(evidence)
        if evidence.evidence_kind == EvidenceKind.contact_table:
            has_contact_source = "contact_table" in source_roles
            has_distance_context = _valid_distance_context(evidence)
            if has_structure and has_contact_source and has_target and has_method and has_distance_context:
                return True
        if evidence.evidence_kind == EvidenceKind.external_validation:
            has_validation_source = bool(
                source_roles & {"validation_report", "evidence_document", "contact_table"}
            )
            if has_structure and has_validation_source and has_target and has_method:
                return True
        if evidence.evidence_kind == EvidenceKind.measurement and _measurement_has_ligand_context(semantic, evidence):
            return True
    return False


def _measurement_has_ligand_context(semantic: SemanticLayer, evidence: Any) -> bool:
    has_structured_measurement = (
        _valid_distance_context(evidence)
        and _method_is_recorded(evidence)
        and _summary_is_recorded(evidence)
        and _evidence_is_author_reviewed(evidence)
    )
    has_target = bool(evidence.target_entity_ids or evidence.target_selection_ids)
    source_roles = _evidence_source_roles(semantic, evidence)
    has_substantive_source = "structure" in source_roles and bool(
        source_roles & {"contact_table", "validation_report", "evidence_document"}
    )
    return has_structured_measurement and has_target and has_substantive_source


def _evidence_source_roles(semantic: SemanticLayer, evidence: Any) -> set[str]:
    source_ids = set(getattr(evidence, "source_artifact_ids", []))
    roles = {
        artifact.role.value
        for artifact in semantic.artifacts
        if artifact.id in source_ids
    }
    for inventory in semantic.mvsx_inventories:
        if inventory.artifact_id in source_ids:
            roles.update(_inventory_roles(semantic, inventory))
    return roles


def _has_packaged_structure(semantic: SemanticLayer) -> bool:
    return "structure" in _package_roles(semantic)


def _package_roles(semantic: SemanticLayer) -> set[str]:
    roles = {artifact.role.value for artifact in semantic.artifacts}
    for inventory in semantic.mvsx_inventories:
        roles.update(_inventory_roles(semantic, inventory))
    return roles


def _inventory_has_structure(semantic: SemanticLayer, inventory: Any) -> bool:
    return "structure" in _inventory_roles(semantic, inventory)


def _inventory_roles(semantic: SemanticLayer, inventory: Any) -> set[str]:
    return {
        role
        for roles in _inventory_member_roles(semantic, inventory).values()
        for role in roles
    }


def _inventory_member_roles(semantic: SemanticLayer, inventory: Any) -> dict[str, set[str]]:
    references = [
        reference
        for reference in semantic.native_references
        if reference.source_location.artifact_id == inventory.artifact_id
        and reference.source_location.json_pointer
    ]
    members_by_id = {
        member.member_id: member
        for member in inventory.members
        if not member.is_dir and is_sha256_digest(member.sha256)
    }
    roles_by_member: dict[str, set[str]] = {}
    trajectory_suffixes = {".xtc", ".dcd", ".trr", ".nc", ".nctraj", ".lammpstrj"}
    topology_suffixes = {".psf", ".prmtop", ".top"}
    for resource in semantic.resource_references:
        if (
            resource.artifact_id != inventory.artifact_id
            or resource.mvsx_member_id not in members_by_id
            or not resource.source_location.json_pointer
        ):
            continue
        pointer_prefix = resource.source_location.json_pointer.rstrip("/") + "/children/"
        descendant_types = {
            reference.ref_type
            for reference in references
            if str(reference.source_location.json_pointer).startswith(pointer_prefix)
        }
        member = members_by_id[resource.mvsx_member_id]
        suffix = Path(member.normalized_name.lower()).suffix
        roles = roles_by_member.setdefault(member.member_id, set())
        if "mvs_structure" in descendant_types:
            roles.add("structure")
        if "mvs_volume" in descendant_types:
            roles.add("map")
        if suffix in trajectory_suffixes:
            roles.add("trajectory")
        if suffix in topology_suffixes:
            roles.add("topology")
    return roles_by_member


def _structure_digests_for_source_ids(
    semantic: SemanticLayer,
    source_ids: set[str],
) -> set[str]:
    digests = {
        str(artifact.sha256).lower()
        for artifact in semantic.artifacts
        if artifact.id in source_ids
        and artifact.role.value == "structure"
        and is_sha256_digest(artifact.sha256)
    }
    for inventory in semantic.mvsx_inventories:
        if inventory.artifact_id not in source_ids:
            continue
        roles_by_member = _inventory_member_roles(semantic, inventory)
        digests.update(
            str(member.sha256).lower()
            for member in inventory.members
            if "structure" in roles_by_member.get(member.member_id, set())
            and is_sha256_digest(member.sha256)
        )
    return digests


def _method_is_recorded(evidence: Any) -> bool:
    return _text_is_recorded(getattr(evidence, "method_name", ""))


def _summary_is_recorded(evidence: Any) -> bool:
    return _text_is_recorded(getattr(evidence, "result_summary", ""))


def _text_is_recorded(value: Any) -> bool:
    if value is None:
        return False
    normalized = str(value).strip().lower()
    return (
        bool(normalized)
        and normalized
        not in {
            "unknown",
            "unspecified",
            "todo",
            "tbd",
            "none",
            "null",
            "n/a",
            "na",
            "not applicable",
            "not_applicable",
        }
        and not normalized.startswith(("todo", "tbd"))
    )


def _evidence_is_author_reviewed(evidence: Any) -> bool:
    return (
        getattr(evidence, "review_status", None)
        in {ReviewStatus.confirmed, ReviewStatus.human_accepted}
        and _text_is_recorded(getattr(evidence, "reviewer", ""))
        and _is_rfc3339_timestamp(getattr(evidence, "reviewed_at", None))
    )


def _uncertainty_is_complete(uncertainty: Any) -> bool:
    return (
        _text_is_recorded(getattr(uncertainty, "statement", ""))
        and getattr(uncertainty, "review_status", None)
        in {ReviewStatus.confirmed, ReviewStatus.human_accepted}
        and _text_is_recorded(getattr(uncertainty, "reviewer", ""))
        and _is_rfc3339_timestamp(getattr(uncertainty, "reviewed_at", None))
    )


def _is_rfc3339_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
        value,
    ):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _visual_semantics_is_author_reviewed(item: Any) -> bool:
    if not _text_is_recorded(getattr(item, "reviewer", "")) or not _is_rfc3339_timestamp(
        getattr(item, "reviewed_at", None)
    ):
        return False
    if item.meaning_status == MeaningStatus.user_confirmed_meaning:
        return _text_is_recorded(getattr(item, "meaning", ""))
    if item.meaning_status == MeaningStatus.user_declared_no_scientific_meaning:
        return _text_is_recorded(getattr(item, "no_scientific_meaning_reason", ""))
    return False


def _valid_distance_context(evidence: Any) -> bool:
    threshold = getattr(evidence, "thresholds", {}).get("distance")
    unit = str(getattr(evidence, "units", {}).get("distance", "")).strip().lower()
    if unit in {"", "unknown", "unspecified"}:
        return False
    if isinstance(threshold, bool):
        return False
    try:
        return float(threshold) > 0
    except (TypeError, ValueError):
        return False


def _parameter_names(evidence: Any) -> set[str]:
    return {
        str(key).strip().lower().replace("-", "_").replace(" ", "_")
        for key, value in getattr(evidence, "parameters", {}).items()
        if _context_value_is_recorded(value)
    }


def _context_value_is_recorded(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return _text_is_recorded(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, (dict, list, tuple, set)):
        return bool(value)
    return True


def _density_context_is_recorded(evidence: Any) -> bool:
    relevant = {
        "contour",
        "contour_level",
        "contour_sigma",
        "isovalue",
        "iso_value",
        "map_threshold",
        "fit_metric",
        "map_model_correlation",
        "correlation_coefficient",
        "fsc",
        "resolution",
    }
    values = {
        str(key).strip().lower().replace("-", "_").replace(" ", "_"): value
        for source in (getattr(evidence, "thresholds", {}), getattr(evidence, "parameters", {}))
        for key, value in source.items()
    }
    return any(name in relevant and _context_value_is_recorded(value) for name, value in values.items())


def _trajectory_analysis_is_complete(semantic: SemanticLayer, evidence: Any, claim_id: str) -> bool:
    if evidence.evidence_kind != EvidenceKind.trajectory_analysis or claim_id not in evidence.claim_ids:
        return False
    roles = _evidence_source_roles(semantic, evidence)
    names = _parameter_names(evidence)
    has_frame_context = bool(
        names
        & {
            "frame",
            "frames",
            "frame_range",
            "frame_selection",
            "selected_frames",
            "sampling",
            "sampling_window",
            "time_range",
        }
    )
    has_replicate_context = _replicate_context_is_recorded(evidence)
    return (
        {"trajectory", "topology"} <= roles
        and _method_is_recorded(evidence)
        and _summary_is_recorded(evidence)
        and _evidence_is_author_reviewed(evidence)
        and has_frame_context
        and has_replicate_context
    )


def _replicate_context_is_recorded(evidence: Any) -> bool:
    parameters = {
        str(key).strip().lower().replace("-", "_").replace(" ", "_"): value
        for key, value in getattr(evidence, "parameters", {}).items()
    }
    for name in {"replicate", "replicates", "replica", "replicas"}:
        if name in parameters and _context_value_is_recorded(parameters[name]):
            return True
    for name in {"replicate_count", "n_replicates"}:
        if name not in parameters:
            continue
        value = parameters[name]
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if not isinstance(value, bool) and count >= 1 and str(value).strip() == str(count):
            return True
    return False


def _density_evidence_is_complete(semantic: SemanticLayer, evidence: Any, claim_id: str) -> bool:
    if (
        evidence.evidence_kind not in {EvidenceKind.density_support, EvidenceKind.map_fit_metric}
        or claim_id not in evidence.claim_ids
    ):
        return False
    roles = _evidence_source_roles(semantic, evidence)
    return (
        {"map", "structure"} <= roles
        and _method_is_recorded(evidence)
        and _density_context_is_recorded(evidence)
        and _summary_is_recorded(evidence)
        and _evidence_is_author_reviewed(evidence)
    )


def _computed_model_evidence_is_complete(semantic: SemanticLayer, evidence: Any, claim_id: str) -> bool:
    if evidence.evidence_kind != EvidenceKind.external_validation or claim_id not in evidence.claim_ids:
        return False
    roles = _evidence_source_roles(semantic, evidence)
    return (
        "structure" in roles
        and bool(roles & {"validation_report", "evidence_document"})
        and _method_is_recorded(evidence)
        and _summary_is_recorded(evidence)
        and _evidence_is_author_reviewed(evidence)
    )


def _model_comparison_evidence_is_complete(semantic: SemanticLayer, evidence: Any, claim_id: str) -> bool:
    if claim_id not in evidence.claim_ids or not _method_is_recorded(evidence):
        return False
    linked_structure_digests = _structure_digests_for_source_ids(
        semantic,
        set(evidence.source_artifact_ids),
    )
    return (
        len(linked_structure_digests) >= 2
        and _summary_is_recorded(evidence)
        and _evidence_is_author_reviewed(evidence)
    )


def _visibility_findings(semantic: SemanticLayer) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    critical_entities = {entity.id for entity in semantic.entities if entity.claim_critical}
    critical_selections = {selection.id for selection in semantic.selections if selection.claim_critical}
    for scene_index, scene in enumerate(semantic.scenes):
        for visibility_index, record in enumerate(scene.visibility):
            critical = (record.entity_id in critical_entities) or (record.selection_id in critical_selections)
            if critical and record.state in {"hidden", "excluded"} and not record.reason:
                findings.append(
                    finding(
                        "SCENE.HIDDEN.CRITICAL_REASON",
                        "G5_VISIBILITY",
                        "L2_VISUAL_REPRODUCIBILITY",
                        "ERROR",
                        "DISCLOSURE_WARNING",
                        "A figure-central hidden or excluded object needs a short explanation.",
                        pointer=f"/scenes/{scene_index}/visibility/{visibility_index}/reason",
                        blocks=["archive"],
                        claim_critical=True,
                        waivable=True,
                        fix="Add a short reason for hiding/excluding it, or revise the scene.",
                    )
                )
    return findings


def _native_scene_anchor_findings(semantic: SemanticLayer, mode: str) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    if mode not in {"share", "archive"}:
        return findings
    for index, raw in enumerate(semantic.raw_native_observations):
        if raw.resolution in {"no_scene_effect", "reviewed_no_claim_impact", "not_applicable"}:
            continue
        if raw.claim_critical in {ClaimCriticalStatus.true, ClaimCriticalStatus.unknown}:
            rule_id = "IMPORT.NATIVE.RAW_AFFECTS_SCENE"
            if "pymol" in raw.raw_id or raw.reason.startswith(("unknown_pymol", "pymol_", "dynamic_or_executable_pymol")):
                rule_id = "IMPORT.PYMOL.RAW_AFFECTS_SCENE"
            elif "chimerax" in raw.raw_id or raw.reason.startswith(("unknown_chimerax", "dynamic_or_executable_chimerax")):
                rule_id = "IMPORT.CXC.RAW_AFFECTS_SCENE"
            if raw.reason.startswith("unknown_mvs") or raw.reason.startswith("invalid_mvs"):
                rule_id = "IMPORT.MVS.UNKNOWN_NODE"
            findings.append(
                finding(
                    rule_id,
                    "G6_NATIVE_STATIC_IMPORT",
                    "L2_VISUAL_REPRODUCIBILITY",
                    "ERROR" if mode == "archive" or raw.claim_critical == ClaimCriticalStatus.true else "WARNING",
                    "REVIEWABILITY_ERROR",
                    f"Native content was preserved for author review: {raw.reason}.",
                    pointer=f"/raw_native_observations/{index}",
                    blocks=["archive"] if raw.claim_critical == ClaimCriticalStatus.unknown else ["share", "archive"],
                    claim_critical=raw.claim_critical != ClaimCriticalStatus.false,
                    waivable=True,
                    fix="Mark whether this item affects the figure, or record a reason to leave it as-is.",
                )
            )
    for index, ref in enumerate(semantic.native_references):
        if ref.claim_critical == ClaimCriticalStatus.true and ref.identity_status != "resolved":
            findings.append(
                finding(
                    "SCENE.MOLECULAR_IDENTITY_UNCONFIRMED",
                    "G6_NATIVE_STATIC_IMPORT",
                    "L1_SEMANTIC_LINKABILITY",
                    "ERROR",
                    "REVIEWABILITY_ERROR",
                    f"Name the molecule, chain, residue or file behind this native reference: {ref.native_expression}.",
                    pointer=f"/native_references/{index}",
                    blocks=["share", "archive"],
                    claim_critical=True,
                    waivable=True,
                    fix="Add a reader-friendly identity for this reference, or record why it is not needed.",
                )
            )
        if ref.claim_critical == ClaimCriticalStatus.true and ref.target_resolution_status.value != "resolved_against_artifact":
            findings.append(
                finding(
                    "SCENE.TARGET_RESOLUTION_INCOMPLETE",
                    "G6_NATIVE_STATIC_IMPORT",
                    "L1_SEMANTIC_LINKABILITY",
                    "ERROR",
                    "REVIEWABILITY_ERROR",
                    f"This figure-central native reference has not been matched to a package file: {ref.native_expression}.",
                    pointer=f"/native_references/{index}/target_resolution_status",
                    blocks=["archive"],
                    claim_critical=True,
                    waivable=True,
                    fix="Mark it resolved_against_artifact after linking the relevant package file, or record why it is not needed.",
                )
            )
    answered_ops = {
        operation_id
        for item in semantic.visual_encoding_semantics
        if _visual_semantics_is_author_reviewed(item)
        for operation_id in item.operation_ids
    }
    for index, operation in enumerate(semantic.observed_scene_operations):
        needs_author_review = (
            operation.meaning_status == MeaningStatus.requires_user_completion
            or operation.needs_author_confirmation
            or operation.claim_critical == ClaimCriticalStatus.true
            or (
                operation.meaning_status == MeaningStatus.tool_suggested_meaning
                and operation.claim_critical == ClaimCriticalStatus.unknown
                and _operation_has_visual_candidate(operation)
            )
            or _operation_likely_ligand_claim_central(semantic, operation)
        )
        if (
            operation.claim_critical != ClaimCriticalStatus.false
            and needs_author_review
            and operation.operation_id not in answered_ops
        ):
            findings.append(
                finding(
                    "SCENE.VISUAL_ENCODING.MEANING_MISSING",
                    "G6_NATIVE_STATIC_IMPORT",
                    "L2_VISUAL_REPRODUCIBILITY",
                    "ERROR",
                    "REVIEWABILITY_ERROR",
                    f"Confirm or edit the suggested meaning of this visual encoding, or mark it as presentation only: {operation.operation_id}.",
                    pointer=f"/observed_scene_operations/{index}",
                    blocks=["archive"],
                    claim_critical=True,
                    waivable=True,
                    fix="Confirm the matching operation in `scene_semantics_by_operation`, edit the meaning, or mark it as presentation only.",
                )
            )
    for index, resource in enumerate(semantic.resource_references):
        if (
            resource.claim_critical in {ClaimCriticalStatus.true, ClaimCriticalStatus.unknown}
            and resource.uri_kind in {"remote", "file", "unknown", "relative", "missing_archive_member"}
            and not _resource_has_verifiable_fixity(semantic, resource)
        ):
            missing_archive_member = resource.uri_kind == "missing_archive_member"
            display_uri = resource_uri_summary(resource.uri)
            message = (
                f"This referenced file is missing from the MVSX archive: {display_uri}."
                if missing_archive_member
                else f"This resource needs a local file, checksum or documented reason before archive export: {display_uri}."
            )
            fix = (
                "Rebuild the MVSX with the file at the referenced archive path; an external sibling file does not make the archive self-contained."
                if missing_archive_member
                else "Attach the resource, record an expected checksum, or record why it can remain detached."
            )
            findings.append(
                finding(
                    (
                        "IMPORT.MVSX.MEMBER_MISSING"
                        if missing_archive_member
                        else "IMPORT.REMOTE_RESOURCE_DETACHED"
                    ),
                    "G6_NATIVE_STATIC_IMPORT",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "DISCLOSURE_WARNING",
                    message,
                    pointer=f"/resource_references/{index}",
                    blocks=["archive"] if resource.claim_critical == ClaimCriticalStatus.unknown else ["share", "archive"],
                    claim_critical=resource.claim_critical != ClaimCriticalStatus.false,
                    waivable=True,
                    fix=fix,
                )
            )
    return findings


def _resource_has_verifiable_fixity(semantic: SemanticLayer, resource: Any) -> bool:
    if resource.uri_kind == "data":
        return True
    if resource.uri_kind in {"relative", "local"}:
        return any(
            artifact.kind in {ArtifactKind.local_attached, ArtifactKind.local_detached}
            and is_sha256_digest(artifact.sha256)
            and getattr(artifact.role, "value", artifact.role) != "directory"
            and artifact.format != "inode/directory"
            and (
                artifact.kind == ArtifactKind.local_attached
                and artifact.included
                or artifact.kind == ArtifactKind.local_detached
                and not artifact.included
            )
            for artifact in resource_matching_artifacts(
                semantic,
                resource.uri,
                resource_ref=resource,
            )
        )
    if resource.uri_kind == "archive_member" and resource.mvsx_member_id:
        return any(
            inventory.artifact_id == resource.artifact_id
            and any(
                member.member_id == resource.mvsx_member_id
                and not member.is_dir
                and is_sha256_digest(member.sha256)
                for member in inventory.members
            )
            for inventory in semantic.mvsx_inventories
        )
    if resource.uri_kind == "remote":
        return any(
            artifact.kind == ArtifactKind.remote
            and artifact.url == resource.uri
            and is_sha256_digest(artifact.sha256)
            for artifact in semantic.artifacts
        )
    return False


def _operation_likely_ligand_claim_central(semantic: SemanticLayer, operation: Any) -> bool:
    if not any(claim.claim_type == ClaimType.ligand_binding_pose for claim in semantic.claims):
        return False
    if getattr(operation, "operation", "") not in {"colored", "labeled"}:
        return False
    text = " ".join(
        str(value)
        for value in [
            getattr(operation, "target", ""),
            getattr(operation, "candidate_meaning", ""),
            getattr(operation, "auto_annotation", ""),
        ]
    ).lower()
    return any(token in text for token in ["ligand", "pocket", "binding-site", "binding site"])


def _operation_has_visual_candidate(operation: Any) -> bool:
    candidate = str(getattr(operation, "candidate_meaning", "") or "")
    if (
        candidate
        and "no scientific meaning is inferred" in candidate.lower()
        and not getattr(operation, "needs_author_confirmation", False)
    ):
        return False
    return getattr(operation, "operation", "") in {"colored", "labeled"} and bool(candidate)

def _privacy_findings(root: Path, semantic: SemanticLayer, mode: str) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    if mode not in {"share", "archive"}:
        return findings
    data = semantic.model_dump(mode="json")
    for pointer, value in _walk_json(data):
        if not isinstance(value, str):
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(value):
                findings.append(
                    finding(
                        "SECURITY.PATH.PRIVACY",
                        "G7_EXPORT_READY",
                        "L0_PACKAGE_INTEGRITY",
                        "ERROR",
                        "SECURITY_BLOCKER",
                        "Package text may include a local path, email address or token-like value.",
                        pointer=pointer,
                        blocks=["share", "archive"],
                        fix="Remove or redact sensitive text before export.",
                    )
                )
                break
    for file_path in safe_walk(root):
        relative = file_path.relative_to(root.resolve()).as_posix()
        if relative == SEMANTIC_LAYER_FILENAME:
            continue
        try:
            if not file_path.is_file() or file_path.stat().st_size > MAX_PRIVACY_SCAN_BYTES:
                continue
            payload = file_path.read_bytes()
            if b"\x00" in payload:
                continue
            text = payload.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            findings.append(
                finding(
                    "SECURITY.PATH.PRIVACY",
                    "G7_EXPORT_READY",
                    "L0_PACKAGE_INTEGRITY",
                    "ERROR",
                    "SECURITY_BLOCKER",
                    f"Package text may contain a private path, email address or token-like value: {relative}.",
                    pointer=f"/{relative}",
                    blocks=["share", "archive"],
                    fix="Review and redact this package text before sharing.",
                )
            )
    return findings


def _walk_json(value: Any, pointer: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            yield from _walk_json(child, f"{pointer}/{escaped}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_json(child, f"{pointer}/{index}")
    else:
        yield pointer or "/", value


def _apply_waivers(findings: list[ValidationFinding], semantic: SemanticLayer, mode: str) -> None:
    for item in findings:
        finding_anchor = _finding_anchor_id(item, semantic)
        for index, waiver in enumerate(semantic.provenance.waivers):
            if (
                not _text_is_recorded(waiver.reason)
                or not _text_is_recorded(waiver.reviewer)
                or not _is_rfc3339_timestamp(waiver.reviewed_at or waiver.timestamp)
            ):
                continue
            if waiver.anchor_id is not None and waiver.anchor_id != finding_anchor:
                continue
            if waiver.anchor_id is None and waiver.scope not in {"package", "global", "all"}:
                continue
            if waiver.rule_id == item.rule_id and item.waivable and waiver_covers(waiver.max_export_mode, mode):
                item.status = "WAIVED"
                item.waiver_id = f"waiver:{index}"
                break


def _finding_anchor_id(item: ValidationFinding, semantic: SemanticLayer) -> str | None:
    parts = item.json_pointer.strip("/").split("/")
    if len(parts) < 2:
        return None
    collection_name, index_text = parts[:2]
    try:
        collection = getattr(semantic, collection_name)
        anchored = collection[int(index_text)]
    except (AttributeError, IndexError, TypeError, ValueError):
        return None
    for attribute in (
        "id",
        "raw_id",
        "operation_id",
        "native_ref_id",
        "resource_ref_id",
        "binding_id",
    ):
        value = getattr(anchored, attribute, None)
        if value:
            return str(value)
    return None


def _report(
    package_id: str,
    semantic_ref: SemanticLayerRef,
    mode: str,
    findings: list[ValidationFinding],
    semantic: SemanticLayer | None,
    root: Path,
    revalidation: dict[str, object] | None = None,
) -> ValidationReport:
    summary = {"errors": 0, "warnings": 0, "info": 0}
    blocking_errors = 0
    warnings = 0
    for item in findings:
        if item.severity == "ERROR":
            summary["errors"] += 1
            if item.status != "WAIVED" and mode in item.blocks_modes:
                blocking_errors += 1
        elif item.severity == "WARNING":
            summary["warnings"] += 1
            if item.status != "WAIVED":
                warnings += 1
        else:
            summary["info"] += 1
    status = "fail" if blocking_errors else "pass_with_warnings" if warnings else "pass"
    return ValidationReport(
        package_id=package_id,
        semantic_layer_ref=semantic_ref,
        export_mode=mode,
        overall_status=status,
        validation_levels=_levels(),
        summary=summary,
        findings=findings,
        claim_traceability_matrix=_traceability_matrix(semantic),
        artifact_fixity=_artifact_fixity(root, semantic),
        entity_evidence_matrix=_entity_evidence_matrix(semantic),
        unresolved_list=_unresolved(semantic),
        native_inference_limits=[
            "Native viewer files were parsed statically; the viewer was not run, so successful loading, non-empty selections and rendered pixels were not runtime-verified.",
            "Visualization operations are context, not scientific support; support comes from claim-linked evidence files and author-reviewed notes.",
            "Distance commands are measurement intent and are not automatically classified as hydrogen bonds or contacts.",
            "Selection names such as active_site remain native labels until confirmed by the author.",
            "A color ramp over atom field b does not identify whether the values are crystallographic B-factors, pLDDT or custom values.",
            "Automatic privacy scanning covers package metadata and UTF-8 text attachments up to 2 MiB; binary and larger files still need manual review.",
        ],
        evidence_minimums_by_profile=_evidence_minimums(),
        human_review_required=_human_review_required(semantic),
        visual_context_audit=_visual_context_audit(semantic),
        waiver_list=[waiver.model_dump(mode="json") for waiver in semantic.provenance.waivers] if semantic else [],
        revalidation=revalidation or {"performed_on_exported_package": False, "status": "not_performed"},
    )


def _levels() -> list[dict[str, object]]:
    return [
        {"level": "L0_PACKAGE_INTEGRITY", "name": "Package integrity"},
        {"level": "L1_SEMANTIC_LINKABILITY", "name": "Semantic linkability"},
        {"level": "L2_VISUAL_REPRODUCIBILITY", "name": "Visual reproducibility"},
        {"level": "L3_CLAIM_EVIDENCE", "name": "Claim evidence context"},
        {"level": "L4_REVIEW_PACKAGE", "name": "Reviewer package usability"},
    ]


def _traceability_matrix(semantic: SemanticLayer | None) -> list[dict[str, object]]:
    if semantic is None:
        return []
    matrix = []
    for index, claim in enumerate(semantic.claims):
        evidence_ids = claim.evidence_ids
        entity_ids = sorted(
            {
                entity_id
                for evidence in semantic.evidence
                if evidence.id in evidence_ids
                for entity_id in evidence.target_entity_ids
            }
        )
        matrix.append(
            {
                "claim_id": claim.id,
                "claim_text": claim.claim_text.value,
                "claim_type": claim.claim_type.value,
                "figure_ref": claim.figure_ref,
                "claim_status": claim.claim_status,
                "review_status": claim.review_status.value,
                "scene_ids": claim.scene_ids,
                "render_artifact_ids": sorted(
                    {
                        artifact_id
                        for scene in semantic.scenes
                        if scene.id in claim.scene_ids
                        for artifact_id in scene.render_artifact_ids
                    }
                ),
                "native_artifact_ids": sorted(
                    {
                        artifact_id
                        for scene in semantic.scenes
                        if scene.id in claim.scene_ids
                        for artifact_id in scene.native_artifact_ids
                    }
                ),
                "selection_ids": sorted(
                    {
                        selection_id
                        for scene in semantic.scenes
                        if scene.id in claim.scene_ids
                        for selection_id in scene.selection_ids
                    }
                ),
                "entity_ids": entity_ids,
                "critical_entity_visibility": "unknown",
                "evidence_ids": evidence_ids,
                "uncertainty_ids": claim.uncertainty_ids,
                "required_evidence_status": "complete" if _claim_evidence_complete(semantic, claim) else "missing",
                "recommended_evidence_status": "partial",
                "blocking_findings": [],
                "json_pointer": f"/claims/{index}",
            }
        )
    return matrix


def _artifact_fixity(root: Path, semantic: SemanticLayer | None) -> list[dict[str, object]]:
    if semantic is None:
        return []
    rows = []
    for artifact in semantic.artifacts:
        exists = False
        actual_sha = None
        if artifact.path and artifact.kind == ArtifactKind.local_attached:
            try:
                path = resolve_package_path(root, artifact.path)
                exists = path.exists()
                actual_sha = (
                    sha256_directory(path)
                    if path.is_dir()
                    else sha256_file(path)
                    if path.is_file()
                    else None
                )
            except Exception:
                exists = False
        if artifact.kind == ArtifactKind.local_attached:
            status = (
                "pass"
                if exists
                and is_sha256_digest(artifact.sha256)
                and actual_sha == artifact.sha256
                else "fail"
            )
        elif is_sha256_digest(artifact.sha256):
            status = "expected_only"
        else:
            status = "unavailable"
        rows.append(
            {
                "artifact_id": artifact.id,
                "path": artifact.path,
                "url": artifact.url,
                "role": artifact.role.value,
                "kind": artifact.kind.value,
                "exists": exists,
                "expected_sha256": artifact.sha256,
                "actual_sha256": actual_sha,
                "status": status,
            }
        )
    return rows


def _entity_evidence_matrix(semantic: SemanticLayer | None) -> list[dict[str, object]]:
    if semantic is None:
        return []
    rows = []
    for entity in semantic.entities:
        evidence_ids = [
            evidence.id for evidence in semantic.evidence if entity.id in evidence.target_entity_ids
        ]
        rows.append(
            {
                "entity_id": entity.id,
                "label": entity.label,
                "claim_critical": entity.claim_critical,
                "stable_identity": entity.stable_identity,
                "evidence_ids": evidence_ids,
                "status": "linked" if evidence_ids else "unlinked",
            }
        )
    return rows


def _unresolved(semantic: SemanticLayer | None) -> list[dict[str, object]]:
    if semantic is None:
        return []
    unresolved = []
    for pointer, value in _walk_json(semantic.model_dump(mode="json")):
        if value in {"unknown", "needs_review"}:
            unresolved.append({"json_pointer": pointer, "value": value})
    return unresolved


def _evidence_minimums() -> list[dict[str, object]]:
    return [
        {
            "claim_type": "simple_structure_view",
            "minimum": ["native artifact", "structure artifact", "scene/camera", "render output", "sha256"],
        },
        {
            "claim_type": "ligand_binding_pose",
            "minimum": [
                "ligand stable ID",
                "binding-site residue stable IDs",
                "contact/distance evidence artifact",
                "method/threshold/units",
                "uncertainty or alternative-pose statement",
            ],
        },
        {
            "claim_type": "trajectory_mechanism",
            "minimum": ["trajectory", "topology", "trajectory analysis", "replicate/frame/method context"],
        },
        {
            "claim_type": "cryo_em_map_fit/xray_density_support",
            "minimum": ["map artifact", "density or map-fit evidence", "contour/method parameters"],
        },
        {
            "claim_type": "computed_model_claim",
            "minimum": ["computed structure", "confidence or validation evidence"],
        },
        {
            "claim_type": "model_comparison",
            "minimum": ["two structure artifacts", "comparison evidence linked to both"],
        },
    ]


def _claim_evidence_complete(semantic: SemanticLayer, claim: Any) -> bool:
    if not claim.evidence_ids:
        return False
    if claim.claim_type == ClaimType.ligand_binding_pose:
        return _has_ligand_evidence(semantic, claim.id)
    if claim.claim_type == ClaimType.trajectory_mechanism:
        roles = {artifact.role.value for artifact in semantic.artifacts}
        return {"trajectory", "topology"} <= roles and any(
            _trajectory_analysis_is_complete(semantic, item, claim.id)
            for item in semantic.evidence
        )
    if claim.claim_type in {ClaimType.cryo_em_map_fit, ClaimType.xray_density_support}:
        roles = {artifact.role.value for artifact in semantic.artifacts}
        return {"map", "structure"} <= roles and any(
            _density_evidence_is_complete(semantic, item, claim.id)
            for item in semantic.evidence
        )
    if claim.claim_type == ClaimType.computed_model_claim:
        return any(artifact.role.value == "structure" for artifact in semantic.artifacts) and any(
            _computed_model_evidence_is_complete(semantic, item, claim.id)
            for item in semantic.evidence
        )
    if claim.claim_type == ClaimType.model_comparison:
        return sum(1 for artifact in semantic.artifacts if artifact.role.value == "structure") >= 2 and any(
            _model_comparison_evidence_is_complete(semantic, item, claim.id)
            for item in semantic.evidence
        )
    return any(
        item.id in claim.evidence_ids
        and claim.id in item.claim_ids
        and bool(item.source_artifact_ids)
        and _summary_is_recorded(item)
        and _evidence_is_author_reviewed(item)
        for item in semantic.evidence
    )


def _human_review_required(semantic: SemanticLayer | None) -> list[dict[str, object]]:
    if semantic is None:
        return []
    rows = []
    for pointer, value in _walk_json(semantic.model_dump(mode="json")):
        if value == "needs_review":
            rows.append({"json_pointer": pointer, "reason": "Field requires human review."})
    return rows


def _visual_context_audit(semantic: SemanticLayer | None) -> list[dict[str, object]]:
    if semantic is None:
        return []
    rows = []
    for scene in semantic.scenes:
        for record in scene.visibility:
            rows.append(
                {
                    "scene_id": scene.id,
                    "entity_id": record.entity_id,
                    "selection_id": record.selection_id,
                    "native_target": record.native_target,
                    "state": record.state,
                    "reason": record.reason,
                    "review_status": record.review_status.value,
                }
            )
    return rows
