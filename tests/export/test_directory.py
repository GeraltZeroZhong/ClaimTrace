import json
import zipfile
from pathlib import Path

import pytest

import claimtrace.export.directory as export_module
import claimtrace.validation.engine as validation_engine
from claimtrace import init_package
from claimtrace.errors import SecurityError, ValidationError


def _write_mvs(path: Path) -> None:
    tree = {
        "metadata": {"version": "1"},
        "root": {"kind": "root", "children": []},
    }
    if path.suffix == ".mvsj":
        path.write_text(json.dumps(tree), encoding="utf-8")
        return
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("index.mvsj", json.dumps(tree))


@pytest.mark.parametrize("suffix", [".mvsj", ".mvsx"])
@pytest.mark.parametrize("zip_output", [False, True])
def test_mvs_export_uses_at_most_three_validation_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    zip_output: bool,
) -> None:
    source = tmp_path / f"scene{suffix}"
    _write_mvs(source)
    package = init_package(native=source, out=tmp_path / "package")
    validation_calls = 0
    mvs_reads = 0
    original_validate = export_module.validate_package
    original_read_mvs = validation_engine.read_mvs

    def counting_validate(*args, **kwargs):
        nonlocal validation_calls
        validation_calls += 1
        return original_validate(*args, **kwargs)

    def counting_read_mvs(*args, **kwargs):
        nonlocal mvs_reads
        mvs_reads += 1
        return original_read_mvs(*args, **kwargs)

    monkeypatch.setattr(export_module, "validate_package", counting_validate)
    monkeypatch.setattr(validation_engine, "read_mvs", counting_read_mvs)

    export_module.export_package(
        package.root,
        tmp_path / ("export.zip" if zip_output else "export"),
        mode="draft",
        zip_output=zip_output,
    )

    assert 2 <= validation_calls <= 3
    if suffix == ".mvsx":
        assert 2 <= mvs_reads <= 3
    else:
        assert mvs_reads == 0


def test_directory_and_zip_exports_preserve_empty_directories(tmp_path: Path) -> None:
    package = init_package(blank=True, out=tmp_path / "package")
    empty = package.root / "data" / "kept-empty" / "nested"
    empty.mkdir(parents=True)

    directory_output = tmp_path / "directory-export"
    export_module.export_package(package.root, directory_output, mode="draft")
    assert (directory_output / "data" / "kept-empty" / "nested").is_dir()

    zip_output = tmp_path / "archive-export.zip"
    export_module.export_package(package.root, zip_output, mode="draft", zip_output=True)
    with zipfile.ZipFile(zip_output) as archive:
        names = set(archive.namelist())
    assert "data/kept-empty/" in names
    assert "data/kept-empty/nested/" in names


def test_atomic_replace_restores_previous_output_if_install_fails(tmp_path: Path) -> None:
    output = tmp_path / "export.zip"
    output.write_bytes(b"previous export")
    container = tmp_path / "staging-container"
    container.mkdir()
    missing_staged_output = container / "missing.zip"

    with pytest.raises(FileNotFoundError):
        export_module._replace_output_atomically(
            missing_staged_output,
            output,
            container,
            force=True,
        )

    assert output.read_bytes() == b"previous export"
    assert not (container / "previous-output").exists()


def test_atomic_replace_does_not_overwrite_new_output_without_force(tmp_path: Path) -> None:
    output = tmp_path / "export.zip"
    output.write_bytes(b"created while export was building")
    container = tmp_path / "staging-container"
    container.mkdir()
    staged_output = container / "package.zip"
    staged_output.write_bytes(b"new export")

    with pytest.raises(SecurityError, match="--force"):
        export_module._replace_output_atomically(
            staged_output,
            output,
            container,
            force=False,
        )

    assert output.read_bytes() == b"created while export was building"
    assert staged_output.read_bytes() == b"new export"


def test_force_refuses_to_replace_an_unrelated_file(tmp_path: Path) -> None:
    package = init_package(blank=True, out=tmp_path / "package")
    output = tmp_path / "important.txt"
    output.write_text("keep me\n", encoding="utf-8")

    with pytest.raises(SecurityError, match="non-ClaimTrace file"):
        export_module.export_package(
            package.root,
            output,
            mode="draft",
            zip_output=True,
            force=True,
        )

    assert output.read_text(encoding="utf-8") == "keep me\n"


def test_force_can_replace_an_existing_claimtrace_zip(tmp_path: Path) -> None:
    package = init_package(blank=True, out=tmp_path / "package")
    output = tmp_path / "export.zip"
    export_module.export_package(package.root, output, mode="draft", zip_output=True)

    export_module.export_package(
        package.root,
        output,
        mode="draft",
        zip_output=True,
        force=True,
    )

    assert zipfile.is_zipfile(output)
    with zipfile.ZipFile(output) as archive:
        assert "claimtrace-export.json" in archive.namelist()


def test_late_export_failure_keeps_existing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = init_package(blank=True, out=tmp_path / "source")
    existing = init_package(blank=True, out=tmp_path / "existing")
    marker = existing.root / "evidence" / "keep.txt"
    marker.write_text("keep me\n", encoding="utf-8")
    semantic_before = (existing.root / "semantic_layer.json").read_bytes()
    original_build = export_module._build_export_directory

    def build_then_corrupt(*args, **kwargs) -> None:
        original_build(*args, **kwargs)
        staging = args[1]
        (staging / "semantic_layer.json").write_text("{not-json", encoding="utf-8")

    monkeypatch.setattr(export_module, "_build_export_directory", build_then_corrupt)

    with pytest.raises(ValidationError):
        export_module.export_package(
            source.root,
            existing.root,
            mode="draft",
            force=True,
        )

    assert (existing.root / "semantic_layer.json").read_bytes() == semantic_before
    assert marker.read_text(encoding="utf-8") == "keep me\n"
