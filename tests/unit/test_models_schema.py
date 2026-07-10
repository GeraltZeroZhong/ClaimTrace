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
