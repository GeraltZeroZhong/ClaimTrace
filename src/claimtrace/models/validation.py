"""Validation report models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from claimtrace.constants import PACKAGE_VERSION, VALIDATION_REPORT_SCHEMA_VERSION
from claimtrace.models.semantic_layer import utc_now


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


Severity = Literal["ERROR", "WARNING", "INFO"]
FindingStatus = Literal["PASS", "FAIL", "WAIVED", "NOT_APPLICABLE"]


class ValidationFinding(StrictModel):
    rule_id: str
    gate: str
    validation_level: str
    severity: Severity
    finding_class: str
    status: FindingStatus
    message: str
    json_pointer: str = ""
    blocks_modes: list[str] = Field(default_factory=list)
    claim_critical: bool = False
    waivable: bool = False
    suggested_fix: str = ""
    waiver_id: str | None = None
    extensions: dict[str, object] = Field(default_factory=dict)


class SemanticLayerRef(StrictModel):
    path: str = "semantic_layer.json"
    sha256: str
    schema_version: str


class ValidationReport(StrictModel):
    report_schema_version: str = VALIDATION_REPORT_SCHEMA_VERSION
    package_id: str
    semantic_layer_ref: SemanticLayerRef
    validated_at: str = Field(default_factory=utc_now)
    validator_version: str = PACKAGE_VERSION
    export_mode: str = "draft"
    overall_status: Literal["pass", "pass_with_warnings", "fail", "needs_review"] = "needs_review"
    scope_statement: str = (
        "This report checks package completeness, consistency, and share readiness. "
        "Scientific support is supplied by the attached evidence files and notes."
    )
    validation_levels: list[dict[str, object]] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    findings: list[ValidationFinding] = Field(default_factory=list)
    claim_traceability_matrix: list[dict[str, object]] = Field(default_factory=list)
    artifact_fixity: list[dict[str, object]] = Field(default_factory=list)
    entity_evidence_matrix: list[dict[str, object]] = Field(default_factory=list)
    unresolved_list: list[dict[str, object]] = Field(default_factory=list)
    native_inference_limits: list[str] = Field(default_factory=list)
    evidence_minimums_by_profile: list[dict[str, object]] = Field(default_factory=list)
    human_review_required: list[dict[str, object]] = Field(default_factory=list)
    visual_context_audit: list[dict[str, object]] = Field(default_factory=list)
    waiver_list: list[dict[str, object]] = Field(default_factory=list)
    revalidation: dict[str, object] = Field(default_factory=dict)
