"""Shared authoring records retain their actual interface and stable links."""

import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from claimtrace import load_package
from claimtrace.gui.server import Application


def _upload(name: str, content: str | bytes) -> dict[str, str]:
    payload = content.encode() if isinstance(content, str) else content
    return {"name": name, "content": base64.b64encode(payload).decode()}


def _application(tmp_path: Path, interface: str | None = None) -> Application:
    options = {} if interface is None else {"interface": interface}
    application = Application(workspace=tmp_path / "workspace", **options)
    image = io.BytesIO()
    Image.new("RGB", (12, 12), "#32766e").save(image, format="PNG")
    application.import_files({
        "title": "Selected residue review",
        "files": [
            _upload("view.pml", "load model.pdb, model\nselect site, chain A and resi 42\n"
                    "show sticks, site\ncolor teal, site\ncustom_scene_macro site\n"),
            _upload("view.png", image.getvalue()),
            _upload("model.pdb", "ATOM      1  CA  ASP A  42       0.000   0.000   0.000  1.00 20.00           C\nEND\n"),
        ],
    })
    return application


def _record_claim(application: Application) -> dict:
    semantic = application.state()["semantic"]
    application.save_claim({
        "claim_text": "The view highlights chain A residue 42.",
        "figure_ref": "Figure A", "claim_type": "simple_structure_view",
        "scene_ids": [semantic["scenes"][0]["id"]],
    })
    return application.state()["semantic"]["claims"][0]


def _record_support(application: Application, claim_id: str) -> dict:
    semantic = application.state()["semantic"]
    source_ids = [item["id"] for item in semantic["artifacts"] if item["role"] == "structure"]
    application.save_evidence({
        "claim_id": claim_id, "evidence_kind": "manual_rationale",
        "method_name": "Inspect the scene and coordinate source.",
        "result_summary": "Chain A residue 42 is present in the coordinate source.",
        "source_artifact_ids": source_ids,
        "parameters": {"analysis_settings": "Chain A; residue 42."},
    })
    application.save_uncertainty({
        "claim_id": claim_id, "statement": "This view shows one conformation.",
    })
    raw = semantic["raw_native_observations"][0]
    application.save_context({
        "scene": {"id": semantic["scenes"][0]["id"], "camera_context": "Chain A site in the supplied view."},
        "software": {"name": "PyMOL", "version": "3.1", "command": "pymol native/view.pml"},
        "reuse": {"license": "CC BY 4.0", "citation": "Synthetic teaching figure"},
        "raw_reviews": [{"raw_id": raw["raw_id"], "resolution": "reviewed_no_claim_impact",
                         "reason": "The macro adds the panel title."}],
    })
    return application.state()["semantic"]


@pytest.mark.parametrize("interface", [None, "cli"], ids=["default-gui", "cli"])
def test_authoring_records_and_context_identify_their_interface(tmp_path, interface):
    application = _application(tmp_path, interface)
    expected = interface or "gui"
    claim = _record_claim(application)
    semantic = _record_support(application, claim["id"])
    assert claim["id"].startswith(f"claim:{expected}:")
    assert claim["claim_text"]["reviewer"] == expected
    evidence, = semantic["evidence"]
    uncertainty, = semantic["uncertainty"]
    software, = semantic["software_environment"]
    assert evidence["id"].startswith(f"evidence:{expected}:")
    assert evidence["reviewer"] == expected
    assert evidence["generated_by"] == f"author via ClaimTrace {expected.upper()}"
    assert uncertainty["id"].startswith(f"uncertainty:{expected}:")
    assert uncertainty["reviewer"] == expected
    assert software["id"].startswith(f"software:{expected}:")
    assert software["extensions"]["reviewer"] == expected
    assert semantic["reuse"]["reviewer"] == expected
    assert semantic["scenes"][0]["extensions"]["gui_camera_context"]["reviewer"] == expected
    activities = {item["activity_type"]: item for item in semantic["provenance"]["activities"]}
    for suffix in ("add_claim", "add_evidence", "record_uncertainty", "record_context", "review_source"):
        activity = activities[f"{expected}_{suffix}"]
        assert activity["id"].startswith(f"activity:{expected}_{suffix}:")
    assert activities[f"{expected}_review_source"]["extensions"]["reviewer"] == expected
    assert evidence["provenance_id"] == activities[f"{expected}_add_evidence"]["id"]
    assert load_package(application.package.root).semantic_layer.claims[0].claim_text.reviewer == expected


def test_cli_edits_gui_records_without_replacing_their_ids(tmp_path):
    original = _application(tmp_path)
    claim = _record_claim(original)
    before = _record_support(original, claim["id"])
    evidence, = before["evidence"]
    uncertainty, = before["uncertainty"]
    software, = before["software_environment"]
    terminal = Application(original.package.root, interface="cli")
    terminal.save_claim({
        "id": claim["id"], "claim_text": "The saved view locates chain A residue 42.",
        "figure_ref": "Figure A", "claim_type": "simple_structure_view", "scene_ids": claim["scene_ids"],
    })
    terminal.save_evidence({
        "id": evidence["id"], "claim_id": claim["id"], "method_name": "Inspect residue identities.",
        "result_summary": "The displayed residue matches the coordinate identity.",
        "source_artifact_ids": evidence["source_artifact_ids"],
    })
    terminal.save_uncertainty({
        "id": uncertainty["id"], "claim_id": claim["id"],
        "statement": "The saved structure provides a static view.",
    })
    terminal.save_context({"software": {"id": software["id"], "name": "PyMOL", "version": "3.1.1"}})
    after = original.state()["semantic"]
    for section in ("claims", "evidence", "uncertainty", "software_environment"):
        assert [item["id"] for item in after[section]] == [item["id"] for item in before[section]]
    assert after["claims"][0]["claim_text"]["reviewer"] == "cli"
    assert after["evidence"][0]["reviewer"] == "cli"
    assert after["evidence"][0]["generated_by"] == "author via ClaimTrace CLI"
    assert after["uncertainty"][0]["reviewer"] == "cli"
    assert after["software_environment"][0]["extensions"]["reviewer"] == "cli"
    assert after["claims"][0]["evidence_ids"] == [evidence["id"]]
    assert after["claims"][0]["uncertainty_ids"] == [uncertainty["id"]]
    actions = {item["activity_type"] for item in after["provenance"]["activities"]}
    assert {"gui_add_claim", "gui_add_evidence", "cli_edit_claim", "cli_edit_evidence"} <= actions


def test_scene_identity_and_lifecycle_protocol_keys_work_across_interfaces(tmp_path):
    application = _application(tmp_path, "cli")
    claim = _record_claim(application)
    semantic = application.state()["semantic"]
    selection = semantic["selections"][0]
    structure = next(item for item in semantic["artifacts"] if item["role"] == "structure")
    color = next(item for item in semantic["observed_scene_operations"] if item["operation"] == "colored")
    identity = {"selection_id": selection["id"], "entity_type": "residue", "label": "Chain A ASP 42",
                "source_artifact_ids": [structure["id"]]}
    application.save_identities({"claim_id": claim["id"], "identities": [identity],
                                "visual_meanings": [{"operation_id": color["operation_id"],
                                                     "meaning": "Teal identifies the selected residue."}]})
    application.set_lifecycle({"mode": "internal"})
    browser = Application(application.package.root)
    state = browser.state()
    entity = next(item for item in state["semantic"]["entities"] if "gui_identity" in item["extensions"])
    assert entity["id"].startswith("entity:cli:")
    assert entity["extensions"]["reviewer"] == "cli"
    meaning = next(item for item in state["semantic"]["visual_encoding_semantics"]
                   if color["operation_id"] in item["operation_ids"])
    assert meaning["reviewer"] == "cli"
    assert state["workflow"]["lifecycle"]["mode"] == "internal"
    assert state["semantic"]["extensions"]["gui_lifecycle"] == "internal"
    browser.save_identities({"claim_id": claim["id"], "identities": [{**identity, "label": "Chain A residue ASP 42"}]})
    updated = browser.state()["semantic"]
    same_entities = [item for item in updated["entities"] if "gui_identity" in item["extensions"]]
    assert [item["id"] for item in same_entities] == [entity["id"]]
    assert same_entities[0]["extensions"]["reviewer"] == "gui"


def test_authoring_interface_accepts_only_supported_sources():
    with pytest.raises(ValueError, match="gui or cli"):
        Application(interface="web")
