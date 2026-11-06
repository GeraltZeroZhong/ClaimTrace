"""Authoring tasks preserve claim and scene scope across interface modes."""

import pytest

from claimtrace.gui.audit import build_audit
from claimtrace.models.semantic_layer import (
    Artifact, Claim, Evidence, ObservedSceneOperation, ProvenancedString, Scene, SemanticLayer, Uncertainty, VisualEncodingSemantics,
)
from claimtrace.models.validation import SemanticLayerRef, ValidationFinding, ValidationReport
from claimtrace.workflow import build_workflow


def projected(tmp_path, semantic):
    report = ValidationReport(
        package_id="workflow", export_mode="draft", overall_status="pass",
        semantic_layer_ref=SemanticLayerRef(sha256="", schema_version="0.1.0"),
    )
    return build_workflow(semantic, report, build_audit(tmp_path, semantic, report))


def package():
    semantic = SemanticLayer.new("workflow")
    semantic.scenes = [Scene(id="scene:before", description="Before", camera={"focus": "site"})]
    semantic.claims = [Claim(
        id="claim:1", claim_text=ProvenancedString(value="The two structures differ."),
        figure_ref="Figure A", scene_ids=["scene:before"], claim_type="model_comparison",
    )]
    return semantic


def test_pending_limitation_opens_existing_record(tmp_path):
    semantic = package()
    semantic.uncertainty = [
        Uncertainty(id="uncertainty:1", statement="TODO: inspect alternatives", claim_ids=["claim:1"], review_status="confirmed", reviewer="author", reviewed_at="2026-10-01T10:00:00Z"),
        Uncertainty(id="uncertainty:2", statement="unknown", claim_ids=["claim:1"]),
    ]
    semantic.claims[0].uncertainty_ids = [item.id for item in semantic.uncertainty]
    workflow = projected(tmp_path, semantic)
    tasks = [item for item in workflow["tasks"] if item["action"] == "edit-uncertainty"]
    assert {item["record_id"] for item in tasks} == {"uncertainty:1", "uncertainty:2"}
    assert not any(item["action"] == "new-uncertainty" for item in workflow["tasks"])


@pytest.mark.parametrize("review", [
    {"reviewer": None, "reviewed_at": "2026-10-01T10:00:00Z"},
    {"reviewer": "unknown", "reviewed_at": "2026-10-01T10:00:00Z"},
    {"reviewer": "Author", "reviewed_at": "pending"},
])
def test_incomplete_review_opens_existing_limitation(tmp_path, review):
    semantic = package()
    semantic.uncertainty = [Uncertainty(
        id="uncertainty:existing", statement="One conformation is represented.",
        claim_ids=["claim:1"], review_status="confirmed", **review,
    )]
    tasks = projected(tmp_path, semantic)["tasks"]
    assert any(t["action"] == "edit-uncertainty" and t["record_id"] == "uncertainty:existing" for t in tasks)
    assert not any(t["action"] == "new-uncertainty" for t in tasks)


def test_missing_views_have_distinct_scene_targets(tmp_path):
    semantic = package()
    semantic.scenes.extend([Scene(id="scene:after", description="After"), Scene(id="scene:alternate", description="Alternate")])
    semantic.claims[0].scene_ids = [item.id for item in semantic.scenes]
    workflow = projected(tmp_path, semantic)
    tasks = [item for item in workflow["tasks"] if item["action"] == "context"]
    assert {item["scene_id"] for item in tasks} == {"scene:after", "scene:alternate"}
    assert len({item["id"] for item in tasks}) == 2
    assert all("scene:before" != item["scene_id"] for item in tasks)
    assert "After" in next(item["detail"] for item in tasks if item["scene_id"] == "scene:after")


def test_image_view_description_keeps_scene_attachment_question_until_source_attached(tmp_path):
    semantic = package()
    image = Artifact(id="image:panel", path="panel.png", role="render_image")
    semantic.artifacts.append(image)
    (tmp_path / image.path).write_bytes(b"figure image")
    scene = semantic.scenes[0]
    scene.extensions = {"view_kind": "molecular"}
    scene.camera = {}
    scene.render_artifact_ids = [image.id]
    scene.description = "Static image scene requiring author completion."
    before = projected(tmp_path, semantic)
    scene_tasks = [item for item in before["tasks"] if item["scene_id"] == scene.id]
    assert {item["action"] for item in scene_tasks} == {"context", "attach"}

    scene.camera = {"author_context": "Full panel, with teal residues shown at the lower edge."}
    after = projected(tmp_path, semantic)
    scene_tasks = [item for item in after["tasks"] if item["scene_id"] == scene.id]
    assert [item["action"] for item in scene_tasks] == ["attach"]
    assert scene_tasks[0]["claim_id"] == semantic.claims[0].id
    assert not scene_tasks[0]["blocking"]
    assert after["lifecycle"]["ready"]

    native = Artifact(id="native:scene", path="scene.pml", role="native_script")
    semantic.artifacts.append(native)
    scene.native_artifact_ids = [native.id]
    (tmp_path / native.path).write_text("show cartoon\n")
    assert not any(
        item["action"] == "attach" and item["scene_id"] == scene.id
        for item in projected(tmp_path, semantic)["tasks"]
    )


@pytest.mark.parametrize("view_kind", ["plot", "figure_assembly", "molecular"])
def test_image_type_precedes_type_specific_guidance(tmp_path, view_kind):
    semantic = package()
    image = Artifact(id="image:panel", path="panel.png", role="render_image")
    semantic.artifacts.append(image)
    (tmp_path / image.path).write_bytes(b"figure image")
    scene = semantic.scenes[0]
    scene.camera = {"author_context": "A previously recorded figure description."}
    scene.render_artifact_ids = [image.id]
    tasks = [item for item in projected(tmp_path, semantic)["tasks"] if item["scene_id"] == scene.id]
    assert [(item["action"], item["title"]) for item in tasks] == [
        ("context", "What kind of figure is this?")
    ]
    scene.extensions = {"view_kind": view_kind}
    tasks = [item for item in projected(tmp_path, semantic)["tasks"] if item["scene_id"] == scene.id]
    assert [item["action"] for item in tasks] == (["attach"] if view_kind == "molecular" else [])


@pytest.mark.parametrize("view_kind", ["plot", "figure_assembly"])
def test_static_figure_questions_request_settings_and_preserve_package_gate(tmp_path, view_kind):
    semantic = package()
    image = Artifact(id="image:panel", path="panel.png", role="render_image")
    semantic.artifacts.append(image)
    (tmp_path / image.path).write_bytes(b"figure image")
    scene = semantic.scenes[0]
    scene.camera = {}
    scene.render_artifact_ids = [image.id]
    scene.extensions = {"view_kind": view_kind}
    tasks = [item for item in projected(tmp_path, semantic)["tasks"] if item["scene_id"] == scene.id]
    assert [item["action"] for item in tasks] == ["context"]
    assert "settings" in tasks[0]["detail"]
    assert "camera" not in tasks[0]["detail"]

    scene.camera = {"author_context": "Frame index versus contact state; all 500 frames."}
    assert not any(item["scene_id"] == scene.id for item in projected(tmp_path, semantic)["tasks"])

    finding = ValidationFinding(
        rule_id="CLAIM.SIMPLE.REQUIRED_STRUCTURE", gate="G4", validation_level="L3",
        severity="ERROR", finding_class="REVIEWABILITY_ERROR", status="FAIL",
        message="The selected claim type requires structure context.",
        json_pointer="/claims/0/claim_type", blocks_modes=["archive"],
    )
    report = ValidationReport(
        package_id="workflow", export_mode="archive", overall_status="fail",
        semantic_layer_ref=SemanticLayerRef(sha256="", schema_version="0.1.0"),
        findings=[finding],
    )
    workflow = build_workflow(semantic, report, build_audit(tmp_path, semantic, report))
    assert workflow["lifecycle"]["ready"] is False
    assert workflow["lifecycle"]["blocking_count"] == 1
    requirement = next(item for item in workflow["tasks"] if finding.rule_id in item["rule_ids"])
    assert requirement["action"] == "add-structure"
    assert requirement["title"] == "Which structure was used?"
    assert "analysis" in requirement["detail"]
    assert requirement["blocking"] is True


def test_distance_question_targets_incomplete_measurement(tmp_path):
    semantic = package()
    semantic.evidence = [
        Evidence(id="evidence:complete", evidence_kind="measurement", claim_ids=["claim:1"], thresholds={"distance": 4}, units={"distance": "angstrom"}),
        Evidence(id="evidence:pending", evidence_kind="measurement", claim_ids=["claim:1"]),
    ]
    semantic.claims[0].evidence_ids = [item.id for item in semantic.evidence]
    tasks = projected(tmp_path, semantic)["tasks"]
    distance = [item for item in tasks if item["title"] == "What distance was measured?"]
    assert len(distance) == 1
    assert distance[0]["record_id"] == "evidence:pending"
    assert not any(item["action"] == "cutoff" for item in tasks)


def test_draft_visual_questions_stay_with_their_claim(tmp_path):
    semantic = package()
    (tmp_path / "scene.mvsj").write_text("{}")
    semantic.artifacts.append(Artifact(id="native:scene", path="scene.mvsj", role="molviewspec"))
    semantic.scenes[0].native_artifact_ids = ["native:scene"]
    semantic.scenes[0].extensions = {"molviewspec_root": {"json_pointer": "/snapshots/0/root"}}
    semantic.scenes.append(Scene(id="scene:after", description="After", camera={"focus": "other"}, native_artifact_ids=["native:scene"], extensions={"molviewspec_root": {"json_pointer": "/snapshots/1/root"}}))
    semantic.claims.append(Claim(id="claim:2", claim_text=ProvenancedString(value="Another view."), scene_ids=["scene:after"]))
    semantic.observed_scene_operations.append(ObservedSceneOperation(
        operation_id="operation:color", operation="colored", target="site",
        details={"scene_id": "scene:before"}, meaning_status="requires_user_completion",
        source_location={"artifact_id": "native:scene", "json_pointer": "/snapshots/0/root/children/0"},
        needs_author_confirmation=True,
    ))
    workflow = projected(tmp_path, semantic)
    questions = [item for item in workflow["tasks"] if item["action"] == "explain-colors"]
    assert [item["claim_id"] for item in questions] == ["claim:1"]
    assert workflow["lifecycle"]["ready"] is True
    assert not questions[0]["blocking"]

    finding = ValidationFinding(
        rule_id="CLAIM.LIGAND.IDENTITY_CONTEXT", gate="G4", validation_level="L3",
        severity="ERROR", finding_class="REVIEWABILITY_ERROR", status="FAIL",
        message="Link the selected atoms to their molecular identities.",
        json_pointer="/claims/0", blocks_modes=["archive"],
    )
    report = ValidationReport(
        package_id="workflow", export_mode="draft", overall_status="pass",
        semantic_layer_ref=SemanticLayerRef(sha256="", schema_version="0.1.0"),
        findings=[finding],
    )
    prioritized = build_workflow(semantic, report, build_audit(tmp_path, semantic, report))
    assert prioritized["next_action"]["action"] == "identify-regions"
    assert prioritized["next_action"]["claim_id"] == "claim:1"
    assert prioritized["lifecycle"]["ready"] is True


@pytest.mark.parametrize(
    "meaning_status,meaning_field",
    [
        ("user_confirmed_meaning", "meaning"),
        ("user_declared_no_scientific_meaning", "no_scientific_meaning_reason"),
    ],
)
def test_recorded_visual_meaning_completes_question_with_original_import_flags(
    tmp_path, meaning_status, meaning_field
):
    semantic = package()
    (tmp_path / "scene.pml").write_text("color teal, site\n")
    semantic.artifacts.append(Artifact(id="native:scene", path="scene.pml", role="native_script"))
    semantic.scenes[0].native_artifact_ids = ["native:scene"]
    semantic.observed_scene_operations.append(ObservedSceneOperation(
        operation_id="operation:color", operation="colored", target="site",
        meaning_status="requires_user_completion", needs_author_confirmation=True,
        source_location={"artifact_id": "native:scene", "line": 1},
    ))
    assert any(item["action"] == "explain-colors" for item in projected(tmp_path, semantic)["tasks"])
    meaning = VisualEncodingSemantics(
        operation_ids=["operation:color"], encoding_type="color",
        meaning_status=meaning_status, reviewer="Author", reviewed_at="2026-10-01T10:00:00Z",
        **{meaning_field: "Teal identifies the selected site."},
    )
    semantic.visual_encoding_semantics.append(meaning)
    assert not any(item["action"] == "explain-colors" for item in projected(tmp_path, semantic)["tasks"])
    assert semantic.observed_scene_operations[0].needs_author_confirmation
    meaning.reviewed_at = None
    assert any(item["action"] == "explain-colors" for item in projected(tmp_path, semantic)["tasks"])
