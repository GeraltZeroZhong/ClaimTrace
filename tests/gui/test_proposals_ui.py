"""Exercise suggestion rendering and review requests in the browser code."""

import shutil
import subprocess
from pathlib import Path

import pytest


def run_browser_functions(checks: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise suggestion review")
    source = (Path(__file__).parents[2] / "src/claimtrace/gui/static/app.js").read_text(encoding="utf-8")
    helpers = source[source.index("const esc ="):source.index("const icons =")]
    functions = source[source.index("function proposalClaimIds("):source.index("function auditFileSummary(")]
    setup = r'''
const assert = require("node:assert/strict");
const state = {mode: "simple", claimId: "claim:a", reviewer: "", data: {
  semantic: {claims: [{id: "claim:a"}, {id: "claim:b"}], artifacts: [{id: "artifact:1", path: "evidence/contacts.csv"}]}, proposals: [],
}};
const semantic = () => state.data.semantic;
const types = {ligand_binding_pose: "Ligand binding pose"}, evidenceKinds = {}, limitationCategories = {general: "General limitation"};
const icon = () => "";
const fileName = id => semantic().artifacts.find(a => a.id === id)?.path || id;
const fileChip = id => `<button data-file="${esc(id)}">${esc(fileName(id))}</button>`;
const fieldError = (message, field) => Object.assign(new Error(message), {field});
const proposal = {
 id: "proposal:1", title: "Qualify the pose interpretation", status: "pending", claim_id: "claim:a",
 actor: {name: "Scientific assistant", model: "model-x", version: "1"},
 rationale: "The supplied table records geometry.", source_artifact_ids: ["artifact:1"],
 changes: [{record_type: "claim", record_id: "claim:a", fields: {claim_text: "A geometric contact is shown.", scene_ids: ["scene:1"]}}],
 diff: [{record_type: "claim", record_id: "claim:a", field: "claim_text", label: "Figure statement", before: "The pose is validated.", after: "A geometric contact is shown."}],
};
'''
    result = subprocess.run([node, "-e", helpers + functions + setup + checks], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr


def test_proposals_are_scoped_to_claims_and_show_review_history():
    run_browser_functions(r'''
assert.equal(proposalSection(), "");
state.data.proposals = [proposal, {...proposal, id: "other", title: "Other claim update", claim_id: "claim:b", changes: []}];
let rendered = proposalSection();
assert.match(rendered, /Review suggestion/);
assert.match(rendered, /contacts.csv/);
assert.match(rendered, /Scientific assistant · model-x · 1/);
assert.doesNotMatch(rendered, /Other claim update/);
assert.match(proposalDiff(proposal), /The pose is validated./);
assert.match(proposalDiff(proposal), /A geometric contact is shown./);
state.data.proposals.push({...proposal, id: "new", title: "New claim proposal", claim_id: null, changes: [{record_type: "claim", record_id: "claim:new", fields: {}}]});
assert.match(proposalSection(), /New claim proposal/);
proposal.status = "rejected";
assert.match(proposalSection(), /Reviewed suggestions/);
assert.match(proposalSection(), /View decision/);
assert.match(proposalSection(), /Rejected/);
proposal.title = '<img src=x onerror="alert(1)">';
assert.doesNotMatch(proposalSection(), /<img/);
assert.match(proposalSection(), /&lt;img/);
''')


def test_revision_preserves_ids_and_types_without_mutating_original_proposal():
    run_browser_functions(r'''
const numeric = {...proposal, changes: [{record_type: "evidence", record_id: "evidence:1", claim_id: "claim:a", fields: {result_summary: "Old finding", distance: 4, enabled: true, optional: null, parameters: {atom: "A42"}}}]};
const initial = JSON.stringify(numeric);
let form = new Map([["proposal_0_result_summary", "Revised finding"], ["proposal_0_distance", "3.2"], ["proposal_0_enabled", "false"], ["proposal_0_optional", ""]]);
let result = proposalEdits(numeric, form);
assert.equal(result[0].record_id, "evidence:1");
assert.equal(result[0].claim_id, "claim:a");
assert.deepEqual(result[0].fields, {result_summary: "Revised finding", distance: 3.2, enabled: false, optional: null, parameters: {atom: "A42"}});
assert.equal(JSON.stringify(numeric), initial);
form.set("proposal_0_distance", "abc");
assert.throws(() => proposalEdits(numeric, form), e => e.field === "proposal_0_distance");
form.set("proposal_0_distance", "4");
form.set("proposal_0_parameters", "{broken");
assert.throws(() => proposalEdits(numeric, form), e => e.field === "proposal_0_parameters");
form.set("proposal_0_parameters", "[]");
assert.throws(() => proposalEdits(numeric, form), /same data format/);
''')


def test_review_requires_human_name_and_sends_explicit_accept_or_reject():
    run_browser_functions(r'''
let captured, request;
let dialogOpener;
const nodes = {"#dialog-form": {dataset: {}}, "#dialog-title": {focus() {}}, "#proposal-section-title": {}};
const $ = selector => nodes[selector];
const field = (label, name) => `<input name="${name}">`;
const textfield = (label, name) => `<textarea name="${name}"></textarea>`;
const formDialog = (title, subtitle, fields, submit, button) => { captured = {title, fields, submit, button}; };
const mutate = async (path, body) => { request = {path, body}; };
const toast = () => {};
const updateDetail = () => {};
state.data.proposals = [proposal];
(async () => {
 proposalReviewForm(proposal.id);
 assert.equal(captured.button, "Accept suggestion");
 await assert.rejects(captured.submit(new Map([["reviewer", " "]])), e => e.field === "reviewer");
 assert.equal(request, undefined);
 await captured.submit(new Map([["reviewer", "A. Reviewer"], ["review_note", "Checked source table."]]));
 assert.deepEqual(request, {path: "/api/proposal-review", body: {id: "proposal:1", decision: "accept", reviewer: "A. Reviewer", note: "Checked source table."}});
 nodes["#dialog-form"].dataset = {};
 proposalReviewForm(proposal.id, "reject");
 await captured.submit(new Map([["reviewer", "B. Reviewer"], ["review_note", "Scope needs another source."]]));
 assert.equal(request.body.decision, "reject");
 assert.equal(request.body.reviewer, "B. Reviewer");
 assert.equal(request.body.changes, undefined);
})().catch(error => {console.error(error); process.exitCode = 1;});
''')


def test_history_shows_the_accepted_revision_and_retains_original_values():
    run_browser_functions(r'''
proposal.status = "accepted";
proposal.accepted_diff = [{...proposal.diff[0], after: "A source-checked contact is shown."}];
let rendered = proposalDiff(proposal);
assert.match(rendered, /A source-checked contact is shown./);
assert.doesNotMatch(rendered, /A geometric contact is shown./);
assert.match(proposalDiff(proposal, true), /A geometric contact is shown./);
proposal.status = "reverted";
assert.match(proposalDiff(proposal), /Accepted, then reverted/);
state.mode = "simple";
assert.doesNotMatch(proposalValue({distance: 4, unit: "angstrom"}), /<pre/);
assert.match(proposalValue({distance: 4, unit: "angstrom"}), /<dt>distance<\/dt>/);
state.mode = "expert";
assert.match(proposalValue({distance: 4, unit: "angstrom"}), /<pre/);
''')


def test_pending_comparison_reads_current_record_and_retains_suggestion_baseline():
    run_browser_functions(r'''
semantic().claims[0].claim_text = {value: "A statement revised by its author."};
const rendered = proposalDiff(proposal);
assert.match(rendered, /A statement revised by its author./);
assert.match(rendered, /When suggested/);
assert.match(rendered, /The pose is validated./);
assert.match(rendered, /A geometric contact is shown./);
assert.deepEqual(proposal.diff[0].before, "The pose is validated.");
''')


def test_basic_revision_retains_custom_categories_and_keeps_structured_fields_for_expert():
    run_browser_functions(r'''
const nodes = {"#dialog-form": {dataset: {}}, "#dialog-title": {focus() {}}};
const $ = selector => nodes[selector];
const field = (label, name) => `<input name="${name}">`;
const textfield = (label, name) => `<textarea name="${name}"></textarea>`;
let rendered;
const formDialog = (title, subtitle, fields) => { rendered = fields; };
proposal.changes = [{record_type: "uncertainty", record_id: "uncertainty:1", fields: {category: "sampling_scope", statement: "One replicate is supplied.", alternative_explanations: ["Other runs may differ."]}}];
state.data.proposals = [proposal];
proposalReviewForm(proposal.id, "accept", true);
assert.match(rendered, /value="sampling_scope" selected/);
assert.match(rendered, /Additional fields are available in Expert mode/);
assert.doesNotMatch(rendered, /textarea name="proposal_0_alternative_explanations"/);
state.mode = "expert";
nodes["#dialog-form"].dataset = {};
proposalReviewForm(proposal.id, "accept", true);
assert.match(rendered, /textarea name="proposal_0_alternative_explanations"/);
assert.equal(proposalFieldValue({field: "claim_type"}, "ligand_binding_pose"), "Ligand binding pose");
''')
