"""Completion templates and answer application."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from claimtrace import _simple_yaml
from claimtrace._finite import ensure_finite
from claimtrace.errors import ClaimTraceError
from claimtrace.models import (
    Claim,
    EvidenceBinding,
    CompletionTask,
    Entity,
    Evidence,
    ProvenancedString,
    Scene,
    Selection,
    SoftwareEnvironment,
    Uncertainty,
    VisualEncodingSemantics,
)
from claimtrace.models.semantic_layer import (
    ClaimCriticalStatus,
    ArtifactRole,
    ClaimType,
    ConfidenceValue,
    MeaningStatus,
    Provenance,
    ReviewStatus,
    SemanticLayer,
    SourceType,
    TargetResolutionStatus,
    Waiver,
    utc_now,
)
from claimtrace.package.registry import (
    find_artifact_by_path,
    register_local_artifact,
    register_remote_artifact,
    replay_destination_for,
)
from claimtrace.package.resources import resource_uri_summary
from claimtrace.path_hints import windows_path_hint


NATIVE_SCENE_ANSWER_SCHEMA = "claimtrace.native_scene_answers.v1"
LEGACY_NATIVE_SCENE_ANSWER_SCHEMA = "claimtrace.cxc_mvs_answers.v1"
NATIVE_SCENE_ANSWER_SCHEMAS = {NATIVE_SCENE_ANSWER_SCHEMA, LEGACY_NATIVE_SCENE_ANSWER_SCHEMA}
NATIVE_SCENE_ANSWER_FIELDS = {
    "native_identity_mappings",
    "scene_semantics_by_operation",
    "raw_resolutions",
    "resource_bindings",
    "evidence_bindings",
    "waivers",
}


TEMPLATES: dict[str, dict[str, Any]] = {
    "simple-structure-view": {
        "package": {
            "title": "Simple molecular structure view",
            "creator": "unknown",
            "license": "unknown",
            "profile": "simple-structure-view",
        },
        "claim": {
            "claim_text": "TODO: write one sentence stating what this figure or panel shows",
            "claim_type": "simple_structure_view",
            "figure_ref": "TODO: add the figure or panel label",
            "scope": "panel",
        },
        "artifacts": [
            {"path": "model.cif", "role": "structure"},
        ],
        "entities": [],
        "evidence": [
            {
                "evidence_kind": "manual_rationale",
                "method_name": "TODO: name the inspection or analysis used to check this claim",
                "result_summary": "TODO: explain which attached files support this panel and how",
                "source_artifact_roles": ["native_script", "render_image", "structure"],
            }
        ],
        "scene": {
            "color_meanings": {},
            "label_meanings": {},
            "notes": "",
        },
        "uncertainty": {
            "category": "scope",
            "statement": "TODO: add a relevant limitation, or set uncertainty: [] if none applies",
        },
        "reuse": {"license": "unknown", "citation": "unknown"},
    },
    "ligand-binding-pose": {
        "package": {
            "title": "Ligand binding pose review package",
            "creator": "unknown",
            "license": "unknown",
            "profile": "ligand-binding-pose",
        },
        "claim": {
            "claim_text": "TODO: write the exact claim about the ligand and binding pocket in this panel",
            "claim_type": "ligand_binding_pose",
            "figure_ref": "TODO: add the figure or panel label",
            "scope": "panel",
        },
        "artifacts": [
            {"path": "model.cif", "role": "structure"},
            {"path": "contacts.csv", "role": "contact_table"},
        ],
        "entities": [
            {
                "id": "entity:ligand:X",
                "entity_type": "ligand",
                "label": "Ligand X",
                "stable_identity": "unknown",
                "claim_critical": True,
            },
            {
                "id": "entity:binding-site",
                "entity_type": "residue_set",
                "label": "Binding-site residues",
                "stable_identity": "unknown",
                "claim_critical": True,
            },
        ],
        "evidence": [
            {
                "evidence_kind": "contact_table",
                "method_name": "TODO: name the contact or validation method",
                "thresholds": {},
                "units": {},
                "result_summary": "TODO: summarize the contacts or measured distances and name the supporting files",
                "source_artifact_roles": ["contact_table", "structure"],
                "target_entity_ids": ["entity:ligand:X", "entity:binding-site"],
            }
        ],
        "scene": {
            "color_meanings": {},
            "label_meanings": {},
            "notes": "",
        },
        "uncertainty": {
            "category": "alternative_pose",
            "statement": "TODO: state whether alternative poses, water molecules, cofactors, or other limitations were assessed",
        },
        "reuse": {"license": "unknown", "citation": "unknown"},
    },
}


def available_templates() -> tuple[str, ...]:
    return tuple(TEMPLATES.keys())


SECTION_QUESTIONS = {
    "claim": "What should a reader understand from this figure or panel?",
    "entities": "Which molecules, residues or selections should readers be able to identify clearly?",
    "scene": "Review any low-confidence or claim-critical color/label suggestions; ClaimTrace records literal scene facts automatically.",
    "evidence": "Which files or notes help readers check this figure?",
    "uncertainty": "What useful caveat or context should travel with this package?",
    "reuse": "What citation, license or reuse note should be included?",
}


def answer_template(template: str) -> dict[str, Any]:
    try:
        return json.loads(json.dumps(TEMPLATES[template]))
    except KeyError as exc:
        allowed = ", ".join(available_templates())
        raise ValueError(f"Unknown completion template: {template}. Choose one of: {allowed}.") from exc


def completion_tasks_for_template(template: str) -> list[CompletionTask]:
    tasks: list[CompletionTask] = []
    for section, question in SECTION_QUESTIONS.items():
        tasks.append(
            CompletionTask(
                id=f"task:{template}:{section}",
                section=section,
                question=question,
                target_json_pointer=_section_pointer(section),
                field_use="Records the author’s statement, evidence and interpretation of the figure.",
                examples=_section_examples(section, template),
                accepted_values=["unknown", "not_applicable", "short author-provided value"],
                blocking=(
                    section == "claim"
                    or template == "ligand-binding-pose"
                    and section in {"entities", "evidence", "uncertainty"}
                ),
            )
        )
    return tasks


def _section_pointer(section: str) -> str:
    return {
        "claim": "/claims",
        "entities": "/entities",
        "scene": "/scenes",
        "evidence": "/evidence",
        "uncertainty": "/uncertainty",
        "reuse": "/reuse",
    }.get(section, "/extensions")


def _section_examples(section: str, template: str) -> list[str]:
    if section == "claim":
        return [answer_template(template)["claim"]["claim_text"], "unknown"]
    if section == "scene":
        if template == "ligand-binding-pose":
            return [
                "confirm: magenta marks the ligand discussed in this panel",
                "edit: label names the pocket residue being discussed",
                "presentation only: color improves contrast",
            ]
        return [
            "confirm: cartoon/sticks distinguish the objects described in the panel",
            "edit: label identifies the chain or residue readers should notice",
            "presentation only: color improves contrast",
        ]
    if section == "evidence":
        if template == "ligand-binding-pose":
            return [
                "contacts.csv with distance threshold 4.0 angstrom",
                "model.cif, figure_A.png and contacts.csv were checked together",
            ]
        return ["model.cif and figure_A.png were checked together", "native scene and structure file were reviewed together"]
    if section == "uncertainty":
        if template == "ligand-binding-pose":
            return ["Alternative poses need comparison.", "Assess water and cofactor context in a separate view."]
        return ["not_applicable: this is a simple structure view", "The statement describes visible structure and selection."]
    return ["unknown", "confirmed value"]


def load_answers(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"Answer file not found: {path}. Generate one with `claimtrace complete --emit-template > answers.yml`.")
    data = _simple_yaml.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Answers file must contain a mapping at the top level.")
    return data


def dump_answer_template(template: str) -> str:
    return _simple_yaml.dumps(answer_template(template))


def package_answer_template(semantic: SemanticLayer, template: str = "simple-structure-view") -> dict[str, Any]:
    data = answer_template(template)
    data["package"].update(
        {
            "title": semantic.package.title,
            "creator": semantic.package.creator,
            "license": semantic.package.license,
            "profile": semantic.package.profile,
            "description": semantic.package.description,
        }
    )
    _make_artifacts_package_aware(data, semantic)
    _make_evidence_package_aware(data, semantic)
    _make_scenes_package_aware(data, semantic)
    data["reuse"] = semantic.reuse.model_dump(mode="json", exclude={"extensions"})
    data["software"] = [item.model_dump(mode="json") for item in semantic.software_environment]
    if semantic.entities or semantic.claims:
        data["entities"] = [item.model_dump(mode="json") for item in semantic.entities]
    if semantic.claims:
        data.pop("claim", None)
        data["claims"] = []
        for claim in semantic.claims:
            item = claim.model_dump(mode="json")
            text = item.pop("claim_text")
            item.update({key: value for key, value in text.items() if key != "value"})
            item["claim_text"] = text["value"]
            data["claims"].append(item)
        data["evidence"] = [item.model_dump(mode="json") for item in semantic.evidence]
        data["uncertainty"] = [item.model_dump(mode="json") for item in semantic.uncertainty]
    if semantic.selections:
        data["selections"] = [
            {
                **selection.model_dump(mode="json"),
                "native_selector": selection.native_selector.value,
                "review_instruction": (
                    "If this selection supports the figure claim, link entity_ids and set claim_critical: true; "
                    "otherwise leave claim_critical: false."
                ),
            }
            for selection in semantic.selections
        ]
    if _has_cxc_mvs_anchors(semantic):
        data["answer_schema"] = NATIVE_SCENE_ANSWER_SCHEMA
        data["native_identity_mappings"] = [
            {
                "native_ref_id": ref.native_ref_id,
                "native_expression": ref.native_expression,
                "stable_identity": ref.stable_identity,
                "identity_status": ref.identity_status,
                "target_resolution_status": ref.target_resolution_status.value,
                "claim_critical": ref.claim_critical.value,
                "review_status": ref.review_status.value,
            }
            for ref in semantic.native_references
        ]
        data["scene_semantics_by_operation"] = [
            {
                "operation_ids": [operation.operation_id],
                "operation": operation.operation,
                "native": operation.native_command,
                "source_location": operation.source_location.model_dump(mode="json", exclude_none=True),
                "encoding_type": operation.operation,
                "meaning_status": operation.meaning_status.value,
                "claim_critical": operation.claim_critical.value,
                "auto_annotation": operation.auto_annotation or "",
                "candidate_meaning": operation.candidate_meaning or "",
                "meaning": "",
                "no_scientific_meaning_reason": "",
                "review_instruction": _operation_review_instruction(operation),
            }
            for operation in semantic.observed_scene_operations
            if _include_scene_semantics_entry(operation)
        ]
        recorded_ids = {
            operation_id for item in semantic.visual_encoding_semantics for operation_id in item.operation_ids
        }
        data["scene_semantics_by_operation"] = [
            item for item in data["scene_semantics_by_operation"]
            if not recorded_ids.intersection(item["operation_ids"])
        ]
        operations = {item.operation_id: item for item in semantic.observed_scene_operations}
        for meaning in semantic.visual_encoding_semantics:
            item = meaning.model_dump(mode="json")
            linked = [operations[oid] for oid in meaning.operation_ids if oid in operations]
            if linked:
                operation = linked[0]
                item.update(
                    operation=operation.operation, native=operation.native_command,
                    source_location=operation.source_location.model_dump(mode="json", exclude_none=True),
                )
                criticality = {entry.claim_critical.value for entry in linked}
                if len(criticality) == 1:
                    item["claim_critical"] = criticality.pop()
            data["scene_semantics_by_operation"].append(item)
        data["raw_resolutions"] = [
            {
                "raw_id": raw.raw_id,
                "native_text": raw.native_text,
                "reason": raw.reason,
                "claim_critical": raw.claim_critical.value,
                "resolution": raw.resolution,
                "review_status": raw.review_status.value,
            }
            for raw in semantic.raw_native_observations
        ]
        data["resource_bindings"] = [
            {
                "resource_ref_id": resource.resource_ref_id,
                "uri": resource_uri_summary(resource.uri),
                "uri_kind": resource.uri_kind,
                "claim_critical": resource.claim_critical.value,
            }
            for resource in semantic.resource_references
        ]
        data["evidence_bindings"] = [item.model_dump(mode="json") for item in semantic.evidence_bindings]
        data["waivers"] = [item.model_dump(mode="json") for item in semantic.provenance.waivers]
    return data


def dump_package_answer_template(semantic: SemanticLayer, template: str = "simple-structure-view") -> str:
    header = "\n".join(
        [
            "# ClaimTrace answers",
            "# Fill claim.claim_text and claim.figure_ref first. Fill evidence[].method_name and result_summary only for evidence you actually have.",
            "# uncertainty: replace the placeholder with an author-reviewed caveat, or use uncertainty: [] if none applies.",
            "# artifacts: leave empty when init/add-artifact already included the files; otherwise add paths to copy.",
            "# entities/selections: fill only molecules, chains, residues or selections readers must identify.",
            "# scene_semantics_by_operation: edit only entries listed here; they are keyed by operation_ids.",
            "# In multi-scene packages, choose claim.scene_ids and assign each render_artifact_id only to its matching scene.",
            "# ClaimTrace records color, label and display commands. Review each candidate_meaning before accepting it.",
            "# For each color/label suggestion choose one:",
            "#   meaning_status: user_confirmed_meaning          # visual choice carries the figure message",
            "#   meaning_status: user_declared_no_scientific_meaning  # contrast/readability only",
            "#   claim_critical: false                            # incidental to this figure or panel",
            "# raw_resolutions: review only preserved/unsupported native items; keep raw_id unchanged.",
            "#   resolution choices include reviewed_no_claim_impact, no_scene_effect, converted_to_evidence, waived, and not_applicable.",
            "# Long inline resource URIs are summarized here; semantic_layer.json keeps the exact value.",
            "# Leave operation_ids and native_ref_id values unchanged; they point back to what ClaimTrace observed.",
            "# Relative paths are resolved from the package first, then from this answers file.",
            "",
        ]
    )
    return header + _simple_yaml.dumps(package_answer_template(semantic, template))


def apply_answers(
    root: Path,
    semantic: SemanticLayer,
    answers: dict[str, Any],
    *,
    answer_base: Path | None = None,
) -> SemanticLayer:
    """Validate the complete edit in memory before attaching files or changing CAL."""
    answer_base = answer_base or root
    candidate, registrations = _prepare_answers(root, semantic, answers, answer_base=answer_base)
    for source, options in registrations:
        if not options["detached"]:
            register_local_artifact(root, candidate, source, **options)
    for field in type(semantic).model_fields:
        setattr(semantic, field, getattr(candidate, field))
    return semantic


def _prepare_answers(
    root: Path | None,
    semantic: SemanticLayer,
    answers: dict[str, Any],
    *,
    answer_base: Path | None = None,
    validate_references: bool = True,
) -> tuple[SemanticLayer, list[tuple[Path, dict[str, Any]]]]:
    """Build and validate a candidate CAL without writing package files."""
    ensure_finite(answers)
    original = semantic
    semantic = semantic.model_copy(deep=True)
    registrations: list[tuple[Path, dict[str, Any]]] = []
    answer_base = answer_base or root
    if root is not None:
        problems = _check_answer_artifact_paths(answers, root, answer_base or root)
        if problems:
            raise ValueError("\n".join(problems))
    _register_answer_artifacts(root, semantic, answers.get("artifacts", []), answer_base, registrations)
    _apply_cxc_mvs_answers(semantic, answers)
    _apply_package(semantic, answers.get("package", {}))
    _apply_reuse(semantic, answers.get("reuse", {}))
    _apply_entities(semantic, answers.get("entities", []))
    _apply_selections(semantic, answers.get("selections", []))
    claims = _coerce_list(answers.get("claims", answers.get("claim")))
    claim_items = [item for item in claims if isinstance(item, dict)]
    claim_ids = [
        _apply_claim(semantic, item, answer_index=index, answer_count=len(claim_items))
        for index, item in enumerate(claim_items)
    ]
    evidence_ids = _apply_evidence(
        root, semantic, answers.get("evidence", []), answer_base, claim_ids, registrations
    )
    uncertainty_ids = _apply_uncertainty(semantic, answers.get("uncertainty", []), claim_ids)
    _apply_scene_semantics(
        semantic, answers.get("scenes", answers.get("scene", {})),
        validate_references=validate_references,
    )
    for records, changed_ids, field in (
        (semantic.evidence, evidence_ids, "evidence_ids"),
        (semantic.uncertainty, uncertainty_ids, "uncertainty_ids"),
    ):
        changed = {record.id: record for record in records if record.id in changed_ids}
        for claim in semantic.claims:
            retained = [
                identity for identity in getattr(claim, field)
                if identity not in changed or claim.id in changed[identity].claim_ids
            ]
            linked = [record.id for record in changed.values() if claim.id in record.claim_ids]
            setattr(claim, field, list(dict.fromkeys(retained + linked)))
    _apply_software(semantic, answers.get("software", []))
    _mark_tasks_answered(semantic)
    semantic.add_activity("completion", "Applied author completion answers.")
    candidate = SemanticLayer.model_validate(ensure_finite(semantic.model_dump()))
    if validate_references:
        from claimtrace.validation.engine import _reference_findings

        existing = Counter((item.rule_id, item.message) for item in _reference_findings(original))
        for issue in _reference_findings(candidate):
            key = (issue.rule_id, issue.message)
            if existing[key]:
                existing[key] -= 1
            else:
                raise ValueError(f"{issue.json_pointer}: {issue.message}")
    return candidate, registrations


def check_answers(
    answers: dict[str, Any],
    semantic: SemanticLayer | None = None,
    *,
    root: Path | None = None,
    answer_base: Path | None = None,
) -> list[str]:
    problems: list[str] = []
    answer_schema = answers.get("answer_schema")
    if answer_schema and answer_schema not in NATIVE_SCENE_ANSWER_SCHEMAS:
        allowed = ", ".join(sorted(NATIVE_SCENE_ANSWER_SCHEMAS))
        problems.append(f"answer_schema has unsupported value: {answer_schema}. Choose one of: {allowed}.")
    if "claim" not in answers and "claims" not in answers:
        problems.append("Missing claim or claims section.")
    if "evidence" not in answers:
        problems.append("Missing evidence section.")
    if "reuse" not in answers:
        problems.append("Missing reuse section.")
    prepared = None
    if root is not None:
        problems.extend(_check_answer_artifact_paths(answers, root, answer_base or root))
    if not problems:
        try:
            prepared, _ = _prepare_answers(
                root, semantic or SemanticLayer.new("answer-check"), answers,
                answer_base=answer_base, validate_references=semantic is not None,
            )
        except (ValueError, TypeError, ClaimTraceError) as exc:
            problems.append(f"Invalid answer value: {exc}")
    reference_semantic = prepared if semantic is not None and prepared is not None else semantic
    unchanged_operations: set[str] = set()
    if semantic is not None and prepared is not None and semantic.claims == prepared.claims:
        previous_operations = {item.operation_id: item for item in semantic.observed_scene_operations}
        for operation in prepared.observed_scene_operations:
            old_meanings = [item for item in semantic.visual_encoding_semantics if operation.operation_id in item.operation_ids]
            new_meanings = [item for item in prepared.visual_encoding_semantics if operation.operation_id in item.operation_ids]
            if previous_operations.get(operation.operation_id) == operation and old_meanings == new_meanings:
                unchanged_operations.add(operation.operation_id)
    if _uses_native_scene_answer_schema(answers) or (semantic is not None and _has_cxc_mvs_anchors(semantic)):
        # Planned artifacts are already represented, including their final local IDs.
        problems.extend(_check_cxc_mvs_answers(answers, reference_semantic, unchanged_operations=unchanged_operations))
    problems.extend(_check_required_content(answers, semantic, prepared))
    problems.extend(_check_scene_links(answers, reference_semantic))
    return problems


def completed_answer_sections(answers: dict[str, Any]) -> set[str]:
    """Return completion sections that contain an honest, usable answer.

    This is deliberately separate from archive validation. A scene-only draft
    may complete its claim while leaving the evidence task open.
    """

    completed: set[str] = set()
    claims = _coerce_list(answers.get("claims", answers.get("claim")))
    if claims and all(
        isinstance(item, dict)
        and not _is_placeholder(item.get("claim_text", item.get("text")))
        and not _is_placeholder(item.get("figure_ref"))
        for item in claims
    ):
        completed.add("claim")

    evidence = _coerce_list(answers.get("evidence", []))
    if "evidence" in answers and not evidence:
        completed.add("evidence")
    elif evidence and all(
        isinstance(item, dict)
        and not _is_placeholder(item.get("result_summary"))
        and any(
            _coerce_list(item.get(field))
            for field in ("source_artifact_ids", "source_artifact_roles", "source_artifact_paths")
        )
        for item in evidence
    ):
        completed.add("evidence")

    claim_types = {
        str(item.get("claim_type", ""))
        for item in claims
        if isinstance(item, dict)
    }
    entities = _coerce_list(answers.get("entities", []))
    if ClaimType.ligand_binding_pose.value in claim_types:
        if entities and all(
            isinstance(item, dict) and not _is_placeholder(item.get("stable_identity"))
            for item in entities
        ):
            completed.add("entities")
    else:
        completed.add("entities")

    if "scene" in answers or "scenes" in answers or "scene_semantics_by_operation" in answers:
        completed.add("scene")
    uncertainty = _coerce_list(answers.get("uncertainty", []))
    if "uncertainty" in answers and not uncertainty:
        completed.add("uncertainty")
    elif uncertainty and all(
        not _is_placeholder(item.get("statement") if isinstance(item, dict) else item)
        for item in uncertainty
    ):
        completed.add("uncertainty")
    if "reuse" in answers:
        completed.add("reuse")
    return completed


def _uses_native_scene_answer_schema(answers: dict[str, Any]) -> bool:
    return answers.get("answer_schema") in NATIVE_SCENE_ANSWER_SCHEMAS or _has_native_scene_answer_fields(answers)


def _has_native_scene_answer_fields(answers: dict[str, Any]) -> bool:
    return any(field in answers for field in NATIVE_SCENE_ANSWER_FIELDS)


def _has_cxc_mvs_anchors(semantic: SemanticLayer) -> bool:
    return any(
        [
            semantic.observed_scene_operations,
            semantic.native_references,
            semantic.raw_native_observations,
            semantic.resource_references,
            semantic.mvsx_inventories,
        ]
    )


def _include_scene_semantics_entry(operation: Any) -> bool:
    return (
        operation.meaning_status == MeaningStatus.requires_user_completion
        or bool(getattr(operation, "needs_author_confirmation", False))
        or (
            operation.meaning_status == MeaningStatus.tool_suggested_meaning
            and operation.claim_critical != ClaimCriticalStatus.false
            and _operation_has_visual_candidate(operation)
        )
    )


def _operation_review_instruction(operation: Any) -> str:
    candidate = str(getattr(operation, "candidate_meaning", "") or "")
    if (
        candidate
        and "no scientific meaning is inferred" in candidate.lower()
        and not getattr(operation, "needs_author_confirmation", False)
    ):
        return (
            "ClaimTrace inferred no scientific meaning for this visual choice. "
            "Review it only if the color/label matters for this figure; otherwise it can stay non-critical."
        )
    if operation.needs_author_confirmation:
        return "Confirm or edit this suggested meaning because it is low-confidence or figure-central."
    return (
        "Before archive export, confirm/edit this suggestion, mark it presentation only, "
        "or set claim_critical to false if it is not figure-central."
    )


def _make_artifacts_package_aware(data: dict[str, Any], semantic: SemanticLayer) -> None:
    # A package-aware template must not turn a native `load model.cif`
    # reference into a claim that model.cif exists beside answers.yml. Missing
    # resources remain visible under resource_bindings and in `inspect`; users
    # attach them explicitly with add-artifact or add a real path here.
    data["artifacts"] = []


def _make_evidence_package_aware(data: dict[str, Any], semantic: SemanticLayer) -> None:
    evidence_items = _coerce_list(data.get("evidence", []))
    if not evidence_items:
        return
    source_roles = [
        artifact.role.value
        for artifact in semantic.artifacts
        if artifact.role.value
        in {
            "native_script",
            "native_session",
            "chimerax_script",
            "molviewspec",
            "render_image",
            "structure",
            "map",
            "contact_table",
            "validation_report",
            "evidence_document",
        }
    ]
    if not source_roles:
        return
    native_only_roles = {
        "native_script",
        "native_session",
        "chimerax_script",
        "molviewspec",
    }
    if set(source_roles) <= native_only_roles:
        # A scene script is useful reproducibility context, but it is not by
        # itself scientific support for the claim.  Let an only-native package
        # be completed as an honest draft; archive validation will still ask
        # for linked evidence instead of forcing the author to invent a
        # result_summary about evidence they do not have.
        data["evidence"] = []
        return
    first = evidence_items[0]
    if isinstance(first, dict):
        first["source_artifact_roles"] = sorted(set(source_roles))
        readable = ", ".join(sorted(set(source_roles)))
        first["result_summary"] = f"TODO: explain how the attached {readable} file(s) support this panel"
    data["evidence"] = evidence_items


def _make_scenes_package_aware(data: dict[str, Any], semantic: SemanticLayer) -> None:
    if not semantic.scenes:
        return
    claims = _coerce_list(data.get("claims", data.get("claim")))
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        if len(semantic.scenes) == 1:
            claim["scene_ids"] = [semantic.scenes[0].id]
        else:
            claim["scene_ids"] = []
            claim["available_scene_ids"] = [scene.id for scene in semantic.scenes]
    if len(semantic.scenes) > 1:
        data["available_render_artifacts"] = [
            {"id": artifact.id, "path": artifact.path or artifact.url or "unknown"}
            for artifact in semantic.artifacts
            if artifact.role.value == "render_image"
        ]
    base = data.pop("scene", {})
    base = base if isinstance(base, dict) else {}
    scenes = []
    for scene in semantic.scenes:
        meanings = scene.extensions.get("user_scene_semantics", [])
        meanings = meanings[-1] if isinstance(meanings, list) and meanings else {}
        scenes.append({
            **base,
            **meanings,
            "scene_ids": [scene.id],
            "render_artifact_ids": list(scene.render_artifact_ids),
        })
    if len(scenes) == 1:
        data["scene"] = scenes[0]
    else:
        data["scenes"] = scenes


def _check_required_content(
    answers: dict[str, Any], semantic: SemanticLayer | None, prepared: SemanticLayer | None = None,
) -> list[str]:
    problems: list[str] = []
    unchanged: set[str] = set()
    if semantic is not None and prepared is not None:
        previous_records = {item.id: item for field in ("claims", "evidence", "uncertainty") for item in getattr(semantic, field)}
        unchanged = {
            item.id for field in ("claims", "evidence", "uncertainty") for item in getattr(prepared, field)
            if previous_records.get(item.id) == item
        }
    claims = [
        _effective_answer(item, semantic.claims if semantic else [])
        for item in _coerce_list(answers.get("claims", answers.get("claim")))
    ]
    claim_types = {
        str(item.get("claim_type", ""))
        for item in claims
        if isinstance(item, dict) and item.get("id") not in unchanged
    }
    seen_claim_ids: set[str] = set()
    for index, item in enumerate(claims):
        if not isinstance(item, dict):
            problems.append(f"claim[{index}] must be a mapping.")
            continue
        text = item.get("claim_text", item.get("text"))
        if isinstance(text, dict):
            text = text.get("value")
        if _is_placeholder(text):
            problems.append("claim.claim_text is still unknown; write the figure or panel message.")
        if _is_placeholder(item.get("figure_ref")):
            problems.append("claim.figure_ref is still unknown; write the figure or panel label.")
        if len(claims) > 1:
            claim_id = str(item.get("id", "")).strip()
            if not claim_id:
                problems.append(f"claims[{index}].id is required when an answers file has multiple claims.")
            elif claim_id in seen_claim_ids:
                problems.append(f"claims[{index}].id is duplicated: {claim_id}")
            seen_claim_ids.add(claim_id)
        if semantic is not None:
            scene_ids = [str(value) for value in _coerce_list(item.get("scene_ids", []))]
            if len(semantic.scenes) > 1 and not scene_ids:
                problems.append(
                    "claim.scene_ids must choose at least one scene because this package contains multiple scenes."
                )
            known_scene_ids = {scene.id for scene in semantic.scenes}
            for scene_id in scene_ids:
                if scene_id not in known_scene_ids:
                    problems.append(f"claims[{index}].scene_ids references unknown scene_id: {scene_id}")
    for index, item in enumerate(_coerce_list(answers.get("evidence", []))):
        if isinstance(item, dict) and item.get("id") in unchanged:
            continue
        item = _effective_answer(item, semantic.evidence if semantic else [])
        if not isinstance(item, dict):
            problems.append(f"evidence[{index}] must be a mapping.")
            continue
        if _is_placeholder(item.get("result_summary")):
            problems.append(f"evidence[{index}].result_summary is still unknown.")
        if _is_placeholder(item.get("method_name")):
            problems.append(f"evidence[{index}].method_name is still unknown; name the review or analysis method.")
        has_source = any(
            _coerce_list(item.get(field))
            for field in ["source_artifact_ids", "source_artifact_roles", "source_artifact_paths"]
        )
        if not has_source:
            problems.append(
                f"evidence[{index}] needs a source_artifact_roles, source_artifact_paths or source_artifact_ids entry."
            )
        if str(item.get("evidence_kind", "")) in {"contact_table", "measurement"}:
            thresholds = item.get("thresholds", {})
            parameters = item.get("parameters", {})
            units = item.get("units", {})
            threshold = thresholds.get("distance") if isinstance(thresholds, dict) else None
            measured = parameters.get("measured_distance") if isinstance(parameters, dict) else None
            is_measurement = str(item.get("evidence_kind")) == "measurement" and measured is not None
            distance = measured if is_measurement else threshold
            unit = units.get("distance") if isinstance(units, dict) else None
            try:
                valid_threshold = not isinstance(distance, bool) and math.isfinite(float(distance)) and float(distance) > 0
            except (TypeError, ValueError, OverflowError):
                valid_threshold = False
            if not valid_threshold:
                problems.append(
                    f"evidence[{index}].parameters.measured_distance needs a positive finite numeric distance."
                    if is_measurement else f"evidence[{index}].thresholds.distance needs a positive numeric cutoff."
                )
            if _is_placeholder(unit):
                problems.append(
                    f"evidence[{index}].units.distance is still unknown; record a unit such as angstrom."
                )
    if ClaimType.ligand_binding_pose.value in claim_types:
        entities = _coerce_list(answers.get(
            "entities", [item.model_dump(mode="json") for item in semantic.entities] if semantic else []
        ))
        if not entities:
            problems.append("A ligand-binding answer needs ligand and binding-site/residue entities.")
        for index, item in enumerate(entities):
            if not isinstance(item, dict):
                problems.append(f"entities[{index}] must be a mapping.")
            elif _is_placeholder(item.get("stable_identity")):
                problems.append(
                    f"entities[{index}].stable_identity is still unknown; record the model/chain/residue or ligand identity."
                )
    existing_limits = []
    if semantic is not None:
        answered_claim_ids = {str(item["id"]) for item in claims if isinstance(item, dict) and item.get("id")}
        existing_limits = [
            item.model_dump(mode="json") for item in semantic.uncertainty
            if answered_claim_ids.intersection(item.claim_ids)
        ]
    uncertainty = _coerce_list(answers.get("uncertainty", existing_limits))
    if ClaimType.ligand_binding_pose.value in claim_types and not uncertainty:
        problems.append("A ligand-binding answer needs a caveat or alternative-pose statement.")
    for index, item in enumerate(uncertainty):
        if isinstance(item, dict) and item.get("id") in unchanged:
            continue
        item = _effective_answer(item, semantic.uncertainty if semantic else [])
        statement = item.get("statement") if isinstance(item, dict) else item
        if _is_placeholder(statement):
            problems.append(f"uncertainty[{index}].statement is still unknown.")
    return problems


def _effective_answer(item: Any, records: list[Any]) -> Any:
    """Validate partial updates against the fields retained from an explicit ID."""
    if not isinstance(item, dict) or not item.get("id"):
        return item
    previous = next((record for record in records if record.id == item["id"]), None)
    if previous is None:
        return item
    values = previous.model_dump(mode="json")
    if "claim_text" in values and isinstance(item.get("claim_text"), dict):
        item = {**item, "claim_text": {**values["claim_text"], **item["claim_text"]}}
    elif "text" in item and "claim_text" not in item:
        item = {**item, "claim_text": item["text"]}
    return {**values, **item}


def _check_scene_links(
    answers: dict[str, Any],
    semantic: SemanticLayer | None,
) -> list[str]:
    if semantic is None:
        return []
    problems: list[str] = []
    known_scene_ids = {scene.id for scene in semantic.scenes}
    render_ids = {
        artifact.id for artifact in semantic.artifacts if artifact.role.value == "render_image"
    }
    for index, item in enumerate(_coerce_list(answers.get("scenes", answers.get("scene", [])))):
        if not isinstance(item, dict):
            problems.append(f"scenes[{index}] must be a mapping.")
            continue
        target_ids = [str(value) for value in _coerce_list(item.get("scene_ids", []))]
        for scene_id in target_ids:
            if scene_id not in known_scene_ids:
                problems.append(f"scenes[{index}] references unknown scene_id: {scene_id}")
        linked_renders = [
            str(value) for value in _coerce_list(item.get("render_artifact_ids", []))
        ]
        if linked_renders and len(semantic.scenes) > 1 and not target_ids:
            problems.append(
                f"scenes[{index}] must include scene_ids before assigning render_artifact_ids in a multi-scene package."
            )
        for artifact_id in linked_renders:
            if artifact_id not in render_ids:
                problems.append(
                    f"scenes[{index}] references unknown rendered-image artifact_id: {artifact_id}"
                )
    return problems


def _check_answer_artifact_paths(answers: dict[str, Any], root: Path, answer_base: Path) -> list[str]:
    problems: list[str] = []
    for index, item in enumerate(_coerce_list(answers.get("artifacts", []))):
        if not isinstance(item, dict) or item.get("url") or not item.get("path"):
            continue
        source = _resolve_answer_path(root, answer_base, str(item["path"]))
        if not source.exists():
            problems.append(
                f"artifacts[{index}].path not found: {item['path']} "
                f"(looked at {root / str(item['path'])} and {answer_base / str(item['path'])})."
                f"{windows_path_hint(item['path'])}"
            )
    for index, item in enumerate(_coerce_list(answers.get("evidence", []))):
        if not isinstance(item, dict):
            continue
        for path in _coerce_list(item.get("source_artifact_paths", [])):
            source = _resolve_answer_path(root, answer_base, str(path))
            if not source.exists():
                problems.append(
                    f"evidence[{index}].source_artifact_paths entry not found: {path} "
                    f"(looked at {root / str(path)} and {answer_base / str(path)})."
                    f"{windows_path_hint(path)}"
                )
    return problems


def _is_placeholder(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    lowered = text.lower()
    if lowered.startswith("todo") or "ligand x occupies pocket y" in lowered:
        return True
    return lowered in {
        "unknown",
        "todo",
        "tbd",
        "not set",
        "short author-provided value",
    }


def _check_cxc_mvs_answers(
    answers: dict[str, Any], semantic: SemanticLayer | None, *, unchanged_operations: set[str] | None = None,
) -> list[str]:
    problems: list[str] = []
    if semantic is None:
        return problems
    unchanged_operations = unchanged_operations or set()
    operation_ids = {operation.operation_id for operation in semantic.observed_scene_operations}
    required_operation_ids = {
        operation.operation_id
        for operation in semantic.observed_scene_operations
        if operation.meaning_status == MeaningStatus.requires_user_completion
        or operation.needs_author_confirmation
        or (
            operation.meaning_status == MeaningStatus.tool_suggested_meaning
            and operation.claim_critical == ClaimCriticalStatus.unknown
            and _operation_has_visual_candidate(operation)
        )
        or _operation_likely_ligand_claim_central(operation, answers, semantic)
    }
    required_operation_ids -= unchanged_operations
    native_ref_ids = {ref.native_ref_id for ref in semantic.native_references}
    raw_ids = {raw.raw_id for raw in semantic.raw_native_observations}
    resource_ref_ids = {resource.resource_ref_id for resource in semantic.resource_references}
    artifact_ids = {artifact.id for artifact in semantic.artifacts}
    scene_ids = {scene.id for scene in semantic.scenes}
    claim_ids = {claim.id for claim in semantic.claims}
    claim_ids.update(
        str(item.get("id"))
        for item in _coerce_list(answers.get("claims", answers.get("claim")))
        if isinstance(item, dict) and item.get("id")
    )
    evidence_ids = {item.id for item in semantic.evidence}
    uncertainty_ids = {item.id for item in semantic.uncertainty}
    entity_ids = {item.id for item in semantic.entities}
    selection_ids = {item.id for item in semantic.selections}
    binding_ids = {item.binding_id for item in semantic.evidence_bindings}
    software_ids = {item.id for item in semantic.software_environment}
    activity_ids = {item.id for item in semantic.provenance.activities}
    agent_ids = {item.id for item in semantic.provenance.agents}
    member_ids = {
        member.member_id
        for inventory in semantic.mvsx_inventories
        for member in inventory.members
    }
    answer_id_fields = {
        "evidence": "id",
        "uncertainty": "id",
        "entities": "id",
        "selections": "id",
        "software": "id",
        "evidence_bindings": "binding_id",
    }
    answer_anchor_ids = {
        str(item[id_field])
        for field, id_field in answer_id_fields.items()
        for item in _coerce_list(answers.get(field, []))
        if isinstance(item, dict) and item.get(id_field)
    }
    anchor_ids = (
        operation_ids
        | native_ref_ids
        | raw_ids
        | resource_ref_ids
        | artifact_ids
        | scene_ids
        | claim_ids
        | evidence_ids
        | uncertainty_ids
        | entity_ids
        | selection_ids
        | binding_ids
        | software_ids
        | activity_ids
        | agent_ids
        | member_ids
        | answer_anchor_ids
    )
    for index, item in enumerate(_coerce_list(answers.get("native_identity_mappings", []))):
        native_ref_id = str(item.get("native_ref_id", "")) if isinstance(item, dict) else ""
        if native_ref_id and native_ref_id not in native_ref_ids:
            problems.append(f"native_identity_mappings[{index}] references unknown native_ref_id: {native_ref_id}")
    answered_operation_ids: set[str] = set()
    for index, item in enumerate(_coerce_list(answers.get("scene_semantics_by_operation", []))):
        if not isinstance(item, dict):
            problems.append(f"scene_semantics_by_operation[{index}] must be a mapping.")
            continue
        ids = [str(value) for value in _coerce_list(item.get("operation_ids", []))]
        if not ids:
            problems.append(f"scene_semantics_by_operation[{index}] must include operation_ids.")
        for operation_id in ids:
            if operation_id not in operation_ids:
                problems.append(f"scene_semantics_by_operation[{index}] references unknown operation_id: {operation_id}")
            answered_operation_ids.add(operation_id)
        if ids and set(ids) <= unchanged_operations:
            continue
        source_operation = next(
            (
                operation
                for operation in semantic.observed_scene_operations
                if operation.operation_id in ids
            ),
            None,
        )
        meaning_status = str(item.get("meaning_status", "requires_user_completion"))
        try:
            status = MeaningStatus(meaning_status)
        except ValueError:
            allowed = ", ".join(value.value for value in MeaningStatus)
            problems.append(
                f"scene_semantics_by_operation[{index}].meaning_status has unsupported value: "
                f"{meaning_status}. Choose one of: {allowed}."
            )
            continue
        item_claim_critical = _claim_critical_status(item.get("claim_critical"))
        if meaning_status == "requires_user_completion" and item_claim_critical != ClaimCriticalStatus.false:
            problems.append(
                f"scene_semantics_by_operation[{index}] still needs a meaning_status: "
                "use user_confirmed_meaning, user_declared_no_scientific_meaning, or keep tool_suggested_meaning only when not claim-critical."
            )
        if status == MeaningStatus.tool_suggested_meaning and item_claim_critical == ClaimCriticalStatus.true:
            problems.append(
                f"scene_semantics_by_operation[{index}] is marked claim-critical; confirm or edit the suggested meaning."
            )
        if (
            status == MeaningStatus.tool_suggested_meaning
            and item_claim_critical == ClaimCriticalStatus.unknown
            and source_operation is not None
            and _operation_has_visual_candidate(source_operation)
        ):
            problems.append(
                f"scene_semantics_by_operation[{index}] is still an unconfirmed tool suggestion; confirm it, mark it presentation only, or set claim_critical to false."
            )
        if (
            status == MeaningStatus.tool_suggested_meaning
            and source_operation is not None
            and _operation_likely_ligand_claim_central(source_operation, answers, semantic)
        ):
            problems.append(
                f"scene_semantics_by_operation[{index}] appears central to a ligand-binding claim; confirm it or mark it as presentation only."
            )
        if (
            _truthy(item.get("needs_author_confirmation", False))
            and item_claim_critical != ClaimCriticalStatus.false
            and status
            not in {
                MeaningStatus.user_confirmed_meaning,
                MeaningStatus.user_declared_no_scientific_meaning,
            }
        ):
            problems.append(
                f"scene_semantics_by_operation[{index}] needs author confirmation; use user_confirmed_meaning, "
                "user_declared_no_scientific_meaning, or set claim_critical to false."
            )
        if meaning_status == "user_confirmed_meaning" and _is_placeholder(item.get("meaning")):
            problems.append(f"scene_semantics_by_operation[{index}].meaning is still unknown.")
        if meaning_status == "user_declared_no_scientific_meaning" and _is_placeholder(
            item.get("no_scientific_meaning_reason")
        ):
            problems.append(
                f"scene_semantics_by_operation[{index}].no_scientific_meaning_reason is still missing."
            )
    for index, item in enumerate(_coerce_list(answers.get("raw_resolutions", []))):
        raw_id = str(item.get("raw_id", "")) if isinstance(item, dict) else ""
        if raw_id and raw_id not in raw_ids:
            problems.append(f"raw_resolutions[{index}] references unknown raw_id: {raw_id}")
        if isinstance(item, dict) and not _is_placeholder(item.get("resolution")):
            allowed = {
                "no_scene_effect",
                "reviewed_no_claim_impact",
                "converted_to_evidence",
                "waived",
                "not_applicable",
            }
            if str(item.get("resolution")) not in allowed:
                problems.append(
                    f"raw_resolutions[{index}].resolution has unsupported value: {item.get('resolution')}. "
                    f"Choose one of: {', '.join(sorted(allowed))}."
                )
    missing_operation_ids = sorted(required_operation_ids - answered_operation_ids)
    for operation_id in missing_operation_ids:
        operation = next(
            (
                item
                for item in semantic.observed_scene_operations
                if item.operation_id == operation_id
            ),
            None,
        )
        problems.append(
            "scene_semantics_by_operation is missing an entry for observed operation: "
            f"{operation_id}{_operation_context_for_problem(operation)}"
        )
    for index, item in enumerate(_coerce_list(answers.get("resource_bindings", []))):
        resource_ref_id = str(item.get("resource_ref_id", "")) if isinstance(item, dict) else ""
        if resource_ref_id and resource_ref_id not in resource_ref_ids:
            problems.append(f"resource_bindings[{index}] references unknown resource_ref_id: {resource_ref_id}")
    for index, item in enumerate(_coerce_list(answers.get("evidence_bindings", []))):
        if not isinstance(item, dict):
            problems.append(f"evidence_bindings[{index}] must be a mapping.")
            continue
        claim_id = item.get("claim_id")
        if claim_id and str(claim_id) not in claim_ids:
            problems.append(f"evidence_bindings[{index}] references unknown claim_id: {claim_id}")
        for operation_id in _coerce_list(item.get("operation_ids", [])):
            if str(operation_id) not in operation_ids:
                problems.append(
                    f"evidence_bindings[{index}] references unknown operation_id: {operation_id}"
                )
        for resource_ref_id in _coerce_list(item.get("resource_ref_ids", [])):
            if str(resource_ref_id) not in resource_ref_ids:
                problems.append(
                    f"evidence_bindings[{index}] references unknown resource_ref_id: {resource_ref_id}"
                )
        for artifact_id in _coerce_list(item.get("evidence_artifact_ids", [])):
            if str(artifact_id) not in artifact_ids:
                problems.append(f"evidence_bindings[{index}] references unknown evidence artifact: {artifact_id}")
    for index, item in enumerate(_coerce_list(answers.get("waivers", []))):
        anchor_id = str(item.get("anchor_id", "")) if isinstance(item, dict) else ""
        if anchor_id and anchor_id not in anchor_ids:
            problems.append(f"waivers[{index}] references unknown anchor_id: {anchor_id}")
    return problems


def _operation_context_for_problem(operation: Any) -> str:
    if operation is None:
        return ""
    pieces = []
    location = getattr(operation, "source_location", None)
    line = getattr(location, "line", None)
    if line is not None:
        pieces.append(f"line {line}")
    native = getattr(operation, "native_command", None)
    if native:
        pieces.append(str(native))
    annotation = getattr(operation, "auto_annotation", None)
    if annotation:
        pieces.append(str(annotation))
    candidate = getattr(operation, "candidate_meaning", None)
    if candidate:
        pieces.append(f"suggestion: {candidate}")
    return " (" + "; ".join(pieces) + ")" if pieces else ""


def _operation_likely_ligand_claim_central(operation: Any, answers: dict[str, Any], semantic: SemanticLayer | None) -> bool:
    if not _has_ligand_binding_claim(answers, semantic):
        return False
    if getattr(operation, "operation", "") not in {"colored", "labeled"}:
        return False
    text = " ".join(
        str(value)
        for value in [
            getattr(operation, "target", ""),
            getattr(operation, "candidate_meaning", ""),
            getattr(operation, "auto_annotation", ""),
        ]
    ).lower()
    return any(token in text for token in ["ligand", "pocket", "binding-site", "binding site"])


def _operation_has_visual_candidate(operation: Any) -> bool:
    candidate = str(getattr(operation, "candidate_meaning", "") or "")
    if (
        candidate
        and "no scientific meaning is inferred" in candidate.lower()
        and not getattr(operation, "needs_author_confirmation", False)
    ):
        return False
    return getattr(operation, "operation", "") in {"colored", "labeled"} and bool(candidate)


def _has_ligand_binding_claim(answers: dict[str, Any], semantic: SemanticLayer | None) -> bool:
    answer_claims = _coerce_list(answers.get("claims", answers.get("claim")))
    if any(
        isinstance(item, dict) and str(item.get("claim_type", "")) == ClaimType.ligand_binding_pose.value
        for item in answer_claims
    ):
        return True
    return bool(semantic and any(claim.claim_type == ClaimType.ligand_binding_pose for claim in semantic.claims))


def _apply_cxc_mvs_answers(semantic: SemanticLayer, answers: dict[str, Any]) -> None:
    if not _uses_native_scene_answer_schema(answers):
        return
    for item in _coerce_list(answers.get("native_identity_mappings", [])):
        if not isinstance(item, dict):
            continue
        native_ref_id = str(item.get("native_ref_id", ""))
        ref = next((ref for ref in semantic.native_references if ref.native_ref_id == native_ref_id), None)
        if ref is None:
            continue
        if "stable_identity" in item:
            ref.stable_identity = str(item["stable_identity"]) if item["stable_identity"] is not None else None
            if ref.stable_identity and ref.stable_identity != "unknown":
                ref.identity_status = "resolved"
        if "target_resolution_status" in item:
            ref.target_resolution_status = TargetResolutionStatus(str(item["target_resolution_status"]))
        if "identity_status" in item:
            ref.identity_status = item["identity_status"]
        if ref.identity_status == "resolved" and _is_placeholder(ref.stable_identity):
            ref.identity_status = "unresolved"
        if "claim_critical" in item:
            ref.claim_critical = _claim_critical_status(item["claim_critical"])
        ref.review_status = ReviewStatus(item.get("review_status", "confirmed"))
    for item in _coerce_list(answers.get("scene_semantics_by_operation", [])):
        if not isinstance(item, dict):
            continue
        operation_ids = [str(value) for value in _coerce_list(item.get("operation_ids", []))]
        source_operation = next(
            (
                operation
                for operation in semantic.observed_scene_operations
                if operation.operation_id in operation_ids
            ),
            None,
        )
        status = MeaningStatus(str(item.get("meaning_status", "requires_user_completion")))
        is_user_reviewed = status in {
            MeaningStatus.user_confirmed_meaning,
            MeaningStatus.user_declared_no_scientific_meaning,
        }
        item_claim_critical = _claim_critical_status(item.get("claim_critical"))
        needs_author_confirmation = False if is_user_reviewed or item_claim_critical == ClaimCriticalStatus.false else _truthy(
            item.get("needs_author_confirmation", getattr(source_operation, "needs_author_confirmation", False))
        )
        if (
            source_operation is not None
            and not is_user_reviewed
            and not item.get("meaning")
            and not item.get("no_scientific_meaning_reason")
            and set(operation_ids) == {source_operation.operation_id}
            and status == source_operation.meaning_status
            and needs_author_confirmation == source_operation.needs_author_confirmation
            and ("claim_critical" not in item or item_claim_critical == source_operation.claim_critical)
            and item.get("encoding_type", source_operation.operation) == source_operation.operation
            and all(
                item.get(field, getattr(source_operation, field)) == getattr(source_operation, field)
                for field in ("auto_annotation", "candidate_meaning", "meaning_confidence", "meaning_basis")
            )
            and not any(set(operation_ids).intersection(entry.operation_ids) for entry in semantic.visual_encoding_semantics)
        ):
            # A generated pending prompt preserves the native observation until
            # the author supplies a meaning or changes its review decision.
            continue
        semantics = VisualEncodingSemantics(
            operation_ids=operation_ids,
            encoding_type=str(item.get("encoding_type", "visual")),
            meaning_status=status,
            meaning=None if item.get("meaning") is None else str(item.get("meaning")),
            auto_annotation=item.get("auto_annotation", getattr(source_operation, "auto_annotation", None)),
            candidate_meaning=item.get("candidate_meaning", getattr(source_operation, "candidate_meaning", None)),
            meaning_confidence=ConfidenceValue(
                str(item.get("meaning_confidence") or getattr(source_operation, "meaning_confidence", ConfidenceValue.unknown).value)
            ),
            meaning_basis=[
                str(value)
                for value in _coerce_list(item.get("meaning_basis", getattr(source_operation, "meaning_basis", [])))
            ],
            needs_author_confirmation=needs_author_confirmation,
            no_scientific_meaning_reason=None
            if item.get("no_scientific_meaning_reason") is None
            else str(item.get("no_scientific_meaning_reason")),
            reviewer=str(item.get("reviewer", "author")) if is_user_reviewed else None,
            reviewed_at=(item.get("reviewed_at") or utc_now()) if is_user_reviewed else None,
        )
        previous = next((
            entry for entry in semantic.visual_encoding_semantics
            if set(semantics.operation_ids) <= set(entry.operation_ids)
        ), None)
        reviewed_fields = ("encoding_type", "meaning", "no_scientific_meaning_reason")
        if previous is not None and is_user_reviewed and any(
            getattr(previous, field) != getattr(semantics, field) for field in reviewed_fields
        ):
            review = _review_fields(
                {**item, "review_status": "confirmed"},
                {"review_status": "confirmed", "reviewer": previous.reviewer, "reviewed_at": previous.reviewed_at},
                content_changed=True,
            )
            semantics.reviewer = review["reviewer"]
            semantics.reviewed_at = review["reviewed_at"]
            if review["review_status"] == ReviewStatus.needs_review:
                semantics.meaning_status = MeaningStatus.requires_user_completion
                semantics.needs_author_confirmation = True
                is_user_reviewed = False
        meaning_changed = previous != semantics
        _upsert_visual_semantics(semantic.visual_encoding_semantics, semantics)
        for operation in semantic.observed_scene_operations:
            if operation.operation_id in semantics.operation_ids:
                operation.meaning_status = semantics.meaning_status
                if meaning_changed:
                    operation.auto_annotation = semantics.auto_annotation or operation.auto_annotation
                    operation.candidate_meaning = semantics.candidate_meaning or operation.candidate_meaning
                    operation.meaning_confidence = semantics.meaning_confidence
                    operation.meaning_basis = semantics.meaning_basis or operation.meaning_basis
                operation.needs_author_confirmation = semantics.needs_author_confirmation
                if "claim_critical" in item:
                    operation.claim_critical = _claim_critical_status(item["claim_critical"])
                if is_user_reviewed:
                    operation.review_status = ReviewStatus.confirmed
                elif meaning_changed:
                    operation.review_status = ReviewStatus.needs_review
    for item in _coerce_list(answers.get("raw_resolutions", [])):
        if not isinstance(item, dict):
            continue
        raw = next((raw for raw in semantic.raw_native_observations if raw.raw_id == str(item.get("raw_id", ""))), None)
        if raw is None:
            continue
        if "claim_critical" in item:
            raw.claim_critical = _claim_critical_status(item["claim_critical"])
        if "resolution" in item:
            resolution = str(item.get("resolution") or "unknown")
            raw.resolution = resolution  # type: ignore[assignment]
            if resolution in {"no_scene_effect", "reviewed_no_claim_impact", "not_applicable"}:
                raw.claim_critical = ClaimCriticalStatus.false
        raw.review_status = ReviewStatus(item.get("review_status", "confirmed"))
    for item in _coerce_list(answers.get("resource_bindings", [])):
        if not isinstance(item, dict):
            continue
        resource = next(
            (resource for resource in semantic.resource_references if resource.resource_ref_id == str(item.get("resource_ref_id", ""))),
            None,
        )
        if resource is None:
            continue
        if "claim_critical" in item:
            resource.claim_critical = _claim_critical_status(item["claim_critical"])
    for index, item in enumerate(_coerce_list(answers.get("evidence_bindings", []))):
        if not isinstance(item, dict):
            continue
        binding = EvidenceBinding(
                binding_id=str(
                    item.get("binding_id")
                    or _answer_object_id(semantic, "evidence-binding", index)
                ),
                claim_id=None if item.get("claim_id") is None else str(item.get("claim_id")),
                operation_ids=[str(value) for value in _coerce_list(item.get("operation_ids", []))],
                resource_ref_ids=[str(value) for value in _coerce_list(item.get("resource_ref_ids", []))],
                evidence_artifact_ids=[str(value) for value in _coerce_list(item.get("evidence_artifact_ids", []))],
                evidence_type=str(item.get("evidence_type", "manual_rationale")),
                method_context=dict(item.get("method_context", {})),
                support_status=str(item.get("support_status", "user_confirmed")),
            )
        _upsert_evidence_binding(semantic.evidence_bindings, binding)
    for item in _coerce_list(answers.get("waivers", [])):
        if not isinstance(item, dict):
            continue
        waiver = Waiver(
                rule_id=str(item.get("rule_id", "UNKNOWN")),
                scope=str(item.get("scope", item.get("anchor_id", "unknown"))),
                anchor_id=None if item.get("anchor_id") is None else str(item.get("anchor_id")),
                reason=str(item.get("reason", "No reason provided.")),
                reviewer=str(item.get("reviewer", "author")),
                reviewed_at=item.get("reviewed_at") or utc_now(),
                max_export_mode=str(item.get("max_export_mode", "draft")),
            )
        identity = (waiver.rule_id, waiver.scope, waiver.anchor_id)
        for index, previous in enumerate(semantic.provenance.waivers):
            if (previous.rule_id, previous.scope, previous.anchor_id) == identity:
                semantic.provenance.waivers[index] = waiver
                break
        else:
            semantic.provenance.waivers.append(waiver)


def _claim_critical_status(value: Any) -> ClaimCriticalStatus:
    if isinstance(value, bool):
        return ClaimCriticalStatus.true if value else ClaimCriticalStatus.false
    text = str(value).lower()
    if text in {"true", "yes", "claim_critical", "figure_central", "important", "affects_figure"}:
        return ClaimCriticalStatus.true
    if text in {"false", "no", "not_claim_critical", "not_figure_central", "presentation_only"}:
        return ClaimCriticalStatus.false
    return ClaimCriticalStatus.unknown


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "needs_author_confirmation"}


def _apply_package(semantic: SemanticLayer, data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        return
    for key in ["title", "creator", "license", "profile", "description"]:
        if key in data and data[key] is not None:
            setattr(semantic.package, key, str(data[key]))


def _apply_reuse(semantic: SemanticLayer, data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        return
    if "license" in data:
        semantic.reuse.license = str(data["license"])
        semantic.package.license = str(data["license"])
    if "citation" in data:
        semantic.reuse.citation = str(data["citation"]) if data["citation"] is not None else None
    if "restrictions" in data:
        semantic.reuse.restrictions = [str(item) for item in _coerce_list(data["restrictions"])]
    if "reviewer" in data:
        semantic.reuse.reviewer = data["reviewer"]
    if data:
        semantic.reuse.reviewed_at = data.get("reviewed_at", utc_now())


def _register_answer_artifacts(
    root: Path | None,
    semantic: SemanticLayer,
    items: Any,
    answer_base: Path | None,
    registrations: list[tuple[Path, dict[str, Any]]],
) -> None:
    for item in _coerce_list(items):
        if not isinstance(item, dict):
            continue
        if item.get("url"):
            register_remote_artifact(
                semantic,
                str(item["url"]),
                role=item.get("role"),
                expected_sha256=item.get("sha256"),
            )
            continue
        if not item.get("path"):
            continue
        if item.get("role") is not None:
            ArtifactRole(item["role"])
        if root is None:
            continue
        source = _resolve_answer_path(root, answer_base, str(item["path"]))
        if not source.exists():
            raise ValueError(
                f"Artifact path not found: {item['path']}. "
                f"Looked at {root / str(item['path'])} and {answer_base / str(item['path'])}. "
                "Put the file next to the answers file, put it inside the package, or use a url entry."
                f"{windows_path_hint(item['path'])}"
            )
        _prepare_local_artifact(
            root, semantic, source, registrations,
            role=item.get("role"), detached=bool(item.get("detached", False)),
        )


def _prepare_local_artifact(
    root: Path,
    semantic: SemanticLayer,
    source: Path,
    registrations: list[tuple[Path, dict[str, Any]]],
    *,
    role: str | None = None,
    detached: bool = False,
):
    options = {
        "role": role,
        "copy": True,
        "detached": detached,
        "relative_destination": replay_destination_for(semantic, source),
    }
    artifact = register_local_artifact(root, semantic, source, dry_run=True, **options)
    registrations.append((source, options))
    return artifact


def _apply_entities(semantic: SemanticLayer, items: Any) -> None:
    for index, item in enumerate(_coerce_list(items)):
        if not isinstance(item, dict):
            continue
        entity_id = str(item.get("id") or _answer_object_id(semantic, "entity", index))
        previous = next((entry for entry in semantic.entities if entry.id == entity_id), None)
        values = previous.model_dump() if previous else {"review_status": "confirmed"}
        values.update({key: value for key, value in item.items() if key in Entity.model_fields})
        values["id"] = entity_id
        if "source_artifact_ids" in item:
            values["source_artifact_ids"] = [str(value) for value in _coerce_list(item["source_artifact_ids"])]
        entity = Entity.model_validate(values)
        _upsert(semantic.entities, entity)


def _apply_selections(semantic: SemanticLayer, items: Any) -> None:
    for index, item in enumerate(_coerce_list(items)):
        if not isinstance(item, dict):
            continue
        selection_id = str(item.get("id") or _answer_object_id(semantic, "selection", index))
        previous = next((entry for entry in semantic.selections if entry.id == selection_id), None)
        values = previous.model_dump() if previous else {"name": "selection", "review_status": "confirmed"}
        values.update({key: value for key, value in item.items() if key in Selection.model_fields})
        selector = item.get("native_selector", previous.native_selector.value if previous else "unknown")
        selector_data = selector if isinstance(selector, dict) else {"value": str(selector)}
        changed = previous is not None and selector_data.get("value", previous.native_selector.value) != previous.native_selector.value
        selector_values = previous.native_selector.model_dump() if previous and not changed else {
            "value": "unknown", "source_type": SourceType.user_asserted,
            "confidence": ConfidenceValue.unknown,
            "review_status": item.get("review_status", "confirmed"),
        }
        selector_values.update(selector_data)
        values.update(id=selection_id, native_selector=ProvenancedString.model_validate(selector_values))
        if "entity_ids" in item:
            values["entity_ids"] = [str(value) for value in _coerce_list(item["entity_ids"])]
        selection = Selection.model_validate(values)
        if changed and "runtime_verification" in selection.extensions:
            selection.extensions["runtime_verification"] = "unverified"
        _upsert(semantic.selections, selection)


def _apply_scene_semantics(
    semantic: SemanticLayer, items: Any, *, validate_references: bool = True
) -> None:
    for item in _coerce_list(items):
        if not isinstance(item, dict):
            continue
        target_ids = [str(value) for value in _coerce_list(item.get("scene_ids", []))]
        target_scenes = [
            scene for scene in semantic.scenes if not target_ids or scene.id in target_ids
        ]
        if not target_scenes and semantic.scenes and not target_ids:
            target_scenes = semantic.scenes
        if "render_artifact_ids" in item:
            render_ids = [
                str(value) for value in _coerce_list(item.get("render_artifact_ids", []))
            ]
            known_render_ids = {
                artifact.id
                for artifact in semantic.artifacts
                if artifact.role.value == "render_image"
            }
            unknown = sorted(set(render_ids) - known_render_ids)
            if unknown and validate_references:
                raise ValueError(
                    "Scene answer references unknown rendered-image artifact IDs: "
                    + ", ".join(unknown)
                )
            if render_ids and len(semantic.scenes) > 1 and not target_ids:
                raise ValueError(
                    "Choose explicit scene_ids to link each rendered image to its matching scene."
                )
            for scene in target_scenes:
                scene.render_artifact_ids = sorted(set(render_ids))
        if not any(key in item for key in ("color_meanings", "label_meanings", "notes")):
            continue
        for scene in target_scenes:
            recorded = scene.extensions.get("user_scene_semantics", [])
            previous = recorded[-1] if recorded else None
            previous_content = previous or {}
            semantics = {
                "color_meanings": dict(item.get("color_meanings", previous_content.get("color_meanings", {}))),
                "label_meanings": dict(item.get("label_meanings", previous_content.get("label_meanings", {}))),
                "notes": str(item.get("notes", previous_content.get("notes", ""))).strip(),
            }
            if previous is None and not any(semantics.values()):
                continue
            changed = previous is not None and any(previous.get(key) != value for key, value in semantics.items())
            review = _review_fields(item, previous, content_changed=changed)
            scene_semantics = {**semantics, **review, "review_status": review["review_status"].value}
            scene.extensions["user_scene_semantics"] = [scene_semantics]
            _apply_legacy_visual_meanings_to_operations(semantic, scene, scene_semantics, previous_content)


def _legacy_operation_meaning(operation: Any, semantics: dict[str, Any]) -> str | None:
    color_meanings = semantics.get("color_meanings", {})
    label_meanings = semantics.get("label_meanings", {})
    if operation.operation == "colored":
        color = str(operation.details.get("color", ""))
        return str(color_meanings[color]) if color in color_meanings else None
    if operation.operation == "labeled":
        label = str(operation.details.get("label_expression") or operation.target)
        return str(label_meanings[label]) if label in label_meanings else None
    return None


def _apply_legacy_visual_meanings_to_operations(
    semantic: SemanticLayer, scene: Scene, semantics: dict[str, Any], previous: dict[str, Any],
) -> None:
    for operation in semantic.observed_scene_operations:
        scene_id = operation.details.get("scene_id")
        belongs_to_scene = (
            scene_id == scene.id if scene_id
            else operation.source_location.artifact_id in scene.native_artifact_ids
        )
        if not belongs_to_scene:
            continue
        existing = next((
            entry for entry in semantic.visual_encoding_semantics
            if operation.operation_id in entry.operation_ids
        ), None)
        previous_meaning = _legacy_operation_meaning(operation, previous)
        if existing is not None and (
            existing.operation_ids != [operation.operation_id]
            or not previous_meaning or existing.meaning != previous_meaning
        ):
            # An independently recorded operation meaning remains authoritative.
            continue
        meaning = _legacy_operation_meaning(operation, semantics)
        if not meaning:
            if existing is not None:
                semantic.visual_encoding_semantics.remove(existing)
                operation.meaning_status = MeaningStatus.requires_user_completion
                operation.review_status = ReviewStatus.needs_review
                operation.needs_author_confirmation = True
            continue
        reviewed = semantics.get("review_status") in {"confirmed", "human_accepted"}
        updated = VisualEncodingSemantics(
            operation_ids=[operation.operation_id],
            encoding_type=operation.operation,
            meaning_status=MeaningStatus.user_confirmed_meaning if reviewed else MeaningStatus.requires_user_completion,
            meaning=meaning,
            reviewer=semantics.get("reviewer") if reviewed else None,
            reviewed_at=semantics.get("reviewed_at") if reviewed else None,
            needs_author_confirmation=not reviewed,
        )
        if existing is None:
            semantic.visual_encoding_semantics.append(updated)
        else:
            updated = existing.model_copy(update={
                field: getattr(updated, field)
                for field in ("meaning", "meaning_status", "reviewer", "reviewed_at", "needs_author_confirmation")
            })
            semantic.visual_encoding_semantics[semantic.visual_encoding_semantics.index(existing)] = updated
        operation.meaning_status = MeaningStatus.user_confirmed_meaning if reviewed else MeaningStatus.requires_user_completion
        operation.review_status = ReviewStatus.confirmed if reviewed else ReviewStatus.needs_review
        operation.needs_author_confirmation = not reviewed


def _apply_claim(
    semantic: SemanticLayer,
    data: dict[str, Any],
    *,
    answer_index: int = 0,
    answer_count: int = 1,
) -> str:
    if not data.get("id") and len(semantic.claims) > 1:
        raise ValueError("claim.id is required when the package contains multiple claims; choose an existing ID or a new ID.")
    claim_id = str(
        data.get("id")
        or (
            semantic.claims[0].id
            if answer_count == 1 and len(semantic.claims) == 1
            else _answer_object_id(semantic, "claim", answer_index)
        )
    )
    previous = next((item for item in semantic.claims if item.id == claim_id), None)
    values = previous.model_dump() if previous else {"claim_status": "reviewable"}
    values.update({key: value for key, value in data.items() if key in Claim.model_fields})
    for field in ("scene_ids", "evidence_ids", "uncertainty_ids"):
        if field in data:
            values[field] = [str(value) for value in _coerce_list(data[field])]
    text_data = data.get("claim_text", data.get("text"))
    text_values = previous.claim_text.model_dump() if previous else {"value": "unknown"}
    if isinstance(text_data, dict):
        text_values.update(text_data)
    elif text_data is not None:
        text_values["value"] = str(text_data)
    text_metadata = text_data.copy() if isinstance(text_data, dict) else {}
    for key in ("source_type", "source_location", "confidence", "review_status", "reviewer", "reviewed_at"):
        if key in data:
            text_metadata[key] = data[key]
    if previous and text_values["value"] != previous.claim_text.value:
        for key, default in (("source_type", "user_asserted"), ("source_location", None), ("confidence", "unknown")):
            if key not in text_metadata:
                text_values[key] = default
    text_values.update(text_metadata)
    candidate_values = {**values, "id": claim_id, "claim_text": text_values}
    candidate = Claim.model_validate(candidate_values)
    changed = previous is not None and _reviewed_content(candidate) != _reviewed_content(previous)
    text_values.update(_review_fields(text_metadata, previous.claim_text if previous else None, content_changed=changed))
    values.update(
        id=claim_id,
        claim_text=ProvenancedString.model_validate(text_values),
        review_status=text_values["review_status"],
    )
    claim = Claim.model_validate(values)
    if previous is None and not claim.scene_ids and len(semantic.scenes) == 1:
        claim.scene_ids = [scene.id for scene in semantic.scenes]
    _upsert(semantic.claims, claim)
    return claim.id


def _apply_evidence(
    root: Path | None,
    semantic: SemanticLayer,
    items: Any,
    answer_base: Path | None,
    claim_ids: list[str],
    registrations: list[tuple[Path, dict[str, Any]]],
) -> list[str]:
    evidence_ids: list[str] = []
    for index, item in enumerate(_coerce_list(items)):
        if not isinstance(item, dict):
            continue
        evidence_id = str(item.get("id") or _answer_object_id(semantic, "evidence", index))
        previous = next((entry for entry in semantic.evidence if entry.id == evidence_id), None)
        source_fields = ("source_artifact_ids", "source_artifact_roles", "source_artifact_paths")
        replacing_sources = any(field in item for field in source_fields)
        source_ids = list(previous.source_artifact_ids) if previous and not replacing_sources else []
        source_ids.extend(str(value) for value in _coerce_list(item.get("source_artifact_ids", [])))
        for role in _coerce_list(item.get("source_artifact_roles", [])):
            ArtifactRole(role)
        source_ids.extend(_artifact_ids_for_roles(semantic, _coerce_list(item.get("source_artifact_roles", []))))
        for source_path in _coerce_list(item.get("source_artifact_paths", [])):
            artifact = find_artifact_by_path(semantic, str(source_path))
            if artifact is None and root is not None:
                resolved = _resolve_answer_path(root, answer_base, str(source_path))
                if resolved.exists():
                    artifact = _prepare_local_artifact(
                        root, semantic, resolved, registrations, role=item.get("artifact_role"),
                    )
            if artifact is not None:
                source_ids.append(artifact.id)
        values = previous.model_dump() if previous else {
            "generated_by": "author", "method_name": "manual review", "claim_ids": claim_ids,
        }
        values.update({key: value for key, value in item.items() if key in Evidence.model_fields})
        values.update(id=evidence_id, source_artifact_ids=list(dict.fromkeys(source_ids)))
        if previous is None or set(source_ids) != set(previous.source_artifact_ids):
            values["fixity_status"] = item.get("fixity_status", "available" if source_ids else "unknown")
        for field in ("claim_ids", "target_entity_ids", "target_selection_ids", "limitations", "alternative_explanations"):
            if field in item:
                values[field] = [str(value) for value in _coerce_list(item[field])]
        if "units" in item and isinstance(item["units"], dict):
            values["units"] = {str(key): str(value) for key, value in item["units"].items()}
        evidence = Evidence.model_validate(values)
        changed = previous is not None and _reviewed_content(evidence) != _reviewed_content(previous)
        evidence = evidence.model_copy(update=_review_fields(item, previous, content_changed=changed))
        _upsert(semantic.evidence, evidence)
        evidence_ids.append(evidence.id)
    return evidence_ids


def _apply_uncertainty(semantic: SemanticLayer, items: Any, claim_ids: list[str]) -> list[str]:
    uncertainty_ids: list[str] = []
    for index, item in enumerate(_coerce_list(items)):
        if isinstance(item, str):
            item = {"statement": item}
        if not isinstance(item, dict):
            continue
        uncertainty_id = str(item.get("id") or _answer_object_id(semantic, "uncertainty", index))
        previous = next((entry for entry in semantic.uncertainty if entry.id == uncertainty_id), None)
        values = previous.model_dump() if previous else {"claim_ids": claim_ids}
        values.update({key: value for key, value in item.items() if key in Uncertainty.model_fields})
        values["id"] = uncertainty_id
        for field in ("claim_ids", "alternative_explanations"):
            if field in item:
                values[field] = [str(value) for value in _coerce_list(item[field])]
        uncertainty = Uncertainty.model_validate(values)
        changed = previous is not None and _reviewed_content(uncertainty) != _reviewed_content(previous)
        uncertainty = uncertainty.model_copy(update=_review_fields(item, previous, content_changed=changed))
        _upsert(semantic.uncertainty, uncertainty)
        uncertainty_ids.append(uncertainty.id)
    return uncertainty_ids


def _reviewed_content(record: Any) -> dict[str, Any]:
    """Scientific content covered by a record's review, excluding review bookkeeping."""
    values = record.model_dump(mode="json", exclude={
        "id", "review_status", "reviewer", "reviewed_at", "extensions", "fixity_status", "claim_status",
    })
    if isinstance(record, Claim):
        values["claim_text"] = _reviewed_content(record.claim_text)
    return values


def _review_fields(
    data: dict[str, Any], previous: Any = None, *, content_changed: bool = False,
) -> dict[str, Any]:
    """Carry a review forward only while its scientific content is unchanged."""
    recorded = previous if isinstance(previous, dict) else previous.model_dump() if previous else {}
    previous_status = ReviewStatus(recorded.get("review_status", "confirmed"))
    status = ReviewStatus(data.get("review_status", previous_status))
    reviewed = status in {ReviewStatus.confirmed, ReviewStatus.human_accepted}
    if previous is not None and content_changed:
        fresh_review = reviewed and "review_status" in data and (
            "reviewed_at" not in data
            or bool(data["reviewed_at"] and data["reviewed_at"] != recorded.get("reviewed_at"))
        )
        if fresh_review:
            return {
                "review_status": status,
                "reviewer": data.get("reviewer") or "author",
                "reviewed_at": data.get("reviewed_at") or utc_now(),
            }
        return {"review_status": ReviewStatus.needs_review if reviewed else status, "reviewer": None, "reviewed_at": None}
    changed = previous is None or status != previous_status
    return {
        "review_status": status,
        "reviewer": data.get("reviewer", ("author" if reviewed else None) if changed else recorded.get("reviewer")),
        "reviewed_at": data.get("reviewed_at", (utc_now() if reviewed else None) if changed else recorded.get("reviewed_at")),
    }


def _apply_software(semantic: SemanticLayer, items: Any) -> None:
    for index, item in enumerate(_coerce_list(items)):
        if not isinstance(item, dict):
            continue
        software_id = str(item.get("id") or _answer_object_id(semantic, "software", index))
        previous = next((entry for entry in semantic.software_environment if entry.id == software_id), None)
        values = previous.model_dump() if previous else {"name": "unknown"}
        values.update({key: value for key, value in item.items() if key in SoftwareEnvironment.model_fields})
        values["id"] = software_id
        software = SoftwareEnvironment.model_validate(values)
        _upsert(semantic.software_environment, software)


def _mark_tasks_answered(semantic: SemanticLayer) -> None:
    if not isinstance(semantic.provenance, Provenance):
        semantic.provenance = Provenance()


def _artifact_ids_for_roles(semantic: SemanticLayer, roles: list[Any]) -> list[str]:
    wanted = {str(role) for role in roles}
    return [artifact.id for artifact in semantic.artifacts if artifact.role.value in wanted]


def _resolve_answer_path(root: Path, answer_base: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    package_candidate = root / candidate
    if package_candidate.exists():
        return package_candidate
    return answer_base / candidate


def _coerce_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _answer_object_id(semantic: SemanticLayer, prefix: str, index: int) -> str:
    identity = f"{semantic.semantic_layer_id}:answers:{prefix}:{index}"
    return f"{prefix}:answers:{uuid5(NAMESPACE_URL, identity).hex[:12]}"


def _upsert(items: list[Any], item: Any) -> None:
    for index, existing in enumerate(items):
        if getattr(existing, "id", None) == getattr(item, "id", None):
            items[index] = item
            return
    items.append(item)


def _upsert_visual_semantics(
    items: list[VisualEncodingSemantics],
    item: VisualEncodingSemantics,
) -> None:
    operation_ids = set(item.operation_ids)
    updated = []
    inserted = False
    for existing in items:
        if operation_ids.intersection(existing.operation_ids):
            remaining = [identity for identity in existing.operation_ids if identity not in operation_ids]
            if remaining:
                updated.append(existing.model_copy(update={"operation_ids": remaining}))
            if not inserted:
                updated.append(item)
                inserted = True
        else:
            updated.append(existing)
    if not inserted:
        updated.append(item)
    items[:] = updated


def _upsert_evidence_binding(items: list[EvidenceBinding], item: EvidenceBinding) -> None:
    for index, existing in enumerate(items):
        if existing.binding_id == item.binding_id:
            items[index] = item
            return
    items.append(item)


def ensure_scene_for_images(
    semantic: SemanticLayer,
    render_ids: list[str] | None = None,
    *,
    scene_id: str | None = None,
) -> None:
    render_ids = render_ids or [
        artifact.id for artifact in semantic.artifacts if artifact.role.value == "render_image"
    ]
    if not render_ids:
        return
    if scene_id is not None:
        scene = next((item for item in semantic.scenes if item.id == scene_id), None)
        if scene is None:
            raise ValueError(f"Unknown scene id for rendered panel: {scene_id}")
        scene.render_artifact_ids = sorted(set(scene.render_artifact_ids + render_ids))
        return
    if semantic.scenes:
        if len(semantic.scenes) == 1:
            scene = semantic.scenes[0]
            scene.render_artifact_ids = sorted(set(scene.render_artifact_ids + render_ids))
        else:
            artifacts = {artifact.id: artifact for artifact in semantic.artifacts}
            linked = {aid for scene in semantic.scenes for aid in scene.render_artifact_ids}
            for render_id in render_ids:
                image = artifacts.get(render_id)
                if render_id in linked or image is None or not image.path:
                    continue
                matches = [
                    scene for scene in semantic.scenes
                    if any(
                        aid in artifacts and artifacts[aid].path
                        and Path(artifacts[aid].path).stem == Path(image.path).stem
                        for aid in scene.native_artifact_ids
                    )
                ]
                if len(matches) == 1:
                    matches[0].render_artifact_ids.append(render_id)
        return
    semantic.scenes.append(
        Scene(
            id=f"scene:{uuid4().hex[:12]}",
            description="Static image scene requiring author completion.",
            render_artifact_ids=render_ids,
            parse_confidence=ConfidenceValue.unknown,
            review_status=ReviewStatus.needs_review,
        )
    )
