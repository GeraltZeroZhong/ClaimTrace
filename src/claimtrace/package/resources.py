"""Shared helpers for native resource references."""

from __future__ import annotations

import hashlib
from pathlib import Path
import posixpath
from typing import Any


def resource_uri_summary(uri: str, *, max_length: int = 140) -> str:
    """Return a bounded human-readable URI while semantic JSON keeps the exact value."""

    text = str(uri)
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]
    if text.startswith("data:"):
        header = text[5:].split(",", 1)[0]
        media_type = header.split(";", 1)[0] or "text/plain"
        return f"inline data URI ({media_type}, {len(text)} characters, sha256 {digest}…)"
    if len(text) <= max_length:
        return text
    keep = max(24, max_length - 35)
    return f"{text[:keep]}… [{len(text)} characters, sha256 {digest}…]"


def resource_matches_artifact(semantic: Any, uri: str, *, resource_ref: Any | None = None) -> bool:
    """Return whether a native resource URI is represented by an attached artifact.

    A bare filename from a native script may match an artifact stored under a
    package role directory. If the native URI contains a directory component, the
    package artifact path must end with that relative path rather than merely
    sharing the same basename.
    """

    uri_text_input = str(uri).replace("\\", "/")
    matching_refs = (
        [resource_ref]
        if resource_ref is not None
        else [
            resource
            for resource in getattr(semantic, "resource_references", [])
            if str(getattr(resource, "uri", "")).replace("\\", "/") == uri_text_input
        ]
    )
    if matching_refs:
        artifact_by_id = {
            getattr(artifact, "id", None): artifact
            for artifact in getattr(semantic, "artifacts", [])
        }
        artifact_paths = {
            str(getattr(artifact, "path", "")).replace("\\", "/")
            for artifact in getattr(semantic, "artifacts", [])
            if getattr(artifact, "path", None)
        }
        for resource in matching_refs:
            if getattr(resource, "uri_kind", "unknown") not in {"relative", "local"}:
                continue
            native = artifact_by_id.get(getattr(resource, "artifact_id", None))
            native_path = getattr(native, "path", None)
            if not native_path:
                continue
            expected = posixpath.normpath(
                posixpath.join(posixpath.dirname(str(native_path).replace("\\", "/")), uri_text_input)
            )
            if not expected.startswith("../") and expected in artifact_paths:
                return True
        return False

    uri_path = Path(uri_text_input)
    if not uri_path.parts:
        return False
    uri_text = uri_path.as_posix()
    bare_filename = len(uri_path.parts) == 1
    for artifact in getattr(semantic, "artifacts", []):
        artifact_path_value = getattr(artifact, "path", None)
        if not artifact_path_value:
            continue
        artifact_path = Path(str(artifact_path_value).replace("\\", "/"))
        artifact_text = artifact_path.as_posix()
        if artifact_text.endswith(uri_text):
            return True
        if bare_filename and artifact_path.name == uri_path.name:
            return True
    return False


def synchronize_resource_bindings(semantic: Any) -> None:
    """Mark native references resolved when their replay-relative file is attached."""

    for resource in getattr(semantic, "resource_references", []):
        if not resource_matches_artifact(semantic, resource.uri, resource_ref=resource):
            continue
        resource.fixity_status = "available"
        resource.fetch_status = "fetched"
        location = getattr(resource, "source_location", None)
        for native_ref in getattr(semantic, "native_references", []):
            ref_location = getattr(native_ref, "source_location", None)
            if _same_source_anchor(location, ref_location):
                native_ref.target_resolution_status = "resolved_against_artifact"


def _same_source_anchor(first: Any, second: Any) -> bool:
    """Match the exact native statement/node that introduced a resource.

    JSON-based formats generally have no line number, so comparing two ``None``
    line values would incorrectly resolve every reference in the document.
    """

    if first is None or second is None or first.artifact_id != second.artifact_id:
        return False
    first_pointer = getattr(first, "json_pointer", None)
    second_pointer = getattr(second, "json_pointer", None)
    if first_pointer is not None or second_pointer is not None:
        return bool(first_pointer and second_pointer and first_pointer == second_pointer)
    first_line = getattr(first, "line", None)
    second_line = getattr(second, "line", None)
    return first_line is not None and second_line is not None and first_line == second_line
