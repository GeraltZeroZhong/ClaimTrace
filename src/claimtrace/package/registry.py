"""Artifact registration."""

from __future__ import annotations

import hashlib
import mimetypes
import posixpath
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from claimtrace.models import Artifact, SemanticLayer
from claimtrace.models.semantic_layer import ArtifactKind, ArtifactRole, ReviewStatus
from claimtrace.errors import PackageError
from claimtrace.package.checksums import (
    directory_size,
    file_size,
    is_sha256_digest,
    sha256_directory,
    sha256_file,
)
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
MAX_STRUCTURE_HEADER_SCAN_BYTES = 16 * 1024 * 1024


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
    if suffix in {".pdb", ".cif", ".mmcif"} and _looks_like_coordinate_structure(path):
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


def _looks_like_coordinate_structure(path: Path) -> bool:
    suffix = path.suffix.lower()
    try:
        with path.open("rb") as handle:
            sample = handle.read(MAX_STRUCTURE_HEADER_SCAN_BYTES)
    except OSError:
        return False
    if suffix == ".pdb":
        return sample.startswith((b"ATOM  ", b"HETATM")) or b"\nATOM  " in sample or b"\nHETATM" in sample
    if suffix in {".cif", ".mmcif"}:
        lowered = sample.lower()
        has_cartesian_coordinates = all(
            token in lowered
            for token in (b"_atom_site.cartn_x", b"_atom_site.cartn_y", b"_atom_site.cartn_z")
        )
        has_fractional_coordinates = all(
            token in lowered
            for token in (
                b"_atom_site_fract_x",
                b"_atom_site_fract_y",
                b"_atom_site_fract_z",
            )
        )
        return has_cartesian_coordinates or has_fractional_coordinates
    return False


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
    image_metadata = None
    if requested_role == ArtifactRole.render_image:
        if source.is_dir():
            raise PackageError("A rendered-image artifact must be a regular image file, not a directory.")
        from claimtrace.importers.image import inspect_image

        image_metadata = inspect_image(source)
    if source.is_dir():
        digest = sha256_directory(source)
        size = directory_size(source)
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
    relative_path = ensure_relative_path(relative_path)
    target_path = source
    reuse_existing_target = False
    existing = find_artifact_by_path(semantic, relative_path)
    if existing:
        if existing.kind == ArtifactKind.local_attached and detached:
            raise PackageError(
                f"Artifact is already attached at {relative_path}; it cannot be changed to detached "
                "implicitly because that would leave its package payload behind. Keep it attached, "
                "or remove the artifact and payload explicitly before registering detached metadata."
            )
        if existing.kind == ArtifactKind.remote:
            raise PackageError(
                f"Artifact path is already registered with an incompatible remote state: {relative_path}."
            )

        target = resolve_package_path(root, relative_path)
        target_exists = target.exists()
        same_file = target_exists and source.resolve() == target.resolve()
        if existing.sha256 and existing.sha256 != digest and not same_file:
            raise PackageError(
                f"Artifact path already exists in package: {relative_path}. "
                "The incoming content does not match its recorded SHA-256 checksum."
            )

        if copy and not detached:
            if target_exists:
                validate_artifact_source(target)
                same_kind = source.is_dir() == target.is_dir()
                target_digest = sha256_directory(target) if target.is_dir() else sha256_file(target)
                if not same_kind or not same_file and digest != target_digest:
                    raise PackageError(
                        f"Artifact path already exists in package: {relative_path}. "
                        "The package payload differs from the incoming artifact."
                    )
                target_path = target
            else:
                target_path = copy_into_package(root, source, relative_path)

            if target_path.is_dir():
                digest = sha256_directory(target_path)
                size = directory_size(target_path)
            else:
                digest = sha256_file(target_path)
                size = file_size(target_path)
        elif not detached:
            if not target_exists:
                raise PackageError(
                    f"Attached artifact payload is missing at {relative_path}; re-register it with copying enabled."
                )
            target_path = target

        existing.role = requested_role
        existing.sha256 = digest
        existing.byte_size = size
        existing.kind = ArtifactKind.local_detached if detached else ArtifactKind.local_attached
        existing.included = not detached
        existing.format = "inode/directory" if source.is_dir() else media_type_for(source)
        existing.media_type = None if source.is_dir() else existing.format
        existing.fixity_status = "available"
        if image_metadata is not None:
            existing.extensions["image"] = image_metadata
        return existing
    if copy and not detached:
        target = resolve_package_path(root, relative_path)
        if target.exists():
            validate_artifact_source(target)
            same_file = source.resolve() == target.resolve()
            same_kind = source.is_dir() == target.is_dir()
            if target.is_dir():
                target_digest = sha256_directory(target)
            else:
                target_digest = sha256_file(target)
            if not same_kind or not same_file and digest != target_digest:
                raise PackageError(
                    f"Package destination already contains an unregistered different artifact: {relative_path}. "
                    "Rename the incoming file or register the existing package file first."
                )
            target_path = target
            reuse_existing_target = True
    if copy and not detached:
        if not reuse_existing_target:
            target_path = copy_into_package(root, source, relative_path)
        if target_path.is_dir():
            digest = sha256_directory(target_path)
            size = directory_size(target_path)
        else:
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
    if image_metadata is not None:
        artifact.extensions["image"] = image_metadata
    return artifact


def register_remote_artifact(
    semantic: SemanticLayer,
    url: str,
    role: str | ArtifactRole | None = None,
    *,
    expected_sha256: str | None = None,
) -> Artifact:
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise PackageError("Remote artifact URL is malformed; check its host and brackets.") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise PackageError(
            "Remote artifact URLs must use http:// or https://, include a host, and omit embedded credentials."
        )
    if expected_sha256 is not None and not is_sha256_digest(expected_sha256):
        raise PackageError("Expected SHA-256 must contain exactly 64 hexadecimal characters.")
    expected_sha256 = expected_sha256.lower() if expected_sha256 is not None else None
    requested_role = ArtifactRole(role) if role is not None else None
    existing = next((artifact for artifact in semantic.artifacts if artifact.url == url), None)
    if existing:
        recorded_sha256 = existing.sha256.lower() if existing.sha256 else None
        if expected_sha256 and recorded_sha256 and recorded_sha256 != expected_sha256:
            raise PackageError(
                f"Remote artifact {url} already has a conflicting SHA-256 checksum "
                f"({recorded_sha256}); refusing to replace it with {expected_sha256}."
            )
        if requested_role is not None:
            existing.role = requested_role
        if expected_sha256 is not None:
            existing.sha256 = expected_sha256
        elif recorded_sha256 and is_sha256_digest(recorded_sha256):
            existing.sha256 = recorded_sha256
        existing.kind = ArtifactKind.remote
        existing.path = None
        existing.included = False
        existing.format = "remote"
        existing.media_type = None
        existing.fixity_status = "available" if existing.sha256 else "unavailable"
        return existing
    artifact = Artifact(
        id=_unique_artifact_id(semantic, Path(url), expected_sha256, url),
        kind=ArtifactKind.remote,
        role=requested_role or ArtifactRole.generic,
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
