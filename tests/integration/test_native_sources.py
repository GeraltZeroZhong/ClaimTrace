import json
from pathlib import Path

import pytest

from claimtrace import init_package
from claimtrace.errors import PackageError
from claimtrace.package.registry import register_local_artifact, replay_destination_for
from claimtrace.package.resources import synchronize_resource_bindings


def test_same_basename_sources_bind_to_their_relative_paths(tmp_path: Path):
    script = tmp_path / "scene.pml"
    script.write_text("load a/model.cif, first\nload b/model.cif, second\n", encoding="utf-8")
    first, second = [tmp_path / folder / "model.cif" for folder in ("a", "b")]
    for source, content in ((first, "data_first\n"), (second, "data_second\n")):
        source.parent.mkdir()
        source.write_text(content, encoding="utf-8")

    package = init_package(native=script, artifacts=[second], out=tmp_path / "package")
    assert (package.root / "native/b/model.cif").read_bytes() == second.read_bytes()
    assert not (package.root / "native/a/model.cif").exists()
    assert [item.fixity_status for item in package.semantic_layer.resource_references] == [
        "unknown", "available",
    ]

    package.add_artifact(first)

    assert (package.root / "native/a/model.cif").read_bytes() == first.read_bytes()
    assert (package.root / "native/b/model.cif").read_bytes() == second.read_bytes()
    assert all(item.fixity_status == "available" for item in package.semantic_layer.resource_references)
    assert all(item.target_resolution_status.value == "resolved_against_artifact"
               for item in package.semantic_layer.native_references)


def test_ambiguous_basename_requires_a_relative_source_path(tmp_path: Path):
    script = tmp_path / "scene.pml"
    script.write_text("load a/model.cif, first\nload b/model.cif, second\n", encoding="utf-8")
    package = init_package(native=script, out=tmp_path / "package")
    source = tmp_path / "model.cif"
    source.write_text("data_model\n", encoding="utf-8")
    before = package.semantic_layer.model_dump(mode="json")

    with pytest.raises(PackageError, match="several native resource paths"):
        package.add_artifact(source)
    assert package.semantic_layer.model_dump(mode="json") == before
    assert not (package.root / "native/a/model.cif").exists()

    # The lower-level registration API also permits an explicit destination.
    register_local_artifact(
        package.root, package.semantic_layer, source, relative_destination="native/b/model.cif",
    )
    synchronize_resource_bindings(package.semantic_layer)
    assert [item.fixity_status for item in package.semantic_layer.resource_references] == [
        "unknown", "available",
    ]


def test_unique_basename_fallback_and_specific_relative_path(tmp_path: Path):
    script = tmp_path / "scene.pml"
    script.write_text("load a/model.cif, first\n", encoding="utf-8")
    package = init_package(native=script, out=tmp_path / "package")
    source = tmp_path / "model.cif"
    assert replay_destination_for(package.semantic_layer, source) == "native/a/model.cif"

    script.write_text("load model.cif, first\nload a/model.cif, second\n", encoding="utf-8")
    package = init_package(native=script, out=tmp_path / "specific-package")
    assert replay_destination_for(package.semantic_layer, tmp_path / "a/model.cif") == "native/a/model.cif"


def _write_camera(path: Path, distance: int) -> None:
    if path.suffix == ".cxc":
        path.write_text(f"view\nturn y {distance}\n", encoding="utf-8")
    else:
        path.write_text(json.dumps({
            "metadata": {"version": "1"},
            "root": {"kind": "root", "children": [{
                "kind": "camera", "params": {"target": [0, 0, 0], "position": [0, 0, distance]},
            }]},
        }), encoding="utf-8")


@pytest.mark.parametrize("suffixes", [(".cxc", ".cxc"), (".mvsj", ".mvsj"),
                                      (".cxc", ".mvsj"), (".mvsj", ".cxc")])
def test_native_inputs_keep_independent_scenes_and_cameras(tmp_path: Path, suffixes):
    paths = [tmp_path / f"view-{index}{suffix}" for index, suffix in enumerate(suffixes)]
    for index, path in enumerate(paths, start=1):
        _write_camera(path, index * 10)
    baseline = init_package(native=paths[0], out=tmp_path / "baseline")
    package = init_package(native=paths, out=tmp_path / "package")
    scenes = package.semantic_layer.scenes

    assert len(scenes) == 2
    assert len({scene.id for scene in scenes}) == 2
    assert scenes[0].model_dump(mode="json") == baseline.semantic_layer.scenes[0].model_dump(mode="json")
    for index, (path, scene) in enumerate(zip(paths, scenes), start=1):
        native = next(item for item in package.semantic_layer.artifacts if item.path == f"native/{path.name}")
        assert scene.native_artifact_ids == [native.id]
        operations = [item for item in package.semantic_layer.observed_scene_operations
                      if item.source_location.artifact_id == native.id]
        assert operations
        assert {item.details["scene_id"] for item in operations} == {scene.id}
        if path.suffix == ".cxc":
            assert [item["command"] for item in scene.camera["chimerax_commands"]] == [
                "view", f"turn y {index * 10}",
            ]
        else:
            assert scene.camera["molviewspec"]["params"]["position"] == [0, 0, index * 10]


def test_mvs_snapshots_stay_separate_when_another_native_file_is_added(tmp_path: Path):
    story = tmp_path / "story.mvsj"
    story.write_text(json.dumps({
        "metadata": {"version": "1"},
        "snapshots": [
            {"title": name, "root": {"kind": "root", "children": [{
                "kind": "camera", "params": {"target": [0, 0, 0], "position": [0, 0, distance]},
            }]}}
            for name, distance in (("Before", 10), ("After", 20))
        ],
    }), encoding="utf-8")
    other = tmp_path / "third.mvsj"
    _write_camera(other, 30)

    package = init_package(native=[story, other], out=tmp_path / "package")

    assert len(package.semantic_layer.scenes) == 3
    assert [scene.camera["molviewspec"]["params"]["position"][2]
            for scene in package.semantic_layer.scenes] == [10, 20, 30]
    first, second, third = package.semantic_layer.scenes
    assert first.native_artifact_ids == second.native_artifact_ids
    assert first.native_artifact_ids != third.native_artifact_ids


def test_chimerax_repeated_resources_and_targets_keep_valid_reference_ids(tmp_path: Path):
    script = tmp_path / "views.cxc"
    script.write_text("open model.cif model.cif\nselect #1 | #1\n", encoding="utf-8")
    source = tmp_path / "model.cif"
    source.write_text("data_model\n", encoding="utf-8")

    package = init_package(native=script, artifacts=[source], out=tmp_path / "package")

    resources = package.semantic_layer.resource_references
    assert [item.uri for item in resources] == ["model.cif", "model.cif"]
    assert [item.source_location.column for item in resources] == [6, 16]
    assert len({item.resource_ref_id for item in resources}) == 2
    assert all(item.fixity_status == "available" for item in resources)
    references = package.semantic_layer.native_references
    assert len(references) == 1
    assert references[0].native_expression == "#1"
    assert not any(item.rule_id == "G3.REFERENCE.DUPLICATE_ID"
                   for item in package.validate().findings)


def test_removing_a_resource_record_clears_its_stale_binding(tmp_path: Path):
    script = tmp_path / "view.pml"
    script.write_text("load model.cif, protein\n", encoding="utf-8")
    source = tmp_path / "model.cif"
    source.write_text("data_model\n", encoding="utf-8")
    package = init_package(native=script, artifacts=[source], out=tmp_path / "package")
    semantic = package.semantic_layer
    resource = semantic.resource_references[0]
    native_ref = semantic.native_references[0]
    assert resource.fixity_status == "available"
    assert native_ref.target_resolution_status.value == "resolved_against_artifact"

    semantic.artifacts = [item for item in semantic.artifacts if item.path != "native/model.cif"]
    package.save()

    assert resource.fixity_status == "unknown"
    assert resource.fetch_status == "not_fetched"
    assert native_ref.target_resolution_status.value == "expression_only"
    package.add_artifact(source)
    assert resource.fixity_status == "available"
    assert native_ref.target_resolution_status.value == "resolved_against_artifact"
