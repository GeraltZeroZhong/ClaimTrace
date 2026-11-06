import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from claimtrace import init_package, load_package
from claimtrace.constants import COMPLETION_TASKS_PATH
from claimtrace.errors import PackageError
from claimtrace.package.layout import read_completion_tasks, write_json


@pytest.mark.parametrize("failure", ["write", "replace"])
def test_failed_json_save_preserves_previous_package(tmp_path, monkeypatch, failure):
    package = init_package(blank=True, out=tmp_path / "package")
    manifest = package.root / "semantic_layer.json"
    before = manifest.read_bytes()
    package.semantic_layer.package.title = "Updated title"
    original_open = Path.open

    if failure == "write":
        @contextmanager
        def failing_open(path, mode="r", *args, **kwargs):
            with original_open(path, mode, *args, **kwargs) as handle:
                if path.parent == package.root and mode in {"w", "x"}:
                    handle.write("partial write")
                    raise OSError("Disk full")
                yield handle

        monkeypatch.setattr(Path, "open", failing_open)
    else:
        def failed_replace(source, destination):
            raise OSError("Replacement failed")

        monkeypatch.setattr("claimtrace.package.layout.os.replace", failed_replace)

    with pytest.raises(OSError):
        package.save()

    assert manifest.read_bytes() == before
    assert load_package(package.root).semantic_layer.package.title == "Untitled ClaimTrace package"
    assert not list(package.root.glob(".*.tmp"))


def test_json_save_preserves_unicode_and_file_mode(tmp_path):
    path = tmp_path / "record.json"
    write_json(path, {"title": "First"})
    path.chmod(0o600)
    mode = path.stat().st_mode

    write_json(path, {"title": "Ligand α"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"title": "Ligand α"}
    assert path.stat().st_mode == mode


def test_completion_reader_accepts_legacy_list(tmp_path):
    package = init_package(blank=True, out=tmp_path / "package")
    tasks = read_completion_tasks(package.root)
    write_json(package.root / COMPLETION_TASKS_PATH, [task.model_dump(mode="json") for task in tasks])

    assert read_completion_tasks(package.root) == tasks


@pytest.mark.parametrize("data", [[], None, "record"])
def test_package_loader_reports_invalid_manifest_root(tmp_path, data):
    package = init_package(blank=True, out=tmp_path / "package")
    write_json(package.root / "semantic_layer.json", data)

    with pytest.raises(PackageError, match="must contain a JSON object"):
        load_package(package.root)
