"""Piped terminal input and agent output preserve scientific Unicode text."""

import json
import os
from pathlib import Path
import subprocess
import sys

from claimtrace.api import init_package, load_package


def test_redirected_cli_streams_preserve_unicode(tmp_path):
    package = init_package(out=tmp_path / "package", title="Protein α", blank=True)
    package.add_claim("Residue β is shown.", figure_ref="A")
    environment = os.environ.copy()
    environment.pop("PYTHONIOENCODING", None)
    environment["PYTHONUTF8"] = "0"
    environment["PYTHONPATH"] = str(Path(__file__).parents[2] / "src")
    result = subprocess.run(
        [sys.executable, "-m", "claimtrace", "prepare", str(package.root)],
        input="1\nResidue γ is shown.\n:draft\n0\n".encode("utf-8"),
        capture_output=True, cwd=tmp_path, env=environment,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    output = result.stdout.decode("utf-8")
    assert "Protein α" in output
    assert "Claim draft saved." in output
    assert load_package(package.root).semantic_layer.claims[0].claim_text.value == "Residue γ is shown."
    result = subprocess.run(
        [sys.executable, "-m", "claimtrace", "agent", "inspect", str(package.root), "--summary"],
        capture_output=True, cwd=tmp_path, env=environment,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    payload = json.loads(result.stdout.decode("utf-8"))
    assert payload["ok"]
    assert payload["audit"]["claims"][0]["headline"] == "Residue γ is shown."
