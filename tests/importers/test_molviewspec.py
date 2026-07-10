import json
from copy import deepcopy
import zipfile
from pathlib import Path

import pytest

from claimtrace.errors import SecurityError
from claimtrace.importers.base import default_importers
from claimtrace.importers.molviewspec import MolViewSpecImporter, read_mvs
from claimtrace.models import SemanticLayer


def _basic_mvs_tree() -> dict:
    return {
        "metadata": {"version": "1"},
        "root": {
            "kind": "root",
            "children": [
                {
                    "kind": "download",
                    "params": {"url": "model.cif"},
                    "children": [
                        {
                            "kind": "parse",
                            "params": {"format": "mmcif"},
                            "children": [
                                {
                                    "kind": "structure",
                                    "params": {"type": "model"},
                                    "children": [
                                        {
                                            "kind": "component",
                                            "params": {"selector": "all"},
                                            "children": [
                                                {
                                                    "kind": "representation",
                                                    "params": {"type": "cartoon"},
                                                    "children": [
                                                        {"kind": "color", "params": {"color": "red"}}
                                                    ],
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
            ],
        },
    }


def test_molviewspec_stable_discovered_without_experimental():
    importers = default_importers(include_experimental=False)
    assert any(plugin.name == "molviewspec" and plugin.stability == "stable" for plugin in importers)


def test_mvsj_import_parses_official_envelope_and_writes_anchors(tmp_path: Path):
    scene = tmp_path / "scene.mvsj"
    scene.write_text(json.dumps(_basic_mvs_tree()), encoding="utf-8")
    semantic = SemanticLayer.new("pkg-test")

    result = MolViewSpecImporter().import_into(scene, "artifact:mvsj", semantic)

    assert result.importer_name == "molviewspec"
    assert {operation.operation for operation in semantic.observed_scene_operations} >= {"represented", "colored"}
    assert any(operation.source_location.json_pointer.startswith("/root") for operation in semantic.observed_scene_operations)
    assert semantic.native_references
    assert semantic.resource_references[0].uri == "model.cif"
    assert all("extraction_confidence" in fact for fact in result.fact_dicts())


def test_mvsx_import_builds_inventory_and_links_archive_member(tmp_path: Path):
    archive = tmp_path / "scene.mvsx"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("index.mvsj", json.dumps(_basic_mvs_tree()))
        zf.writestr("model.cif", "data_model\n")
    semantic = SemanticLayer.new("pkg-test")

    read_result = read_mvs(archive, "artifact:mvsx")
    assert set(read_result.member_bytes) == {"index.mvsj"}

    MolViewSpecImporter().import_into(archive, "artifact:mvsx", semantic)

    inventory = semantic.mvsx_inventories[0]
    model_member = next(member for member in inventory.members if member.normalized_name == "model.cif")
    assert model_member.sha256
    assert model_member.referenced is True
    assert semantic.resource_references[0].mvsx_member_id == model_member.member_id


@pytest.mark.parametrize(
    "bad_name",
    ["../evil.txt", "C:/secret.txt", r"nested\\evil.txt", "nested//evil.txt", "nested/./evil.txt"],
)
def test_mvsx_rejects_unsafe_member_names(tmp_path: Path, bad_name: str):
    archive = tmp_path / "bad.mvsx"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("index.mvsj", json.dumps(_basic_mvs_tree()))
        zf.writestr(bad_name, "bad")

    with pytest.raises(SecurityError):
        read_mvs(archive, "artifact:mvsx")


def test_mvs_camera_metadata_and_selector_are_preserved_conservatively(tmp_path: Path):
    scene = tmp_path / "scene.mvsj"
    data = _basic_mvs_tree()
    data["metadata"]["title"] = "A real MVS title"
    data["root"]["children"].append(
        {"kind": "camera", "params": {"target": [0, 0, 0], "position": [0, 0, 20]}}
    )
    component = data["root"]["children"][0]["children"][0]["children"][0]["children"][0]
    component["params"]["selector"] = {"auth_asym_id": "A", "auth_seq_id": 42}
    scene.write_text(json.dumps(data), encoding="utf-8")
    semantic = SemanticLayer.new("pkg-test")

    result = MolViewSpecImporter().import_into(scene, "artifact:mvsj", semantic)

    assert semantic.package.title == "A real MVS title"
    assert semantic.scenes[0].camera["molviewspec"]["status"] == "statically_recorded_not_rendered"
    assert any(operation.target == '{"auth_asym_id":"A","auth_seq_id":42}' for operation in semantic.observed_scene_operations)
    assert all(
        fact.confidence["basis"] != ["mvs_tree_schema_node", "json_pointer"]
        for fact in result.facts
    )


def test_mvs_snapshots_become_separate_scenes_and_bad_children_stay_raw(tmp_path: Path):
    scene = tmp_path / "story.mvsj"
    scene.write_text(
        json.dumps(
            {
                "metadata": {"version": "1"},
                "snapshots": [
                    {
                        "title": "Before",
                        "linger_duration_ms": 500,
                        "root": {
                            "kind": "root",
                            "children": ["bad child", {"kind": "camera", "params": {"target": [0, 0, 0], "position": [0, 0, 10]}}],
                        },
                    },
                    {
                        "metadata": {"title": "After"},
                        "root": {"kind": "root", "children": []},
                    },
                    "bad snapshot",
                ],
            }
        ),
        encoding="utf-8",
    )
    semantic = SemanticLayer.new("pkg-test")

    MolViewSpecImporter().import_into(scene, "artifact:mvsj", semantic)

    assert [item.description for item in semantic.scenes] == ["Before", "After"]
    assert semantic.observed_scene_operations[0].details["scene_id"] == semantic.scenes[0].id
    assert {item.reason for item in semantic.raw_native_observations} == {
        "invalid_mvs_child",
        "invalid_mvs_snapshot",
    }
    assert semantic.scenes[0].extensions["molviewspec_root"]["snapshot_metadata"]["linger_duration_ms"] == 500


def test_mvs_data_uri_and_missing_archive_member_have_distinct_status(tmp_path: Path):
    archive = tmp_path / "scene.mvsx"
    tree = {
        "metadata": {"version": "1"},
        "root": {
            "kind": "root",
            "children": [
                {"kind": "download", "params": {"url": "data:chemical/x-pdb,ATOM"}},
                {"kind": "download", "params": {"url": "missing/model.cif"}},
            ],
        },
    }
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("index.mvsj", json.dumps(tree))
    semantic = SemanticLayer.new("pkg-test")

    MolViewSpecImporter().import_into(archive, "artifact:mvsx", semantic)

    data_uri, missing = semantic.resource_references
    assert (data_uri.uri_kind, data_uri.fetch_status, data_uri.fixity_status) == (
        "data",
        "not_applicable",
        "available",
    )
    assert missing.uri_kind == "missing_archive_member"
    assert missing.mvsx_member_id is None


def test_nonstandard_single_nested_mvsj_is_read_for_static_review_with_warning(tmp_path: Path):
    archive = tmp_path / "scene.mvsx"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("scene/view.mvsj", json.dumps(_basic_mvs_tree()))
    semantic = SemanticLayer.new("pkg-test")

    result = MolViewSpecImporter().import_into(archive, "artifact:mvsx", semantic)

    assert semantic.mvsx_inventories[0].format_status == "nonstandard_single_mvsj"
    assert semantic.mvsx_inventories[0].scene_entry == "scene/view.mvsj"
    assert any(item.reason == "nonstandard_mvsx_scene_entry" for item in semantic.raw_native_observations)
    assert "top-level index.mvsj" in result.warnings[0]


def test_mvs_measurement_primitives_are_intent_not_generic_overlay(tmp_path: Path):
    scene = tmp_path / "measure.mvsj"
    scene.write_text(
        json.dumps(
            {
                "metadata": {"version": "1"},
                "root": {
                    "kind": "root",
                    "children": [
                        {
                            "kind": "primitives",
                            "children": [
                                {"kind": "primitive", "params": {"kind": "distance_measurement", "start": [0, 0, 0], "end": [1, 0, 0]}},
                                {"kind": "primitive", "params": {"kind": "angle_measurement", "a": [0, 0, 0], "b": [1, 0, 0], "c": [1, 1, 0]}},
                            ],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    semantic = SemanticLayer.new("pkg-test")

    MolViewSpecImporter().import_into(scene, "artifact:mvsj", semantic)

    assert [operation.operation for operation in semantic.observed_scene_operations] == [
        "measurement_intent",
        "measurement_intent",
    ]


def test_mvs_required_clip_uri_format_and_measurement_endpoints_stay_raw(tmp_path: Path):
    scene = tmp_path / "invalid-required-params.mvsj"
    scene.write_text(
        json.dumps(
            {
                "metadata": {"version": "1"},
                "root": {
                    "kind": "root",
                    "children": [
                        {"kind": "clip", "params": {}},
                        {"kind": "primitives_from_uri", "params": {"uri": "marks.json"}},
                        {
                            "kind": "primitives",
                            "children": [
                                {
                                    "kind": "primitive",
                                    "params": {"kind": "distance_measurement", "start": [0, 0, 0]},
                                },
                                {
                                    "kind": "primitive",
                                    "params": {
                                        "kind": "angle_measurement",
                                        "a": [0, 0, 0],
                                        "b": [1, 0, 0],
                                    },
                                },
                            ],
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    semantic = SemanticLayer.new("pkg-test")

    result = MolViewSpecImporter().import_into(scene, "artifact:mvsj", semantic)

    raw_facts = [fact for fact in result.facts if fact.support_status == "raw_unsupported"]
    assert [fact.support_status for fact in raw_facts] == [
        "raw_unsupported",
        "raw_unsupported",
        "raw_unsupported",
        "raw_unsupported",
    ]
    assert {item.reason for item in semantic.raw_native_observations} == {
        "missing_required_mvs_params:type",
        "missing_required_mvs_params:format",
        "missing_required_mvs_params:end",
        "missing_required_mvs_params:c",
    }
    assert not semantic.observed_scene_operations


def test_mvs_current_official_parse_and_representation_enums_are_accepted(tmp_path: Path):
    parse_formats = {
        "mmcif",
        "bcif",
        "pdb",
        "pdbqt",
        "gro",
        "xyz",
        "mol",
        "sdf",
        "mol2",
        "lammpstrj",
        "xtc",
        "nctraj",
        "dcd",
        "trr",
        "psf",
        "prmtop",
        "top",
        "map",
        "dx",
        "dxbin",
    }
    representation_types = {
        "cartoon",
        "backbone",
        "ball_and_stick",
        "line",
        "spacefill",
        "carbohydrate",
        "surface",
        "putty",
    }
    for value in parse_formats:
        data = deepcopy(_basic_mvs_tree())
        data["root"]["children"][0]["children"][0]["params"]["format"] = value
        scene = tmp_path / f"parse-{value}.mvsj"
        scene.write_text(json.dumps(data), encoding="utf-8")
        semantic = SemanticLayer.new(f"pkg-parse-{value}")
        MolViewSpecImporter().import_into(scene, "artifact:mvsj", semantic)
        assert not semantic.raw_native_observations, value

    for value in representation_types:
        data = deepcopy(_basic_mvs_tree())
        representation = data["root"]["children"][0]["children"][0]["children"][0]["children"][0]["children"][0]
        representation["params"]["type"] = value
        scene = tmp_path / f"representation-{value}.mvsj"
        scene.write_text(json.dumps(data), encoding="utf-8")
        semantic = SemanticLayer.new(f"pkg-representation-{value}")
        MolViewSpecImporter().import_into(scene, "artifact:mvsj", semantic)
        assert not semantic.raw_native_observations, value
        assert any(operation.operation == "represented" for operation in semantic.observed_scene_operations)


def test_mvs_volume_enums_camera_shapes_and_invalid_enums_are_checked(tmp_path: Path):
    valid_tree = {
        "metadata": {"version": "1"},
        "root": {
            "kind": "root",
            "children": [
                {
                    "kind": "download",
                    "params": {"url": "map.dx"},
                    "children": [
                        {
                            "kind": "parse",
                            "params": {"format": "dx"},
                            "children": [
                                {
                                    "kind": "volume",
                                    "children": [
                                        {
                                            "kind": "volume_representation",
                                            "params": {"type": "grid_slice", "dimension": "z"},
                                        },
                                        {
                                            "kind": "volume_representation",
                                            "params": {"type": "isosurface"},
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                },
                {
                    "kind": "camera",
                    "params": {"target": [0, 0, 0], "position": [0, 0, 20]},
                },
            ],
        },
    }
    valid = tmp_path / "valid-volume.mvsj"
    valid.write_text(json.dumps(valid_tree), encoding="utf-8")
    semantic = SemanticLayer.new("pkg-valid-volume")
    MolViewSpecImporter().import_into(valid, "artifact:mvsj", semantic)
    assert not semantic.raw_native_observations
    assert [operation.operation for operation in semantic.observed_scene_operations].count(
        "volume_displayed"
    ) == 2
    assert "molviewspec" in semantic.scenes[0].camera

    invalid_tree = deepcopy(valid_tree)
    invalid_tree["root"]["children"].pop(1)
    invalid_tree["root"]["children"].extend(
        [
            {"kind": "camera", "params": {"target": [0, 0], "position": ["x", 0, 1]}},
            {
                "kind": "primitives",
                "children": [{"kind": "primitive", "params": {"kind": "hydrogen_bond"}}],
            },
        ]
    )
    invalid_tree["root"]["children"][0]["children"][0]["params"]["format"] = "nonsense"
    invalid = tmp_path / "invalid-enums.mvsj"
    invalid.write_text(json.dumps(invalid_tree), encoding="utf-8")
    semantic = SemanticLayer.new("pkg-invalid-enums")
    MolViewSpecImporter().import_into(invalid, "artifact:mvsj", semantic)
    reasons = {item.reason for item in semantic.raw_native_observations}
    assert "invalid_mvs_param:format" in reasons
    assert "invalid_mvs_param:target,position" in reasons
    assert "invalid_mvs_param:kind" in reasons
    assert "molviewspec" not in semantic.scenes[0].camera


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
def test_mvsj_rejects_non_finite_json_numbers(tmp_path: Path, token: str):
    scene = tmp_path / "nonfinite.mvsj"
    scene.write_text(
        f'{{"metadata":{{"version":"1"}},"root":{{"kind":"root","children":[]}},"bad":{token}}}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="[Nn]on-finite"):
        read_mvs(scene, "artifact:mvsj")
