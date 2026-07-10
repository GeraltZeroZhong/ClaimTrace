import subprocess
import sys
import os
import json
from pathlib import Path
import shutil
import zipfile

import pytest

from claimtrace import _simple_yaml


def test_end_to_end_zip_roundtrip(tmp_path: Path):
    source = Path("examples/simple-pymol-structure")
    pkg = tmp_path / "scene-package"
    zip_path = tmp_path / "scene-package.zip"
    roundtrip = tmp_path / "roundtrip"
    env = {**os.environ, "PYTHONPATH": "src"}

    subprocess.run(
        [
            sys.executable,
            "-m",
            "claimtrace",
            "init",
            "--native",
            str(source / "figure_A.pml"),
            "--image",
            str(source / "figure_A.png"),
            "--out",
            str(pkg),
            "--template",
            "simple-structure-view",
            "--no-input",
        ],
        check=True,
        env=env,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "claimtrace",
            "complete",
            str(pkg),
            "--answers",
            str(source / "answers.yml"),
            "--no-input",
        ],
        check=True,
        env=env,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "claimtrace",
            "export",
            str(pkg),
            "--zip",
            "--mode",
            "archive",
            "--out",
            str(zip_path),
            "--no-input",
        ],
        check=True,
        env=env,
    )
    roundtrip.mkdir()
    subprocess.run(["unzip", "-q", str(zip_path), "-d", str(roundtrip)], check=True)
    validation_report = json.loads((roundtrip / "validation_report.json").read_text(encoding="utf-8"))
    assert validation_report["revalidation"]["performed_on_exported_package"] is True
    result = subprocess.run(
        [sys.executable, "-m", "claimtrace", "validate", str(roundtrip), "--format", "text"],
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    assert "pass" in result.stdout


@pytest.mark.parametrize("suffix", [".cxc", ".mvsj", ".mvsx"])
def test_supported_native_formats_complete_archive_and_export(tmp_path: Path, suffix: str):
    env = {**os.environ, "PYTHONPATH": "src"}
    source = tmp_path / f"scene{suffix}"
    model = tmp_path / "model.cif"
    image = tmp_path / "figure.png"
    shutil.copyfile("examples/simple-pymol-structure/model.cif", model)
    shutil.copyfile("examples/simple-pymol-structure/figure_A.png", image)
    mvs_tree = {
        "metadata": {"version": "1", "title": f"Roundtrip {suffix}"},
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
                                                {"kind": "representation", "params": {"type": "cartoon"}}
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
                {"kind": "camera", "params": {"target": [0, 0, 0], "position": [0, 0, 20]}},
            ],
        },
    }
    if suffix == ".cxc":
        source.write_text("open model.cif\ncartoon #1\nview\n", encoding="utf-8")
    elif suffix == ".mvsj":
        source.write_text(json.dumps(mvs_tree), encoding="utf-8")
    else:
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("index.mvsj", json.dumps(mvs_tree))
            archive.write(model, "model.cif")

    package = tmp_path / "package"
    archive_path = tmp_path / "package.zip"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "claimtrace",
            "init",
            str(source),
            "--image",
            str(image),
            "--artifact",
            str(model),
            "--out",
            str(package),
        ],
        check=True,
        env=env,
    )
    answers_path = package / "answers.yml"
    answers = _simple_yaml.loads(answers_path.read_text(encoding="utf-8"))
    answers["claim"]["claim_text"] = "The panel shows the attached molecular structure."
    answers["claim"]["figure_ref"] = "Figure 1A"
    answers["uncertainty"] = []
    for evidence in answers.get("evidence", []):
        evidence["method_name"] = "Author visual review"
        evidence["result_summary"] = "The native scene, structure and rendered panel were reviewed together."
    for item in answers.get("scene_semantics_by_operation", []):
        item["claim_critical"] = False
    answers_path.write_text(_simple_yaml.dumps(answers), encoding="utf-8")

    subprocess.run(
        [sys.executable, "-m", "claimtrace", "complete", str(package), "--answers", str(answers_path)],
        check=True,
        env=env,
    )
    subprocess.run(
        [sys.executable, "-m", "claimtrace", "validate", str(package), "--mode", "archive"],
        check=True,
        env=env,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "claimtrace",
            "export",
            str(package),
            "--mode",
            "archive",
            "--out",
            str(archive_path),
        ],
        check=True,
        env=env,
    )

    assert zipfile.is_zipfile(archive_path)
