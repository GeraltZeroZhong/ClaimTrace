from types import SimpleNamespace

from claimtrace.package.resources import resource_matches_artifact, synchronize_resource_bindings


def _artifact(**values):
    defaults = {
        "id": "artifact:test",
        "path": "data/test.dat",
        "kind": "local_attached",
        "included": True,
        "sha256": "0" * 64,
        "role": SimpleNamespace(value="generic"),
        "format": "application/octet-stream",
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_resource_matching_uses_basename_only_for_bare_native_paths():
    semantic = SimpleNamespace(
        artifacts=[
            _artifact(path="data/structures/model.cif"),
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
            _artifact(id="artifact:pml", path="native/figure_A.pml"),
            _artifact(id="artifact:model", path="data/structures/model.cif"),
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
            _artifact(id="artifact:mvsj", path="native/scene.mvsj"),
            _artifact(id="artifact:annotation", path="native/annotations.json"),
        ],
        resource_references=[resource],
        native_references=[matching_ref, unrelated_ref],
    )

    synchronize_resource_bindings(semantic)

    assert matching_ref.target_resolution_status == "resolved_against_artifact"
    assert unrelated_ref.target_resolution_status == "expression_only"


def test_reviewed_detached_binding_keeps_its_recorded_fixity():
    location = SimpleNamespace(artifact_id="artifact:pml", line=1, column=1, json_pointer=None)
    resource = SimpleNamespace(
        uri="model.cif", uri_kind="relative", artifact_id="artifact:pml",
        source_location=location, fixity_status="available", fetch_status="not_fetched",
    )
    native_ref = SimpleNamespace(
        source_location=location, target_resolution_status="resolved_against_artifact",
    )
    semantic = SimpleNamespace(
        artifacts=[
            _artifact(id="artifact:pml", path="native/view.pml"),
            _artifact(id="artifact:model", path="native/model.cif",
                      kind="local_detached", included=False),
        ],
        resource_references=[resource], native_references=[native_ref],
    )

    synchronize_resource_bindings(semantic)

    assert resource.fixity_status == "available"
    assert native_ref.target_resolution_status == "resolved_against_artifact"
