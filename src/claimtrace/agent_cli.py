"""Noninteractive, versioned JSON interface for agent-assisted authoring."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import typer
from pydantic import ValidationError

from claimtrace.api import load_package
from claimtrace.gui.server import Application
from claimtrace.proposals import (
    PROTOCOL_VERSION,
    check_proposal,
    create_proposal,
    proposal_schema,
    review_proposal,
    stored_proposals,
)
from claimtrace.workflow import review_package

agent_app = typer.Typer(
    help="Inspect records, propose changes, and record explicit human decisions."
)


def _output(data: dict[str, Any]) -> None:
    typer.echo(
        json.dumps(
            {"protocol_version": PROTOCOL_VERSION, "ok": True, **data},
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
    )


def _error(exc: Exception) -> None:
    if isinstance(exc, ValidationError):
        errors = [
            {"code": e["type"], "pointer": "/" + "/".join(map(str, e["loc"])), "message": e["msg"]}
            for e in exc.errors()
        ]
    else:
        errors = [
            {
                "code": getattr(exc, "code", "invalid_input"),
                "pointer": getattr(exc, "pointer", ""),
                "message": str(exc),
            }
        ]
    _output({"ok": False, "errors": errors})
    raise typer.Exit(1)


def _read(path: Path):
    def reject(value):
        raise ValueError(f"Use a finite JSON number in place of {value}.")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)


@agent_app.command("schema")
def schema() -> None:
    """Print the proposal input schema and supported field names."""
    _output({"schema": proposal_schema()})


@agent_app.command("inspect")
def inspect_package(
    package: Path = typer.Argument(..., help="ClaimTrace package folder."),
    claim: Optional[str] = typer.Option(
        None, "--claim", help="Focus the audit on a stable claim ID."
    ),
    mode: Optional[str] = typer.Option(
        None,
        "--mode",
        help="Purpose: draft, internal, share or archive; defaults to the saved purpose.",
    ),
    summary: bool = typer.Option(
        False,
        "--summary",
        help="Read a compact audit and source index before opening full records.",
    ),
) -> None:
    """Read current records, audit, review needs and pending proposals."""
    try:
        state = review_package(package, mode=mode)
        audit, workflow = state["audit"], state["workflow"]
        if claim:
            if claim not in {c["id"] for c in audit["claims"]}:
                raise ValueError("Choose a claim ID from the current package.")
            audit = {**audit, "claims": [c for c in audit["claims"] if c["id"] == claim]}
            tasks = [t for t in workflow["tasks"] if t.get("claim_id") in {None, claim}]
            workflow = {**workflow, "tasks": tasks, "next_action": tasks[0] if tasks else None}
        values = stored_proposals(load_package(package).semantic_layer)
        result = {
            "package": state["root"],
            "mode": state["workflow"]["lifecycle"]["mode"],
            "semantic": state["semantic"],
            "audit": audit,
            "validation": state["report"],
            "workflow": workflow,
            "proposals": values,
            "scope": {"claim_id": claim, "validation": "package", "detail": "full"},
        }
        if summary:
            result.pop("semantic")
            result["scope"]["detail"] = "summary"
            graph_fields = {
                "operation_ids", "raw_observation_ids", "evidence_binding_ids",
                "resource_ref_ids", "resource_artifact_ids", "artifact_ids",
            }
            result["audit"] = {
                **audit,
                "claims": [
                    {key: value for key, value in item.items() if key not in graph_fields}
                    for item in audit["claims"]
                ],
            }
            result["artifacts"] = [
                {k: a[k] for k in ("id", "path", "url", "role", "description") if a.get(k)}
                for a in state["semantic"]["artifacts"]
            ]
            report = state["report"]
            result["validation"] = {
                "overall_status": report["overall_status"],
                "export_mode": report["export_mode"],
                "summary": report["summary"],
                "findings": [
                    {
                        k: f[k]
                        for k in (
                            "rule_id",
                            "severity",
                            "status",
                            "message",
                            "json_pointer",
                            "blocks_modes",
                        )
                    }
                    | {"blocking": f["status"] == "FAIL" and f["severity"] == "ERROR"
                       and report["export_mode"] in f["blocks_modes"]}
                    for f in report["findings"]
                    if f["status"] != "PASS"
                ],
            }
            result["proposals"] = [
                {
                    k: p[k]
                    for k in ("id", "title", "status", "claim_id", "actor", "review")
                    if k in p
                }
                for p in values
            ]
        _output(result)
    except Exception as exc:
        _error(exc)


@agent_app.command("check")
def check(
    package: Path = typer.Argument(...),
    input_file: Path = typer.Option(
        ..., "--input", help="Proposal JSON file to check without saving."
    ),
) -> None:
    """Validate a proposal and preview its changes without writing files."""
    try:
        pkg = load_package(package)
        preview = check_proposal(pkg, _read(input_file))
        _output({"package": str(pkg.root.resolve()), "preview": preview, "errors": []})
    except Exception as exc:
        _error(exc)


@agent_app.command("propose")
def propose(
    package: Path = typer.Argument(...),
    input_file: Path = typer.Option(
        ..., "--input", help="Proposal JSON with an explicit actor and stable proposal ID."
    ),
    workspace: Optional[Path] = typer.Option(
        None, "--workspace", help="Parent folder for working copies of received exports."
    ),
) -> None:
    """Save a pending proposal while preserving accepted scientific records."""
    try:
        data = _read(input_file)
        application = Application(package, workspace, interface="cli")
        check_proposal(application.require_package(), data)
        with application.edit_package() as original:
            result = create_proposal(application.require_package(), data)
        _output(
            {
                "package": str(application.require_package().root),
                "proposal": result,
                "working_copy_from": original,
            }
        )
    except Exception as exc:
        _error(exc)


@agent_app.command("proposals")
def proposals(
    package: Path = typer.Argument(...),
    status: Optional[str] = typer.Option(
        None, "--status", help="Filter pending, accepted, rejected or reverted proposals."
    ),
) -> None:
    """List saved proposals and their human review decisions."""
    try:
        if status and status not in {"pending", "accepted", "rejected", "reverted"}:
            raise ValueError("Choose pending, accepted, rejected or reverted.")
        pkg = load_package(package)
        values = stored_proposals(pkg.semantic_layer)
        _output(
            {
                "package": str(pkg.root.resolve()),
                "proposals": [p for p in values if status is None or p["status"] == status],
            }
        )
    except Exception as exc:
        _error(exc)


@agent_app.command("review")
def review(
    package: Path = typer.Argument(...),
    proposal_id: str = typer.Argument(...),
    decision: str = typer.Option(
        ..., "--decision", help="The user's decision: accept, reject or revert."
    ),
    reviewer: str = typer.Option(
        ..., "--reviewer", help="Name of the person who made this decision."
    ),
    note: str = typer.Option("", "--note", help="Optional review note."),
    edits: Optional[Path] = typer.Option(
        None,
        "--edits",
        help="JSON array of reviewed changes, retaining the proposed record IDs and field names.",
    ),
    workspace: Optional[Path] = typer.Option(
        None, "--workspace", help="Parent folder for working copies of received exports."
    ),
) -> None:
    """Record a specific human decision and preserve its provenance."""
    try:
        edited = _read(edits) if edits else None
        if edited is not None and (
            not isinstance(edited, list) or any(not isinstance(c, dict) for c in edited)
        ):
            raise ValueError("Provide the reviewed changes as a JSON array.")
        application = Application(package, workspace, interface="cli")
        with application.edit_package() as original:
            result = review_proposal(
                application.require_package(),
                proposal_id,
                decision=decision,
                reviewer=reviewer,
                note=note,
                changes=edited,
            )
        _output(
            {
                "package": str(application.require_package().root),
                "proposal": result,
                "working_copy_from": original,
            }
        )
    except Exception as exc:
        _error(exc)
