"""Experimental MolViewSpec importer with safe MVSX reading."""

from __future__ import annotations

from pathlib import Path

from claimtrace.importers.base import ExtractedFact, ImportResult
from claimtrace.models import CompletionTask, SemanticLayer
from claimtrace.importers.molviewspec import read_mvs


class MolViewSpecImporter:
    name = "molviewspec"
    stability = "experimental"

    def detect(self, path: Path) -> float:
        return 0.96 if path.suffix.lower() in {".mvsj", ".mvsx"} else 0.0

    def import_into(self, path: Path, artifact_id: str, semantic: SemanticLayer) -> ImportResult:
        tree = _read_mvs(path)
        facts: list[ExtractedFact] = []
        for index, node in enumerate(_walk_tree(tree)):
            kind = str(node.get("kind", node.get("type", "unknown")))
            facts.append(
                ExtractedFact(
                    fact_id=f"fact-mvs-{index + 1:04d}",
                    tool="molviewspec",
                    artifact_id=artifact_id,
                    source_location={"artifact_id": artifact_id, "json_pointer": node.get("_pointer", "")},
                    native_command=f"node:{kind}",
                    native_value={key: value for key, value in node.items() if key != "_pointer"},
                    normalized_target={"object_type": f"molviewspec.{kind}", "json_pointer": ""},
                    normalized_value={"node_kind": kind, "experimental": True},
                    support_status="supported_heuristic",
                    confidence={
                        "level": "medium",
                        "score": 0.6,
                        "basis": ["structured_json_tree", "experimental_mapping"],
                    },
                    review_status="needs_review",
                )
            )
        task = CompletionTask(
            id="task:experimental-mvs-review",
            section="scene",
            question="Confirm MolViewSpec scene semantics and claim-critical meaning.",
            target_json_pointer="/scenes",
            field_use="MolViewSpec is structured, but claim and evidence semantics still require author confirmation.",
            examples=["confirmed", "unknown"],
            accepted_values=["confirmed", "unknown", "not_applicable"],
            blocking=False,
        )
        return ImportResult(
            importer_name=self.name,
            facts=facts,
            tasks=[task],
            warnings=["MolViewSpec import is experimental and requires human review."],
        )


def _read_mvs(path: Path) -> dict:
    return read_mvs(path, "artifact:experimental").data


def _walk_tree(node: object, pointer: str = ""):
    if isinstance(node, dict):
        current = dict(node)
        current["_pointer"] = pointer or "/"
        yield current
        children = node.get("children")
        if isinstance(children, list):
            for index, child in enumerate(children):
                yield from _walk_tree(child, f"{pointer}/children/{index}")
    elif isinstance(node, list):
        for index, child in enumerate(node):
            yield from _walk_tree(child, f"{pointer}/{index}")
