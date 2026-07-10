"""Opaque artifact importer."""

from __future__ import annotations

from pathlib import Path

from claimtrace.importers.base import ExtractedFact, ImportResult
from claimtrace.models import CompletionTask, SemanticLayer


class GenericImporter:
    name = "generic"
    stability = "stable"

    def detect(self, path: Path) -> float:
        return 0.1 if path.exists() else 0.0

    def import_into(self, path: Path, artifact_id: str, semantic: SemanticLayer) -> ImportResult:
        fact = ExtractedFact(
            fact_id="fact-generic-artifact-0001",
            tool="generic",
            artifact_id=artifact_id,
            source_location={"artifact_id": artifact_id, "path": path.name},
            native_command="register opaque artifact",
            native_value={"path": path.name, "suffix": path.suffix},
            normalized_target={"object_type": "artifact.opaque", "json_pointer": ""},
            normalized_value={"artifact_id": artifact_id},
            support_status="supported_exact",
            confidence={"level": "exact", "score": 1.0, "basis": ["artifact_registered"]},
            review_status="auto_extracted",
        )
        task = CompletionTask(
            id=f"task:generic-artifact:{artifact_id.replace(':', '-')}",
            section="data provenance",
            question="What role does this artifact play in the claim package?",
            target_json_pointer="/artifacts",
            field_use="Opaque files are registered for fixity; their scientific role needs author confirmation.",
            examples=["validation report", "contact evidence", "unknown"],
            accepted_values=["artifact role", "unknown", "not_applicable"],
            blocking=False,
        )
        return ImportResult(importer_name=self.name, facts=[fact], tasks=[task])
