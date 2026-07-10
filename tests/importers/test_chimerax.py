from pathlib import Path

from claimtrace.importers.base import default_importers
from claimtrace.importers.chimerax import ChimeraXImporter, split_commands, tokenize_command
from claimtrace.models import SemanticLayer


def test_chimerax_stable_discovered_without_experimental():
    importers = default_importers(include_experimental=False)
    assert any(plugin.name == "chimerax" and plugin.stability == "stable" for plugin in importers)


def test_chimerax_tokenizer_keeps_model_refs_and_splits_comments():
    commands = split_commands('show #1; color magenta "#1/A:42"; # comment\n# full line comment\n')

    assert [command.text for command in commands] == ["show #1", 'color magenta "#1/A:42"']
    tokens, error = tokenize_command(commands[1].text, commands[1].column)
    assert error is None
    assert [token.value for token in tokens] == ["color", "magenta", "#1/A:42"]


def test_chimerax_import_writes_typed_operations_native_refs_and_raw(tmp_path: Path):
    script = tmp_path / "scene.cxc"
    script.write_text(
        "show #1; color magenta #1/A:42\n"
        "runscript build_scene.py $1\n",
        encoding="utf-8",
    )
    semantic = SemanticLayer.new("pkg-test")

    result = ChimeraXImporter().import_into(script, "artifact:cxc", semantic)

    assert result.importer_name == "chimerax"
    assert {operation.operation for operation in semantic.observed_scene_operations} == {"displayed", "colored"}
    color_operation = next(operation for operation in semantic.observed_scene_operations if operation.operation == "colored")
    assert color_operation.meaning_status.value == "requires_user_completion"
    assert color_operation.needs_author_confirmation is True
    assert color_operation.auto_annotation == "Target `#1/A:42` is colored `magenta`."
    assert color_operation.candidate_meaning
    assert {ref.native_expression for ref in semantic.native_references} == {"#1", "#1/A:42"}
    assert semantic.raw_native_observations[0].reason == "dynamic_command_boundary"
    assert all("extraction_confidence" in fact for fact in result.fact_dicts())


def test_chimerax_color_accepts_target_first_order(tmp_path: Path):
    script = tmp_path / "scene.cxc"
    script.write_text("color ligand green\ncolor #1/A:10-130 hot pink\n", encoding="utf-8")
    semantic = SemanticLayer.new("pkg-test")

    ChimeraXImporter().import_into(script, "artifact:cxc", semantic)

    operations = [operation for operation in semantic.observed_scene_operations if operation.operation == "colored"]
    assert operations[0].target == "ligand"
    assert operations[0].details["ast"]["color"] == "green"
    assert operations[0].details["ast"]["color_parse_order"] == "target_color"
    assert operations[1].target == "#1/A:10-130"
    assert operations[1].details["ast"]["color"] == "hot pink"
    assert operations[1].auto_annotation == "Target `#1/A:10-130` is colored `hot pink`."


def test_chimerax_label_text_splits_target_and_label(tmp_path: Path):
    script = tmp_path / "scene.cxc"
    script.write_text("label #1/A:42 text Asp42\n", encoding="utf-8")
    semantic = SemanticLayer.new("pkg-test")

    ChimeraXImporter().import_into(script, "artifact:cxc", semantic)

    operation = semantic.observed_scene_operations[0]
    assert operation.operation == "labeled"
    assert operation.target == "#1/A:42"
    assert operation.details["ast"]["label"] == "Asp42"
    assert operation.auto_annotation == "Target `#1/A:42` is labeled with `Asp42`."


def test_chimerax_official_color_syntax_keeps_hex_and_options(tmp_path: Path):
    script = tmp_path / "scene.cxc"
    script.write_text(
        "color #1/A #ff00ff\ncolor /A & helix sky blue target c\n",
        encoding="utf-8",
    )
    semantic = SemanticLayer.new("pkg-test")

    ChimeraXImporter().import_into(script, "artifact:cxc", semantic)

    first, second = semantic.observed_scene_operations
    assert first.target == "#1/A"
    assert first.details["ast"]["color"] == "#ff00ff"
    assert second.target == "/A & helix"
    assert second.details["ast"]["color"] == "sky blue"
    assert second.details["ast"]["options"] == "target c"


def test_chimerax_open_keeps_quoted_windows_and_multiple_resources(tmp_path: Path):
    script = tmp_path / "scene.cxc"
    script.write_text(
        'open "inputs/model one.cif" name receptor\n'
        "open data/a.cif data/b.cif\n"
        "open 1cbs\n"
        'open "C:\\Users\\Alice\\model one.cif"\n',
        encoding="utf-8",
    )
    semantic = SemanticLayer.new("pkg-test")

    ChimeraXImporter().import_into(script, "artifact:cxc", semantic)

    resources = {resource.uri: resource.uri_kind for resource in semantic.resource_references}
    assert resources == {
        "inputs/model one.cif": "relative",
        "data/a.cif": "relative",
        "data/b.cif": "relative",
        "1cbs": "remote",
        "C:\\Users\\Alice\\model one.cif": "file",
    }


def test_chimerax_records_camera_visibility_and_representation_state(tmp_path: Path):
    script = tmp_path / "scene.cxc"
    script.write_text("cartoon #1\nstyle :LIG stick\nhide #1 atoms\nview\nzoom #1 1.2\n", encoding="utf-8")
    semantic = SemanticLayer.new("pkg-test")

    ChimeraXImporter().import_into(script, "artifact:cxc", semantic)

    scene = semantic.scenes[0]
    assert [item["style"] for item in scene.representations] == ["cartoon", "stick"]
    assert scene.visibility[0].state == "hidden"
    assert len(scene.camera["chimerax_commands"]) == 2
    assert not semantic.raw_native_observations
