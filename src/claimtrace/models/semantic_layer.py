"""Claim Accountability Layer data model."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from claimtrace.constants import CAL_SCHEMA_VERSION, PACKAGE_VERSION


def utc_now() -> str:
    """Return an RFC 3339 UTC timestamp."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ReviewStatus(str, Enum):
    auto_extracted = "auto_extracted"
    needs_review = "needs_review"
    confirmed = "confirmed"
    human_accepted = "human_accepted"
    rejected = "rejected"
    superseded = "superseded"


class SourceType(str, Enum):
    native_file = "native_file"
    artifact_metadata = "artifact_metadata"
    computed_by_tool = "computed_by_tool"
    user_asserted = "user_asserted"
    external_evidence = "external_evidence"
    tool_generated = "tool_generated"
    unknown = "unknown"


class ConfidenceValue(str, Enum):
    exact = "exact"
    high = "high"
    medium = "medium"
    low = "low"
    heuristic = "heuristic"
    unknown = "unknown"


class SupportStatus(str, Enum):
    supported_deep = "supported_deep"
    supported_shallow = "supported_shallow"
    supported_heuristic = "supported_heuristic"
    supported_compat = "supported_compat"
    raw_unsupported = "raw_unsupported"
    unsupported = "unsupported"


class MeaningStatus(str, Enum):
    native_observed = "native_observed"
    tool_suggested_meaning = "tool_suggested_meaning"
    requires_user_completion = "requires_user_completion"
    user_declared_no_scientific_meaning = "user_declared_no_scientific_meaning"
    user_confirmed_meaning = "user_confirmed_meaning"
    unresolved_claim_critical = "unresolved_claim_critical"


class TargetResolutionStatus(str, Enum):
    expression_only = "expression_only"
    resolved_against_artifact = "resolved_against_artifact"
    unresolved = "unresolved"
    not_checked = "not_checked"


class ClaimCriticalStatus(str, Enum):
    true = "true"
    false = "false"
    unknown = "unknown"


class ArtifactKind(str, Enum):
    local_attached = "local_attached"
    local_detached = "local_detached"
    remote = "remote"


class ArtifactRole(str, Enum):
    native_script = "native_script"
    native_session = "native_session"
    chimerax_script = "chimerax_script"
    molviewspec = "molviewspec"
    render_image = "render_image"
    structure = "structure"
    map = "map"
    trajectory = "trajectory"
    topology = "topology"
    contact_table = "contact_table"
    validation_report = "validation_report"
    evidence_document = "evidence_document"
    directory = "directory"
    generic = "generic"
    package_metadata = "package_metadata"


class ClaimType(str, Enum):
    simple_structure_view = "simple_structure_view"
    selection_highlight = "selection_highlight"
    ligand_binding_pose = "ligand_binding_pose"
    cryo_em_map_fit = "cryo_em_map_fit"
    xray_density_support = "xray_density_support"
    trajectory_mechanism = "trajectory_mechanism"
    model_comparison = "model_comparison"
    computed_model_claim = "computed_model_claim"
    unknown = "unknown"


class EvidenceKind(str, Enum):
    measurement = "measurement"
    external_validation = "external_validation"
    density_support = "density_support"
    map_fit_metric = "map_fit_metric"
    contact_table = "contact_table"
    trajectory_analysis = "trajectory_analysis"
    manual_rationale = "manual_rationale"
    negative_control = "negative_control"
    waiver = "waiver"
    native_observation = "native_observation"


class SourceLocation(StrictModel):
    artifact_id: str | None = None
    line: int | None = None
    column: int | None = None
    json_pointer: str | None = None
    path: str | None = None
    url: str | None = None


class ExtractionConfidence(StrictModel):
    level: ConfidenceValue = ConfidenceValue.unknown
    score: float | None = None
    basis: list[str] = Field(default_factory=list)


class ProvenancedString(StrictModel):
    value: str
    source_type: SourceType = SourceType.user_asserted
    source_location: SourceLocation | None = None
    confidence: ConfidenceValue = ConfidenceValue.unknown
    review_status: ReviewStatus = ReviewStatus.needs_review
    reviewer: str | None = None
    reviewed_at: str | None = None


class ProvenancedNumber(StrictModel):
    value: float
    source_type: SourceType = SourceType.user_asserted
    source_location: SourceLocation | None = None
    confidence: ConfidenceValue = ConfidenceValue.unknown
    review_status: ReviewStatus = ReviewStatus.needs_review
    reviewer: str | None = None
    reviewed_at: str | None = None


class ProvenancedList(StrictModel):
    value: list[str] = Field(default_factory=list)
    source_type: SourceType = SourceType.user_asserted
    source_location: SourceLocation | None = None
    confidence: ConfidenceValue = ConfidenceValue.unknown
    review_status: ReviewStatus = ReviewStatus.needs_review
    reviewer: str | None = None
    reviewed_at: str | None = None


class PackageMetadata(StrictModel):
    package_id: str
    title: str = "Untitled ClaimTrace package"
    creator: str = "unknown"
    license: str = "unknown"
    created_at: str = Field(default_factory=utc_now)
    profile: str = "draft"
    cal_schema_version: str = CAL_SCHEMA_VERSION
    description: str | None = None
    extensions: dict[str, Any] = Field(default_factory=dict)


class Artifact(StrictModel):
    id: str
    kind: ArtifactKind = ArtifactKind.local_attached
    role: ArtifactRole = ArtifactRole.generic
    path: str | None = None
    url: str | None = None
    format: str = "application/octet-stream"
    media_type: str | None = None
    sha256: str | None = None
    byte_size: int | None = None
    included: bool = True
    detached_reason: str | None = None
    source_type: SourceType = SourceType.artifact_metadata
    review_status: ReviewStatus = ReviewStatus.auto_extracted
    created_at: str = Field(default_factory=utc_now)
    accessed_at: str | None = None
    fixity_status: str = "available"
    extensions: dict[str, Any] = Field(default_factory=dict)


class Claim(StrictModel):
    id: str
    claim_text: ProvenancedString
    claim_type: ClaimType = ClaimType.unknown
    figure_ref: str = "unknown"
    scope: str = "unknown"
    scene_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    uncertainty_ids: list[str] = Field(default_factory=list)
    claim_status: str = "needs_review"
    review_status: ReviewStatus = ReviewStatus.needs_review
    extensions: dict[str, Any] = Field(default_factory=dict)


class Entity(StrictModel):
    id: str
    entity_type: str = "unknown"
    label: str = "unknown"
    stable_identity: str = "unknown"
    source_artifact_ids: list[str] = Field(default_factory=list)
    claim_critical: bool = False
    review_status: ReviewStatus = ReviewStatus.needs_review
    extensions: dict[str, Any] = Field(default_factory=dict)


class Selection(StrictModel):
    id: str
    name: str
    native_selector: ProvenancedString
    entity_ids: list[str] = Field(default_factory=list)
    source_artifact_id: str | None = None
    claim_critical: bool = False
    review_status: ReviewStatus = ReviewStatus.needs_review
    extensions: dict[str, Any] = Field(default_factory=dict)


class VisibilityRecord(StrictModel):
    entity_id: str | None = None
    selection_id: str | None = None
    native_target: str | None = None
    state: Literal["visible", "hidden", "simplified", "excluded", "unknown"] = "unknown"
    reason: str | None = None
    source_type: SourceType = SourceType.native_file
    review_status: ReviewStatus = ReviewStatus.needs_review


class ObservedSceneOperation(StrictModel):
    operation_id: str
    operation: str
    target: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    auto_annotation: str | None = None
    candidate_meaning: str | None = None
    meaning_confidence: ConfidenceValue = ConfidenceValue.unknown
    meaning_basis: list[str] = Field(default_factory=list)
    needs_author_confirmation: bool = False
    source_location: SourceLocation = Field(default_factory=SourceLocation)
    native_command: str | None = None
    native_value: dict[str, Any] = Field(default_factory=dict)
    support_status: SupportStatus = SupportStatus.supported_shallow
    extraction_confidence: ExtractionConfidence = Field(default_factory=ExtractionConfidence)
    review_status: ReviewStatus = ReviewStatus.auto_extracted
    meaning_status: MeaningStatus = MeaningStatus.native_observed
    target_resolution_status: TargetResolutionStatus = TargetResolutionStatus.expression_only
    claim_critical: ClaimCriticalStatus = ClaimCriticalStatus.unknown


class NativeReference(StrictModel):
    native_ref_id: str
    source_location: SourceLocation = Field(default_factory=SourceLocation)
    native_expression: str
    ref_type: str
    stable_identity: str | None = None
    identity_status: Literal["resolved", "unresolved", "not_applicable"] = "unresolved"
    claim_critical: ClaimCriticalStatus = ClaimCriticalStatus.unknown
    review_status: ReviewStatus = ReviewStatus.needs_review
    target_resolution_status: TargetResolutionStatus = TargetResolutionStatus.expression_only


class RawNativeObservation(StrictModel):
    raw_id: str
    artifact_id: str
    source_location: SourceLocation = Field(default_factory=SourceLocation)
    native_text: str
    reason: str
    support_status: SupportStatus = SupportStatus.raw_unsupported
    extraction_confidence: ExtractionConfidence = Field(default_factory=ExtractionConfidence)
    may_affect_scene_id: str | None = None
    resolution: Literal[
        "unknown",
        "no_scene_effect",
        "reviewed_no_claim_impact",
        "converted_to_evidence",
        "waived",
        "not_applicable",
    ] = "unknown"
    claim_critical: ClaimCriticalStatus = ClaimCriticalStatus.unknown
    review_status: ReviewStatus = ReviewStatus.needs_review


class ResourceReference(StrictModel):
    resource_ref_id: str
    artifact_id: str | None = None
    uri: str
    uri_kind: Literal[
        "local",
        "relative",
        "remote",
        "archive_member",
        "missing_archive_member",
        "file",
        "data",
        "unknown",
    ] = "unknown"
    base_uri: str | None = None
    mvsx_member_id: str | None = None
    fetch_status: Literal["not_fetched", "fetched", "unresolved", "not_applicable"] = "not_fetched"
    fixity_status: str = "unknown"
    claim_critical: ClaimCriticalStatus = ClaimCriticalStatus.unknown
    source_location: SourceLocation = Field(default_factory=SourceLocation)


class MVSXMember(StrictModel):
    member_id: str
    original_name: str
    normalized_name: str
    is_dir: bool = False
    sha256: str | None = None
    crc32: str | None = None
    byte_size: int | None = None
    compressed_size: int | None = None
    compression_method: str = "unknown"
    external_attr: int | None = None
    media_type: str | None = None
    referenced_by_json_pointers: list[str] = Field(default_factory=list)
    referenced: bool = False


class MVSXInventory(StrictModel):
    artifact_id: str
    scene_entry: str | None = None
    format_status: Literal["standard", "nonstandard_single_mvsj"] = "standard"
    members: list[MVSXMember] = Field(default_factory=list)


class VisualEncodingSemantics(StrictModel):
    operation_ids: list[str] = Field(default_factory=list)
    encoding_type: str
    meaning_status: MeaningStatus = MeaningStatus.requires_user_completion
    meaning: str | None = None
    auto_annotation: str | None = None
    candidate_meaning: str | None = None
    meaning_confidence: ConfidenceValue = ConfidenceValue.unknown
    meaning_basis: list[str] = Field(default_factory=list)
    needs_author_confirmation: bool = False
    no_scientific_meaning_reason: str | None = None
    reviewer: str | None = None
    reviewed_at: str | None = None


class EvidenceBinding(StrictModel):
    binding_id: str
    claim_id: str | None = None
    operation_ids: list[str] = Field(default_factory=list)
    resource_ref_ids: list[str] = Field(default_factory=list)
    evidence_artifact_ids: list[str] = Field(default_factory=list)
    evidence_type: str
    method_context: dict[str, Any] = Field(default_factory=dict)
    support_status: str = "unresolved"


class Scene(StrictModel):
    id: str
    description: str = "Draft scene from native artifacts"
    native_artifact_ids: list[str] = Field(default_factory=list)
    render_artifact_ids: list[str] = Field(default_factory=list)
    selection_ids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    representations: list[dict[str, Any]] = Field(default_factory=list)
    visibility: list[VisibilityRecord] = Field(default_factory=list)
    camera: dict[str, Any] = Field(default_factory=dict)
    parse_confidence: ConfidenceValue = ConfidenceValue.unknown
    review_status: ReviewStatus = ReviewStatus.needs_review
    extensions: dict[str, Any] = Field(default_factory=dict)


class Evidence(StrictModel):
    id: str
    evidence_kind: EvidenceKind = EvidenceKind.manual_rationale
    claim_ids: list[str] = Field(default_factory=list)
    source_artifact_ids: list[str] = Field(default_factory=list)
    target_entity_ids: list[str] = Field(default_factory=list)
    target_selection_ids: list[str] = Field(default_factory=list)
    generated_by: str = "unknown"
    method_name: str = "unknown"
    method_version: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    thresholds: dict[str, Any] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    result_summary: str = "unknown"
    result_summary_structured: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    alternative_explanations: list[str] = Field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.needs_review
    reviewer: str | None = None
    reviewed_at: str | None = None
    provenance_id: str | None = None
    fixity_status: str = "unknown"
    extensions: dict[str, Any] = Field(default_factory=dict)


class Uncertainty(StrictModel):
    id: str
    claim_ids: list[str] = Field(default_factory=list)
    category: str = "general"
    statement: str = "unknown"
    alternative_explanations: list[str] = Field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.needs_review
    reviewer: str | None = None
    reviewed_at: str | None = None
    extensions: dict[str, Any] = Field(default_factory=dict)


class SoftwareEnvironment(StrictModel):
    id: str
    name: str
    version: str = "unknown"
    role: str = "viewer"
    command: str | None = None
    extensions: dict[str, Any] = Field(default_factory=dict)


class Agent(StrictModel):
    id: str
    name: str
    agent_type: Literal["person", "software", "organization", "unknown"] = "unknown"
    version: str | None = None
    extensions: dict[str, Any] = Field(default_factory=dict)


class Activity(StrictModel):
    id: str
    activity_type: str
    started_at: str = Field(default_factory=utc_now)
    ended_at: str | None = None
    agent_id: str | None = None
    used_artifact_ids: list[str] = Field(default_factory=list)
    generated_ids: list[str] = Field(default_factory=list)
    description: str = ""
    extensions: dict[str, Any] = Field(default_factory=dict)


class Waiver(StrictModel):
    rule_id: str
    scope: str
    reason: str
    reviewer: str
    anchor_id: str | None = None
    timestamp: str = Field(default_factory=utc_now)
    reviewed_at: str | None = None
    max_export_mode: Literal["draft", "internal", "share", "archive"] = "draft"


class Provenance(StrictModel):
    agents: list[Agent] = Field(default_factory=list)
    activities: list[Activity] = Field(default_factory=list)
    waivers: list[Waiver] = Field(default_factory=list)
    extensions: dict[str, Any] = Field(default_factory=dict)


class Reuse(StrictModel):
    license: str = "unknown"
    citation: str | None = None
    restrictions: list[str] = Field(default_factory=list)
    reviewer: str | None = None
    reviewed_at: str | None = None
    extensions: dict[str, Any] = Field(default_factory=dict)


class CompletionTask(StrictModel):
    id: str
    section: str
    question: str
    target_json_pointer: str
    required_for_modes: list[str] = Field(default_factory=lambda: ["share", "archive"])
    status: Literal["open", "answered", "waived"] = "open"
    field_use: str = ""
    examples: list[str] = Field(default_factory=list)
    accepted_values: list[str] = Field(default_factory=list)
    blocking: bool = True
    created_at: str = Field(default_factory=utc_now)
    extensions: dict[str, Any] = Field(default_factory=dict)


class SemanticLayer(StrictModel):
    schema_version: str = CAL_SCHEMA_VERSION
    semantic_layer_id: str
    package: PackageMetadata
    claims: list[Claim] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    selections: list[Selection] = Field(default_factory=list)
    scenes: list[Scene] = Field(default_factory=list)
    observed_scene_operations: list[ObservedSceneOperation] = Field(default_factory=list)
    native_references: list[NativeReference] = Field(default_factory=list)
    raw_native_observations: list[RawNativeObservation] = Field(default_factory=list)
    resource_references: list[ResourceReference] = Field(default_factory=list)
    mvsx_inventories: list[MVSXInventory] = Field(default_factory=list)
    visual_encoding_semantics: list[VisualEncodingSemantics] = Field(default_factory=list)
    evidence_bindings: list[EvidenceBinding] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    uncertainty: list[Uncertainty] = Field(default_factory=list)
    software_environment: list[SoftwareEnvironment] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)
    reuse: Reuse = Field(default_factory=Reuse)
    last_validation: dict[str, Any] = Field(default_factory=dict)
    extensions: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def new(cls, package_id: str, title: str = "Untitled ClaimTrace package") -> "SemanticLayer":
        return cls(
            semantic_layer_id=f"claimtrace:cal:{package_id}",
            package=PackageMetadata(package_id=package_id, title=title),
            provenance=Provenance(
                agents=[
                    Agent(
                        id="agent:claimtrace",
                        name="ClaimTrace",
                        agent_type="software",
                        version=PACKAGE_VERSION,
                    )
                ],
                activities=[
                    Activity(
                        id="activity:init",
                        activity_type="package_initialization",
                        agent_id="agent:claimtrace",
                        description="Initialized ClaimTrace package.",
                    )
                ],
            ),
        )

    def add_activity(self, activity_type: str, description: str, **extra: Any) -> Activity:
        agent_id = str(extra.pop("agent_id", "agent:claimtrace"))
        used_artifact_ids = [str(value) for value in extra.pop("used_artifact_ids", [])]
        generated_ids = [str(value) for value in extra.pop("generated_ids", [])]
        activity = Activity(
            id=f"activity:{activity_type}:{len(self.provenance.activities) + 1}",
            activity_type=activity_type,
            agent_id=agent_id,
            used_artifact_ids=used_artifact_ids,
            generated_ids=generated_ids,
            description=description,
            extensions=extra,
        )
        self.provenance.activities.append(activity)
        return activity
