"""Experimental static ChimeraX command importer."""

from __future__ import annotations

from pathlib import Path

from claimtrace.importers.base import ExtractedFact, ImportResult
from claimtrace.models import CompletionTask, SemanticLayer


class ChimeraXImporter:
    name = "chimerax"
    stability = "experimental"

    def detect(self, path: Path) -> float:
        return 0.95 if path.suffix.lower() == ".cxc" else 0.0

    def import_into(self, path: Path, artifact_id: str, semantic: SemanticLayer) -> ImportResult:
        facts: list[ExtractedFact] = []
        tasks: list[CompletionTask] = []
        for line_no, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            command = line.split(None, 1)[0].lower()
            support = "raw_unsupported" if command in {"runscript", "alias", "foreachfile"} else "supported_heuristic"
            confidence = "low" if support == "raw_unsupported" else "medium"
            facts.append(
                ExtractedFact(
                    fact_id=f"fact-chimerax-{line_no:04d}",
                    tool="chimerax",
                    artifact_id=artifact_id,
                    source_location={"artifact_id": artifact_id, "line": line_no, "column": 1},
                    native_command=line,
                    native_value={"command": command, "raw": line},
                    normalized_target={"object_type": f"chimerax.{command}", "json_pointer": ""},
                    normalized_value={"experimental": True},
                    support_status=support,
                    confidence={
                        "level": confidence,
                        "score": 0.4 if confidence == "medium" else 0.2,
                        "basis": ["experimental_shallow_parse"],
                    },
                    review_status="needs_review",
                )
            )
        tasks.append(
            CompletionTask(
                id="task:experimental-chimerax-review",
                section="scene",
                question="Confirm ChimeraX experimental import results against the original command file.",
                target_json_pointer="/scenes",
                field_use="ChimeraX importer is experimental and does not reconstruct full viewer state.",
                examples=["confirmed", "unknown", "not_applicable"],
                accepted_values=["confirmed", "unknown", "not_applicable"],
                blocking=False,
            )
        )
        return ImportResult(
            importer_name=self.name,
            facts=facts,
            tasks=tasks,
            warnings=["ChimeraX import is experimental and requires human review."],
        )
