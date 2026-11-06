"""Package README generation."""

from __future__ import annotations

import shlex
from pathlib import PurePosixPath

from claimtrace.models import SemanticLayer
from claimtrace.models.validation import ValidationReport
from claimtrace.package.resources import resource_matches_artifact, resource_uri_summary


def render_readme(semantic: SemanticLayer, report: ValidationReport | None = None) -> str:
    operation_meanings = _visual_meaning_by_operation(semantic)
    lines = [
        f"# {semantic.package.title}",
        "",
        "Trace each figure statement to its visual evidence, source files, settings and limitations.",
        "",
        "## Review summary",
        "",
    ]
    lines.extend(_review_summary_lines(semantic, report))
    lines.extend(_proposal_lines(semantic))
    lines.extend(
        [
            "",
            "## How to read this package",
            "",
            "Extract the ZIP, open a terminal in the extracted package folder, and run:",
            "",
            "```bash",
            "claimtrace gui .",
            "```",
            "",
            "Select a claim and open **Review** to inspect its figure, source files, evidence, and limitations. **Prepare** shows the details to complete.",
            "",
            "In the terminal, run `claimtrace review .` to read the audit or `claimtrace prepare .` to continue editing.",
            "",
            "- Open rendered panels in `renders/`, then read the claim, evidence and visual meanings below.",
            "- Review **Open items and limits** for required updates and recommendations.",
            "- Author-confirmed meanings and tool suggestions carry separate labels below.",
            "- Use `checksums/sha256.txt` to verify included files.",
            "- Native viewer files are under `native/`; files referenced by relative native paths may be co-located there for replay, while other data are under `data/`.",
            "- `semantic_layer.json` is the canonical machine-readable record for advanced review.",
        ]
    )
    lines.extend(
        [
            "",
            "## Evidence summary",
            "",
        ]
    )
    evidence_summary = _evidence_summary_lines(semantic)
    lines.extend([f"- {line}" for line in evidence_summary] or ["Claim-linked evidence entries: 0."])
    lines.extend(
        [
            "",
            "## Visual meanings",
            "",
        ]
    )
    visual_summary = _visual_summary_lines(semantic)
    lines.extend([f"- {line}" for line in visual_summary] or ["Visual meanings: awaiting author description."])
    lines.extend(
        [
            "",
            "## Open items and limits",
            "",
        ]
    )
    lines.extend([f"- {line}" for line in _open_item_lines(semantic, report)])
    lines.extend(
        [
            "",
            "## At a glance",
            "",
        ]
    )
    lines.extend(_support_map_lines(semantic, report))
    lines.extend([
        "",
        "## Claims",
        "",
    ])
    if not semantic.claims:
        from claimtrace.proposals import stored_proposals

        has_draft_claim = any(
            proposal["status"] == "pending" and any(
                change["record_type"] == "claim" for change in proposal["changes"]
            ) for proposal in stored_proposals(semantic)
        )
        lines.append(
            "A proposed statement is awaiting review in **Agent suggestions**."
            if has_draft_claim else
            "Use **Add claim** in the GUI to record the figure's statement."
        )
    for claim in semantic.claims:
        lines.extend(
            [
                f"### {claim.figure_ref}",
                "",
                f"- Text: {claim.claim_text.value}",
                f"- Type: {claim.claim_type.value}",
                f"- Figure/panel: {claim.figure_ref}",
                f"- Linked scenes: {len(claim.scene_ids)}",
                f"- Linked evidence entries: {len(claim.evidence_ids)}",
                f"- Caveats/uncertainty notes: {len(claim.uncertainty_ids)}",
                "",
            ]
        )
    lines.extend(["", "## Evidence", ""])
    artifact_labels = _artifact_label_map(semantic)
    for evidence in semantic.evidence:
        claim_links = ", ".join(evidence.claim_ids) or "claim link pending"
        lines.extend(
            [
                f"- {evidence.evidence_kind.value.replace('_', ' ')}",
                f"  Claim link: {claim_links}",
                f"  How it was checked: {evidence.method_name}",
                f"  Source files: {', '.join(_artifact_labels(evidence.source_artifact_ids, artifact_labels)) or 'source links pending'}",
                f"  Observation: {evidence.result_summary}",
            ]
        )
        if evidence.parameters.get("analysis_settings"):
            lines.append(f"  Analysis settings: {evidence.parameters['analysis_settings']}")
        if evidence.thresholds:
            lines.append("  Cutoffs: " + ", ".join(
                f"{key}: {value} {evidence.units.get(key, '')}".rstrip()
                for key, value in evidence.thresholds.items()
            ))
        if evidence.parameters.get("measured_distance") is not None:
            lines.append(
                f"  Measured distance: {evidence.parameters['measured_distance']} "
                f"{evidence.units.get('distance', '')}".rstrip()
            )
    if not semantic.evidence:
        lines.append("Evidence entries: 0.")
    lines.extend(["", "## Uncertainty", ""])
    for uncertainty in semantic.uncertainty:
        lines.append(f"- {uncertainty.category}: {uncertainty.statement}")
    if not semantic.uncertainty:
        lines.append("Recorded limitations: 0.")

    lines.extend(["## Scene files and images", ""])
    native_render_count = 0
    for artifact in semantic.artifacts:
        if artifact.role.value in {"native_script", "native_session", "chimerax_script", "molviewspec", "render_image"}:
            location = artifact.path or artifact.url or "unknown"
            label = _artifact_role_label(artifact.role.value)
            if artifact.role.value == "molviewspec" and str(location).lower().endswith(".mvsx"):
                label = "MolViewSpec archive"
            lines.append(f"- {label}: `{location}`")
            native_render_count += 1
    if native_render_count == 0:
        lines.append("Scene files and figure images: to add.")
    lines.extend(["", "## Reproduce the figure", ""])
    lines.extend(_replay_lines(semantic))
    lines.extend(["", "<details>", "<summary>Scene records and imported commands</summary>", "", "## Imported scene observations", ""])
    native_lines = _native_observation_lines(semantic)
    if native_lines:
        lines.extend(native_lines)
    else:
        lines.append("Imported scene observations: 0.")
    lines.extend(["", "## Scene details", ""])
    for scene in semantic.scenes:
        lines.append(f"### {scene.id}")
        if scene.camera.get("author_context"):
            lines.extend(["", f"Recorded view or figure settings: {scene.camera['author_context']}"])
        operations = scene.extensions.get("observed_scene_operations", [])
        if not operations:
            operations = [
                operation.model_dump(mode="json", exclude_none=True)
                for operation in semantic.observed_scene_operations
                if operation.details.get("scene_id") == scene.id
            ]
        if operations:
            lines.append("")
            lines.append("Automatically observed native scene operations:")
            for operation in operations:
                details = operation.get("details", {}) if isinstance(operation, dict) else {}
                detail_text = ", ".join(
                    f"{key}={value}"
                    for key, value in details.items()
                    if key in {"command", "kind", "method", "style", "value"}
                )
                annotation = operation.get("auto_annotation") if isinstance(operation, dict) else None
                candidate = operation.get("candidate_meaning") if isinstance(operation, dict) else None
                operation_id = operation.get("operation_id", "") if isinstance(operation, dict) else ""
                author_meaning = operation_meanings.get(operation_id)
                lines.append(
                    f"- {operation.get('operation', 'observed')} `{operation.get('target', 'unknown')}`"
                    + (f" ({detail_text})" if detail_text else "")
                    + (f" - {annotation}" if annotation else "")
                    + (f" {_visual_meaning_text(author_meaning)}" if author_meaning else "")
                    + (f" Suggested meaning awaiting review: {candidate}" if candidate and not author_meaning else "")
                )
        semantics = scene.extensions.get("user_scene_semantics", [])
        if semantics:
            lines.append("")
            lines.append("Author-provided color and label meanings:")
            semantic_items = semantics if isinstance(semantics, list) else [semantics]
            for item in semantic_items:
                color_meanings = item.get("color_meanings", {}) if isinstance(item, dict) else {}
                label_meanings = item.get("label_meanings", {}) if isinstance(item, dict) else {}
                notes = item.get("notes", "") if isinstance(item, dict) else ""
                for color, meaning in color_meanings.items():
                    lines.append(f"- Color `{color}`: {meaning}")
                for label, meaning in label_meanings.items():
                    lines.append(f"- Label `{label}`: {meaning}")
                if notes:
                    lines.append(f"- Notes: {notes}")
        if not operations and not semantics:
            lines.append("Scene operations and visual meanings: to record.")
    lines.extend(["", "</details>", "", "## Molecules and selections", ""])
    lines.append(
        f"Recorded molecules: {len(semantic.entities)}; selections: {len(semantic.selections)}. "
        "The complete records are under `entities` and `selections` in `semantic_layer.json`."
    )
    lines.extend(["", "Entries marked figure-central:", ""])
    important_count = 0
    for entity in semantic.entities:
        if entity.claim_critical:
            lines.append(f"- `{entity.id}`: {entity.label}, stable identity `{entity.stable_identity}`")
            important_count += 1
    for selection in semantic.selections:
        if selection.claim_critical:
            lines.append(f"- `{selection.id}`: native selector `{selection.native_selector.value}`")
            important_count += 1
    if important_count == 0:
        lines.append("0 marked.")
        if semantic.selections:
            lines.append("Open **Selected regions** in the GUI to inspect the recorded selections and their source commands.")
    lines.extend(["", "## Validation", ""])
    if report:
        failed = [item for item in report.findings if item.status == "FAIL"]
        blocking = [
            item
            for item in failed
            if item.severity == "ERROR" and report.export_mode in item.blocks_modes
        ]
        recommended = [item for item in failed if item not in blocking]
        lines.extend(
            [
                f"- Overall status: `{report.overall_status}`",
                f"- Blocking updates: {len(blocking)}",
                f"- Recommended updates: {len(recommended)}",
                f"- Waiver records: {len(report.waiver_list)}",
                f"- Findings waived: {_waived_finding_count(report)}",
                "- Full machine-readable report: `validation_report.json`",
            ]
        )
        lines.extend(_validation_next_actions(report))
    else:
        lines.append("Run `claimtrace validate .` to generate `validation_report.json`.")
    lines.extend(
        [
            "",
            "## Checksums",
            "",
            "Package checksums are in `checksums/sha256.txt`.",
            "",
            "## Reuse",
            "",
            f"- License: {semantic.reuse.license or semantic.package.license}",
            f"- Citation: {semantic.reuse.citation or 'unknown'}",
        ]
    )
    if semantic.reuse.restrictions:
        lines.append(f"- Restrictions: {', '.join(semantic.reuse.restrictions)}")
    return "\n".join(lines).rstrip() + "\n"


def _review_summary_lines(semantic: SemanticLayer, report: ValidationReport | None) -> list[str]:
    claim = semantic.claims[0] if semantic.claims else None
    lines = [
        f"- Figure/panel: {claim.figure_ref if claim else 'to record'}",
        f"- Claim: {claim.claim_text.value if claim else 'to record'}",
        f"- Readiness: {_readiness_text(report)}",
    ]
    renders = [
        artifact.path or artifact.url or "unknown"
        for artifact in semantic.artifacts
        if artifact.role.value == "render_image"
    ]
    lines.append(f"- Rendered panel: {', '.join(f'`{item}`' for item in renders) if renders else 'to record'}")
    evidence = _evidence_summary_lines(semantic, limit=2)
    lines.append(f"- Evidence summary: {'; '.join(evidence) if evidence else 'to record'}")
    visual = _visual_summary_lines(semantic, limit=2)
    lines.append(f"- Visual meanings: {'; '.join(visual) if visual else 'to record'}")
    if report is not None and report.overall_status == "pass":
        note_count = len(report.human_review_required)
        suffix = "; additional review items in `human_review_required` in `validation_report.json`" if note_count else ""
        lines.append(f"- Selected export checks: passed{suffix}")
    else:
        open_items = _open_item_lines(semantic, report, limit=2)
        lines.append(f"- Open items: {'; '.join(open_items) if open_items else 'to record'}")
    return lines


def _proposal_lines(semantic: SemanticLayer) -> list[str]:
    from claimtrace.proposals import stored_proposals

    pending = [p for p in stored_proposals(semantic) if p["status"] == "pending"]
    if not pending:
        return []
    lines = [
        "", "## Suggestions awaiting review", "",
        "These proposed changes are saved for human review. Current claim and evidence records appear below.",
        "Open **Agent suggestions** in the GUI, or run `claimtrace agent proposals . --status pending` to read the changes and sources.",
    ]
    labels = {
        "claim_text": "Proposed statement", "figure_ref": "Figure label",
        "method_name": "How it was checked", "result_summary": "Proposed observation",
        "statement": "Proposed limitation",
    }
    artifacts = _artifact_label_map(semantic)
    for proposal in pending:
        lines.extend(["", f"### {proposal['title']}", "", f"- Proposal: `{proposal['id']}`",
                      f"- Prepared by: {proposal['actor']['name']}"])
        if proposal.get("rationale"):
            lines.append(f"- Rationale: {proposal['rationale']}")
        for change in proposal["changes"]:
            for field, value in change["fields"].items():
                if field in labels:
                    lines.append(f"- {labels[field]}: {value}")
        sources = _artifact_labels(proposal.get("source_artifact_ids", []), artifacts)
        if sources:
            lines.append(f"- Source files: {', '.join(sources)}")
    return lines


def _static_figures_only(semantic: SemanticLayer) -> bool:
    return bool(semantic.scenes) and all(
        scene.extensions.get("view_kind") in {"plot", "figure_assembly"}
        and not scene.native_artifact_ids for scene in semantic.scenes
    )


def _replay_lines(semantic: SemanticLayer) -> list[str]:
    if _static_figures_only(semantic):
        lines = [
            "Review the linked analysis sources and recorded figure settings. "
            "Use the original analysis or figure-assembly tools to reproduce these static figures."
        ]
        for scene in semantic.scenes:
            context = scene.camera.get("author_context")
            lines.append(f"- Figure settings (`{scene.id}`): {context or 'to record'}")
        return lines
    lines = [
        "ClaimTrace imports saved scene instructions. Open the scene in its original viewer to check loading, selections, and the saved view. Assess the scientific claim using the linked evidence and limitations.",
        "Replay only native scripts you trust. Review raw or unknown commands first, and use an isolated, network-restricted viewer when provenance is uncertain.",
    ]
    unresolved = [
        resource.uri
        for resource in semantic.resource_references
        if resource.uri_kind in {"relative", "local", "missing_archive_member"}
        and not resource_matches_artifact(semantic, resource.uri, resource_ref=resource)
    ]
    if unresolved:
        lines.append(
            "- Add these referenced files to complete the local replay package: "
            + ", ".join(f"`{resource_uri_summary(item)}`" for item in unresolved)
        )
    remote = [
        resource.uri
        for resource in semantic.resource_references
        if resource.uri_kind == "remote" and resource.fetch_status != "fetched"
    ]
    if remote:
        lines.append(
            "- Replay may need network access for: "
            + ", ".join(f"`{resource_uri_summary(item)}`" for item in remote[:5])
        )
    pymol_scripts = [
        artifact for artifact in semantic.artifacts
        if artifact.role.value == "native_script" and artifact.path and artifact.path.lower().endswith(".pml")
    ]
    for artifact in pymol_scripts:
        path = PurePosixPath(str(artifact.path))
        parent = path.parent.as_posix()
        filename = path.name
        posix_parent = shlex.quote(parent)
        posix_name = shlex.quote(filename)
        powershell_parent = _powershell_quote(parent)
        powershell_name = _powershell_quote(f".\\{filename}")
        lines.extend(
            [
                f"- PyMOL scene: `{artifact.path}`. Start PyMOL with `{parent}` as the working directory so relative `load` paths resolve.",
                f"  - Bash: `cd {posix_parent} && pymol {posix_name}`",
                f"  - PowerShell: `Set-Location {powershell_parent}; pymol {powershell_name}`",
            ]
        )
    sessions = [
        artifact.path for artifact in semantic.artifacts
        if artifact.role.value == "native_session" and artifact.path
    ]
    for path in sessions:
        lines.append(f"- PyMOL session: open `{path}` in a compatible local PyMOL version.")
    chimerax_scripts = [
        artifact for artifact in semantic.artifacts
        if artifact.role.value == "chimerax_script" and artifact.path and artifact.path.lower().endswith(".cxc")
    ]
    for artifact in chimerax_scripts:
        path = PurePosixPath(str(artifact.path))
        parent = path.parent.as_posix()
        filename = path.name
        posix_parent = shlex.quote(parent)
        posix_name = shlex.quote(filename)
        powershell_parent = _powershell_quote(parent)
        powershell_name = _powershell_quote(f".\\{filename}")
        lines.extend(
            [
                f"- ChimeraX scene: `{artifact.path}`. Start UCSF ChimeraX with `{parent}` as the working directory so relative `open` paths resolve.",
                f"  - Bash: `cd {posix_parent} && chimerax {posix_name}`",
                f"  - PowerShell: `Set-Location {powershell_parent}; chimerax {powershell_name}`",
            ]
        )
    inventories = {inventory.artifact_id: inventory for inventory in semantic.mvsx_inventories}
    mvs_artifacts = [
        artifact for artifact in semantic.artifacts
        if artifact.role.value == "molviewspec" and artifact.path
    ]
    for artifact in mvs_artifacts:
        suffix = PurePosixPath(str(artifact.path)).suffix.lower()
        if suffix == ".mvsj":
            lines.append(
                f"- MolViewSpec JSON: `{artifact.path}`. Open or drag it into a Mol* viewer with MolViewSpec support. "
                "Make referenced resources available through URLs the browser can access."
            )
        elif suffix == ".mvsx":
            inventory = inventories.get(artifact.id)
            if inventory and inventory.format_status != "standard":
                lines.append(
                    f"- MolViewSpec archive to update: `{artifact.path}`. ClaimTrace read `{inventory.scene_entry}`. "
                    "Rebuild the archive with a top-level `index.mvsj` for standard MVSX replay in Mol*."
                )
            else:
                lines.append(
                    f"- MolViewSpec archive: `{artifact.path}`. Open or drag the `.mvsx` into a Mol* viewer with MolViewSpec support; embedded resources stay inside the archive."
                )
    if not pymol_scripts and not sessions and not chimerax_scripts and not mvs_artifacts:
        lines.append("- Attach a saved viewer scene to prepare replay.")
    return lines


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _readiness_text(report: ValidationReport | None) -> str:
    if report is None:
        return "validation pending"
    if report.overall_status == "pass":
        waived = _waived_finding_count(report)
        suffix = f" with {waived} waived finding(s)" if waived else ""
        return f"ready for `{report.export_mode}` handoff{suffix}"
    if report.overall_status == "pass_with_warnings":
        return f"ready for `{report.export_mode}` with warnings"
    if report.overall_status == "fail":
        errors = report.summary.get("errors", 0)
        warnings = report.summary.get("warnings", 0)
        return f"has {errors} blocking update(s) and {warnings} warning(s)"
    return str(report.overall_status)


def _evidence_summary_lines(semantic: SemanticLayer, limit: int | None = None) -> list[str]:
    lines: list[str] = []
    linked_ids = {evidence_id for claim in semantic.claims for evidence_id in claim.evidence_ids}
    for evidence in semantic.evidence:
        if evidence.id not in linked_ids:
            continue
        summary = evidence.result_summary or "to record"
        method = evidence.method_name if evidence.method_name and evidence.method_name != "unknown" else ""
        prefix = f"{method}: " if method else ""
        lines.append(f"{prefix}{summary}")
        if limit is not None and len(lines) >= limit:
            break
    return lines


def _visual_summary_lines(semantic: SemanticLayer, limit: int | None = None) -> list[str]:
    operation_by_id = {operation.operation_id: operation for operation in semantic.observed_scene_operations}
    lines: list[str] = []
    for item in semantic.visual_encoding_semantics:
        operations = [operation_by_id.get(operation_id) for operation_id in item.operation_ids]
        operation = next((value for value in operations if value is not None), None)
        target = getattr(operation, "target", "") or "scene"
        feature = getattr(operation, "operation", item.encoding_type).replace("_", " ")
        status = item.meaning_status.value
        if status == "user_confirmed_meaning":
            meaning = item.meaning or "author confirmed"
            lines.append(f"{feature} on `{target}`: {meaning}")
        elif status == "user_declared_no_scientific_meaning":
            reason = item.no_scientific_meaning_reason or "presentation only"
            lines.append(f"{feature} on `{target}`: presentation only ({reason})")
        elif status == "tool_suggested_meaning":
            candidate = item.candidate_meaning or "tool suggestion"
            lines.append(f"{feature} on `{target}`: suggested meaning awaiting review ({candidate})")
        else:
            lines.append(f"{feature} on `{target}`: {status}")
        if limit is not None and len(lines) >= limit:
            break
    if lines:
        return lines
    suggestions = [
        operation
        for operation in semantic.observed_scene_operations
        if operation.candidate_meaning and operation.needs_author_confirmation
    ]
    for operation in suggestions[: limit or len(suggestions)]:
        lines.append(f"{operation.operation.replace('_', ' ')} on `{operation.target or 'scene'}`: needs review")
    return lines


def _open_item_lines(
    semantic: SemanticLayer,
    report: ValidationReport | None,
    limit: int | None = None,
) -> list[str]:
    lines: list[str] = []
    if report is not None:
        failed = [item for item in report.findings if item.status == "FAIL"]
        required = [
            item
            for item in failed
            if item.severity == "ERROR" and report.export_mode in item.blocks_modes
        ]
        warnings = [item for item in failed if item not in required]
        for item in required:
            lines.append(f"Required: {item.message}")
        for item in warnings:
            lines.append(f"Recommended: {item.message}")
        note_count = len(report.human_review_required)
        if note_count and lines:
            lines.append(f"Additional review items: {note_count}; see `human_review_required` in `validation_report.json`.")
        if note_count and not lines and report.overall_status != "pass":
            lines.append(f"Additional review items: {note_count}; see `human_review_required` in `validation_report.json`.")
        if not lines and report.overall_status == "pass":
            lines.append(f"Required checks passed for `{report.export_mode}` export")
            if note_count:
                lines.append(f"Additional review items: {note_count}; see `human_review_required` in `validation_report.json`.")
        if report.native_inference_limits:
            lines.extend([
                "Scope: Reproduce static figures using their analysis sources and recorded plotting or assembly settings."
                if _static_figures_only(semantic) else
                "Scope: Imported scene instructions preserve visual context. Viewer loading, selections, and rendered output require a replay check.",
                "Evidence: Assess claim support from linked source files and author-reviewed observations.",
            ])
    if not lines:
        unconfirmed = [
            operation
            for operation in semantic.observed_scene_operations
            if operation.needs_author_confirmation and operation.candidate_meaning
        ]
        for operation in unconfirmed:
            lines.append(f"Review visual meaning for {operation.operation} `{operation.target or 'scene'}`")
    if limit is not None:
        return lines[:limit]
    return lines or ["Open **Prepare** in the GUI to review the available claim context."]


def _native_observation_lines(semantic: SemanticLayer) -> list[str]:
    lines: list[str] = []
    operation_meanings = _visual_meaning_by_operation(semantic)
    scene_extension_operations = [
        operation
        for scene in semantic.scenes
        for operation in scene.extensions.get("observed_scene_operations", [])
        if isinstance(operation, dict)
    ]
    if semantic.observed_scene_operations:
        lines.append("Observed scene operations:")
        for operation in semantic.observed_scene_operations:
            target = f" `{operation.target}`" if operation.target else ""
            line = f"- `{operation.operation_id}`: {operation.operation}{target}"
            if operation.auto_annotation:
                line += f" - {operation.auto_annotation}"
            author_meaning = operation_meanings.get(operation.operation_id)
            if author_meaning:
                line += f" {_visual_meaning_text(author_meaning)}"
            elif operation.candidate_meaning:
                line += f" Tool suggestion (unconfirmed): {operation.candidate_meaning}"
            author_reviewed = author_meaning and getattr(author_meaning, "meaning_status", None).value in {
                "user_confirmed_meaning",
                "user_declared_no_scientific_meaning",
            }
            if operation.needs_author_confirmation and not author_reviewed:
                line += " Confirmation needed."
            lines.append(line)
    elif scene_extension_operations:
        lines.append("Observed scene operations:")
        for operation in scene_extension_operations:
            target = f" `{operation.get('target')}`" if operation.get("target") else ""
            op_id = operation.get("operation_id", "scene-level")
            lines.append(f"- `{op_id}`: {operation.get('operation', 'observed')}{target}")
    if semantic.visual_encoding_semantics:
        if lines:
            lines.append("")
        lines.append("Author-reviewed operation meanings and remaining suggestions:")
        for item in semantic.visual_encoding_semantics:
            operation_ids = ", ".join(item.operation_ids) or "link pending"
            if item.meaning_status.value == "tool_suggested_meaning":
                meaning = f"tool suggestion, unconfirmed: {item.candidate_meaning or 'to record'}"
            elif item.meaning_status.value == "user_declared_no_scientific_meaning":
                meaning = f"presentation only: {item.no_scientific_meaning_reason or 'to record'}"
            elif item.meaning_status.value == "user_confirmed_meaning":
                meaning = f"author confirmed: {item.meaning or 'to record'}"
            else:
                meaning = item.meaning or item.no_scientific_meaning_reason or "to record"
            lines.append(f"- `{operation_ids}`: {item.meaning_status.value}; {meaning}")
    if semantic.native_references:
        if lines:
            lines.append("")
        lines.append("Native references needing or containing identity context:")
        for ref in semantic.native_references:
            identity = ref.stable_identity or "unknown"
            lines.append(f"- `{ref.native_ref_id}`: `{ref.native_expression}` -> {identity}")
    if semantic.raw_native_observations:
        if lines:
            lines.append("")
        lines.append("Raw/native items preserved for author review:")
        for raw in semantic.raw_native_observations:
            lines.append(f"- `{raw.raw_id}`: {raw.reason}; resolution `{raw.resolution}`")
    if semantic.resource_references:
        if lines:
            lines.append("")
        lines.append("Native resource references:")
        for resource in semantic.resource_references:
            lines.append(
                f"- `{resource.resource_ref_id}` ({resource.uri_kind}, fixity {resource.fixity_status}): `{resource_uri_summary(resource.uri)}`"
            )
    if semantic.mvsx_inventories:
        if lines:
            lines.append("")
        lines.append("MolViewSpec archive inventory:")
        for inventory in semantic.mvsx_inventories:
            referenced = [member for member in inventory.members if member.referenced]
            lines.append(
                f"- `{inventory.artifact_id}`: entry `{inventory.scene_entry or 'unknown'}`, "
                f"{len(inventory.members)} member(s), {len(referenced)} referenced, status `{inventory.format_status}`"
            )
            for member in referenced[:5]:
                digest = f", sha256 `{member.sha256[:16]}…`" if member.sha256 else ""
                lines.append(f"  - `{member.normalized_name}`{digest}")
    return lines


def _visual_meaning_by_operation(semantic: SemanticLayer) -> dict[str, object]:
    by_operation: dict[str, object] = {}
    for item in semantic.visual_encoding_semantics:
        for operation_id in item.operation_ids:
            by_operation[operation_id] = item
    return by_operation


def _visual_meaning_text(item: object) -> str:
    status = getattr(getattr(item, "meaning_status", None), "value", "")
    if status == "user_confirmed_meaning":
        meaning = getattr(item, "meaning", None) or "to record"
        return f"Author confirmed: {meaning}"
    if status == "user_declared_no_scientific_meaning":
        reason = getattr(item, "no_scientific_meaning_reason", None) or "to record"
        return f"Presentation only: {reason}"
    if status == "tool_suggested_meaning":
        candidate = getattr(item, "candidate_meaning", None) or "to record"
        return f"Tool suggestion (unconfirmed): {candidate}"
    return ""


def _support_map_lines(semantic: SemanticLayer, report: ValidationReport | None) -> list[str]:
    artifact_labels = _artifact_label_map(semantic)
    status = report.overall_status if report else "validation pending"
    lines = [f"- Validation status: `{status}`"]
    lines.append("- Validation scope: package completeness, traceability, paths and fixity.")
    lines.append(
        "- Native/render files: "
        f"{_role_presence(semantic, {'native_script', 'native_session', 'chimerax_script', 'molviewspec'})} "
        f"/ {_role_presence(semantic, {'render_image'})}"
    )
    lines.append(f"- Structure/map files: {_role_presence(semantic, {'structure', 'map'})}")
    lines.append(f"- Evidence entries: {len(semantic.evidence)} recorded" if semantic.evidence else "- Evidence entries: 0")
    lines.append(
        "- Dedicated evidence/validation files: "
        f"{_role_presence(semantic, {'contact_table', 'validation_report', 'evidence_document'})}"
    )
    if not semantic.claims:
        lines.append("- Claim summary: to record")
        return lines
    for claim in semantic.claims:
        lines.append(f"- `{claim.figure_ref}`: {claim.claim_text.value}")
        render_ids = [
            artifact_id
            for scene in semantic.scenes
            if scene.id in claim.scene_ids
            for artifact_id in scene.render_artifact_ids
        ]
        native_ids = [
            artifact_id
            for scene in semantic.scenes
            if scene.id in claim.scene_ids
            for artifact_id in scene.native_artifact_ids
        ]
        evidence_artifact_ids = [
            artifact_id
            for evidence in semantic.evidence
            if evidence.id in claim.evidence_ids
            for artifact_id in evidence.source_artifact_ids
        ]
        if render_ids:
            lines.append(f"  Renders: {', '.join(_artifact_labels(render_ids, artifact_labels))}")
        if native_ids:
            lines.append(f"  Native files: {', '.join(_artifact_labels(native_ids, artifact_labels))}")
        if evidence_artifact_ids:
            lines.append(f"  Supporting files: {', '.join(_artifact_labels(evidence_artifact_ids, artifact_labels))}")
        if not evidence_artifact_ids:
            lines.append("  Supporting files: links pending")
    return lines


def _artifact_label_map(semantic: SemanticLayer) -> dict[str, str]:
    return {
        artifact.id: f"`{artifact.path or artifact.url or 'to record'}` ({_artifact_role_label(artifact.role.value)})"
        for artifact in semantic.artifacts
    }


def _artifact_role_label(role: str) -> str:
    labels = {
        "native_script": "PyMOL scene",
        "native_session": "PyMOL session",
        "chimerax_script": "ChimeraX scene",
        "molviewspec": "MolViewSpec scene",
        "render_image": "Rendered panel",
        "structure": "Structure file",
        "map": "Map file",
        "trajectory": "Trajectory file",
        "topology": "Topology file",
        "contact_table": "Contact table",
        "validation_report": "Validation report",
        "evidence_document": "Evidence note",
        "directory": "Directory artifact",
        "generic": "Supporting file",
        "package_metadata": "Package metadata",
    }
    return labels.get(role, role.replace("_", " "))


def _role_presence(semantic: SemanticLayer, roles: set[str]) -> str:
    count = sum(1 for artifact in semantic.artifacts if artifact.role.value in roles)
    return f"{count} present" if count else "to record"


def _artifact_labels(ids: list[str], labels: dict[str, str]) -> list[str]:
    return [labels.get(artifact_id, f"`{artifact_id}`") for artifact_id in ids]


def _validation_next_actions(report: ValidationReport) -> list[str]:
    findings = [item for item in report.findings if item.status == "FAIL"]
    if not findings:
        lines = ["", "Next actions:", f"- Package checks passed for `{report.export_mode}` mode."]
        if report.waiver_list:
            lines.append(f"- Review the {len(report.waiver_list)} recorded waiver(s) before reuse.")
            for waiver in report.waiver_list[:5]:
                lines.append(
                    f"  - `{waiver.get('rule_id', 'unknown')}`: {waiver.get('reason', 'Reason to add.')}"
                )
        return lines
    required = [
        item
        for item in findings
        if item.severity == "ERROR" and report.export_mode in item.blocks_modes
    ]
    recommended = [item for item in findings if item not in required]
    lines = ["", "Next actions:"]
    if required:
        lines.append(f"Required before `{report.export_mode}`:")
        for item in required[:8]:
            lines.extend(_finding_lines(item))
    else:
        lines.append(f"- Required checks passed for `{report.export_mode}`.")
    if recommended:
        lines.append("")
        lines.append("Recommended:")
        for item in recommended[:6]:
            lines.extend(_finding_lines(item))
    return lines


def _waived_finding_count(report: ValidationReport) -> int:
    return sum(1 for item in report.findings if item.status == "WAIVED")


def _finding_lines(item) -> list[str]:
    lines = [f"- `{item.rule_id}`: {item.message}"]
    if item.json_pointer:
        lines.append(f"  Edit: `{item.json_pointer}`")
    if item.suggested_fix:
        lines.append(f"  Next: {item.suggested_fix}")
    return lines
