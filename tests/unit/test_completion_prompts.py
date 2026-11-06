from pathlib import Path

import yaml

from claimtrace.api import init_package
from claimtrace.completion import (
    answer_template,
    apply_answers,
    check_answers,
    completed_answer_sections,
    completion_tasks_for_template,
    package_answer_template,
)
from claimtrace.models.semantic_layer import SoftwareEnvironment, VisualEncodingSemantics, Waiver


def test_scene_prompt_asks_meaning_not_observed_object_listing():
    tasks = completion_tasks_for_template("simple-structure-view")
    scene_task = next(task for task in tasks if task.section == "scene")

    assert "low-confidence or claim-critical color/label suggestions" in scene_task.question
    assert "literal scene facts automatically" in scene_task.question
    assert "Which displayed" not in scene_task.question
    assert "hidden" not in scene_task.question


def test_packaged_answer_templates_match_runtime_defaults():
    template_root = Path("src/claimtrace/resources/templates")
    for name in ("simple-structure-view", "ligand-binding-pose"):
        packaged = yaml.safe_load((template_root / f"{name}.yml").read_text(encoding="utf-8"))
        assert packaged == answer_template(name)


def test_package_answer_template_lists_extracted_selections(tmp_path: Path):
    script = tmp_path / "scene.pml"
    script.write_text("select active_site, chain A and resi 10\n", encoding="utf-8")
    pkg = init_package(native=script, out=tmp_path / "pkg")

    template = package_answer_template(pkg.semantic_layer)

    assert template["selections"][0]["name"] == "active_site"
    assert template["selections"][0]["native_selector"] == "chain A and resi 10"
    assert template["selections"][0]["review_status"] == "needs_review"
    assert "claim_critical" in template["selections"][0]["review_instruction"]


def test_ligand_template_todo_claim_is_rejected(tmp_path: Path):
    pkg = init_package(blank=True, out=tmp_path / "pkg")
    answers = package_answer_template(pkg.semantic_layer, "ligand-binding-pose")

    problems = check_answers(answers)

    assert any("claim.claim_text is still unknown" in problem for problem in problems)
    assert any("method_name is still unknown" in problem for problem in problems)
    assert any("thresholds.distance" in problem for problem in problems)
    assert any("stable_identity is still unknown" in problem for problem in problems)
    assert any("uncertainty[0].statement" in problem for problem in problems)
    assert answers["evidence"][0]["target_entity_ids"] == [
        "entity:ligand:X",
        "entity:binding-site",
    ]


def test_noncritical_visual_item_can_keep_unresolved_meaning_status(tmp_path: Path):
    script = tmp_path / "scene.cxc"
    script.write_text("color #1/A #ff00ff\n", encoding="utf-8")
    pkg = init_package(native=script, out=tmp_path / "pkg")
    answers = package_answer_template(pkg.semantic_layer)
    answers["claim"]["claim_text"] = "The panel shows chain A."
    answers["claim"]["figure_ref"] = "Figure 1A"
    answers["scene_semantics_by_operation"][0]["claim_critical"] = False

    problems = check_answers(answers, pkg.semantic_layer)

    assert not any("meaning_status" in problem for problem in problems)


def test_answer_waiver_can_anchor_to_claim_created_by_same_answers(tmp_path: Path):
    script = tmp_path / "scene.cxc"
    script.write_text("color #1/A #ff00ff\n", encoding="utf-8")
    pkg = init_package(native=script, out=tmp_path / "pkg")
    answers = package_answer_template(pkg.semantic_layer)
    answers["claim"].update(
        {
            "id": "claim:panel-a",
            "claim_text": "The panel shows chain A.",
            "figure_ref": "Figure 1A",
        }
    )
    answers["scene_semantics_by_operation"][0]["claim_critical"] = False
    answers["waivers"] = [
        {
            "rule_id": "CLAIM.EXAMPLE",
            "scope": "claim:panel-a",
            "anchor_id": "claim:panel-a",
            "reason": "Reviewed for this claim.",
            "reviewer": "author",
            "max_export_mode": "draft",
        }
    ]

    problems = check_answers(answers, pkg.semantic_layer)

    assert not any("waivers[0] references unknown anchor_id" in problem for problem in problems)
    apply_answers(pkg.root, pkg.semantic_layer, answers, answer_base=tmp_path)
    assert any(claim.id == "claim:panel-a" for claim in pkg.semantic_layer.claims)
    assert pkg.semantic_layer.provenance.waivers[-1].anchor_id == "claim:panel-a"


def test_only_pml_template_does_not_invent_missing_structure_or_render(tmp_path: Path):
    script = tmp_path / "scene.pml"
    script.write_text("load model.cif, structure\nshow cartoon, structure\n", encoding="utf-8")
    pkg = init_package(native=script, out=tmp_path / "pkg")

    answers = package_answer_template(pkg.semantic_layer)

    assert answers["artifacts"] == []
    assert answers["evidence"] == []
    answers["claim"]["claim_text"] = "Draft claim recorded from the native scene."
    answers["claim"]["figure_ref"] = "Figure 1A"
    answers["uncertainty"] = []
    assert check_answers(answers, pkg.semantic_layer) == []
    assert completed_answer_sections(answers) == {
        "claim",
        "entities",
        "evidence",
        "scene",
        "uncertainty",
        "reuse",
    }


def test_reapplying_answers_is_idempotent(tmp_path: Path):
    script = tmp_path / "scene.pml"
    script.write_text("color cyan, all\n", encoding="utf-8")
    pkg = init_package(native=script, out=tmp_path / "pkg")
    answers = package_answer_template(pkg.semantic_layer)
    answers["claim"]["claim_text"] = "Figure shows the scene."
    answers["evidence"] = [
        {
            "evidence_kind": "manual_rationale",
            "method_name": "Author review",
            "result_summary": "The native scene was reviewed.",
            "source_artifact_roles": ["native_script"],
        }
    ]

    apply_answers(pkg.root, pkg.semantic_layer, answers, answer_base=tmp_path)
    first_counts = (
        len(pkg.semantic_layer.evidence),
        len(pkg.semantic_layer.uncertainty),
        len(pkg.semantic_layer.visual_encoding_semantics),
    )
    apply_answers(pkg.root, pkg.semantic_layer, answers, answer_base=tmp_path)

    assert (
        len(pkg.semantic_layer.evidence),
        len(pkg.semantic_layer.uncertainty),
        len(pkg.semantic_layer.visual_encoding_semantics),
    ) == first_counts


def test_reapplying_answers_can_add_remote_artifact_checksum(tmp_path: Path):
    pkg = init_package(blank=True, out=tmp_path / "pkg")
    url = "https://example.org/model.cif"
    answers = {"artifacts": [{"url": url, "role": "generic"}]}

    apply_answers(pkg.root, pkg.semantic_layer, answers, answer_base=tmp_path)
    answers["artifacts"][0].update({"role": "structure", "sha256": "a" * 64})
    apply_answers(pkg.root, pkg.semantic_layer, answers, answer_base=tmp_path)

    matching = [artifact for artifact in pkg.semantic_layer.artifacts if artifact.url == url]
    assert len(matching) == 1
    assert matching[0].role.value == "structure"
    assert matching[0].sha256 == "a" * 64
    assert matching[0].fixity_status == "available"


def test_current_template_roundtrip_preserves_reviewed_context_and_native_provenance(tmp_path):
    script = tmp_path / "scene.pml"
    script.write_text("select site, chain A and resi 10\ncolor cyan, site\nunknown_command site\n")
    pkg = init_package(native=script, out=tmp_path / "pkg")
    pkg.add_claim("Chain A residue 10 is shown in cyan.", "simple_structure_view", "Figure 1")
    semantic = pkg.semantic_layer
    timestamp = "2026-01-02T10:00:00Z"
    semantic.package.description = "Reviewed molecular panel."
    semantic.package.license = "CC-BY-4.0"
    semantic.reuse.license = "CC-BY-4.0"
    semantic.reuse.citation = "Data source citation."
    semantic.reuse.restrictions = ["Retain attribution."]
    semantic.reuse.reviewer = "reviewer:alice"
    semantic.reuse.reviewed_at = timestamp
    semantic.software_environment = [SoftwareEnvironment(
        id="software:viewer", name="PyMOL", version="3.1", extensions={"platform": "Linux"},
    )]
    meaning = {
        "color_meanings": {"cyan": "Chain A residue 10"}, "label_meanings": {}, "notes": "Residue view.",
        "review_status": "confirmed", "reviewer": "reviewer:alice", "reviewed_at": timestamp,
    }
    semantic.scenes[0].extensions["user_scene_semantics"] = [meaning]
    operation = next(item for item in semantic.observed_scene_operations if item.operation == "colored")
    operation.meaning_status = "user_confirmed_meaning"
    operation.review_status = "confirmed"
    operation.needs_author_confirmation = False
    semantic.visual_encoding_semantics = [VisualEncodingSemantics(
        operation_ids=[operation.operation_id], encoding_type="colored",
        meaning_status="user_confirmed_meaning", meaning="Chain A residue 10",
        reviewer="reviewer:alice", reviewed_at=timestamp,
    )]
    raw = semantic.raw_native_observations[0]
    raw.resolution = "reviewed_no_claim_impact"
    raw.claim_critical = "false"
    raw.review_status = "confirmed"
    semantic.provenance.waivers = [Waiver(
        rule_id="IMPORT.PYMOL.RAW_AFFECTS_SCENE", scope=raw.raw_id, anchor_id=raw.raw_id,
        reason="Reviewed as incidental to the panel.", reviewer="reviewer:alice", reviewed_at=timestamp,
    )]
    # Revalidate assigned enum fields as when loading a saved package.
    semantic = type(semantic).model_validate(semantic.model_dump())
    before = semantic.model_dump()
    data = package_answer_template(semantic)
    assert data["scene"]["color_meanings"] == {"cyan": "Chain A residue 10"}
    assert data["reuse"]["citation"] == "Data source citation."
    assert data["raw_resolutions"][0]["resolution"] == "reviewed_no_claim_impact"
    assert data["evidence"] == data["uncertainty"] == []
    assert check_answers(data, semantic, root=pkg.root) == []
    for _ in range(2):
        apply_answers(pkg.root, semantic, data)
        after = semantic.model_dump()
        for field in (
            "claims", "entities", "selections", "evidence", "uncertainty", "reuse",
            "software_environment", "visual_encoding_semantics", "raw_native_observations", "scenes",
            "native_references", "observed_scene_operations",
        ):
            assert after[field] == before[field], field
        assert after["provenance"]["waivers"] == before["provenance"]["waivers"]
    data["scene_semantics_by_operation"][0]["meaning"] = "Chain B residue 10"
    data["scene"]["color_meanings"]["cyan"] = "Chain B residue 10"
    apply_answers(pkg.root, semantic, data)
    changed_meaning = semantic.visual_encoding_semantics[0]
    assert changed_meaning.meaning_status.value == "requires_user_completion"
    assert changed_meaning.reviewer is None
    assert changed_meaning.reviewed_at is None
    changed_scene = semantic.scenes[0].extensions["user_scene_semantics"][0]
    assert changed_scene["review_status"] == "needs_review"
    assert changed_scene["reviewer"] is None
    assert changed_scene["reviewed_at"] is None


def test_current_draft_keeps_pending_native_observations_without_redundant_records(tmp_path):
    script = tmp_path / "scene.pml"
    script.write_text("distance d, chain A and resi 1, chain B and resi 2\ncolor cyan, binding_site\n")
    pkg = init_package(native=script, out=tmp_path / "pkg")
    pkg.add_claim("The figure shows a selected distance guide.", "simple_structure_view", "Figure 1")
    before = pkg.semantic_layer.model_dump()
    answers = package_answer_template(pkg.semantic_layer)
    assert answers["scene_semantics_by_operation"]
    assert answers["evidence"][0]["review_status"] == "needs_review"
    assert check_answers(answers, pkg.semantic_layer, root=pkg.root) == []
    apply_answers(pkg.root, pkg.semantic_layer, answers)
    after = pkg.semantic_layer.model_dump()
    for field in ("claims", "evidence", "observed_scene_operations", "visual_encoding_semantics"):
        assert before[field] == after[field]
    answers["evidence"][0]["result_summary"] = "A measured result is being added."
    assert any("thresholds.distance" in issue for issue in check_answers(answers, pkg.semantic_layer, root=pkg.root))


def test_scene_meanings_stay_with_their_own_native_operations_and_update(tmp_path):
    first, second = tmp_path / "first.pml", tmp_path / "second.pml"
    first.write_text('color red, chain A\nlabel chain A, "A"\n')
    second.write_text('color red, chain B\nlabel chain B, "B"\n')
    pkg = init_package(native=[first, second], out=tmp_path / "package")
    semantic = pkg.semantic_layer
    scene_a, scene_b = semantic.scenes
    meanings_a = {"scene_ids": [scene_a.id], "color_meanings": {"red": "Chain A"},
                  "label_meanings": {"\"A\"": "Chain A label"}, "notes": "Panel A"}
    meanings_b = {"scene_ids": [scene_b.id], "color_meanings": {"red": "Chain B"}}
    apply_answers(pkg.root, semantic, {"scenes": [meanings_a, meanings_b]})

    def meaning_for(scene, operation_type):
        operation = next(op for op in semantic.observed_scene_operations
                         if op.source_location.artifact_id in scene.native_artifact_ids
                         and op.operation == operation_type)
        return next((item for item in semantic.visual_encoding_semantics
                     if operation.operation_id in item.operation_ids), None)

    assert meaning_for(scene_a, "colored").meaning == "Chain A"
    assert meaning_for(scene_b, "colored").meaning == "Chain B"
    assert meaning_for(scene_a, "labeled").meaning == "Chain A label"
    assert meaning_for(scene_b, "labeled") is None
    apply_answers(pkg.root, semantic, {"scene": {
        "scene_ids": [scene_a.id], "color_meanings": {"red": "Mutation site in chain A"},
    }})
    revised = meaning_for(scene_a, "colored")
    assert revised.meaning == "Mutation site in chain A"
    assert revised.meaning_status.value == "requires_user_completion"
    assert revised.reviewer is None
    assert meaning_for(scene_b, "colored").meaning == "Chain B"
    # Clearing a color mapping removes its derived meaning; unrelated labels stay recorded.
    apply_answers(pkg.root, semantic, {"scene": {"scene_ids": [scene_a.id], "color_meanings": {}}})
    assert meaning_for(scene_a, "colored") is None
    assert meaning_for(scene_a, "labeled").meaning == "Chain A label"
    assert semantic.scenes[0].extensions["user_scene_semantics"][0]["notes"] == "Panel A"


def test_scene_meaning_respects_snapshot_scene_id_over_shared_native_file(tmp_path):
    from claimtrace.models import Artifact, ObservedSceneOperation, Scene, SemanticLayer

    semantic = SemanticLayer.new("snapshots")
    semantic.artifacts = [Artifact(id="artifact:mvs", role="molviewspec")]
    semantic.scenes = [Scene(id=f"scene:{letter}", native_artifact_ids=["artifact:mvs"]) for letter in "ab"]
    semantic.observed_scene_operations = [ObservedSceneOperation(
        operation_id=f"operation:{letter}", operation="colored",
        source_location={"artifact_id": "artifact:mvs"},
        details={"scene_id": f"scene:{letter}", "color": "red"},
    ) for letter in "ab"]
    apply_answers(tmp_path, semantic, {"scene": {"scene_ids": ["scene:a"], "color_meanings": {"red": "Chain A"}}})
    assert len(semantic.visual_encoding_semantics) == 1
    assert semantic.visual_encoding_semantics[0].operation_ids == ["operation:a"]


def test_editing_one_operation_splits_grouped_meanings_and_clears_stale_review(tmp_path):
    from claimtrace.validation.engine import _native_scene_anchor_findings

    script = tmp_path / "scene.pml"
    script.write_text("color red, binding_site\ncolor blue, ligand\n")
    pkg = init_package(native=script, out=tmp_path / "package")
    semantic = pkg.semantic_layer
    ids = [operation.operation_id for operation in semantic.observed_scene_operations]
    original = {
        "operation_ids": ids, "encoding_type": "colored", "meaning": "Binding interface",
        "meaning_status": "user_confirmed_meaning", "claim_critical": True,
        "reviewer": "Reviewer A", "reviewed_at": "2026-01-01T00:00:00Z",
    }
    apply_answers(pkg.root, semantic, {"scene_semantics_by_operation": [original]})
    apply_answers(pkg.root, semantic, {"scene_semantics_by_operation": [{
        **original, "operation_ids": [ids[0]], "meaning": "Catalytic residues",
    }]})
    edited = next(item for item in semantic.visual_encoding_semantics if ids[0] in item.operation_ids)
    retained = next(item for item in semantic.visual_encoding_semantics if ids[1] in item.operation_ids)
    assert edited.operation_ids == [ids[0]]
    assert edited.meaning_status.value == "requires_user_completion"
    assert edited.reviewer is None
    assert retained.operation_ids == [ids[1]]
    assert retained.meaning == "Binding interface"
    assert retained.reviewer == "Reviewer A"
    findings = _native_scene_anchor_findings(semantic, "archive")
    assert any(issue.rule_id == "SCENE.VISUAL_ENCODING.MEANING_MISSING"
               and issue.json_pointer == "/observed_scene_operations/0" for issue in findings)


def test_reordering_grouped_operation_ids_replaces_the_same_meaning(tmp_path):
    script = tmp_path / "scene.pml"
    script.write_text("color red, binding_site\ncolor blue, ligand\n")
    pkg = init_package(native=script, out=tmp_path / "package")
    ids = [operation.operation_id for operation in pkg.semantic_layer.observed_scene_operations]
    item = {"operation_ids": ids, "encoding_type": "colored", "meaning": "Interface",
            "meaning_status": "user_confirmed_meaning", "reviewer": "Reviewer A",
            "reviewed_at": "2026-01-01T00:00:00Z"}
    apply_answers(pkg.root, pkg.semantic_layer, {"scene_semantics_by_operation": [item]})
    apply_answers(pkg.root, pkg.semantic_layer, {"scene_semantics_by_operation": [{
        **item, "operation_ids": list(reversed(ids)),
    }]})
    assert len(pkg.semantic_layer.visual_encoding_semantics) == 1
    assert pkg.semantic_layer.visual_encoding_semantics[0].reviewer == "Reviewer A"


def test_clearing_native_identity_resets_its_resolution(tmp_path):
    from claimtrace.models import NativeReference, SemanticLayer

    semantic = SemanticLayer.new("clear-identity")
    semantic.native_references = [NativeReference(
        native_ref_id="ref:chain", native_expression="chain A", ref_type="chain",
        stable_identity="Model 1 chain A", identity_status="resolved", claim_critical="true",
    )]
    apply_answers(tmp_path, semantic, {"native_identity_mappings": [{
        "native_ref_id": "ref:chain", "stable_identity": "", "identity_status": "resolved",
    }]})
    assert semantic.native_references[0].identity_status == "unresolved"
