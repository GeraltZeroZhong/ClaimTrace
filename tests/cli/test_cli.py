import json
import re
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from claimtrace import _simple_yaml
from claimtrace.cli import app
from claimtrace.constants import PACKAGE_VERSION


runner = CliRunner()


def write_png(path: Path) -> None:
    Image.new("RGB", (2, 2), color=(32, 96, 160)).save(path, format="PNG")


def _current_example_answers(package: Path, tmp_path: Path) -> Path:
    source = Path("examples/simple-pymol-structure")
    answers = _simple_yaml.loads((source / "answers.yml").read_text(encoding="utf-8"))
    semantic = json.loads((package / "semantic_layer.json").read_text(encoding="utf-8"))
    colored = next(
        operation
        for operation in semantic["observed_scene_operations"]
        if operation["operation"] == "colored"
    )
    answers["scene_semantics_by_operation"][0]["operation_ids"] = [colored["operation_id"]]
    answers["artifacts"][0]["path"] = str((source / "model.cif").resolve())
    path = tmp_path / "current-answers.yml"
    path.write_text(_simple_yaml.dumps(answers), encoding="utf-8")
    return path


def test_cli_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"claimtrace {PACKAGE_VERSION}" in result.stdout


def test_cli_quickstart_shows_short_user_path():
    result = runner.invoke(app, ["quickstart"])

    assert result.exit_code == 0
    assert "python -m pip install claimtrace" in result.stdout
    assert "not published on PyPI" not in result.stdout
    assert "./dist/claimtrace" not in result.stdout
    assert "Supported native scene files: .pml, .cxc, .mvsj, .mvsx" in result.stdout
    assert 'claimtrace init --file "figure_A.pml"' in result.stdout
    assert 'Edit "scene-package/answers.yml"' in result.stdout
    assert "> scene-package/answers.yml" not in result.stdout
    assert 'claimtrace prepare "scene-package"' in result.stdout
    assert 'claimtrace review "scene-package"' in result.stdout
    assert 'claimtrace export "scene-package"' in result.stdout


def test_cli_schema_outputs_json():
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == 0
    assert "Claim Accountability Layer" in result.stdout


def test_cli_schema_out_writes_without_echoing_full_schema(tmp_path: Path):
    output = tmp_path / "semantic-layer.schema.json"

    result = runner.invoke(app, ["schema", "--out", str(output)])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"Wrote schema: {output}"
    assert "Claim Accountability Layer" in output.read_text(encoding="utf-8")


def test_cli_schema_rejects_unknown_format():
    result = runner.invoke(app, ["schema", "--format", "yaml"])
    assert result.exit_code == 1
    assert "Unknown format: yaml" in result.output


def test_cli_complete_rejects_unknown_section(tmp_path: Path):
    script = tmp_path / "scene.pml"
    script.write_text("show cartoon\n", encoding="utf-8")
    out = tmp_path / "pkg"

    result = runner.invoke(app, ["init", "--native", str(script), "--out", str(out), "--no-input"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["complete", str(out), "--section", "nope", "--no-input"])
    assert result.exit_code == 1
    assert "Unknown section: nope" in result.output


def test_cli_init_complete_validate(tmp_path: Path):
    source = Path("examples/simple-pymol-structure")
    out = tmp_path / "pkg"
    result = runner.invoke(
        app,
        [
            "init",
            "--native",
            str(source / "figure_A.pml"),
            "--image",
            str(source / "figure_A.png"),
            "--out",
            str(out),
            "--no-input",
        ],
    )
    assert result.exit_code == 0, result.output

    answers = _current_example_answers(out, tmp_path)
    result = runner.invoke(app, ["complete", str(out), "--answers", str(answers), "--no-input"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["validate", str(out), "--mode", "archive"])
    assert result.exit_code == 0, result.output
    assert "pass" in result.stdout


def test_cli_emit_template_is_package_aware_for_cxc(tmp_path: Path):
    script = tmp_path / "scene.cxc"
    script.write_text("color magenta #1/A:42\nrunscript build.py $1\n", encoding="utf-8")
    out = tmp_path / "pkg"

    result = runner.invoke(app, ["init", "--native", str(script), "--out", str(out), "--no-input"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["complete", str(out), "--emit-template"])
    assert result.exit_code == 0, result.output
    assert "answer_schema: claimtrace.native_scene_answers.v1" in result.stdout
    assert "scene_semantics_by_operation:" in result.stdout
    assert "auto_annotation:" in result.stdout
    assert "candidate_meaning:" in result.stdout
    assert "requires_user_completion" in result.stdout
    assert "native_identity_mappings:" in result.stdout
    assert "raw_resolutions:" in result.stdout


def test_cli_check_answers_rejects_unknown_cxc_anchor(tmp_path: Path):
    script = tmp_path / "scene.cxc"
    script.write_text("color magenta #1\n", encoding="utf-8")
    out = tmp_path / "pkg"
    answers = tmp_path / "answers.yml"
    answers.write_text(
        "\n".join(
            [
                "answer_schema: claimtrace.cxc_mvs_answers.v1",
                "claim:",
                "  claim_text: test",
                "  claim_type: simple_structure_view",
                "  figure_ref: Figure 1A",
                "evidence:",
                "  - evidence_kind: manual_rationale",
                "    result_summary: test",
                "reuse:",
                "  license: unknown",
                "scene_semantics_by_operation:",
                "  - operation_ids:",
                "      - op:does-not-exist",
                "    encoding_type: color",
                "    meaning_status: user_confirmed_meaning",
                "    meaning: test",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["init", "--native", str(script), "--out", str(out), "--no-input"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["complete", str(out), "--check-answers", str(answers)])
    assert result.exit_code == 1
    assert "unknown operation_id" in result.output


def test_cli_default_package_uses_scene_package(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "scene.pml"
    script.write_text("show cartoon\n", encoding="utf-8")

    result = runner.invoke(app, ["init", "--native", str(script), "--out", "scene-package", "--no-input"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["complete", "--emit-template"])
    assert result.exit_code == 0, result.output
    assert "Using scene-package" in result.output
    assert "ClaimTrace answers" in result.stdout


def test_cli_missing_package_error_suggests_init(tmp_path: Path):
    missing = tmp_path / "not-a-package"

    result = runner.invoke(app, ["inspect", str(missing)])

    assert result.exit_code == 1
    assert "No ClaimTrace package found" in result.output
    assert 'claimtrace init "<scene-file>"' in result.output
    assert ".pml, .cxc, .mvsj, .mvsx" in result.output


def test_cli_scene_file_used_as_package_gets_executable_recovery_command(tmp_path: Path):
    scene = tmp_path / "scene.cxc"
    scene.write_text("view\n", encoding="utf-8")

    result = runner.invoke(app, ["inspect", str(scene)])

    assert result.exit_code == 1
    assert "Import this scene to create a ClaimTrace package folder" in result.output
    assert f'claimtrace init "{scene}" --out "scene-package"' in result.output
    assert f'--out "{scene}"' not in result.output


def test_cli_check_answers_rejects_template_placeholders(tmp_path: Path):
    script = tmp_path / "scene.pml"
    script.write_text("show cartoon\n", encoding="utf-8")
    out = tmp_path / "pkg"
    answers = tmp_path / "answers.yml"

    result = runner.invoke(app, ["init", "--native", str(script), "--out", str(out), "--no-input"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["complete", str(out), "--emit-template"])
    assert result.exit_code == 0, result.output
    answers.write_text(result.stdout, encoding="utf-8")

    result = runner.invoke(app, ["complete", str(out), "--check-answers", str(answers)])
    assert result.exit_code == 1
    assert "claim.claim_text is still unknown" in result.output


def test_cli_simple_template_requires_author_review_of_uncertainty(tmp_path: Path):
    script = tmp_path / "scene.pml"
    script.write_text("show cartoon\n", encoding="utf-8")
    out = tmp_path / "pkg"
    result = runner.invoke(app, ["init", str(script), "--out", str(out)])
    assert result.exit_code == 0, result.output
    answers = _simple_yaml.loads((out / "answers.yml").read_text(encoding="utf-8"))
    answers["claim"]["claim_text"] = "Figure 1A shows a cartoon structure view."
    answers["claim"]["figure_ref"] = "Figure 1A"
    answers["evidence"] = []
    answers_path = tmp_path / "answers.yml"
    answers_path.write_text(_simple_yaml.dumps(answers), encoding="utf-8")

    result = runner.invoke(app, ["complete", str(out), "--check-answers", str(answers_path)])

    assert result.exit_code == 1
    assert "uncertainty[0].statement is still unknown" in result.output


def test_cli_init_refuses_non_empty_output_without_force(tmp_path: Path):
    script = tmp_path / "scene.pml"
    script.write_text("show cartoon\n", encoding="utf-8")
    out = tmp_path / "pkg"
    out.mkdir()
    (out / "old.txt").write_text("old", encoding="utf-8")

    result = runner.invoke(app, ["init", "--native", str(script), "--out", str(out), "--no-input"])

    assert result.exit_code == 1
    assert "Output directory already has files" in result.output


def test_cli_export_zip_suffix_writes_zip_without_zip_flag(tmp_path: Path):
    source = Path("examples/simple-pymol-structure")
    out = tmp_path / "pkg"
    zip_path = tmp_path / "pkg.zip"

    result = runner.invoke(
        app,
        [
            "init",
            "--native",
            str(source / "figure_A.pml"),
            "--image",
            str(source / "figure_A.png"),
            "--out",
            str(out),
            "--no-input",
        ],
    )
    assert result.exit_code == 0, result.output
    answers = _current_example_answers(out, tmp_path)
    result = runner.invoke(app, ["complete", str(out), "--answers", str(answers), "--no-input"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["export", str(out), "--mode", "archive", "--out", str(zip_path), "--no-input"])

    assert result.exit_code == 0, result.output
    assert zipfile.is_zipfile(zip_path)
    assert "Exported zip package" in result.output


def test_cli_validate_rejects_unknown_mode(tmp_path: Path):
    out = tmp_path / "pkg"
    result = runner.invoke(app, ["validate", str(out), "--mode", "nonsense"])

    assert result.exit_code == 1
    assert "Unknown mode: nonsense" in result.output


def test_cli_init_requires_input_unless_blank(tmp_path: Path):
    result = runner.invoke(app, ["init", "--out", str(tmp_path / "pkg"), "--no-input"])

    assert result.exit_code == 1
    assert "No input files were provided" in result.output

    result = runner.invoke(app, ["init", "--out", str(tmp_path / "blank"), "--blank", "--no-input"])

    assert result.exit_code == 0, result.output


def test_cli_force_refuses_current_directory(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    marker = tmp_path / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    script = tmp_path / "scene.pml"
    script.write_text("show cartoon\n", encoding="utf-8")

    result = runner.invoke(app, ["init", "--native", str(script), "--out", ".", "--force", "--no-input"])

    assert result.exit_code == 1
    assert "Refusing to replace this directory" in result.output
    assert marker.exists()


def test_cli_validate_refuses_to_overwrite_semantic_layer(tmp_path: Path):
    source = Path("examples/simple-pymol-structure")
    out = tmp_path / "pkg"
    result = runner.invoke(
        app,
        [
            "init",
            "--native",
            str(source / "figure_A.pml"),
            "--image",
            str(source / "figure_A.png"),
            "--out",
            str(out),
            "--no-input",
        ],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["validate", str(out), "--out", str(out / "semantic_layer.json")])

    assert result.exit_code == 1
    assert "Refusing to write a validation report over semantic_layer.json" in result.output


def test_cli_init_accepts_positional_scene_and_writes_answers_safely(tmp_path: Path):
    # Unicode escapes retain non-Latin filename coverage in English source text.
    script = tmp_path / "\u8f93\u5165 scene.pml"
    script.write_text("show cartoon\n", encoding="utf-8")
    out = tmp_path / "\u7ed3\u679c package"

    result = runner.invoke(
        app,
        ["init", str(script), "--out", str(out), "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["answers"] == str(out / "answers.yml")
    assert payload["profile"] == "simple-structure-view"
    answers = out / "answers.yml"
    assert answers.exists()
    assert "ClaimTrace answers" in answers.read_text(encoding="utf-8")

    text_out = tmp_path / "quoted package"
    result = runner.invoke(app, ["init", str(script), "--out", str(text_out)])
    assert result.exit_code == 0, result.output
    assert f'Next: claimtrace prepare "{text_out}"' in result.output
    assert result.output.count("claimtrace ") == 1
    assert "Materials: 1 scene file, 0 figure images" in result.output
    assert ">""" not in result.output
    assert "--emit-template >" not in result.output


def test_cli_init_rejects_native_conflicts_and_wrong_extension(tmp_path: Path):
    script = tmp_path / "scene.pml"
    script.write_text("show cartoon\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["init", str(script), "--native", str(script), "--out", str(tmp_path / "conflict")],
    )
    assert result.exit_code == 1
    assert "Choose one scene-input form" in result.output

    wrong = tmp_path / "scene.py"
    wrong.write_text("print('do not run')\n", encoding="utf-8")
    result = runner.invoke(app, ["init", str(wrong), "--out", str(tmp_path / "wrong")])
    assert result.exit_code == 1
    assert "Unsupported native scene file" in result.output
    assert ".pml" in result.output and ".cxc" in result.output


def test_cli_auto_template_detects_ligand_scene_and_explicit_template_wins(tmp_path: Path):
    script = tmp_path / "ligand.pml"
    script.write_text(
        "select ligand, resn LIG\nselect pocket, byres (ligand around 4)\nshow sticks, ligand\ndistance contacts, ligand, pocket\ncolor magenta, ligand\n",
        encoding="utf-8",
    )
    auto_out = tmp_path / "auto"

    result = runner.invoke(app, ["init", str(script), "--out", str(auto_out)])
    assert result.exit_code == 0, result.output
    semantic = json.loads((auto_out / "semantic_layer.json").read_text(encoding="utf-8"))
    assert semantic["package"]["profile"] == "ligand-binding-pose"
    assert "claim_type: ligand_binding_pose" in (auto_out / "answers.yml").read_text(encoding="utf-8")
    tasks = json.loads((auto_out / "semantic" / "completion_tasks.json").read_text(encoding="utf-8"))
    assert any(task["id"] == "task:ligand-binding-pose:claim" for task in tasks["tasks"])
    assert not any(task["id"] == "task:simple-structure-view:claim" for task in tasks["tasks"])

    explicit_out = tmp_path / "explicit"
    result = runner.invoke(
        app,
        ["init", str(script), "--out", str(explicit_out), "--template", "simple-structure-view"],
    )
    assert result.exit_code == 0, result.output
    semantic = json.loads((explicit_out / "semantic_layer.json").read_text(encoding="utf-8"))
    assert semantic["package"]["profile"] == "simple-structure-view"


def test_cli_auto_template_does_not_turn_displayed_ligand_into_binding_claim(tmp_path: Path):
    script = tmp_path / "display-only-ligand.pml"
    script.write_text("select ligand, resn LIG\nshow sticks, ligand\ncolor magenta, ligand\n", encoding="utf-8")
    out = tmp_path / "pkg"

    result = runner.invoke(app, ["init", str(script), "--out", str(out)])

    assert result.exit_code == 0, result.output
    semantic = json.loads((out / "semantic_layer.json").read_text(encoding="utf-8"))
    assert semantic["package"]["profile"] == "simple-structure-view"


def test_cli_malformed_mvsj_error_names_format_file_and_location(tmp_path: Path):
    scene = tmp_path / "broken scene.mvsj"
    scene.write_text("{\n not-json", encoding="utf-8")

    result = runner.invoke(app, ["init", str(scene), "--out", str(tmp_path / "pkg")])

    assert result.exit_code == 1
    assert "Invalid MolViewSpec JSON" in result.output
    assert "broken scene.mvsj" in result.output
    assert "line 2, column" in result.output


def test_cli_inspect_json_exposes_native_scientific_details(tmp_path: Path):
    script = tmp_path / "scene.cxc"
    script.write_text("color magenta #1/A:42\nrunscript build.py $1\n", encoding="utf-8")
    out = tmp_path / "pkg"
    result = runner.invoke(app, ["init", str(script), "--out", str(out)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["inspect", str(out), "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["observed_scene_operations"]
    assert payload["native_references"]
    assert payload["raw_native_observations"]
    assert "resource_references" in payload
    assert "visual_encoding_semantics" in payload
    assert payload["observed_scene_operations"][0]["operation_id"].startswith("op:")


def test_cli_inspect_text_prioritizes_scientific_operation_over_global_config(tmp_path: Path):
    script = tmp_path / "scene.pml"
    script.write_text(
        "\n".join(
            [
                "set ray_shadows, 0",
                "set antialias, 1",
                "set orthoscopic, 1",
                "set depth_cue, 0",
                "set specular, 0",
                "set ambient, 0.5",
                "set direct, 0.5",
                "color cyan, chain A",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "pkg"
    result = runner.invoke(app, ["init", str(script), "--out", str(out)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["inspect", str(out), "--details"])
    assert result.exit_code == 0, result.output
    operation_block = result.output.split("Recognized scene operations:", 1)[1].split("Visual meanings", 1)[0]
    assert "colored" in operation_block


def test_cli_complete_actions_are_mutually_exclusive(tmp_path: Path):
    image = tmp_path / "figure.png"
    write_png(image)
    out = tmp_path / "pkg"
    result = runner.invoke(app, ["init", "--image", str(image), "--out", str(out)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        app,
        [
            "complete",
            str(out),
            "--emit-template",
            "--check-answers",
            str(out / "answers.yml"),
        ],
    )
    assert result.exit_code == 1
    assert "Choose only one completion action" in result.output


def test_cli_complete_complex_scene_opens_terminal_and_preserves_template(tmp_path: Path, monkeypatch):
    script = tmp_path / "scene.pml"
    script.write_text("color cyan, chain A\n", encoding="utf-8")
    out = tmp_path / "pkg"
    result = runner.invoke(app, ["init", str(script), "--out", str(out)])
    assert result.exit_code == 0, result.output
    answers = out / "answers.yml"
    before = answers.read_text(encoding="utf-8")

    opened = []
    monkeypatch.setattr("claimtrace.terminal.prepare_terminal", lambda package, **kwargs: opened.append((package, kwargs)))
    result = runner.invoke(app, ["complete", str(out)])

    assert result.exit_code == 0, result.output
    assert opened == [(out.resolve(), {})]
    assert answers.read_text(encoding="utf-8") == before
    assert "What should a reader understand" not in result.output


def test_cli_section_prompt_saves_entity_without_requiring_unrelated_answers(tmp_path: Path):
    image = tmp_path / "figure.png"
    write_png(image)
    out = tmp_path / "pkg"
    result = runner.invoke(app, ["init", "--image", str(image), "--out", str(out)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        app,
        ["complete", str(out), "--section", "entities"],
        input="Protein alpha, chain A\n",
    )

    assert result.exit_code == 0, result.output
    saved = (out / "answers.yml").read_text(encoding="utf-8")
    assert "Protein alpha, chain A" in saved
    assert "entity:interactive:" in saved
    semantic = json.loads((out / "semantic_layer.json").read_text(encoding="utf-8"))
    assert semantic["entities"][0]["label"] == "Protein alpha, chain A"
    assert semantic["claims"] == []


def test_cli_section_prompt_preserves_newer_records_and_saved_answer_draft(tmp_path: Path):
    from claimtrace import load_package
    from claimtrace.gui.server import Application

    image = tmp_path / "figure.png"
    write_png(image)
    out = tmp_path / "pkg"
    result = runner.invoke(app, ["init", "--image", str(image), "--out", str(out)])
    assert result.exit_code == 0, result.output
    application = Application(out)
    application.save_claim({
        "claim_text": "The view identifies chain A.", "figure_ref": "Figure A",
        "scene_ids": [application.package.semantic_layer.scenes[0].id],
    })
    application.save_answers({"text": application.answers_text()})
    saved = (out / "answers.yml").read_bytes()
    first = load_package(out).semantic_layer.claims[0]
    application.save_claim({
        "id": first.id, "claim_text": "The view identifies chain B.", "figure_ref": "Figure B",
    })
    before = load_package(out).semantic_layer.model_dump(mode="json")
    task_path = out / "semantic" / "completion_tasks.json"
    tasks_before = json.loads(task_path.read_text(encoding="utf-8"))["tasks"]
    result = runner.invoke(app, ["complete", str(out), "--section", "reuse"], input="CC BY 4.0\n")
    assert result.exit_code == 0, result.output
    after = load_package(out).semantic_layer.model_dump(mode="json")
    assert after["reuse"]["license"] == "CC BY 4.0"
    for key in ("claims", "evidence", "uncertainty", "scenes", "entities", "artifacts"):
        assert after[key] == before[key]
    assert (out / "answers.yml").read_bytes() == saved
    assert (out / "answers.draft.yml").is_file()
    tasks_after = json.loads(task_path.read_text(encoding="utf-8"))["tasks"]
    assert [(t["id"], t["status"]) for t in tasks_after if t["section"] != "reuse"] == [
        (t["id"], t["status"]) for t in tasks_before if t["section"] != "reuse"
    ]
    result = runner.invoke(app, ["complete", str(out), "--section", "claim"], input="The view identifies chain C.\nFigure C\n")
    assert result.exit_code == 0, result.output
    claim, = load_package(out).semantic_layer.claims
    assert claim.id == first.id
    assert claim.claim_text.value == "The view identifies chain C."
    assert claim.claim_text.reviewer == "cli"
    assert claim.scene_ids == first.scene_ids
    result = runner.invoke(app, ["complete", str(out), "--section", "claim"], input="\n\n")
    assert result.exit_code == 0, result.output
    unchanged, = load_package(out).semantic_layer.claims
    assert unchanged.claim_text.value == claim.claim_text.value
    assert unchanged.figure_ref == "Figure C"


def test_cli_multi_claim_prompt_requires_record_choice_before_input(tmp_path: Path):
    from claimtrace.api import init_package

    package = init_package(out=tmp_path / "package", blank=True)
    package.add_claim("First panel observation.", figure_ref="Figure A")
    package.add_claim("Second panel observation.", figure_ref="Figure B")
    before = (package.root / "semantic_layer.json").read_bytes()
    result = runner.invoke(app, ["complete", str(package.root), "--section", "claim"])
    assert result.exit_code == 1
    assert "Choose the record to edit" in result.output
    assert "claimtrace prepare" in result.output
    assert (package.root / "semantic_layer.json").read_bytes() == before


def test_cli_interactive_draft_preserves_a_dangling_answers_symlink(tmp_path: Path):
    from claimtrace.api import init_package

    package = init_package(out=tmp_path / "package", blank=True)
    outside = tmp_path / "outside-answers.yml"
    link = package.root / "answers.yml"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symbolic links are unavailable for this test environment")
    result = runner.invoke(app, ["complete", str(package.root), "--section", "reuse"], input="CC BY 4.0\n")
    assert result.exit_code == 0, result.output
    assert link.is_symlink()
    assert not outside.exists()
    draft = package.root / "answers.draft.yml"
    assert "CC BY 4.0" in draft.read_text(encoding="utf-8")


def test_cli_interactive_success_marks_completion_tasks_answered(tmp_path: Path):
    image = tmp_path / "figure.png"
    write_png(image)
    out = tmp_path / "pkg"
    result = runner.invoke(app, ["init", "--image", str(image), "--out", str(out)])
    assert result.exit_code == 0, result.output

    responses = "\n".join(
        [
            "A simple structure view is shown.",
            "Figure 1A",
            "Protein alpha",
            "Colors are presentation only.",
            "The attached render supports the panel.",
            "No mechanism is asserted.",
            "CC-BY-4.0",
        ]
    ) + "\n"
    result = runner.invoke(app, ["complete", str(out), "--template", "simple-structure-view"], input=responses)
    assert result.exit_code == 0, result.output

    semantic = json.loads((out / "semantic_layer.json").read_text(encoding="utf-8"))
    assert any(entity["label"] == "Protein alpha" for entity in semantic["entities"])
    tasks = json.loads((out / "semantic" / "completion_tasks.json").read_text(encoding="utf-8"))
    assert {task["status"] for task in tasks["tasks"]} == {"answered"}


def test_cli_validate_out_must_stay_in_package(tmp_path: Path):
    out = tmp_path / "pkg"
    result = runner.invoke(app, ["init", "--blank", "--out", str(out)])
    assert result.exit_code == 0, result.output

    outside = tmp_path / "outside.json"
    result = runner.invoke(app, ["validate", str(out), "--out", str(outside)])
    assert result.exit_code == 1
    assert "must stay inside the package directory" in result.output
    assert not outside.exists()


def test_cli_validate_out_rejects_symlinks(tmp_path: Path):
    out = tmp_path / "pkg"
    result = runner.invoke(app, ["init", "--blank", "--out", str(out)])
    assert result.exit_code == 0, result.output
    symlink_out = out / "linked-report.json"
    try:
        symlink_out.symlink_to(out / "real-report.json")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this filesystem")
    result = runner.invoke(app, ["validate", str(out), "--out", str(symlink_out)])
    assert result.exit_code == 1
    assert "through a symbolic link" in result.output

    outside_dir = tmp_path / "outside-dir"
    outside_dir.mkdir()
    linked_parent = out / "linked-parent"
    linked_parent.symlink_to(outside_dir, target_is_directory=True)
    result = runner.invoke(app, ["validate", str(out), "--out", str(linked_parent / "report.json")])
    assert result.exit_code == 1
    assert "must stay inside the package directory" in result.output
    assert not (outside_dir / "report.json").exists()


def test_cli_export_zip_hint_is_platform_neutral(tmp_path: Path):
    source = Path("examples/simple-pymol-structure")
    out = tmp_path / "pkg"
    zip_path = tmp_path / "pkg with space.zip"
    result = runner.invoke(
        app,
        [
            "init",
            str(source / "figure_A.pml"),
            "--image",
            str(source / "figure_A.png"),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    answers = _current_example_answers(out, tmp_path)
    result = runner.invoke(app, ["complete", str(out), "--answers", str(answers)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["export", str(out), "--out", str(zip_path), "--mode", "archive"])
    assert result.exit_code == 0, result.output
    assert f'Extract "{zip_path}" with your file manager' in result.output
    assert 'claimtrace validate "<extracted package folder>"' in result.output
    assert "unzip" not in result.output
    assert "/tmp/claimtrace-roundtrip" not in result.output


def test_cli_hidden_compatibility_no_input_and_multiline_epilog(tmp_path: Path):
    init_help = runner.invoke(app, ["init", "--help"])
    export_help = runner.invoke(app, ["export", "--help"])
    assert init_help.exit_code == 0 and export_help.exit_code == 0
    assert "--no-input" not in init_help.stdout
    assert "--no-input" not in export_help.stdout
    plain_help = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", init_help.stdout)
    normalized_help = " ".join(plain_help.split())
    assert 'claimtrace init --native "figure_A.pml"' in normalized_help

    script = tmp_path / "scene.pml"
    script.write_text("show cartoon\n", encoding="utf-8")
    result = runner.invoke(
        app,
        ["init", str(script), "--out", str(tmp_path / "pkg"), "--no-input"],
    )
    assert result.exit_code == 0, result.output


def test_cli_inspect_default_is_a_task_summary_and_json_stays_detailed(tmp_path: Path):
    script = tmp_path / "scene.pml"
    script.write_text("select pocket, chain A and resi 42\ncolor cyan, pocket\n", encoding="utf-8")
    package = tmp_path / "pkg"
    assert runner.invoke(app, ["init", str(script), "--out", str(package)]).exit_code == 0

    summary = runner.invoke(app, ["inspect", str(package)])
    assert summary.exit_code == 0, summary.output
    assert "Materials: 1 scene file" in summary.output
    assert "What does this figure show?" in summary.output
    assert "SHA256" not in summary.output
    assert "Recognized scene operations" not in summary.output
    assert f'Next: claimtrace prepare "{package}"' in summary.output

    details = runner.invoke(app, ["inspect", str(package), "--details"])
    assert details.exit_code == 0, details.output
    assert "Recognized scene operations" in details.output
    assert "SHA256" in details.output
    payload = json.loads(runner.invoke(app, ["inspect", str(package), "--format", "json"]).stdout)
    assert payload["observed_scene_operations"]
    assert payload["artifacts"]


def test_cli_complete_gui_opens_the_selected_package_and_rejects_mixed_actions(tmp_path: Path, monkeypatch):
    image = tmp_path / "panel.png"
    write_png(image)
    package = tmp_path / "pkg"
    assert runner.invoke(app, ["init", "--image", str(image), "--out", str(package)]).exit_code == 0
    opened = []
    monkeypatch.setattr("claimtrace.gui.server.serve", lambda **kwargs: opened.append(kwargs))

    result = runner.invoke(app, ["complete", str(package), "--gui"])
    assert result.exit_code == 0, result.output
    assert opened == [{"package": package.resolve(), "port": 0, "open_browser": True, "initial_view": "prepare"}]
    result = runner.invoke(app, ["complete", str(package), "--gui", "--answers", str(package / "answers.yml")])
    assert result.exit_code == 1
    assert "Choose only one completion action" in result.output
    result = runner.invoke(app, ["complete", str(package), "--gui", "--section", "claim"])
    assert result.exit_code == 1
    assert len(opened) == 1


def test_cli_image_only_draft_review_guides_scientific_context(tmp_path: Path):
    image = tmp_path / "panel.png"
    write_png(image)
    package = tmp_path / "pkg"
    result = runner.invoke(app, ["init", "--image", str(image), "--out", str(package)])
    assert result.exit_code == 0, result.output
    assert "Image draft" in result.output
    assert result.output.count("claimtrace ") == 1

    for mode in ("draft", "internal", "share", "archive"):
        result = runner.invoke(app, ["review", str(package), "--mode", mode, "--format", "json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["mode"] == mode
        assert payload["workflow"]["lifecycle"]["mode"] == mode
        assert payload["workflow"]["next_action"]["action"] == "new-claim"
        assert payload["audit"]["summary"]["replay_status"] == "unverified"
    result = runner.invoke(app, ["review", str(package)])
    assert result.exit_code == 0, result.output
    assert "Working draft package checks" in result.output
    assert "Add the statement" in result.output
    assert f'claimtrace prepare "{package}"' in result.output
    assert f'claimtrace export "{package}" --mode draft' in result.output


def test_cli_review_filters_claim_and_keeps_package_context(tmp_path: Path):
    from claimtrace.api import load_package

    image = tmp_path / "panel.png"
    write_png(image)
    package = tmp_path / "pkg"
    assert runner.invoke(app, ["init", "--image", str(image), "--out", str(package)]).exit_code == 0
    pkg = load_package(package)
    first = pkg.add_claim("A helix is highlighted.", claim_type="simple_structure_view", figure_ref="A")
    second = pkg.add_claim("The pocket is shown.", claim_type="simple_structure_view", figure_ref="B")
    result = runner.invoke(app, ["review", str(package), "--claim", second.id, "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [item["id"] for item in payload["audit"]["claims"]] == [second.id]
    assert payload["audit"]["summary"]["claims"] == 1
    assert all(task["claim_id"] in (None, second.id) for task in payload["workflow"]["tasks"])
    result = runner.invoke(app, ["review", str(package), "--claim", first.id, "--format", "md"])
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("# ClaimTrace review")
    assert "A helix is highlighted." in result.stdout
    assert "The pocket is shown." not in result.stdout
    assert "**Visual evidence**" in result.stdout
    assert "Scene replay: pending verification in the original viewer." in result.stdout
    result = runner.invoke(app, ["review", str(package), "--claim", "claim:missing"])
    assert result.exit_code == 1
    assert "Available claims" in result.output


def test_cli_review_after_completion_matches_verified_export(tmp_path: Path):
    source = Path("examples/simple-pymol-structure")
    package = tmp_path / "pkg"
    result = runner.invoke(app, ["init", str(source / "figure_A.pml"), "--image", str(source / "figure_A.png"), "--out", str(package)])
    assert result.exit_code == 0, result.output
    answers = _current_example_answers(package, tmp_path)
    result = runner.invoke(app, ["complete", str(package), "--answers", str(answers)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["review", str(package), "--mode", "archive", "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["workflow"]["lifecycle"]["ready"] is True
    assert payload["workflow"]["lifecycle"]["blocking_count"] == 0
    assert payload["audit"]["summary"]["replay_status"] == "unverified"
    result = runner.invoke(app, ["review", str(package), "--mode", "archive"])
    assert result.exit_code == 0, result.output
    assert "Archive package checks: Ready" in result.output
    output = tmp_path / "figure.zip"
    result = runner.invoke(app, ["export", str(package), "--mode", "archive", "--out", str(output)])
    assert result.exit_code == 0, result.output
    with zipfile.ZipFile(output) as archive:
        assert "semantic_layer.json" in archive.namelist()
        assert "validation_report.json" in archive.namelist()


def test_cli_supporting_files_can_start_a_draft_without_an_image(tmp_path: Path):
    table = tmp_path / "contacts.csv"
    table.write_text("residue,distance\n42,3.0\n", encoding="utf-8")
    package = tmp_path / "pkg"
    result = runner.invoke(app, ["init", "--artifact", str(table), "--out", str(package)])
    assert result.exit_code == 0, result.output
    assert "Files draft" in result.output
    assert "Image draft" not in result.output
    assert "Materials: 0 scene files, 0 figure images, 1 supporting file" in result.output
    result = runner.invoke(app, ["review", str(package), "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["workflow"]["lifecycle"]["ready"] is True
    assert {task["action"] for task in payload["workflow"]["tasks"]} >= {"new-claim", "attach"}


def test_cli_prepare_routes_start_existing_package_and_example(tmp_path: Path, monkeypatch):
    package = tmp_path / "pkg"
    assert runner.invoke(app, ["init", "--blank", "--out", str(package)]).exit_code == 0
    opened = []
    monkeypatch.setattr("claimtrace.terminal.prepare_terminal", lambda package, **kwargs: opened.append((package, kwargs)))

    result = runner.invoke(app, ["prepare"])
    assert result.exit_code == 0, result.output
    assert opened[-1][0] is None
    result = runner.invoke(app, ["prepare", str(package), "--expert", "--claim", "2"])
    assert result.exit_code == 0, result.output
    assert opened[-1] == (package.resolve(), {"expert": True, "example": None, "workspace": None, "claim_id": "2"})
    workspace = tmp_path / "practice"
    result = runner.invoke(app, ["prepare", "--example", "ligand-contacts", "--workspace", str(workspace)])
    assert result.exit_code == 0, result.output
    assert opened[-1] == (None, {"expert": False, "example": "ligand-contacts", "workspace": workspace, "claim_id": None})
    result = runner.invoke(app, ["prepare", str(package), "--example", "ligand-contacts"])
    assert result.exit_code == 1
    assert "Choose an existing package or a practice example" in result.output
    assert len(opened) == 3


def test_cli_examples_lists_gui_catalog():
    from claimtrace.gui.examples import example_catalog

    result = runner.invoke(app, ["examples"])
    assert result.exit_code == 0, result.output
    for item in example_catalog():
        assert item["id"] in result.stdout
        assert item["title"] in result.stdout
    assert "claimtrace prepare --example" in result.stdout


def test_cli_init_auto_files_partitions_and_deduplicates_named_inputs(tmp_path: Path):
    script = tmp_path / "scene.pml"
    script.write_text("show cartoon\n", encoding="utf-8")
    image = tmp_path / "panel.png"
    write_png(image)
    model = tmp_path / "model.cif"
    model.write_text("data_synthetic\nloop_\n_atom_site.Cartn_x\n_atom_site.Cartn_y\n_atom_site.Cartn_z\n0 0 0\n", encoding="utf-8")
    table = tmp_path / "contacts.csv"
    table.write_text("residue,distance\n42,3.0\n", encoding="utf-8")
    package = tmp_path / "pkg"
    result = runner.invoke(app, ["init", "--native", str(script), "--file", str(script), "--file", str(image), "--file", str(model), "--file", str(table), "--out", str(package), "--format", "json"])
    assert result.exit_code == 0, result.output
    semantic = json.loads((package / "semantic_layer.json").read_text(encoding="utf-8"))
    assert len(semantic["artifacts"]) == 4
    assert {item["role"] for item in semantic["artifacts"]} == {"native_script", "render_image", "structure", "contact_table"}
    assert len(semantic["scenes"][0]["native_artifact_ids"]) == 1
    result = runner.invoke(app, ["init", "--blank", "--file", str(image), "--out", str(tmp_path / "blank")])
    assert result.exit_code == 1
    assert "Use --blank on its own" in result.output


def test_cli_review_numbered_claims_statuses_and_expert_questions(tmp_path: Path):
    from claimtrace.api import load_package

    package = tmp_path / "pkg"
    assert runner.invoke(app, ["init", "--blank", "--out", str(package)]).exit_code == 0
    pkg = load_package(package)
    first = pkg.add_claim("A helix is highlighted.", claim_type="simple_structure_view", figure_ref="A")
    second = pkg.add_claim("The pocket is shown.", claim_type="simple_structure_view", figure_ref="B")
    result = runner.invoke(app, ["review", str(package), "--claim", "2", "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [item["id"] for item in payload["audit"]["claims"]] == [second.id]
    result = runner.invoke(app, ["review", str(package), "--claim", "2"])
    assert result.exit_code == 0, result.output
    assert "2. B" in result.stdout
    assert "A helix is highlighted." not in result.stdout
    assert first.id not in result.stdout and second.id not in result.stdout
    assert "Visual evidence · Add details:" in result.stdout
    expert = runner.invoke(app, ["review", str(package), "--expert"])
    assert expert.exit_code == 0, expert.output
    assert first.id in expert.stdout and second.id in expert.stdout
    full = json.loads(runner.invoke(app, ["review", str(package), "--format", "json"]).stdout)
    assert len(full["workflow"]["tasks"]) > 3
    for task in full["workflow"]["tasks"]:
        assert task["title"] in expert.stdout


def test_cli_review_export_share_saved_purpose_and_leave_override_read_only(tmp_path: Path):
    from claimtrace.api import load_package
    from claimtrace.workflow import review_package

    image = tmp_path / "panel.png"
    write_png(image)
    package = tmp_path / "pkg"
    assert runner.invoke(app, ["init", "--file", str(image), "--out", str(package)]).exit_code == 0
    pkg = load_package(package)
    pkg.semantic_layer.extensions["gui_lifecycle"] = "archive"
    pkg.save()
    before = (package / "semantic_layer.json").read_bytes()
    assert review_package(package)["workflow"]["lifecycle"]["mode"] == "archive"
    result = runner.invoke(app, ["review", str(package), "--format", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["mode"] == "archive"
    result = runner.invoke(app, ["export", str(package)])
    assert result.exit_code == 1, result.output
    assert not package.with_suffix(".zip").exists()

    result = runner.invoke(app, ["review", str(package), "--mode", "draft", "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["mode"] == "draft"
    assert payload["workflow"]["lifecycle"]["ready"] is True
    assert payload["workflow"]["tasks"]
    result = runner.invoke(app, ["export", str(package), "--mode", "draft"])
    assert result.exit_code == 0, result.output
    with zipfile.ZipFile(package.with_suffix(".zip")) as archive:
        assert json.loads(archive.read("validation_report.json"))["export_mode"] == "draft"
    assert (package / "semantic_layer.json").read_bytes() == before


def test_cli_default_export_uses_working_draft_and_optional_output(tmp_path: Path):
    package = tmp_path / "pkg"
    assert runner.invoke(app, ["init", "--blank", "--out", str(package)]).exit_code == 0
    result = runner.invoke(app, ["export", str(package)])
    assert result.exit_code == 0, result.output
    with zipfile.ZipFile(package.with_suffix(".zip")) as archive:
        assert json.loads(archive.read("validation_report.json"))["export_mode"] == "draft"


def test_cli_review_labels_an_unfinished_figure_as_a_draft(tmp_path: Path):
    from claimtrace.api import load_package

    package = tmp_path / "pkg"
    assert runner.invoke(app, ["init", "--blank", "--out", str(package)]).exit_code == 0
    load_package(package).add_claim("The figure shows a model.", claim_type="simple_structure_view", figure_ref="unknown")
    result = runner.invoke(app, ["review", str(package)])
    assert result.exit_code == 0, result.output
    assert "1. Draft figure" in result.stdout
    assert "1. unknown" not in result.stdout


def test_cli_export_from_inside_package_uses_sibling_zip(tmp_path: Path, monkeypatch):
    package = tmp_path / "my-package"
    assert runner.invoke(app, ["init", "--blank", "--out", str(package)]).exit_code == 0
    monkeypatch.chdir(package)
    for arguments in ([], ["."]):
        result = runner.invoke(app, ["export", *arguments])
        assert result.exit_code == 0, result.output
        output = package.with_suffix(".zip")
        with zipfile.ZipFile(output) as archive:
            assert "semantic_layer.json" in archive.namelist()
        output.unlink()


def test_cli_export_fallback_and_uppercase_zip_suffix(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init", "--blank", "--out", "scene-package"]).exit_code == 0
    result = runner.invoke(app, ["export"])
    assert result.exit_code == 0, result.output
    assert zipfile.is_zipfile(tmp_path / "scene-package.zip")
    result = runner.invoke(app, ["export", "--out", "review.ZIP"])
    assert result.exit_code == 0, result.output
    assert "Exported zip package:" in result.output
    assert zipfile.is_zipfile(tmp_path / "review.ZIP")
