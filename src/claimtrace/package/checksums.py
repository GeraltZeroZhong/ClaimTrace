"""Streaming checksum helpers."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from claimtrace.package.paths import ensure_relative_path, safe_walk


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def is_sha256_digest(value: str | None) -> bool:
    return bool(value and SHA256_RE.fullmatch(value.lower()))


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def file_size(path: Path) -> int:
    return path.stat().st_size


def directory_size(path: Path) -> int:
    return sum(file_size(item) for item in safe_walk(path) if item.is_file())


def sha256_directory(path: Path) -> str:
    """Hash a directory's relative file and directory names plus file contents."""

    root = path.resolve()
    digest = hashlib.sha256()
    for item in sorted(safe_walk(root, include_directories=True)):
        relative = ensure_relative_path(item.relative_to(root).as_posix())
        entry_type = b"D" if item.is_dir() else b"F"
        digest.update(entry_type)
        digest.update(b"\0")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if item.is_file():
            digest.update(sha256_file(item).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def checksum_inventory(root: Path, exclude: set[str] | None = None) -> list[tuple[str, str]]:
    exclude = exclude or set()
    rows: list[tuple[str, str]] = []
    for path in sorted(safe_walk(root)):
        relative = path.relative_to(root).as_posix()
        if relative in exclude:
            continue
        ensure_relative_path(relative)
        rows.append((sha256_file(path), relative))
    return rows


def write_sha256_txt(root: Path, output: Path | None = None) -> Path:
    output = output or root / "checksums" / "sha256.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = checksum_inventory(root, exclude={output.relative_to(root).as_posix()})
    text = "".join(f"{digest}  {relative}\n" for digest, relative in rows)
    output.write_text(text, encoding="utf-8")
    return output
