import json
from pathlib import Path

from typer.testing import CliRunner

from claimtrace.api import load_package
from claimtrace.cli import app
from claimtrace.gui.examples import create_example

runner = CliRunner()


def invoke(*args):
    result = runner.invoke(app, ["agent", *map(str, args)])
    payload = json.loads(result.stdout)
    assert payload["protocol_version"] == "1"
    return result, payload


def proposal_file(pkg, tmp_path):
    payload = {
        "id": "proposal:cli",
        "actor": {"id": "agent:cli-test", "name": "CLI test"},
        "title": "Describe the selected region",
        "rationale": "The scene specifies a residue selection.",
        "changes": [
            {
                "record_type": "claim",
                "record_id": "claim:cli",
                "fields": {
                    "claim_text": "The scene highlights residues 42 and 85.",
                    "figure_ref": "A",
                    "claim_type": "selection_highlight",
                    "scene_ids": [pkg.semantic_layer.scenes[0].id],
                },
            }
        ],
    }
    path = tmp_path / "proposal.json"
    path.write_text(json.dumps(payload))
    return path


def test_cli_checks_and_inspection_preserve_source_then_review_export(tmp_path):
    pkg = create_example("highlight-residues", tmp_path)
    source = proposal_file(pkg, tmp_path)
    before = (pkg.root / "semantic_layer.json").read_bytes()
    for arguments in [("schema",), ("inspect", pkg.root), ("check", pkg.root, "--input", source)]:
        result, payload = invoke(*arguments)
        assert result.exit_code == 0, payload
        assert payload["ok"]
        assert (pkg.root / "semantic_layer.json").read_bytes() == before
    result, payload = invoke("propose", pkg.root, "--input", source)
    assert result.exit_code == 0, payload
    assert payload["proposal"]["status"] == "pending"
    assert not load_package(pkg.root).semantic_layer.claims
    _, state = invoke("inspect", pkg.root, "--summary")
    assert state["workflow"]["next_action"]["record_id"] == "proposal:cli"
    assert state["workflow"]["next_action"]["action"] == "review-proposal"
    assert all(t["action"] != "new-claim" for t in state["workflow"]["tasks"])
    from claimtrace.export.readme import render_readme

    text = render_readme(load_package(pkg.root).semantic_layer)
    assert "proposal:cli" in text and "Proposed statement: The scene highlights residues 42 and 85." in text
    assert "Use **Add claim**" not in text
    result, payload = invoke(
        "review", pkg.root, "proposal:cli", "--decision", "accept", "--reviewer", "Reviewer"
    )
    assert result.exit_code == 0, payload
    result, payload = invoke("inspect", pkg.root, "--claim", "claim:cli")
    assert payload["semantic"]["claims"][0]["claim_text"]["source_type"] == "tool_generated"
    assert payload["audit"]["claims"][0]["id"] == "claim:cli"
    _, summary = invoke("inspect", pkg.root, "--summary")
    claim = summary["audit"]["claims"][0]
    assert "operation_ids" not in claim
    for key in ("stages", "source_artifacts", "selection_ids", "issues", "replay_status"):
        assert claim[key] == payload["audit"]["claims"][0][key]
    assert all("blocking" in item for item in summary["validation"]["findings"])
    assert all(t["action"] != "review-proposal" for t in summary["workflow"]["tasks"])
    result = runner.invoke(app, ["export", str(pkg.root), "--out", str(tmp_path / "audit.zip")])
    assert result.exit_code == 0, result.output


def test_received_export_proposal_creates_working_copy(tmp_path):
    pkg = create_example("highlight-residues", tmp_path)
    source = proposal_file(pkg, tmp_path)
    received = pkg.export(tmp_path / "received", mode="draft")
    before = {
        str(p.relative_to(received)): p.read_bytes() for p in received.rglob("*") if p.is_file()
    }
    result, payload = invoke(
        "propose", received, "--input", source, "--workspace", tmp_path / "copies"
    )
    assert result.exit_code == 0, payload
    assert payload["working_copy_from"] == str(received)
    copy = Path(payload["package"])
    assert copy != received
    assert {
        str(p.relative_to(received)): p.read_bytes() for p in received.rglob("*") if p.is_file()
    } == before
    result, payload = invoke(
        "review", copy, "proposal:cli", "--decision", "accept", "--reviewer", "Reviewer"
    )
    assert result.exit_code == 0, payload
    assert len(load_package(copy).semantic_layer.claims) == 1
    assert len(list((tmp_path / "copies").iterdir())) == 1


def test_errors_are_machine_readable_and_leave_package_unchanged(tmp_path):
    pkg = create_example("highlight-residues", tmp_path)
    source = proposal_file(pkg, tmp_path)
    data = json.loads(source.read_text())
    data["changes"][0]["fields"]["claim_type"] = "invalid"
    source.write_text(json.dumps(data))
    before = (pkg.root / "semantic_layer.json").read_bytes()
    for action in ("check", "propose"):
        result, payload = invoke(action, pkg.root, "--input", source)
        assert result.exit_code == 1
        assert payload["ok"] is False
        assert payload["errors"][0]["code"]
        assert "message" in payload["errors"][0]
        assert (pkg.root / "semantic_layer.json").read_bytes() == before
    result, payload = invoke("proposals", pkg.root, "--status", "invalid")
    assert result.exit_code == 1 and payload["errors"]


def test_summary_retains_actionable_findings_sources_and_pending_status(tmp_path):
    pkg = create_example("highlight-residues", tmp_path)
    source = proposal_file(pkg, tmp_path)
    invoke("propose", pkg.root, "--input", source)
    before = (pkg.root / "semantic_layer.json").read_bytes()
    _, full = invoke("inspect", pkg.root)
    result, summary = invoke("inspect", pkg.root, "--summary")
    assert result.exit_code == 0, summary
    assert summary["audit"] == full["audit"]
    assert summary["scope"]["detail"] == "summary"
    assert {a["id"] for a in summary["artifacts"]} == {
        a["id"] for a in full["semantic"]["artifacts"]
    }
    assert {f["rule_id"] for f in summary["validation"]["findings"]} == {
        f["rule_id"] for f in full["validation"]["findings"] if f["status"] != "PASS"
    }
    assert summary["proposals"][0]["status"] == "pending"
    assert len(json.dumps(summary)) < len(json.dumps(full)) / 2
    assert (pkg.root / "semantic_layer.json").read_bytes() == before


def test_skill_resource_exports_a_complete_portable_bundle(tmp_path):
    result = runner.invoke(app, ["skill"])
    source = Path(result.stdout.strip())
    assert source.is_file()
    output = tmp_path / "claimtrace"
    result = runner.invoke(app, ["skill", "--out", str(output)])
    assert result.exit_code == 0, result.output
    files = {
        p.relative_to(source.parent): p.read_bytes()
        for p in source.parent.rglob("*")
        if p.is_file()
    }
    assert files == {
        p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()
    }
    result = runner.invoke(app, ["skill", "--out", str(output)])
    assert result.exit_code == 1
    assert (output / "SKILL.md").read_bytes() == source.read_bytes()
