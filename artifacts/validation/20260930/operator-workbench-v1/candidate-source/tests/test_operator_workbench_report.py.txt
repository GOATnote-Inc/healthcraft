"""Lazy workbench sources retain exact evidence without eagerly expanding it."""

import importlib
import importlib.util
import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest


@pytest.fixture
def examples():
    path = Path(__file__).with_name("test_operator_incident_report.py")
    spec = importlib.util.spec_from_file_location("workbench_examples", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def incident(examples):
    return examples.incident.__wrapped__()


@pytest.fixture
def adjudication(examples, incident):
    return examples.adjudication.__wrapped__(incident)


def render(pair):
    return importlib.import_module("healthcraft.operator_workbench_report").render_workbench(*pair)


def node_inspect(pair, refs, tmp_path, examples):
    node = shutil.which("node")
    if not node:
        pytest.skip("Installed Node required for offline source-inspector contracts")
    page = examples.Page(render(pair))
    script = page.scripts["workbench-sources"]
    (tmp_path / "sources.js").write_text(script)
    subprocess.run([node, "--check", str(tmp_path / "sources.js")], check=True, capture_output=True)
    harness = r"""
const fs=require('node:fs'),vm=require('node:vm'),p=JSON.parse(fs.readFileSync(0,'utf8'));
const c={document:{getElementById(id){return {textContent:id==='incident-packet'?p.packet_text:p.template_text,addEventListener(){}};},querySelectorAll(){return [];}}};
vm.createContext(c);vm.runInContext(p.base,c);vm.runInContext(p.script,c);
const results=p.refs.map(r=>{try{return c.HealthcraftSources.inspect(...r);}catch(e){return {error:e.message};}});
process.stdout.write(JSON.stringify(results));
"""
    proc = subprocess.run(
        [node, "-e", harness],
        check=True,
        capture_output=True,
        text=True,
        input=json.dumps(
            {
                "packet_text": page.scripts["incident-packet"],
                "template_text": page.scripts["incident-template"],
                "base": page.scripts["incident-app"],
                "script": script,
                "refs": refs,
            }
        ),
    )
    return json.loads(proc.stdout)


def test_initial_source_markup_is_bounded_and_packet_unchanged(incident, examples):
    before = deepcopy(incident)
    page = examples.Page(render(incident))
    assert not any(a.get("class") == "source-node" for _, a in page.tags)
    assert json.loads(page.scripts["incident-packet"]) == before[0]
    assert json.loads(page.scripts["incident-template"]) == before[1]
    assert len(page.tags) < 600
    assert len([1 for _, a in page.tags if "data-source-document" in a]) == 4
    assert all(
        f"draft-{name}" in render(incident)
        for name in ("file", "preview", "apply", "cancel", "undo", "status")
    )
    assert incident == before


def test_all_lexemes_and_pointer_values_stay_exact(incident, examples, tmp_path):
    packet, template = incident
    docs = packet["cases"][0]["documents"]
    docs["scenario"].update(
        big=90071992547409931234567890, negative_zero=-0.0, array=list(range(123))
    )
    docs["evidence"]["note"] = (
        '{"n":90071992547409931234567891,"decimal":0.10000000000000001,"nil":null}'
    )
    for key in ("scenario", "evidence"):
        packet["cases"][0]["availability"][key]["sha256"] = examples.digest(docs[key])
    template["packet_sha256"] = examples.digest(packet)
    refs = [
        [0, {"document": "scenario", "pointer": "/big"}],
        [0, {"document": "scenario", "pointer": "/negative_zero"}],
        [0, {"document": "evidence", "pointer": "/note", "decoded_json_pointer": "/n"}],
        [0, {"document": "evidence", "pointer": "/note", "decoded_json_pointer": "/decimal"}],
        [0, {"document": "scenario", "pointer": "/nested/a~1b~0c/1/literal"}],
        [0, {"document": "scenario", "pointer": "/array"}, 50],
    ]
    rows = node_inspect(incident, refs, tmp_path, examples)
    assert [r["display"] for r in rows[:4]] == [
        "90071992547409931234567890",
        "-0.0",
        "90071992547409931234567891",
        "0.10000000000000001",
    ]
    assert rows[4]["display"] == "é\nline"
    assert rows[5]["total_children"] == 123 and len(rows[5]["children"]) == 50
    assert rows[5]["children"][0]["reference"]["pointer"] == "/array/50"
    assert rows[5]["children"][-1]["reference"]["pointer"] == "/array/99"
    assert rows[2]["raw_text"] == docs["evidence"]["note"]


@pytest.mark.parametrize(
    "pointer", ["/missing", "/nested/a~1b~0c/00", "/nested/a~1b~0c/0\n", "\n", "/bad~2key"]
)
def test_invalid_or_missing_reference_never_becomes_null(incident, examples, tmp_path, pointer):
    row = node_inspect(
        incident, [[0, {"document": "scenario", "pointer": pointer}]], tmp_path, examples
    )[0]
    assert "error" in row or row["status"] == "unavailable"
    assert row.get("display") != "null"


def test_missing_document_null_and_bad_decoded_json_stay_distinct(incident, examples, tmp_path):
    refs = [
        [0, {"document": "runtime", "pointer": ""}],
        [0, {"document": "scenario", "pointer": "/nested/a~1b~0c/0"}],
        [0, {"document": "evidence", "pointer": "/bad_note", "decoded_json_pointer": "/x"}],
    ]
    missing, null, invalid = node_inspect(incident, refs, tmp_path, examples)
    assert missing["status"] == "unavailable" and missing["reason"] == "Not captured"
    assert null["status"] == "available" and null["display"] == "null"
    assert invalid["status"] == "unavailable" and "Duplicate" in invalid["reason"]
    assert invalid["raw_text"] == '{"x":1,"x":2}'


@pytest.mark.parametrize(
    "raw", ['{"n":NaN}', '{"n":Infinity}', '{"n":1e400}', '{"a":1,"\\u0061":2}']
)
def test_decoded_json_rejects_invalid_values_without_repair(incident, examples, tmp_path, raw):
    packet, template = incident
    packet["cases"][0]["documents"]["evidence"]["bad_note"] = raw
    packet["cases"][0]["availability"]["evidence"]["sha256"] = examples.digest(
        packet["cases"][0]["documents"]["evidence"]
    )
    template["packet_sha256"] = examples.digest(packet)
    row = node_inspect(
        incident,
        [[0, {"document": "evidence", "pointer": "/bad_note", "decoded_json_pointer": ""}]],
        tmp_path,
        examples,
    )[0]
    assert row["status"] == "unavailable" and row["raw_text"] == raw


def test_adjudication_and_canonical_reload_have_exact_forms(adjudication, examples):
    page = examples.Page(render(adjudication))
    assert json.loads(page.scripts["incident-template"]) == adjudication[1]
    assert [
        a["id"] for tag, a in page.tags if tag == "select" and a.get("id", "").endswith("-judgment")
    ] == [f"case-0-check-{i}-judgment" for i in range(4)]
    reordered = tuple(json.loads(json.dumps(v, sort_keys=True)) for v in adjudication)
    assert render(adjudication) == render(reordered)


def test_response_namespace_cannot_offer_unrepresentable_decoded_citation(
    adjudication, examples, tmp_path
):
    packet, template = adjudication
    raw = '{"result":"displayed nested claim"}'
    packet["cases"][0]["documents"]["response"]["incident_assessment"]["summary"] = raw
    template["packet_sha256"] = examples.digest(packet)
    pointer = "/incident_assessment/summary"
    rows = node_inspect(
        adjudication,
        [
            [0, {"document": "response", "pointer": pointer}],
            [0, {"document": "response", "pointer": pointer, "decoded_json_pointer": "/result"}],
            [0, {"document": "response", "pointer": pointer, "decoded_json_pointer": ""}],
        ],
        tmp_path,
        examples,
    )
    assert rows[0]["status"] == "available" and rows[0]["display"] == raw
    assert all("Response references cannot decode JSON" in row.get("error", "") for row in rows[1:])


def test_untrusted_source_text_cannot_create_markup(incident, examples):
    packet, template = incident
    packet["cases"][0]["documents"]["scenario"]["payload"] = "</script><img src=x onerror=alert(1)>"
    packet["cases"][0]["availability"]["scenario"]["sha256"] = examples.digest(
        packet["cases"][0]["documents"]["scenario"]
    )
    template["packet_sha256"] = examples.digest(packet)
    page = examples.Page(render(incident))
    assert not any(tag in {"img", "iframe", "link"} or "src" in a for tag, a in page.tags)
    assert json.loads(page.scripts["incident-packet"]) == packet


def test_public_model_capture_scale_and_every_assisted_reference(tmp_path, examples):
    base = Path(__file__).resolve().parents[1] / "artifacts/operator-review/20260930/incidents-v2"
    for label in ("native-raw", "native-assisted", "model-raw", "model-assisted"):
        public = base / label / "public"
        original = {
            name: (public / name).read_bytes()
            for name in ("packet.json", "response-template.json", "report.html")
        }
        pair = (json.loads(original["packet.json"]), json.loads(original["response-template.json"]))
        html = render(pair)
        page = examples.Page(html)
        assert len(page.tags) < 2000
        assert len(html.encode()) < len(original["report.html"]) * 0.4
        assert len([1 for _, a in page.tags if "data-source-document" in a]) == 4 * len(
            pair[0]["cases"]
        )
        assert json.loads(page.scripts["incident-packet"]) == pair[0]
        assert json.loads(page.scripts["incident-template"]) == pair[1]
        refs = []
        for index, case in enumerate(pair[0]["cases"]):
            for claim in (case.get("assistance") or {}).get("claims", []):
                refs.extend([index, ref] for ref in claim["refs"])
        if refs:
            rows = node_inspect(pair, refs, tmp_path, examples)
            assert all(row.get("status") == "available" for row in rows)
            assert [row["reference"] for row in rows] == [ref for _, ref in refs]
        assert original == {name: (public / name).read_bytes() for name in original}


def test_inspector_links_pages_and_literal_dom_are_not_eager(incident, examples, tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Installed Node required for offline inspector DOM contracts")
    packet, template = incident
    packet["cases"][0]["documents"]["scenario"]["many"] = list(range(125))
    packet["cases"][0]["availability"]["scenario"]["sha256"] = examples.digest(
        packet["cases"][0]["documents"]["scenario"]
    )
    template["packet_sha256"] = examples.digest(packet)
    page = examples.Page(render(incident))
    harness = r"""
const fs=require('node:fs'),vm=require('node:vm'),p=JSON.parse(fs.readFileSync(0,'utf8'));
const nodes={};
function element(tag){return {tagName:tag,children:[],listeners:{},textContent:'',value:'',hidden:false,
 appendChild(n){this.children.push(n);},replaceChildren(...items){this.children=items;},
 addEventListener(k,fn){this.listeners[k]=fn;}};}
for(const [tag,attrs] of p.tags)if(attrs.id)nodes[attrs.id]=element(tag);
nodes['incident-packet'].textContent=p.packet_text;
nodes['incident-template'].textContent=p.template_text;
const openButton=element('button');openButton.dataset={sourceOpen:'0'};
const c={document:{getElementById(id){if(!nodes[id])throw Error('Missing '+id);return nodes[id];},
 querySelectorAll(selector){return selector==='[data-source-open]'?[openButton]:[];},
 createElement:element}};
vm.createContext(c);vm.runInContext(p.base,c);vm.runInContext(p.script,c);
const ref={document:'scenario',pointer:'/many'};
c.HealthcraftSources.open(0,ref);
const result={first:nodes['source-0-children'].children.length};
const next=nodes['source-0-context'].children.find(n=>n.textContent==='Next children');
next.listeners.click();result.second=nodes['source-0-children'].children.length;
result.second_label=nodes['source-0-children'].children[0].children[0].textContent;
nodes['source-0-children'].children[0].children[0].listeners.click();
result.value=nodes['source-0-value'].textContent;result.citation=nodes['source-0-citation'].value;
c.HealthcraftSources.open(0,{document:'scenario',pointer:'/nested/a~1b~0c/1/literal'});
result.literal=nodes['source-0-value'].textContent;
c.HealthcraftSources.open(0,{document:'evidence',pointer:'/bad_note',decoded_json_pointer:'/x'});
result.raw=nodes['source-0-raw'].textContent;result.status=nodes['source-0-status'].textContent;
result.children_after_error=nodes['source-0-children'].children.length;
nodes['source-0-query'].value='{';openButton.listeners.click();
result.invalid_query={raw:nodes['source-0-raw'].textContent,
 citation:nodes['source-0-citation'].value,query:nodes['source-0-query'].value};
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        check=True,
        capture_output=True,
        text=True,
        input=json.dumps(
            {
                "tags": page.tags,
                "packet_text": page.scripts["incident-packet"],
                "template_text": page.scripts["incident-template"],
                "base": page.scripts["incident-app"],
                "script": page.scripts["workbench-sources"],
            }
        ),
    )
    result = json.loads(completed.stdout)
    assert result["first"] == result["second"] == 50
    assert result["second_label"] == "50 · number" and result["value"] == "50"
    assert json.loads(result["citation"]) == {"document": "scenario", "pointer": "/many/50"}
    assert result["literal"] == "é\nline"
    assert result["raw"] == '{"x":1,"x":2}' and "Duplicate" in result["status"]
    assert result["children_after_error"] == 0
    assert result["invalid_query"] == {"raw": "", "citation": "", "query": "{"}


def test_exact_owned_keys_and_parent_context(incident, examples, tmp_path):
    packet, template = incident
    packet["cases"][0]["documents"]["scenario"]["keys"] = {
        "": "empty",
        "0": "numeric member",
        "a/b~c": None,
        "line\n": "newline member",
        "__proto__": {"constructor": "owned value"},
    }
    packet["cases"][0]["availability"]["scenario"]["sha256"] = examples.digest(
        packet["cases"][0]["documents"]["scenario"]
    )
    template["packet_sha256"] = examples.digest(packet)
    pointers = ["/keys/", "/keys/0", "/keys/a~1b~0c", "/keys/line\n", "/keys/__proto__/constructor"]
    rows = node_inspect(
        incident,
        [[0, {"document": "scenario", "pointer": p}] for p in pointers],
        tmp_path,
        examples,
    )
    assert [row["display"] for row in rows] == [
        "empty",
        "numeric member",
        "null",
        "newline member",
        "owned value",
    ]
    assert rows[-1]["parent_reference"] == {"document": "scenario", "pointer": "/keys/__proto__"}
    decoded = node_inspect(
        incident,
        [[0, {"document": "evidence", "pointer": "/note", "decoded_json_pointer": ""}]],
        tmp_path,
        examples,
    )[0]
    assert decoded["parent_reference"] == {"document": "evidence", "pointer": "/note"}


@pytest.mark.parametrize("mode", ["incident", "adjudication"])
def test_actual_workbench_scripts_resume_and_export_original_schema(
    incident, adjudication, examples, tmp_path, mode
):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Installed Node required for offline full-script checks")
    path = Path(__file__).with_name("test_operator_workbench_drafts.py")
    spec = importlib.util.spec_from_file_location("workbench_draft_test_controls", path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    pair = incident if mode == "incident" else adjudication
    page = examples.Page(render(pair))
    controls = helper.Controls(render(pair))
    response = deepcopy(pair[1])
    if mode == "incident":
        response["cases"][0]["identified_target"]["patient_id"] = "pending-operator-text"
        response["cases"][0]["timing"].update(
            method="self_reported", elapsed_seconds=12.5, note="Synthetic test only"
        )
    else:
        response["cases"][0]["checks"][0]["rationale"] = "Unfinished synthetic test draft"
        response["reviewer_declaration"]["independent_review"] = False
    export = helper.export_expression((mode, pair))
    action = (
        "(()=>{const before="
        + export
        + ";HealthcraftDrafts.preview(raw);const preview="
        + export
        + ";HealthcraftDrafts.apply();const after="
        + export
        + ";HealthcraftDrafts.undo();return {before,preview,after,undone:"
        + export
        + "};})()"
    )
    proc = subprocess.run(
        [node, "-e", helper.HARNESS],
        check=True,
        capture_output=True,
        text=True,
        input=json.dumps(
            {
                "packet": pair[0],
                "template": pair[1],
                "controls": controls.controls,
                "finding": controls.finding,
                "original": page.scripts["incident-app"] + "\n" + page.scripts["workbench-sources"],
                "drafts": page.scripts["workbench-drafts"],
                "raw": json.dumps(response),
                "action": action,
            }
        ),
    )
    result = json.loads(proc.stdout)["result"]
    assert result["before"] == result["preview"] == result["undone"] == pair[1]
    assert result["after"] == response
    if mode == "incident":
        from healthcraft.operator_incidents import validate_incident_response

        assert validate_incident_response(result["after"], pair[0])["case-1"]["status"] == "pending"
    else:
        from healthcraft.operator_adjudication import validate_adjudication_response

        assert (
            validate_adjudication_response(result["after"], pair[0])["case-1"]["status"]
            == "pending"
        )
