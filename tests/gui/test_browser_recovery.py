"""Regression checks for interrupted browser editing and package navigation."""

import shutil
import subprocess
from pathlib import Path

import pytest


SOURCE = (Path(__file__).parents[2] / "src/claimtrace/gui/static/app.js").read_text(
    encoding="utf-8"
)


def run_browser_logic(source: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise browser recovery")
    result = subprocess.run(
        [node, "-e", source], capture_output=True, text=True, encoding="utf-8"
    )
    assert result.returncode == 0, result.stderr


def test_unsaved_form_requires_a_discard_decision_and_blocks_reload():
    values = SOURCE[SOURCE.index("let dialogInitialValues"):SOURCE.index("function dialog(")]
    close = SOURCE[SOURCE.index("function closeDialog("):SOURCE.index("const field =")]
    unload = SOURCE[SOURCE.index('window.addEventListener("beforeunload"'):SOURCE.index("(async () => {")]
    run_browser_logic(r'''
const assert = require("node:assert/strict");
const state = {busy:false};
const modal = {open:true,dataset:{},close(){this.open=false;}};
let fields = [["statement","Initial"],["sources","a"],["sources","b"]];
class File {constructor(name="",time=Date.now()){this.name=name;this.lastModified=time;this.size=0;}}
class FormData {constructor(){return [...fields,["file",new File("",++clock)]];}}
let clock=0, decision=false, prompts=0;
const form={};
const $ = selector => selector === "#dialog" ? modal : form;
const listeners={};
const window={confirm(){prompts++;return decision;},addEventListener(k,fn){listeners[k]=fn;}};
''' + values + close + unload + r'''
dialogInitialValues=dialogValues();
assert.equal(hasUnsavedDialog(),false); // Empty file inputs must not appear edited.
closeDialog(); assert.equal(modal.open,false); assert.equal(prompts,0);
modal.open=true; fields[0][1]="New observation";
closeDialog(); assert.equal(modal.open,true); assert.equal(prompts,1);
assert.equal(fields[0][1],"New observation");
let prevented=false;
const event={preventDefault(){prevented=true;}};
listeners.beforeunload(event); assert.equal(prevented,true); assert.equal(event.returnValue,"");
decision=true; state.busy=true; closeDialog(); assert.equal(modal.open,true);
state.busy=false; modal.dataset.submitting="true"; closeDialog(); assert.equal(modal.open,true);
delete modal.dataset.submitting; closeDialog(); assert.equal(modal.open,false);
prevented=false; listeners.beforeunload(event); assert.equal(prevented,false);
modal.open=true; fields[0][1]="Initial"; fields.pop();
assert.equal(hasUnsavedDialog(),true); // Selection-only edits are also protected.
''')


def test_browser_requests_keep_the_displayed_package_context():
    urls = SOURCE[SOURCE.index("const packageURL"):SOURCE.index("const claim =")]
    api = SOURCE[SOURCE.index("async function api("):SOURCE.index("function rememberView(")]
    run_browser_logic(r'''
const assert = require("node:assert/strict");
const state={data:{root:"/tmp/review A/图"}};
let request;
const fetch=async(path,options)=>{request={path,options};return {ok:true,json:async()=>({})};};
''' + urls + api + r'''
(async()=>{
const link=new URL(artifactURL("artifact:a",true),"http://localhost");
assert.equal(link.searchParams.get("package_root"),state.data.root);
assert.equal(link.searchParams.get("id"),"artifact:a");
assert.equal(link.searchParams.get("download"),"1");
await api("/api/claim",{claim_text:"Observation"});
assert.equal(JSON.parse(request.options.body).package_root,state.data.root);
await api("/api/answers?source=saved");
const answers=new URL(request.path,"http://localhost");
assert.equal(answers.searchParams.get("source"),"saved");
assert.equal(answers.searchParams.get("package_root"),state.data.root);
await api("/api/state");assert.equal(request.path,"/api/state");
})().catch(error=>{console.error(error);process.exitCode=1;});
''')


def test_mobile_claim_selection_returns_from_export_to_the_chosen_record():
    handler = SOURCE[SOURCE.index('  if (event.target.id === "mobile-claim-select")'):
                     SOURCE.index('  if (event.target.id === "import-files")')]
    run_browser_logic(r'''
const assert=require("node:assert/strict");
const state={view:"export",claimId:"a"};
let focused=false, renders=0;
const $=()=>({focus(){focused=true;}});
const updateDetail=()=>{renders++;};
function change(value){const event={target:{id:"mobile-claim-select",value}};
''' + handler + r'''
}
change("b");assert.equal(state.claimId,"b");assert.equal(state.view,"review");
assert.equal(focused,true);assert.equal(renders,1);
state.view="prepare";change("a");assert.equal(state.view,"prepare");
state.view="export";change("");assert.equal(state.claimId,null);assert.equal(state.view,"prepare");
''')
