"""Static image metadata importer."""

from __future__ import annotations

import struct
from pathlib import Path

from claimtrace.importers.base import ExtractedFact, ImportResult
from claimtrace.models import CompletionTask, SemanticLayer


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".webp", ".svg"}


class ImageImporter:
    name = "image"
    stability = "stable"

    def detect(self, path: Path) -> float:
        return 0.9 if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES else 0.0

    def import_into(self, path: Path, artifact_id: str, semantic: SemanticLayer) -> ImportResult:
        dimensions = image_dimensions(path)
        artifact = next((item for item in semantic.artifacts if item.id == artifact_id), None)
        if artifact and dimensions:
            artifact.extensions["image"] = {"width": dimensions[0], "height": dimensions[1]}
        fact = ExtractedFact(
            fact_id="fact-image-metadata-0001",
            tool="image",
            artifact_id=artifact_id,
            source_location={"artifact_id": artifact_id, "path": path.name},
            native_command="read image metadata",
            native_value={"path": path.name},
            normalized_target={"object_type": "artifact.image_metadata", "json_pointer": ""},
            normalized_value={"dimensions": dimensions},
            support_status="supported_exact",
            confidence={"level": "exact", "score": 1.0, "basis": ["file_header_metadata"]},
            review_status="auto_extracted",
        )
        task = CompletionTask(
            id="task:image-claim-context",
            section="claim",
            question="What claim, if any, should this static image be linked to?",
            target_json_pointer="/claims",
            field_use="A static image cannot reveal molecular identity, camera, selections or claim meaning by itself.",
            examples=["Figure 1A shows an overview of chain A.", "unknown"],
            accepted_values=["free text", "unknown", "not_applicable"],
            blocking=False,
        )
        return ImportResult(importer_name=self.name, facts=[fact], tasks=[task])


def image_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as handle:
            header = handle.read(32)
        if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
            return struct.unpack(">II", header[16:24])
        if header[:6] in {b"GIF87a", b"GIF89a"} and len(header) >= 10:
            return struct.unpack("<HH", header[6:10])
        if header.startswith(b"<svg"):
            return None
        try:
            from PIL import Image  # type: ignore

            with Image.open(path) as image:
                return image.size
        except Exception:
            return None
    except OSError:
        return None
