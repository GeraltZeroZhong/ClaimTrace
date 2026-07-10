"""Path safety helpers."""

from __future__ import annotations

import os
import re
import stat
import unicodedata
from pathlib import Path

from claimtrace.errors import SecurityError


def ensure_relative_path(path: str | Path) -> str:
    original = str(path)
    if "\\" in original:
        raise SecurityError(f"Backslashes are not allowed in stored package paths: {path!r}")
    raw = original
    components = raw.split("/")
    if not raw or any(part in {"", ".", ".."} for part in components):
        raise SecurityError(
            f"Package paths must use a canonical relative form with no empty, dot or parent segments: {path!r}"
        )
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in raw):
        raise SecurityError(f"Control characters are not allowed in package paths: {path!r}")
    if re.match(r"^[A-Za-z]:", raw) or raw.startswith("//"):
        raise SecurityError(
            f"Windows drive or UNC paths are not package-relative paths: {path}. "
            "In WSL, use a path like /mnt/c/Users/..."
        )
    candidate = Path(raw)
    if candidate.is_absolute() or raw.startswith("~"):
        raise SecurityError(f"Absolute or home-relative paths are not allowed in packages: {path}")
    parts = candidate.parts
    reserved = {"con", "prn", "aux", "nul", *{f"com{i}" for i in range(1, 10)}, *{f"lpt{i}" for i in range(1, 10)}}
    for part in parts:
        if ":" in part:
            raise SecurityError(f"Colons and NTFS alternate-stream syntax are not allowed: {path}")
        if part.endswith((" ", ".")):
            raise SecurityError(f"Package path components cannot end in a space or dot: {path}")
        if part.split(".", 1)[0].casefold() in reserved:
            raise SecurityError(f"Windows-reserved package path component is not allowed: {part}")
    return raw


def resolve_package_path(root: Path, relative_path: str | Path) -> Path:
    safe = ensure_relative_path(relative_path)
    root_resolved = root.resolve()
    lexical_target = root_resolved / safe
    current = lexical_target
    while current != root_resolved and current != current.parent:
        if current.is_symlink():
            raise SecurityError(f"Symbolic links are not allowed in package paths: {current}")
        current = current.parent
    target = lexical_target.resolve(strict=False)
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


def safe_walk(root: Path, *, include_directories: bool = False):
    root_resolved = root.resolve()

    def raise_walk_error(exc: OSError) -> None:
        raise exc

    for dirpath, dirnames, filenames in os.walk(root_resolved, onerror=raise_walk_error):
        dir_path = Path(dirpath)
        ensure_no_dangerous_symlink(root_resolved, dir_path)
        for dirname in dirnames:
            path = dir_path / dirname
            if path.is_symlink():
                raise SecurityError(f"Symbolic links are not allowed in package trees: {path}")
            if not stat.S_ISDIR(path.lstat().st_mode):
                raise SecurityError(f"Only regular directories are allowed in package trees: {path}")
            ensure_relative_path(path.relative_to(root_resolved).as_posix())
            if include_directories:
                yield path
        for filename in filenames:
            path = dir_path / filename
            if path.is_symlink():
                raise SecurityError(f"Symbolic links are not allowed in package trees: {path}")
            if not stat.S_ISREG(path.lstat().st_mode):
                raise SecurityError(f"Only regular files are allowed in package trees: {path}")
            ensure_no_dangerous_symlink(root_resolved, path)
            ensure_relative_path(path.relative_to(root_resolved).as_posix())
            yield path
