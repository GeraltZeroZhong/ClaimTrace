import json
from pathlib import Path
import zipfile

from claimtrace.api import init_package
from claimtrace.completion import apply_answers
from claimtrace.export.readme import render_readme
from claimtrace.validation.engine import validate_package


def test_readme_does_not_show_confirmed_operation_as_unconfirmed(tmp_path: Path):
    pml = tmp_path / "scene.pml"
    pml.write_text("color magenta, ligand\n", encoding="utf-8")
    pkg = init_package(native=pml, out=tmp_path / "pkg")
    operation = pkg.semantic_layer.observed_scene_operations[0]
    answers = {
        "answer_schema": "claimtrace.native_scene_answers.v1",
        "claim": {
            "claim_text": "Figure highlights the ligand.",
            "claim_type": "selection_highlight",
            "figure_ref": "Figure 1A",
        },
        "evidence": [
            {
                "evidence_kind": "manual_rationale",
                "result_summary": "Native scene was reviewed.",
                "source_artifact_roles": ["native_script"],
            }
        ],
        "reuse": {"license": "unknown"},
        "scene_semantics_by_operation": [
            {
                "operation_ids": [operation.operation_id],
                "encoding_type": operation.operation,
                "meaning_status": "user_confirmed_meaning",
                "meaning": "magenta marks the ligand discussed in this panel",
                "claim_critical": "true",
            }
        ],
    }

    apply_answers(pkg.root, pkg.semantic_layer, answers, answer_base=tmp_path)
    report = validate_package(pkg.root, mode="archive")
    text = render_readme(pkg.semantic_layer, report)

    assert "## Review Summary" in text
    assert "## Evidence Summary" in text
    assert "## Visual Meaning Summary" in text
    assert "## Open Items / Limits" in text
    assert "Author confirmed: magenta marks the ligand discussed in this panel" in text
    assert "Tool suggestion (unconfirmed): Color may highlight the ligand" not in text
    assert "Author confirmed: magenta marks the ligand discussed in this panel Confirmation needed." not in text
    assert "{'json_pointer'" not in text
    assert "validation_report.json" in text


def test_readme_gives_native_replay_guidance_for_cxc_mvsj_and_mvsx(tmp_path: Path):
    cxc = tmp_path / "scene A.cxc"
    cxc.write_text("view\n", encoding="utf-8")
    cxc_pkg = init_package(native=cxc, out=tmp_path / "cxc")

    mvs_tree = {
        "metadata": {"version": "1"},
        "root": {"kind": "root", "children": []},
    }
    mvsj = tmp_path / "scene A.mvsj"
    mvsj.write_text(json.dumps(mvs_tree), encoding="utf-8")
    mvsj_pkg = init_package(native=mvsj, out=tmp_path / "mvsj")

    mvsx = tmp_path / "scene A.mvsx"
    with zipfile.ZipFile(mvsx, "w") as archive:
        archive.writestr("index.mvsj", json.dumps(mvs_tree))
    mvsx_pkg = init_package(native=mvsx, out=tmp_path / "mvsx")

    cxc_text = render_readme(cxc_pkg.semantic_layer)
    mvsj_text = render_readme(mvsj_pkg.semantic_layer)
    mvsx_text = render_readme(mvsx_pkg.semantic_layer)

    assert "ChimeraX scene: `native/scene A.cxc`" in cxc_text
    assert "chimerax 'scene A.cxc'" in cxc_text
    assert "MolViewSpec JSON: `native/scene A.mvsj`" in mvsj_text
    assert "MolViewSpec archive: `native/scene A.mvsx`" in mvsx_text
    assert "No PyMOL replay file" not in cxc_text + mvsj_text + mvsx_text


def test_readme_bounds_inline_data_uri_for_humans(tmp_path: Path):
    payload = "A" * 5000
    mvsj = tmp_path / "inline.mvsj"
    mvsj.write_text(
        json.dumps(
            {
                "metadata": {"version": "1"},
                "root": {
                    "kind": "root",
                    "children": [
                        {"kind": "download", "params": {"url": f"data:chemical/x-pdb,{payload}"}}
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    pkg = init_package(native=mvsj, out=tmp_path / "pkg")

    text = render_readme(pkg.semantic_layer)

    assert "inline data URI (chemical/x-pdb" in text
    assert payload not in text
