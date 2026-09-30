"""Saved v2 reports resume only after lossless, assignment-bound validation."""

import importlib
import importlib.util
import json
import shutil
import subprocess
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def ui_helpers():
    spec = importlib.util.spec_from_file_location(
        "frozen_incident_ui_tests", ROOT / "tests/test_operator_incident_report.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=["incident", "adjudication"])
def pair(request):
    helpers = ui_helpers()
    incident = helpers.incident.__wrapped__()
    value = incident if request.param == "incident" else helpers.adjudication.__wrapped__(incident)
    return request.param, value


class Controls(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.controls, self.finding, self.current, self.in_template = [], [], None, False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "template":
            self.in_template = True
        if tag in ("input", "textarea", "select"):
            record = {
                "id": attrs.get("id"),
                "field": attrs.get("data-field"),
                "tag": tag.upper(),
                "value": attrs.get("value", ""),
                "options": [],
            }
            if self.in_template and record["field"]:
                self.finding.append(record)
            elif record["id"]:
                self.controls.append(record)
            self.current = record if tag != "input" else None
        if tag == "option" and self.current:
            self.current["options"].append(attrs.get("value", ""))
            if len(self.current["options"]) == 1:
                self.current["value"] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "template":
            self.in_template = False
        if tag in ("textarea", "select"):
            self.current = None

    def handle_data(self, value):
        if self.current and self.current["tag"] == "TEXTAREA":
            self.current["value"] += value


HARNESS = r"""
const fs=require('node:fs'),
vm=require('node:vm');
const p=JSON.parse(fs.readFileSync(0,
'utf8'));
let changes=0,
failOnce=null;
class Field {
  constructor(d,
  attached=true){
    this.id=d.id;
    this.dataset={
      field:d.field
    }
    ;
    this.tagName=d.tag;
    this.options=d.options.map(value=>({
      value
    }
    ));
    this._value=d.value;
    this.attached=attached;
    this.listeners={
    }
    ;
    this.handlers={};
    this.disabled=false;
    this.textContent='';
    this.files=[];
  }
  get value(){
    return this._value;
  }
  set value(v){
    if(failOnce!==null&&this.id===failOnce){
      failOnce=null;
      throw Error('Injected setter failure');
    }
    if(this.attached)changes++;
    this._value=this.tagName==='SELECT'&&!this.options.some(x=>x.value===v)?'':v;
  }
  addEventListener(name,
  fn,options){
    if(!this.handlers[name])this.handlers[name]=[];
    this.handlers[name].push({fn,capture:options===true||Boolean(options&&options.capture)});
    this.listeners[name]=()=>{
      let result;
      for(const handler of [...this.handlers[name]].sort((a,b)=>Number(b.capture)-Number(a.capture)))
        result=handler.fn();
      return result;
    };
  }
}
class Finding {
  constructor(){
    this.fields=Object.fromEntries(p.finding.map(x=>[x.field,
    new Field(x,
    false)]));
    this.removeButton={
      addEventListener:(name,
      fn)=>{
        this.removeHandler=fn;
      }
    }
    ;
    this.parent=null;
  }
  querySelector(q){
    const m=q.match(/^\[data-field="(.+)"\]$/);
    if(m)return this.fields[m[1]];
    if(q==='[data-remove-finding]')return this.removeButton;
    if(q==='[data-finding]')return this;
    return null;
  }
  querySelectorAll(q){
    return q==='[data-field]'?Object.values(this.fields):[];
  }
  remove(){
    if(this.parent)this.parent.replaceChildren(...this.parent.children.filter(x=>x!==this));
  }
}
class Fragment {
  constructor(){
    this.node=new Finding();
  }
  querySelector(q){
    return this.node.querySelector(q);
  }
}
class Container {
  constructor(){
    this.children=[];
  }
  get childNodes(){
    return this.children;
  }
  querySelectorAll(q){
    return q==='[data-finding]'?this.children:[];
  }
  replaceChildren(...nodes){
    changes++;
    for(const n of this.children){
      n.parent=null;
      Object.values(n.fields).forEach(x=>x.attached=false);
    }
    this.children=[];
    for(const node of nodes){
      const n=node.node||node;
      n.parent=this;
      Object.values(n.fields).forEach(x=>x.attached=true);
      this.children.push(n);
    }
  }
  appendChild(node){
    this.replaceChildren(...this.children,
    node);
  }
}
const ids=Object.fromEntries(p.controls.map(x=>[x.id,
new Field(x)]));
for(let i=0;
i<p.packet.cases.length;
i++){
  ids['findings-'+i]=new Container();
  ids['finding-template-'+i]={
    content:{
      cloneNode(){
        return new Fragment();
      }
    }
  }
  ;
}
for(const id of ['draft-file',
'draft-preview',
'draft-apply',
'draft-cancel',
'draft-undo',
'draft-status',
'download-response',
'export-status'])ids[id]=new Field({
  id,
  tag:'BUTTON',
  value:'',
  options:[]
}
);
ids['incident-packet']={
  textContent:JSON.stringify(p.packet)
}
;
ids['incident-template']={
  textContent:JSON.stringify(p.template)
}
;
const addButtons=[];
if(p.packet.presentation){
  for(let i=0;i<p.packet.cases.length;i++){
    const button=new Field({id:'add-finding-'+i,tag:'BUTTON',value:'',options:[]});
    button.dataset.addFinding=String(i);ids[button.id]=button;addButtons.push(button);
  }
}
const document={
  getElementById(id){
    return ids[id]||null;
  }
  ,
  querySelectorAll(selector){
    return selector==='[data-add-finding]'?addButtons:[];
  }
}
;
const c={
  document,
  console,
  raw:p.raw,
  ids,
  setFailure(id){
    failOnce=id;
  }
  ,
  mutationCount(){
    return changes;
  }
  ,
  resetMutations(){
    changes=0;
  }
}
;
vm.createContext(c);
vm.runInContext(p.original,
c);
vm.runInContext(p.drafts,
c);
changes=0;
(async()=>{
  try{
    const result=await vm.runInContext(p.action,
    c);
    process.stdout.write(JSON.stringify({
      result,
      changes
    }
    ));
  }
  catch(e){
    process.stdout.write(JSON.stringify({
      error:e.message,
      changes
    }
    ));
  }
}
)();
"""


def run_js(pair, value, action):
    node = shutil.which("node")
    if not node:
        pytest.skip("Existing local Node runtime needed for offline JS checks")
    mode, (packet, template) = pair
    renderer = importlib.import_module("healthcraft.operator_incident_report")
    drafts = importlib.import_module("healthcraft.operator_workbench_drafts")
    html = getattr(renderer, f"render_{mode}_packet")(packet, template)
    controls = Controls(html)
    result = subprocess.run(
        [node, "-e", HARNESS],
        input=json.dumps(
            {
                "packet": packet,
                "template": template,
                "controls": controls.controls,
                "finding": controls.finding,
                "original": renderer._SCRIPT,
                "drafts": drafts.SCRIPT,
                "raw": value if isinstance(value, str) else json.dumps(value),
                "action": action,
            }
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def exported(pair):
    return deepcopy(pair[1][1])


def export_expression(pair):
    return (
        "buildIncidentResponse(readIncidentForm(),responseTemplate,packet)"
        if pair[0] == "incident"
        else "buildAdjudicationResponse(readAdjudicationForm(),responseTemplate,packet)"
    )


def test_preview_does_not_change_forms_and_apply_roundtrips_pending_work(pair):
    value = exported(pair)
    row = value["cases"][0]
    if pair[0] == "incident":
        row["identified_target"]["patient_id"] = "PAT-partial"
        row["incident_assessment"]["summary"] = "Unfinished source review — no conclusion"
        row["timing"] = {
            "method": "self_reported",
            "elapsed_seconds": None,
            "active_seconds": 2.5,
            "note": "partial",
        }
    else:
        row["checks"][0]["rationale"] = "Unfinished adjudication"
        value["reviewer_declaration"]["qualifications"] = "Self-declared details"
        value["reviewer_declaration"]["independent_review"] = False
    action = """
(()=>{
  const preview=HealthcraftDrafts.preview(raw);
  const before=mutationCount();
  HealthcraftDrafts.apply();
  return {
    preview,
    before,
    exported:EXPORT,
    state:HealthcraftDrafts.state()
  }
  ;
}
)()
""".replace("EXPORT", export_expression(pair))
    result = run_js(pair, value, action)
    assert "error" not in result
    assert result["result"]["before"] == 0
    assert result["result"]["exported"] == value
    assert result["result"]["state"]["can_undo"] is True


@pytest.mark.parametrize(
    "fault",
    [
        "packet",
        "assignment",
        "role",
        "extra",
        "missing_case",
        "duplicate_case",
        "extra_nested",
        "unavailable_ref",
        "duplicate_key",
    ],
)
def test_invalid_or_foreign_saved_response_cannot_mutate_form(pair, fault):
    value = exported(pair)
    if fault == "packet":
        value["packet_sha256"] = "b" * 64
    elif fault == "assignment":
        value["assignment_id"] = "someone-else"
    elif fault == "role":
        value["role"] = "resolver" if pair[0] == "incident" else "other"
    elif fault == "extra":
        value["unexpected"] = "not dropped"
    elif fault == "missing_case":
        value["cases"] = []
    elif fault == "duplicate_case":
        value["cases"].append(deepcopy(value["cases"][0]))
    elif fault == "extra_nested":
        value["cases"][0]["unexpected"] = "not dropped"
    elif fault == "unavailable_ref":
        key = "axes" if pair[0] == "incident" else "checks"
        value["cases"][0][key][0]["evidence_refs"] = [{"document": "runtime", "pointer": ""}]
    elif fault == "duplicate_key":
        value = '{"packet_id":"duplicate",' + json.dumps(value)[1:]
    result = run_js(
        pair,
        value,
        """
(()=>{
  let message;
  try{
    HealthcraftDrafts.preview(raw);
  }
  catch(e){
    message=e.message;
  }
  return {
    message,
    state:HealthcraftDrafts.state(),
    changes:mutationCount()
  }
  ;
}
)()
""",
    )
    assert result["result"]["message"]
    assert result["result"]["changes"] == 0
    assert result["result"]["state"]["pending"] is False


def test_cancel_and_undo_preserve_malformed_existing_textarea(pair):
    field = "case-0-axis-0-refs" if pair[0] == "incident" else "case-0-check-0-refs"
    action = """
(()=>{
  ids['FIELD'].value='not JSON, unfinished';
  resetMutations();
  HealthcraftDrafts.preview(raw);
  HealthcraftDrafts.cancel();
  const cancelled=ids['FIELD'].value;
  HealthcraftDrafts.preview(raw);
  HealthcraftDrafts.apply();
  HealthcraftDrafts.undo();
  return {
    cancelled,
    restored:ids['FIELD'].value,
    state:HealthcraftDrafts.state()
  }
  ;
}
)()
""".replace("FIELD", field)
    result = run_js(pair, exported(pair), action)
    assert "error" not in result
    assert result["result"]["cancelled"] == result["result"]["restored"] == "not JSON, unfinished"
    assert result["result"]["state"]["can_undo"] is False


def test_missing_dom_field_is_rejected_before_any_form_change(pair):
    field = "case-0-timing-note" if pair[0] == "incident" else "declaration-conflicts"
    result = run_js(
        pair,
        exported(pair),
        """
(()=>{
  HealthcraftDrafts.preview(raw);
  delete ids['FIELD'];
  try{
    HealthcraftDrafts.apply();
  }
  catch(e){
    return {
      error:e.message,
      changes:mutationCount()
    }
    ;
  }
}
)()
""".replace("FIELD", field),
    )
    assert result["result"]["error"]
    assert result["result"]["changes"] == 0


def test_apply_failure_rolls_back_previous_raw_state(pair):
    field = "case-0-timing-note" if pair[0] == "incident" else "declaration-conflicts"
    first = "case-0-target-patient" if pair[0] == "incident" else "case-0-check-0-rationale"
    result = run_js(
        pair,
        exported(pair),
        """
(()=>{
  ids['FIRST'].value='existing unsaved text';
  HealthcraftDrafts.preview(raw);
  setFailure('FIELD');
  let error;
  try{
    HealthcraftDrafts.apply();
  }
  catch(e){
    error=e.message;
  }
  return {
    error,
    restored:ids['FIRST'].value
  }
  ;
}
)()
""".replace("FIELD", field).replace("FIRST", first),
    )
    assert result["result"]["error"]
    assert result["result"]["restored"] == "existing unsaved text"


def test_raw_draft_findings_and_references_roundtrip_without_inferred_status():
    helpers = ui_helpers()
    pair = ("incident", helpers.incident.__wrapped__())
    value = exported(pair)
    value["cases"][0]["incident_assessment"]["findings"] = [
        {
            "finding_id": "finding-8",
            "category": "source_uncertainty",
            "claim": "Draft only",
            "observed_target": {"patient_id": None, "encounter_id": "ENC-draft"},
            "source_ids": ["SRC-1"],
            "evidence_refs": [
                {
                    "document": "evidence",
                    "pointer": "/note",
                    "decoded_json_pointer": "/nested/unknown",
                }
            ],
        }
    ]
    action = """
(()=>{
  HealthcraftDrafts.preview(raw);
  HealthcraftDrafts.apply();
  const result=EXPORT;
  const count=findingCounters[0];
  HealthcraftDrafts.undo();
  return {
    result,
    count,
    findings:ids['findings-0'].children.length
  }
  ;
}
)()
""".replace("EXPORT", export_expression(pair))
    result = run_js(pair, value, action)
    assert result["result"]["result"] == value
    assert result["result"]["count"] >= 8
    assert result["result"]["findings"] == 0


@pytest.mark.parametrize(
    "literal", ["9007199254740993", "1e20", "0.100000000000000000001", "1e-400"]
)
def test_lossy_numeric_tokens_reject_before_dom_mutation(literal):
    pair = ("incident", ui_helpers().incident.__wrapped__())
    raw = json.dumps(exported(pair)).replace(
        '"elapsed_seconds": null', '"elapsed_seconds": ' + literal
    )
    result = run_js(
        pair,
        raw,
        """
(()=>{
  try{
    HealthcraftDrafts.preview(raw);
  }
  catch(e){
    return {
      error:e.message,
      changes:mutationCount()
    }
    ;
  }
}
)()
""",
    )
    assert "exactly" in result["result"]["error"]
    assert result["result"]["changes"] == 0


def test_exact_numeric_exponent_and_numeric_looking_text_are_preserved():
    pair = ("incident", ui_helpers().incident.__wrapped__())
    value = exported(pair)
    value["cases"][0]["timing"].update(
        method="self_reported", elapsed_seconds=0.001, note="9007199254740993"
    )
    raw = json.dumps(value).replace('"elapsed_seconds": 0.001', '"elapsed_seconds": 1e-3')
    result = run_js(
        pair,
        raw,
        """
(()=>{
  HealthcraftDrafts.preview(raw);
  HealthcraftDrafts.apply();
  return buildIncidentResponse(readIncidentForm(),
  responseTemplate,
  packet);
}
)()
""",
    )
    assert result["result"] == value


def test_cancel_discards_an_inflight_file_read_without_late_application(pair):
    result = run_js(
        pair,
        exported(pair),
        """
(async()=>{
  let release;
  ids['draft-file'].files=[{
    text(){
      return new Promise(resolve=>release=resolve);
    }
  }
  ];
  const reading=ids['draft-preview'].listeners.click();
  HealthcraftDrafts.cancel();
  release(raw);
  await reading;
  return {
    state:HealthcraftDrafts.state(),
    changes:mutationCount()
  }
  ;
}
)()
""",
    )
    assert result["result"]["state"]["pending"] is False
    assert result["result"]["changes"] == 0


def test_cancel_discards_an_inflight_file_error_without_overwriting_status(pair):
    result = run_js(
        pair,
        exported(pair),
        """(async()=>{let reject;ids['draft-file'].files=[{text(){return new Promise((resolve,fail)=>reject=fail);}}];
const reading=ids['draft-preview'].listeners.click();ids['draft-cancel'].listeners.click();const status=ids['draft-status'].textContent;
reject(new Error('old file read failed'));await reading;return {status,final:ids['draft-status'].textContent,changes:mutationCount()};})()""",
    )
    assert result["result"]["status"] == result["result"]["final"]
    assert result["result"]["changes"] == 0


def test_undo_restores_original_finding_nodes_and_unfinished_text():
    pair = ("incident", ui_helpers().incident.__wrapped__())
    result = run_js(
        pair,
        exported(pair),
        """(()=>{
const fragment=ids['finding-template-0'].content.cloneNode(true);
const original=fragment.querySelector('[data-finding]');
original.querySelector('[data-field="source_ids"]').value='unfinished [';
ids['findings-0'].appendChild(fragment);
HealthcraftDrafts.preview(raw);HealthcraftDrafts.apply();HealthcraftDrafts.undo();
return {same_node:ids['findings-0'].children[0]===original,
raw:original.querySelector('[data-field="source_ids"]').value};
})()""",
    )
    assert result["result"] == {"same_node": True, "raw": "unfinished ["}


def test_unpaired_surrogate_text_cannot_load_as_utf8_response(pair):
    value = exported(pair)
    key = "axes" if pair[0] == "incident" else "checks"
    value["cases"][0][key][0]["rationale"] = "invalid \ud800 text"
    result = run_js(
        pair,
        value,
        """(()=>{
try {HealthcraftDrafts.preview(raw);}catch(e){return {error:e.message,changes:mutationCount()};}
})()""",
    )
    assert result.get("result", {}).get("error")
    assert result["result"]["changes"] == 0


@pytest.mark.parametrize(
    "identifiers",
    [
        ["finding-9007199254740991"],
        ["finding-9007199254740992"],
        ["finding-8"],
        ["finding-1", "finding-3", "FINDING-4"],
    ],
)
def test_loaded_ids_survive_two_real_add_clicks_without_collision(identifiers):
    pair = ("incident", ui_helpers().incident.__wrapped__())
    value = exported(pair)
    value["cases"][0]["incident_assessment"]["findings"] = [
        {
            "finding_id": identifier,
            "category": "source_uncertainty",
            "claim": "Original draft",
            "observed_target": {"patient_id": None, "encounter_id": None},
            "source_ids": [],
            "evidence_refs": [],
        }
        for identifier in identifiers
    ]
    action = """(()=>{
HealthcraftDrafts.preview(raw);HealthcraftDrafts.apply();
for(let i=0;i<2;i++){
  ids['add-finding-0'].listeners.click();
  const node=ids['findings-0'].children.at(-1);
  node.querySelector('[data-field="category"]').value='source_uncertainty';
  node.querySelector('[data-field="claim"]').value='New draft';
}
return buildIncidentResponse(readIncidentForm(),responseTemplate,packet);
})()"""
    result = run_js(pair, value, action)
    assert "error" not in result, result
    findings = result["result"]["cases"][0]["incident_assessment"]["findings"]
    assert findings[: len(identifiers)] == value["cases"][0]["incident_assessment"]["findings"]
    assert len({row["finding_id"].casefold() for row in findings}) == len(identifiers) + 2
