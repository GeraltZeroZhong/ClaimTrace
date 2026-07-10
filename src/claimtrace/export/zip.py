"""Zip export helpers."""

from __future__ import annotations

import zipfile
from pathlib import Path

from claimtrace.package.paths import ensure_relative_path, safe_walk


def zip_directory(source: Path, output: Path, *, force: bool = False) -> Path:
    if output.is_symlink():
        raise FileExistsError(f"Zip output cannot be a symbolic link: {output}")
    if output.exists():
        if not force:
            raise FileExistsError(f"Export output already exists: {output}")
        output.unlink()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(safe_walk(source, include_directories=True)):
            relative = path.relative_to(source).as_posix()
            ensure_relative_path(relative)
            archive.write(path, relative + "/" if path.is_dir() else relative)
    return output
