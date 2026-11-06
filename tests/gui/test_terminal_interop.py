"""Terminal forms preserve saved GUI records during partial edits."""

import typer

from claimtrace.gui.server import Application
from claimtrace.models.semantic_layer import VisibilityRecord
from claimtrace.terminal import TerminalWorkspace


def _workspace(tmp_path):
    gui = Application(workspace=tmp_path)
    gui.example({"id": "highlight-residues"})
    scene_id = gui.state()["semantic"]["scenes"][0]["id"]
    gui.save_claim({
        "claim_text": "Two residues are highlighted.", "figure_ref": "Figure A",
        "claim_type": "simple_structure_view", "scene_ids": [scene_id],
    })
    app = Application(gui.package.root, interface="cli")
    return gui, TerminalWorkspace(app)


def test_partial_terminal_claim_edit_preserves_unvisited_gui_fields(tmp_path, monkeypatch):
    gui, terminal = _workspace(tmp_path)
    before = gui.state()["semantic"]["claims"][0]
    answers = iter(["The selected residues appear in teal.", ":draft"])
    monkeypatch.setattr(typer, "prompt", lambda *a, **kw: next(answers))
    terminal.claim_form()
    after = gui.state()["semantic"]["claims"][0]
    assert after["id"] == before["id"]
    assert after["claim_text"]["value"] == "The selected residues appear in teal."
    assert after["figure_ref"] == before["figure_ref"]
    assert after["scene_ids"] == before["scene_ids"]
    assert after["claim_type"] == before["claim_type"]
    assert after["claim_text"]["reviewer"] == "cli"
    assert after["review_status"] == "needs_review"


def test_partial_terminal_evidence_edit_preserves_unvisited_gui_fields(tmp_path, monkeypatch):
    gui, terminal = _workspace(tmp_path)
    semantic = gui.state()["semantic"]
    claim_id = semantic["claims"][0]["id"]
    sources = [a["id"] for a in semantic["artifacts"] if a["role"] == "structure"]
    gui.save_evidence({
        "claim_id": claim_id, "evidence_kind": "contact_table",
        "source_artifact_ids": sources, "method_name": "Measure the selected atom distances.",
        "result_summary": "The selected pair lies within the recorded cutoff.",
        "parameters": {"analysis_settings": "Chain A; selected atoms."},
        "thresholds": {"distance": 4}, "units": {"distance": "angstrom"},
    })
    before = gui.state()["semantic"]["evidence"][0]

    def prompt(label, **kwargs):
        return ":draft" if label == "How was it checked?" else kwargs.get("default", "")

    monkeypatch.setattr(typer, "prompt", prompt)
    terminal.evidence_form()
    after = gui.state()["semantic"]["evidence"][0]
    for field in ("id", "claim_ids", "evidence_kind", "source_artifact_ids", "method_name",
                  "result_summary", "parameters", "thresholds", "units"):
        assert after[field] == before[field], field
    assert after["reviewer"] == "cli"
    assert after["review_status"] == "needs_review"


def test_clearing_terminal_evidence_regions_clears_their_derived_entity_links(tmp_path, monkeypatch):
    gui, terminal = _workspace(tmp_path)
    semantic = gui.state()["semantic"]
    selection = next(s for s in semantic["selections"] if s["entity_ids"])
    claim_id = semantic["claims"][0]["id"]
    source_id = next(a["id"] for a in semantic["artifacts"] if a["role"] == "structure")
    gui.save_evidence({
        "claim_id": claim_id, "evidence_kind": "manual_rationale",
        "source_artifact_ids": [source_id], "method_name": "Inspect the highlighted region.",
        "result_summary": "The selected residues occur in the coordinate file.",
        "target_selection_ids": [selection["id"]], "target_entity_ids": selection["entity_ids"],
    })

    def prompt(label, **kwargs):
        return "0" if label.startswith("Regions used in this check") else kwargs.get("default", "")

    monkeypatch.setattr(typer, "prompt", prompt)
    terminal.evidence_form()
    evidence = gui.state()["semantic"]["evidence"][0]
    assert evidence["target_selection_ids"] == []
    assert evidence["target_entity_ids"] == []


def test_terminal_scene_context_and_visual_meaning_use_imported_model_fields(tmp_path, monkeypatch):
    gui, terminal = _workspace(tmp_path)

    def context_prompt(label, **kwargs):
        return "Chain A, state 1, with the selected residues in front." if label == "View, camera, and state" else kwargs.get("default", "")

    monkeypatch.setattr(typer, "prompt", context_prompt)
    terminal.scene_form()
    scene = gui.state()["semantic"]["scenes"][0]
    assert scene["camera"]["author_context"] == "Chain A, state 1, with the selected residues in front."
    assert scene["extensions"]["gui_camera_context"]["reviewer"] == "cli"

    def meaning_prompt(label, **kwargs):
        if label == "Visual cue":
            return "3"
        if label == "Meaning":
            return "Teal identifies the selected chain A residues."
        return kwargs.get("default", "")

    monkeypatch.setattr(typer, "prompt", meaning_prompt)
    terminal.visual_meanings()
    semantic = gui.state()["semantic"]
    assert any(v["reviewer"] == "cli" and v["meaning"] == "Teal identifies the selected chain A residues."
               for v in semantic["visual_encoding_semantics"])


def test_terminal_can_clear_saved_scene_context_and_visibility_reason(tmp_path, monkeypatch):
    gui, terminal = _workspace(tmp_path)
    scene = gui.package.semantic_layer.scenes[0]
    scene.visibility.append(VisibilityRecord(native_target="solvent", state="hidden"))
    gui.package.save()
    hidden_index = next(i for i, row in enumerate(scene.visibility) if row.state == "hidden")
    gui.save_context({"scene": {
        "id": scene.id, "camera_context": "An obsolete orientation description.",
        "visibility": [{"index": hidden_index, "reason": "An obsolete visibility explanation."}],
    }})
    before = gui.state()["semantic"]["scenes"][0]

    def prompt(label, **kwargs):
        return "~" if label == "View, camera, and state" or label.startswith("Why is ") else kwargs.get("default", "")

    monkeypatch.setattr(typer, "prompt", prompt)
    terminal.scene_form()
    after = gui.state()["semantic"]["scenes"][0]
    assert "author_context" not in after["camera"]
    assert "gui_camera_context" not in after["extensions"]
    assert after["camera"] == {key: value for key, value in before["camera"].items() if key != "author_context"}
    assert after["visibility"][hidden_index]["reason"] == "unknown"
    assert after["visibility"][hidden_index]["review_status"] == "needs_review"
