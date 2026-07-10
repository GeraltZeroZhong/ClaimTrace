"""Package directory layout and JSON I/O."""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path
from uuid import uuid4

from claimtrace.constants import (
    COMPLETION_TASKS_PATH,
    EXTRACTION_REPORT_PATH,
    SEMANTIC_LAYER_FILENAME,
)
from claimtrace.errors import PackageError, SchemaVersionError, SecurityError
from claimtrace.models import CompletionTask, SemanticLayer
from claimtrace.package.paths import resolve_package_path


PACKAGE_DIRS = [
    "semantic",
    "schema",
    "checksums",
    "native",
    "data/structures",
    "data/maps",
    "data/trajectories",
    "evidence",
    "renders",
]


def create_package_root(
    root: Path,
    title: str = "Untitled ClaimTrace package",
    *,
    force: bool = False,
) -> SemanticLayer:
    if root.exists() and not root.is_dir():
        raise PackageError(f"Output path exists and is not a directory: {root}")
    if root.exists() and any(root.iterdir()):
        if not force:
            raise PackageError(
                f"Output directory already has files: {root}. "
                "Choose a new --out path or pass --force to replace it."
            )
        _validate_force_replace_root(root)
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    for directory in PACKAGE_DIRS:
        (root / directory).mkdir(parents=True, exist_ok=True)
    package_id = f"scene-package-{uuid4().hex[:12]}"
    semantic = SemanticLayer.new(package_id=package_id, title=title)
    write_semantic_layer(root, semantic)
    write_json(root / EXTRACTION_REPORT_PATH, {"facts": [], "importers": []})
    write_completion_tasks(root, [])
    return semantic


def load_semantic_layer(root: Path) -> SemanticLayer:
    path = root / SEMANTIC_LAYER_FILENAME
    if not path.exists():
        raise PackageError(f"Missing {SEMANTIC_LAYER_FILENAME} in {root}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if str(data.get("schema_version")) != "0.1.0":
        raise SchemaVersionError(f"Unsupported CAL schema version: {data.get('schema_version')}")
    return SemanticLayer.model_validate(data)


def write_semantic_layer(root: Path, semantic: SemanticLayer) -> None:
    write_json(root / SEMANTIC_LAYER_FILENAME, semantic.model_dump(mode="json", exclude_none=True))


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def read_completion_tasks(root: Path) -> list[CompletionTask]:
    path = root / COMPLETION_TASKS_PATH
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    tasks = data.get("tasks", data if isinstance(data, list) else [])
    return [CompletionTask.model_validate(item) for item in tasks]


def write_completion_tasks(root: Path, tasks: list[CompletionTask]) -> None:
    write_json(root / COMPLETION_TASKS_PATH, {"tasks": [task.model_dump(mode="json") for task in tasks]})


def append_extraction_report(root: Path, importer_name: str, facts: list[dict]) -> None:
    path = root / EXTRACTION_REPORT_PATH
    report = read_json(path)
    existing = list(report.get("facts", []))
    existing.extend(facts)
    importers = list(report.get("importers", []))
    if importer_name and importer_name not in importers:
        importers.append(importer_name)
    write_json(path, {"facts": existing, "importers": importers})


def validate_artifact_source(source: Path) -> None:
    """Reject links and non-regular files without following them."""

    source = Path(source)
    source_mode = source.lstat().st_mode
    if stat.S_ISLNK(source_mode):
        raise SecurityError(f"Artifact source is a symbolic link, which is not allowed: {source}")
    if stat.S_ISREG(source_mode):
        return
    if not stat.S_ISDIR(source_mode):
        raise SecurityError(
            f"Artifact source is an unsupported {_special_file_kind(source_mode)}: {source}. "
            "Only regular files and directories can be registered."
        )

    pending = [source]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
        for entry in entries:
            entry_path = Path(entry.path)
            entry_mode = entry.stat(follow_symlinks=False).st_mode
            if stat.S_ISLNK(entry_mode):
                raise SecurityError(
                    "Artifact source contains a symbolic link, which is not allowed: "
                    f"{entry_path}"
                )
            if stat.S_ISDIR(entry_mode):
                pending.append(entry_path)
            elif not stat.S_ISREG(entry_mode):
                raise SecurityError(
                    "Artifact source contains an unsupported "
                    f"{_special_file_kind(entry_mode)}: {entry_path}. "
                    "Only regular files and directories can be registered."
                )


def copy_into_package(root: Path, source: Path, relative_destination: str) -> Path:
    source = Path(source)
    validate_artifact_source(source)
    target = resolve_package_path(root, relative_destination)
    source_resolved = source.resolve()
    target_resolved = target.resolve(strict=False)
    if (
        source.is_dir()
        and target_resolved != source_resolved
        and target_resolved.is_relative_to(source_resolved)
    ):
        raise SecurityError(
            f"Package destination {target} is inside source directory {source}; "
            "refusing a recursive copy."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    if source_resolved != target_resolved:
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target, symlinks=True)
        else:
            shutil.copy2(source, target, follow_symlinks=False)
        try:
            validate_artifact_source(target)
        except SecurityError:
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)
            raise
    return target


def _special_file_kind(mode: int) -> str:
    if stat.S_ISFIFO(mode):
        return "FIFO"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
        return "device"
    return "special file"


def _validate_force_replace_root(root: Path) -> None:
    resolved = root.resolve()
    cwd = Path.cwd().resolve()
    home = Path.home().resolve()
    if resolved in {Path("/").resolve(), home, cwd} or cwd.is_relative_to(resolved):
        raise PackageError(f"Refusing to replace this directory with --force: {root}")
    if not (root / SEMANTIC_LAYER_FILENAME).exists():
        raise PackageError(
            f"Refusing to replace non-ClaimTrace directory with --force: {root}. "
            "Choose a new --out path or remove the directory yourself."
        )
