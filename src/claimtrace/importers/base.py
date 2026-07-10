"""Importer plugin interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from claimtrace.models import CompletionTask, SemanticLayer


@dataclass
class ExtractedFact:
    fact_id: str
    tool: str
    artifact_id: str
    source_location: dict[str, Any]
    native_command: str
    native_value: dict[str, Any]
    normalized_target: dict[str, Any]
    normalized_value: dict[str, Any]
    support_status: str
    confidence: dict[str, Any]
    review_status: str = "needs_review"

    def as_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "tool": self.tool,
            "artifact_id": self.artifact_id,
            "source_location": self.source_location,
            "native_command": self.native_command,
            "native_value": self.native_value,
            "normalized_target": self.normalized_target,
            "normalized_value": self.normalized_value,
            "support_status": self.support_status,
            "confidence": self.confidence,
            "extraction_confidence": self.confidence,
            "review_status": self.review_status,
        }


@dataclass
class ImportResult:
    importer_name: str
    facts: list[ExtractedFact] = field(default_factory=list)
    tasks: list[CompletionTask] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def fact_dicts(self) -> list[dict[str, Any]]:
        return [fact.as_dict() for fact in self.facts]


class NativeImporterPlugin(Protocol):
    name: str
    stability: str

    def detect(self, path: Path) -> float:
        ...

    def import_into(self, path: Path, artifact_id: str, semantic: SemanticLayer) -> ImportResult:
        ...


def detect_importer(path: Path, importers: list[NativeImporterPlugin]) -> NativeImporterPlugin:
    scored = sorted(((plugin.detect(path), plugin) for plugin in importers), key=lambda item: item[0])
    score, plugin = scored[-1]
    if score <= 0:
        from claimtrace.importers.generic import GenericImporter

        return GenericImporter()
    return plugin


def default_importers(include_experimental: bool = True) -> list[NativeImporterPlugin]:
    from claimtrace.importers.chimerax import ChimeraXImporter
    from claimtrace.importers.directory import DirectoryImporter
    from claimtrace.importers.generic import GenericImporter
    from claimtrace.importers.image import ImageImporter
    from claimtrace.importers.molviewspec import MolViewSpecImporter
    from claimtrace.importers.pymol import PyMOLImporter

    importers: list[NativeImporterPlugin] = [
        ChimeraXImporter(),
        MolViewSpecImporter(),
        PyMOLImporter(),
        ImageImporter(),
        DirectoryImporter(),
        GenericImporter(),
    ]
    if include_experimental:
        from claimtrace.importers.experimental.chimerax import ChimeraXImporter as ExperimentalChimeraXImporter
        from claimtrace.importers.experimental.molviewspec import MolViewSpecImporter as ExperimentalMolViewSpecImporter

        importers.extend([ExperimentalChimeraXImporter(), ExperimentalMolViewSpecImporter()])
    return importers
