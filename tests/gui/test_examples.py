import base64
import csv
import json
import math
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

from claimtrace.api import load_package
from claimtrace.gui.audit import export_markdown
from claimtrace.gui.examples import create_example, example_catalog
from claimtrace.gui.server import Application, RequestError, create_server
from claimtrace.models.semantic_layer import MeaningStatus, VisualEncodingSemantics, utc_now


def artifact_path(package, name: str) -> Path:
    artifact = next(
        item for item in package.semantic_layer.artifacts if Path(item.path or "").name == name
    )
    return package.root / artifact.path


def coordinates(path: Path) -> dict[str, tuple[float, float, float]]:
    return {
        f"{line[21]}/{int(line[22:26])}/{line[12:16].strip()}": (
            float(line[30:38]),
            float(line[38:46]),
            float(line[46:54]),
        )
        for line in path.read_text().splitlines()
        if line.startswith(("ATOM  ", "HETATM"))
    }


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.mark.parametrize("example_id", [item["id"] for item in example_catalog()])
def test_practice_answers_finish_all_stages_and_archive_export(tmp_path, example_id):
    app = Application(workspace=tmp_path / "workspace")
    app.example({"id": example_id})
    state = app.state()
    example = state["semantic"]["extensions"]["gui_example"]
    assert example["notice"] == "Synthetic practice data"
    assert state["semantic"]["claims"] == []
    assert state["semantic"]["evidence"] == []
    assert state["semantic"]["uncertainty"] == []
    assert all(scene["camera"] for scene in state["semantic"]["scenes"])
    source_ids = set(example["evidence"]["source_artifact_ids"])
    assert {
        Path(item["path"]).name
        for item in state["semantic"]["artifacts"]
        if item["id"] in source_ids
    } == set(example["evidence"]["source_filenames"])

    app.save_claim(
        {
            **example["claim"],
            "scene_ids": [item["id"] for item in state["semantic"]["scenes"]],
        }
    )
    claim_id = app.state()["semantic"]["claims"][0]["id"]
    app.save_evidence({**example["evidence"], "claim_id": claim_id})
    app.save_uncertainty({**example["uncertainty"], "claim_id": claim_id})
    app.save_context({
        "reuse": {"license": "Synthetic teaching example", "citation": "ClaimTrace practice case"},
        "software": {"name": "PyMOL", "version": "3.1"},
    })
    app.set_lifecycle({"mode": "archive"})
    completed = app.state()
    assert completed["report"]["overall_status"] == "pass", completed["report"]["findings"]
    audit_claim = completed["audit"]["claims"][0]
    assert audit_claim["status"] == "recorded"
    assert [item["status"] for item in audit_claim["stages"]] == ["recorded"] * 5
    assert audit_claim["issues"] == []
    assert "Scene replay: pending verification in the original viewer" in audit_claim["stages"][-1]["summary"]
    markdown = export_markdown(completed["audit"])
    assert example["claim"]["claim_text"] in markdown
    assert example["evidence"]["method_name"] in markdown
    assert example["uncertainty"]["statement"] in markdown
    assert json.loads(json.dumps(completed["audit"]))["claims"][0]["id"] == claim_id
    package = app.require_package()
    output = package.export(tmp_path / f"{example_id}-export", mode="archive")
    assert load_package(output).validate(mode="archive").overall_status == "pass"
    reopened = Application(package=output)
    assert reopened.state()["audit"]["claims"][0]["status"] == "recorded"


def test_highlight_membership_matches_coordinate_file_and_native_selector(tmp_path):
    package = create_example("highlight-residues", tmp_path)
    pdb = coordinates(artifact_path(package, "synthetic.pdb"))
    rows = read_rows(artifact_path(package, "selection.csv"))
    assert set(pdb) == {f"{row['chain']}/{row['residue']}/{row['atom']}" for row in rows}
    assert {row["residue"] for row in rows if row["highlighted"] == "true"} == {"42", "85"}
    selector = package.semantic_layer.selections[0].native_selector.value
    assert selector == "chain A and resi 42+85"
    assert all(selection.entity_ids for selection in package.semantic_layer.selections)


def test_contact_distances_and_cutoff_match_pdb_coordinates(tmp_path):
    package = create_example("ligand-contacts", tmp_path)
    pdb = coordinates(artifact_path(package, "synthetic.pdb"))
    rows = read_rows(artifact_path(package, "contacts.csv"))
    cutoff = package.semantic_layer.extensions["gui_example"]["evidence"]["thresholds"]["distance"]
    assert len(rows) == 3
    for row in rows:
        distance = math.sqrt(
            sum((a - b) ** 2 for a, b in zip(pdb[row["site_atom"]], pdb[row["ligand_atom"]]))
        )
        assert float(row["distance_angstrom"]) == pytest.approx(distance, abs=0.0005)
        assert (row["within_4_angstrom"] == "true") == (distance <= cutoff)
    assert [row["site_atom"] for row in rows if row["within_4_angstrom"] == "true"] == [
        "A/42/CA",
        "A/85/CA",
    ]


def test_model_comparison_matches_both_coordinate_sources(tmp_path):
    package = create_example("compare-models", tmp_path)
    first = coordinates(artifact_path(package, "model-a.pdb"))
    second = coordinates(artifact_path(package, "model-b.pdb"))
    rows = read_rows(artifact_path(package, "comparison.csv"))
    assert set(first) == set(second) == {row["atom"] for row in rows}
    squares = []
    for row in rows:
        squared = sum((a - b) ** 2 for a, b in zip(first[row["atom"]], second[row["atom"]]))
        squares.append(squared)
        assert float(row["displacement_angstrom"]) == math.sqrt(squared)
    rmsd = math.sqrt(sum(squares) / len(squares))
    example = package.semantic_layer.extensions["gui_example"]
    assert f"{rmsd:.3f} angstrom" in example["claim"]["claim_text"]
    assert f"{rmsd:.3f} angstrom" in example["evidence"]["result_summary"]


def test_evidence_target_links_are_checked_and_retained_when_editing(tmp_path):
    app = Application(workspace=tmp_path)
    app.example({"id": "ligand-contacts"})
    state = app.state()
    example = state["semantic"]["extensions"]["gui_example"]
    app.save_claim({**example["claim"], "scene_ids": [state["semantic"]["scenes"][0]["id"]]})
    claim_id = app.state()["semantic"]["claims"][0]["id"]
    payload = {**example["evidence"], "claim_id": claim_id}
    for field in ["target_selection_ids", "target_entity_ids"]:
        with pytest.raises(RequestError, match="saved in this package"):
            app.save_evidence({**payload, field: ["missing-target"]})
        assert app.state()["semantic"]["evidence"] == []
    app.save_evidence(payload)
    evidence = app.state()["semantic"]["evidence"][0]
    app.save_evidence(
        {
            **{
                key: value
                for key, value in payload.items()
                if key not in {"target_selection_ids", "target_entity_ids"}
            },
            "id": evidence["id"],
        }
    )
    saved = app.state()["semantic"]["evidence"][0]
    assert saved["target_selection_ids"] == payload["target_selection_ids"]
    assert saved["target_entity_ids"] == payload["target_entity_ids"]


def test_example_catalog_http_creation_and_fresh_copies(tmp_path):
    server = create_server(port=0, workspace=tmp_path)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    def request(method, path, data=None):
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        connection.request(
            method,
            path,
            body=json.dumps(data) if data is not None else None,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        body = json.loads(response.read())
        status = response.status
        connection.close()
        return status, body

    try:
        status, response = request("GET", "/api/examples")
        assert status == 200
        assert len(response["examples"]) == 3
        assert all(item["synthetic"] for item in response["examples"])
        roots = []
        for _ in range(2):
            status, state = request("POST", "/api/example", {"id": "ligand-contacts"})
            assert status == 200
            roots.append(state["root"])
            assert state["semantic"]["claims"] == []
        assert roots[0] != roots[1]
        assert all((Path(root) / "semantic_layer.json").is_file() for root in roots)
        status, error = request("POST", "/api/example", {"id": "missing"})
        assert status == 400
        assert error["error"] == "Choose a practice example from the list."
        assert request("GET", "/api/state")[1]["root"] == roots[-1]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def raw_contact_app(tmp_path):
    """Use only exported source files, without the example's prepared identities."""
    source = create_example("ligand-contacts", tmp_path / "source")
    example = source.semantic_layer.extensions["gui_example"]
    files = [
        {
            "name": Path(item.path).name,
            "content": base64.b64encode((source.root / item.path).read_bytes()).decode(),
        }
        for item in source.semantic_layer.artifacts
    ]
    files.append(
        {
            "name": "other.pml",
            "content": base64.b64encode(
                b"select elsewhere, chain Z and resi 9\ncolor blue, elsewhere\n"
            ).decode(),
        }
    )
    app = Application(workspace=tmp_path / "imported")
    app.import_files({"title": "Raw contact review", "files": files})
    state = app.state()
    scene = state["semantic"]["scenes"][0]
    app.save_claim({**example["claim"], "scene_ids": [scene["id"]]})
    claim_id = app.state()["semantic"]["claims"][0]["id"]
    artifact_ids = {Path(item["path"]).name: item["id"] for item in state["semantic"]["artifacts"]}
    app.save_evidence(
        {
            **example["evidence"],
            "claim_id": claim_id,
            "source_artifact_ids": [
                artifact_ids[name] for name in example["evidence"]["source_filenames"]
            ],
            "target_selection_ids": scene["selection_ids"],
            "target_entity_ids": [],
        }
    )
    app.save_uncertainty({**example["uncertainty"], "claim_id": claim_id})
    state = app.state()
    selections = {item["name"]: item for item in state["semantic"]["selections"]}
    operation = next(
        item
        for item in state["semantic"]["observed_scene_operations"]
        if item["operation"] == "colored" and item["target"] == "ligand"
    )
    payload = {
        "claim_id": claim_id,
        "identities": [
            {
                "selection_id": selections["ligand"]["id"],
                "entity_type": "ligand",
                "label": "Synthetic ligand LIG, chain B residue 1",
                "source_artifact_ids": [artifact_ids["synthetic.pdb"]],
            },
            {
                "selection_id": selections["site"]["id"],
                "entity_type": "residue",
                "label": "Synthetic chain A residues ASP 42 and SER 85",
                "source_artifact_ids": [artifact_ids["synthetic.pdb"]],
            },
        ],
        "visual_meanings": [
            {
                "operation_id": operation["operation_id"],
                "meaning": "Orange identifies the synthetic ligand LIG in chain B residue 1.",
                "presentation_only": False,
            }
        ],
    }
    return app, payload


def test_raw_import_scene_labels_complete_identity_and_color_records(tmp_path):
    app, payload = raw_contact_app(tmp_path)
    draft = app.state()
    assert draft["workflow"]["lifecycle"]["ready"] is True
    assert {task["action"] for task in draft["workflow"]["tasks"]} >= {
        "identify-regions", "explain-colors",
    }
    app.set_lifecycle({"mode": "archive"})
    before = app.state()
    rules = {item["rule_id"] for item in before["audit"]["claims"][0]["issues"] if item["blocking"]}
    assert rules == {"CLAIM.LIGAND.IDENTITY_CONTEXT", "SCENE.VISUAL_ENCODING.MEANING_MISSING"}
    assert before["semantic"]["entities"] == []
    assert (
        next(item for item in before["audit"]["claims"][0]["stages"] if item["key"] == "visual")[
            "status"
        ]
        == "review"
    )
    app.save_identities({"claim_id": payload["claim_id"], "identities": payload["identities"]})
    remaining = app.state()["audit"]["claims"][0]["issues"]
    assert {item["rule_id"] for item in remaining if item["blocking"]} == {
        "SCENE.VISUAL_ENCODING.MEANING_MISSING"
    }
    app.save_identities(
        {"claim_id": payload["claim_id"], "visual_meanings": payload["visual_meanings"]}
    )
    state = app.state()
    assert state["audit"]["claims"][0]["status"] == "recorded"
    assert state["audit"]["claims"][0]["validation_blockers"] == 0
    assert state["report"]["overall_status"] == "pass"
    assert len(state["semantic"]["entities"]) == 2
    evidence = state["semantic"]["evidence"][0]
    assert set(evidence["target_entity_ids"]) == {
        item["id"] for item in state["semantic"]["entities"]
    }
    for item in state["semantic"]["entities"]:
        assert item["extensions"]["source_type"] == "user_asserted"
        assert item["extensions"]["reviewer"] == "gui"
        assert item["review_status"] == "confirmed"
        assert item["label"] in item["stable_identity"]
        assert len(item["source_artifact_ids"]) == 2  # Explicit structure plus native selection.
    original_ids = [item["id"] for item in state["semantic"]["entities"]]
    payload["identities"][0]["label"] = "Synthetic ligand LIG B/1/C1"
    payload["visual_meanings"][0].update(
        meaning="Orange separates the ligand from the residue markers.", presentation_only=True
    )
    app.save_identities(payload)
    state = app.state()
    assert [item["id"] for item in state["semantic"]["entities"]] == original_ids
    assert len(state["semantic"]["visual_encoding_semantics"]) == 1
    meaning = state["semantic"]["visual_encoding_semantics"][0]
    assert meaning["meaning_status"] == "user_declared_no_scientific_meaning"
    assert meaning["no_scientific_meaning_reason"] == payload["visual_meanings"][0]["meaning"]
    output = app.require_package().export(tmp_path / "raw-export", mode="archive")
    assert load_package(output).validate(mode="archive").overall_status == "pass"


@pytest.mark.parametrize("invalid", ["selection", "operation", "source", "placeholder"])
def test_scene_label_validation_is_scoped_and_preserves_saved_records(tmp_path, invalid):
    app, payload = raw_contact_app(tmp_path)
    state = app.state()
    manifest = Path(state["root"]) / "semantic_layer.json"
    saved = manifest.read_bytes()
    if invalid == "selection":
        payload["identities"][1]["selection_id"] = next(
            item["id"] for item in state["semantic"]["selections"] if item["name"] == "elsewhere"
        )
    elif invalid == "operation":
        payload["visual_meanings"][0]["operation_id"] = next(
            item["operation_id"]
            for item in state["semantic"]["observed_scene_operations"]
            if item["target"] == "elsewhere"
        )
    elif invalid == "source":
        payload["identities"][1]["source_artifact_ids"] = [
            next(
                item["id"]
                for item in state["semantic"]["artifacts"]
                if item["role"] == "render_image"
            )
        ]
    else:
        payload["identities"][1]["label"] = "TODO molecule name"
    with pytest.raises(RequestError):
        app.save_identities(payload)
    assert manifest.read_bytes() == saved
    assert app.state()["semantic"]["entities"] == []


def test_scene_labels_preserve_existing_entities_and_unrelated_evidence(tmp_path):
    app = Application(workspace=tmp_path)
    app.example({"id": "ligand-contacts"})
    state = app.state()
    example = state["semantic"]["extensions"]["gui_example"]
    scene_id = state["semantic"]["scenes"][0]["id"]
    original_entities = state["semantic"]["entities"]
    app.save_claim({**example["claim"], "scene_ids": [scene_id]})
    first_claim_id = app.state()["semantic"]["claims"][0]["id"]
    app.save_evidence({**example["evidence"], "claim_id": first_claim_id})
    unrelated_evidence = app.state()["semantic"]["evidence"][0]
    app.save_claim({**example["claim"], "scene_ids": [scene_id]})
    current_claim_id = app.state()["semantic"]["claims"][1]["id"]
    app.save_evidence({**example["evidence"], "claim_id": current_claim_id})
    state = app.state()
    selection = next(item for item in state["semantic"]["selections"] if item["name"] == "ligand")
    structure = next(item for item in state["semantic"]["artifacts"] if item["role"] == "structure")
    app.save_identities(
        {
            "claim_id": current_claim_id,
            "identities": [
                {
                    "selection_id": selection["id"],
                    "entity_type": "ligand",
                    "label": "Synthetic LIG B/1/C1",
                    "source_artifact_ids": [structure["id"]],
                }
            ],
        }
    )
    state = app.state()
    assert state["semantic"]["entities"][:2] == original_entities
    assert state["semantic"]["evidence"][0] == unrelated_evidence
    new_id = state["semantic"]["entities"][-1]["id"]
    assert new_id in state["semantic"]["evidence"][1]["target_entity_ids"]
    assert new_id not in state["semantic"]["evidence"][0]["target_entity_ids"]


def test_visual_meaning_edit_updates_one_operation_and_preserves_group_members(tmp_path):
    app = Application(workspace=tmp_path)
    app.example({"id": "highlight-residues"})
    package = app.require_package()
    semantic = package.semantic_layer
    colors = [item for item in semantic.observed_scene_operations if item.operation == "colored"]
    assert len(colors) == 2
    original_commands = [item.native_command for item in colors]
    global_meaning = VisualEncodingSemantics(
        encoding_type="color",
        meaning="Scene-wide palette note.",
        meaning_status=MeaningStatus.user_confirmed_meaning,
        reviewer="practice fixture author",
        reviewed_at=utc_now(),
    )
    semantic.visual_encoding_semantics = [
        VisualEncodingSemantics(
            operation_ids=[item.operation_id for item in colors],
            encoding_type="color",
            meaning_status=MeaningStatus.user_confirmed_meaning,
            meaning="The palette identifies the selected residue set and background residues.",
            reviewer="practice fixture author",
            reviewed_at=utc_now(),
        ),
        global_meaning,
    ]
    package.save()
    example = semantic.extensions["gui_example"]
    app.save_claim({**example["claim"], "scene_ids": [semantic.scenes[0].id]})
    claim_id = app.state()["semantic"]["claims"][0]["id"]
    app.save_identities(
        {
            "claim_id": claim_id,
            "visual_meanings": [
                {
                    "operation_id": colors[0].operation_id,
                    "meaning": "Gray identifies the background residue set.",
                    "presentation_only": False,
                }
            ],
        }
    )
    state = app.state()
    meanings = state["semantic"]["visual_encoding_semantics"]
    assert len(meanings) == 3
    assert meanings[0]["operation_ids"] == [colors[1].operation_id]
    assert (
        meanings[0]["meaning"]
        == "The palette identifies the selected residue set and background residues."
    )
    assert meanings[0]["reviewer"] == "practice fixture author"
    assert meanings[1] == global_meaning.model_dump(mode="json")
    assert meanings[2]["operation_ids"] == [colors[0].operation_id]
    assert meanings[2]["meaning"] == "Gray identifies the background residue set."
    assert meanings[2]["reviewer"] == "gui"
    assert [
        item["native_command"]
        for item in state["semantic"]["observed_scene_operations"]
        if item["operation"] == "colored"
    ] == original_commands
