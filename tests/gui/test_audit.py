"""Claim-scoped projection tests: attribution and scientific boundaries."""

from pathlib import Path

import pytest

from claimtrace.api import init_package
from claimtrace.gui.audit import build_audit, export_markdown
from claimtrace.models.semantic_layer import (
    Artifact,
    Claim,
    Evidence,
    ObservedSceneOperation,
    ProvenancedString,
    ResourceReference,
    Scene,
    SemanticLayer,
    Uncertainty,
)
from claimtrace.models.validation import SemanticLayerRef, ValidationFinding, ValidationReport


def _report(*findings: ValidationFinding, mode: str = "archive") -> ValidationReport:
    return ValidationReport(
        package_id="test",
        semantic_layer_ref=SemanticLayerRef(sha256="", schema_version="1.0"),
        export_mode=mode,
        overall_status="pass",
        findings=list(findings),
    )


def _review() -> dict:
    return {
        "review_status": "confirmed",
        "reviewer": "Author",
        "reviewed_at": "2026-10-01T10:00:00Z",
    }


def _package(tmp_path: Path, suffix: str = "a") -> SemanticLayer:
    semantic = SemanticLayer.new("test")
    native = f"native:{suffix}"
    path = f"{suffix}.pml"
    (tmp_path / path).write_text("show cartoon\n", encoding="utf-8")
    semantic.artifacts.append(Artifact(id=native, path=path, role="native_script"))
    semantic.scenes.append(
        Scene(id=f"scene:{suffix}", native_artifact_ids=[native], camera={"set_view": "1,0,0"})
    )
    semantic.claims.append(
        Claim(
            id=f"claim:{suffix}",
            figure_ref=f"Figure {suffix}",
            claim_type="simple_structure_view",
            claim_text=ProvenancedString(value=f"Structure {suffix} is shown.", **_review()),
            scene_ids=[f"scene:{suffix}"],
            review_status="confirmed",
        )
    )
    return semantic


def _stage(claim: dict, key: str) -> dict:
    return next(stage for stage in claim["stages"] if stage["key"] == key)


def test_overflowing_distance_value_keeps_the_audit_readable(tmp_path):
    semantic = _package(tmp_path)
    semantic.evidence.append(Evidence(
        id="evidence:distance", claim_ids=["claim:a"], evidence_kind="measurement",
        parameters={"measured_distance": 10 ** 400}, units={"distance": "angstrom"},
    ))
    claim, = build_audit(tmp_path, semantic, _report())["claims"]
    stage = _stage(claim, "reproducibility")
    assert stage["status"] == "missing"
    assert "measured distance needed" in stage["summary"]


def test_multi_claim_findings_and_sources_stay_scoped(tmp_path):
    semantic = _package(tmp_path)
    second = _package(tmp_path, "b")
    semantic.claims.extend(second.claims)
    semantic.scenes.extend(second.scenes)
    semantic.artifacts.extend(second.artifacts)
    semantic.evidence.append(
        Evidence(
            id="evidence:b",
            claim_ids=["claim:b"],
            source_artifact_ids=["native:b"],
            method_name="Author visual review",
            result_summary="The view is descriptive.",
            **_review(),
        )
    )
    semantic.claims[1].evidence_ids = ["evidence:b"]
    issue = ValidationFinding(
        rule_id="CLAIM.BASIC.EVIDENCE",
        gate="G4",
        validation_level="L3",
        severity="ERROR",
        finding_class="REVIEWABILITY_ERROR",
        status="FAIL",
        message="A needs evidence.",
        json_pointer="/claims/0/evidence_ids",
        blocks_modes=["archive"],
    )
    global_issue = issue.model_copy(
        update={
            "rule_id": "PACKAGE.TEST",
            "json_pointer": "/package/license",
            "message": "Package license context.",
        }
    )
    audit = build_audit(tmp_path, semantic, _report(issue, global_issue))
    a, b = audit["claims"]
    assert a["artifact_ids"] == ["native:a"]
    assert b["artifact_ids"] == ["native:b"]
    assert a["evidence_ids"] == []
    assert b["evidence_ids"] == ["evidence:b"]
    assert a["validation_blockers"] == 1
    assert b["validation_blockers"] == 0
    assert not any(item.get("rule_id") == "CLAIM.BASIC.EVIDENCE" for item in b["issues"])
    assert audit["package_findings"][0]["rule_id"] == "PACKAGE.TEST"


def test_ligand_missing_cutoff_provenance_and_uncertainty(tmp_path):
    semantic = _package(tmp_path)
    semantic.claims[0].claim_type = "ligand_binding_pose"
    semantic.observed_scene_operations.append(
        ObservedSceneOperation(
            operation_id="op:distance",
            operation="measurement_intent",
            details={"command": "distance", "selection_1": "ligand", "selection_2": "pocket"},
            source_location={"artifact_id": "native:a", "line": 4},
        )
    )
    claim = build_audit(tmp_path, semantic, _report())["claims"][0]
    assert _stage(claim, "provenance")["status"] == "missing"
    assert _stage(claim, "uncertainty")["status"] == "missing"
    assert "cutoff and units needed" in _stage(claim, "reproducibility")["summary"]
    assert claim["operation_ids"] == ["op:distance"]
    assert claim["replay_status"] == "unverified"
    assert claim["status"] == "incomplete"


def test_source_presence_does_not_verify_replay(tmp_path):
    semantic = _package(tmp_path)
    semantic.evidence.append(
        Evidence(
            id="evidence:a",
            claim_ids=["claim:a"],
            source_artifact_ids=["native:a"],
            method_name="Author visual review",
            result_summary="Descriptive structure view.",
            **_review(),
        )
    )
    semantic.claims[0].evidence_ids = ["evidence:a"]
    audit = build_audit(tmp_path, semantic, _report())
    claim = audit["claims"][0]
    assert _stage(claim, "provenance")["status"] == "recorded"
    assert _stage(claim, "uncertainty")["status"] == "not_applicable"
    assert _stage(claim, "reproducibility")["status"] == "recorded"
    assert "Scene replay: pending verification in the original viewer" in _stage(claim, "reproducibility")["summary"]
    assert claim["replay_status"] == "unverified"
    assert "Scene replay: pending verification in the original viewer" in export_markdown(audit)
    assert "Scientific support: review the linked evidence" in export_markdown(audit)


@pytest.mark.parametrize(
    "thresholds,units,expected",
    [
        ({"distance": 4}, {}, "distance units"),
        ({}, {"distance": "angstrom"}, "a positive distance cutoff"),
        ({}, {}, "a positive distance cutoff and units"),
    ],
)
def test_contact_audit_identifies_the_specific_missing_field(tmp_path, thresholds, units, expected):
    semantic = _package(tmp_path)
    semantic.evidence.append(
        Evidence(
            id="evidence:contacts",
            claim_ids=["claim:a"],
            evidence_kind="contact_table",
            source_artifact_ids=["native:a"],
            method_name="Contact analysis",
            result_summary="Residue 42 is within the contact range.",
            thresholds=thresholds,
            units=units,
            **_review(),
        )
    )
    claim = build_audit(tmp_path, semantic, _report())["claims"][0]
    issue = next(item for item in claim["issues"] if item["section"] == "reproducibility")
    assert issue["message"] == f"Contact analysis needs {expected}."
    assert issue["fix"] == f"Edit the evidence to record {expected}."


def test_placeholder_camera_not_treated_as_captured_view(tmp_path):
    semantic = _package(tmp_path)
    semantic.scenes[0].camera = {"state": "unknown", "view": "TODO"}
    claim = build_audit(tmp_path, semantic, _report())["claims"][0]
    assert claim["camera_status"] == "not_recorded"
    assert _stage(claim, "reproducibility")["status"] == "missing"
    assert claim["replay_status"] == "unverified"


def test_camera_metadata_alone_is_not_view_parameters(tmp_path):
    semantic = _package(tmp_path)
    semantic.scenes[0].camera = {
        "molviewspec": {
            "params": {},
            "json_pointer": "/root/children/0",
            "source_path": "index.mvsj",
            "status": "statically_recorded_not_rendered",
        }
    }
    claim = build_audit(tmp_path, semantic, _report())["claims"][0]
    assert claim["camera_status"] == "not_recorded"
    semantic.scenes[0].camera["molviewspec"]["params"] = {"position": [0, 0, 0]}
    claim = build_audit(tmp_path, semantic, _report())["claims"][0]
    assert claim["camera_status"] == "recorded"


@pytest.mark.parametrize("view_kind", ["plot", "figure_assembly"])
def test_explicit_static_figure_tracks_sources_and_settings_without_molecular_replay(
    tmp_path, view_kind
):
    semantic = _package(tmp_path)
    for aid, path, role in (("panel", "plot.png", "render_image"), ("table", "values.csv", "generic")):
        (tmp_path / path).write_text("supplied figure data\n")
        semantic.artifacts.append(Artifact(id=aid, path=path, role=role))
    scene = semantic.scenes[0]
    scene.native_artifact_ids = []
    scene.render_artifact_ids = ["panel"]
    scene.extensions = {"view_kind": view_kind}
    scene.camera = {"author_context": "Time in ns; binary interaction states; frames 0–499."}
    semantic.evidence.append(Evidence(
        id="evidence:a", claim_ids=["claim:a"], source_artifact_ids=["table"],
        method_name="Adjacent-frame comparison", result_summary="Two state changes.",
        **_review(),
    ))
    audit = build_audit(tmp_path, semantic, _report())
    claim = audit["claims"][0]
    assert _stage(claim, "reproducibility")["status"] == "recorded"
    assert _stage(claim, "visual")["summary"] == "1 saved figure"
    assert claim["replay_status"] == claim["camera_status"] == "not_applicable"
    assert claim["view_context_status"] == "recorded"
    assert audit["summary"]["replay_status"] == "not_applicable"
    assert "pending verification in the original viewer" not in export_markdown(audit)
    assert "Package validation is reported separately" in export_markdown(audit)

    scene.camera = {"set_view": "1,0,0"}
    missing_settings = build_audit(tmp_path, semantic, _report())["claims"][0]
    assert missing_settings["view_context_status"] == "not_recorded"
    assert "analysis or assembly settings" in _stage(missing_settings, "reproducibility")["summary"]

    scene.camera = {"author_context": "Time in ns; binary interaction states; frames 0–499."}
    (tmp_path / "values.csv").unlink()
    missing_source = build_audit(tmp_path, semantic, _report())["claims"][0]
    assert _stage(missing_source, "reproducibility")["status"] == "missing"
    assert "source files" in _stage(missing_source, "reproducibility")["summary"]

    (tmp_path / "plot.png").unlink()
    missing_figure = build_audit(tmp_path, semantic, _report())["claims"][0]
    assert "attach the saved figure" in _stage(missing_figure, "reproducibility")["summary"]


def test_image_only_view_keeps_molecular_replay_requirement_without_explicit_static_kind(tmp_path):
    semantic = _package(tmp_path)
    scene = semantic.scenes[0]
    scene.native_artifact_ids = []
    scene.camera = {"author_context": "The ligand is shown from above."}
    scene.render_artifact_ids = ["panel"]
    (tmp_path / "panel.png").write_text("figure")
    semantic.artifacts.append(Artifact(id="panel", path="panel.png", role="render_image"))
    claim = build_audit(tmp_path, semantic, _report())["claims"][0]
    assert claim["replay_status"] == "unverified"
    assert "attach the saved scene file" in _stage(claim, "reproducibility")["summary"]


def test_plot_and_molecular_scene_keep_their_distinct_replay_requirements(tmp_path):
    semantic = _package(tmp_path)
    (tmp_path / "plot.png").write_text("figure")
    semantic.artifacts.append(Artifact(id="panel", path="plot.png", role="render_image"))
    semantic.scenes.append(Scene(
        id="scene:plot", render_artifact_ids=["panel"], extensions={"view_kind": "plot"},
        camera={"author_context": "Contact counts versus frame index; all 500 frames."},
    ))
    semantic.claims[0].scene_ids.append("scene:plot")
    semantic.evidence.append(Evidence(
        id="evidence:a", claim_ids=["claim:a"], source_artifact_ids=["native:a"],
        method_name="Compare displayed contexts", result_summary="Both views use the same site.",
        **_review(),
    ))
    claim = build_audit(tmp_path, semantic, _report())["claims"][0]
    assert claim["replay_status"] == "unverified"
    assert claim["camera_status"] == claim["view_context_status"] == "recorded"
    assert _stage(claim, "reproducibility")["status"] == "recorded"

    semantic.scenes[0].native_artifact_ids = []
    claim = build_audit(tmp_path, semantic, _report())["claims"][0]
    assert "attach the saved scene file" in _stage(claim, "reproducibility")["summary"]
    assert claim["replay_status"] == "unverified"


def test_distance_source_and_units_need_a_measured_value(tmp_path):
    semantic = _package(tmp_path)
    semantic.claims[0].claim_type = "ligand_binding_pose"
    semantic.evidence.append(
        Evidence(
            id="evidence:a",
            claim_ids=["claim:a"],
            source_artifact_ids=["native:a"],
            evidence_kind="measurement",
            method_name="Distance analysis",
            result_summary="A distance was recorded.",
            units={"distance": "angstrom"},
            **_review(),
        )
    )
    semantic.uncertainty.append(
        Uncertainty(
            id="uncertainty:a",
            claim_ids=["claim:a"],
            statement="Alternative poses not assessed.",
            **_review(),
        )
    )
    claim = build_audit(tmp_path, semantic, _report())["claims"][0]
    assert _stage(claim, "uncertainty")["status"] == "recorded"
    assert any("a measured distance" in item["message"] for item in claim["issues"])
    semantic.evidence[-1].parameters["measured_distance"] = 3.0
    claim = build_audit(tmp_path, semantic, _report())["claims"][0]
    assert not any("measured distance" in item["message"] or "cutoff" in item["message"] for item in claim["issues"])


def test_mvs_snapshots_do_not_borrow_operations(tmp_path):
    semantic = _package(tmp_path)
    semantic.scenes[0].extensions = {"molviewspec_root": {"json_pointer": "/snapshots/0/root"}}
    semantic.scenes.append(
        Scene(
            id="scene:b",
            native_artifact_ids=["native:a"],
            extensions={"molviewspec_root": {"json_pointer": "/snapshots/1/root"}},
        )
    )
    for index in (0, 1):
        semantic.observed_scene_operations.append(
            ObservedSceneOperation(
                operation_id=f"op:{index}",
                operation="colored",
                source_location={
                    "artifact_id": "native:a",
                    "json_pointer": f"/snapshots/{index}/root/children/0",
                },
            )
        )
        (tmp_path / f"model{index}.cif").write_text("data_test\n", encoding="utf-8")
        semantic.artifacts.append(
            Artifact(id=f"model:{index}", role="structure", path=f"model{index}.cif")
        )
        semantic.resource_references.append(
            ResourceReference(
                resource_ref_id=f"resource:{index}",
                artifact_id="native:a",
                uri=f"model{index}.cif",
                uri_kind="relative",
                source_location={
                    "artifact_id": "native:a",
                    "json_pointer": f"/snapshots/{index}/root/children/0",
                },
            )
        )
    claim = build_audit(tmp_path, semantic, _report())["claims"][0]
    assert claim["operation_ids"] == ["op:0"]
    assert claim["resource_ref_ids"] == ["resource:0"]
    assert claim["resource_artifact_ids"] == {"resource:0": ["model:0"]}
    assert "model:0" in claim["artifact_ids"]
    assert "model:1" not in claim["artifact_ids"]


def test_native_owner_is_not_mistaken_for_referenced_structure(tmp_path):
    scene = tmp_path / "scene.pml"
    scene.write_text("load model.cif, complex\n", encoding="utf-8")
    package = init_package(native=scene, out=tmp_path / "package")
    package.add_claim("The structure is shown.", "simple_structure_view", "Figure A")
    resource = package.semantic_layer.resource_references[0]
    assert resource.artifact_id == package.semantic_layer.scenes[0].native_artifact_ids[0]
    before = build_audit(package.root, package.semantic_layer, package.validate())["claims"][0]
    assert before["unresolved_resource_ids"] == [resource.resource_ref_id]
    assert before["resource_artifact_ids"][resource.resource_ref_id] == []

    model = tmp_path / "model.cif"
    model.write_text("data_test\n", encoding="utf-8")
    attached = package.add_artifact(model, role="structure")
    after = build_audit(package.root, package.semantic_layer, package.validate())["claims"][0]
    assert after["unresolved_resource_ids"] == []
    assert after["resource_artifact_ids"][resource.resource_ref_id] == [attached.id]
    assert attached.id in after["artifact_ids"]
    assert after["replay_status"] == "unverified"


def test_missing_resource_and_invalid_path_are_visible_without_opening(tmp_path):
    semantic = _package(tmp_path)
    semantic.artifacts.append(Artifact(id="structure:a", role="structure", path="../private.cif"))
    semantic.resource_references.append(
        ResourceReference(
            resource_ref_id="resource:a",
            uri="model.cif",
            uri_kind="relative",
            artifact_id="structure:a",
            source_location={"artifact_id": "native:a"},
        )
    )
    claim = build_audit(tmp_path, semantic, _report())["claims"][0]
    assert "1 scene source file to attach" in _stage(claim, "reproducibility")["summary"]


def test_nonblocking_warning_and_waiver_are_not_validation_blockers(tmp_path):
    semantic = _package(tmp_path)
    warning = ValidationFinding(
        rule_id="CLAIM.UNCERTAINTY.MISSING",
        gate="G4",
        validation_level="L3",
        severity="WARNING",
        finding_class="EVIDENCE_LIMITATION_WARNING",
        status="FAIL",
        message="Caveat absent.",
        json_pointer="/claims/0/uncertainty_ids",
        blocks_modes=["archive"],
    )
    waived = warning.model_copy(
        update={"rule_id": "CLAIM.BASIC.EVIDENCE", "severity": "ERROR", "status": "WAIVED"}
    )
    claim = build_audit(tmp_path, semantic, _report(warning, waived))["claims"][0]
    assert claim["validation_blockers"] == 0
    assert all(not item["blocking"] for item in claim["issues"])


@pytest.mark.parametrize("mode", ["draft", "internal"])
def test_trajectory_context_question_stays_visible_in_audit_when_export_is_allowed(tmp_path, mode):
    semantic = _package(tmp_path)
    semantic.claims[0].claim_type = "trajectory_mechanism"
    (tmp_path / "events.csv").write_text("frame,state\n0,1\n")
    semantic.artifacts.append(Artifact(id="table:events", path="events.csv", role="contact_table"))
    semantic.evidence.append(Evidence(
        id="evidence:events", claim_ids=["claim:a"], evidence_kind="trajectory_analysis",
        source_artifact_ids=["table:events"], method_name="Count supplied event states",
        result_summary="One sampled state is present.", **_review(),
    ))
    semantic.claims[0].evidence_ids = ["evidence:events"]
    finding = ValidationFinding(
        rule_id="CLAIM.TRAJECTORY.REQUIRED_CONTEXT", gate="G4B_EVIDENCE_MINIMUMS",
        validation_level="L3_CLAIM_EVIDENCE", severity="ERROR", finding_class="CLAIM_EVIDENCE_ERROR",
        status="FAIL", message="Trajectory and topology files are required for the mechanism claim.",
        json_pointer="/claims/0/evidence_ids", blocks_modes=["share", "archive"],
    )
    before = build_audit(tmp_path, semantic, _report(mode=mode))["claims"][0]
    assert _stage(before, "provenance")["status"] == "recorded"
    claim = build_audit(tmp_path, semantic, _report(finding, mode=mode))["claims"][0]
    assert claim["validation_blockers"] == 0
    assert _stage(claim, "provenance")["status"] == "review"
    assert _stage(claim, "provenance")["summary"] == finding.message

    from claimtrace.workflow import build_workflow

    report = _report(finding, mode=mode)
    workflow = build_workflow(semantic, report, build_audit(tmp_path, semantic, report))
    task = next(item for item in workflow["tasks"] if finding.rule_id in item["rule_ids"])
    assert task["action"] == "attach"
    assert "topology" in task["title"] and "trajectory" in task["title"]
    assert task["claim_id"] == "claim:a"
    assert "link them to the analysis evidence" in task["detail"]
    assert not task["blocking"]
    assert all(item["title"] != "Which file contains this supporting result?" for item in workflow["tasks"])


def test_markdown_keeps_priority_items_short_and_preserves_trace(tmp_path):
    semantic = _package(tmp_path)
    audit = build_audit(tmp_path, semantic, _report())
    claim = audit["claims"][0]
    claim["issues"] = [
        {
            "message": f"Rule finding {i}.",
            "fix": "Review the record.",
            "section": "claim",
            "status": "FAIL",
            "blocking": True,
        }
        for i in range(6)
    ]
    claim["issues"].append(
        {
            "message": "Cutoff is missing.",
            "fix": "Record cutoff and units.",
            "section": "reproducibility",
            "status": "FAIL",
            "blocking": False,
            "origin": "audit_context",
        }
    )
    claim["issues"].append(
        {
            "message": "Waived rule.",
            "fix": "",
            "section": "claim",
            "status": "WAIVED",
            "blocking": False,
        }
    )
    text = export_markdown(audit)
    assert text.count("- Review:") + text.count("- Blocking:") == 3
    assert "Cutoff is missing" in text
    assert "Sources: a.pml." in text
    assert claim["artifact_ids"] == ["native:a"]
    assert "4 more open items; 1 waived" in text
    assert "Full findings: JSON audit" in text
    assert len(claim["issues"]) == 8
