"""Actual offline form exports preserve independent, source-cited judgments."""

import hashlib
import importlib
import json
import shutil
import subprocess
from copy import deepcopy
from html.parser import HTMLParser

import pytest

AXES = (
    "execution_completion",
    "write_acknowledgement",
    "storage",
    "readback",
    "reconciliation_correctness",
    "evidence_sufficiency",
)
CHECKS = (
    "target_attribution",
    "incident_accuracy_completeness",
    "evidence_support",
    "uncertainty_handling",
)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def blank_axis(identifier, key="axis_id"):
    value = {
        key: identifier,
        "judgment": None,
        "unassessed_reason": None,
        "rationale": "",
        "evidence_refs": [],
    }
    if key == "check_id":
        value["response_pointers"] = []
    return value


@pytest.fixture
def incident():
    documents = {
        "task": {"target": {"patient_id": "PAT-A", "encounter_id": "ENC-A"}},
        "scenario": {"nested": {"a/b~c": [None, {"literal": "é\nline"}]}},
        "evidence": {
            "note": '{"nested":{"id":"SRC-1","unknown":null}}',
            "bad_note": '{"x":1,"x":2}',
            "completion": {"status": "failed"},
        },
        "runtime": None,
    }
    packet = {
        "schema_version": "healthcraft-operator-incident-packet/v2",
        "packet_id": "p1",
        "assignment_id": "a1",
        "operator_id": "operator",
        "presentation": "raw",
        "protocol": {"protocol_id": "dev", "purpose": "engineering_development"},
        "axes": [
            {"axis_id": key, "question": "Assess " + key, "distinction": "Observed is not correct."}
            for key in AXES
        ],
        "cases": [
            {
                "review_case_id": "case-1",
                "attempt_sha256": "a" * 64,
                "scenario_family_id": "family-1",
                "documents": documents,
                "availability": {
                    key: {
                        "status": "available" if value is not None else "unavailable",
                        "reason": None if value is not None else "Not captured",
                        "sha256": digest(value) if value is not None else None,
                    }
                    for key, value in documents.items()
                },
                "assistance": None,
            }
        ],
        "limitations": ["Development material; no clinical validation."],
    }
    template = {
        "schema_version": "healthcraft-operator-incident-response/v2",
        "packet_id": "p1",
        "packet_sha256": digest(packet),
        "assignment_id": "a1",
        "operator_id": "operator",
        "cases": [
            {
                "review_case_id": "case-1",
                "identified_target": {
                    "status": None,
                    "patient_id": "",
                    "encounter_id": "",
                    "unassessed_reason": None,
                    "rationale": "",
                    "evidence_refs": [],
                },
                "axes": [blank_axis(key) for key in AXES],
                "incident_assessment": {
                    "status": None,
                    "summary": "",
                    "findings": [],
                    "unassessed_reason": None,
                    "evidence_refs": [],
                },
                "timing": {
                    "method": "not_collected",
                    "elapsed_seconds": None,
                    "active_seconds": None,
                    "note": "",
                },
            }
        ],
    }
    return packet, template


@pytest.fixture
def adjudication(incident):
    source, response = incident
    packet = {
        "schema_version": "healthcraft-operator-incident-adjudication-packet/v2",
        "packet_id": "adj1",
        "assignment_id": "adj-assignment",
        "adjudicator_id": "reviewer",
        "role": "initial",
        "protocol": source["protocol"],
        "operator_packet_sha256": digest(source),
        "operator_response_sha256": digest(response),
        "validity_rubric": {
            "schema_version": "healthcraft-operator-report-validity/v1",
            "scope": "engineering_report_validity",
            "checks": [{"check_id": key, "question": "Review " + key} for key in CHECKS],
        },
        "cases": [
            {
                "review_case_id": "case-1",
                "scenario_family_id": "family-1",
                "operator_report_status": "pending",
                "documents": {
                    **source["cases"][0]["documents"],
                    "response": response["cases"][0],
                    "prior_judgments": None,
                },
            }
        ],
        "limitations": ["Declarations do not prove reviewer independence."],
    }
    template = {
        "schema_version": "healthcraft-operator-incident-adjudication/v2",
        "packet_id": "adj1",
        "packet_sha256": digest(packet),
        "assignment_id": "adj-assignment",
        "adjudicator_id": "reviewer",
        "role": "initial",
        "cases": [
            {
                "review_case_id": "case-1",
                "overall": None,
                "unassessed_reason": None,
                "rationale": "",
                "checks": [blank_axis(key, "check_id") for key in CHECKS],
            }
        ],
        "reviewer_declaration": {"independent_review": None, "qualifications": "", "conflicts": ""},
    }
    return packet, template


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags, self.text, self.scripts = [], [], {}
        self.active = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if tag == "script":
            self.active = attrs["id"]
            self.scripts[self.active] = ""

    def handle_endtag(self, tag):
        if tag == "script":
            self.active = None

    def handle_data(self, value):
        self.text.append(value)
        if self.active:
            self.scripts[self.active] += value


def render(pair, mode="incident"):
    api = importlib.import_module("healthcraft.operator_incident_report")
    return getattr(api, "render_" + mode + "_packet")(*pair)


def values(template):
    value = deepcopy(template)

    # UI stores freeform reference arrays, source IDs and response pointers as text.
    def convert(item):
        if isinstance(item, dict):
            for key, child in list(item.items()):
                if key in {"evidence_refs", "source_ids", "response_pointers"}:
                    item[key] = json.dumps(child)
                elif child is None:
                    item[key] = ""
                else:
                    convert(child)
        elif isinstance(item, list):
            for child in item:
                convert(child)

    convert(value)
    return value


def node_export(pair, answers, tmp_path, mode="incident"):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Installed Node required for offline serializer verification")
    page = Page(render(pair, mode))
    script = page.scripts["incident-app"]
    path = tmp_path / "app.js"
    path.write_text(script)
    subprocess.run([node, "--check", str(path)], check=True, capture_output=True, text=True)
    harness = """const fs=require('node:fs'),vm=require('node:vm');
const p=JSON.parse(fs.readFileSync(0,'utf8'));
const c={document:{getElementById(id){return {textContent:id==='incident-packet'?JSON.stringify(p.packet):id==='incident-template'?JSON.stringify(p.template):'',addEventListener(){}};},querySelectorAll(){return [];}}};
vm.createContext(c);vm.runInContext(p.script,c);
try {process.stdout.write(JSON.stringify({result:c[p.name](p.values,p.template,p.packet)}));}
catch(e){process.stdout.write(JSON.stringify({error:e.message}));}
"""
    result = subprocess.run(
        [node, "-e", harness],
        input=json.dumps(
            {
                "script": script,
                "packet": pair[0],
                "template": pair[1],
                "values": answers,
                "name": "buildIncidentResponse"
                if mode == "incident"
                else "buildAdjudicationResponse",
            }
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_raw_assisted_same_sources_blank_forms_and_explicit_claims(incident):
    before = deepcopy(incident)
    raw = Page(render(incident))
    packet, template = deepcopy(incident)
    packet["presentation"] = "assisted"
    packet["cases"][0]["assistance"] = {
        "schema_version": "healthcraft-incident-evidence/v1",
        "status": "partial",
        "document_sha256": {k: digest(v) for k, v in packet["cases"][0]["documents"].items()},
        "coverage": {"storage": "unavailable"},
        "claims": [
            {
                "id": "claim-1",
                "category": "completion",
                "code": "recorded_failed",
                "summary": "Captured execution failed",
                "observed": {"status": "failed"},
                "refs": [{"document": "evidence", "pointer": "/completion"}],
            }
        ],
        "limitations": ["Claim to inspect, not an operator answer."],
        "unassessed": ["runtime"],
    }
    template["packet_sha256"] = digest(packet)
    assisted = Page(render((packet, template)))

    def refs(page):
        return [a["value"] for t, a in page.tags if a.get("data-source-reference") == "true"]

    assert refs(raw) == refs(assisted)
    assert "Captured execution failed" not in " ".join(raw.text)
    assert "Captured execution failed" in " ".join(assisted.text)
    assert "Independent report validity" not in " ".join(raw.text)
    assert [a["data-axis"] for t, a in raw.tags if t == "select" and "data-axis" in a] == list(AXES)
    assert any(a.get("data-add-finding") == "0" for _, a in raw.tags)
    assert any(a.get("data-remove-finding") == "true" for _, a in raw.tags)
    assert json.loads(raw.scripts["incident-template"]) == incident[1]
    assert incident == before


def test_every_nested_value_has_citation_and_strict_decoded_notes(incident):
    page = Page(render(incident))
    refs = [
        json.loads(a["value"]) for _, a in page.tags if a.get("data-source-reference") == "true"
    ]
    assert {"document": "scenario", "pointer": "/nested/a~1b~0c/1/literal"} in refs
    assert {
        "document": "evidence",
        "pointer": "/note",
        "decoded_json_pointer": "/nested/unknown",
    } in refs
    assert not any(r.get("pointer") == "/bad_note" and "decoded_json_pointer" in r for r in refs)
    assert "Decoded JSON unavailable" in " ".join(page.text)
    assert "Not captured" in " ".join(page.text)
    assert "null" in " ".join(page.text)


def test_no_external_resources_and_untrusted_text_cannot_escape(incident):
    packet, template = deepcopy(incident)
    packet["cases"][0]["documents"]["scenario"]["payload"] = (
        '</script><img src=x onerror="alert(1)">\u2028'
    )
    packet["cases"][0]["availability"]["scenario"]["sha256"] = digest(
        packet["cases"][0]["documents"]["scenario"]
    )
    template["packet_sha256"] = digest(packet)
    page = Page(render((packet, template)))
    assert not any(tag in {"img", "iframe", "link"} or "src" in attrs for tag, attrs in page.tags)
    assert all(a["href"].startswith("#") for _, a in page.tags if "href" in a)
    assert json.loads(page.scripts["incident-packet"]) == packet
    ids = [a["id"] for _, a in page.tags if "id" in a]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("mode", ["incident", "adjudication"])
def test_blank_export_is_exact_template(incident, adjudication, tmp_path, mode):
    pair = incident if mode == "incident" else adjudication
    assert node_export(pair, values(pair[1]), tmp_path, mode) == {"result": pair[1]}


def test_pending_draft_text_known_target_and_refs_are_retained(incident, tmp_path):
    answer = values(incident[1])
    target = answer["cases"][0]["identified_target"]
    target.update(
        patient_id="operator-entered-id",
        rationale="Still checking",
        evidence_refs='[{"document":"task","pointer":"/target"}]',
    )
    answer["cases"][0]["axes"][0]["rationale"] = "Unfinished reasoning"
    result = node_export(incident, answer, tmp_path)["result"]
    assert result["cases"][0]["identified_target"]["status"] is None
    assert result["cases"][0]["identified_target"]["patient_id"] == "operator-entered-id"
    assert result["cases"][0]["axes"][0]["judgment"] is None
    assert result["cases"][0]["axes"][0]["rationale"] == "Unfinished reasoning"


def test_incident_finding_export_preserves_claim_and_known_unknowns(incident, tmp_path):
    answer = values(incident[1])
    row = answer["cases"][0]
    row["identified_target"].update(
        status="unassessed",
        patient_id="known-id",
        unassessed_reason="insufficient_evidence",
        rationale="Encounter unknown",
    )
    row["incident_assessment"].update(
        status="findings_identified",
        summary="Execution issue",
        evidence_refs='[{"document":"evidence","pointer":"/completion"}]',
        findings=[
            {
                "finding_id": "finding-1",
                "category": "execution",
                "claim": "Execution recorded failed",
                "observed_target": {"patient_id": "known-id", "encounter_id": ""},
                "source_ids": "[]",
                "evidence_refs": '[{"document":"evidence","pointer":"/completion/status"}]',
            }
        ],
    )
    row["timing"].update(method="self_reported", elapsed_seconds="12.5", note="Entered by operator")
    result = node_export(incident, answer, tmp_path)["result"]["cases"][0]
    assert result["identified_target"]["patient_id"] == "known-id"
    assert result["incident_assessment"]["findings"][0]["observed_target"]["encounter_id"] is None
    assert result["timing"]["elapsed_seconds"] == 12.5
    assert result["timing"]["active_seconds"] is None


@pytest.mark.parametrize(
    "refs",
    [
        '[{"document":"task","pointer":"/wrong","pointer":"/target"}]',
        '[{"document":"task","pointer":"/wrong","\\u0070ointer":"/target"}]',
        '[{"document":"task","pointer":"\\n"}]',
        '[{"document":"runtime","pointer":""}]',
        '[{"document":"evidence","pointer":"/bad_note","decoded_json_pointer":"/x"}]',
        '[{"document":"task","pointer":"/missing"}]',
        '[{"document":"task","pointer":"","extra":{"x":1,"x":2}}]',
        '[{"document":"task","pointer":"","extra":1e999}]',
    ],
)
def test_invalid_citations_never_normalized_or_exported(incident, tmp_path, refs):
    answer = values(incident[1])
    answer["cases"][0]["axes"][0]["evidence_refs"] = refs
    assert "error" in node_export(incident, answer, tmp_path)


def test_timing_error_does_not_erase_structured_report(incident, tmp_path):
    answer = values(incident[1])
    answer["cases"][0]["timing"].update(
        method="self_reported", elapsed_seconds="2", active_seconds="3", note="Mistyped"
    )
    result = node_export(incident, answer, tmp_path)["result"]["cases"][0]
    assert result["timing"]["active_seconds"] == 3
    assert result["timing"]["elapsed_seconds"] == 2


def test_adjudication_valid_decision_and_independence_declaration(adjudication, tmp_path):
    adjudication[0]["cases"][0]["operator_report_status"] = "submitted"
    adjudication[1]["packet_sha256"] = digest(adjudication[0])
    answer = values(adjudication[1])
    row = answer["cases"][0]
    for check in row["checks"]:
        check.update(
            judgment="supported",
            rationale="Source supports report",
            evidence_refs='[{"document":"task","pointer":"/target"}]',
            response_pointers='["/identified_target"]',
        )
    row.update(overall="valid", rationale="All required checks supported")
    answer["reviewer_declaration"].update(
        independent_review="false", qualifications="Self-reported", conflicts="Same author"
    )
    result = node_export(adjudication, answer, tmp_path, "adjudication")["result"]
    assert result["cases"][0]["overall"] == "valid"
    assert result["reviewer_declaration"]["independent_review"] is False
    assert result["packet_sha256"] == adjudication[1]["packet_sha256"]


def test_adjudicator_cannot_promote_incomplete_checks_to_valid(adjudication, tmp_path):
    answer = values(adjudication[1])
    answer["cases"][0].update(overall="valid", rationale="Guessed")
    assert "error" in node_export(adjudication, answer, tmp_path, "adjudication")


def test_adjudicator_pending_overall_retains_finished_checks(adjudication, tmp_path):
    answer = values(adjudication[1])
    answer["cases"][0]["checks"][0].update(
        judgment="supported",
        rationale="Task identifies target",
        evidence_refs='[{"document":"task","pointer":"/target"}]',
        response_pointers='["/identified_target"]',
    )
    result = node_export(adjudication, answer, tmp_path, "adjudication")["result"]
    assert result["cases"][0]["overall"] is None
    assert result["cases"][0]["checks"][0]["judgment"] == "supported"


def test_binding_mismatch_or_filled_template_is_rejected(incident):
    packet, template = deepcopy(incident)
    template["packet_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        render((packet, template))
    template["packet_sha256"] = digest(packet)
    template["cases"][0]["axes"][0]["judgment"] = "yes"
    with pytest.raises(ValueError):
        render((packet, template))


def draft_finding():
    return {
        "finding_id": "finding-1",
        "category": "content",
        "claim": "",
        "observed_target": {"patient_id": "", "encounter_id": ""},
        "source_ids": "[]",
        "evidence_refs": "[]",
    }


def test_draft_finding_remains_pending_with_partial_fields(incident, tmp_path):
    answer = values(incident[1])
    answer["cases"][0]["incident_assessment"]["findings"] = [draft_finding()]
    result = node_export(incident, answer, tmp_path)["result"]
    row = result["cases"][0]["incident_assessment"]
    assert row["status"] is None and row["findings"][0]["claim"] == ""
    core = importlib.import_module("healthcraft.operator_incidents")
    assert core.validate_incident_response(result, incident[0])["case-1"]["status"] == "pending"


@pytest.mark.parametrize("mutation", ["duplicate_id", "invalid_id", "duplicate_source"])
def test_finding_identity_contract_matches_importer(incident, tmp_path, mutation):
    answer = values(incident[1])
    finding = draft_finding()
    finding.update(claim="Draft claim", evidence_refs='[{"document":"task","pointer":""}]')
    findings = [finding]
    if mutation == "duplicate_id":
        findings.append({**finding, "finding_id": "FINDING-1"})
    elif mutation == "invalid_id":
        finding["finding_id"] = "finding-1\n"
    else:
        finding["source_ids"] = '["SRC-1","SRC-1"]'
    answer["cases"][0]["incident_assessment"]["findings"] = findings
    assert "error" in node_export(incident, answer, tmp_path)


@pytest.mark.parametrize("location", ["packet", "case", "template"])
def test_unexpected_packet_fields_never_embedded(incident, location):
    packet, template = deepcopy(incident)
    item = {"packet": packet, "case": packet["cases"][0], "template": template}[location]
    item["private_expected_answers"] = {"truth": "do not display"}
    template["packet_sha256"] = digest(packet)
    with pytest.raises(ValueError):
        render((packet, template))


def test_adjudicator_source_navigation_distinguishes_response_pointer(adjudication):
    page = Page(render(adjudication, "adjudication"))
    response_pointers = [
        a["value"] for _, a in page.tags if a.get("data-response-pointer") == "true"
    ]
    assert json.dumps("/identified_target") in response_pointers
    refs = [
        json.loads(a["value"]) for _, a in page.tags if a.get("data-source-reference") == "true"
    ]
    assert not any(r["document"] == "response" for r in refs)


def test_array_reference_cannot_normalize_newline_index(incident, tmp_path):
    answer = values(incident[1])
    answer["cases"][0]["axes"][0]["evidence_refs"] = json.dumps(
        [{"document": "scenario", "pointer": "/nested/a~1b~0c/0\n"}]
    )
    assert "error" in node_export(incident, answer, tmp_path)


def test_pending_operator_report_cannot_be_declared_valid(adjudication, tmp_path):
    answer = values(adjudication[1])
    for check in answer["cases"][0]["checks"]:
        check.update(
            judgment="supported",
            rationale="Proposed",
            evidence_refs='[{"document":"task","pointer":""}]',
            response_pointers='[""]',
        )
    answer["cases"][0].update(overall="valid", rationale="Attempted premature declaration")
    assert "error" in node_export(adjudication, answer, tmp_path, "adjudication")


@pytest.mark.parametrize("presentation", ["raw", "assisted"])
def test_real_core_packet_html_javascript_import_and_adjudication(tmp_path, presentation):
    from pathlib import Path

    from healthcraft import operator_adjudication as adjudicator
    from healthcraft import operator_incidents as core

    source = (
        Path(__file__).resolve().parents[1]
        / "artifacts/reconciliation/20260930/casebook-native-v2/run/manifest.json"
    )
    source_before = source.read_bytes()
    out = tmp_path / "operator"
    packet = core.build_incident_packet(
        source,
        out,
        expected_sha256=hashlib.sha256(source_before).hexdigest(),
        selections={"case-a": "REC2-004/designated", "case-b": "REC2-008/designated"},
        protocol={"protocol_id": "serializer-integration", "purpose": "engineering_development"},
        assignment={
            "assignment_id": "a1",
            "operator_id": "synthetic-test-operator",
            "presentation": presentation,
        },
    )
    template = core.incident_response_template(packet)
    assert (out / "public/report.html").read_text() == render((packet, template))
    answer = values(template)
    row = answer["cases"][0]
    target = packet["cases"][0]["documents"]["task"]["target"]
    row["identified_target"].update(
        status="identified",
        **target,
        rationale="Synthetic test declaration from task",
        evidence_refs='[{"document":"task","pointer":"/target"}]',
    )
    row["axes"][0].update(
        judgment="unassessed",
        unassessed_reason="reviewer_abstention",
        rationale="Synthetic test abstention",
    )
    row["incident_assessment"]["findings"] = [draft_finding()]
    row["timing"].update(
        method="self_reported",
        elapsed_seconds="12.5",
        note="Synthetic test declaration, not measured",
    )
    exported = node_export((packet, template), answer, tmp_path)["result"]
    response_path = tmp_path / "operator-response.json"
    response_path.write_text(json.dumps(exported, ensure_ascii=False) + "\n")
    receipt = core.import_incident_response(
        out / "manifest.json", response_path, tmp_path / "operator-import"
    )
    assert receipt["status"] == "recorded", receipt["errors"]
    assert receipt["adjudication_status"] == "pending"
    assert all(case["status"] == "pending" for case in receipt["cases"])
    assert receipt["cases"][0]["response"]["timing"]["active_seconds"] is None
    assert receipt["cases"][0]["response"]["incident_assessment"]["findings"][0]["claim"] == ""
    assert (tmp_path / "operator-import/submission.json").read_bytes() == response_path.read_bytes()

    adjudication_dir = tmp_path / "adjudication"
    adjudication_packet = adjudicator.build_adjudication_packet(
        out / "manifest.json",
        response_path,
        adjudication_dir,
        assignment={
            "assignment_id": "adj",
            "adjudicator_id": "synthetic-test-adjudicator",
            "role": "initial",
        },
    )
    adjudication_template = adjudicator.adjudication_template(adjudication_packet)
    assert (adjudication_dir / "public/report.html").read_text() == render(
        (adjudication_packet, adjudication_template), "adjudication"
    )
    answer = values(adjudication_template)
    for check in answer["cases"][0]["checks"]:
        check.update(
            judgment="unsupported",
            rationale="Synthetic interface test declaration, not actual review",
            evidence_refs='[{"document":"task","pointer":"/target"}]',
            response_pointers='["/identified_target"]',
        )
    answer["cases"][0].update(
        overall="invalid", rationale="Synthetic interface test declaration only"
    )
    answer["reviewer_declaration"].update(independent_review="false", conflicts="Automated fixture")
    exported = node_export(
        (adjudication_packet, adjudication_template), answer, tmp_path, "adjudication"
    )["result"]
    adjudication_response = tmp_path / "adjudication-response.json"
    adjudication_response.write_text(json.dumps(exported) + "\n")
    receipt = adjudicator.import_adjudication_response(
        adjudication_dir / "manifest.json", adjudication_response, tmp_path / "adjudication-import"
    )
    assert receipt["status"] == "recorded", receipt["errors"]
    assert (
        receipt["counts"]["assigned"] == 2
        and receipt["counts"]["declared"] == 1
        and receipt["counts"]["pending"] == 1
    )
    assert receipt["reviewer_declaration"]["independent_review"] is False
    assert source.read_bytes() == source_before


@pytest.mark.parametrize("mode", ["incident", "adjudication"])
def test_canonical_packet_reload_preserves_exact_html(incident, adjudication, mode):
    pair = incident if mode == "incident" else adjudication
    reordered = tuple(json.loads(json.dumps(value, sort_keys=True)) for value in pair)
    assert render(pair, mode) == render(reordered, mode)


class FormPage(Page):
    """Read actual emitted field defaults, without a browser or DOM renderer."""

    def __init__(self, text):
        self.fields, self.finding_fields = {}, {}
        self.control = None
        self.select = None
        super().__init__(text)

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        attrs = dict(attrs)
        if tag not in {"input", "textarea", "select", "option"}:
            return
        key = attrs.get("id") or attrs.get("data-field")
        mapping = self.fields if "id" in attrs else self.finding_fields
        if tag == "input" and key:
            mapping[key] = attrs.get("value", "")
        if tag == "textarea" and key:
            mapping[key] = ""
            self.control = (mapping, key)
        if tag == "select" and key:
            self.select = (mapping, key)
        if tag == "option" and self.select:
            mapping, key = self.select
            mapping.setdefault(key, attrs["value"])

    def handle_data(self, value):
        super().handle_data(value)
        if self.control:
            mapping, key = self.control
            mapping[key] += value

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        if tag == "textarea":
            self.control = None
        if tag == "select":
            self.select = None


@pytest.mark.parametrize("mode", ["incident", "adjudication"])
def test_actual_form_fields_and_download_handler_preserve_blank_template(
    incident, adjudication, tmp_path, mode
):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Installed Node required for offline form contract verification")
    pair = incident if mode == "incident" else adjudication
    page = FormPage(render(pair, mode))
    harness = r"""
const fs=require('node:fs'),vm=require('node:vm');
const p=JSON.parse(fs.readFileSync(0,'utf8')),elements={},downloads=[];
function node(id,value){return {id,value,listeners:{},children:[],
  addEventListener(name,fn){this.listeners[name]=fn;},
  appendChild(child){this.children.push(child);child.parent=this;},
  querySelectorAll(){return this.children;},
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(x=>x!==this);},
  click(){this.clicked=true;}};}
for(const [id,value] of Object.entries(p.fields))elements[id]=node(id,value);
for(const [tag,a] of p.tags)if(a.id&&!elements[a.id])elements[a.id]=node(a.id,'');
elements['incident-packet'].textContent=JSON.stringify(p.packet);
elements['incident-template'].textContent=JSON.stringify(p.template);
const buttons=[];
for(const [tag,a] of p.tags)if(a['data-add-finding']){
  const button=node('add','');button.dataset={addFinding:a['data-add-finding']};buttons.push(button);
  elements[`finding-template-${a['data-add-finding']}`].content={cloneNode(){
    const result=node('finding',''),fields={};
    for(const [key,value] of Object.entries(p.finding_fields))fields[key]=node(key,value);
    const remove=node('remove','');
    result.querySelector=selector=>selector==='[data-finding]'?result:
      selector==='[data-remove-finding]'?remove:fields[selector.match(/data-field="([^"]+)"/)[1]];
    return result;
  }};
}
const c={document:{getElementById(id){if(!elements[id])throw Error('Missing field '+id);return elements[id];},
  querySelectorAll(selector){return selector==='[data-add-finding]'?buttons:[];},
  createElement(){return node('link','');},body:node('body','')},
  Blob:class {constructor(parts){downloads.push(parts.join(''));}},
  URL:{createObjectURL(){return 'blob:offline-test';},revokeObjectURL(){}}};
vm.createContext(c);vm.runInContext(p.script,c);
elements['download-response'].listeners.click();
const result={blank:JSON.parse(downloads[0]),export_status:elements['export-status'].textContent};
if(p.mode==='incident'){
  buttons[0].listeners.click();buttons[0].listeners.click();
  elements['findings-0'].children[0].querySelector('[data-remove-finding]').listeners.click();
  elements['findings-0'].children[0].querySelector('[data-field="category"]').value='content';
  elements['download-response'].listeners.click();
  result.draft=JSON.parse(downloads[1]);
  const field=elements['case-0-axis-0-refs'];
  field.value='[{"document":"task","pointer":"/bad","pointer":""}]';
  elements['download-response'].listeners.click();
  result.failed={status:elements['export-status'].textContent,entered:field.value,downloads:downloads.length};
}
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        [node, "-e", harness],
        check=True,
        capture_output=True,
        text=True,
        input=json.dumps(
            {
                "packet": pair[0],
                "template": pair[1],
                "fields": page.fields,
                "finding_fields": page.finding_fields,
                "tags": page.tags,
                "mode": mode,
                "script": page.scripts["incident-app"],
            }
        ),
    )
    result = json.loads(completed.stdout)
    assert result["blank"] == pair[1]
    assert "Pending fields remain pending" in result["export_status"]
    if mode == "incident":
        row = result["draft"]["cases"][0]["incident_assessment"]
        assert row["status"] is None and len(row["findings"]) == 1
        assert row["findings"][0]["finding_id"] == "finding-2"
        assert result["failed"]["downloads"] == 2
        assert "Duplicate JSON key" in result["failed"]["status"]
        assert '"pointer":"/bad","pointer":""' in result["failed"]["entered"]


def test_adjudicator_strict_decoded_array_citation_matches_importer(adjudication, tmp_path):
    from healthcraft.operator_adjudication import validate_adjudication_response

    adjudication[0]["cases"][0]["documents"]["evidence"]["array_text"] = '[{"x":null}]'
    adjudication[1]["packet_sha256"] = digest(adjudication[0])
    answer = values(adjudication[1])
    answer["cases"][0]["checks"][0].update(
        rationale="Draft citation of a captured value",
        evidence_refs='[{"document":"evidence","pointer":"/array_text","decoded_json_pointer":"/0/x"}]',
    )
    exported = node_export(adjudication, answer, tmp_path, "adjudication")["result"]
    received = validate_adjudication_response(exported, adjudication[0])
    assert received["case-1"]["status"] == "pending"
    assert received["case-1"]["response"] == exported["cases"][0]


@pytest.mark.parametrize("mode", ["incident", "adjudication"])
def test_unknown_family_is_explicit_and_does_not_infer_from_case_id(incident, adjudication, mode):
    pair = incident if mode == "incident" else adjudication
    pair[0]["cases"][0]["scenario_family_id"] = None
    pair[1]["packet_sha256"] = digest(pair[0])
    page = Page(render(pair, mode))
    assert "Unknown — not captured" in " ".join(page.text)
    assert json.loads(page.scripts["incident-packet"])["cases"][0]["scenario_family_id"] is None
    assert json.loads(page.scripts["incident-template"]) == pair[1]


@pytest.mark.parametrize("presentation", ["raw", "assisted"])
def test_actual_missing_model_scenario_still_issues_both_forms(tmp_path, presentation):
    from pathlib import Path

    from healthcraft import operator_adjudication as adjudicator
    from healthcraft import operator_incidents as core

    original = (
        Path(__file__).resolve().parents[1]
        / "artifacts/reconciliation/20260930/local-casebook-pilot-v1/run"
    )
    original_manifest_bytes = (original / "manifest.json").read_bytes()
    manifest = json.loads(original_manifest_bytes)
    attempt = "REC2-001/medgemma"
    selected = {
        name: original / name
        for name in manifest["files"]
        if name in {"plan.json", "cases.json"}
        or (name.startswith(attempt + "/") and name != attempt + "/case.json")
    }
    source = tmp_path / "source"
    for name, path in selected.items():
        destination = source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())
    (source / "cases.json").write_text("[]\n")
    plan = json.loads((source / "plan.json").read_bytes())
    plan["roster"] = [row for row in plan["roster"] if row["id"] == attempt]
    (source / "plan.json").write_text(json.dumps(plan))
    manifest["files"] = {
        name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in selected
    }
    manifest["outcomes"] = [row for row in manifest["outcomes"] if row["id"] == attempt]
    manifest_path = source / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    packet = core.build_incident_packet(
        manifest_path,
        tmp_path / "operator",
        expected_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        selections={"opaque-a": attempt},
        protocol={"protocol_id": "missing-capture-test", "purpose": "engineering_development"},
        assignment={
            "assignment_id": "missing-a",
            "operator_id": "synthetic-test-operator",
            "presentation": presentation,
        },
    )
    assert packet["cases"][0]["scenario_family_id"] is None
    assert packet["cases"][0]["documents"]["scenario"] is None
    assert packet["cases"][0]["availability"]["scenario"]["status"] == "unavailable"
    template = core.incident_response_template(packet)
    response_path = tmp_path / "operator-response.json"
    response_path.write_text(json.dumps(template))
    imported = core.import_incident_response(
        tmp_path / "operator/manifest.json", response_path, tmp_path / "operator-import"
    )
    assert imported["status"] == "recorded"
    assert len(imported["cases"]) == 1 and imported["cases"][0]["status"] == "pending"
    adjudication_packet = adjudicator.build_adjudication_packet(
        tmp_path / "operator/manifest.json",
        response_path,
        tmp_path / "adjudication",
        assignment={
            "assignment_id": "missing-adj",
            "adjudicator_id": "synthetic-test-adjudicator",
            "role": "initial",
        },
    )
    assert adjudication_packet["cases"][0]["scenario_family_id"] is None
    assert adjudication_packet["cases"][0]["documents"]["scenario"] is None
    for path in (
        tmp_path / "operator/public/report.html",
        tmp_path / "adjudication/public/report.html",
    ):
        page = Page(path.read_text())
        assert "Unknown — not captured" in " ".join(page.text)
    assert (original / "manifest.json").read_bytes() == original_manifest_bytes
