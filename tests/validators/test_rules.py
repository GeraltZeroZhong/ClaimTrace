import json
import zipfile
from pathlib import Path

from PIL import Image

from claimtrace import _simple_yaml
from claimtrace.api import init_package
from claimtrace.completion import apply_answers, check_answers
from claimtrace.models import Artifact, Entity, Evidence, EvidenceBinding
from claimtrace.models.semantic_layer import (
    ArtifactKind,
    ArtifactRole,
    EvidenceKind,
    ReviewStatus,
    Waiver,
)
from claimtrace.package.checksums import file_size, sha256_file, write_sha256_txt
from claimtrace.package.layout import write_json, write_semantic_layer
from claimtrace.validation.engine import validate_package


def write_png(path: Path) -> None:
    Image.new("RGB", (2, 2), color=(32, 96, 160)).save(path, format="PNG")


def test_ligand_claim_missing_contacts_fails_archive(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("select ligand, resn LIG\nshow sticks, ligand\n", encoding="utf-8")
    image = tmp_path / "figure.png"
    write_png(image)
    pkg = init_package(native=pml, image=image, out=tmp_path / "pkg")
    pkg.add_claim("Ligand occupies pocket.", "ligand_binding_pose", "Figure 1A")
    pkg.save()

    report = validate_package(pkg.root, mode="archive")

    assert report.overall_status == "fail"
    assert any(item.rule_id == "CLAIM.LIGAND.REQUIRED_CONTACTS" for item in report.findings)


def test_simple_structure_view_without_structure_fails_archive(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("show cartoon\n", encoding="utf-8")
    image = tmp_path / "figure.png"
    write_png(image)
    pkg = init_package(native=pml, image=image, out=tmp_path / "pkg")
    pkg.add_claim("Figure shows a structure.", "simple_structure_view", "Figure 1A")
    pkg.save()

    report = validate_package(pkg.root, mode="archive")

    assert report.overall_status == "fail"
    assert any(item.rule_id == "CLAIM.SIMPLE.REQUIRED_STRUCTURE" for item in report.findings)


def test_warning_rules_do_not_declare_blocking_modes():
    rules = _simple_yaml.loads(Path("src/claimtrace/resources/validation/rules.yaml").read_text(encoding="utf-8"))

    offenders = [
        rule["rule_id"]
        for rule in rules
        if rule.get("severity") == "WARNING" and rule.get("blocks_modes")
    ]

    assert offenders == []


def test_missing_mvsx_member_uses_specific_validation_rule(tmp_path: Path):
    scene = {
        "metadata": {"version": "1"},
        "root": {
            "kind": "root",
            "children": [{"kind": "download", "params": {"url": "data/missing.cif"}}],
        },
    }
    archive = tmp_path / "scene.mvsx"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("index.mvsj", json.dumps(scene))
    pkg = init_package(native=archive, out=tmp_path / "pkg")

    report = validate_package(pkg.root, mode="archive")

    missing = [item for item in report.findings if "missing from the MVSX archive" in item.message]
    assert [item.rule_id for item in missing] == ["IMPORT.MVSX.MEMBER_MISSING"]


def test_tool_suggested_visual_encoding_requires_archive_triage(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text(
        "select ligand, resn LIG\ncolor magenta, ligand\nlabel ligand, name\n"
        "set_view (1,0,0,0,1,0,0,0,1,0,0,-10,0,0,0,1,20,-10)\n",
        encoding="utf-8",
    )
    model = tmp_path / "model.cif"
    model.write_text("data_model\n", encoding="utf-8")
    image = tmp_path / "figure.png"
    write_png(image)
    pkg = init_package(native=pml, image=image, out=tmp_path / "pkg")
    pkg.add_artifact(model, role="structure")
    answers = {
        "claim": {
            "claim_text": "Figure shows a ligand-highlighted structure.",
            "claim_type": "simple_structure_view",
            "figure_ref": "Figure 1A",
        },
        "evidence": [
            {
                "evidence_kind": "manual_rationale",
                "method_name": "Author visual review",
                "result_summary": "Native scene and structure file were reviewed together.",
                "source_artifact_roles": ["native_script", "structure"],
            }
        ],
        "reuse": {"license": "unknown"},
    }
    apply_answers(pkg.root, pkg.semantic_layer, answers, answer_base=tmp_path)
    write_semantic_layer(pkg.root, pkg.semantic_layer)

    report = validate_package(pkg.root, mode="archive")

    assert report.overall_status == "fail"
    assert any(item.rule_id == "SCENE.VISUAL_ENCODING.MEANING_MISSING" for item in report.findings)

    triaged_answers = {
        **answers,
        "answer_schema": "claimtrace.native_scene_answers.v1",
        "scene_semantics_by_operation": [
            {
                "operation_ids": [operation.operation_id],
                "encoding_type": operation.operation,
                "meaning_status": "tool_suggested_meaning",
                "claim_critical": "false",
            }
            for operation in pkg.semantic_layer.observed_scene_operations
            if operation.candidate_meaning
        ],
    }
    problems = check_answers(triaged_answers, pkg.semantic_layer, root=pkg.root, answer_base=tmp_path)
    assert problems == []
    apply_answers(pkg.root, pkg.semantic_layer, triaged_answers, answer_base=tmp_path)
    write_semantic_layer(pkg.root, pkg.semantic_layer)

    report = validate_package(pkg.root, mode="archive")

    assert report.overall_status == "pass"
    assert not any(item.rule_id == "SCENE.VISUAL_ENCODING.MEANING_MISSING" for item in report.findings)


def test_non_scientific_global_color_suggestion_does_not_block_archive(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text(
        "color cyan, all\nset_view (1,0,0,0,1,0,0,0,1,0,0,-10,0,0,0,1,20,-10)\n",
        encoding="utf-8",
    )
    model = tmp_path / "model.cif"
    model.write_text("data_model\n", encoding="utf-8")
    image = tmp_path / "figure.png"
    write_png(image)
    pkg = init_package(native=pml, image=image, out=tmp_path / "pkg")
    pkg.add_artifact(model, role="structure")
    answers = {
        "claim": {
            "claim_text": "Figure shows a structure.",
            "claim_type": "simple_structure_view",
            "figure_ref": "Figure 1A",
        },
        "evidence": [
            {
                "evidence_kind": "manual_rationale",
                "result_summary": "Native scene and structure file were reviewed together.",
                "source_artifact_roles": ["native_script", "structure"],
            }
        ],
        "reuse": {"license": "unknown"},
    }
    apply_answers(pkg.root, pkg.semantic_layer, answers, answer_base=tmp_path)
    write_semantic_layer(pkg.root, pkg.semantic_layer)

    report = validate_package(pkg.root, mode="archive")

    assert report.overall_status == "pass"
    assert not any(item.rule_id == "SCENE.VISUAL_ENCODING.MEANING_MISSING" for item in report.findings)


def test_check_answers_validates_native_scene_fields_without_schema(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("color magenta, ligand\n", encoding="utf-8")
    pkg = init_package(native=pml, out=tmp_path / "pkg")
    answers = {
        "claim": {"claim_text": "test", "claim_type": "simple_structure_view", "figure_ref": "Figure 1A"},
        "evidence": [{"evidence_kind": "manual_rationale", "result_summary": "test"}],
        "reuse": {"license": "unknown"},
        "scene_semantics_by_operation": [
            {
                "operation_ids": ["op:does-not-exist"],
                "encoding_type": "colored",
                "meaning_status": "user_confirmed_meaning",
                "meaning": "test",
            }
        ],
    }

    problems = check_answers(answers, pkg.semantic_layer, root=pkg.root, answer_base=tmp_path)

    assert any("unknown operation_id" in problem for problem in problems)


def test_selection_highlight_requires_selection_entity_mapping(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("select active_site, chain A and resi 10\nshow sticks, active_site\n", encoding="utf-8")
    model = tmp_path / "model.cif"
    model.write_text("data_model\n", encoding="utf-8")
    pkg = init_package(native=pml, out=tmp_path / "pkg")
    pkg.add_artifact(model, role="structure")
    answers = {
        "claim": {
            "claim_text": "Figure highlights the active-site residue.",
            "claim_type": "selection_highlight",
            "figure_ref": "Figure 1A",
        },
        "evidence": [
            {
                "evidence_kind": "manual_rationale",
                "result_summary": "Native scene and structure file were reviewed together.",
                "source_artifact_roles": ["native_script", "structure"],
            }
        ],
        "reuse": {"license": "unknown"},
    }
    apply_answers(pkg.root, pkg.semantic_layer, answers, answer_base=tmp_path)
    write_semantic_layer(pkg.root, pkg.semantic_layer)

    report = validate_package(pkg.root, mode="archive")

    assert report.overall_status == "fail"
    assert any(item.rule_id == "CLAIM.SELECTION.IDENTITY_MISSING" for item in report.findings)

    placeholder = Entity(id="entity:placeholder")
    pkg.semantic_layer.entities.append(placeholder)
    pkg.semantic_layer.selections[0].entity_ids = [placeholder.id]
    pkg.save()

    report = validate_package(pkg.root, mode="archive")
    assert any(item.rule_id == "CLAIM.SELECTION.IDENTITY_MISSING" for item in report.findings)


def test_ligand_measurement_needs_structured_context(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("select ligand, resn LIG\nshow sticks, ligand\n", encoding="utf-8")
    model = tmp_path / "model.cif"
    model.write_text("data_model\n", encoding="utf-8")
    pkg = init_package(native=pml, out=tmp_path / "pkg")
    pkg.add_artifact(model, role="structure")
    answers = {
        "claim": {
            "claim_text": "Ligand occupies the example pocket.",
            "claim_type": "ligand_binding_pose",
            "figure_ref": "Figure 2A",
        },
        "evidence": [
            {
                "evidence_kind": "measurement",
                "method_name": "Native distance intent",
                "result_summary": "A distance command exists in the native script.",
                "source_artifact_roles": ["native_script"],
            }
        ],
        "reuse": {"license": "unknown"},
    }
    apply_answers(pkg.root, pkg.semantic_layer, answers, answer_base=tmp_path)
    write_semantic_layer(pkg.root, pkg.semantic_layer)

    report = validate_package(pkg.root, mode="archive")

    assert report.overall_status == "fail"
    assert any(item.rule_id == "CLAIM.LIGAND.REQUIRED_CONTACTS" for item in report.findings)


def test_validate_reports_non_object_semantic_json(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "semantic_layer.json").write_text("[]", encoding="utf-8")

    report = validate_package(package, mode="archive")

    assert report.overall_status == "fail"
    assert any(item.rule_id == "G1.SCHEMA" for item in report.findings)


def test_export_checksum_manifest_detects_semantic_layer_tampering(tmp_path: Path):
    pkg = init_package(blank=True, out=tmp_path / "pkg")
    write_sha256_txt(pkg.root)
    semantic_path = pkg.root / "semantic_layer.json"
    semantic_path.write_text(semantic_path.read_text(encoding="utf-8").replace("Untitled", "Tampered"), encoding="utf-8")

    report = validate_package(pkg.root, mode="draft")

    assert report.overall_status == "fail"
    assert any(item.rule_id == "G2.FIXITY.MANIFEST_HASH_MISMATCH" for item in report.findings)


def test_validation_report_inside_working_package_does_not_imply_export(tmp_path: Path):
    pkg = init_package(blank=True, out=tmp_path / "pkg")
    write_json(pkg.root / "validation_report.json", {"overall_status": "pass"})

    report = validate_package(pkg.root, mode="draft")

    assert not any(item.rule_id == "G2.FIXITY.MANIFEST_MISSING" for item in report.findings)


def test_dangling_evidence_binding_fails_reference_gate(tmp_path: Path):
    pkg = init_package(blank=True, out=tmp_path / "pkg")
    pkg.semantic_layer.evidence_bindings.append(
        EvidenceBinding(
            binding_id="binding:dangling",
            claim_id="claim:missing",
            operation_ids=["op:missing"],
            resource_ref_ids=["resource:missing"],
            evidence_artifact_ids=["artifact:missing"],
            evidence_type="contact_table",
        )
    )
    pkg.save()

    report = validate_package(pkg.root, mode="draft")

    missing = [item for item in report.findings if item.rule_id == "G3.REFERENCE.MISSING"]
    assert len(missing) == 4
    assert report.overall_status == "fail"


def test_empty_contact_table_metadata_does_not_satisfy_ligand_gate(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("select ligand, resn LIG\n", encoding="utf-8")
    structure = tmp_path / "model.cif"
    structure.write_text("data_model\n", encoding="utf-8")
    contacts = tmp_path / "contacts_irrelevant.csv"
    contacts.write_text("note\nnot_a_molecular_contact\n", encoding="utf-8")
    pkg = init_package(native=pml, artifacts=[structure, contacts], out=tmp_path / "pkg")
    answers = {
        "claim": {
            "claim_text": "Ligand occupies the pocket.",
            "claim_type": "ligand_binding_pose",
            "figure_ref": "Figure 1A",
        },
        "evidence": [
            {
                "evidence_kind": "contact_table",
                "method_name": "Unspecified",
                "result_summary": "A file was attached.",
                "source_artifact_roles": ["structure", "contact_table"],
            }
        ],
        "reuse": {"license": "unknown"},
    }
    apply_answers(pkg.root, pkg.semantic_layer, answers, answer_base=tmp_path)
    pkg.save()

    report = validate_package(pkg.root, mode="archive")

    assert any(item.rule_id == "CLAIM.LIGAND.REQUIRED_CONTACTS" for item in report.findings)


def test_trajectory_claim_requires_trajectory_topology_and_analysis(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("show cartoon\n", encoding="utf-8")
    pkg = init_package(native=pml, out=tmp_path / "pkg")
    pkg.add_claim("The trajectory demonstrates a mechanism.", "trajectory_mechanism", "Figure 3A")
    pkg.save()

    report = validate_package(pkg.root, mode="archive")

    assert any(item.rule_id == "CLAIM.TRAJECTORY.REQUIRED_CONTEXT" for item in report.findings)


def test_density_claim_requires_map_and_parameterized_fit_evidence(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("show cartoon\n", encoding="utf-8")
    pkg = init_package(native=pml, out=tmp_path / "pkg")
    pkg.add_claim("The model is supported by cryo-EM density.", "cryo_em_map_fit", "Figure 4A")
    pkg.save()

    report = validate_package(pkg.root, mode="archive")

    assert any(item.rule_id == "CLAIM.DENSITY.REQUIRED_CONTEXT" for item in report.findings)


def test_evidence_links_must_be_bidirectional(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("show cartoon\n", encoding="utf-8")
    pkg = init_package(native=pml, out=tmp_path / "pkg")
    claim = pkg.add_claim("Figure shows a structure.", "simple_structure_view", "Figure 1A")
    evidence = Evidence(
        id="evidence:one-way",
        evidence_kind=EvidenceKind.manual_rationale,
        claim_ids=[],
        source_artifact_ids=[pkg.semantic_layer.artifacts[0].id],
        method_name="Author review",
        result_summary="The native scene was inspected.",
        review_status=ReviewStatus.confirmed,
    )
    pkg.semantic_layer.evidence.append(evidence)
    claim.evidence_ids = [evidence.id]
    pkg.save()

    report = validate_package(pkg.root, mode="draft")

    assert report.overall_status == "fail"
    assert any(item.rule_id == "G3.REFERENCE.INCONSISTENT" for item in report.findings)


def test_trajectory_analysis_needs_frame_and_replicate_context(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("show cartoon\n", encoding="utf-8")
    trajectory = tmp_path / "run.xtc"
    trajectory.write_bytes(b"trajectory")
    topology = tmp_path / "topology.pdb"
    topology.write_text("END\n", encoding="utf-8")
    analysis = tmp_path / "analysis.txt"
    analysis.write_text("RMSD summary\n", encoding="utf-8")
    pkg = init_package(native=pml, out=tmp_path / "pkg")
    trajectory_artifact = pkg.add_artifact(trajectory, role="trajectory")
    topology_artifact = pkg.add_artifact(topology, role="topology")
    analysis_artifact = pkg.add_artifact(analysis, role="evidence_document")
    answers = {
        "claim": {
            "claim_text": "The trajectory supports a conformational mechanism.",
            "claim_type": "trajectory_mechanism",
            "figure_ref": "Figure 3A",
        },
        "evidence": [
            {
                "evidence_kind": "trajectory_analysis",
                "method_name": "Backbone RMSD",
                "parameters": {"frame_selection": "every 10th frame"},
                "result_summary": "The selected frames were compared by RMSD.",
                "source_artifact_ids": [
                    trajectory_artifact.id,
                    topology_artifact.id,
                    analysis_artifact.id,
                ],
            }
        ],
        "reuse": {"license": "unknown"},
    }
    apply_answers(pkg.root, pkg.semantic_layer, answers, answer_base=tmp_path)
    pkg.save()

    report = validate_package(pkg.root, mode="archive")

    assert any(item.rule_id == "CLAIM.TRAJECTORY.REQUIRED_CONTEXT" for item in report.findings)


def test_trajectory_context_rejects_empty_parameter_values(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("show cartoon\n", encoding="utf-8")
    trajectory = tmp_path / "run.xtc"
    trajectory.write_bytes(b"trajectory")
    topology = tmp_path / "topology.pdb"
    topology.write_text("END\n", encoding="utf-8")
    pkg = init_package(native=pml, out=tmp_path / "pkg")
    trajectory_artifact = pkg.add_artifact(trajectory, role="trajectory")
    topology_artifact = pkg.add_artifact(topology, role="topology")
    answers = {
        "claim": {
            "claim_text": "The trajectory supports a conformational mechanism.",
            "claim_type": "trajectory_mechanism",
            "figure_ref": "Figure 3A",
        },
        "evidence": [
            {
                "evidence_kind": "trajectory_analysis",
                "method_name": "Backbone RMSD",
                "parameters": {"frame_selection": None, "replicate_count": ""},
                "result_summary": "Frames were compared by RMSD.",
                "source_artifact_ids": [trajectory_artifact.id, topology_artifact.id],
            }
        ],
        "reuse": {"license": "unknown"},
    }
    apply_answers(pkg.root, pkg.semantic_layer, answers, answer_base=tmp_path)
    pkg.save()

    report = validate_package(pkg.root, mode="archive")

    assert any(item.rule_id == "CLAIM.TRAJECTORY.REQUIRED_CONTEXT" for item in report.findings)


def test_density_evidence_must_link_map_and_fitted_structure(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("show cartoon\n", encoding="utf-8")
    map_file = tmp_path / "density.mrc"
    map_file.write_bytes(b"map")
    structure = tmp_path / "model.cif"
    structure.write_text("data_model\n", encoding="utf-8")
    pkg = init_package(native=pml, out=tmp_path / "pkg")
    map_artifact = pkg.add_artifact(map_file, role="map")
    pkg.add_artifact(structure, role="structure")
    answers = {
        "claim": {
            "claim_text": "The model is supported by the displayed density.",
            "claim_type": "cryo_em_map_fit",
            "figure_ref": "Figure 4A",
        },
        "evidence": [
            {
                "evidence_kind": "density_support",
                "method_name": "Contour inspection",
                "parameters": {"contour_sigma": 1.5},
                "result_summary": "Density was displayed at the stated contour.",
                "source_artifact_ids": [map_artifact.id],
            }
        ],
        "reuse": {"license": "unknown"},
    }
    apply_answers(pkg.root, pkg.semantic_layer, answers, answer_base=tmp_path)
    pkg.save()

    report = validate_package(pkg.root, mode="archive")

    assert any(item.rule_id == "CLAIM.DENSITY.REQUIRED_CONTEXT" for item in report.findings)


def test_density_context_rejects_empty_or_unrelated_parameters(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("show cartoon\n", encoding="utf-8")
    map_file = tmp_path / "density.mrc"
    map_file.write_bytes(b"map")
    structure = tmp_path / "model.cif"
    structure.write_text("data_model\n", encoding="utf-8")
    pkg = init_package(native=pml, out=tmp_path / "pkg")
    map_artifact = pkg.add_artifact(map_file, role="map")
    structure_artifact = pkg.add_artifact(structure, role="structure")
    answers = {
        "claim": {
            "claim_text": "The model is supported by the displayed density.",
            "claim_type": "cryo_em_map_fit",
            "figure_ref": "Figure 4A",
        },
        "evidence": [
            {
                "evidence_kind": "density_support",
                "method_name": "Contour inspection",
                "parameters": {"unrelated": "", "contour_sigma": None},
                "result_summary": "The map and structure were reviewed together.",
                "source_artifact_ids": [map_artifact.id, structure_artifact.id],
            }
        ],
        "reuse": {"license": "unknown"},
    }
    apply_answers(pkg.root, pkg.semantic_layer, answers, answer_base=tmp_path)
    pkg.save()

    report = validate_package(pkg.root, mode="archive")

    assert any(item.rule_id == "CLAIM.DENSITY.REQUIRED_CONTEXT" for item in report.findings)


def test_anchor_waiver_does_not_waive_other_findings_with_same_rule(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("unknown_one alpha\nunknown_two beta\n", encoding="utf-8")
    pkg = init_package(native=pml, out=tmp_path / "pkg")
    first_raw = pkg.semantic_layer.raw_native_observations[0]
    pkg.semantic_layer.provenance.waivers.append(
        Waiver(
            rule_id="IMPORT.PYMOL.RAW_AFFECTS_SCENE",
            scope=first_raw.raw_id,
            anchor_id=first_raw.raw_id,
            reason="Reviewed the first item only.",
            reviewer="author",
            max_export_mode="archive",
        )
    )
    pkg.save()

    report = validate_package(pkg.root, mode="archive")
    raw_findings = [
        item for item in report.findings if item.rule_id == "IMPORT.PYMOL.RAW_AFFECTS_SCENE"
    ]

    assert [item.status for item in raw_findings] == ["WAIVED", "FAIL"]


def test_computed_model_validation_must_be_linked_to_the_claim(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("show cartoon\n", encoding="utf-8")
    structure = tmp_path / "prediction.cif"
    structure.write_text("data_prediction\n", encoding="utf-8")
    report_file = tmp_path / "validation.pdf"
    report_file.write_bytes(b"validation")
    pkg = init_package(native=pml, out=tmp_path / "pkg")
    structure_artifact = pkg.add_artifact(structure, role="structure")
    pkg.add_artifact(report_file, role="validation_report")
    answers = {
        "claim": {
            "claim_text": "The computed model has high confidence in the core.",
            "claim_type": "computed_model_claim",
            "figure_ref": "Figure 5A",
        },
        "evidence": [
            {
                "evidence_kind": "external_validation",
                "method_name": "Confidence review",
                "result_summary": "The model was reviewed, but the report is not linked here.",
                "source_artifact_ids": [structure_artifact.id],
            }
        ],
        "reuse": {"license": "unknown"},
    }
    apply_answers(pkg.root, pkg.semantic_layer, answers, answer_base=tmp_path)
    pkg.save()

    report = validate_package(pkg.root, mode="archive")

    assert any(item.rule_id == "CLAIM.COMPUTED_MODEL.REQUIRED_VALIDATION" for item in report.findings)


def test_model_comparison_evidence_must_link_both_structures(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("show cartoon\n", encoding="utf-8")
    model_a = tmp_path / "model_a.cif"
    model_b = tmp_path / "model_b.cif"
    comparison = tmp_path / "comparison.txt"
    model_a.write_text("data_a\n", encoding="utf-8")
    model_b.write_text("data_b\n", encoding="utf-8")
    comparison.write_text("comparison\n", encoding="utf-8")
    pkg = init_package(native=pml, out=tmp_path / "pkg")
    pkg.add_artifact(model_a, role="structure")
    pkg.add_artifact(model_b, role="structure")
    comparison_artifact = pkg.add_artifact(comparison, role="evidence_document")
    answers = {
        "claim": {
            "claim_text": "The two models differ in the highlighted region.",
            "claim_type": "model_comparison",
            "figure_ref": "Figure 6A",
        },
        "evidence": [
            {
                "evidence_kind": "external_validation",
                "method_name": "Structural superposition",
                "result_summary": "A comparison note was attached without both model links.",
                "source_artifact_ids": [
                    pkg.semantic_layer.artifacts[0].id,
                    comparison_artifact.id,
                ],
            }
        ],
        "reuse": {"license": "unknown"},
    }
    apply_answers(pkg.root, pkg.semantic_layer, answers, answer_base=tmp_path)
    pkg.save()

    report = validate_package(pkg.root, mode="archive")

    assert any(item.rule_id == "CLAIM.MODEL_COMPARISON.REQUIRED_CONTEXT" for item in report.findings)


def test_duplicate_artifact_ids_are_reported_as_integrity_error(tmp_path: Path):
    first = tmp_path / "a.cif"
    second = tmp_path / "b.cif"
    first.write_text("data_a\n", encoding="utf-8")
    second.write_text("data_b\n", encoding="utf-8")
    pkg = init_package(artifacts=[first, second], out=tmp_path / "pkg")
    pkg.semantic_layer.artifacts[1].id = pkg.semantic_layer.artifacts[0].id
    pkg.save()

    report = validate_package(pkg.root, mode="draft")

    assert any(item.rule_id == "G3.REFERENCE.DUPLICATE_ARTIFACT_ID" for item in report.findings)


def test_unreviewed_claim_text_cannot_pass_archive_attribution(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("show cartoon\n", encoding="utf-8")
    pkg = init_package(native=pml, out=tmp_path / "pkg")
    claim = pkg.add_claim("Figure shows a structure.", "simple_structure_view", "Figure 1A")
    claim.review_status = ReviewStatus.needs_review
    claim.claim_text.review_status = ReviewStatus.needs_review
    claim.claim_text.reviewer = None
    claim.claim_text.reviewed_at = None
    pkg.save()

    report = validate_package(pkg.root, mode="archive")

    assert any(item.rule_id == "CLAIM.BASIC.AUTHOR_REVIEW" for item in report.findings)


def test_render_content_is_validated_even_when_fixity_matches(tmp_path: Path):
    image = tmp_path / "figure.png"
    write_png(image)
    pkg = init_package(image=image, out=tmp_path / "pkg")
    artifact = pkg.semantic_layer.artifacts[0]
    packaged = pkg.root / str(artifact.path)
    packaged.write_bytes(b"not a real image")
    artifact.sha256 = sha256_file(packaged)
    artifact.byte_size = file_size(packaged)
    pkg.save()

    report = validate_package(pkg.root, mode="archive")

    assert any(item.rule_id == "G2.RENDER.INVALID_IMAGE" for item in report.findings)


def test_remote_resource_status_string_does_not_replace_fixity(tmp_path: Path):
    scene = tmp_path / "remote.mvsj"
    scene.write_text(
        json.dumps(
            {
                "metadata": {"version": "1"},
                "root": {
                    "kind": "root",
                    "children": [
                        {
                            "kind": "download",
                            "params": {"url": "https://example.org/model.cif"},
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    pkg = init_package(native=scene, out=tmp_path / "pkg")
    pkg.semantic_layer.resource_references[0].fixity_status = "available"
    pkg.save()

    report = validate_package(pkg.root, mode="archive")

    assert any(item.rule_id == "IMPORT.REMOTE_RESOURCE_DETACHED" for item in report.findings)


def test_relative_resource_needs_real_attached_fixity_or_expected_digest(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("load model.cif\n", encoding="utf-8")
    pkg = init_package(native=pml, out=tmp_path / "pkg")
    pkg.semantic_layer.artifacts.append(
        Artifact(
            id="artifact:detached-model",
            kind=ArtifactKind.local_detached,
            role=ArtifactRole.structure,
            path="native/model.cif",
            included=False,
            sha256=None,
            fixity_status="available",
        )
    )
    pkg.semantic_layer.resource_references[0].fixity_status = "available"
    pkg.save()

    report = validate_package(pkg.root, mode="archive")

    assert any(item.rule_id == "IMPORT.REMOTE_RESOURCE_DETACHED" for item in report.findings)


def test_mvsx_recorded_inventory_cannot_hide_archive_tampering(tmp_path: Path):
    tree = {
        "metadata": {"version": "1"},
        "root": {"kind": "root", "children": []},
    }
    archive = tmp_path / "scene.mvsx"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("index.mvsj", json.dumps(tree))
        handle.writestr("model.cif", "data_model\n")
    pkg = init_package(native=archive, out=tmp_path / "pkg")
    member = next(
        item for item in pkg.semantic_layer.mvsx_inventories[0].members if not item.is_dir
    )
    member.sha256 = "0" * 64
    pkg.save()

    report = validate_package(pkg.root, mode="draft")

    assert any(item.rule_id == "G2.FIXITY.MVSX_INVENTORY_MISMATCH" for item in report.findings)


def test_density_claim_recognizes_verified_structure_and_map_inside_mvsx(tmp_path: Path):
    tree = {
        "metadata": {"version": "1"},
        "root": {
            "kind": "root",
            "children": [
                {
                    "kind": "download",
                    "params": {"url": "model.cif"},
                    "children": [
                        {
                            "kind": "parse",
                            "params": {"format": "mmcif"},
                            "children": [
                                {"kind": "structure", "params": {"type": "model"}}
                            ],
                        }
                    ],
                },
                {
                    "kind": "download",
                    "params": {"url": "density.map"},
                    "children": [
                        {
                            "kind": "parse",
                            "params": {"format": "map"},
                            "children": [
                                {
                                    "kind": "volume",
                                    "children": [
                                        {
                                            "kind": "volume_representation",
                                            "params": {"type": "isosurface"},
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
            ],
        },
    }
    archive = tmp_path / "density.mvsx"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("index.mvsj", json.dumps(tree))
        handle.writestr("model.cif", "data_model\n_atom_site.Cartn_x\n_atom_site.Cartn_y\n_atom_site.Cartn_z\n")
        handle.writestr("density.map", b"map payload")
    pkg = init_package(native=archive, out=tmp_path / "pkg")
    mvsx_id = pkg.semantic_layer.artifacts[0].id
    answers = {
        "claim": {
            "claim_text": "The displayed model is evaluated against density.",
            "claim_type": "cryo_em_map_fit",
            "figure_ref": "Figure 4B",
        },
        "evidence": [
            {
                "evidence_kind": "density_support",
                "method_name": "Contour inspection",
                "parameters": {"contour_sigma": 1.5},
                "result_summary": "The embedded map and fitted model were reviewed together.",
                "source_artifact_ids": [mvsx_id],
            }
        ],
        "uncertainty": [],
        "reuse": {"license": "unknown"},
    }
    apply_answers(pkg.root, pkg.semantic_layer, answers, answer_base=tmp_path)
    pkg.save()

    report = validate_package(pkg.root, mode="archive")

    assert not any(item.rule_id == "CLAIM.DENSITY.REQUIRED_CONTEXT" for item in report.findings)


def test_model_comparison_requires_two_distinct_structure_digests(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("show cartoon\n", encoding="utf-8")
    first = tmp_path / "first.cif"
    second = tmp_path / "second.cif"
    first.write_text("identical structure bytes\n", encoding="utf-8")
    second.write_text("identical structure bytes\n", encoding="utf-8")
    pkg = init_package(native=pml, out=tmp_path / "pkg")
    first_artifact = pkg.add_artifact(first, role="structure")
    second_artifact = pkg.add_artifact(second, role="structure")
    answers = {
        "claim": {
            "claim_text": "Two registered models are compared.",
            "claim_type": "model_comparison",
            "figure_ref": "Figure 6B",
        },
        "evidence": [
            {
                "evidence_kind": "external_validation",
                "method_name": "Structural superposition",
                "result_summary": "Both registered files were linked to the comparison.",
                "source_artifact_ids": [first_artifact.id, second_artifact.id],
            }
        ],
        "reuse": {"license": "unknown"},
    }
    apply_answers(pkg.root, pkg.semantic_layer, answers, answer_base=tmp_path)
    pkg.save()

    report = validate_package(pkg.root, mode="archive")

    assert any(
        item.rule_id == "CLAIM.MODEL_COMPARISON.REQUIRED_CONTEXT"
        for item in report.findings
    )


def test_invalid_waiver_metadata_does_not_waive_finding(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("unknown_command value\n", encoding="utf-8")
    pkg = init_package(native=pml, out=tmp_path / "pkg")
    raw = pkg.semantic_layer.raw_native_observations[0]
    pkg.semantic_layer.provenance.waivers.append(
        Waiver(
            rule_id="IMPORT.PYMOL.RAW_AFFECTS_SCENE",
            scope=raw.raw_id,
            anchor_id=raw.raw_id,
            reason="",
            reviewer="",
            reviewed_at="not-a-time",
            max_export_mode="archive",
        )
    )
    pkg.save()

    report = validate_package(pkg.root, mode="archive")
    finding = next(
        item for item in report.findings if item.rule_id == "IMPORT.PYMOL.RAW_AFFECTS_SCENE"
    )

    assert finding.status == "FAIL"
