import json
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


@pytest.mark.parametrize("bad_name", ["../evil.txt", "C:/secret.txt", r"nested\\evil.txt"])
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
