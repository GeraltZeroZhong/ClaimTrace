"""User flows through terminal forms, checking the shared package records."""

import json

import pytest
from PIL import Image
from typer.testing import CliRunner

from claimtrace.api import load_package
from claimtrace.cli import app
from claimtrace.gui.examples import create_example
from claimtrace.gui.server import Application
from claimtrace.terminal import TerminalWorkspace

runner = CliRunner()


def enter(package, *answers, extra=()):
    result = runner.invoke(app, ["prepare", str(package), *extra], input="\n".join(answers) + "\n")
    assert result.exit_code == 0, result.output
    assert "Action needs attention" not in result.output, result.output
    return result


@pytest.mark.parametrize("example", ["highlight-residues", "ligand-contacts", "compare-models"])
def test_practice_prepare_review_export_uses_gui_records(tmp_path, example):
    package = create_example(example, tmp_path)
    evidence_answers = [""] * (9 if example == "ligand-contacts" else 7)
    output = tmp_path / "audit.zip"
    result = enter(
        package.root,
        "1",
        "",
        "",
        "",
        "",
        "2",
        *evidence_answers,
        "3",
        "",
        "",
        "5",
        "6",
        "",
        str(output),
        "0",
    )
    assert output.is_file(), result.output
    assert "Audit exported:" in result.output
    state = Application(package.root).state()
    assert len(state["semantic"]["claims"]) == 1
    claim = state["semantic"]["claims"][0]
    evidence = next(e for e in state["semantic"]["evidence"] if e["id"] in claim["evidence_ids"])
    assert evidence["reviewer"] == "cli"
    assert evidence["source_artifact_ids"]
    assert evidence["method_name"] != "unknown"
    if example == "ligand-contacts":
        assert evidence["thresholds"]["distance"] == 4
        assert evidence["units"]["distance"] == "angstrom"
    assert claim["uncertainty_ids"]
    assert state["workflow"]["lifecycle"]["ready"]


def test_existing_claim_partial_draft_preserves_other_fields(tmp_path):
    package = create_example("highlight-residues", tmp_path)
    enter(package.root, "1", "", "", "", "", "0")
    before = load_package(package.root).semantic_layer.claims[0]
    enter(package.root, "1", "Updated figure statement.", ":draft", "0")
    after = load_package(package.root).semantic_layer.claims[0]
    assert after.id == before.id
    assert after.figure_ref == before.figure_ref
    assert after.scene_ids == before.scene_ids
    assert after.claim_text.value == "Updated figure statement."
    assert after.review_status.value == "needs_review"
    assert after.claim_text.reviewed_at is None


def test_evidence_edit_targets_claim_linked_record_and_retains_draft_fields(tmp_path):
    package = create_example("ligand-contacts", tmp_path)
    enter(package.root, "1", "", "", "", "", "2", *([""] * 9), "0")
    layer = load_package(package.root).semantic_layer
    user_evidence = next(e for e in layer.evidence if e.id in layer.claims[0].evidence_ids)
    native = [e.model_dump(mode="json") for e in layer.evidence if e.id != user_evidence.id]
    enter(package.root, "2", "", ":draft", "0")
    layer = load_package(package.root).semantic_layer
    after = next(e for e in layer.evidence if e.id == user_evidence.id)
    assert after.result_summary == user_evidence.result_summary
    assert after.method_name == user_evidence.method_name
    assert after.source_artifact_ids == user_evidence.source_artifact_ids
    assert after.review_status.value == "needs_review"
    assert [e.model_dump(mode="json") for e in layer.evidence if e.id != user_evidence.id] == native


def test_back_and_eof_leave_current_form_unchanged(tmp_path):
    package = create_example("highlight-residues", tmp_path)
    before = (package.root / "semantic_layer.json").read_bytes()
    result = enter(package.root, "1", "Partial statement", ":back", "0")
    assert "Returned to the menu" in result.output
    assert (package.root / "semantic_layer.json").read_bytes() == before
    result = runner.invoke(app, ["prepare", str(package.root)], input="1\nPartial statement\n")
    assert result.exit_code == 0, result.output
    assert "Session finished" in result.output
    assert (package.root / "semantic_layer.json").read_bytes() == before


def test_incomplete_evidence_saves_explicit_draft(tmp_path):
    package = create_example("ligand-contacts", tmp_path)
    result = enter(
        package.root,
        "1",
        "",
        "",
        "",
        "",
        "2",
        "",
        "0",
        "Inspect the source",
        "Two contacts appear",
        "~",
        "~",
        "",
        "",
        "",
        "0",
    )
    assert "Evidence draft saved" in result.output
    layer = load_package(package.root).semantic_layer
    evidence = next(e for e in layer.evidence if e.id in layer.claims[0].evidence_ids)
    assert evidence.review_status.value == "needs_review"
    assert evidence.source_artifact_ids == []
    assert "distance" not in evidence.thresholds


@pytest.mark.parametrize("measured,cutoff,expected_status", [
    ("", "4", "needs_review"),
    ("2", "~", "confirmed"),
])
def test_measurement_requires_observed_distance_not_contact_cutoff(
    tmp_path, measured, cutoff, expected_status,
):
    package = create_example("ligand-contacts", tmp_path)
    enter(package.root, "1", "", "", "", "", "0")
    result = enter(
        package.root,
        "2", "measurement", "", "Inspect the synthetic atom pair",
        "The selected pair is recorded in the source table.",
        measured, cutoff, "angstrom", "", "", "", "0",
    )
    layer = load_package(package.root).semantic_layer
    evidence = next(e for e in layer.evidence if e.id in layer.claims[0].evidence_ids)
    assert evidence.review_status.value == expected_status
    if measured:
        assert evidence.parameters["measured_distance"] == 2
        assert "distance" not in evidence.thresholds
        assert "Evidence saved." in result.output
    else:
        assert "measured_distance" not in evidence.parameters
        assert evidence.thresholds["distance"] == 4
        assert "Enter the measured distance" in result.output
        assert "Evidence draft saved." in result.output


def test_native_visibility_and_visual_meaning_forms_save(tmp_path, monkeypatch):
    package = create_example("highlight-residues", tmp_path)
    enter(package.root, "1", "", "", "", "", "0")
    workspace = TerminalWorkspace(Application(package.root, interface="cli"))
    monkeypatch.setattr(
        "claimtrace.terminal._text", lambda *a, **k: "Overview with background hidden."
    )
    workspace.scene_form()
    monkeypatch.setattr(
        "claimtrace.terminal._choice", lambda label, options, default=None: next(iter(options))
    )
    workspace.visual_meanings()
    state = Application(package.root).state()
    assert (
        state["semantic"]["scenes"][0]["camera"]["author_context"]
        == "Overview with background hidden."
    )
    assert any(v["reviewer"] == "cli" for v in state["semantic"]["visual_encoding_semantics"])


def test_received_export_edit_uses_working_copy(tmp_path):
    package = create_example("highlight-residues", tmp_path)
    exported = package.export(tmp_path / "received", mode="draft")
    before = (exported / "semantic_layer.json").read_bytes()
    copies = tmp_path / "working"
    result = enter(exported, "1", "", "", "", "", "0", extra=["--workspace", str(copies)])
    assert "Working copy:" in result.output
    assert (exported / "semantic_layer.json").read_bytes() == before
    layers = list(copies.glob("*/semantic_layer.json"))
    assert len(layers) == 1
    assert len(json.loads(layers[0].read_text())["claims"]) == 1


def test_start_from_files_with_spaces_and_select_analysis_plot(tmp_path):
    image = tmp_path / "my plot.png"
    Image.new("RGB", (5, 5)).save(image)
    output = tmp_path / "my package"
    result = runner.invoke(
        app,
        ["prepare"],
        input="\n".join(
            [
                "2",
                str(image),
                "",
                "My analysis plot",
                str(output),
                "4",
                "2",
                "X: residue index; Y: displacement in angstrom.",
                "1",
                "The largest displacement occurs at residue 117.",
                "Figure 1",
                "7",
                "",
                "0",
            ]
        )
        + "\n",
    )
    assert result.exit_code == 0, result.output
    assert "Action needs attention" not in result.output
    layer = load_package(output).semantic_layer
    assert layer.scenes[0].extensions["view_kind"] == "plot"
    assert layer.claims[0].figure_ref == "Figure 1"
    assert layer.scenes[0].camera["author_context"].startswith("X: residue")


def test_multiple_claims_select_by_displayed_number(tmp_path):
    package = create_example("highlight-residues", tmp_path)
    enter(package.root, "1", "", "", "", "", "8", "2", "Second statement", "Figure 2", "", "", "0")
    layer = load_package(package.root).semantic_layer
    assert len(layer.claims) == 2
    enter(package.root, "1", "Updated second statement", "", "", "", "0", extra=["--claim", "2"])
    updated = load_package(package.root).semantic_layer
    assert updated.claims[0].claim_text == layer.claims[0].claim_text
    assert updated.claims[1].claim_text.value == "Updated second statement"


def test_shared_evidence_keeps_other_claim_regions_when_accepting_defaults(tmp_path):
    from claimtrace.api import init_package

    sources = []
    for name, residue in (("first", 42), ("second", 85)):
        source = tmp_path / f"{name}.pml"
        source.write_text(f"select {name}_site, chain A and resi {residue}\nshow sticks, {name}_site\n")
        sources.append(source)
    structure = tmp_path / "model.cif"
    structure.write_text("data_synthetic\n_entry.id synthetic\n")
    package = init_package(native=sources, out=tmp_path / "package")
    structure_id = package.add_artifact(structure, role="structure").id
    gui = Application(package.root)
    for index, scene in enumerate(package.semantic_layer.scenes, 1):
        gui.save_claim({
            "claim_text": f"Scene {index} shows a selected residue.",
            "figure_ref": str(index), "scene_ids": [scene.id],
        })
        claim = gui.package.semantic_layer.claims[-1]
        gui.save_identities({
            "claim_id": claim.id,
            "identities": [{
                "selection_id": scene.selection_ids[0], "entity_type": "residue",
                "label": f"Selected residue in scene {index}",
                "source_artifact_ids": [structure_id],
            }],
        })
    layer = gui.package.semantic_layer
    targets = [selection.id for selection in layer.selections]
    entities = [entity.id for entity in layer.entities]
    gui.save_evidence({
        "claim_id": layer.claims[0].id,
        "method_name": "Compare the selected residues in both scenes.",
        "result_summary": "The scenes select different residues.",
        "source_artifact_ids": [structure_id],
        "target_selection_ids": targets, "target_entity_ids": entities,
    })
    evidence_id = gui.package.semantic_layer.evidence[-1].id
    result = runner.invoke(app, ["set", str(package.root), "/claims/1/evidence_ids", json.dumps([evidence_id])])
    assert result.exit_code == 0, result.output
    result = enter(package.root, "2", *([""] * 8), "0")
    evidence = load_package(package.root).semantic_layer.evidence[-1]
    assert "Evidence saved." in result.output
    assert evidence.target_selection_ids == targets
    assert evidence.target_entity_ids == entities
    assert evidence_id in load_package(package.root).semantic_layer.claims[1].evidence_ids


@pytest.mark.parametrize("existing_kind", ["native", "image"])
def test_add_native_scene_offers_new_scene_and_image_completion(tmp_path, existing_kind):
    from claimtrace.api import init_package

    native = tmp_path / "first.pml"
    native.write_text("show cartoon\n")
    image = tmp_path / "panel.png"
    Image.new("RGB", (5, 5)).save(image)
    kwargs = {"native": native} if existing_kind == "native" else {"image": image}
    package = init_package(out=tmp_path / "package", **kwargs)
    before = package.semantic_layer.scenes[0]
    second = tmp_path / "second.pml"
    second.write_text("select site, chain A and resi 42\nshow sticks, site\n")
    result = enter(package.root, "7", str(second), "", "0")
    layer = load_package(package.root).semantic_layer
    assert "New scene / package source" in result.output
    assert f"File added: {second.name}" in result.output
    if existing_kind == "native":
        assert len(layer.scenes) == 2
        assert layer.scenes[0].native_artifact_ids == before.native_artifact_ids
        assert layer.scenes[1].selection_ids
    else:
        assert len(layer.scenes) == 1
        assert layer.scenes[0].id == before.id
        assert layer.scenes[0].native_artifact_ids
        assert layer.scenes[0].render_artifact_ids == before.render_artifact_ids
        assert layer.scenes[0].selection_ids


def test_add_image_can_start_a_second_scene(tmp_path):
    from claimtrace.api import init_package

    image = tmp_path / "first.png"
    Image.new("RGB", (5, 5)).save(image)
    package = init_package(out=tmp_path / "package", image=image)
    before = package.semantic_layer.scenes[0].model_dump()
    second = tmp_path / "second.png"
    Image.new("RGB", (5, 5), "teal").save(second)
    result = enter(package.root, "7", str(second), "new", "0")
    layer = load_package(package.root).semantic_layer
    assert "File added: second.png" in result.output
    assert len(layer.scenes) == 2
    assert layer.scenes[0].model_dump() == before
    second_ids = layer.scenes[1].render_artifact_ids
    assert len(second_ids) == 1
    assert next(a for a in layer.artifacts if a.id == second_ids[0]).path == "renders/second.png"
