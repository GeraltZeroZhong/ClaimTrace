from pathlib import Path

from claimtrace.importers.pymol import PyMOLImporter
from claimtrace.models import SemanticLayer


def test_pymol_importer_extracts_selection_and_downgrades_dynamic(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text(
        "select active_site, chain A and resi 10\n"
        "distance d1, active_site, ligand\n"
        "run dangerous.py\n",
        encoding="utf-8",
    )
    semantic = SemanticLayer.new("pkg-test")

    result = PyMOLImporter().import_into(pml, "artifact:pml", semantic)

    assert any(selection.name == "active_site" for selection in semantic.selections)
    assert any(evidence.evidence_kind.value == "measurement" for evidence in semantic.evidence)
    assert any(fact.support_status == "raw_unsupported" for fact in result.facts)
    assert "hydrogen" not in result.fact_dicts()[1]["normalized_value"].get("classification", "")


def test_pymol_importer_auto_records_scene_operations(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text(
        "select ligand, resn LIG\n"
        "create ligand_obj, ligand\n"
        "show sticks, ligand\n"
        "show cartoon, protein\n"
        "hide sticks, solvent\n"
        "color magenta, ligand\n"
        "label ligand, name\n"
        "clip slab, 20\n",
        encoding="utf-8",
    )
    semantic = SemanticLayer.new("pkg-test")

    PyMOLImporter().import_into(pml, "artifact:pml", semantic)

    operations = semantic.scenes[0].extensions["observed_scene_operations"]
    observed = {item["operation"] for item in operations}
    assert {"created", "displayed", "hidden", "simplified", "colored", "labeled", "clipped"} <= observed
    color_operation = next(item for item in operations if item["operation"] == "colored")
    label_operation = next(item for item in operations if item["operation"] == "labeled")
    assert color_operation["details"]["color"] == "magenta"
    assert color_operation["meaning_status"] == "tool_suggested_meaning"
    assert color_operation["auto_annotation"] == "Target `ligand` is colored `magenta`."
    assert "ligand" in color_operation["candidate_meaning"]
    assert label_operation["details"]["label_expression"] == "name"
    assert label_operation["meaning_status"] == "tool_suggested_meaning"
    assert label_operation["auto_annotation"] == "Target `ligand` is labeled with `name`."
    assert semantic.observed_scene_operations
    assert any(operation.operation == "colored" for operation in semantic.observed_scene_operations)
    assert any(operation.candidate_meaning for operation in semantic.observed_scene_operations)
    assert [record.native_target for record in semantic.scenes[0].visibility] == [
        "ligand",
        "protein",
        "solvent",
    ]
    assert semantic.scenes[0].visibility[0].selection_id == semantic.selections[0].id
    assert all(record.selection_id is None for record in semantic.scenes[0].visibility[1:])


def test_pymol_label_expression_keeps_quoted_comma(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text('label ligand, "%s,%s" % (resn,resi)\n', encoding="utf-8")
    semantic = SemanticLayer.new("pkg-test")

    PyMOLImporter().import_into(pml, "artifact:pml", semantic)

    label_operation = next(operation for operation in semantic.observed_scene_operations if operation.operation == "labeled")
    assert label_operation.details["label_expression"] == '"%s,%s" % (resn,resi)'


def test_pymol_importer_keeps_multiline_set_view_together(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text(
        "set_view (\\\n"
        "  0.999, 0.010, 0.000,\\\n"
        "  0.000, 0.000, 1.000 )\n",
        encoding="utf-8",
    )
    semantic = SemanticLayer.new("pkg-test")

    result = PyMOLImporter().import_into(pml, "artifact:pml", semantic)

    assert not semantic.raw_native_observations
    assert any(operation.operation == "camera_set" for operation in semantic.observed_scene_operations)
    assert all(fact.support_status != "raw_unsupported" for fact in result.facts)


def test_pymol_importer_splits_semicolons_and_strips_only_unquoted_comments(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text(
        'select quoted, resn "A;#B"; label quoted, "%s;%s#ok" % (resn,resi); '
        "show sticks, quoted; color cyan, quoted # trailing comment; hide lines, quoted\n",
        encoding="utf-8",
    )
    semantic = SemanticLayer.new("pkg-test")

    result = PyMOLImporter().import_into(pml, "artifact:pml", semantic)

    assert [fact.native_value["command"] for fact in result.facts] == [
        "select",
        "label",
        "show",
        "color",
    ]
    assert {fact.source_location["line"] for fact in result.facts} == {1}
    assert len({fact.fact_id for fact in result.facts}) == 4
    assert all("runtime_unverified" in fact.confidence["basis"] for fact in result.facts)
    label_operation = next(operation for operation in semantic.observed_scene_operations if operation.operation == "labeled")
    assert label_operation.details["label_expression"] == '"%s;%s#ok" % (resn,resi)'
    assert semantic.selections[0].native_selector.value == 'resn "A;#B"'


def test_pymol_importer_unquotes_load_and_output_paths_and_keeps_load_state(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text(
        'load "inputs/model one.pdb", "complex A", 2, pdb\n'
        'png "out/image one.png", 1200, 900, 300, 1\n'
        'save "out/session one.pse", "complex A", 2, pse\n',
        encoding="utf-8",
    )
    semantic = SemanticLayer.new("pkg-test")

    result = PyMOLImporter().import_into(pml, "artifact:pml", semantic)

    assert semantic.resource_references[0].uri == "inputs/model one.pdb"
    assert semantic.native_references[0].native_expression == "complex A"
    loaded = next(operation for operation in semantic.observed_scene_operations if operation.operation == "loaded")
    assert loaded.target == "complex A"
    assert loaded.details["state"] == "2"
    outputs = [operation for operation in semantic.observed_scene_operations if operation.operation == "output_intent"]
    assert [operation.target for operation in outputs] == ["out/image one.png", "out/session one.pse"]
    assert outputs[0].details["width"] == "1200"
    assert outputs[1].details["state"] == "2"
    assert result.facts[0].normalized_value["object"] == "complex A"
    assert result.facts[0].normalized_value["state"] == "2"


def test_pymol_selection_and_evidence_ids_are_namespaced_per_artifact(tmp_path: Path):
    first = tmp_path / "first.pml"
    second = tmp_path / "second.pml"
    script = "select focus, chain A\ndistance d1, focus, ligand\n"
    first.write_text(script, encoding="utf-8")
    second.write_text(script, encoding="utf-8")
    semantic = SemanticLayer.new("pkg-test")

    PyMOLImporter().import_into(first, "artifact:first", semantic)
    PyMOLImporter().import_into(second, "artifact:second", semantic)

    assert len(semantic.selections) == 2
    assert len({selection.id for selection in semantic.selections}) == 2
    assert {selection.source_artifact_id for selection in semantic.selections} == {
        "artifact:first",
        "artifact:second",
    }
    assert len(semantic.evidence) == 2
    assert len({evidence.id for evidence in semantic.evidence}) == 2
    measurements = [
        operation for operation in semantic.observed_scene_operations if operation.operation == "measurement_intent"
    ]
    assert len(measurements) == 2
    assert all("runtime_unverified" in operation.extraction_confidence.basis for operation in measurements)


def test_pymol_importer_structures_common_scene_commands(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text(
        "reinitialize everything\n"
        "bg_color white\n"
        "set_color warning, [1.0, 0.5, 0.0]\n"
        "remove solvent\n"
        "delete old_object\n"
        "enable protein\n"
        "disable solvent\n"
        "orient protein\n"
        "center ligand\n"
        "origin ligand\n"
        "turn x, 90\n"
        "zoom ligand, 4, 2, 1\n"
        "ray 1200, 900\n"
        "spectrum b, blue_white_red, protein, 0, 100\n"
        "set cartoon_transparency, 0.35, protein\n"
        "quit\n",
        encoding="utf-8",
    )
    semantic = SemanticLayer.new("pkg-test")

    result = PyMOLImporter().import_into(pml, "artifact:pml", semantic)

    assert not semantic.raw_native_observations
    assert all(fact.support_status == "supported_shallow" for fact in result.facts)
    operations = {operation.operation for operation in semantic.observed_scene_operations}
    assert {
        "reinitialized",
        "background_colored",
        "custom_color_defined",
        "atoms_removed",
        "object_deleted",
        "enabled",
        "disabled",
        "camera_oriented",
        "camera_centered",
        "origin_set",
        "camera_turned",
        "camera_zoomed",
        "ray_traced",
        "colored",
        "transparency_changed",
        "session_terminated",
    } <= operations
    spectrum = next(
        operation
        for operation in semantic.observed_scene_operations
        if operation.operation == "colored" and operation.details.get("method") == "spectrum"
    )
    assert spectrum.details["expression"] == "b"
    assert spectrum.needs_author_confirmation is True
    assert spectrum.meaning_status.value == "requires_user_completion"
    transparency = next(
        operation for operation in semantic.observed_scene_operations if operation.operation == "transparency_changed"
    )
    assert transparency.details["setting"] == "cartoon_transparency"
    removed = next(record for record in semantic.scenes[0].visibility if record.state == "excluded")
    assert removed.native_target == "solvent"
    assert removed.selection_id is None


def test_pymol_color_semantics_and_bad_selection_names_require_review(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text(
        'select "bad name", chain A\n'
        "select all, chain B\n"
        "color red, confidence\n"
        "color warning, ligand\n"
        "@helper.pml\n"
        "run helper.py\n",
        encoding="utf-8",
    )
    semantic = SemanticLayer.new("pkg-test")

    result = PyMOLImporter().import_into(pml, "artifact:pml", semantic)

    reasons = {observation.reason for observation in semantic.raw_native_observations}
    assert "invalid_pymol_selection_name:bad name" in reasons
    assert "reserved_pymol_selection_name:all" in reasons
    assert sum(reason == "dynamic_or_executable_pymol_content" for reason in reasons) == 1
    assert sum(fact.support_status == "raw_unsupported" for fact in result.facts) == 2
    colors = [operation for operation in semantic.observed_scene_operations if operation.operation == "colored"]
    assert len(colors) == 2
    assert all(operation.needs_author_confirmation for operation in colors)
    assert all(operation.meaning_status.value == "requires_user_completion" for operation in colors)
