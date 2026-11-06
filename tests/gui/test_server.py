import base64
import io
import json
import threading
import zipfile
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import quote

import pytest
from PIL import Image

from claimtrace import _simple_yaml, load_package
from claimtrace.gui.server import MAX_REQUEST_BYTES, MAX_TEXT_PREVIEW_BYTES, create_server


def upload(name: str, payload: str | bytes) -> dict[str, str]:
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return {"name": name, "content": base64.b64encode(payload).decode("ascii")}


def png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (12, 12), "#32766e").save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def server(tmp_path: Path):
    instance = create_server(port=0, workspace=tmp_path / "workspace")
    worker = threading.Thread(target=instance.serve_forever, daemon=True)
    worker.start()
    yield instance
    instance.shutdown()
    instance.server_close()
    worker.join(timeout=2)


def request(server, method: str, path: str, body=None, headers=None):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers or {})
    payload = json.dumps(body).encode() if body is not None else None
    connection.request(method, path, body=payload, headers=request_headers)
    response = connection.getresponse()
    result = response.read()
    response_headers = dict(response.getheaders())
    status = response.status
    connection.close()
    if response_headers.get("Content-Type", "").startswith("application/json"):
        result = json.loads(result)
    return status, result, response_headers


def import_package(server):
    status, state, _ = request(
        server,
        "POST",
        "/api/import",
        {
            "title": "Test structure view",
            "files": [
                upload("view.pml", "select site, chain A and resi 42\nshow sticks, site\n"),
                upload("figure.png", png_bytes()),
            ],
        },
    )
    assert status == 200, state
    return state


def test_stale_browser_cannot_edit_or_download_another_package(server):
    first = import_package(server)
    status, second, _ = request(server, "POST", "/api/example", {"id": "ligand-contacts"})
    assert status == 200, second
    root = Path(second["root"])
    before = (root / "semantic_layer.json").read_bytes()
    for endpoint, payload in [
        ("/api/claim", {"claim_text": "A stale draft", "save_draft": True}),
        ("/api/lifecycle", {"mode": "archive"}),
        ("/api/attach", {"files": [upload("stale.txt", "From the first package")]}),
        ("/api/export", {}),
        ("/api/validate", {}),
    ]:
        status, error, _ = request(server, "POST", endpoint, {
            **payload, "package_root": first["root"],
        })
        assert status == 409, (endpoint, error)
        assert "changed in another tab" in error["error"]
    for endpoint in ("/api/audit?format=md", "/api/audit?format=json",
                     "/api/artifact?id=missing", "/api/source?id=missing", "/api/answers?source=current"):
        status, error, _ = request(server, "GET", endpoint + "&package_root=" + quote(first["root"]))
        assert status == 409, (endpoint, error)
    assert (root / "semantic_layer.json").read_bytes() == before
    assert not (root / "data/stale.txt").exists()
    # Refresh still reveals the active package. Reopening the intended package
    # lets the preserved form retry its original request.
    status, refreshed, _ = request(server, "GET", "/api/state")
    assert status == 200 and refreshed["root"] == second["root"]
    status, _, _ = request(server, "POST", "/api/open", {"path": first["root"]})
    assert status == 200
    status, saved, _ = request(server, "POST", "/api/claim", {
        "claim_text": "A stale draft", "save_draft": True, "package_root": first["root"],
    })
    assert status == 200, saved
    assert saved["root"] == first["root"]
    assert saved["semantic"]["claims"][0]["claim_text"]["value"] == "A stale draft"
    status, audit, _ = request(server, "GET", "/api/audit?format=json&package_root=" + quote(first["root"]))
    assert status == 200, audit


@pytest.mark.parametrize("existing_image", [False, True])
def test_new_figure_scene_preserves_original_scene_and_links_claim(server, existing_image):
    state = import_package(server)
    original_scene = state["semantic"]["scenes"][0]
    status, state, _ = request(server, "POST", "/api/claim", {
        "claim_text": "The first panel shows the selected region.", "figure_ref": "Figure A",
        "scene_ids": [original_scene["id"]],
    })
    assert status == 200, state
    claim = state["semantic"]["claims"][0]
    payload = {"role": "render_image", "new_scene": True, "claim_id": claim["id"]}
    if existing_image:
        payload["artifact_ids"] = original_scene["render_artifact_ids"]
    else:
        payload["files"] = [upload("second.png", png_bytes())]
    status, state, _ = request(server, "POST", "/api/attach", payload)
    assert status == 200, state
    scenes = state["semantic"]["scenes"]
    assert len(scenes) == 2
    assert scenes[0] == original_scene
    assert scenes[1]["render_artifact_ids"]
    assert scenes[1]["native_artifact_ids"] == []
    assert state["semantic"]["claims"][0]["scene_ids"] == [scene["id"] for scene in scenes]
    if not existing_image:
        assert set(scenes[0]["render_artifact_ids"]).isdisjoint(scenes[1]["render_artifact_ids"])


def test_failed_new_scene_attachment_restores_files_and_scene_records(server):
    state = import_package(server)
    root = Path(state["root"])
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    status, error, _ = request(server, "POST", "/api/attach", {
        "role": "render_image", "new_scene": True,
        "files": [upload("second.png", png_bytes()), upload("broken.png", b"truncated")],
    })
    assert status == 400, error
    after = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert after == before
    status, restored, _ = request(server, "GET", "/api/state")
    assert status == 200
    assert restored["semantic"] == state["semantic"]


def test_import_open_and_validate_are_persistent_and_read_only(server):
    status, empty, _ = request(server, "GET", "/api/state")
    assert status == 200
    assert empty == {"root": None, "semantic": None, "report": None, "audit": None, "workflow": None}
    state = import_package(server)
    root = Path(state["root"])
    assert root.is_relative_to(server.application.workspace)
    assert (
        root / "native/view.pml"
    ).read_text() == "select site, chain A and resi 42\nshow sticks, site\n"
    before = {
        path.relative_to(root): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }
    for method, endpoint, payload in [
        ("GET", "/api/state", None),
        ("POST", "/api/validate", {}),
        ("POST", "/api/open", {"path": str(root)}),
    ]:
        status, response, _ = request(server, method, endpoint, payload)
        assert status == 200, response
        assert response["semantic"]["package"]["title"] == "Test structure view"
        assert response["report"]["export_mode"] == "draft"
    after = {
        path.relative_to(root): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_lifecycle_selection_persists_and_draft_keeps_author_questions(server):
    state = import_package(server)
    assert state["workflow"]["lifecycle"]["mode"] == "draft"
    assert state["workflow"]["lifecycle"]["ready"] is True
    assert state["workflow"]["next_action"]["action"] == "new-claim"
    status, state, _ = request(server, "POST", "/api/lifecycle", {"mode": "share"})
    assert status == 200
    assert state["workflow"]["lifecycle"]["mode"] == "share"
    assert state["workflow"]["lifecycle"]["ready"] is False
    assert state["workflow"]["lifecycle"]["blocking_count"] > 0
    status, state, _ = request(server, "POST", "/api/open", {"path": state["root"]})
    assert status == 200
    assert state["report"]["export_mode"] == "share"
    status, result, _ = request(server, "POST", "/api/lifecycle", {"mode": "complete"})
    assert status == 400
    assert "Working draft, Lab handoff, External review, or Archive" in result["error"]


def test_partial_claim_and_evidence_survive_reopening(server):
    state = import_package(server)
    status, state, _ = request(server, "POST", "/api/claim", {
        "claim_text": "Working observation of the highlighted region.", "save_draft": True,
    })
    assert status == 200, state
    claim = state["semantic"]["claims"][0]
    assert claim["figure_ref"] == "unknown"
    assert claim["scene_ids"] == []
    assert claim["review_status"] == "needs_review"
    assert claim["claim_text"]["reviewed_at"] is None
    status, state, _ = request(server, "POST", "/api/evidence", {
        "claim_id": claim["id"], "result_summary": "The two residues appear next to the ligand.",
        "save_draft": True,
    })
    assert status == 200, state
    status, reopened, _ = request(server, "POST", "/api/open", {"path": state["root"]})
    assert status == 200
    evidence = reopened["semantic"]["evidence"][0]
    assert evidence["result_summary"] == "The two residues appear next to the ligand."
    assert evidence["source_artifact_ids"] == []
    assert evidence["method_name"] == "unknown"
    assert evidence["review_status"] == "needs_review"
    task = next(task for task in reopened["workflow"]["tasks"] if task["action"] == "edit-evidence")
    assert task["record_id"] == evidence["id"]
    status, error, _ = request(server, "POST", "/api/evidence", {
        "claim_id": claim["id"], "result_summary": "The two residues appear next to the ligand.",
    })
    assert status == 400
    assert "how this was checked" in error["error"]


def test_existing_images_can_be_linked_without_uploading_again(server):
    status, state, _ = request(server, "POST", "/api/import", {
        "title": "Two views",
        "files": [upload("front.pml", "show cartoon\n"), upload("back.pml", "show sticks\n"),
                  upload("panel.png", png_bytes())],
    })
    assert status == 200
    image = next(a for a in state["semantic"]["artifacts"] if a["role"] == "render_image")
    first, second = state["semantic"]["scenes"]
    assert not first["render_artifact_ids"] and not second["render_artifact_ids"]
    before_count = len(state["semantic"]["artifacts"])
    status, linked, _ = request(server, "POST", "/api/attach", {
        "role": "render_image", "scene_id": first["id"], "artifact_ids": [image["id"]],
    })
    assert status == 200, linked
    assert len(linked["semantic"]["artifacts"]) == before_count
    assert linked["semantic"]["scenes"][0]["render_artifact_ids"] == [image["id"]]
    assert not linked["semantic"]["scenes"][1]["render_artifact_ids"]
    saved = (Path(linked["root"]) / "semantic_layer.json").read_bytes()
    for invalid in [
        {"role": "render_image", "artifact_ids": [image["id"]]},
        {"role": "render_image", "scene_id": first["id"], "artifact_ids": first["native_artifact_ids"]},
    ]:
        status, _, _ = request(server, "POST", "/api/attach", invalid)
        assert status == 400
        assert (Path(linked["root"]) / "semantic_layer.json").read_bytes() == saved


def test_late_native_scene_completes_image_scene_and_preserves_claim_links(server):
    status, state, _ = request(server, "POST", "/api/import", {
        "files": [upload("panel.png", png_bytes())], "title": "Panel first",
    })
    assert status == 200
    scene_id = state["semantic"]["scenes"][0]["id"]
    render_id = state["semantic"]["scenes"][0]["render_artifact_ids"][0]
    status, state, _ = request(server, "POST", "/api/claim", {
        "claim_text": "Chain A residue 42 is highlighted.", "figure_ref": "A", "scene_ids": [scene_id],
    })
    assert status == 200
    status, state, _ = request(server, "POST", "/api/attach", {
        "scene_id": scene_id,
        "files": [
            upload("model.pdb", "ATOM      1  CA  ASP A  42       0.000   0.000   0.000  1.00 20.00           C\nEND\n"),
            upload("view.pml", "load model.pdb, model\nselect site, chain A and resi 42\nshow sticks, site\nzoom site\n"),
        ],
    })
    assert status == 200, state
    assert len(state["semantic"]["scenes"]) == 1
    scene = state["semantic"]["scenes"][0]
    assert scene["id"] == scene_id
    assert scene["native_artifact_ids"]
    assert scene["render_artifact_ids"] == [render_id]
    assert scene["selection_ids"]
    assert state["semantic"]["claims"][0]["scene_ids"] == [scene_id]
    assert state["audit"]["claims"][0]["unresolved_resource_ids"] == []
    before = len(state["semantic"]["observed_scene_operations"])
    status, state, _ = request(server, "POST", "/api/attach", {
        "scene_id": scene_id,
        "files": [upload("view.pml", "load model.pdb, model\nselect site, chain A and resi 42\nshow sticks, site\nzoom site\n")],
    })
    assert status == 200
    assert len(state["semantic"]["observed_scene_operations"]) == before


def test_late_native_import_rolls_back_observations_on_upload_failure(server):
    state = import_package(server)
    root = Path(state["root"])
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    status, error, _ = request(server, "POST", "/api/attach", {
        "files": [upload("second.pml", "select other, chain B\nzoom other\n"), upload("bad.png", "invalid image")],
    })
    assert status == 400
    assert "image" in error["error"].lower()
    after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert after == before


def test_supporting_files_can_start_a_draft_and_add_native_scene_later(server):
    status, state, _ = request(server, "POST", "/api/import", {
        "files": [upload("contacts.csv", "residue,distance\n42,3.0\n")], "title": "Results first",
    })
    assert status == 200, state
    assert state["semantic"]["scenes"] == []
    assert {task["action"] for task in state["workflow"]["tasks"]} >= {"new-claim", "attach"}
    status, state, _ = request(server, "POST", "/api/attach", {
        "files": [upload("later.pml", "select site, chain A and resi 42\nzoom site\n")],
    })
    assert status == 200
    assert len(state["semantic"]["scenes"]) == 1
    assert state["semantic"]["observed_scene_operations"]


def test_earlier_structure_can_be_reattached_at_late_scene_replay_path(server):
    coordinates = "ATOM      1  CA  ASP A  42       0.000   0.000   0.000  1.00 20.00           C\nEND\n"
    status, state, _ = request(server, "POST", "/api/import", {
        "files": [upload("model.pdb", coordinates)],
    })
    assert status == 200
    status, state, _ = request(server, "POST", "/api/attach", {
        "files": [upload("later.pml", "load model.pdb, model\nzoom model\n")],
    })
    assert status == 200
    assert not (Path(state["root"]) / "native/model.pdb").exists()
    question = next(item for item in state["workflow"]["tasks"] if item["action"] == "attach")
    assert "model.pdb" in question["detail"]
    assert state["semantic"]["resource_references"][0]["fixity_status"] != "available"
    status, state, _ = request(server, "POST", "/api/attach", {
        "files": [upload("model.pdb", coordinates)],
    })
    assert status == 200
    assert (Path(state["root"]) / "native/model.pdb").read_text() == coordinates
    assert state["semantic"]["resource_references"][0]["fixity_status"] == "available"
    status, payload, _ = request(server, "POST", "/api/export", {"mode": "draft"})
    assert status == 200
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.read("native/model.pdb").decode() == coordinates
        assert archive.read("native/later.pml") == b"load model.pdb, model\nzoom model\n"


def test_previously_imported_sources_get_the_same_role_as_new_evidence_uploads(server):
    status, state, _ = request(server, "POST", "/api/import", {
        "files": [upload("view.pml", "select site, resi 42\nshow sticks, site\n"),
                  upload("figure.png", png_bytes()), upload("scores.csv", "rank,rmsd\n1,0.4\n"),
                  upload("model.pdb", "ATOM      1  CA  ASP A  42       0.000   0.000   0.000  1.00 20.00           C\n")],
    })
    assert status == 200
    roles = {item["id"]: item["role"] for item in state["semantic"]["artifacts"]}
    table = next(item for item in state["semantic"]["artifacts"] if item["path"].endswith("scores.csv"))
    assert table["role"] == "generic"
    status, state, _ = request(server, "POST", "/api/claim", {
        "claim_text": "The supplied comparison reports a pose difference.", "figure_ref": "Figure B",
        "scene_ids": [state["semantic"]["scenes"][0]["id"]],
    })
    assert status == 200
    status, state, _ = request(server, "POST", "/api/evidence", {
        "claim_id": state["semantic"]["claims"][0]["id"], "evidence_kind": "external_validation",
        "method_name": "Compare supplied pose measurements", "result_summary": "Rank one has RMSD 0.4 angstrom.",
        "source_artifact_ids": list(roles), "files": [upload("extra.csv", "rank,rmsd\n2,1.2\n")],
    })
    assert status == 200, state
    for item in state["semantic"]["artifacts"]:
        assert item["role"] == ("validation_report" if item["path"].endswith(("scores.csv", "extra.csv")) else roles[item["id"]])
    assert len(state["semantic"]["artifacts"]) == len(roles) + 1


def test_evidence_first_then_figure_creates_scene(server):
    status, state, _ = request(server, "POST", "/api/import", {
        "files": [upload("contacts.csv", "residue,distance\n42,3.0\n")],
    })
    assert status == 200
    assert state["semantic"]["scenes"] == []
    status, state, _ = request(server, "POST", "/api/attach", {
        "files": [upload("figure.png", png_bytes())],
    })
    assert status == 200
    assert len(state["semantic"]["scenes"]) == 1
    render_id = state["semantic"]["scenes"][0]["render_artifact_ids"][0]
    assert next(item for item in state["semantic"]["artifacts"] if item["id"] == render_id)["role"] == "render_image"


def test_verified_zip_export_uses_selected_lifecycle(server):
    state = import_package(server)
    status, payload, headers = request(server, "POST", "/api/export", {"mode": "draft"})
    assert status == 200, payload
    assert headers["Content-Type"] == "application/zip"
    assert "attachment" in headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        assert "semantic_layer.json" in names
        assert "native/view.pml" in names
        assert "renders/figure.png" in names
        assert "README.md" in names
        report_name = next(name for name in names if name.endswith("validation_report.json"))
        report = json.loads(archive.read(report_name))
        assert report["export_mode"] == "draft"
        assert report["revalidation"]["performed_on_exported_package"] is True
    status, error, _ = request(server, "POST", "/api/export", {"mode": "archive"})
    assert status == 400
    assert "error" in error
    assert Path(state["root"]).exists()


def test_figure_added_from_draft_claim_links_the_new_scene(server):
    status, state, _ = request(server, "POST", "/api/import", {
        "files": [upload("values.csv", "distance\n3.0\n")],
    })
    assert status == 200
    status, state, _ = request(server, "POST", "/api/claim", {
        "claim_text": "The plotted distance is 3.0 angstrom.", "save_draft": True,
    })
    claim = state["semantic"]["claims"][0]
    assert claim["scene_ids"] == []
    status, state, _ = request(server, "POST", "/api/attach", {
        "role": "render_image", "claim_id": claim["id"],
        "files": [upload("figure.png", png_bytes())],
    })
    assert status == 200, state
    assert state["semantic"]["claims"][0]["scene_ids"] == [state["semantic"]["scenes"][0]["id"]]
    assert state["semantic"]["claims"][0]["review_status"] == "needs_review"
    assert not any(item["title"] == "Which scene shows this claim?" for item in state["workflow"]["tasks"])


def test_partial_csv_preview_identifies_truncation_and_download_preserves_all_rows(server):
    content = ("frame,distance\n" + "100,3.0\n" * 100000).encode()
    status, state, _ = request(server, "POST", "/api/import", {
        "files": [upload("events.csv", content)],
    })
    assert status == 200
    aid = state["semantic"]["artifacts"][0]["id"]
    url = f"/api/artifact?id={quote(aid)}"
    status, preview, headers = request(server, "GET", url)
    assert status == 200 and headers["X-ClaimTrace-Preview"] == "partial"
    assert preview == content[:MAX_TEXT_PREVIEW_BYTES]
    status, downloaded, headers = request(server, "GET", url + "&download=1")
    assert status == 200 and downloaded == content
    assert "X-ClaimTrace-Preview" not in headers


def received_export(server):
    import_package(server)
    status, payload, _ = request(server, "POST", "/api/export", {"mode": "draft"})
    assert status == 200
    root = server.application.workspace.parent / "received"
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        archive.extractall(root)
    status, state, _ = request(server, "POST", "/api/open", {"path": str(root)})
    assert status == 200 and state["is_exported"] is True
    return root


def test_received_export_edit_creates_working_copy_and_can_export_again(server):
    root = received_export(server)
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    status, state, _ = request(server, "POST", "/api/claim", {
        "claim_text": "The recipient records an additional figure observation.", "save_draft": True,
    })
    assert status == 200, state
    working = Path(state["root"])
    assert working != root and working.is_relative_to(server.application.workspace)
    assert state["working_copy_from"] == str(root)
    assert state["is_exported"] is False
    assert state["semantic"]["claims"][0]["claim_text"]["value"].startswith("The recipient")
    assert state["report"]["overall_status"] != "fail"
    status, state, _ = request(server, "POST", "/api/lifecycle", {"mode": "draft"})
    assert status == 200 and state["root"] == str(working)
    assert "working_copy_from" not in state
    status, payload, _ = request(server, "POST", "/api/export", {"mode": "draft"})
    assert status == 200
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        semantic = json.loads(archive.read("semantic_layer.json"))
        assert semantic["claims"][0]["claim_text"]["value"].startswith("The recipient")
    assert {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()} == before
    assert load_package(root).validate(mode="draft").overall_status != "fail"


def test_invalid_received_export_edit_keeps_original_open_and_discards_copy(server):
    root = received_export(server)
    before = set(server.application.workspace.iterdir())
    status, error, _ = request(server, "POST", "/api/claim", {"claim_text": ""})
    assert status == 400 and "Enter the claim" in error["error"]
    assert server.application.package.root == root
    assert set(server.application.workspace.iterdir()) == before
    assert load_package(root).validate(mode="draft").overall_status != "fail"


def test_changed_received_export_is_reported_before_creating_a_copy(server):
    root = received_export(server)
    (root / "native/view.pml").write_text("modified after export")
    before = set(server.application.workspace.iterdir())
    status, error, _ = request(server, "POST", "/api/lifecycle", {"mode": "draft"})
    assert status == 400
    assert "view.pml" in error["error"]
    assert "Open the original download" in error["error"]
    assert server.application.package.root == root
    assert set(server.application.workspace.iterdir()) == before


def test_guided_context_records_view_reuse_software_and_source_review(server):
    status, state, _ = request(server, "POST", "/api/import", {
        "files": [upload("custom.pml", "select site, chain A\ncustom_scene_macro site\n")],
    })
    assert status == 200
    scene_id = state["semantic"]["scenes"][0]["id"]
    raw = state["semantic"]["raw_native_observations"][0]
    status, state, _ = request(server, "POST", "/api/context", {
        "reuse": {"license": "Internal laboratory review", "citation": "Project figure A", "restrictions": ["Contact the author for redistribution."]},
        "software": {"name": "PyMOL", "version": "3.1", "command": "pymol custom.pml"},
        "scene": {"id": scene_id, "camera_context": "Named view binding_site, focused on chain A."},
        "raw_reviews": [{"raw_id": raw["raw_id"], "resolution": "reviewed_no_claim_impact", "reason": "This macro adds the presentation title outside the molecular view."}],
    })
    assert status == 200, state
    semantic = state["semantic"]
    assert state["report"]["overall_status"] != "fail", state["report"]["findings"]
    assert semantic["reuse"]["license"] == "Internal laboratory review"
    assert semantic["software_environment"][-1]["version"] == "3.1"
    assert semantic["scenes"][0]["camera"]["author_context"] == "Named view binding_site, focused on chain A."
    assert semantic["raw_native_observations"][0]["native_text"] == raw["native_text"]
    assert semantic["raw_native_observations"][0]["resolution"] == "reviewed_no_claim_impact"
    activity = next(item for item in semantic["provenance"]["activities"] if item["activity_type"] == "gui_review_source")
    assert activity["generated_ids"] == [raw["raw_id"]]
    assert "presentation title" in activity["description"]
    root = Path(state["root"])
    before = (root / "semantic_layer.json").read_bytes()
    status, _, _ = request(server, "POST", "/api/context", {
        "reuse": {"license": "Changed"}, "scene": {"id": "scene:missing", "camera_context": "Front view"},
    })
    assert status == 400
    assert (root / "semantic_layer.json").read_bytes() == before


def test_image_view_type_can_be_recorded_and_restored(server):
    status, state, _ = request(server, "POST", "/api/import", {
        "files": [upload("events.png", png_bytes())],
    })
    assert status == 200
    scene_id = state["semantic"]["scenes"][0]["id"]
    for kind in ("plot", "figure_assembly", "molecular"):
        status, state, _ = request(server, "POST", "/api/context", {
            "scene": {"id": scene_id, "view_kind": kind, "camera_context": "Time 0–499 ns; selected interaction rows."},
        })
        assert status == 200, state
        assert state["semantic"]["scenes"][0]["extensions"]["view_kind"] == kind
    root = Path(state["root"])
    before = (root / "semantic_layer.json").read_bytes()
    status, _, _ = request(server, "POST", "/api/context", {
        "scene": {"id": scene_id, "view_kind": "invalid"},
    })
    assert status == 400
    assert (root / "semantic_layer.json").read_bytes() == before


def test_molecular_scene_keeps_its_replay_requirements(server):
    state = import_package(server)
    root = Path(state["root"])
    before = (root / "semantic_layer.json").read_bytes()
    status, _, _ = request(server, "POST", "/api/context", {
        "scene": {"id": state["semantic"]["scenes"][0]["id"], "view_kind": "plot"},
    })
    assert status == 400
    assert (root / "semantic_layer.json").read_bytes() == before


def test_claim_evidence_uncertainty_and_attachment_roundtrip(server):
    state = import_package(server)
    scene = state["semantic"]["scenes"][0]["id"]
    status, state, _ = request(
        server,
        "POST",
        "/api/claim",
        {
            "claim_text": "Panel A highlights the selected residues.",
            "claim_type": "selection_highlight",
            "figure_ref": "Figure 1A",
            "scene_ids": [scene],
        },
    )
    assert status == 200, state
    claim_id = state["semantic"]["claims"][0]["id"]
    status, state, _ = request(
        server,
        "POST",
        "/api/attach",
        {
            "files": [upload("contacts.csv", "residue,distance\n42,3.5\n")],
            "role": "contact_table",
        },
    )
    assert status == 200, state
    contact = next(
        item for item in state["semantic"]["artifacts"] if item["role"] == "contact_table"
    )
    status, state, _ = request(
        server,
        "POST",
        "/api/evidence",
        {
            "claim_id": claim_id,
            "method_name": "Author contact analysis",
            "result_summary": "Residue 42 lies within the recorded cutoff.",
            "source_artifact_ids": [contact["id"]],
            "evidence_kind": "contact_table",
            "thresholds": {"distance": 4.0},
            "units": {"distance": "angstrom"},
        },
    )
    assert status == 200, state
    evidence_id = state["semantic"]["claims"][0]["evidence_ids"][0]
    assert state["semantic"]["evidence"][0]["provenance_id"]
    status, state, _ = request(
        server,
        "POST",
        "/api/uncertainty",
        {
            "claim_id": claim_id,
            "statement": "Selection membership does not establish a physical interaction.",
        },
    )
    assert status == 200, state
    uncertainty_id = state["semantic"]["claims"][0]["uncertainty_ids"][0]
    status, state, _ = request(
        server,
        "POST",
        "/api/claim",
        {
            "id": claim_id,
            "claim_text": "Panel A highlights residue 42.",
            "figure_ref": "Figure 1A",
            "scene_ids": [scene],
        },
    )
    assert status == 200, state
    saved = load_package(state["root"]).semantic_layer.claims[0]
    assert saved.evidence_ids == [evidence_id]
    assert saved.uncertainty_ids == [uncertainty_id]
    assert saved.claim_type.value == "selection_highlight"
    status, payload, headers = request(
        server, "GET", f"/api/artifact?id={quote(contact['id'])}&download=1"
    )
    assert status == 200
    assert payload == b"residue,distance\n42,3.5\n"
    assert "attachment" in headers["Content-Disposition"]
    status, payload, _ = request(server, "GET", f"/api/source?id={quote(contact['id'])}")
    assert status == 200
    assert payload == b"residue,distance\n42,3.5\n"


def test_evidence_upload_saves_sources_and_claim_link_together(server):
    state = import_package(server)
    package = load_package(state["root"])
    claim = package.add_claim("The selected residues contact the ligand.", figure_ref="A")
    existing_source = state["semantic"]["artifacts"][0]["id"]
    status, state, _ = request(
        server,
        "POST",
        "/api/evidence",
        {
            "claim_id": claim.id,
            "method_name": "Contact analysis",
            "result_summary": "Residue 42 lies within 4 angstrom.",
            "evidence_kind": "contact_table",
            "source_artifact_ids": [existing_source],
            "files": [upload("distances.csv", "residue,distance\n42,3.5\n")],
            "thresholds": {"distance": 4},
            "units": {"distance": "angstrom"},
        },
    )
    assert status == 200, state
    evidence = state["semantic"]["evidence"][0]
    source = next(
        item for item in state["semantic"]["artifacts"] if item["role"] == "contact_table"
    )
    assert evidence["source_artifact_ids"] == [existing_source, source["id"]]
    assert state["semantic"]["claims"][0]["evidence_ids"] == [evidence["id"]]
    assert (Path(state["root"]) / source["path"]).read_text() == "residue,distance\n42,3.5\n"
    activity = next(
        item
        for item in state["semantic"]["provenance"]["activities"]
        if item["id"] == evidence["provenance_id"]
    )
    assert activity["used_artifact_ids"] == evidence["source_artifact_ids"]


@pytest.mark.parametrize("failure", ["invalid_evidence", "invalid_upload", "final_save"])
def test_evidence_upload_failure_restores_files_and_records(server, monkeypatch, failure):
    from claimtrace.api import ClaimTracePackage

    state = import_package(server)
    package = load_package(state["root"])
    claim = package.add_claim("The selected residues contact the ligand.", figure_ref="A")
    root = package.root
    before = (root / "semantic_layer.json").read_bytes()
    data = {
        "claim_id": claim.id,
        "method_name": "Contact analysis",
        "result_summary": "Residue 42 lies within 4 angstrom.",
        "evidence_kind": "contact_table",
        "files": [upload("distances.csv", "residue,distance\n42,3.5\n")],
    }
    if failure == "invalid_evidence":
        data["method_name"] = ""
    elif failure == "invalid_upload":
        data["files"].append(upload("broken.png", "invalid image"))
    else:
        original_save = ClaimTracePackage.save

        def fail_after_evidence_edit(self):
            if self.semantic_layer.evidence:
                raise OSError("Test interrupted evidence save.")
            return original_save(self)

        monkeypatch.setattr(ClaimTracePackage, "save", fail_after_evidence_edit)
    status, error, _ = request(server, "POST", "/api/evidence", data)
    assert status == 400, error
    assert (root / "semantic_layer.json").read_bytes() == before
    assert not (root / "evidence/distances.csv").exists()
    assert not (root / "renders/broken.png").exists()
    assert server.application.package.semantic_layer.evidence == []


def test_answers_are_real_explicit_and_failures_leave_saved_package_untouched(server):
    state = import_package(server)
    root = Path(state["root"])
    status, result, _ = request(server, "GET", "/api/answers")
    assert status == 200
    assert not (root / "answers.yml").exists()
    before = (root / "semantic_layer.json").read_bytes()
    status, error, _ = request(server, "POST", "/api/answers", {"text": "claim: ["})
    assert status == 400
    assert "YAML" in error["error"]
    assert (root / "semantic_layer.json").read_bytes() == before
    answers = _simple_yaml.loads(result["text"])
    answers["claim"]["claim_text"] = "Panel A highlights residue 42."
    answers["claim"]["figure_ref"] = "Figure 1A"
    answers["evidence"] = []
    answers["uncertainty"] = []
    text = _simple_yaml.dumps(answers)
    status, result, _ = request(server, "POST", "/api/answers", {"text": text})
    assert status == 200, result
    assert (root / "answers.yml").read_text() == text
    assert (
        result["semantic"]["claims"][0]["claim_text"]["value"] == "Panel A highlights residue 42."
    )
    status, result, _ = request(server, "GET", "/api/answers?source=saved")
    assert status == 200
    assert result["text"] == text
    assert result["source"] == "saved"


def test_bad_requests_do_not_change_current_package(server):
    state = import_package(server)
    root = Path(state["root"])
    before = (root / "semantic_layer.json").read_bytes()
    cases = [
        ("/api/claim", {"claim_text": "One claim", "figure_ref": "A", "scene_ids": ["missing"]}),
        ("/api/claim", {"claim_text": "", "figure_ref": "A", "scene_ids": []}),
        (
            "/api/evidence",
            {"claim_id": "missing", "method_name": "review", "result_summary": "no source"},
        ),
        ("/api/import", {"files": [upload("../escaped.txt", "unsafe")]}),
        ("/api/import", {"files": [upload(".aws/credentials", "unsafe")]}),
        ("/api/import", {"files": [upload("a.pml", "show cartoon"), upload("a.pml", "hide all")]}),
        ("/api/import", {"files": [{"name": "a.txt", "content": "!notbase64"}]}),
    ]
    for endpoint, payload in cases:
        status, error, _ = request(server, "POST", endpoint, payload)
        assert status in {400, 403}, error
        assert error["error"]
        assert (root / "semantic_layer.json").read_bytes() == before
        assert server.application.package.root == root


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({"Host": "attacker.test"}, 403),
        ({"Origin": "https://attacker.test"}, 403),
        ({"Origin": "null"}, 403),
        ({"Sec-Fetch-Site": "cross-site"}, 403),
        ({"Content-Type": "text/plain"}, 415),
        ({"Content-Length": str(MAX_REQUEST_BYTES + 1)}, 413),
    ],
)
def test_http_boundary_rejects_cross_site_and_oversized_mutations(server, headers, expected):
    # Header preflight rejects these requests before a body is sent. Sending
    # the body afterward can race the server's closed connection on Windows.
    status, result, _ = request(server, "POST", "/api/validate", headers=headers)
    assert status == expected
    assert result["error"]
    assert server.application.package is None


def test_registered_artifact_cannot_escape_package(server, tmp_path: Path):
    state = import_package(server)
    artifact = state["semantic"]["artifacts"][0]
    original = Path(state["root"]) / artifact["path"]
    original.unlink()
    secret = tmp_path / "outside.txt"
    secret.write_text("do not expose")
    try:
        original.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this filesystem")
    status, error, _ = request(server, "GET", f"/api/artifact?id={quote(artifact['id'])}")
    assert status == 403
    assert "Symbolic links" in error["error"]
    status, _, _ = request(server, "GET", "/api/artifact?id=../../outside.txt")
    assert status == 404


def test_tiff_preview_keeps_original_download(server):
    state = import_package(server)
    image = io.BytesIO()
    Image.new("RGB", (20, 15), "white").save(image, format="TIFF")
    content = image.getvalue()
    status, state, _ = request(
        server,
        "POST",
        "/api/attach",
        {
            "files": [upload("panel.tif", content)],
            "scene_id": state["semantic"]["scenes"][0]["id"],
        },
    )
    assert status == 200, state
    artifact = next(
        item for item in state["semantic"]["artifacts"] if item["path"].endswith("panel.tif")
    )
    status, preview, headers = request(server, "GET", f"/api/artifact?id={quote(artifact['id'])}")
    assert status == 200
    assert headers["Content-Type"] == "image/png"
    assert Image.open(io.BytesIO(preview)).size == (20, 15)
    status, original, _ = request(
        server, "GET", f"/api/artifact?id={quote(artifact['id'])}&download=1"
    )
    assert status == 200
    assert original == content


def test_failed_multi_attachment_rolls_back_earlier_files(server):
    state = import_package(server)
    root = Path(state["root"])
    original = (root / "semantic_layer.json").read_bytes()
    status, result, _ = request(
        server,
        "POST",
        "/api/attach",
        {
            "files": [upload("new-note.txt", "new note"), upload("broken.png", "not an image")],
        },
    )
    assert status == 400, result
    assert "cannot be decoded" in result["error"]
    assert (root / "semantic_layer.json").read_bytes() == original
    assert not (root / "data/new-note.txt").exists()
    assert not (root / "renders/broken.png").exists()


def test_generated_answers_preserve_current_claims_and_links(server):
    state = import_package(server)
    for name in ("First", "Second"):
        status, state, _ = request(
            server,
            "POST",
            "/api/claim",
            {
                "claim_text": f"{name} panel claim.",
                "figure_ref": name,
                "scene_ids": [state["semantic"]["scenes"][0]["id"]],
            },
        )
        assert status == 200, state
    status, payload, _ = request(server, "GET", "/api/answers")
    assert status == 200
    answers = _simple_yaml.loads(payload["text"])
    assert "claim" not in answers
    assert [item["claim_text"] for item in answers["claims"]] == [
        "First panel claim.",
        "Second panel claim.",
    ]
    assert [item["id"] for item in answers["claims"]] == [
        item["id"] for item in state["semantic"]["claims"]
    ]


def test_current_answers_do_not_revert_simple_form_changes(server):
    state = import_package(server)
    status, response, _ = request(server, "GET", "/api/answers")
    assert status == 200
    answers = _simple_yaml.loads(response["text"])
    answers["claim"]["claim_text"] = "Original author claim."
    answers["claim"]["figure_ref"] = "A"
    answers["evidence"] = []
    answers["uncertainty"] = []
    answers["author_workflow_note"] = "Preserve the existing expert notes."
    saved_text = _simple_yaml.dumps(answers)
    status, state, _ = request(server, "POST", "/api/answers", {"text": saved_text})
    assert status == 200, state
    claim = state["semantic"]["claims"][0]
    status, state, _ = request(
        server,
        "POST",
        "/api/claim",
        {
            "id": claim["id"],
            "claim_text": "Revised author claim.",
            "figure_ref": "A",
            "scene_ids": claim["scene_ids"],
        },
    )
    assert status == 200, state
    status, current, _ = request(server, "GET", "/api/answers")
    assert status == 200
    assert current["source"] == "current"
    assert current["saved_available"] is True
    current_answers = _simple_yaml.loads(current["text"])
    assert current_answers["claims"][0]["claim_text"] == "Revised author claim."
    assert current_answers["author_workflow_note"] == answers["author_workflow_note"]
    status, original, _ = request(server, "GET", "/api/answers?source=saved")
    assert status == 200
    assert original["text"] == saved_text
    assert (Path(state["root"]) / "answers.yml").read_text() == saved_text
    status, state, _ = request(server, "POST", "/api/answers", {"text": current["text"]})
    assert status == 200, state
    assert state["semantic"]["claims"][0]["claim_text"]["value"] == "Revised author claim."


def test_edit_accepts_one_sided_claim_evidence_and_uncertainty_links(server):
    from claimtrace.models.semantic_layer import Evidence, Uncertainty

    state = import_package(server)
    package = load_package(state["root"])
    claim = package.add_claim("A recorded view.", figure_ref="A")
    package.semantic_layer.evidence.append(Evidence(id="evidence:one-sided"))
    package.semantic_layer.uncertainty.append(Uncertainty(id="uncertainty:one-sided"))
    claim.evidence_ids = ["evidence:one-sided"]
    claim.uncertainty_ids = ["uncertainty:one-sided"]
    package.save()
    status, state, _ = request(
        server,
        "POST",
        "/api/evidence",
        {
            "id": "evidence:one-sided",
            "claim_id": claim.id,
            "method_name": "Author review",
            "result_summary": "The source was reviewed.",
        },
    )
    assert status == 200, state
    assert state["semantic"]["evidence"][0]["claim_ids"] == [claim.id]
    status, state, _ = request(
        server,
        "POST",
        "/api/uncertainty",
        {
            "id": "uncertainty:one-sided",
            "claim_id": claim.id,
            "statement": "This view does not establish a physical interaction.",
        },
    )
    assert status == 200, state
    assert state["semantic"]["uncertainty"][0]["claim_ids"] == [claim.id]


def test_demo_is_explicitly_synthetic_and_audit_downloads(server):
    status, state, _ = request(server, "POST", "/api/demo", {})
    assert status == 200, state
    assert state["semantic"]["extensions"]["gui_demo"] is True
    assert len(state["semantic"]["claims"]) == 2
    assert state["semantic"]["claims"][0]["evidence_ids"] == []
    assert state["semantic"]["claims"][1]["evidence_ids"]
    assert state["semantic"]["evidence"][0]["thresholds"] == {}
    for format in ("json", "md"):
        status, payload, headers = request(server, "GET", f"/api/audit?format={format}")
        assert status == 200
        assert "attachment" in headers["Content-Disposition"]
        assert payload


def test_current_answers_preserve_guided_visual_meaning_and_reuse(server):
    status, state, _ = request(server, "POST", "/api/import", {
        "title": "Visual meaning review",
        "files": [upload("view.cxc", "color teal #1/A:42\n")],
    })
    assert status == 200, state
    status, initial, _ = request(server, "GET", "/api/answers")
    assert status == 200
    answers = _simple_yaml.loads(initial["text"])
    answers["claim"].update(claim_text="The teal selection shows residue 42.", figure_ref="A")
    answers["evidence"] = []
    answers["uncertainty"] = []
    answers["reuse"]["license"] = "CC BY 4.0"
    answers["author_workflow_note"] = "Compare this statement with the assay record."
    for row in answers["scene_semantics_by_operation"]:
        row.update(meaning_status="user_confirmed_meaning", meaning="Teal provides display context.")
        row["author_note"] = "Use the assay terminology."
    saved_text = _simple_yaml.dumps(answers)
    status, state, _ = request(server, "POST", "/api/answers", {"text": saved_text})
    assert status == 200, state
    operation = next(o for o in state["semantic"]["observed_scene_operations"] if o["operation"] == "colored")
    status, state, _ = request(server, "POST", "/api/identities", {
        "claim_id": state["semantic"]["claims"][0]["id"],
        "visual_meanings": [{
            "operation_id": operation["operation_id"],
            "meaning": "Teal marks the residue measured by the assay.",
        }],
    })
    assert status == 200, state
    status, state, _ = request(server, "POST", "/api/context", {
        "reuse": {
            "license": "All rights reserved", "citation": "Updated attribution",
            "restrictions": ["Permission required"],
        },
        "scene": {
            "id": state["semantic"]["scenes"][0]["id"],
            "camera_context": "Chain A, state 1, viewed from the ligand-facing side.",
        },
    })
    assert status == 200, state
    before = state["semantic"]
    status, current, _ = request(server, "GET", "/api/answers")
    assert status == 200, current
    current_answers = _simple_yaml.loads(current["text"])
    assert current_answers["author_workflow_note"] == answers["author_workflow_note"]
    current_meaning = next(row for row in current_answers["scene_semantics_by_operation"]
                           if operation["operation_id"] in row["operation_ids"])
    assert current_meaning["author_note"] == "Use the assay terminology."
    assert current_meaning["meaning"] == "Teal marks the residue measured by the assay."
    status, original, _ = request(server, "GET", "/api/answers?source=saved")
    assert status == 200 and original["text"] == saved_text
    status, state, _ = request(server, "POST", "/api/answers", {"text": current["text"]})
    assert status == 200, state
    after = state["semantic"]
    for field in ("license", "citation", "restrictions"):
        assert after["reuse"][field] == before["reuse"][field]
    assert after["scenes"][0]["camera"] == before["scenes"][0]["camera"]
    for field in ("meaning", "meaning_status", "reviewer", "no_scientific_meaning_reason"):
        assert after["visual_encoding_semantics"][0][field] == before["visual_encoding_semantics"][0][field]
