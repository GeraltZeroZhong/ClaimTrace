"""Directory inventory importer."""

from __future__ import annotations

from pathlib import Path

from claimtrace.importers.base import ExtractedFact, ImportResult
from claimtrace.models import CompletionTask, SemanticLayer


class DirectoryImporter:
    name = "directory"
    stability = "stable"

    def detect(self, path: Path) -> float:
        return 0.8 if path.is_dir() else 0.0

    def import_into(self, path: Path, artifact_id: str, semantic: SemanticLayer) -> ImportResult:
        children = sorted(child.name for child in path.iterdir())
        fact = ExtractedFact(
            fact_id="fact-directory-inventory-0001",
            tool="directory",
            artifact_id=artifact_id,
            source_location={"artifact_id": artifact_id, "path": path.name},
            native_command="inventory directory",
            native_value={"children": children},
            normalized_target={"object_type": "artifact.directory_inventory", "json_pointer": ""},
            normalized_value={"children": children},
            support_status="supported_exact",
            confidence={"level": "exact", "score": 1.0, "basis": ["filesystem_inventory"]},
            review_status="auto_extracted",
        )
        task = CompletionTask(
            id="task:directory-roles",
            section="data provenance",
            question="Which files in this directory are structure, evidence, render or native artifacts?",
            target_json_pointer="/artifacts",
            field_use="Directory grouping is observable, but scientific artifact roles require confirmation.",
            examples=["model.cif: structure", "contacts.csv: contact_table"],
            accepted_values=["role mapping", "unknown"],
            blocking=False,
        )
        return ImportResult(importer_name=self.name, facts=[fact], tasks=[task])
