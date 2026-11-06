"""The agent proposal path retains human control and existing scientific records."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from claimtrace.api import load_package
from claimtrace.gui.examples import create_example
from claimtrace.proposals import (
    ProposalError,
    check_proposal,
    create_proposal,
    proposal_schema,
    review_proposal,
    stored_proposals,
)


@pytest.fixture
def sample(tmp_path):
    pkg = create_example("highlight-residues", tmp_path)
    source = next(a.id for a in pkg.semantic_layer.artifacts if a.role.value == "structure")
    scene = pkg.semantic_layer.scenes[0].id
    data = {
        "id": "proposal:highlight",
        "actor": {"id": "agent:test", "name": "Test assistant", "model": "test-model"},
        "title": "Describe the highlighted residues",
        "rationale": "The source selection identifies residues 42 and 85.",
        "source_artifact_ids": [source],
        "claim_id": "claim:highlight",
        "changes": [
            {
                "record_type": "claim",
                "record_id": "claim:highlight",
                "fields": {
                    "claim_text": "The highlighted region contains residues 42 and 85.",
                    "claim_type": "selection_highlight",
                    "figure_ref": "Figure 1",
                    "scene_ids": [scene],
                },
            },
            {
                "record_type": "evidence",
                "record_id": "evidence:selection",
                "claim_id": "claim:highlight",
                "fields": {
                    "method_name": "Compare the scene selection with supplied coordinates.",
                    "result_summary": "The scene selects chain A residues 42 and 85.",
                    "source_artifact_ids": [source],
                },
            },
            {
                "record_type": "uncertainty",
                "record_id": "uncertainty:static",
                "claim_id": "claim:highlight",
                "fields": {
                    "statement": "The selected coordinates represent a single conformation."
                },
            },
        ],
    }
    return pkg, data


def test_check_is_read_only_and_propose_keeps_scientific_records_unchanged(sample):
    pkg, data = sample
    before = (pkg.root / "semantic_layer.json").read_bytes()
    preview = check_proposal(pkg, data)
    assert preview["status"] == "pending"
    assert preview["diff"][0]["before"] is None
    assert (pkg.root / "semantic_layer.json").read_bytes() == before
    assert not pkg.semantic_layer.claims
    result = create_proposal(pkg, data)
    saved = load_package(pkg.root).semantic_layer
    assert not saved.claims
    assert not any(e.id == "evidence:selection" for e in saved.evidence)
    assert result["actor"]["model"] == "test-model"
    assert saved.provenance.activities[-1].agent_id == "agent:test"
    assert stored_proposals(saved)[0]["status"] == "pending"
    original = (pkg.root / "semantic_layer.json").read_bytes()
    create_proposal(pkg, data)
    assert (pkg.root / "semantic_layer.json").read_bytes() == original


def test_accept_links_records_separates_actor_reviewer_and_reverts(sample):
    pkg, data = sample
    before = pkg.semantic_layer.model_dump(mode="json")
    create_proposal(pkg, data)
    result = review_proposal(pkg, data["id"], decision="accept", reviewer="Dr Example")
    assert result["status"] == "accepted"
    saved = load_package(pkg.root).semantic_layer
    claim = saved.claims[0]
    assert claim.review_status.value == "human_accepted"
    assert claim.claim_text.source_type.value == "tool_generated"
    assert claim.claim_text.reviewer == "Dr Example"
    assert claim.evidence_ids == ["evidence:selection"]
    assert claim.uncertainty_ids == ["uncertainty:static"]
    evidence = next(e for e in saved.evidence if e.id == "evidence:selection")
    assert evidence.generated_by == "Test assistant"
    assert evidence.reviewer == "Dr Example"
    assert saved.provenance.activities[-1].agent_id == "person:Dr Example"
    review_proposal(
        pkg, data["id"], decision="revert", reviewer="Dr Example", note="Use the original wording."
    )
    after = load_package(pkg.root).semantic_layer.model_dump(mode="json")
    for section in ("claims", "evidence", "uncertainty", "scenes", "selections", "entities"):
        assert after[section] == before[section]
    assert stored_proposals(pkg.semantic_layer)[0]["status"] == "reverted"
    assert len(stored_proposals(pkg.semantic_layer)[0]["review_history"]) == 2


def test_rejection_and_edited_acceptance_keep_original_proposal(sample):
    pkg, data = sample
    create_proposal(pkg, data)
    reviewed = review_proposal(
        pkg, data["id"], decision="reject", reviewer="Researcher", note="Check residue numbering."
    )
    assert reviewed["review"]["note"] == "Check residue numbering."
    assert pkg.semantic_layer.claims == []
    data["id"] = "proposal:revision"
    create_proposal(pkg, data)
    edited = deepcopy(data["changes"])
    edited[0]["fields"]["claim_text"] = "Chain A residues 42 and 85 form the highlighted selection."
    result = review_proposal(
        pkg, data["id"], decision="accept", reviewer="Researcher", changes=edited
    )
    assert (
        result["changes"][0]["fields"]["claim_text"] == data["changes"][0]["fields"]["claim_text"]
    )
    assert pkg.semantic_layer.claims[0].claim_text.value == edited[0]["fields"]["claim_text"]
    assert result["accepted_diff"][0]["after"] == edited[0]["fields"]["claim_text"]


def test_human_edits_after_proposal_and_after_acceptance_are_protected(sample):
    pkg, data = sample
    create_proposal(pkg, data)
    review_proposal(pkg, data["id"], decision="accept", reviewer="Researcher")
    proposal = deepcopy(data)
    proposal["id"] = "proposal:edited-claim"
    proposal["changes"] = [
        {
            "record_type": "claim",
            "record_id": "claim:highlight",
            "fields": {"claim_text": "New suggestion."},
        }
    ]
    create_proposal(pkg, proposal)
    pkg.semantic_layer.claims[0].figure_ref = "Figure 2"
    pkg.save()
    before = (pkg.root / "semantic_layer.json").read_bytes()
    for proposal_id, decision in [(proposal["id"], "accept"), (data["id"], "revert")]:
        with pytest.raises(ProposalError, match="has changed"):
            review_proposal(pkg, proposal_id, decision=decision, reviewer="Researcher")
        assert (pkg.root / "semantic_layer.json").read_bytes() == before


def test_partial_patch_preserves_evidence_metadata_and_merges_settings(sample):
    pkg, data = sample
    create_proposal(pkg, data)
    review_proposal(pkg, data["id"], decision="accept", reviewer="Researcher")
    evidence = next(e for e in pkg.semantic_layer.evidence if e.id == "evidence:selection")
    evidence.extensions["lab_context"] = {"replicate": "A"}
    evidence.parameters = {"frame": 10, "selection": "chain A"}
    evidence.provenance_id = "activity:init"
    pkg.save()
    data["id"] = "proposal:settings"
    data["changes"] = [
        {
            "record_type": "evidence",
            "record_id": evidence.id,
            "fields": {"parameters": {"frame": 20}},
        }
    ]
    create_proposal(pkg, data)
    review_proposal(pkg, data["id"], decision="accept", reviewer="Researcher")
    saved = next(e for e in pkg.semantic_layer.evidence if e.id == evidence.id)
    assert saved.parameters == {"frame": 20, "selection": "chain A"}
    assert saved.provenance_id == "activity:init"
    assert saved.extensions["lab_context"] == {"replicate": "A"}


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d["changes"][0]["fields"].update(claim_type="invalid-type"),
        lambda d: d["changes"][0]["fields"].update(review_status="human_accepted"),
        lambda d: d["changes"][0]["fields"].update(scene_ids=["missing-scene"]),
        lambda d: d["changes"][1]["fields"].update(source_artifact_ids=["missing-source"]),
        lambda d: d["changes"][1]["fields"].update(parameters={"value": float("nan")}),
    ],
)
def test_invalid_proposal_leaves_package_and_files_unchanged(sample, edit):
    pkg, data = sample
    edit(data)
    before = {
        str(p.relative_to(pkg.root)): p.read_bytes() for p in pkg.root.rglob("*") if p.is_file()
    }
    with pytest.raises((ValueError, ValidationError)):
        create_proposal(pkg, data)
    assert {
        str(p.relative_to(pkg.root)): p.read_bytes() for p in pkg.root.rglob("*") if p.is_file()
    } == before
    assert not pkg.semantic_layer.claims


def test_measurement_without_contact_cutoff_is_valid(sample):
    pkg, data = sample
    data["changes"][1]["fields"].update(
        evidence_kind="measurement",
        parameters={"measured_distance": 2.0},
        units={"distance": "angstrom"},
    )
    create_proposal(pkg, data)
    review_proposal(pkg, data["id"], decision="accept", reviewer="Researcher")
    evidence = next(e for e in pkg.semantic_layer.evidence if e.id == "evidence:selection")
    assert evidence.thresholds == {}
    assert evidence.parameters["measured_distance"] == 2.0


def test_discovery_schema_validates_types_and_check_locates_missing_measurement(sample):
    from jsonschema import Draft202012Validator

    pkg, data = sample
    schema = proposal_schema()
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(data)
    invalid = deepcopy(data)
    invalid["changes"][0]["fields"]["claim_type"] = "unrecognized-type"
    assert list(validator.iter_errors(invalid))
    invalid = deepcopy(data)
    invalid["changes"][1]["fields"]["units"] = {"distance": 2.8}
    assert list(validator.iter_errors(invalid))
    data["changes"][1]["fields"].update(evidence_kind="measurement", units={"distance": "angstrom"})
    with pytest.raises(ProposalError) as failure:
        check_proposal(pkg, data)
    assert failure.value.pointer == "/changes/1/fields/parameters/measured_distance"
    assert "parameters.measured_distance" in str(failure.value)


def test_pending_accepted_and_reverted_proposals_remain_exportable(sample, tmp_path):
    pkg, data = sample
    create_proposal(pkg, data)
    for status in ("pending", "accepted", "reverted"):
        if status != "pending":
            review_proposal(
                pkg,
                data["id"],
                decision="accept" if status == "accepted" else "revert",
                reviewer="Researcher",
            )
        result = pkg.export(tmp_path / f"{status}.zip", mode="draft", zip_output=True)
        assert result.is_file()
        report = pkg.validate(mode="draft")
        assert report.overall_status != "fail", [f.message for f in report.findings]


def test_revert_preserves_newer_records_that_depend_on_created_entity(sample):
    pkg, data = sample
    data.pop("claim_id")
    data["changes"] = [
        {"record_type": "entity", "record_id": "entity:new", "fields": {"label": "Site"}}
    ]
    create_proposal(pkg, data)
    review_proposal(pkg, data["id"], decision="accept", reviewer="Researcher")
    next_proposal = deepcopy(data)
    next_proposal["id"] = "proposal:dependent-selection"
    next_proposal["changes"] = [
        {
            "record_type": "selection",
            "record_id": "selection:dependent",
            "fields": {"name": "Site", "native_selector": "chain A", "entity_ids": ["entity:new"]},
        }
    ]
    create_proposal(pkg, next_proposal)
    review_proposal(pkg, next_proposal["id"], decision="accept", reviewer="Researcher")
    before = (pkg.root / "semantic_layer.json").read_bytes()
    with pytest.raises(ProposalError, match="dependent records") as error:
        review_proposal(pkg, data["id"], decision="revert", reviewer="Researcher")
    assert error.value.code == "reference_conflict"
    assert (pkg.root / "semantic_layer.json").read_bytes() == before
    review_proposal(pkg, next_proposal["id"], decision="revert", reviewer="Researcher")
    review_proposal(pkg, data["id"], decision="revert", reviewer="Researcher")


def test_visibility_references_and_actor_identity_are_checked(sample):
    pkg, data = sample
    create_proposal(pkg, data)
    changed_actor = deepcopy(data)
    changed_actor["id"] = "proposal:new-model"
    changed_actor["actor"]["model"] = "different-model"
    with pytest.raises(ProposalError, match="distinct agent ID"):
        check_proposal(pkg, changed_actor)
    data.pop("claim_id")
    data["id"] = "proposal:visibility"
    data["changes"] = [
        {
            "record_type": "scene",
            "record_id": pkg.semantic_layer.scenes[0].id,
            "fields": {"visibility": [{"entity_id": "missing:entity", "state": "visible"}]},
        }
    ]
    before = (pkg.root / "semantic_layer.json").read_bytes()
    with pytest.raises(ProposalError, match="missing entity"):
        check_proposal(pkg, data)
    assert (pkg.root / "semantic_layer.json").read_bytes() == before


def test_existing_evidence_keeps_claim_scope_in_partial_proposals(sample):
    from claimtrace.models.semantic_layer import Claim, ProvenancedString

    pkg, data = sample
    create_proposal(pkg, data)
    review_proposal(pkg, data["id"], decision="accept", reviewer="Researcher")
    pkg.semantic_layer.claims.append(
        Claim(
            id="claim:other",
            claim_text=ProvenancedString(value="Another statement"),
            figure_ref="B",
            scene_ids=[pkg.semantic_layer.scenes[0].id],
        )
    )
    pkg.save()
    data["id"] = "proposal:scope"
    data["claim_id"] = "claim:other"
    data["changes"] = [
        {
            "record_type": "evidence",
            "record_id": "evidence:selection",
            "fields": {"result_summary": "Reworded selection observation."},
        }
    ]
    before = (pkg.root / "semantic_layer.json").read_bytes()
    with pytest.raises(ProposalError) as error:
        create_proposal(pkg, data)
    assert error.value.code == "claim_scope_conflict"
    assert (pkg.root / "semantic_layer.json").read_bytes() == before
    data["claim_id"] = "claim:highlight"
    create_proposal(pkg, data)
    review_proposal(pkg, data["id"], decision="accept", reviewer="Researcher")
    evidence = next(e for e in pkg.semantic_layer.evidence if e.id == "evidence:selection")
    assert evidence.claim_ids == ["claim:highlight"]


def test_changed_visibility_has_agent_source_and_original_rows_keep_their_source(sample):
    from claimtrace.models.semantic_layer import VisibilityRecord

    pkg, data = sample
    scene = pkg.semantic_layer.scenes[0]
    original = VisibilityRecord(
        native_target="site", state="visible", review_status="auto_extracted"
    )
    scene.visibility = [original]
    pkg.save()
    data.pop("claim_id")
    data["changes"] = [
        {
            "record_type": "scene",
            "record_id": scene.id,
            "fields": {
                "visibility": [
                    {"native_target": "site", "state": "visible"},
                    {"native_target": "ligand", "state": "hidden"},
                ],
            },
        }
    ]
    checked = check_proposal(pkg, data)
    proposed = checked["diff"][0]["after"]
    assert proposed[0] == original.model_dump(mode="json")
    assert proposed[1]["source_type"] == "tool_generated"
    assert proposed[1]["review_status"] == "needs_review"
    create_proposal(pkg, data)
    review_proposal(pkg, data["id"], decision="accept", reviewer="Researcher")
    accepted = pkg.semantic_layer.scenes[0].visibility
    assert accepted[0] == original
    assert accepted[1].source_type.value == "tool_generated"
    assert accepted[1].review_status.value == "human_accepted"


def test_stale_python_instances_preserve_later_saves_on_propose_and_review(sample):
    pkg, data = sample
    stale = load_package(pkg.root)
    pkg.semantic_layer.scenes[0].description = "Author's updated view description"
    pkg.save()
    before = (pkg.root / "semantic_layer.json").read_bytes()
    with pytest.raises(ProposalError) as error:
        create_proposal(stale, data)
    assert error.value.code == "stale_package"
    assert (pkg.root / "semantic_layer.json").read_bytes() == before
    create_proposal(pkg, data)
    stale = load_package(pkg.root)
    pkg.semantic_layer.scenes[0].description = "Another author update"
    pkg.save()
    before = (pkg.root / "semantic_layer.json").read_bytes()
    with pytest.raises(ProposalError) as error:
        review_proposal(stale, data["id"], decision="accept", reviewer="Researcher")
    assert error.value.code == "stale_package"
    assert (pkg.root / "semantic_layer.json").read_bytes() == before


def test_selection_proposal_requires_replay_of_changed_expression_and_revert_restores_it(sample):
    pkg, data = sample
    selection = pkg.semantic_layer.selections[0]
    selection.extensions["runtime_verification"] = "verified"
    original = selection.model_dump(mode="json")
    pkg.save()
    data["claim_id"] = None
    data["changes"] = [{
        "record_type": "selection", "record_id": selection.id,
        "fields": {"native_selector": "chain B and resi 42+85"},
    }]
    create_proposal(pkg, data)
    assert pkg.semantic_layer.selections[0].extensions["runtime_verification"] == "verified"
    review_proposal(pkg, data["id"], decision="accept", reviewer="Researcher")
    assert pkg.semantic_layer.selections[0].extensions["runtime_verification"] == "unverified"
    assert pkg.semantic_layer.selections[0].native_selector.review_status.value == "human_accepted"
    review_proposal(pkg, data["id"], decision="revert", reviewer="Researcher")
    assert pkg.semantic_layer.selections[0].model_dump(mode="json") == original
