"""Streaming checksum helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path

from claimtrace.package.paths import ensure_relative_path, safe_walk


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
