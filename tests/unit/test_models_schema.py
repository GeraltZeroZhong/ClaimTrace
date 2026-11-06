import json
from pathlib import Path

import jsonschema

from claimtrace.models import SemanticLayer
from claimtrace.schemas import semantic_layer_schema, validation_report_schema


def test_semantic_layer_schema_validates_new_layer():
    semantic = SemanticLayer.new("pkg-test", "Test package")
    jsonschema.Draft202012Validator(semantic_layer_schema()).validate(
        semantic.model_dump(mode="json", exclude_none=True)
    )


def test_validation_report_schema_has_2020_12_marker():
    schema = validation_report_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == "ClaimTrace validation_report.json"


def test_packaged_schema_resources_match_runtime_models():
    schema_dir = Path("src/claimtrace/resources/schema")

    stored_semantic = json.loads(
        (schema_dir / "semantic-layer.schema.json").read_text(encoding="utf-8")
    )
    stored_report = json.loads(
        (schema_dir / "validation-report.schema.json").read_text(encoding="utf-8")
    )

    assert _equivalent_schema_form(stored_semantic) == _equivalent_schema_form(semantic_layer_schema())
    assert _equivalent_schema_form(stored_report) == _equivalent_schema_form(validation_report_schema())


def _equivalent_schema_form(value):
    """Normalize only equivalent spellings emitted across supported Pydantic releases.

    Pydantic 2.7 wraps enum references in allOf and omits the default
    additionalProperties:true. Newer releases emit direct references and an
    explicit true. Defaults, required fields and actual constraints still match
    exactly, so this check continues to detect model/resource drift.
    """
    if isinstance(value, list):
        return [_equivalent_schema_form(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: _equivalent_schema_form(item) for key, item in value.items()}
    if result.get("additionalProperties") is True:
        del result["additionalProperties"]
    alternatives = result.get("allOf")
    if (isinstance(alternatives, list) and len(alternatives) == 1
            and isinstance(alternatives[0], dict) and set(alternatives[0]) == {"$ref"}
            and "$ref" not in result):
        result["$ref"] = alternatives[0]["$ref"]
        del result["allOf"]
    return result
