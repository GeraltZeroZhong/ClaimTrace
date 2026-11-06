"""Source-linked agent proposals and explicit human review over CAL records.

Proposals are retained in a versioned extension. Creating one leaves scientific
records unchanged; acceptance applies a validated field patch to current records.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from claimtrace._finite import ensure_finite

from claimtrace.api import ClaimTracePackage
from claimtrace.models.semantic_layer import (
    Agent,
    Claim,
    Entity,
    Evidence,
    ProvenancedString,
    Scene,
    Selection,
    SemanticLayer,
    SourceLocation,
    Uncertainty,
    VisibilityRecord,
    utc_now,
)
from claimtrace.package.resources import synchronize_resource_bindings

PROTOCOL_VERSION = "1"
EXTENSION = "agent_proposals_v1"
RecordType = Literal["claim", "evidence", "uncertainty", "scene", "selection", "entity"]
RECORDS = {
    "claim": ("claims", Claim),
    "evidence": ("evidence", Evidence),
    "uncertainty": ("uncertainty", Uncertainty),
    "scene": ("scenes", Scene),
    "selection": ("selections", Selection),
    "entity": ("entities", Entity),
}
FIELDS = {
    "claim": {"claim_text", "claim_type", "figure_ref", "scope", "scene_ids"},
    "evidence": {
        "evidence_kind",
        "method_name",
        "method_version",
        "result_summary",
        "parameters",
        "thresholds",
        "units",
        "source_artifact_ids",
        "target_selection_ids",
        "target_entity_ids",
        "limitations",
        "alternative_explanations",
        "result_summary_structured",
    },
    "uncertainty": {"statement", "category", "alternative_explanations"},
    "scene": {
        "description",
        "camera",
        "visibility",
        "selection_ids",
        "entity_ids",
        "accessibility",
    },
    "selection": {"name", "native_selector", "entity_ids", "claim_critical"},
    "entity": {"entity_type", "label", "stable_identity", "source_artifact_ids", "claim_critical"},
}
LABELS = {
    "claim_text": "Figure statement",
    "figure_ref": "Figure label",
    "claim_type": "Statement type",
    "method_name": "How it was checked",
    "result_summary": "What was found",
    "thresholds": "Cutoffs",
    "units": "Units",
    "parameters": "Analysis settings",
    "statement": "Limitation",
    "source_artifact_ids": "Source files",
    "target_selection_ids": "Regions used in this check",
    "target_entity_ids": "Molecules and residues",
    "camera": "View, camera, and state",
    "native_selector": "Region selection",
    "accessibility": "Accessible figure description",
}


class ProposalError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_proposal", pointer: str = ""):
        super().__init__(message)
        self.code = code
        self.pointer = pointer


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Actor(InputModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str | None = None
    provider: str | None = None
    model: str | None = None


class ToolCall(InputModel):
    tool: str = Field(min_length=1)
    version: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    input_artifact_ids: list[str] = Field(default_factory=list)
    output_artifact_ids: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)


class Change(InputModel):
    record_type: RecordType
    record_id: str = Field(min_length=1)
    claim_id: str | None = None
    fields: dict[str, Any] = Field(min_length=1)


class ProposalInput(InputModel):
    schema_version: Literal["1"] = PROTOCOL_VERSION
    id: str = Field(min_length=1)
    actor: Actor
    title: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    claim_id: str | None = None
    source_artifact_ids: list[str] = Field(default_factory=list)
    changes: list[Change] = Field(min_length=1)
    tool_calls: list[ToolCall] = Field(default_factory=list)

    @field_validator("changes")
    @classmethod
    def unique_targets(cls, changes):
        targets = [(c.record_type, c.record_id) for c in changes]
        if len(targets) != len(set(targets)):
            raise ValueError("Combine edits for the same record into one change.")
        return changes


def proposal_schema() -> dict[str, Any]:
    schema = ProposalInput.model_json_schema()
    variants = []
    for kind, (_, model) in RECORDS.items():
        record_schema = model.model_json_schema()

        def expand(value):
            if isinstance(value, list):
                return [expand(item) for item in value]
            if isinstance(value, dict):
                if "$ref" in value:
                    return expand(record_schema["$defs"][value["$ref"].rsplit("/", 1)[-1]])
                return {key: expand(item) for key, item in value.items()}
            return value

        fields = {
            name: expand(record_schema["properties"][name])
            for name in sorted(FIELDS[kind])
            if name != "accessibility"
        }
        for name in {"claim_text", "native_selector"} & fields.keys():
            fields[name] = {"type": "string", "minLength": 1}
        if kind == "scene":
            fields["accessibility"] = {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    name: {"type": "string"}
                    for name in (
                        "alt_text",
                        "caption",
                        "palette_description",
                        "non_color_encoding",
                        "viewer_fallback",
                    )
                },
            }
        if "units" in fields:
            fields["units"]["additionalProperties"] = {"type": ["string", "null"]}
        if kind == "evidence":
            fields["parameters"]["description"] = (
                "Merged settings. For measurement evidence, use measured_distance for the observed "
                "positive distance. A null value removes that key."
            )
            fields["thresholds"]["description"] = (
                "Merged cutoffs. Contact tables require a positive distance key. "
                "Measurement evidence uses parameters.measured_distance."
            )
            fields["units"]["description"] = (
                "Distance evidence uses the distance key, e.g. angstrom."
            )
        variant = deepcopy(schema["$defs"]["Change"])
        variant["properties"]["record_type"] = {"const": kind}
        variant["properties"]["fields"] = {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": False,
            "properties": fields,
        }
        variants.append(variant)
    schema["$defs"]["Change"] = {"oneOf": variants}
    schema["x-record-fields"] = {key: sorted(value) for key, value in FIELDS.items()}
    schema["x-field-notes"] = {
        "claim_text": "Plain text. Source and review metadata are recorded by ClaimTrace.",
        "native_selector": "Plain native selection text; preserve the originating viewer syntax.",
        "parameters": "Top-level map keys merge. A measurement uses measured_distance with a positive value. Use null to remove a key.",
        "thresholds": "Top-level keys merge; a contact table requires a positive distance cutoff.",
        "units": "Use units.distance for measurements and contact tables, e.g. angstrom.",
        "camera": "Proposed saved view metadata; native viewer replay is checked separately.",
        "accessibility": "Map of alt_text, caption, palette_description, non_color_encoding, viewer_fallback to text.",
        "claim_id": "Required on a new evidence or uncertainty record. Existing links are preserved.",
    }
    return schema


def stored_proposals(semantic: SemanticLayer) -> list[dict[str, Any]]:
    value = semantic.extensions.get(EXTENSION, [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ProposalError("Restore the agent proposal list in this package.")
    return deepcopy(value)


def _get(semantic: SemanticLayer, kind: str, identity: str):
    return next((r for r in getattr(semantic, RECORDS[kind][0]) if r.id == identity), None)


def _field(record, name: str):
    if record is None:
        return None
    if name in {"claim_text", "native_selector"}:
        return getattr(record, name).value
    if name == "accessibility":
        return record.extensions.get("accessibility", {})
    return record.model_dump(mode="json").get(name)


def _references(values, known: set[str], label: str) -> None:
    if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
        raise ProposalError(f"Choose {label} using a list of record IDs.")
    missing = set(values) - known
    if missing:
        raise ProposalError(f"Choose {label} from this package: {', '.join(sorted(missing))}.")


def _nonempty(value, label: str) -> None:
    if not isinstance(value, str) or value.strip().lower() in {"", "unknown", "todo", "tbd"}:
        raise ProposalError(f"Enter {label}.")


def _check_new_reference_errors(before: SemanticLayer, after: SemanticLayer) -> None:
    from claimtrace.validation.engine import _reference_findings

    # Retain existing draft gaps while preventing a change from breaking live links.
    previous = Counter((f.rule_id, f.message) for f in _reference_findings(before))
    for issue in _reference_findings(after):
        key = (issue.rule_id, issue.message)
        if previous[key]:
            previous[key] -= 1
        else:
            raise ProposalError(
                f"Update the dependent records first. {issue.message}",
                code="reference_conflict",
                pointer=issue.json_pointer,
            )


def _project(semantic: SemanticLayer, proposal: ProposalInput, *, reviewer: str | None = None):
    """Build an entirely in-memory candidate; validation precedes every write."""
    candidate = semantic.model_copy(deep=True)
    artifacts = {a.id for a in candidate.artifacts}
    _references(proposal.source_artifact_ids, artifacts, "proposal sources")
    for tool in proposal.tool_calls:
        _references(tool.input_artifact_ids, artifacts, "tool input files")
        _references(tool.output_artifact_ids, artifacts, "tool output files")
    known_actor = next((a for a in candidate.provenance.agents if a.id == proposal.actor.id), None)
    if known_actor and (
        known_actor.agent_type != "software"
        or known_actor.name != proposal.actor.name
        or known_actor.version != proposal.actor.version
        or known_actor.extensions.get("provider") != proposal.actor.provider
        or known_actor.extensions.get("model") != proposal.actor.model
    ):
        raise ProposalError(
            "Use a distinct agent ID for this software, version, and model.", code="actor_conflict"
        )
    diffs = []
    touched = []
    timestamp = utc_now()
    status = "human_accepted" if reviewer else "needs_review"
    for index, change in enumerate(proposal.changes):
        invalid = set(change.fields) - FIELDS[change.record_type]
        if invalid:
            raise ProposalError(
                f"Choose editable {change.record_type} fields: {', '.join(sorted(invalid))}.",
                pointer=f"/changes/{index}/fields",
            )
        existing = _get(candidate, change.record_type, change.record_id)
        if change.record_type == "scene" and existing is None:
            raise ProposalError(
                "Import the figure or native scene before proposing its view settings."
            )
        original = existing.model_dump(mode="json") if existing else None
        data = deepcopy(original) if original else {"id": change.record_id}
        if change.record_type in {"evidence", "uncertainty"}:
            parent = change.claim_id or proposal.claim_id
            if existing and parent and parent not in data["claim_ids"]:
                raise ProposalError(
                    "Choose a claim already linked to this record, or propose a new record for this claim.",
                    code="claim_scope_conflict",
                    pointer=f"/changes/{index}/claim_id",
                )
            if existing is None and parent:
                data["claim_ids"] = [parent]
            if not data.get("claim_ids"):
                raise ProposalError("Link this record to a claim using claim_id.")
        for key, value in change.fields.items():
            before = _field(existing, key)
            if key in {"claim_text", "native_selector"}:
                _nonempty(value, LABELS[key])
                data[key] = ProvenancedString(
                    value=value,
                    source_type="tool_generated",
                    review_status=status,
                    reviewer=reviewer,
                    reviewed_at=timestamp if reviewer else None,
                    source_location=SourceLocation(artifact_id=proposal.source_artifact_ids[0])
                    if proposal.source_artifact_ids
                    else None,
                ).model_dump(mode="json")
            elif key == "accessibility":
                allowed = {
                    "alt_text",
                    "caption",
                    "palette_description",
                    "non_color_encoding",
                    "viewer_fallback",
                }
                if (
                    not isinstance(value, dict)
                    or set(value) - allowed
                    or any(not isinstance(v, str) for v in value.values())
                ):
                    raise ProposalError("Use text fields for the accessible figure description.")
                data.setdefault("extensions", {})[key] = {**(before or {}), **value}
            elif key == "visibility" and isinstance(value, list):
                rows = []
                for row in value:
                    parsed = VisibilityRecord.model_validate(row).model_dump(mode="json")
                    content = {
                        k: v for k, v in parsed.items() if k not in {"source_type", "review_status"}
                    }
                    original_row = next(
                        (
                            r
                            for r in before or []
                            if {
                                k: v
                                for k, v in r.items()
                                if k not in {"source_type", "review_status"}
                            }
                            == content
                        ),
                        None,
                    )
                    rows.append(
                        deepcopy(original_row)
                        if original_row
                        else {
                            **parsed,
                            "source_type": "tool_generated",
                            "review_status": status,
                        }
                    )
                data[key] = rows
            elif isinstance(value, dict) and key in {
                "parameters",
                "thresholds",
                "units",
                "camera",
                "result_summary_structured",
            }:
                merged = dict(data.get(key, {}))
                for name, item in value.items():
                    if item is None:
                        merged.pop(name, None)
                    else:
                        merged[name] = item
                data[key] = merged
            else:
                data[key] = value
            after = value if key in {"claim_text", "native_selector"} else data.get(key)
            if key == "accessibility":
                after = data["extensions"][key]
            diffs.append(
                {
                    "record_type": change.record_type,
                    "record_id": change.record_id,
                    "field": key,
                    "label": LABELS.get(key, key.replace("_", " ").capitalize()),
                    "before": before,
                    "after": after,
                }
            )
        data["review_status"] = status
        data.setdefault("extensions", {})["agent_authorship"] = {
            "proposal_id": proposal.id,
            "actor_id": proposal.actor.id,
            "source_type": "tool_generated",
        }
        if change.record_type == "claim":
            data["claim_status"] = "reviewable" if reviewer else "draft"
            if "claim_text" not in change.fields and data.get("claim_text"):
                data["claim_text"]["review_status"] = status
                data["claim_text"]["reviewer"] = reviewer
                data["claim_text"]["reviewed_at"] = timestamp if reviewer else None
        if change.record_type in {"evidence", "uncertainty"}:
            data["reviewer"] = reviewer
            data["reviewed_at"] = timestamp if reviewer else None
        if change.record_type == "evidence" and existing is None:
            data["generated_by"] = proposal.actor.name
        if (
            change.record_type == "selection"
            and existing is not None
            and data["native_selector"]["value"] != existing.native_selector.value
            and "runtime_verification" in data["extensions"]
        ):
            data["extensions"]["runtime_verification"] = "unverified"
        model = RECORDS[change.record_type][1].model_validate(data)
        collection = getattr(candidate, RECORDS[change.record_type][0])
        if existing is None:
            collection.append(model)
        else:
            collection[collection.index(existing)] = model
        touched.append((change.record_type, change.record_id))
    known = {kind: {r.id for r in getattr(candidate, spec[0])} for kind, spec in RECORDS.items()}
    if proposal.claim_id and proposal.claim_id not in known["claim"]:
        raise ProposalError("Choose a claim in this package or include its proposed record.")
    for kind, identity in list(touched):
        record = _get(candidate, kind, identity)
        if kind == "claim":
            _nonempty(record.claim_text.value, "the figure statement")
            _nonempty(record.figure_ref, "the figure label")
            if not record.scene_ids:
                raise ProposalError("Link the claim to a scene.")
            _references(record.scene_ids, known["scene"], "scenes")
        if kind in {"evidence", "uncertainty"}:
            _references(record.claim_ids, known["claim"], "claims")
            for claim_id in record.claim_ids:
                parent = _get(candidate, "claim", claim_id)
                links = parent.evidence_ids if kind == "evidence" else parent.uncertainty_ids
                if record.id not in links:
                    links.append(record.id)
                    if ("claim", claim_id) not in touched:
                        touched.append(("claim", claim_id))
        if kind in {"evidence", "entity"}:
            _references(record.source_artifact_ids, artifacts, "source files")
        if kind == "evidence":
            _nonempty(record.method_name, "how this was checked")
            _nonempty(record.result_summary, "what was found")
            if not record.source_artifact_ids:
                raise ProposalError("Link evidence to a source file.")
            _references(record.target_selection_ids, known["selection"], "regions")
            _references(record.target_entity_ids, known["entity"], "molecules and residues")
            from claimtrace.gui.audit import _distance_gaps

            gaps = (
                _distance_gaps(record.model_dump(mode="json"))
                if record.evidence_kind.value in {"contact_table", "measurement"}
                else set()
            )
            if gaps:
                index = next(
                    i
                    for i, c in enumerate(proposal.changes)
                    if c.record_type == kind and c.record_id == identity
                )
                field = (
                    "units/distance"
                    if gaps == {"units"}
                    else (
                        "parameters/measured_distance"
                        if "measured distance" in gaps
                        else "thresholds/distance"
                    )
                )
                actions = {
                    "measured distance": "Set parameters.measured_distance to the observed positive distance",
                    "cutoff": "Set thresholds.distance to the positive contact cutoff",
                    "units": "Set units.distance to the source unit, e.g. angstrom",
                }
                raise ProposalError(
                    ". ".join(actions[gap] for gap in sorted(gaps)) + ".",
                    code="missing_distance_context",
                    pointer=f"/changes/{index}/fields/{field}",
                )
        if kind == "uncertainty":
            _nonempty(record.statement, "the limitation")
        if kind in {"selection", "scene"}:
            _references(record.entity_ids, known["entity"], "molecules and residues")
        if kind == "selection":
            _nonempty(record.native_selector.value, "the region selection")
        if kind == "scene":
            _references(record.selection_ids, known["selection"], "regions")
    # Force JSON finiteness for free-form maps as well as typed model fields.
    ensure_finite(candidate.model_dump(mode="python"))
    _check_new_reference_errors(semantic, candidate)
    snapshots = []
    for kind, identity in touched:
        before, after = _get(semantic, kind, identity), _get(candidate, kind, identity)
        snapshots.append(
            {
                "record_type": kind,
                "record_id": identity,
                "before": before.model_dump(mode="json") if before else None,
                "after": after.model_dump(mode="json"),
            }
        )
    return candidate, diffs, snapshots


def check_proposal(package: ClaimTracePackage, data: dict[str, Any]) -> dict[str, Any]:
    ensure_finite(data)
    proposal = ProposalInput.model_validate(data)
    prior = next(
        (p for p in stored_proposals(package.semantic_layer) if p["id"] == proposal.id), None
    )
    if prior:
        if prior["input"] != proposal.model_dump(mode="json"):
            raise ProposalError(
                "This proposal ID already has different contents. Use a new ID.",
                code="proposal_conflict",
            )
        if prior["status"] == "pending":
            _unchanged(package.semantic_layer, prior["base_records"], "before")
        return prior
    _, diff, snapshots = _project(package.semantic_layer, proposal)
    return {
        **proposal.model_dump(mode="json"),
        "status": "pending",
        "created_at": utc_now(),
        "input": proposal.model_dump(mode="json"),
        "diff": diff,
        "base_records": [{k: v for k, v in s.items() if k != "after"} for s in snapshots],
        "review": None,
    }


def _save(package: ClaimTracePackage, semantic: SemanticLayer) -> None:
    from claimtrace.constants import EXPORT_MARKER_FILENAME
    from claimtrace.api import load_package

    if (package.root / EXPORT_MARKER_FILENAME).exists() or (
        package.root / "checksums/sha256.txt"
    ).exists():
        raise ProposalError(
            "Use claimtrace agent propose or review to create a working copy of this received export.",
            code="read_only_export",
        )
    current = load_package(package.root).semantic_layer
    if current.model_dump(mode="json") != package.semantic_layer.model_dump(mode="json"):
        raise ProposalError(
            "Reload the package before saving this proposal; its saved records have changed.",
            code="stale_package",
            pointer="/semantic_layer.json",
        )
    synchronize_resource_bindings(semantic)
    content = (
        json.dumps(semantic.model_dump(mode="json", exclude_none=True), indent=2, allow_nan=False)
        + "\n"
    )
    # One atomic manifest replacement records the proposal, records and provenance together.
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=package.root,
            prefix=".proposal-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, package.root / "semantic_layer.json")
        package.semantic_layer = semantic
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def create_proposal(package: ClaimTracePackage, data: dict[str, Any]) -> dict[str, Any]:
    record = check_proposal(package, data)
    semantic = package.semantic_layer.model_copy(deep=True)
    proposals = stored_proposals(semantic)
    if any(p["id"] == record["id"] for p in proposals):
        return record
    actor = Actor.model_validate(record["actor"])
    if not any(a.id == actor.id for a in semantic.provenance.agents):
        semantic.provenance.agents.append(
            Agent(
                id=actor.id,
                name=actor.name,
                version=actor.version,
                agent_type="software",
                extensions={
                    k: v
                    for k, v in {"provider": actor.provider, "model": actor.model}.items()
                    if v is not None
                },
            )
        )
    activity = semantic.add_activity(
        "agent_proposal",
        record["rationale"],
        agent_id=actor.id,
        used_artifact_ids=record["source_artifact_ids"],
        generated_ids=[record["id"]],
        tool_calls=record["tool_calls"],
    )
    record["activity_id"] = activity.id
    proposals.append(record)
    semantic.extensions[EXTENSION] = proposals
    _save(package, semantic)
    return record


def _unchanged(semantic: SemanticLayer, snapshots: list[dict], side: str) -> None:
    for snapshot in snapshots:
        current = _get(semantic, snapshot["record_type"], snapshot["record_id"])
        value = current.model_dump(mode="json") if current else None
        if value != snapshot[side]:
            collection_name = RECORDS[snapshot["record_type"]][0]
            collection = getattr(semantic, collection_name)
            pointer = f"/{collection_name}"
            if current is not None:
                pointer += f"/{collection.index(current)}"
            raise ProposalError(
                f"This {snapshot['record_type']} has changed. Review the current record and create a fresh proposal.",
                code="record_conflict",
                pointer=pointer,
            )


def review_proposal(
    package: ClaimTracePackage,
    identity: str,
    *,
    decision: str,
    reviewer: str,
    note: str = "",
    changes: list[dict] | None = None,
) -> dict[str, Any]:
    _nonempty(reviewer, "the reviewer's name")
    if decision not in {"accept", "reject", "revert"}:
        raise ProposalError("Choose accept, reject or revert.")
    semantic = package.semantic_layer.model_copy(deep=True)
    proposals = stored_proposals(semantic)
    record = next((p for p in proposals if p["id"] == identity), None)
    if record is None:
        raise ProposalError("Choose an existing proposal ID.")
    expected = "accepted" if decision == "revert" else "pending"
    if record["status"] != expected:
        raise ProposalError(
            f"This proposal is {record['status']}. Choose a {expected} proposal.",
            code="review_conflict",
        )
    if decision == "accept":
        _unchanged(semantic, record["base_records"], "before")
        data = deepcopy(record["input"])
        if changes is not None:

            def shape(items):
                return [
                    (c["record_type"], c["record_id"], c.get("claim_id"), set(c["fields"]))
                    for c in items
                ]

            if shape(changes) != shape(data["changes"]):
                raise ProposalError(
                    "Edit values within the proposed fields. Keep the same records and field names."
                )
            data["changes"] = changes
        proposal = ProposalInput.model_validate(data)
        semantic, diff, snapshots = _project(semantic, proposal, reviewer=reviewer)
        record["applied_records"] = snapshots
        record["accepted_diff"] = diff
        record["accepted_changes"] = data["changes"]
    elif decision == "revert":
        _unchanged(semantic, record["applied_records"], "after")
        for snapshot in record["applied_records"]:
            kind, rid = snapshot["record_type"], snapshot["record_id"]
            collection = getattr(semantic, RECORDS[kind][0])
            current = _get(semantic, kind, rid)
            if snapshot["before"] is None:
                collection.remove(current)
            else:
                collection[collection.index(current)] = RECORDS[kind][1].model_validate(
                    snapshot["before"]
                )
        _check_new_reference_errors(package.semantic_layer, semantic)
    person_id = f"person:{reviewer.strip()}"
    person = next((a for a in semantic.provenance.agents if a.id == person_id), None)
    if person and person.agent_type != "person":
        raise ProposalError("Choose a reviewer name distinct from the software agent.")
    if person is None:
        semantic.provenance.agents.append(
            Agent(id=person_id, name=reviewer.strip(), agent_type="person")
        )
    review = {
        "decision": decision,
        "reviewer": reviewer.strip(),
        "reviewed_at": utc_now(),
        "note": note,
    }
    record.setdefault("review_history", []).append(review)
    record["review"] = review
    record["status"] = {"accept": "accepted", "reject": "rejected", "revert": "reverted"}[decision]
    semantic.add_activity(
        f"proposal_{decision}",
        note or f"{decision.capitalize()} proposal {identity}.",
        agent_id=person_id,
        used_artifact_ids=record["source_artifact_ids"],
        generated_ids=[c["record_id"] for c in record["changes"]] if decision == "accept" else [],
        proposal_id=identity,
        proposal_actor_id=record["actor"]["id"],
    )
    semantic.extensions[EXTENSION] = proposals
    _save(package, semantic)
    return record
