from types import SimpleNamespace

from claimtrace.package.resources import resource_matches_artifact, synchronize_resource_bindings


def test_resource_matching_uses_basename_only_for_bare_native_paths():
    semantic = SimpleNamespace(
        artifacts=[
            SimpleNamespace(path="data/structures/model.cif"),
        ]
    )

    assert resource_matches_artifact(semantic, "model.cif")
    assert resource_matches_artifact(semantic, "structures/model.cif")
    assert not resource_matches_artifact(semantic, "other/model.cif")


def test_known_native_resource_must_resolve_from_native_script_directory():
    resource = SimpleNamespace(
        uri="model.cif",
        uri_kind="relative",
        artifact_id="artifact:pml",
    )
    semantic = SimpleNamespace(
        artifacts=[
            SimpleNamespace(id="artifact:pml", path="native/figure_A.pml"),
            SimpleNamespace(id="artifact:model", path="data/structures/model.cif"),
        ],
        resource_references=[resource],
    )

    assert not resource_matches_artifact(semantic, "model.cif")

    semantic.artifacts[1].path = "native/model.cif"
    assert resource_matches_artifact(semantic, "model.cif")


def test_json_resource_binding_resolves_only_the_same_json_pointer():
    location = SimpleNamespace(artifact_id="artifact:mvsj", line=None, json_pointer="/root/children/1")
    resource = SimpleNamespace(
        uri="annotations.json",
        uri_kind="relative",
        artifact_id="artifact:mvsj",
        source_location=location,
        fixity_status="unknown",
        fetch_status="not_fetched",
    )
    matching_ref = SimpleNamespace(
        source_location=SimpleNamespace(
            artifact_id="artifact:mvsj",
            line=None,
            json_pointer="/root/children/1",
        ),
        target_resolution_status="expression_only",
    )
    unrelated_ref = SimpleNamespace(
        source_location=SimpleNamespace(
            artifact_id="artifact:mvsj",
            line=None,
            json_pointer="/root/children/2",
        ),
        target_resolution_status="expression_only",
    )
    semantic = SimpleNamespace(
        artifacts=[
            SimpleNamespace(id="artifact:mvsj", path="native/scene.mvsj"),
            SimpleNamespace(id="artifact:annotation", path="native/annotations.json"),
        ],
        resource_references=[resource],
        native_references=[matching_ref, unrelated_ref],
    )

    synchronize_resource_bindings(semantic)

    assert matching_ref.target_resolution_status == "resolved_against_artifact"
    assert unrelated_ref.target_resolution_status == "expression_only"
