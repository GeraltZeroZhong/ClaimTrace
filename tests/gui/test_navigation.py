"""Keep claim navigation stable across reloads and received-package edits."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_initial_load_selects_claim_and_working_copy_retains_current_context():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise browser navigation")
    source = (Path(__file__).parents[2] / "src/claimtrace/gui/static/app.js").read_text(encoding="utf-8")
    accept_data = source[source.index("function rememberView("):source.index("async function mutate(")]
    checks = r'''
const assert = require("node:assert/strict");
const state = {data: null, claimId: null, view: "prepare"};
const list = (items) => items || [];
const claim = () => list(state.data?.semantic?.claims).find((c) => c.id === state.claimId);
const render = () => {};
const location = {search: ""};
const storage = new Map();
const sessionStorage = {
  getItem: key => storage.get(key) || null,
  setItem: (key, value) => storage.set(key, value),
};
const data = {root: "/received", semantic: {scenes: [{id: "scene:2"}], claims: [{id: "first"}, {id: "second", scene_ids: ["scene:2"]}]}};
acceptData(data);
assert.equal(state.claimId, "first");
assert.equal(state.view, "review");
// A saved claim stays in the author's current stage after a page refresh.
state.view = "prepare";
rememberView();
state.data = null;
acceptData(data);
assert.equal(state.view, "prepare");
state.view = "export";
rememberView();
state.data = null;
acceptData(data);
assert.equal(state.view, "export");
// An explicit launch destination takes precedence over the saved stage.
location.search = "?view=review";
state.data = null;
acceptData(data);
assert.equal(state.view, "review");
location.search = "";
state.claimId = "second";
state.sceneId = "scene:2";
state.view = "prepare";
state.tab = "uncertainty";
rememberView();
state.data = null;
state.claimId = null;
state.sceneId = null;
state.tab = "visual";
acceptData(data);
assert.equal(state.claimId, "second");
assert.equal(state.sceneId, "scene:2");
assert.equal(state.tab, "uncertainty");
state.tab = "evidence";
rememberView();
state.data = null;
acceptData(data);
assert.equal(state.claimId, "second");
assert.equal(state.tab, "evidence");
state.claimId = null;
state.sceneId = "scene:2";
rememberView();
state.data = null;
acceptData(data);
assert.equal(state.claimId, null);
assert.equal(state.sceneId, "scene:2");
// Returning to claim editing still retains context through a working copy.
state.claimId = "second";
state.tab = "uncertainty";
acceptData({...data, root: "/working", working_copy_from: "/received"});
assert.equal(state.claimId, "second");
assert.equal(state.view, "prepare");
assert.equal(state.tab, "uncertainty");
acceptData({...data, root: "/different"});
assert.equal(state.claimId, "first");
assert.equal(state.view, "review");
// A different package and unavailable browser storage retain useful defaults.
state.data = null;
acceptData({...data, root: "/new-package"});
assert.equal(state.view, "review");
sessionStorage.getItem = () => { throw Error("Storage disabled"); };
sessionStorage.setItem = () => { throw Error("Storage disabled"); };
state.data = null;
acceptData(data);
rememberView();
assert.equal(state.view, "review");
'''
    result = subprocess.run([node, "-e", accept_data + checks], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr


def test_first_claim_proposal_routes_prepare_and_review_to_its_review_action():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise browser navigation")
    source = (Path(__file__).parents[2] / "src/claimtrace/gui/static/app.js").read_text(encoding="utf-8")
    views = source[source.index("function taskRows("):source.index("function proposalClaimIds(")]
    setup = r'''
const assert = require("node:assert/strict");
const state = {view: "prepare", data: {semantic: {claims: []}, workflow: {tasks: [
  {id: "task:review", action: "review-proposal", record_id: "proposal:1", title: "Review the draft", detail: "Source-linked draft"}
]}}};
const list = value => value || [];
const semantic = () => state.data.semantic;
const esc = value => String(value);
const icon = () => "";
const claim = () => null;
for (const render of [prepareView, reviewView]) {
  const html = render();
  assert.match(html, /data-task="task:review"/);
  assert.match(html, /Review suggestion/);
  assert.doesNotMatch(html, /data-action="new-claim"/);
}
'''
    result = subprocess.run([node, "-e", views + setup], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
