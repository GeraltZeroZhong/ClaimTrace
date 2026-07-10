"""Completion templates and answer application."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from claimtrace import _simple_yaml
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
    ClaimType,
    ConfidenceValue,
    EvidenceKind,
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
            "claim_text": "TODO: write the figure or panel message",
            "claim_type": "simple_structure_view",
            "figure_ref": "TODO: add figure/panel label",
            "scope": "panel",
        },
        "artifacts": [
            {"path": "model.cif", "role": "structure"},
        ],
        "entities": [],
        "evidence": [
            {
                "evidence_kind": "manual_rationale",
                "method_name": "TODO: name the review or evidence method",
                "result_summary": "TODO: explain which attached files support this panel and how",
                "source_artifact_roles": ["native_script", "render_image", "structure"],
            }
        ],
        "scene": {
            "color_meanings": {},
            "label_meanings": {},
            "notes": "ClaimTrace records literal colors and labels automatically. Tool suggestions are not author-confirmed; confirm figure-central meanings or mark them presentation only.",
        },
        "uncertainty": {
            "category": "scope",
            "statement": "This package records a visual structure view and does not assert a molecular mechanism.",
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
            "claim_text": "TODO: write the exact ligand/pocket claim for this panel",
            "claim_type": "ligand_binding_pose",
            "figure_ref": "TODO: add figure/panel label",
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
                "result_summary": "TODO: summarize the contact/distance evidence and file names",
                "source_artifact_roles": ["contact_table", "structure"],
                "target_entity_ids": ["entity:ligand:X", "entity:binding-site"],
            }
        ],
        "scene": {
            "color_meanings": {},
            "label_meanings": {},
            "notes": "Displayed, hidden, colored and labeled objects are auto-extracted from native artifacts. Confirm ligand/pocket visual meanings that support the figure message.",
        },
        "uncertainty": {
            "category": "alternative_pose",
            "statement": "TODO: state whether alternative poses, waters/cofactors or other limits were assessed",
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
                field_use="Adds author context that native visualization files do not contain.",
                examples=_section_examples(section, template),
                accepted_values=["unknown", "not_applicable", "short author-provided value"],
                blocking=section in {"claim", "evidence"},
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
                "presentation only: color is for contrast; no scientific category implied",
            ]
        return [
            "confirm: cartoon/sticks distinguish the objects described in the panel",
            "edit: label identifies the chain or residue readers should notice",
            "presentation only: color is for contrast; no scientific category implied",
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
            return ["alternative pose not assessed", "water/cofactor context not shown in this panel"]
        return ["not_applicable: this is a simple structure view", "no mechanism or interaction strength is asserted"]
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
        }
    )
    _make_artifacts_package_aware(data, semantic)
    _make_evidence_package_aware(data, semantic)
    if semantic.selections:
        data["selections"] = [
            {
                "id": selection.id,
                "name": selection.name,
                "native_selector": selection.native_selector.value,
                "entity_ids": selection.entity_ids,
                "claim_critical": selection.claim_critical,
                "review_status": selection.review_status.value,
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
                "stable_identity": ref.stable_identity or "unknown",
                "target_resolution_status": ref.target_resolution_status.value,
                "claim_critical": ref.claim_critical.value,
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
        data["raw_resolutions"] = [
            {
                "raw_id": raw.raw_id,
                "native_text": raw.native_text,
                "reason": raw.reason,
                "claim_critical": raw.claim_critical.value,
                "resolution": "unknown",
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
        data["evidence_bindings"] = []
        data["waivers"] = []
    return data


def dump_package_answer_template(semantic: SemanticLayer, template: str = "simple-structure-view") -> str:
    header = "\n".join(
        [
            "# ClaimTrace answers",
            "# Fill claim.claim_text and claim.figure_ref first. Fill evidence[].method_name and result_summary only for evidence you actually have.",
            "# artifacts: leave empty when init/add-artifact already included the files; otherwise add paths to copy.",
            "# entities/selections: fill only molecules, chains, residues or selections readers must identify.",
            "# scene_semantics_by_operation: edit only entries listed here; they are keyed by operation_ids.",
            "# ClaimTrace auto-annotates literal color/label/display facts. The candidate_meaning field is a tool suggestion, not an author-confirmed meaning.",
            "# For each color/label suggestion choose one:",
            "#   meaning_status: user_confirmed_meaning          # visual choice carries the figure message",
            "#   meaning_status: user_declared_no_scientific_meaning  # contrast/readability only",
            "#   claim_critical: false                            # not central to this figure or panel",
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
    answer_base = answer_base or root
    _apply_cxc_mvs_answers(semantic, answers)
    _apply_package(semantic, answers.get("package", {}))
    _apply_reuse(semantic, answers.get("reuse", {}))
    _register_answer_artifacts(root, semantic, answers.get("artifacts", []), answer_base)
    _apply_entities(semantic, answers.get("entities", []))
    _apply_selections(semantic, answers.get("selections", []))
    _apply_scene_semantics(semantic, answers.get("scenes", answers.get("scene", {})))
    claims = _coerce_list(answers.get("claims", answers.get("claim")))
    claim_ids = [_apply_claim(semantic, item) for item in claims if isinstance(item, dict)]
    evidence_ids = _apply_evidence(root, semantic, answers.get("evidence", []), answer_base, claim_ids)
    uncertainty_ids = _apply_uncertainty(semantic, answers.get("uncertainty", []), claim_ids)
    for claim in semantic.claims:
        if claim.id in claim_ids or (not claim_ids and claim.review_status in {ReviewStatus.confirmed, ReviewStatus.human_accepted}):
            claim.evidence_ids = sorted(set(claim.evidence_ids + evidence_ids))
            claim.uncertainty_ids = sorted(set(claim.uncertainty_ids + uncertainty_ids))
            if not claim.scene_ids:
                claim.scene_ids = [scene.id for scene in semantic.scenes]
    _apply_software(semantic, answers.get("software", []))
    _mark_tasks_answered(semantic)
    semantic.add_activity("completion", "Applied author completion answers.")
    return semantic


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
    if _uses_native_scene_answer_schema(answers) or (semantic is not None and _has_cxc_mvs_anchors(semantic)):
        problems.extend(_check_cxc_mvs_answers(answers, semantic))
    if "claim" not in answers and "claims" not in answers:
        problems.append("Missing claim or claims section.")
    if "evidence" not in answers:
        problems.append("Missing evidence section.")
    if "reuse" not in answers:
        problems.append("Missing reuse section.")
    problems.extend(_check_required_content(answers, semantic))
    if root is not None:
        problems.extend(_check_answer_artifact_paths(answers, root, answer_base or root))
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
    if evidence and all(
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
    if uncertainty and all(
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


def _check_required_content(answers: dict[str, Any], semantic: SemanticLayer | None) -> list[str]:
    problems: list[str] = []
    claims = _coerce_list(answers.get("claims", answers.get("claim")))
    claim_types = {
        str(item.get("claim_type", ""))
        for item in claims
        if isinstance(item, dict)
    }
    for index, item in enumerate(claims):
        if not isinstance(item, dict):
            problems.append(f"claim[{index}] must be a mapping.")
            continue
        if _is_placeholder(item.get("claim_text", item.get("text"))):
            problems.append("claim.claim_text is still unknown; write the figure or panel message.")
        if _is_placeholder(item.get("figure_ref")):
            problems.append("claim.figure_ref is still unknown; write the figure or panel label.")
    for index, item in enumerate(_coerce_list(answers.get("evidence", []))):
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
            units = item.get("units", {})
            threshold = thresholds.get("distance") if isinstance(thresholds, dict) else None
            unit = units.get("distance") if isinstance(units, dict) else None
            try:
                valid_threshold = float(threshold) > 0
            except (TypeError, ValueError):
                valid_threshold = False
            if not valid_threshold:
                problems.append(
                    f"evidence[{index}].thresholds.distance needs a positive numeric cutoff."
                )
            if _is_placeholder(unit):
                problems.append(
                    f"evidence[{index}].units.distance is still unknown; record a unit such as angstrom."
                )
    if ClaimType.ligand_binding_pose.value in claim_types:
        entities = _coerce_list(answers.get("entities", []))
        if not entities:
            problems.append("A ligand-binding answer needs ligand and binding-site/residue entities.")
        for index, item in enumerate(entities):
            if not isinstance(item, dict):
                problems.append(f"entities[{index}] must be a mapping.")
            elif _is_placeholder(item.get("stable_identity")):
                problems.append(
                    f"entities[{index}].stable_identity is still unknown; record the model/chain/residue or ligand identity."
                )
    uncertainty = _coerce_list(answers.get("uncertainty", []))
    if ClaimType.ligand_binding_pose.value in claim_types and not uncertainty:
        problems.append("A ligand-binding answer needs a caveat or alternative-pose statement.")
    for index, item in enumerate(uncertainty):
        statement = item.get("statement") if isinstance(item, dict) else item
        if _is_placeholder(statement):
            problems.append(f"uncertainty[{index}].statement is still unknown.")
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


def _check_cxc_mvs_answers(answers: dict[str, Any], semantic: SemanticLayer | None) -> list[str]:
    problems: list[str] = []
    if semantic is None:
        return problems
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
    native_ref_ids = {ref.native_ref_id for ref in semantic.native_references}
    raw_ids = {raw.raw_id for raw in semantic.raw_native_observations}
    resource_ref_ids = {resource.resource_ref_id for resource in semantic.resource_references}
    artifact_ids = {artifact.id for artifact in semantic.artifacts}
    claim_ids = {claim.id for claim in semantic.claims}
    claim_ids.update(
        str(item.get("id"))
        for item in _coerce_list(answers.get("claims", answers.get("claim")))
        if isinstance(item, dict) and item.get("id")
    )
    anchor_ids = operation_ids | native_ref_ids | raw_ids | resource_ref_ids | artifact_ids
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
            ref.stable_identity = str(item["stable_identity"])
            if ref.stable_identity and ref.stable_identity != "unknown":
                ref.identity_status = "resolved"
        if "target_resolution_status" in item:
            ref.target_resolution_status = TargetResolutionStatus(str(item["target_resolution_status"]))
        if "claim_critical" in item:
            ref.claim_critical = _claim_critical_status(item["claim_critical"])
        ref.review_status = ReviewStatus.confirmed
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
        semantics = VisualEncodingSemantics(
            operation_ids=operation_ids,
            encoding_type=str(item.get("encoding_type", "visual")),
            meaning_status=status,
            meaning=None if item.get("meaning") is None else str(item.get("meaning")),
            auto_annotation=str(item.get("auto_annotation") or getattr(source_operation, "auto_annotation", "") or ""),
            candidate_meaning=str(item.get("candidate_meaning") or getattr(source_operation, "candidate_meaning", "") or ""),
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
            reviewed_at=utc_now() if is_user_reviewed else None,
        )
        _upsert_visual_semantics(semantic.visual_encoding_semantics, semantics)
        for operation in semantic.observed_scene_operations:
            if operation.operation_id in semantics.operation_ids:
                operation.meaning_status = semantics.meaning_status
                operation.auto_annotation = semantics.auto_annotation or operation.auto_annotation
                operation.candidate_meaning = semantics.candidate_meaning or operation.candidate_meaning
                operation.meaning_confidence = semantics.meaning_confidence
                operation.meaning_basis = semantics.meaning_basis or operation.meaning_basis
                operation.needs_author_confirmation = semantics.needs_author_confirmation
                if "claim_critical" in item:
                    operation.claim_critical = _claim_critical_status(item["claim_critical"])
                if is_user_reviewed:
                    operation.review_status = ReviewStatus.confirmed
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
        raw.review_status = ReviewStatus.confirmed
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
        semantic.provenance.waivers.append(
            Waiver(
                rule_id=str(item.get("rule_id", "UNKNOWN")),
                scope=str(item.get("scope", item.get("anchor_id", "unknown"))),
                anchor_id=None if item.get("anchor_id") is None else str(item.get("anchor_id")),
                reason=str(item.get("reason", "No reason provided.")),
                reviewer=str(item.get("reviewer", "author")),
                reviewed_at=utc_now(),
                max_export_mode=str(item.get("max_export_mode", "draft")),
            )
        )


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
        semantic.reuse.citation = str(data["citation"])
    if "restrictions" in data:
        semantic.reuse.restrictions = [str(item) for item in _coerce_list(data["restrictions"])]
    semantic.reuse.reviewed_at = utc_now()


def _register_answer_artifacts(
    root: Path,
    semantic: SemanticLayer,
    items: Any,
    answer_base: Path,
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
        source = _resolve_answer_path(root, answer_base, str(item["path"]))
        if not source.exists():
            raise ValueError(
                f"Artifact path not found: {item['path']}. "
                f"Looked at {root / str(item['path'])} and {answer_base / str(item['path'])}. "
                "Put the file next to the answers file, put it inside the package, or use a url entry."
                f"{windows_path_hint(item['path'])}"
            )
        register_local_artifact(
            root,
            semantic,
            source,
            role=item.get("role"),
            copy=True,
            detached=bool(item.get("detached", False)),
            relative_destination=replay_destination_for(semantic, source),
        )


def _apply_entities(semantic: SemanticLayer, items: Any) -> None:
    for index, item in enumerate(_coerce_list(items)):
        if not isinstance(item, dict):
            continue
        entity = Entity(
            id=str(item.get("id") or _answer_object_id(semantic, "entity", index)),
            entity_type=str(item.get("entity_type", "unknown")),
            label=str(item.get("label", "unknown")),
            stable_identity=str(item.get("stable_identity", "unknown")),
            source_artifact_ids=[str(value) for value in _coerce_list(item.get("source_artifact_ids", []))],
            claim_critical=bool(item.get("claim_critical", False)),
            review_status=ReviewStatus(str(item.get("review_status", "confirmed"))),
        )
        _upsert(semantic.entities, entity)


def _apply_selections(semantic: SemanticLayer, items: Any) -> None:
    for index, item in enumerate(_coerce_list(items)):
        if not isinstance(item, dict):
            continue
        selector = str(item.get("native_selector", "unknown"))
        selection = Selection(
            id=str(item.get("id") or _answer_object_id(semantic, "selection", index)),
            name=str(item.get("name", "selection")),
            native_selector=ProvenancedString(
                value=selector,
                source_type=SourceType.user_asserted,
                confidence=ConfidenceValue.unknown,
                review_status=ReviewStatus(str(item.get("review_status", "confirmed"))),
            ),
            entity_ids=[str(value) for value in _coerce_list(item.get("entity_ids", []))],
            claim_critical=bool(item.get("claim_critical", False)),
            review_status=ReviewStatus(str(item.get("review_status", "confirmed"))),
        )
        _upsert(semantic.selections, selection)


def _apply_scene_semantics(semantic: SemanticLayer, items: Any) -> None:
    for item in _coerce_list(items):
        if not isinstance(item, dict):
            continue
        target_ids = [str(value) for value in _coerce_list(item.get("scene_ids", []))]
        target_scenes = [
            scene for scene in semantic.scenes if not target_ids or scene.id in target_ids
        ]
        if not target_scenes and semantic.scenes:
            target_scenes = semantic.scenes
        semantics = {
            "color_meanings": dict(item.get("color_meanings", {})),
            "label_meanings": dict(item.get("label_meanings", {})),
            "notes": str(item.get("notes", "")),
            "review_status": str(item.get("review_status", "confirmed")),
            "reviewer": str(item.get("reviewer", "author")),
            "reviewed_at": utc_now(),
        }
        for scene in target_scenes:
            scene.extensions["user_scene_semantics"] = [semantics]
        _apply_legacy_visual_meanings_to_operations(semantic, semantics)


def _apply_legacy_visual_meanings_to_operations(semantic: SemanticLayer, semantics: dict[str, Any]) -> None:
    color_meanings = semantics.get("color_meanings", {})
    label_meanings = semantics.get("label_meanings", {})
    existing_operation_ids = {
        op_id for item in semantic.visual_encoding_semantics for op_id in item.operation_ids
    }
    for operation in semantic.observed_scene_operations:
        if operation.operation_id in existing_operation_ids:
            continue
        meaning: str | None = None
        if operation.operation == "colored":
            color = str(operation.details.get("color", ""))
            if color in color_meanings:
                meaning = str(color_meanings[color])
        elif operation.operation == "labeled":
            label = str(operation.details.get("label_expression") or operation.target)
            if label in label_meanings:
                meaning = str(label_meanings[label])
            elif label_meanings:
                meaning = "; ".join(f"{key}: {value}" for key, value in label_meanings.items())
        if not meaning:
            continue
        semantic.visual_encoding_semantics.append(
            VisualEncodingSemantics(
                operation_ids=[operation.operation_id],
                encoding_type=operation.operation,
                meaning_status=MeaningStatus.user_confirmed_meaning,
                meaning=meaning,
                reviewer=str(semantics.get("reviewer", "author")),
                reviewed_at=utc_now(),
            )
        )
        existing_operation_ids.add(operation.operation_id)
        operation.meaning_status = MeaningStatus.user_confirmed_meaning
        operation.review_status = ReviewStatus.confirmed


def _apply_claim(semantic: SemanticLayer, data: dict[str, Any]) -> str:
    claim_id = str(data.get("id") or (semantic.claims[0].id if semantic.claims else f"claim:{uuid4().hex[:12]}"))
    review_status = ReviewStatus(str(data.get("review_status", "confirmed")))
    claim = Claim(
        id=claim_id,
        claim_text=ProvenancedString(
            value=str(data.get("claim_text", data.get("text", "unknown"))),
            source_type=SourceType.user_asserted,
            confidence=ConfidenceValue.unknown,
            review_status=review_status,
            reviewer=str(data.get("reviewer", "author")),
            reviewed_at=utc_now(),
        ),
        claim_type=ClaimType(str(data.get("claim_type", "unknown"))),
        figure_ref=str(data.get("figure_ref", "unknown")),
        scope=str(data.get("scope", "unknown")),
        scene_ids=[str(value) for value in _coerce_list(data.get("scene_ids", []))],
        evidence_ids=[str(value) for value in _coerce_list(data.get("evidence_ids", []))],
        uncertainty_ids=[str(value) for value in _coerce_list(data.get("uncertainty_ids", []))],
        claim_status=str(data.get("claim_status", "reviewable")),
        review_status=review_status,
    )
    if not claim.scene_ids:
        claim.scene_ids = [scene.id for scene in semantic.scenes]
    _upsert(semantic.claims, claim)
    return claim.id


def _apply_evidence(
    root: Path,
    semantic: SemanticLayer,
    items: Any,
    answer_base: Path,
    claim_ids: list[str],
) -> list[str]:
    evidence_ids: list[str] = []
    for index, item in enumerate(_coerce_list(items)):
        if not isinstance(item, dict):
            continue
        source_ids = [str(value) for value in _coerce_list(item.get("source_artifact_ids", []))]
        source_ids.extend(_artifact_ids_for_roles(semantic, _coerce_list(item.get("source_artifact_roles", []))))
        for source_path in _coerce_list(item.get("source_artifact_paths", [])):
            artifact = find_artifact_by_path(semantic, str(source_path))
            if artifact is None:
                resolved = _resolve_answer_path(root, answer_base, str(source_path))
                if resolved.exists():
                    artifact = register_local_artifact(
                        root,
                        semantic,
                        resolved,
                        role=item.get("artifact_role"),
                        copy=True,
                        relative_destination=replay_destination_for(semantic, resolved),
                    )
            if artifact is not None:
                source_ids.append(artifact.id)
        evidence = Evidence(
            id=str(item.get("id") or _answer_object_id(semantic, "evidence", index)),
            evidence_kind=EvidenceKind(str(item.get("evidence_kind", "manual_rationale"))),
            claim_ids=[str(value) for value in _coerce_list(item.get("claim_ids", claim_ids))],
            source_artifact_ids=sorted(set(source_ids)),
            target_entity_ids=[str(value) for value in _coerce_list(item.get("target_entity_ids", []))],
            target_selection_ids=[str(value) for value in _coerce_list(item.get("target_selection_ids", []))],
            generated_by=str(item.get("generated_by", "author")),
            method_name=str(item.get("method_name", "manual review")),
            method_version=None if item.get("method_version") is None else str(item["method_version"]),
            parameters=dict(item.get("parameters", {})),
            thresholds=dict(item.get("thresholds", {})),
            units={str(key): str(value) for key, value in dict(item.get("units", {})).items()},
            result_summary=str(item.get("result_summary", "unknown")),
            result_summary_structured=dict(item.get("result_summary_structured", {})),
            limitations=[str(value) for value in _coerce_list(item.get("limitations", []))],
            alternative_explanations=[
                str(value) for value in _coerce_list(item.get("alternative_explanations", []))
            ],
            review_status=ReviewStatus(str(item.get("review_status", "confirmed"))),
            reviewer=str(item.get("reviewer", "author")),
            reviewed_at=utc_now(),
            fixity_status="available" if source_ids else "unknown",
        )
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
        uncertainty = Uncertainty(
            id=str(item.get("id") or _answer_object_id(semantic, "uncertainty", index)),
            claim_ids=[str(value) for value in _coerce_list(item.get("claim_ids", claim_ids))],
            category=str(item.get("category", "general")),
            statement=str(item.get("statement", "unknown")),
            alternative_explanations=[
                str(value) for value in _coerce_list(item.get("alternative_explanations", []))
            ],
            review_status=ReviewStatus(str(item.get("review_status", "confirmed"))),
            reviewer=str(item.get("reviewer", "author")),
            reviewed_at=utc_now(),
        )
        _upsert(semantic.uncertainty, uncertainty)
        uncertainty_ids.append(uncertainty.id)
    return uncertainty_ids


def _apply_software(semantic: SemanticLayer, items: Any) -> None:
    for index, item in enumerate(_coerce_list(items)):
        if not isinstance(item, dict):
            continue
        software = SoftwareEnvironment(
            id=str(item.get("id") or _answer_object_id(semantic, "software", index)),
            name=str(item.get("name", "unknown")),
            version=str(item.get("version", "unknown")),
            role=str(item.get("role", "viewer")),
            command=None if item.get("command") is None else str(item["command"]),
        )
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
    operation_ids = tuple(item.operation_ids)
    for index, existing in enumerate(items):
        if tuple(existing.operation_ids) == operation_ids:
            items[index] = item
            return
    items.append(item)


def _upsert_evidence_binding(items: list[EvidenceBinding], item: EvidenceBinding) -> None:
    for index, existing in enumerate(items):
        if existing.binding_id == item.binding_id:
            items[index] = item
            return
    items.append(item)


def ensure_scene_for_images(semantic: SemanticLayer) -> None:
    render_ids = [artifact.id for artifact in semantic.artifacts if artifact.role.value == "render_image"]
    if not render_ids:
        return
    if semantic.scenes:
        for scene in semantic.scenes:
            scene.render_artifact_ids = sorted(set(scene.render_artifact_ids + render_ids))
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
