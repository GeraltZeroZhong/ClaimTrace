"""Small, claim-scoped views of recorded evidence and static scene context.

This projection deliberately does not infer scientific support or viewer replay
from package validation. The semantic layer remains the source of truth.
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any

from claimtrace.errors import SecurityError
from claimtrace.models.semantic_layer import SemanticLayer
from claimtrace.models.validation import ValidationReport
from claimtrace.package.paths import resolve_package_path
from claimtrace.package.resources import resource_matching_artifacts

SCOPE = (
    "Claim context, source files, and limitations. "
    "Scientific support: review the linked evidence. "
    "Scene replay: pending verification in the original viewer."
)
_PLACEHOLDERS = {
    "",
    "unknown",
    "unspecified",
    "todo",
    "tbd",
    "none",
    "null",
    "n/a",
    "na",
    "not applicable",
    "not_applicable",
}
_DESCRIPTIVE = {"simple_structure_view", "selection_highlight"}
_CAVEAT_TYPES = {
    "ligand_binding_pose",
    "cryo_em_map_fit",
    "xray_density_support",
    "trajectory_mechanism",
    "computed_model_claim",
    "model_comparison",
}
_CAMERA_METADATA = {
    "source_type",
    "review_status",
    "status",
    "confidence",
    "source_location",
    "json_pointer",
    "source_path",
    "artifact_id",
    "line",
    "column",
    "reviewer",
    "reviewed_at",
}


def _recorded(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        return any(_recorded(item) for item in value.values())
    if isinstance(value, list):
        return bool(value) and all(_recorded(item) for item in value)
    text = str(value).strip().lower()
    return text not in _PLACEHOLDERS and not text.startswith(("todo", "tbd"))


def _reviewed(item: dict[str, Any]) -> bool:
    timestamp = item.get("reviewed_at")
    try:
        dated = (
            isinstance(timestamp, str)
            and "T" in timestamp
            and datetime.fromisoformat(timestamp.replace("Z", "+00:00")).tzinfo is not None
        )
    except ValueError:
        dated = False
    return (
        item.get("review_status") in {"confirmed", "human_accepted"}
        and _recorded(item.get("reviewer"))
        and dated
    )


def _camera_recorded(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            _camera_recorded(item) for key, item in value.items() if key not in _CAMERA_METADATA
        )
    if isinstance(value, list):
        return bool(value) and all(_camera_recorded(item) for item in value)
    if isinstance(value, float):
        return math.isfinite(value)
    return _recorded(value)


def _static_figure(scene: dict[str, Any]) -> bool:
    return scene.get("extensions", {}).get("view_kind") in {"plot", "figure_assembly"}


def _view_recorded(scene: dict[str, Any]) -> bool:
    camera = scene.get("camera", {})
    return _camera_recorded(camera.get("author_context")) if _static_figure(scene) else _camera_recorded(camera)


def _available(root: Path, artifact: dict[str, Any]) -> bool:
    if artifact.get("kind") != "local_attached" or not artifact.get("included"):
        return False
    try:
        if not artifact.get("path"):
            return False
        path = resolve_package_path(root, artifact["path"])
        return path.is_file() or (artifact.get("role") == "directory" and path.is_dir())
    except (ValueError, OSError, RuntimeError, SecurityError):
        return False


def _in_scene(item: dict[str, Any], scenes: list[dict[str, Any]]) -> bool:
    source = item.get("source_location", {})
    for scene in scenes:
        if source.get("artifact_id") not in scene["native_artifact_ids"]:
            continue
        prefix = scene.get("extensions", {}).get("molviewspec_root", {}).get("json_pointer")
        if not prefix:
            return True
        pointer = source.get("json_pointer") or ""
        if pointer == prefix or pointer.startswith(prefix.rstrip("/") + "/"):
            return True
    return False


def _distance_gaps(item: dict[str, Any]) -> set[str]:
    threshold = item.get("thresholds", {}).get("distance")
    measurement = item.get("evidence_kind") == "measurement"
    measured = item.get("parameters", {}).get("measured_distance")
    value = measured if measurement and measured is not None else threshold
    try:
        valid = (
            not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value) > 0
        )
    except (TypeError, ValueError, OverflowError):
        valid = False
    gaps = set()
    if not valid:
        gaps.add("measured distance" if measurement else "cutoff")
    if not _recorded(item.get("units", {}).get("distance")):
        gaps.add("units")
    return gaps


def _section(finding: dict[str, Any]) -> str:
    rule = finding.get("rule_id", "")
    pointer = finding.get("json_pointer", "")
    if rule in {"CLAIM.LIGAND.IDENTITY_CONTEXT", "CLAIM.SELECTION.IDENTITY_MISSING"}:
        return "visual"
    if "UNCERTAINTY" in rule or pointer.startswith("/uncertainty/"):
        return "uncertainty"
    if "CAMERA" in rule or "FIXITY" in rule or "RESOURCE" in rule or "MEMBER" in rule:
        return "reproducibility"
    if (
        "EVIDENCE" in rule or "CONTACT" in rule or "REQUIRED_CONTEXT" in rule
        or "REQUIRED_VALIDATION" in rule or pointer.startswith("/evidence/")
    ):
        return "provenance"
    if rule.startswith(("SCENE.", "IMPORT.")) or pointer.startswith(("/scenes/", "/selections/")):
        return "visual"
    return "claim"


def _issue(finding: dict[str, Any], mode: str) -> dict[str, Any]:
    return {
        "message": finding["message"],
        "fix": finding.get("suggested_fix", ""),
        "rule_id": finding["rule_id"],
        "section": _section(finding),
        "json_pointer": finding.get("json_pointer", ""),
        "severity": finding["severity"],
        "status": finding["status"],
        "blocking": (
            finding["status"] == "FAIL"
            and finding["severity"] == "ERROR"
            and mode in finding.get("blocks_modes", [])
        ),
    }


def _stage(key: str, label: str, status: str, summary: str) -> dict[str, str]:
    return {"key": key, "label": label, "status": status, "summary": summary}


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}{'' if number == 1 else 's'}"


def _graph(
    data: dict[str, Any], claim: dict[str, Any], resource_artifacts: dict[str, list[str]]
) -> dict[str, set[str]]:
    scenes = [item for item in data["scenes"] if item["id"] in claim["scene_ids"]]
    evidence = [
        item
        for item in data["evidence"]
        if item["id"] in claim["evidence_ids"] or claim["id"] in item["claim_ids"]
    ]
    bindings = [item for item in data["evidence_bindings"] if item.get("claim_id") == claim["id"]]
    selections = {sid for scene in scenes for sid in scene["selection_ids"]}
    selections.update(sid for item in evidence for sid in item["target_selection_ids"])
    entities = {eid for scene in scenes for eid in scene["entity_ids"]}
    entities.update(eid for item in evidence for eid in item["target_entity_ids"])
    entities.update(
        eid for item in data["selections"] if item["id"] in selections for eid in item["entity_ids"]
    )
    operations = {
        item["operation_id"]
        for item in data["observed_scene_operations"]
        if _in_scene(item, scenes)
    }
    operations.update(oid for binding in bindings for oid in binding["operation_ids"])
    resource_ids = {rid for binding in bindings for rid in binding["resource_ref_ids"]}
    resources = [
        item
        for item in data["resource_references"]
        if item["resource_ref_id"] in resource_ids or _in_scene(item, scenes)
    ]
    artifacts = {
        aid
        for scene in scenes
        for aid in scene["native_artifact_ids"] + scene["render_artifact_ids"]
    }
    artifacts.update(aid for item in evidence for aid in item["source_artifact_ids"])
    artifacts.update(aid for item in bindings for aid in item["evidence_artifact_ids"])
    artifacts.update(item["artifact_id"] for item in resources if item.get("artifact_id"))
    artifacts.update(
        aid for item in resources for aid in resource_artifacts.get(item["resource_ref_id"], [])
    )
    artifacts.update(
        aid
        for item in data["entities"]
        if item["id"] in entities
        for aid in item["source_artifact_ids"]
    )
    artifacts.update(
        item["source_artifact_id"]
        for item in data["selections"]
        if item["id"] in selections and item.get("source_artifact_id")
    )
    return {
        "claims": {claim["id"]},
        "scenes": set(claim["scene_ids"]),
        "evidence": {item["id"] for item in evidence},
        "uncertainty": {
            item["id"]
            for item in data["uncertainty"]
            if item["id"] in claim["uncertainty_ids"] or claim["id"] in item["claim_ids"]
        },
        "artifacts": artifacts,
        "selections": selections,
        "entities": entities,
        "observed_scene_operations": operations,
        "native_references": {
            item["native_ref_id"] for item in data["native_references"] if _in_scene(item, scenes)
        },
        "resource_references": {item["resource_ref_id"] for item in resources},
        "raw_native_observations": {
            item["raw_id"]
            for item in data["raw_native_observations"]
            if item.get("may_affect_scene_id") in claim["scene_ids"] or _in_scene(item, scenes)
        },
        "evidence_bindings": {item["binding_id"] for item in bindings},
    }


def _belongs(finding: dict[str, Any], data: dict[str, Any], graph: dict[str, set[str]]) -> bool:
    parts = finding.get("json_pointer", "").strip("/").split("/")
    if len(parts) < 2:
        return False
    collection, index = parts[:2]
    try:
        item = data[collection][int(index)]
    except (KeyError, ValueError, IndexError, TypeError):
        return False
    if collection == "visual_encoding_semantics":
        return bool(set(item["operation_ids"]) & graph["observed_scene_operations"])
    if collection == "mvsx_inventories":
        return item["artifact_id"] in graph["artifacts"]
    keys = ("id", "operation_id", "resource_ref_id", "native_ref_id", "raw_id", "binding_id")
    return any(item.get(key) in graph.get(collection, set()) for key in keys)


def build_audit(root: Path, semantic: SemanticLayer, report: ValidationReport) -> dict[str, Any]:
    """Return compact audits; unmatched findings remain visible at package scope."""
    root = Path(root)
    data = semantic.model_dump(mode="json")
    findings = [
        item.model_dump(mode="json")
        for item in report.findings
        if item.status in {"FAIL", "WAIVED"}
    ]
    used_findings: set[int] = set()
    claims = []
    by_artifact = {item["id"]: item for item in data["artifacts"]}
    # ResourceReference.artifact_id is the owning native file, not the
    # referenced coordinate file. Resolve native-relative URIs using the same
    # path semantics as package validation.
    resource_artifacts = {
        resource.resource_ref_id: [
            artifact.id
            for artifact in resource_matching_artifacts(
                semantic, resource.uri, resource_ref=resource
            )
        ]
        for resource in semantic.resource_references
    }
    for claim in data["claims"]:
        graph = _graph(data, claim, resource_artifacts)
        scenes = [item for item in data["scenes"] if item["id"] in graph["scenes"]]
        evidence = [item for item in data["evidence"] if item["id"] in graph["evidence"]]
        uncertainty = [item for item in data["uncertainty"] if item["id"] in graph["uncertainty"]]
        selections = [item for item in data["selections"] if item["id"] in graph["selections"]]
        operations = [
            item
            for item in data["observed_scene_operations"]
            if item["operation_id"] in graph["observed_scene_operations"]
        ]
        issues = []
        for index, finding in enumerate(findings):
            if _belongs(finding, data, graph):
                issues.append(_issue(finding, report.export_mode))
                used_findings.add(index)

        def note(section: str, message: str, fix: str) -> None:
            issues.append(
                {
                    "section": section,
                    "message": message,
                    "fix": fix,
                    "severity": "WARNING",
                    "status": "FAIL",
                    "blocking": False,
                    "origin": "audit_context",
                }
            )

        claim_recorded = _recorded(claim["claim_text"]["value"]) and _recorded(claim["figure_ref"])
        stages = [
            _stage(
                "claim",
                "Claim",
                (
                    "missing"
                    if not claim_recorded
                    else "recorded"
                    if _reviewed(claim["claim_text"])
                    else "review"
                ),
                claim["figure_ref"] if claim_recorded else "Record the statement and panel label.",
            )
        ]
        available_ids = {
            aid
            for aid in graph["artifacts"]
            if aid in by_artifact and _available(root, by_artifact[aid])
        }
        native_ids = {aid for item in scenes for aid in item["native_artifact_ids"]}
        render_ids = {aid for item in scenes for aid in item["render_artifact_ids"]}
        static_scenes = [item for item in scenes if _static_figure(item)]
        molecular_scenes = [item for item in scenes if not _static_figure(item)]
        static_only = bool(scenes) and not molecular_scenes
        visual_present = bool(scenes and available_ids & (native_ids | render_ids))
        visual_summary = " · ".join(
            (
                _count(len(scenes), "scene"),
                _count(len(selections), "selection"),
                _count(len(available_ids & render_ids), "panel"),
            )
        )
        if not visual_present:
            visual_summary = "Attach a scene file or figure image."
        elif static_only:
            visual_summary = _count(len(available_ids & render_ids), "saved figure")
        visual_review = any(
            item.get("claim_critical")
            and item["review_status"] not in {"confirmed", "human_accepted"}
            for item in selections
        )
        visual_review = visual_review or any(
            item["claim_critical"] == "true"
            and item["review_status"] not in {"confirmed", "human_accepted"}
            for item in operations
        )
        stages.append(
            _stage(
                "visual",
                "Visual evidence",
                "missing" if not visual_present else "review" if visual_review else "recorded",
                visual_summary,
            )
        )

        evidence_has_context = bool(evidence) and all(
            item["source_artifact_ids"]
            and _recorded(item["method_name"])
            and _recorded(item["result_summary"])
            for item in evidence
        )
        evidence_sources_available = evidence_has_context and all(
            set(item["source_artifact_ids"]) <= available_ids for item in evidence
        )
        evidence_reviewed = bool(evidence) and all(_reviewed(item) for item in evidence)
        if not evidence_has_context:
            needed = []
            if not evidence or any(not item["source_artifact_ids"] for item in evidence):
                needed.append("a source file")
            if not evidence or any(not _recorded(item["method_name"]) for item in evidence):
                needed.append("how it was checked")
            if not evidence or any(not _recorded(item["result_summary"]) for item in evidence):
                needed.append("what it shows")
            requirements = (
                needed[0] if len(needed) == 1 else ", ".join(needed[:-1]) + " and " + needed[-1]
            )
            provenance_summary = "Record " + requirements + "."
            note(
                "provenance",
                provenance_summary,
                "Add evidence with a source file, a check, and an observation.",
            )
        else:
            provenance_summary = "; ".join(dict.fromkeys(item["method_name"] for item in evidence))
            if not evidence_sources_available:
                provenance_summary += "; attach the source files."
            elif not evidence_reviewed:
                provenance_summary += "; review and confirm the evidence record."
        stages.append(
            _stage(
                "provenance",
                "Provenance",
                (
                    "missing"
                    if not evidence_has_context
                    else (
                        "recorded" if evidence_sources_available and evidence_reviewed else "review"
                    )
                ),
                provenance_summary,
            )
        )

        if uncertainty:
            caveat_status = (
                "recorded"
                if all(_recorded(item["statement"]) and _reviewed(item) for item in uncertainty)
                else "review"
            )
            caveat_summary = (
                " · ".join(
                    item["statement"] for item in uncertainty if _recorded(item["statement"])
                )
                or "Add a limitation or alternative explanation."
            )
        elif claim["claim_type"] in _DESCRIPTIVE:
            caveat_status, caveat_summary = (
                "not_applicable",
                "Descriptive view.",
            )
        else:
            caveat_status = "missing" if claim["claim_type"] in _CAVEAT_TYPES else "review"
            caveat_summary = "Add a limitation or alternative explanation."
            if not any("UNCERTAINTY" in item.get("rule_id", "") for item in issues):
                note(
                    "uncertainty",
                    caveat_summary,
                    "Describe the main limitation of this claim.",
                )
        stages.append(_stage("uncertainty", "Uncertainty", caveat_status, caveat_summary))

        cameras_recorded = bool(molecular_scenes) and all(
            _camera_recorded(item["camera"]) for item in molecular_scenes
        )
        views_recorded = bool(scenes) and all(_view_recorded(item) for item in scenes)
        resources = [
            item
            for item in data["resource_references"]
            if item["resource_ref_id"] in graph["resource_references"]
        ]
        unresolved_resources = [
            item
            for item in resources
            if item["uri_kind"] == "missing_archive_member"
            or (
                item["uri_kind"] not in {"archive_member", "data"}
                and not any(
                    aid in available_ids for aid in resource_artifacts[item["resource_ref_id"]]
                )
            )
        ]
        distance_evidence = [
            item for item in evidence if item["evidence_kind"] in {"contact_table", "measurement"}
        ]
        external_validation = any(
            item["evidence_kind"] == "external_validation" for item in evidence
        )
        distance_gaps = set().union(*(_distance_gaps(item) for item in distance_evidence))
        if (
            claim["claim_type"] == "ligand_binding_pose"
            and not distance_evidence
            and not external_validation
        ):
            measurement_present = any(
                item["operation"] in {"measurement_intent", "distance_measured"}
                or item.get("details", {}).get("command") == "distance"
                for item in operations
            )
            if measurement_present:
                distance_gaps.update({"cutoff", "units"})
        if distance_gaps:
            needed = []
            if "cutoff" in distance_gaps:
                needed.append("a positive distance cutoff")
            if "measured distance" in distance_gaps:
                needed.append("a measured distance")
            if "units" in distance_gaps:
                needed.append("units" if needed else "distance units")
            needed_distance = " and ".join(needed)
            note(
                "reproducibility",
                f"{'Distance measurement' if 'measured distance' in distance_gaps else 'Contact analysis'} needs {needed_distance}.",
                f"Edit the evidence to record {needed_distance}.",
            )
        replay_gaps = []
        molecular_native_ids = {
            aid for item in molecular_scenes for aid in item["native_artifact_ids"]
        }
        if not scenes or (molecular_scenes and (
            any(not item["native_artifact_ids"] for item in molecular_scenes)
            or not molecular_native_ids <= available_ids
        )):
            replay_gaps.append("attach the saved scene file")
        if any(not set(item["render_artifact_ids"]) & available_ids for item in static_scenes):
            replay_gaps.append("attach the saved figure")
        if static_scenes and not evidence_sources_available:
            replay_gaps.append("record the analysis and source files")
        if unresolved_resources:
            replay_gaps.append(_count(len(unresolved_resources), "scene source file") + " to attach")
        if molecular_scenes and not cameras_recorded:
            replay_gaps.append("record the saved view")
        if any(not _view_recorded(item) for item in static_scenes):
            replay_gaps.append("record the figure's analysis or assembly settings")
        if distance_gaps:
            replay_gaps.append(
                " and ".join(key for key in ("cutoff", "measured distance", "units") if key in distance_gaps) + " needed"
            )
        reproducibility_summary = (
            "; ".join(replay_gaps)
            if replay_gaps
            else "Saved figure, source files, and analysis or assembly settings recorded"
            if static_only
            else "Scene file, source files, and saved view recorded"
        )
        reproducibility_summary += (
            ". Molecular replay: not applicable. Package validation is reported separately."
            if static_only
            else ". Scene replay: pending verification in the original viewer."
        )
        stages.append(
            _stage(
                "reproducibility",
                "Reproducibility",
                "missing" if replay_gaps else "recorded",
                reproducibility_summary,
            )
        )
        blocking = [item for item in issues if item["blocking"]]
        # Open requirements remain visible in their audit row even when the
        # selected handoff level permits exporting a work in progress.
        for stage in stages:
            stage_issues = [
                item for item in issues
                if item["status"] == "FAIL" and item["section"] == stage["key"]
            ]
            if stage_issues and stage["status"] in {"recorded", "not_applicable"}:
                stage["status"] = "review"
                stage["summary"] = (
                    stage["summary"] + " Review the remaining package requirements."
                    if static_only and stage["key"] == "reproducibility"
                    else stage_issues[0]["message"]
                )
        status = (
            "incomplete"
            if blocking or any(stage["status"] == "missing" for stage in stages)
            else "review"
        )
        # A recorded audit still requires scientific review and viewer replay.
        if (
            status != "incomplete"
            and evidence_reviewed
            and not any(item["status"] == "FAIL" for item in issues)
        ):
            status = (
                "recorded"
                if all(stage["status"] in {"recorded", "not_applicable"} for stage in stages)
                else "review"
            )
        claims.append(
            {
                "id": claim["id"],
                "headline": claim["claim_text"]["value"],
                "figure_ref": claim["figure_ref"],
                "claim_type": claim["claim_type"],
                "status": status,
                "stages": stages,
                "issues": issues,
                "scene_ids": sorted(graph["scenes"]),
                "evidence_ids": sorted(graph["evidence"]),
                "uncertainty_ids": sorted(graph["uncertainty"]),
                "artifact_ids": sorted(graph["artifacts"]),
                "source_artifacts": [
                    {
                        "id": aid,
                        "path": by_artifact[aid].get("path"),
                        "role": by_artifact[aid]["role"],
                    }
                    for aid in sorted(graph["artifacts"])
                    if aid in by_artifact
                ],
                "selection_ids": sorted(graph["selections"]),
                "entity_ids": sorted(graph["entities"]),
                "operation_ids": sorted(graph["observed_scene_operations"]),
                "resource_ref_ids": sorted(graph["resource_references"]),
                "resource_artifact_ids": {
                    rid: resource_artifacts[rid] for rid in sorted(graph["resource_references"])
                },
                "unresolved_resource_ids": sorted(
                    item["resource_ref_id"] for item in unresolved_resources
                ),
                "raw_observation_ids": sorted(graph["raw_native_observations"]),
                "evidence_binding_ids": sorted(graph["evidence_bindings"]),
                "replay_status": "not_applicable" if static_only else "unverified",
                "camera_status": "not_applicable" if static_only else "recorded" if cameras_recorded else "not_recorded",
                "view_context_status": "recorded" if views_recorded else "not_recorded",
                "validation_blockers": len(blocking),
            }
        )
    package_findings = [
        _issue(item, report.export_mode)
        for index, item in enumerate(findings)
        if index not in used_findings
    ]
    static_only = bool(claims) and all(item["replay_status"] == "not_applicable" for item in claims)
    return {
        "claims": claims,
        "scope": (
            "Claim context, source files, and limitations. "
            "Scientific support: review the linked evidence. "
            "Static figures: review the saved outputs and analysis settings. "
            "Package validation is reported separately."
            if static_only else SCOPE
        ),
        "package_findings": package_findings,
        "summary": {
            "claims": len(claims),
            "incomplete": sum(item["status"] == "incomplete" for item in claims),
            "review": sum(item["status"] == "review" for item in claims),
            "recorded": sum(item["status"] == "recorded" for item in claims),
            "validation_mode": report.export_mode,
            "validation_status": report.overall_status,
            "package_blockers": sum(item["blocking"] for item in package_findings),
            "replay_status": "not_applicable" if static_only else "unverified",
        },
    }


def export_markdown(audit: dict[str, Any]) -> str:
    """Export five stages and at most three priority items per claim."""
    lines = ["# ClaimTrace audit", "", audit["scope"], ""]
    labels = {
        "incomplete": "Needs details",
        "missing": "Needs details",
        "review": "Review needed",
        "recorded": "Recorded",
        "not_applicable": "Optional",
    }
    for claim in audit["claims"]:
        lines.extend(
            [
                f"## {claim.get('figure_ref', claim['id'])} · {labels.get(claim['status'], claim['status'])}",
                "",
                claim["headline"],
                "",
            ]
        )
        for stage in claim["stages"]:
            status = labels.get(stage["status"], stage["status"])
            lines.append(f"- **{stage['label']} · {status}** — {stage['summary']}")
        sources = [
            item.get("path") or item["id"]
            for item in claim.get("source_artifacts", [])
        ] or claim["artifact_ids"]
        if sources:
            extra = f"; {len(sources) - 5} more in the JSON audit" if len(sources) > 5 else ""
            lines.extend(["", "Sources: " + "; ".join(sources[:5]) + extra + "."])
        open_items = sorted(
            (item for item in claim["issues"] if item["status"] != "WAIVED"),
            key=lambda item: (
                item.get("origin") != "audit_context",
                not item.get("blocking"),
                item.get("section") not in {"reproducibility", "provenance", "uncertainty"},
            ),
        )
        if open_items:
            lines.extend(["", "Next steps:", ""])
            for item in open_items[:3]:
                prefix = "Blocking: " if item.get("blocking") else "Review: "
                if (
                    item.get("rule_id") == "CLAIM.SELECTION.REQUIRED_SELECTION"
                    and claim.get("replay_status") != "not_applicable"
                ):
                    description = (
                        "Link the highlighted region using its saved molecular scene. "
                        "An image-only record can be shared as a working draft."
                    )
                else:
                    description = f"{item['message']} {item['fix']}".strip()
                lines.append(f"- {prefix}{description}")
        remaining = max(len(open_items) - 3, 0)
        waived = sum(item["status"] == "WAIVED" for item in claim["issues"])
        if remaining or waived:
            lines.extend(
                [
                    "",
                    f"{_count(remaining, 'more open item')}; {waived} waived. Full findings: JSON audit.",
                ]
            )
        lines.append("")
    if audit.get("package_findings"):
        findings = audit["package_findings"]
        blocked = sum(item.get("blocking", False) for item in findings)
        waived = sum(item["status"] == "WAIVED" for item in findings)
        lines.extend(
            [
                "## Package context",
                "",
                f"{blocked} blocking; {len(findings) - blocked - waived} other open; {waived} waived. "
                "Full findings: JSON audit.",
                "",
            ]
        )
    return "\n".join(lines)
