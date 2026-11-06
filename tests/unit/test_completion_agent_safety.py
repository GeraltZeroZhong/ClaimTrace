from copy import deepcopy

import pytest
from PIL import Image

from claimtrace.api import init_package, load_package
from claimtrace.completion import apply_answers, check_answers, package_answer_template
from claimtrace.models import Artifact, Claim, Entity, Evidence, ProvenancedString, Scene, Uncertainty
from claimtrace.errors import PackageError
from claimtrace.models.semantic_layer import SemanticLayer
from claimtrace.package.checksums import sha256_file
from claimtrace.package.registry import register_local_artifact


def answers():
    return {
        "claim": {
            "id": "claim:a", "claim_text": "The panel shows the measured separation.",
            "claim_type": "simple_structure_view", "figure_ref": "Figure A",
        },
        "evidence": [],
        "reuse": {"license": "unknown"},
    }


@pytest.mark.parametrize("section,values", [
    ("claim", {"claim_type": "invented"}),
    ("claim", {"review_status": "approved-by-agent"}),
    ("claim", {"source_type": "invented"}),
    ("claim", {"confidence": "certain"}),
    ("evidence", {"evidence_kind": "invented"}),
    ("evidence", {"review_status": "approved-by-agent"}),
    ("evidence", {"parameters": "use a mapping"}),
    ("uncertainty", {"review_status": "approved-by-agent"}),
])
def test_invalid_model_values_fail_before_any_write_or_semantic_mutation(tmp_path, section, values):
    root = tmp_path / "package"
    source = tmp_path / "observations.txt"
    source.write_text("Measured separation: 3.223 angstrom.\n")
    semantic = SemanticLayer.new("preflight")
    before = semantic.model_dump()
    data = answers()
    data["artifacts"] = [{"path": str(source), "role": "evidence_document"}]
    if section == "claim":
        data[section].update(values)
    elif section == "evidence":
        data[section] = [{
            "method_name": "Read supplied measurements", "result_summary": "Distance recorded.",
            "source_artifact_roles": ["evidence_document"], **values,
        }]
    else:
        data[section] = [{"statement": "The measurement describes this structure.", **values}]
    untouched_answers = deepcopy(data)

    problems = check_answers(data, semantic, root=root, answer_base=tmp_path)

    assert any("Invalid answer value" in problem for problem in problems)
    assert semantic.model_dump() == before
    assert data == untouched_answers
    assert not root.exists()
    with pytest.raises(ValueError):
        apply_answers(root, semantic, data, answer_base=tmp_path)
    assert semantic.model_dump() == before
    assert not root.exists()


def test_no_package_check_also_validates_models():
    data = answers()
    data["claim"]["claim_type"] = "invented"
    assert any("claim_type" in problem for problem in check_answers(data))


def test_native_schema_models_are_preflighted(tmp_path):
    semantic = SemanticLayer.new("native-preflight")
    data = answers()
    data.update(
        answer_schema="claimtrace.native_scene_answers.v1",
        waivers=[{"anchor_id": "claim:a", "max_export_mode": "published"}],
    )
    before = semantic.model_dump()
    assert any("max_export_mode" in problem for problem in check_answers(data, semantic))
    with pytest.raises(ValueError, match="max_export_mode"):
        apply_answers(tmp_path, semantic, data)
    assert semantic.model_dump() == before


@pytest.mark.parametrize("distance", [3.223, "3.223"])
def test_measurement_accepts_distance_and_unit_without_contact_cutoff(tmp_path, distance):
    semantic = SemanticLayer.new("measurement")
    source = tmp_path / "measurement.csv"
    source.write_text("distance_angstrom\n3.223\n")
    data = answers()
    data["evidence"] = [{
        "id": "evidence:distance", "evidence_kind": "measurement",
        "method_name": "Atom-pair measurement", "result_summary": "The separation is 3.223 angstrom.",
        "parameters": {"measured_distance": distance}, "units": {"distance": "angstrom"},
        "source_artifact_paths": [str(source)],
    }]
    root = tmp_path / "package"
    assert check_answers(data, semantic, root=root) == []
    assert not root.exists()
    apply_answers(root, semantic, data)
    assert semantic.evidence[0].parameters["measured_distance"] == distance
    assert semantic.evidence[0].thresholds == {}
    assert (root / semantic.artifacts[0].path).read_bytes() == source.read_bytes()


@pytest.mark.parametrize("distance", [True, 0, -2, float("inf"), float("nan")])
def test_measurement_requires_finite_positive_distance(distance):
    data = answers()
    data["evidence"] = [{
        "evidence_kind": "measurement", "method_name": "Atom-pair measurement",
        "result_summary": "A distance was recorded.", "source_artifact_ids": ["artifact:distance"],
        "parameters": {"measured_distance": distance}, "units": {"distance": "angstrom"},
    }]
    assert any("parameters.measured_distance" in problem for problem in check_answers(data))


def existing_records():
    semantic = SemanticLayer.new("existing-records")
    semantic.artifacts = [Artifact(id="artifact:source", kind="remote", url="https://example.org/data", included=False)]
    semantic.claims = [Claim(
        id=f"claim:{letter}",
        claim_text=ProvenancedString(
            value=f"Panel {letter} shows a molecular view.", source_type="external_evidence",
            source_location={"artifact_id": "artifact:source", "line": 8}, confidence="high",
            review_status="human_accepted", reviewer="reviewer:alice", reviewed_at="2026-01-02T00:00:00Z",
        ),
        claim_type="simple_structure_view", figure_ref=f"Figure {letter}", scope="panel",
        review_status="human_accepted", claim_status="reviewable", scene_ids=[f"scene:{letter}"],
        evidence_ids=[f"evidence:{letter}"], uncertainty_ids=[f"uncertainty:{letter}"],
        extensions={"gui_identity": {"selection": letter}, "custom": "preserve"},
    ) for letter in ("a", "b")]
    semantic.scenes = [Scene(id=f"scene:{letter}") for letter in ("a", "b")]
    semantic.evidence = [Evidence(
        id=f"evidence:{letter}", claim_ids=[f"claim:{letter}"], source_artifact_ids=["artifact:source"],
        target_entity_ids=[f"entity:{letter}"], target_selection_ids=[f"selection:{letter}"],
        generated_by="tool:distance", method_name="Atom-pair measurement", method_version="2.0",
        parameters={"selection": letter}, thresholds={"distance": 4.0}, units={"distance": "angstrom"},
        result_summary="The measured distance is within the selected cutoff.",
        result_summary_structured={"count": 1}, limitations=["Single structure"],
        alternative_explanations=["Other conformers"], review_status="human_accepted",
        reviewer="reviewer:alice", reviewed_at="2026-01-02T00:00:00Z", provenance_id="activity:measurement",
        fixity_status="available", extensions={"gui_identity": {"region": letter}, "custom": [1, 2]},
    ) for letter in ("a", "b")]
    semantic.uncertainty = [Uncertainty(
        id=f"uncertainty:{letter}", claim_ids=[f"claim:{letter}"], category="scope",
        statement="This view describes the supplied structure.", alternative_explanations=["Other conformers"],
        review_status="human_accepted", reviewer="reviewer:alice", reviewed_at="2026-01-02T00:00:00Z",
        extensions={"custom": "preserve"},
    ) for letter in ("a", "b")]
    return semantic


def test_explicit_id_partial_updates_reset_reviews_and_preserve_unrelated_metadata(tmp_path):
    semantic = existing_records()
    semantic.claims[1].evidence_ids.insert(0, "evidence:historic")
    semantic.evidence[1].fixity_status = "unavailable"
    before = semantic.model_dump()
    data = {
        "claim": {"id": "claim:b", "claim_text": "Panel b highlights the measured separation."},
        "evidence": [{
            "id": "evidence:b", "result_summary": "The separation is 3.223 angstrom.",
            "source_artifact_ids": ["artifact:source"],
        }],
        "uncertainty": [{"id": "uncertainty:b", "statement": "Alternative conformers remain unassessed."}],
        "reuse": {},
    }
    assert check_answers(data, semantic, root=tmp_path) == []
    apply_answers(tmp_path, semantic, data)
    for field in ("claims", "evidence", "uncertainty"):
        assert semantic.model_dump()[field][0] == before[field][0]
    expected = deepcopy(before)
    expected["claims"][1]["claim_text"]["value"] = data["claim"]["claim_text"]
    expected["evidence"][1]["result_summary"] = data["evidence"][0]["result_summary"]
    expected["uncertainty"][1]["statement"] = data["uncertainty"][0]["statement"]
    expected["claims"][1]["review_status"] = "needs_review"
    expected["claims"][1]["claim_text"].update(source_type="user_asserted", source_location=None, confidence="unknown")
    for record in (expected["claims"][1]["claim_text"], expected["evidence"][1], expected["uncertainty"][1]):
        record.update(review_status="needs_review", reviewer=None, reviewed_at=None)
    for field in ("claims", "evidence", "uncertainty"):
        assert semantic.model_dump()[field] == expected[field]


def test_unchanged_content_preserves_prior_reviews(tmp_path):
    semantic = existing_records()
    before = semantic.model_dump()
    data = {
        "claim": {"id": "claim:b", "claim_text": semantic.claims[1].claim_text.value},
        "evidence": [{"id": "evidence:b", "result_summary": semantic.evidence[1].result_summary}],
        "uncertainty": [{"id": "uncertainty:b", "statement": semantic.uncertainty[1].statement}],
        "reuse": {},
    }
    apply_answers(tmp_path, semantic, data)
    for field in ("claims", "evidence", "uncertainty"):
        assert semantic.model_dump()[field] == before[field]


@pytest.mark.parametrize("section,change", [
    ("claim", {"figure_ref": "Figure 2b"}),
    ("claim", {"scene_ids": ["scene:a"]}),
    ("evidence", {"parameters": {"selection": "a"}}),
    ("evidence", {"source_artifact_ids": []}),
    ("uncertainty", {"category": "sampling"}),
])
def test_scientific_context_changes_invalidate_review(tmp_path, section, change):
    semantic = existing_records()
    data = {section: {"id": f"{section}:b", **change}}
    apply_answers(tmp_path, semantic, data)
    record = getattr(semantic, "claims" if section == "claim" else section)[1]
    if section == "claim":
        assert record.review_status.value == "needs_review"
        record = record.claim_text
    assert record.review_status.value == "needs_review"
    assert record.reviewer is None
    assert record.reviewed_at is None


@pytest.mark.parametrize("section", ["claim", "evidence", "uncertainty"])
@pytest.mark.parametrize("review", ["copied", "fresh", "explicit"])
def test_changed_content_requires_fresh_review_metadata(tmp_path, section, review):
    semantic = existing_records()
    source = getattr(semantic, "claims" if section == "claim" else section)[1]
    record = source.claim_text if section == "claim" else source
    metadata = {
        "review_status": "human_accepted", "reviewer": record.reviewer,
        "reviewed_at": record.reviewed_at,
    }
    if review == "fresh":
        metadata.update(reviewer="reviewer:bob", reviewed_at="2026-04-01T10:00:00Z")
    elif review == "explicit":
        metadata = {"review_status": "confirmed"}
    text_field = {"claim": "claim_text", "evidence": "result_summary", "uncertainty": "statement"}[section]
    data = {section: {"id": source.id, text_field: "A revised scientific statement.", **metadata}}
    apply_answers(tmp_path, semantic, data)
    result = getattr(semantic, "claims" if section == "claim" else section)[1]
    result = result.claim_text if section == "claim" else result
    if review == "copied":
        assert result.review_status.value == "needs_review"
        assert result.reviewer is None
        assert result.reviewed_at is None
    else:
        assert result.review_status.value == metadata["review_status"]
        assert result.reviewer == ("reviewer:bob" if review == "fresh" else "author")
        assert result.reviewed_at != record.reviewed_at


def test_generated_selections_roundtrip_native_provenance(tmp_path):
    script = tmp_path / "scene.pml"
    script.write_text("select active_site, chain A and resi 10\n")
    package = init_package(native=script, out=tmp_path / "package")
    selection = package.semantic_layer.selections[0].model_dump()
    data = package_answer_template(package.semantic_layer)
    data["claim"].update(claim_text="The selected region is chain A residue 10.", figure_ref="Figure 1")
    data["uncertainty"] = []
    assert check_answers(data, package.semantic_layer, root=package.root) == []
    apply_answers(package.root, package.semantic_layer, data)
    package.save()
    assert load_package(package.root).semantic_layer.selections[0].model_dump() == selection
    package.semantic_layer.selections[0].extensions["runtime_verification"] = "verified"
    apply_answers(package.root, package.semantic_layer, {"selections": [{
        "id": selection["id"], "native_selector": "chain B and resi 10",
    }]})
    changed = package.semantic_layer.selections[0]
    assert changed.native_selector.source_type.value == "user_asserted"
    assert changed.native_selector.source_location is None
    assert changed.extensions == selection["extensions"]


def test_partial_entity_edit_preserves_sources_and_extensions(tmp_path):
    semantic = existing_records()
    semantic.entities = [Entity(
        id="entity:a", label="Chain A", stable_identity="model/A", source_artifact_ids=["artifact:source"],
        extensions={"source_note": "Author-provided identity"}, review_status="confirmed",
    )]
    apply_answers(tmp_path, semantic, {"entities": [{"id": "entity:a", "label": "Domain in chain A"}]})
    assert semantic.entities[0].stable_identity == "model/A"
    assert semantic.entities[0].source_artifact_ids == ["artifact:source"]
    assert semantic.entities[0].extensions == {"source_note": "Author-provided identity"}


@pytest.mark.parametrize("section,change", [
    ("evidence", {"source_artifact_ids": ["artifact:typo"]}),
    ("evidence", {"target_selection_ids": ["selection:typo"]}),
    ("evidence", {"target_entity_ids": ["entity:typo"]}),
    ("claim", {"evidence_ids": ["evidence:typo"]}),
    ("uncertainty", {"claim_ids": ["claim:typo"]}),
])
def test_new_dangling_references_fail_before_copy_or_mutation(tmp_path, section, change):
    semantic = existing_records()
    before = semantic.model_dump()
    source = tmp_path / "new.txt"
    source.write_text("New evidence to attach after preflight.")
    root = tmp_path / "package"
    data = {
        "claim": {"id": "claim:b"}, "evidence": [], "reuse": {},
        "artifacts": [{"path": str(source), "role": "evidence_document"}],
    }
    data[section] = {"id": f"{section}:b", **change}
    assert any("Invalid answer value" in problem for problem in check_answers(data, semantic, root=root))
    with pytest.raises(ValueError, match="/claims/|/evidence/|/uncertainty/"):
        apply_answers(root, semantic, data)
    assert semantic.model_dump() == before
    assert not root.exists()


def test_existing_evidence_keeps_its_claim_binding_when_another_claim_is_edited(tmp_path):
    semantic = existing_records()
    data = {
        "claim": {"id": "claim:a", "claim_text": "Panel a shows a structure."},
        "evidence": [{"id": "evidence:b", "result_summary": "Panel b evidence clarified."}],
        "reuse": {},
    }
    assert check_answers(data, semantic, root=tmp_path) == []
    apply_answers(tmp_path, semantic, data)
    assert semantic.evidence[1].claim_ids == ["claim:b"]
    assert semantic.claims[0].evidence_ids == ["evidence:a"]
    assert semantic.claims[1].evidence_ids == ["evidence:b"]


def test_partial_ligand_claim_keeps_existing_entities_and_limits(tmp_path):
    semantic = existing_records()
    semantic.claims[1].claim_type = "ligand_binding_pose"
    semantic.entities = [Entity(id="entity:ligand", entity_type="ligand", stable_identity="model/A/LIG/201")]
    data = {"claim": {"id": "claim:b", "text": "Panel b shows the ligand pose."}, "evidence": [], "reuse": {}}
    assert check_answers(data, semantic, root=tmp_path) == []
    apply_answers(tmp_path, semantic, data)
    assert semantic.claims[1].claim_text.value == "Panel b shows the ligand pose."


def test_nested_claim_provenance_and_explicit_review_metadata(tmp_path):
    semantic = existing_records()
    timestamp = "2026-02-03T10:00:00Z"
    data = {
        "claim": {"id": "claim:b", "claim_text": {"source_type": "tool_generated", "review_status": "needs_review"}},
        "evidence": [{"id": "evidence:b", "reviewer": "reviewer:bob", "reviewed_at": timestamp}],
        "uncertainty": [{"id": "uncertainty:b", "reviewer": "reviewer:bob", "reviewed_at": timestamp}],
        "reuse": {},
    }
    assert check_answers(data, semantic, root=tmp_path) == []
    apply_answers(tmp_path, semantic, data)
    assert semantic.claims[1].review_status.value == "needs_review"
    assert semantic.claims[1].claim_text.value == "Panel b shows a molecular view."
    assert semantic.claims[1].claim_text.reviewer is None
    for record in (semantic.evidence[1], semantic.uncertainty[1]):
        assert record.reviewer == "reviewer:bob"
        assert record.reviewed_at == timestamp


def test_multi_claim_update_requires_explicit_id(tmp_path):
    semantic = existing_records()
    data = answers()
    del data["claim"]["id"]
    data["claim"]["scene_ids"] = ["scene:b"]
    before = semantic.model_dump()
    assert any("claim.id is required" in problem for problem in check_answers(data, semantic))
    with pytest.raises(ValueError, match="claim.id is required"):
        apply_answers(tmp_path, semantic, data)
    assert semantic.model_dump() == before


def test_explicit_pending_metadata_is_honest_and_legacy_human_defaults_remain(tmp_path):
    semantic = existing_records()
    data = {
        "claim": {"id": "claim:b", "source_type": "tool_generated", "review_status": "needs_review"},
        "evidence": [{"id": "evidence:b", "generated_by": "agent:assistant", "review_status": "needs_review"}],
        "uncertainty": [{"id": "uncertainty:b", "review_status": "needs_review"}],
        "reuse": {},
    }
    apply_answers(tmp_path, semantic, data)
    assert semantic.claims[1].claim_text.source_type.value == "tool_generated"
    for record in (semantic.claims[1].claim_text, semantic.evidence[1], semantic.uncertainty[1]):
        assert record.review_status.value == "needs_review"
        assert record.reviewer is None
        assert record.reviewed_at is None
    fresh = SemanticLayer.new("legacy")
    apply_answers(tmp_path, fresh, answers())
    assert fresh.claims[0].claim_text.reviewer == "author"
    assert fresh.claims[0].claim_text.reviewed_at
    assert fresh.claims[0].claim_text.review_status.value == "confirmed"


@pytest.mark.parametrize("attachment", ["artifacts", "evidence_path"])
def test_planned_artifact_ids_resolve_in_scene_and_native_bindings_without_writes(tmp_path, attachment):
    source = tmp_path / "figure.png"
    Image.new("RGB", (2, 2), "white").save(source)
    artifact_id = f"artifact:{sha256_file(source)[:12]}"
    semantic = SemanticLayer.new("future-artifacts")
    semantic.scenes = [Scene(id="scene:a")]
    before = semantic.model_dump()
    data = answers()
    data.update(
        answer_schema="claimtrace.native_scene_answers.v1",
        artifacts=[{"path": str(source), "role": "render_image"}],
        scene={"scene_ids": ["scene:a"], "render_artifact_ids": [artifact_id]},
        evidence_bindings=[{"claim_id": "claim:a", "evidence_artifact_ids": [artifact_id]}],
    )
    if attachment == "evidence_path":
        del data["artifacts"]
        data["evidence"] = [{
            "method_name": "Inspect supplied image", "result_summary": "The supplied panel was inspected.",
            "source_artifact_paths": [str(source)],
        }]
    root = tmp_path / "package"
    assert check_answers(data, semantic, root=root) == []
    assert semantic.model_dump() == before
    assert not root.exists()
    apply_answers(root, semantic, data)
    assert semantic.artifacts[0].id == artifact_id
    assert semantic.scenes[0].render_artifact_ids == [artifact_id]
    assert semantic.evidence_bindings[0].evidence_artifact_ids == [artifact_id]
    assert (root / "renders/figure.png").read_bytes() == source.read_bytes()


def test_registration_dry_run_keeps_same_id_and_checks_planned_collision(tmp_path):
    source = tmp_path / "first" / "notes.txt"
    source.parent.mkdir()
    source.write_text("first input")
    conflict = tmp_path / "second" / "notes.txt"
    conflict.parent.mkdir()
    conflict.write_text("different input")
    root = tmp_path / "package"
    semantic = SemanticLayer.new("registry-plan")
    planned = register_local_artifact(root, semantic, source, dry_run=True)
    assert not root.exists()
    with pytest.raises(PackageError, match="checksum"):
        register_local_artifact(root, semantic, conflict, dry_run=True)
    assert not root.exists()
    attached = register_local_artifact(root, semantic, source)
    assert attached.id == planned.id
    assert (root / attached.path).read_bytes() == source.read_bytes()


@pytest.mark.parametrize("section,link", [("evidence", "evidence_ids"), ("uncertainty", "uncertainty_ids")])
def test_completion_relinks_existing_record_in_both_directions(tmp_path, section, link):
    from claimtrace.validation.engine import _reference_findings

    semantic = existing_records()
    existing_gaps = _reference_findings(semantic)
    record = getattr(semantic, section)[1]
    apply_answers(tmp_path, semantic, {section: [{"id": record.id, "claim_ids": ["claim:a"]}]})
    assert record.id in getattr(semantic.claims[0], link)
    assert record.id not in getattr(semantic.claims[1], link)
    assert getattr(semantic, section)[1].claim_ids == ["claim:a"]
    assert _reference_findings(semantic) == existing_gaps


@pytest.mark.parametrize("section,link", [("evidence", "evidence_ids"), ("uncertainty", "uncertainty_ids")])
def test_completion_links_new_record_to_existing_unreviewed_claim(tmp_path, section, link):
    from claimtrace.validation.engine import _reference_findings

    semantic = existing_records()
    existing_gaps = _reference_findings(semantic)
    semantic.claims[0].review_status = "needs_review"
    record = {"id": f"{section}:new", "claim_ids": ["claim:a"]}
    record.update({"statement": "One conformation was examined."} if section == "uncertainty" else {
        "method_name": "Inspect the supplied panel", "result_summary": "Chain A is visible.",
        "source_artifact_ids": ["artifact:source"],
    })
    apply_answers(tmp_path, semantic, {section: [record]})
    assert record["id"] in getattr(semantic.claims[0], link)
    assert _reference_findings(semantic) == existing_gaps


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_python_completion_rejects_nonfinite_maps_before_attachment(tmp_path, number):
    semantic = existing_records()
    before = semantic.model_dump()
    root = tmp_path / "new-package"
    source = tmp_path / "new-source.txt"
    source.write_text("Recorded observation")
    data = {
        "claim": {"id": "claim:a"}, "reuse": {},
        "artifacts": [{"path": str(source), "role": "evidence_document"}],
        "evidence": [{"id": "evidence:a", "parameters": {"nested": [number]}}],
    }
    assert any("Non-finite" in problem for problem in check_answers(data, semantic, root=root))
    with pytest.raises(ValueError, match="Non-finite"):
        apply_answers(root, semantic, data)
    assert not root.exists()
    assert semantic.model_dump() == before


def test_completion_allocates_unique_activity_id_after_custom_provenance(tmp_path):
    from claimtrace.models import Activity
    from claimtrace.validation.engine import _reference_findings

    semantic = SemanticLayer.new("custom-provenance")
    semantic.provenance.activities.append(Activity(
        id="activity:completion:3", activity_type="completion", description="Earlier author entry.",
    ))
    apply_answers(tmp_path, semantic, {"reuse": {"license": "CC0-1.0"}})
    ids = [item.id for item in semantic.provenance.activities]
    assert len(ids) == len(set(ids))
    assert semantic.provenance.activities[-1].id == "activity:completion:4"
    assert not _reference_findings(semantic)
