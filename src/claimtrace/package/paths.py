"""Path safety helpers."""

from __future__ import annotations

import os
import re
from pathlib import Path

from claimtrace.errors import SecurityError


def ensure_relative_path(path: str | Path) -> str:
    raw = str(path).replace("\\", "/")
    if re.match(r"^[A-Za-z]:($|/)", raw) or raw.startswith("//"):
        raise SecurityError(
            f"Windows drive or UNC paths are not package-relative paths: {path}. "
            "In WSL, use a path like /mnt/c/Users/..."
        )
    candidate = Path(raw)
    if candidate.is_absolute() or raw.startswith("~"):
        raise SecurityError(f"Absolute or home-relative paths are not allowed in packages: {path}")
    parts = candidate.parts
    if any(part in {"..", ""} for part in parts):
        raise SecurityError(f"Path traversal is not allowed in packages: {path}")
    return raw


def resolve_package_path(root: Path, relative_path: str | Path) -> Path:
    safe = ensure_relative_path(relative_path)
    root_resolved = root.resolve()
    target = (root_resolved / safe).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise SecurityError(f"Path escapes package root: {relative_path}") from exc
    return target


def ensure_no_dangerous_symlink(root: Path, path: Path) -> None:
    root_resolved = root.resolve()
    current = path
    while current != root_resolved and current != current.parent:
        if current.is_symlink():
            target = current.resolve()
            try:
                target.relative_to(root_resolved)
            except ValueError as exc:
                raise SecurityError(f"Symlink escapes package root: {current}") from exc
        current = current.parent


def safe_walk(root: Path):
    root_resolved = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root_resolved):
        dir_path = Path(dirpath)
        ensure_no_dangerous_symlink(root_resolved, dir_path)
        dirnames[:] = [name for name in dirnames if not (dir_path / name).is_symlink()]
        for filename in filenames:
            path = dir_path / filename
            ensure_no_dangerous_symlink(root_resolved, path)
            yield path
