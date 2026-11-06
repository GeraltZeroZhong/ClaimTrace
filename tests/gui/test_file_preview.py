"""Preview responses stay with the file dialog that requested them."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_slow_file_preview_cannot_replace_the_next_files_contents():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise asynchronous browser previews")
    source = (Path(__file__).parents[2] / "src/claimtrace/gui/static/app.js").read_text(encoding="utf-8")
    preview = source[source.index("async function previewFile("):source.index("async function loadSource(")]
    checks = r'''
const assert = require("node:assert/strict");
const esc = value => value, icon = () => "", artifactURL = id => id;
const artifact = id => ({id, path: id + ".txt", role: "evidence_document"});
const rendered = [], pending = new Map();
let current;
const $ = () => current;
const dialog = () => {
 if (current) current.isConnected = false;
 current = {isConnected: true, textContent: "Loading file…"};
};
const renderFilePreview = (element, text, path) => { element.textContent = text; rendered.push({text, path}); };
const fetch = id => new Promise((resolve, reject) => pending.set(id, {resolve, reject}));
const response = text => ({ok: true, text: async () => text, headers: {get: () => null}});
(async () => {
 const earlier = previewFile("first");
 const later = previewFile("second");
 pending.get("second").resolve(response("Second file data"));
 await later;
 pending.get("first").resolve(response("First file data"));
 await earlier;
 assert.equal(current.textContent, "Second file data");
 assert.deepEqual(rendered, [{text: "Second file data", path: "second.txt"}]);
 const failing = previewFile("third");
 const newest = previewFile("fourth");
 pending.get("fourth").resolve(response("Fourth file data"));
 await newest;
 pending.get("third").reject(new Error("Third file unavailable"));
 await failing;
 assert.equal(current.textContent, "Fourth file data");
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    result = subprocess.run([node, "-e", preview + checks], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr


def test_browser_download_uses_the_servers_package_filename():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise browser downloads")
    source = (Path(__file__).parents[2] / "src/claimtrace/gui/static/app.js").read_text(encoding="utf-8")
    download = source[source.index("async function downloadPackage("):source.index("async function action(")]
    checks = r'''
const assert = require("node:assert/strict");
const state = {busy: false, data: {workflow: {lifecycle: {mode: "draft"}}}};
const button = {}, feedback = {}, link = {click() { this.clicked = true; }};
const $ = selector => selector === "#export-feedback" ? feedback : button;
const busy = value => { state.busy = value; }, icon = () => "";
const document = {createElement: () => link};
const URL = {createObjectURL: () => "blob:download", revokeObjectURL() {}};
const setTimeout = callback => callback();
const fetch = async () => ({ok: true, blob: async () => ({}), headers: {
 get: key => key === "Content-Disposition" ? "attachment; filename*=UTF-8''figure-review-draft.zip" : null,
}});
(async () => {
 await downloadPackage();
 assert.equal(link.download, "figure-review-draft.zip");
 assert.equal(link.clicked, true);
 assert.equal(state.busy, false);
 assert.equal(feedback.className, "export-success");
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    result = subprocess.run([node, "-e", download + checks], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
