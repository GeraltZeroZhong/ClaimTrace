"""Static image metadata importer."""

from __future__ import annotations

import math
import warnings
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from claimtrace.importers.base import ExtractedFact, ImportResult
from claimtrace.models import CompletionTask, SemanticLayer


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".webp", ".svg"}
MAX_SVG_BYTES = 16 * 1024 * 1024
RASTER_FORMATS_BY_SUFFIX = {
    ".png": {"PNG"},
    ".jpg": {"JPEG"},
    ".jpeg": {"JPEG"},
    ".gif": {"GIF"},
    ".tif": {"TIFF"},
    ".tiff": {"TIFF"},
    ".webp": {"WEBP"},
}


class ImageImporter:
    name = "image"
    stability = "stable"

    def detect(self, path: Path) -> float:
        return 0.9 if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES else 0.0

    def import_into(self, path: Path, artifact_id: str, semantic: SemanticLayer) -> ImportResult:
        metadata = inspect_image(path)
        dimensions = metadata.get("dimensions")
        artifact = next((item for item in semantic.artifacts if item.id == artifact_id), None)
        if artifact:
            artifact.extensions["image"] = metadata
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


def inspect_image(path: Path) -> dict[str, Any]:
    """Verify a supported image and return reader-friendly metadata."""

    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        raise ValueError(f"Unsupported rendered-image format: {path.suffix or 'no extension'}.")
    if suffix == ".svg":
        return _inspect_svg(path)
    try:
        from PIL import Image

        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                detected_format = str(image.format or "").upper()
                dimensions = tuple(int(value) for value in image.size)
                image.verify()
    except Exception as exc:
        raise ValueError(
            f"Rendered image cannot be decoded as a valid {suffix.lstrip('.').upper()} file: {path}."
        ) from exc
    if detected_format not in RASTER_FORMATS_BY_SUFFIX[suffix]:
        raise ValueError(
            f"Rendered image extension {suffix} does not match its {detected_format or 'unknown'} content: {path}."
        )
    if len(dimensions) != 2 or any(value <= 0 for value in dimensions):
        raise ValueError(f"Rendered image has invalid pixel dimensions: {path}.")
    return {
        "status": "verified",
        "format": detected_format,
        "dimensions": dimensions,
        "width": dimensions[0],
        "height": dimensions[1],
    }


def image_dimensions(path: Path) -> tuple[int, int] | None:
    metadata = inspect_image(path)
    dimensions = metadata.get("dimensions")
    return tuple(dimensions) if dimensions else None


def _inspect_svg(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_SVG_BYTES:
            raise ValueError(f"SVG exceeds the {MAX_SVG_BYTES // (1024 * 1024)} MiB safety limit")
        payload = path.read_bytes()
        if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
            raise ValueError("SVG document type and entity declarations are not accepted")
        root = ElementTree.fromstring(payload)
    except (OSError, ElementTree.ParseError, ValueError) as exc:
        raise ValueError(f"Rendered SVG is not a safe, well-formed SVG document: {path}.") from exc
    if root.tag.rsplit("}", 1)[-1].lower() != "svg":
        raise ValueError(f"Rendered SVG must have an <svg> document root: {path}.")
    dimensions = _svg_dimensions(root)
    metadata: dict[str, Any] = {"status": "verified", "format": "SVG"}
    if dimensions:
        metadata.update(
            {
                "dimensions": dimensions,
                "width": dimensions[0],
                "height": dimensions[1],
            }
        )
    return metadata


def _svg_dimensions(root: ElementTree.Element) -> tuple[int, int] | None:
    width = _svg_length(root.attrib.get("width"))
    height = _svg_length(root.attrib.get("height"))
    if width and height:
        return _positive_pixel_count(width), _positive_pixel_count(height)
    view_box = root.attrib.get("viewBox", "").replace(",", " ").split()
    if len(view_box) != 4:
        return None
    try:
        view_width, view_height = float(view_box[2]), float(view_box[3])
    except ValueError:
        return None
    if not (math.isfinite(view_width) and math.isfinite(view_height)):
        return None
    if view_width <= 0 or view_height <= 0:
        return None
    return _positive_pixel_count(view_width), _positive_pixel_count(view_height)


def _svg_length(value: str | None) -> float | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized.endswith("%"):
        return None
    unit_scale = {
        "px": 1.0,
        "pt": 96.0 / 72.0,
        "pc": 16.0,
        "cm": 96.0 / 2.54,
        "mm": 96.0 / 25.4,
        "in": 96.0,
    }
    scale = 1.0
    for unit, candidate_scale in unit_scale.items():
        if normalized.endswith(unit):
            normalized = normalized[: -len(unit)].strip()
            scale = candidate_scale
            break
    try:
        result = float(normalized) * scale
    except ValueError:
        return None
    return result if math.isfinite(result) and result > 0 else None


def _positive_pixel_count(value: float) -> int:
    return max(1, round(value))
