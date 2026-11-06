"""Shared authoring questions and handoff readiness for the CLI and GUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

LIFECYCLE_LABELS = {
    "draft": "Working draft",
    "internal": "Lab handoff",
    "share": "External review",
    "archive": "Archive",
}


def _data(value: Any) -> dict[str, Any]:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _known(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text not in {"", "unknown", "unspecified", "none", "null", "n/a", "na"} and not text.startswith(("todo", "tbd"))


def _distance_missing(evidence: dict[str, Any]) -> bool:
    from claimtrace.gui.audit import _distance_gaps

    if evidence.get("evidence_kind") not in {"contact_table", "measurement"}:
        return False
    return bool(_distance_gaps(evidence))


def build_workflow(semantic: Any, report: Any, audit: dict[str, Any]) -> dict[str, Any]:
    """Project record gaps into scoped questions, independently of export gates.

    A valid working draft can retain open authoring questions. ``ready`` reports
    the selected validation gate; it carries no scientific or replay judgement.
    """
    from claimtrace.gui.audit import _reviewed, _static_figure, _view_recorded
    from claimtrace.models.semantic_layer import SemanticLayer
    from claimtrace.proposals import stored_proposals
    from claimtrace.validation.engine import _visual_semantics_is_author_reviewed

    data, assessment = _data(semantic), _data(report)
    layer = semantic if hasattr(semantic, "model_dump") else SemanticLayer.model_validate(data)
    reviewed_visual_operations = {
        operation_id
        for item in layer.visual_encoding_semantics
        if _visual_semantics_is_author_reviewed(item)
        for operation_id in item.operation_ids
    }
    mode = assessment["export_mode"]
    if mode not in LIFECYCLE_LABELS:
        raise ValueError("Choose Working draft, Lab handoff, External review, or Archive.")
    tasks: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    evidence_by_id = {item["id"]: item for item in data.get("evidence", [])}
    claim_by_id = {item["id"]: item for item in data.get("claims", [])}
    uncertainty_by_id = {item["id"]: item for item in data.get("uncertainty", [])}
    scene_by_id = {item["id"]: item for item in data.get("scenes", [])}
    artifact_by_id = {item["id"]: item for item in data.get("artifacts", [])}
    pending = [item for item in stored_proposals(layer) if item["status"] == "pending"]
    proposed_claim = any(
        change["record_type"] == "claim" and change["record_id"] not in claim_by_id
        for proposal in pending for change in proposal["changes"]
    )

    def untyped_image(scene: dict[str, Any]) -> bool:
        return bool(scene.get("render_artifact_ids")) and not (
            scene.get("native_artifact_ids") or scene.get("extensions", {}).get("view_kind")
        )

    def view_question(scene: dict[str, Any]) -> tuple[str, str]:
        image_only = bool(scene.get("render_artifact_ids")) and not scene.get("native_artifact_ids")
        source_ids = scene.get("render_artifact_ids" if image_only else "native_artifact_ids", [])
        filenames = ", ".join(
            Path(artifact_by_id[aid]["path"]).name for aid in source_ids
            if aid in artifact_by_id and artifact_by_id[aid].get("path")
        )
        if untyped_image(scene):
            return (
                "What kind of figure is this?",
                "Choose a molecular view, analysis plot, or figure assembly to record its settings.",
            )
        if _static_figure(scene):
            assembly = scene.get("extensions", {}).get("view_kind") == "figure_assembly"
            return (
                "How was this figure assembled?" if assembly else "How was this plot prepared?",
                f"Record the {'panel sources and assembly settings' if assembly else 'axes, filters, and analysis settings'} for {filenames or 'this figure'}.",
            )
        if image_only:
            return (
                "Which region and orientation does this image show?",
                f"Describe the visible region and orientation in {filenames or 'this image'}.",
            )
        label = scene.get("extensions", {}).get("snapshot_title") or scene.get("description")
        if not label or str(label).startswith(("Static image scene", "Scene statically extracted", "Draft scene", "Imported", "Scene from")):
            label = filenames or "this scene"
        return (
            "Which saved view shows this feature?",
            f"Record the saved view or camera position for {str(label).rstrip('. ')}.",
        )

    def add(
        action: str,
        title: str,
        detail: str,
        claim_id: str | None = None,
        *,
        issue: dict[str, Any] | None = None,
        record_id: str | None = None,
        scene_id: str | None = None,
    ) -> None:
        key = f"{claim_id or 'package'}:{action}:{record_id or ''}:{scene_id or ''}"
        if key not in by_id:
            item = {
                "id": key,
                "title": title,
                "detail": detail,
                "claim_id": claim_id,
                "scope": "claim" if claim_id else "package",
                "action": action,
                "record_id": record_id,
                "scene_id": scene_id,
                "rule_ids": [],
                "blocking": False,
            }
            tasks.append(item)
            by_id[key] = item
        item = by_id[key]
        if issue:
            rule = issue.get("rule_id")
            if rule and rule not in item["rule_ids"]:
                item["rule_ids"].append(rule)
            item["blocking"] |= bool(issue.get("blocking"))

    for proposal in pending:
        add(
            "review-proposal", f"Review suggestion: {proposal['title']}",
            "Compare the proposed changes with their sources, then record your decision.",
            proposal.get("claim_id") if proposal.get("claim_id") in claim_by_id else None,
            record_id=proposal["id"],
        )
    if not data.get("claims") and not proposed_claim:
        add("new-claim", "What does this figure show?", "Write the statement this figure supports.")
    if not data.get("scenes"):
        add("attach", "Which figure or scene belongs to these files?", "Add an image or a saved molecular scene.")
    if not data.get("claims"):
        from claimtrace.package.resources import resource_matching_artifacts
        missing_resources = [
            item.uri for item in layer.resource_references
            if item.uri_kind in {"relative", "local"}
            and not resource_matching_artifacts(layer, item.uri, resource_ref=item)
        ]
        if missing_resources:
            add("attach", "Which source files complete this scene?", "Attach the files used by this scene: " + ", ".join(dict.fromkeys(missing_resources)) + ".")

    for claim_audit in audit.get("claims", []):
        cid = claim_audit["id"]
        claim = claim_by_id[cid]
        scenes = claim_audit.get("scene_ids", [])
        scene_id = scenes[0] if len(scenes) == 1 else None
        stages = {item["key"]: item for item in claim_audit["stages"]}
        evidence = [evidence_by_id[eid] for eid in claim_audit.get("evidence_ids", []) if eid in evidence_by_id]
        incomplete = [
            item for item in evidence
            if not item.get("source_artifact_ids") or not _known(item.get("method_name"))
            or not _known(item.get("result_summary"))
            or not _reviewed(item)
        ]
        caveats = [uncertainty_by_id[uid] for uid in claim_audit.get("uncertainty_ids", []) if uid in uncertainty_by_id]
        pending_caveats = [item for item in caveats if not _known(item.get("statement")) or not _reviewed(item)]
        unfinished_caveat = pending_caveats[0] if pending_caveats else None
        caveat_action = "edit-uncertainty" if unfinished_caveat else "new-uncertainty"
        caveat_id = unfinished_caveat["id"] if unfinished_caveat else None
        if (
            not _known(claim.get("claim_text", {}).get("value"))
            or not _known(claim.get("figure_ref"))
            or not _reviewed(claim.get("claim_text", {}))
        ):
            add("edit-claim", "What statement belongs to this figure?", "Record the statement and its figure label.", cid)
        if not claim.get("scene_ids"):
            add("edit-claim", "Which scene shows this claim?", "Choose the relevant scene in the claim record.", cid)
        for item in evidence:
            if _distance_missing(item):
                if item.get("evidence_kind") == "measurement":
                    add("edit-evidence", "What distance was measured?", "Record the measured atom-to-atom distance and its unit.", cid, record_id=item["id"])
                else:
                    add("cutoff", "Which cutoff and unit define this contact?", "Enter the distance cutoff and unit used to select contacts.", cid, record_id=item["id"])
        if stages["provenance"]["status"] in {"missing", "review"}:
            if incomplete:
                for item in incomplete:
                    add("edit-evidence", "What supports this statement?", "Record what the source shows and how it was checked.", cid, record_id=item["id"])
            elif not evidence:
                add("new-evidence", "What supports this statement?", "Choose a source file and describe what it shows.", cid)
            elif not any(
                item.get("section") == "provenance" and item.get("status") == "FAIL"
                and item.get("rule_id") for item in claim_audit.get("issues", [])
            ):
                for item in evidence:
                    add("edit-evidence", "Which file contains this supporting result?", "Attach the source file for this observation.", cid, record_id=item["id"])
        if stages["uncertainty"]["status"] in {"missing", "review"}:
            for item in pending_caveats or [None]:
                add("edit-uncertainty" if item else "new-uncertainty", "What could change this interpretation?", "Record a relevant limitation or alternative explanation.", cid, record_id=item["id"] if item else None)
        if stages["visual"]["status"] == "missing":
            add("add-figure", "Which figure shows this claim?", "Attach the figure image or its saved scene file.", cid, scene_id=scene_id)
        if claim_audit.get("unresolved_resource_ids"):
            add("attach", "Which source files complete this scene?", "Attach the structure, map, or other files used by this scene.", cid, scene_id=scene_id)
        missing_views = [
            scene_by_id[sid] for sid in scenes if sid in scene_by_id
            and (untyped_image(scene_by_id[sid]) or not _view_recorded(scene_by_id[sid]))
        ]
        for scene in missing_views:
            title, detail = view_question(scene)
            add("context", title, detail, cid, scene_id=scene["id"])
        for sid in scenes:
            scene = scene_by_id.get(sid)
            if scene and not untyped_image(scene) and not _static_figure(scene) and not any(
                artifact_by_id.get(aid, {}).get("kind") == "local_attached"
                and artifact_by_id[aid].get("included")
                and artifact_by_id[aid].get("path")
                for aid in scene.get("native_artifact_ids", [])
            ):
                add(
                    "attach", "Add a saved scene for interactive replay",
                    "Attach a PyMOL (.pml), ChimeraX (.cxc), or MolViewSpec (.mvsj/.mvsx) scene. "
                    "This record can be shared as a Working draft.",
                    cid, scene_id=sid,
                )
        scoped_operations = [item for item in data.get("observed_scene_operations", []) if item["operation_id"] in claim_audit.get("operation_ids", [])]
        if any(
            item["operation_id"] not in reviewed_visual_operations
            and item.get("claim_critical") != "false" and (
                item.get("needs_author_confirmation")
                or item.get("meaning_status") in {"requires_user_completion", "tool_suggested_meaning"}
            ) and item.get("operation") in {"colored", "labeled", "represented", "displayed"}
            for item in scoped_operations
        ):
            add("explain-colors", "What do the visual cues mean?", "Describe the highlighted color, label, or representation.", cid)
        for issue in claim_audit.get("issues", []):
            if issue.get("status") != "FAIL":
                continue
            rule = issue.get("rule_id", "")
            if claim_audit.get("replay_status") == "not_applicable" and (
                "CAMERA" in rule
            ):
                add("answers", "Review the package requirements", "Review the claim type and the requirements for the selected export level.", cid, issue=issue, scene_id=scene_id)
            elif rule == "CLAIM.SELECTION.REQUIRED_SELECTION":
                if any(scene_by_id[sid].get("native_artifact_ids") for sid in scenes if sid in scene_by_id):
                    add("view-source", "Where is the highlighted selection recorded?", "The attached scene has no recorded named selection. Inspect its commands, then save the highlighted selection in the original viewer and attach the updated scene.", cid, issue=issue, scene_id=scene_id)
                else:
                    add("attach", "Which saved scene contains the highlighted region?", "Attach the molecular scene containing the named selection. An image-only record can be shared as a Working draft.", cid, issue=issue, scene_id=scene_id)
            elif rule in {"CLAIM.LIGAND.IDENTITY_CONTEXT", "CLAIM.SELECTION.IDENTITY_MISSING", "SCENE.MOLECULAR_IDENTITY_UNCONFIRMED"}:
                add("identify-regions", "Which molecules or residues are selected?", "Confirm the identity of the selected regions using their structure file.", cid, issue=issue)
            elif rule == "SCENE.VISUAL_ENCODING.MEANING_MISSING":
                add("explain-colors", "What do the visual cues mean?", "Describe the highlighted color, label, or representation.", cid, issue=issue)
            elif "UNCERTAINTY" in rule:
                add(caveat_action, "What could change this interpretation?", "Record a relevant limitation or alternative explanation.", cid, issue=issue, record_id=caveat_id)
            elif "REQUIRED_RENDER" in rule:
                add("add-figure", "Which figure shows this claim?", "Attach the exported panel.", cid, issue=issue, scene_id=scene_id)
            elif "REQUIRED_STRUCTURE" in rule:
                detail = (
                    "Attach the coordinate file used to produce this figure or its analysis."
                    if claim_audit.get("replay_status") == "not_applicable"
                    else "Attach the coordinate file shown in this scene."
                )
                add("add-structure", "Which structure was used?", detail, cid, issue=issue, scene_id=scene_id)
            elif "CAMERA" in rule:
                for scene in missing_views:
                    title, detail = view_question(scene)
                    add("context", title, detail, cid, issue=issue, scene_id=scene["id"])
            elif rule == "SCENE.HIDDEN.CRITICAL_REASON":
                add("context", "Why were these scene elements hidden?", "Describe how hiding these elements helps show the claim.", cid, issue=issue, scene_id=scene_id)
            elif "RAW_AFFECTS_SCENE" in rule or rule == "IMPORT.MVS.UNKNOWN_NODE":
                add("context", "How do the additional scene commands affect this figure?", "Inspect the saved commands and describe their effect on the claim.", cid, issue=issue, scene_id=scene_id)
            elif "RESOURCE" in rule or "MEMBER" in rule:
                add("attach", "Which source files complete this scene?", issue.get("fix") or issue["message"], cid, issue=issue, scene_id=scene_id)
            elif rule == "CLAIM.TRAJECTORY.REQUIRED_CONTEXT" and (
                missing := {"trajectory", "topology"} - {a.get("role") for a in data.get("artifacts", [])}
            ):
                names = " and ".join(sorted(missing))
                add(
                    "attach", f"Add the original {names} files",
                    "These inputs support trajectory reproduction. Attach them when available and link them to the analysis evidence. Supplied results can be reviewed in a Working draft.",
                    cid, issue=issue, scene_id=scene_id,
                )
            elif rule.startswith("CLAIM.BASIC.") and rule.rsplit(".", 1)[-1] != "EVIDENCE":
                add("edit-claim", "What statement belongs to this figure?", "Record the statement, figure label, and linked scene.", cid, issue=issue)
            elif "EVIDENCE" in rule or "CONTACT" in rule or "REQUIRED_CONTEXT" in rule or "REQUIRED_VALIDATION" in rule:
                item = incomplete[0] if incomplete else evidence[0] if evidence else None
                title = (
                    "Which inputs and settings support this trajectory claim?"
                    if rule == "CLAIM.TRAJECTORY.REQUIRED_CONTEXT" else "What supports this statement?"
                )
                add("edit-evidence" if item else "new-evidence", title, issue.get("fix") or issue["message"], cid, issue=issue, record_id=item["id"] if item else None)
            elif issue.get("blocking"):
                add("answers", "Review the technical record", issue.get("fix") or issue["message"], cid, issue=issue, scene_id=scene_id)

    for issue in audit.get("package_findings", []):
        if issue.get("status") != "FAIL":
            continue
        rule = issue.get("rule_id", "")
        if rule == "CLAIM.BASIC.MISSING":
            if not proposed_claim:
                add("new-claim", "What does this figure show?", "Write the statement this figure supports.", issue=issue)
        elif "RESOURCE" in rule or "MEMBER" in rule:
            add("attach", "Which source files complete this package?", issue.get("fix") or issue["message"], issue=issue)
        elif issue.get("blocking"):
            add("answers", "Review the technical record", issue.get("fix") or issue["message"], issue=issue)

    if mode in {"share", "archive"}:
        if not _known(data.get("reuse", {}).get("license")):
            add("context", "How may the recipient reuse this package?", "Record its reuse terms and citation.")
        software = data.get("software_environment", [])
        if not software or any(not _known(item.get("version")) for item in software):
            add("context", "Which software produced the scene?", "Record the viewer or analysis tool and its version.")

    blocking = sum(
        finding.get("status") == "FAIL" and finding.get("severity") == "ERROR"
        and mode in finding.get("blocks_modes", [])
        for finding in assessment.get("findings", [])
    )
    tasks.sort(key=lambda task: (
        task["action"] != "review-proposal", not task["blocking"],
        not (task["action"] == "context" and untyped_image(scene_by_id.get(task.get("scene_id"), {}))),
        not bool(task["rule_ids"])
    ))
    return {
        "lifecycle": {
            "mode": mode,
            "label": LIFECYCLE_LABELS[mode],
            "ready": assessment["overall_status"] != "fail",
            "blocking_count": blocking,
        },
        "tasks": tasks,
        "next_action": tasks[0] if tasks else None,
    }


def review_package(root: str | Path, mode: str | None = None) -> dict[str, Any]:
    """Read the common review view without changing the package."""
    from claimtrace.api import load_package
    from claimtrace.gui.audit import build_audit

    package = load_package(root)
    if mode is None:
        mode = package.semantic_layer.extensions.get("gui_lifecycle", "draft")
        if mode not in LIFECYCLE_LABELS:
            mode = "draft"
    report = package.validate(mode=mode)
    audit = build_audit(package.root, package.semantic_layer, report)
    return {
        "root": str(package.root),
        "semantic": package.semantic_layer.model_dump(mode="json"),
        "report": report.model_dump(mode="json"),
        "audit": audit,
        "workflow": build_workflow(package.semantic_layer, report, audit),
    }
