import json
from pathlib import Path

from PIL import Image

import pytest

from claimtrace import _simple_yaml, export_package, init_package, load_package, validate_package
from claimtrace.completion import apply_answers, package_answer_template
from claimtrace.errors import PackageError
from claimtrace.package.layout import read_completion_tasks


def write_png(path: Path) -> None:
    Image.new("RGB", (2, 2), color=(32, 96, 160)).save(path, format="PNG")


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


def test_failed_force_reinitialization_restores_existing_package(tmp_path: Path):
    original = tmp_path / "original.pml"
    original.write_text("show cartoon\n", encoding="utf-8")
    output = tmp_path / "pkg"
    existing = init_package(native=original, out=output)
    before = (output / "semantic_layer.json").read_bytes()
    marker = output / "evidence" / "keep.txt"
    marker.write_text("keep me\n", encoding="utf-8")
    invalid_image = tmp_path / "broken.png"
    invalid_image.write_bytes(b"not an image")

    with pytest.raises(ValueError, match="cannot be decoded"):
        init_package(image=invalid_image, out=output, force=True)

    assert (output / "semantic_layer.json").read_bytes() == before
    assert marker.read_text(encoding="utf-8") == "keep me\n"
    assert load_package(output).semantic_layer.package.package_id == existing.semantic_layer.package.package_id


def test_explicit_empty_evidence_completes_evidence_decision(tmp_path: Path):
    script = tmp_path / "scene.pml"
    script.write_text("show cartoon\n", encoding="utf-8")
    pkg = init_package(native=script, out=tmp_path / "pkg")
    answers = package_answer_template(pkg.semantic_layer)
    answers["claim"]["claim_text"] = "Draft figure shows a cartoon representation."
    answers["claim"]["figure_ref"] = "Figure 1A"
    answers["uncertainty"] = []
    answers_path = tmp_path / "answers.yml"
    answers_path.write_text(_simple_yaml.dumps(answers), encoding="utf-8")

    pkg.complete_from_answers(answers_path)

    statuses = {task.section: task.status for task in read_completion_tasks(pkg.root)}
    assert statuses["claim"] == "answered"
    assert statuses["evidence"] == "answered"


def test_add_render_artifact_links_it_to_existing_scenes(tmp_path: Path):
    script = tmp_path / "scene.pml"
    script.write_text("show cartoon\n", encoding="utf-8")
    image = tmp_path / "figure.png"
    write_png(image)
    pkg = init_package(native=script, out=tmp_path / "pkg")

    artifact = pkg.add_artifact(image, role="render_image")

    assert pkg.semantic_layer.scenes
    assert all(artifact.id in scene.render_artifact_ids for scene in pkg.semantic_layer.scenes)
    reloaded = load_package(pkg.root)
    assert all(artifact.id in scene.render_artifact_ids for scene in reloaded.semantic_layer.scenes)


def test_render_artifact_is_not_guessed_across_multiple_scenes(tmp_path: Path):
    mvsj = tmp_path / "story.mvsj"
    mvsj.write_text(
        json.dumps(
            {
                "metadata": {"version": "1"},
                "snapshots": [
                    {"title": "First", "root": {"kind": "root", "children": []}},
                    {"title": "Second", "root": {"kind": "root", "children": []}},
                ],
            }
        ),
        encoding="utf-8",
    )
    image = tmp_path / "figure.png"
    write_png(image)
    pkg = init_package(native=mvsj, out=tmp_path / "pkg")

    artifact = pkg.add_artifact(image, role="render_image")

    assert len(pkg.semantic_layer.scenes) == 2
    assert all(artifact.id not in scene.render_artifact_ids for scene in pkg.semantic_layer.scenes)

    first_scene = pkg.semantic_layer.scenes[0]
    pkg.add_artifact(image, role="render_image", scene_id=first_scene.id)
    assert artifact.id in first_scene.render_artifact_ids
    assert artifact.id not in pkg.semantic_layer.scenes[1].render_artifact_ids


def test_multiple_claims_keep_their_evidence_and_uncertainty_separate(tmp_path: Path):
    script = tmp_path / "scene.pml"
    script.write_text("show cartoon\n", encoding="utf-8")
    pkg = init_package(native=script, out=tmp_path / "pkg")
    native_id = pkg.semantic_layer.artifacts[0].id
    answers = {
        "claims": [
            {
                "id": "claim:a",
                "claim_text": "Panel A shows one view.",
                "claim_type": "simple_structure_view",
                "figure_ref": "Figure 1A",
            },
            {
                "id": "claim:b",
                "claim_text": "Panel B shows another view.",
                "claim_type": "simple_structure_view",
                "figure_ref": "Figure 1B",
            },
        ],
        "evidence": [
            {
                "id": "evidence:a",
                "claim_ids": ["claim:a"],
                "result_summary": "Evidence for A.",
                "source_artifact_ids": [native_id],
            },
            {
                "id": "evidence:b",
                "claim_ids": ["claim:b"],
                "result_summary": "Evidence for B.",
                "source_artifact_ids": [native_id],
            },
        ],
        "uncertainty": [
            {"id": "uncertainty:a", "claim_ids": ["claim:a"], "statement": "Limit for A."},
            {"id": "uncertainty:b", "claim_ids": ["claim:b"], "statement": "Limit for B."},
        ],
        "reuse": {"license": "unknown"},
    }

    apply_answers(pkg.root, pkg.semantic_layer, answers, answer_base=tmp_path)

    by_id = {claim.id: claim for claim in pkg.semantic_layer.claims}
    assert by_id["claim:a"].evidence_ids == ["evidence:a"]
    assert by_id["claim:b"].evidence_ids == ["evidence:b"]
    assert by_id["claim:a"].uncertainty_ids == ["uncertainty:a"]
    assert by_id["claim:b"].uncertainty_ids == ["uncertainty:b"]
