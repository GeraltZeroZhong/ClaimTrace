import json
import re
import zipfile
from pathlib import Path

from typer.testing import CliRunner

from claimtrace import _simple_yaml
from claimtrace.cli import app


runner = CliRunner()


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
    assert "claimtrace 0.1.0" in result.stdout


def test_cli_quickstart_shows_short_user_path():
    result = runner.invoke(app, ["quickstart"])

    assert result.exit_code == 0
    assert "Supported native scene files: .pml, .cxc, .mvsj, .mvsx" in result.stdout
    assert 'claimtrace init "figure_A.pml"' in result.stdout
    assert 'Edit "scene-package/answers.yml"' in result.stdout
    assert "> scene-package/answers.yml" not in result.stdout
    assert "user_declared_no_scientific_meaning" in result.stdout


def test_cli_schema_outputs_json():
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == 0
    assert "Claim Accountability Layer" in result.stdout


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
    script = tmp_path / "输入 scene.pml"
    script.write_text("show cartoon\n", encoding="utf-8")
    out = tmp_path / "结果 package"

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
    assert f'claimtrace inspect "{text_out}"' in result.output
    assert f'Edit "{text_out / "answers.yml"}"' in result.output
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
    assert "positional scene and --native cannot be used together" in result.output

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

    result = runner.invoke(app, ["inspect", str(out)])
    assert result.exit_code == 0, result.output
    operation_block = result.output.split("Recognized scene operations:", 1)[1].split("Visual meanings", 1)[0]
    assert "colored" in operation_block


def test_cli_complete_actions_are_mutually_exclusive(tmp_path: Path):
    image = tmp_path / "figure.png"
    image.write_bytes(b"image")
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


def test_cli_complete_complex_scene_preserves_template_and_guides_without_prompting(tmp_path: Path):
    script = tmp_path / "scene.pml"
    script.write_text("color cyan, chain A\n", encoding="utf-8")
    out = tmp_path / "pkg"
    result = runner.invoke(app, ["init", str(script), "--out", str(out)])
    assert result.exit_code == 0, result.output
    answers = out / "answers.yml"
    before = answers.read_text(encoding="utf-8")

    result = runner.invoke(app, ["complete", str(out)], input="this must not be consumed\n")

    assert result.exit_code == 1
    assert "generic prompts cannot update safely" in result.output
    assert "operation_ids" in result.output
    assert answers.read_text(encoding="utf-8") == before
    assert "What should a reader understand" not in result.output


def test_cli_interactive_failure_saves_entity_answer_in_draft(tmp_path: Path):
    image = tmp_path / "figure.png"
    image.write_bytes(b"image")
    out = tmp_path / "pkg"
    result = runner.invoke(app, ["init", "--image", str(image), "--out", str(out)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        app,
        ["complete", str(out), "--section", "entities"],
        input="Protein alpha, chain A\n",
    )

    assert result.exit_code == 1
    assert "your responses were not discarded" in result.output
    saved = (out / "answers.yml").read_text(encoding="utf-8")
    assert "Protein alpha, chain A" in saved
    assert "entity:interactive:" in saved
    assert "answers.new.yml" in result.output


def test_cli_interactive_success_marks_completion_tasks_answered(tmp_path: Path):
    image = tmp_path / "figure.png"
    image.write_bytes(b"image")
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
    result = runner.invoke(app, ["complete", str(out)], input=responses)
    assert result.exit_code == 0, result.output

    semantic = json.loads((out / "semantic_layer.json").read_text(encoding="utf-8"))
    assert any(entity["label"] == "Protein alpha" for entity in semantic["entities"])
    tasks = json.loads((out / "semantic" / "completion_tasks.json").read_text(encoding="utf-8"))
    assert {task["status"] for task in tasks["tasks"]} == {"answered"}


def test_cli_validate_out_must_stay_in_package_and_rejects_symlinks(tmp_path: Path):
    out = tmp_path / "pkg"
    result = runner.invoke(app, ["init", "--blank", "--out", str(out)])
    assert result.exit_code == 0, result.output

    outside = tmp_path / "outside.json"
    result = runner.invoke(app, ["validate", str(out), "--out", str(outside)])
    assert result.exit_code == 1
    assert "must stay inside the package directory" in result.output
    assert not outside.exists()

    symlink_out = out / "linked-report.json"
    symlink_out.symlink_to(out / "real-report.json")
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
