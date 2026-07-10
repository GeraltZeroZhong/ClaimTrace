"""Artifact registration."""

from __future__ import annotations

import hashlib
import mimetypes
import posixpath
from pathlib import Path
from uuid import uuid4

from claimtrace.models import Artifact, SemanticLayer
from claimtrace.models.semantic_layer import ArtifactKind, ArtifactRole, ReviewStatus
from claimtrace.errors import PackageError
from claimtrace.package.checksums import file_size, sha256_file
from claimtrace.package.layout import copy_into_package, validate_artifact_source
from claimtrace.package.paths import ensure_relative_path, resolve_package_path


ROLE_DIRS = {
    ArtifactRole.native_script: "native",
    ArtifactRole.native_session: "native",
    ArtifactRole.chimerax_script: "native",
    ArtifactRole.molviewspec: "native",
    ArtifactRole.render_image: "renders",
    ArtifactRole.structure: "data/structures",
    ArtifactRole.map: "data/maps",
    ArtifactRole.trajectory: "data/trajectories",
    ArtifactRole.topology: "data/trajectories",
    ArtifactRole.contact_table: "evidence",
    ArtifactRole.validation_report: "evidence",
    ArtifactRole.evidence_document: "evidence",
    ArtifactRole.directory: "data",
    ArtifactRole.generic: "data",
}


def infer_role(path: Path, requested: str | None = None) -> ArtifactRole:
    if requested:
        return ArtifactRole(requested)
    suffix = path.suffix.lower()
    if suffix == ".pml":
        return ArtifactRole.native_script
    if suffix == ".pse":
        return ArtifactRole.native_session
    if suffix == ".cxc":
        return ArtifactRole.chimerax_script
    if suffix in {".mvsj", ".mvsx"}:
        return ArtifactRole.molviewspec
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".webp", ".svg"}:
        return ArtifactRole.render_image
    if suffix in {".pdb", ".cif", ".mmcif", ".bcif"}:
        return ArtifactRole.structure
    if suffix in {".map", ".mrc", ".ccp4"}:
        return ArtifactRole.map
    if suffix in {".xtc", ".dcd", ".trr", ".nc"}:
        return ArtifactRole.trajectory
    if suffix in {".csv", ".tsv"} and "contact" in path.name.lower():
        return ArtifactRole.contact_table
    if suffix == ".pdf" and "validation" in path.name.lower():
        return ArtifactRole.validation_report
    return ArtifactRole.directory if path.is_dir() else ArtifactRole.generic


def media_type_for(path: Path) -> str:
    media, _ = mimetypes.guess_type(path.name)
    return media or "application/octet-stream"


def artifact_id_for(path: Path, digest: str | None = None) -> str:
    if digest:
        return f"artifact:{digest[:12]}"
    return f"artifact:{uuid4().hex[:12]}"


def _unique_artifact_id(
    semantic: SemanticLayer,
    path: Path,
    digest: str | None,
    identity: str,
) -> str:
    base = artifact_id_for(path, digest)
    existing_ids = {artifact.id for artifact in semantic.artifacts}
    if base not in existing_ids:
        return base
    suffix = hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()[:8]
    candidate = f"{base}-{suffix}"
    counter = 2
    while candidate in existing_ids:
        candidate = f"{base}-{suffix}-{counter}"
        counter += 1
    return candidate


def destination_for(role: ArtifactRole, source: Path) -> str:
    base = ROLE_DIRS.get(role, "data")
    return f"{base}/{source.name}"


def replay_destination_for(semantic: SemanticLayer, source: Path) -> str | None:
    """Return a package path that preserves a native file's relative load URI.

    Native scripts remain byte-for-byte unchanged. When an attached local file
    satisfies a relative resource reference, co-locating it under the native
    script's package directory keeps `load model.cif` replayable.
    """

    source_text = source.as_posix().replace("\\", "/")
    for resource in semantic.resource_references:
        if resource.uri_kind not in {"relative", "local"} or not resource.artifact_id:
            continue
        uri = str(resource.uri).strip().replace("\\", "/")
        if not uri or uri.startswith(("/", "~")) or ":" in uri.split("/", 1)[0]:
            continue
        if source.name != Path(uri).name and not source_text.endswith("/" + uri):
            continue
        native = next(
            (artifact for artifact in semantic.artifacts if artifact.id == resource.artifact_id),
            None,
        )
        if native is None or not native.path:
            continue
        native_parent = Path(str(native.path).replace("\\", "/")).parent.as_posix()
        candidate = posixpath.normpath(posixpath.join(native_parent, uri))
        try:
            ensure_relative_path(candidate)
        except Exception:
            continue
        if candidate.startswith("../") or candidate == "..":
            continue
        return candidate
    return None


def register_local_artifact(
    root: Path,
    semantic: SemanticLayer,
    source: Path,
    role: str | ArtifactRole | None = None,
    *,
    copy: bool = True,
    detached: bool = False,
    relative_destination: str | None = None,
) -> Artifact:
    source = Path(source)
    validate_artifact_source(source)
    requested_role = ArtifactRole(role) if role is not None else infer_role(source)
    if source.is_dir():
        digest = None
        size = None
    else:
        digest = sha256_file(source)
        size = file_size(source)
    relative_path = (
        relative_destination
        if copy and relative_destination is not None
        else destination_for(requested_role, source)
        if copy
        else source.as_posix()
    )
    ensure_relative_path(relative_path)
    target_path = source
    existing = find_artifact_by_path(semantic, relative_path)
    if existing:
        if copy:
            target = resolve_package_path(root, relative_path)
            same_file = target.exists() and source.exists() and source.resolve() == target.resolve()
            same_digest = existing.sha256 == digest if digest else False
            if not same_file and not same_digest:
                raise PackageError(
                    f"Artifact path already exists in package: {relative_path}. "
                    "Rename one file or choose a different role/path before adding it."
                )
        existing.role = requested_role
        existing.sha256 = digest
        existing.byte_size = size
        existing.kind = ArtifactKind.local_detached if detached else ArtifactKind.local_attached
        existing.included = not detached
        existing.format = "inode/directory" if source.is_dir() else media_type_for(source)
        existing.media_type = existing.format
        return existing
    if copy and not detached:
        target_path = copy_into_package(root, source, relative_path)
        if not target_path.is_dir():
            digest = sha256_file(target_path)
            size = file_size(target_path)
    elif not detached:
        target_path = resolve_package_path(root, relative_path)
    artifact = Artifact(
        id=_unique_artifact_id(semantic, source, digest, relative_path),
        kind=ArtifactKind.local_detached if detached else ArtifactKind.local_attached,
        role=requested_role,
        path=relative_path,
        format="inode/directory" if source.is_dir() else media_type_for(source),
        media_type=None if source.is_dir() else media_type_for(source),
        sha256=digest,
        byte_size=size,
        included=not detached,
        review_status=ReviewStatus.auto_extracted,
        fixity_status="unavailable" if detached and digest is None else "available",
    )
    semantic.artifacts.append(artifact)
    return artifact


def register_remote_artifact(
    semantic: SemanticLayer,
    url: str,
    role: str | ArtifactRole | None = None,
    *,
    expected_sha256: str | None = None,
) -> Artifact:
    requested_role = ArtifactRole(role) if role is not None else ArtifactRole.generic
    existing = next((artifact for artifact in semantic.artifacts if artifact.url == url), None)
    if existing:
        return existing
    artifact = Artifact(
        id=_unique_artifact_id(semantic, Path(url), expected_sha256, url),
        kind=ArtifactKind.remote,
        role=requested_role,
        url=url,
        format="remote",
        media_type=None,
        sha256=expected_sha256,
        byte_size=None,
        included=False,
        fixity_status="available" if expected_sha256 else "unavailable",
    )
    semantic.artifacts.append(artifact)
    return artifact


def find_artifact_by_path(semantic: SemanticLayer, path: str) -> Artifact | None:
    normalized = path.replace("\\", "/")
    for artifact in semantic.artifacts:
        if artifact.path == normalized:
            return artifact
    return None
