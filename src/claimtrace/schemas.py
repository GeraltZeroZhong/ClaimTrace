"""JSON Schema generation and resource helpers."""

from __future__ import annotations

from importlib import resources
from typing import Any

from claimtrace.models import SemanticLayer
from claimtrace.models.validation import ValidationReport


def semantic_layer_schema() -> dict[str, Any]:
    schema = SemanticLayer.model_json_schema(ref_template="#/$defs/{model}")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://claimtrace.org/schema/semantic-layer.schema.json"
    schema["title"] = "Claim Accountability Layer semantic_layer.json"
    return schema


def validation_report_schema() -> dict[str, Any]:
    schema = ValidationReport.model_json_schema(ref_template="#/$defs/{model}")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://claimtrace.org/schema/validation-report.schema.json"
    schema["title"] = "ClaimTrace validation_report.json"
    return schema


def resource_text(package: str, name: str) -> str:
    return resources.files(package).joinpath(name).read_text(encoding="utf-8")
