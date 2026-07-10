from pathlib import Path

import pytest

from claimtrace import _simple_yaml, export_package, init_package, load_package, validate_package
from claimtrace.completion import package_answer_template
from claimtrace.errors import PackageError
from claimtrace.package.layout import read_completion_tasks


def test_public_api_roundtrip(tmp_path: Path):
    source = Path("examples/simple-pymol-structure")
    pkg = init_package(
        native=source / "figure_A.pml",
        image=source / "figure_A.png",
        out=tmp_path / "pkg",
    )
    pkg.complete_from_answers(source / "answers.yml")

    loaded = load_package(tmp_path / "pkg")
    structure = next(item for item in loaded.semantic_layer.artifacts if item.role.value == "structure")
    assert structure.path == "native/model.cif"
    assert (loaded.root / structure.path).exists()
    report = validate_package(loaded, mode="archive")
    exported = export_package(loaded, tmp_path / "pkg.zip", mode="archive", zip_output=True)

    assert report.overall_status == "pass"
    assert exported.exists()
    assert all(task.status == "answered" for task in read_completion_tasks(tmp_path / "pkg"))


def test_init_rejects_directory_or_wrong_native_format_before_writing(tmp_path: Path):
    directory = tmp_path / "scene.pml"
    directory.mkdir()
    wrong_format = tmp_path / "scene.txt"
    wrong_format.write_text("show cartoon\n", encoding="utf-8")

    with pytest.raises(PackageError, match="regular file"):
        init_package(native=directory, out=tmp_path / "directory-package")
    with pytest.raises(PackageError, match="Unsupported native scene format"):
        init_package(native=wrong_format, out=tmp_path / "wrong-package")

    assert not (tmp_path / "directory-package").exists()
    assert not (tmp_path / "wrong-package").exists()


def test_failed_import_leaves_existing_empty_output_empty(tmp_path: Path):
    malformed = tmp_path / "broken.mvsj"
    malformed.write_text("{not valid json", encoding="utf-8")
    output = tmp_path / "empty-output"
    output.mkdir()

    with pytest.raises(Exception):
        init_package(native=malformed, out=output)

    assert output.is_dir()
    assert list(output.iterdir()) == []


def test_only_pml_completion_keeps_evidence_task_open(tmp_path: Path):
    script = tmp_path / "scene.pml"
    script.write_text("show cartoon\n", encoding="utf-8")
    pkg = init_package(native=script, out=tmp_path / "pkg")
    answers = package_answer_template(pkg.semantic_layer)
    answers["claim"]["claim_text"] = "Draft figure shows a cartoon representation."
    answers["claim"]["figure_ref"] = "Figure 1A"
    answers_path = tmp_path / "answers.yml"
    answers_path.write_text(_simple_yaml.dumps(answers), encoding="utf-8")

    pkg.complete_from_answers(answers_path)

    statuses = {task.section: task.status for task in read_completion_tasks(pkg.root)}
    assert statuses["claim"] == "answered"
    assert statuses["evidence"] == "open"
