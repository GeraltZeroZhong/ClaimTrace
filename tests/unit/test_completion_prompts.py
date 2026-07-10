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


def test_only_pml_template_does_not_invent_missing_structure_or_render(tmp_path: Path):
    script = tmp_path / "scene.pml"
    script.write_text("load model.cif, structure\nshow cartoon, structure\n", encoding="utf-8")
    pkg = init_package(native=script, out=tmp_path / "pkg")

    answers = package_answer_template(pkg.semantic_layer)

    assert answers["artifacts"] == []
    assert answers["evidence"] == []
    answers["claim"]["claim_text"] = "Draft claim recorded from the native scene."
    answers["claim"]["figure_ref"] = "Figure 1A"
    assert check_answers(answers, pkg.semantic_layer) == []
    assert completed_answer_sections(answers) == {
        "claim",
        "entities",
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
