"""Offline operator presentation preserves evidence and blank response identities."""

import hashlib
import json
import shutil
import subprocess
from copy import deepcopy
from html.parser import HTMLParser

import pytest

from healthcraft.reconciliation.diagnostics import explain_reconciliation
from healthcraft.reconciliation.execution import execute_reference, run_reconciliation_trial
from healthcraft.reconciliation.fixture import load_scenario
from healthcraft.reconciliation.oracle import load_expectations, verify_reconciliation

AXES = (
    "execution_completion",
    "write_acknowledgement",
    "storage",
    "readback",
    "reconciliation_correctness",
    "evidence_sufficiency",
)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


@pytest.fixture
def assignment(monkeypatch):
    monkeypatch.setenv("HC_IDEMPOTENT_TOOLS", "1")
    scenario, expectations = load_scenario(), load_expectations()
    evidence = run_reconciliation_trial(scenario=scenario, controller=execute_reference)
    documents = dict(scenario=scenario, expectations=expectations, evidence=evidence)
    documents["oracle"] = verify_reconciliation(scenario, expectations, evidence)
    packet = {
        "schema_version": "healthcraft-operator-review-packet/v1",
        "packet_id": "packet-test",
        "assignment_id": "assignment-test",
        "reviewer_id": "operator-test",
        "presentation": "raw",
        "protocol": {"protocol_id": "tutorial-1", "purpose": "engineering_tutorial"},
        "scope": "exposed_tutorial_operator_review",
        "cases": [
            {
                "case_id": "case-0001",
                "scenario_family_id": "exposed-reconciliation-v1",
                "source_bindings": {
                    key + "_sha256": digest(value) for key, value in documents.items()
                },
                "documents": documents,
                "explanation": explain_reconciliation(scenario, expectations, evidence),
                "axes": [
                    {
                        "axis_id": key,
                        "question": "Assess " + key,
                        "scope_note": "Engineering evidence only.",
                    }
                    for key in AXES
                ],
            }
        ],
        "limitations": ["Exposed tutorial; no independent participant or clinical evidence."],
    }
    template = {
        "schema_version": "healthcraft-operator-review-response/v1",
        "packet_id": packet["packet_id"],
        "packet_sha256": digest(packet),
        "assignment_id": packet["assignment_id"],
        "reviewer_id": packet["reviewer_id"],
        "cases": [
            {
                "case_id": "case-0001",
                "axes": [
                    {
                        "axis_id": key,
                        "judgment": None,
                        "unassessed_reason": None,
                        "evidence_refs": [],
                        "rationale": "",
                    }
                    for key in AXES
                ],
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


def render(assignment):
    from healthcraft.operator_review_report import render_operator_packet

    return render_operator_packet(*assignment)


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags, self.text, self.scripts, self.source_text = [], [], {}, {}
        self.script = self.source = None
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        self.tags.append((tag, attrs))
        if tag == "script":
            self.script = attrs["id"]
            self.scripts[self.script] = ""
        if tag == "pre" and "data-document" in attrs:
            self.source = (attrs["data-case"], attrs["data-document"])
            self.source_text[self.source] = ""

    def handle_endtag(self, tag):
        if tag == "script":
            self.script = None
        if tag == "pre":
            self.source = None

    def handle_data(self, text):
        self.text.append(text)
        if self.script:
            self.scripts[self.script] += text
        if self.source:
            self.source_text[self.source] += text


def node_export(html, values, tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Optional installed Node runtime required for offline JavaScript contract test")
    page = Page(html)
    script = page.scripts["operator-app"]
    check = tmp_path / "operator.js"
    check.write_text(script)
    subprocess.run([node, "--check", str(check)], check=True, capture_output=True, text=True)
    harness = """const vm=require('node:vm');const fs=require('node:fs');
const payload=JSON.parse(fs.readFileSync(0,'utf8'));
const context={document:{getElementById(id){return {textContent:id==='operator-response-template'?JSON.stringify(payload.template):'',addEventListener(){}};}}};
vm.createContext(context);vm.runInContext(payload.script,context);
try { const result=context.buildOperatorResponse(payload.values,payload.template);process.stdout.write(JSON.stringify({result})); }
catch(error) {process.stdout.write(JSON.stringify({error:error.message}));}
"""
    result = subprocess.run(
        [node, "-e", harness],
        input=json.dumps(
            {
                "script": script,
                "template": json.loads(page.scripts["operator-response-template"]),
                "values": values,
            }
        ),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def blank_values(template):
    return {
        "cases": [
            {
                "axes": [
                    {
                        "judgment": "",
                        "unassessed_reason": "",
                        "evidence_refs": "[]",
                        "rationale": "",
                    }
                    for _ in case["axes"]
                ],
                "timing": {
                    "method": "not_collected",
                    "elapsed_seconds": "",
                    "active_seconds": "",
                    "note": "",
                },
            }
            for case in template["cases"]
        ]
    }


def test_both_presentations_have_same_sources_and_blank_six_axis_form(assignment):
    before = deepcopy(assignment)
    raw = Page(render(assignment))
    packet, template = deepcopy(assignment)
    packet["presentation"] = "assisted"
    template["packet_sha256"] = digest(packet)
    assisted = Page(render((packet, template)))
    assert raw.source_text == assisted.source_text
    for key, content in raw.source_text.items():
        assert json.loads(content) == packet["cases"][0]["documents"][key[1]]
    for page in (raw, assisted):
        selects = [attrs for tag, attrs in page.tags if tag == "select" and "data-axis" in attrs]
        assert {attrs["data-axis"] for attrs in selects} == set(AXES)
        assert len(selects) == 6
        assert json.loads(page.scripts["operator-response-template"]) == (
            template if page is assisted else assignment[1]
        )
        assert "self-reported" in " ".join(page.text).lower()
        assert "clinical" in " ".join(page.text).lower()
    assert "Automated explanation" not in " ".join(raw.text)
    assert "Automated explanation" in " ".join(assisted.text)
    assert assignment == before


def test_all_navigation_is_internal_and_ids_unique_across_cases(assignment):
    packet, template = deepcopy(assignment)
    packet["cases"].append(deepcopy(packet["cases"][0]))
    packet["cases"][1]["case_id"] = "case-0002"
    template["cases"].append(deepcopy(template["cases"][0]))
    template["cases"][1]["case_id"] = "case-0002"
    template["packet_sha256"] = digest(packet)
    page = Page(render((packet, template)))
    ids = [attrs["id"] for _, attrs in page.tags if "id" in attrs]
    assert len(ids) == len(set(ids))
    links = [attrs["href"] for _, attrs in page.tags if "href" in attrs]
    assert links and all(link.startswith("#") and link[1:] in ids for link in links)
    assert len(page.source_text) == 8


@pytest.mark.parametrize(
    "change", ["packet_hash", "identity", "prefilled", "missing_axis", "source", "explanation"]
)
def test_rejects_unbound_or_prefilled_packet(assignment, change):
    packet, template = deepcopy(assignment)
    if change == "packet_hash":
        template["packet_sha256"] = "0" * 64
    elif change == "identity":
        template["reviewer_id"] = "foreign"
    elif change == "prefilled":
        template["cases"][0]["axes"][0]["judgment"] = "yes"
    elif change == "missing_axis":
        template["cases"][0]["axes"].pop()
    elif change == "source":
        packet["cases"][0]["documents"]["evidence"]["changed"] = True
    else:
        packet["cases"][0]["explanation"]["limitations"].append("altered")
    if change in {"source", "explanation"}:
        template["packet_sha256"] = digest(packet)
    with pytest.raises(ValueError):
        render((packet, template))


def test_hostile_labels_are_escaped_and_template_cannot_close_script(assignment):
    packet, template = deepcopy(assignment)
    attack = '</script><img src="https://invalid.example" onerror="boom">\u2028&'
    packet["reviewer_id"] = template["reviewer_id"] = attack
    packet["cases"][0]["axes"][0]["question"] = attack
    packet["limitations"].append(attack)
    template["packet_sha256"] = digest(packet)
    page = Page(render((packet, template)))
    assert set(page.scripts) == {"operator-response-template", "operator-app"}
    assert json.loads(page.scripts["operator-response-template"])["reviewer_id"] == attack
    assert not any(tag in {"img", "iframe", "object", "embed", "link"} for tag, _ in page.tags)
    assert not any(
        "src" in attrs or any(key.lower().startswith("on") for key in attrs)
        for _, attrs in page.tags
    )
    script = page.scripts["operator-app"]
    assert not any(
        term in script
        for term in (
            "fetch(",
            "XMLHttpRequest",
            "WebSocket",
            "localStorage",
            "Date.now",
            "performance.now",
        )
    )


def test_export_blank_preserves_all_denominators_and_ids(assignment, tmp_path):
    packet, template = assignment
    result = node_export(render(assignment), blank_values(template), tmp_path)
    assert result == {"result": template}


def test_export_assessment_abstention_and_manual_timing(assignment, tmp_path):
    _, template = assignment
    values = blank_values(template)
    axis = values["cases"][0]["axes"][0]
    axis.update(
        judgment="yes",
        evidence_refs='[{"document":"evidence","pointer":"/completion"}]',
        rationale="Recorded completion.",
    )
    values["cases"][0]["axes"][1].update(
        judgment="unassessed", unassessed_reason="reviewer_abstention", rationale="Review deferred."
    )
    values["cases"][0]["timing"] = {
        "method": "self_reported",
        "elapsed_seconds": "120",
        "active_seconds": "90.5",
        "note": "Manually reported.",
    }
    response = node_export(render(assignment), values, tmp_path)["result"]
    assert response["packet_sha256"] == template["packet_sha256"]
    assert response["cases"][0]["axes"][0]["judgment"] == "yes"
    assert response["cases"][0]["axes"][1]["judgment"] == "unassessed"
    assert all(row["judgment"] is None for row in response["cases"][0]["axes"][2:])
    assert response["cases"][0]["timing"]["active_seconds"] == 90.5


@pytest.mark.parametrize(
    "invalid", ["refs", "reason", "pending", "timing", "forged_method", "axis_count"]
)
def test_export_rejects_partial_invalid_answers_without_filling_defaults(
    assignment, tmp_path, invalid
):
    values = blank_values(assignment[1])
    row = values["cases"][0]["axes"][0]
    if invalid == "refs":
        row.update(judgment="yes", rationale="Claim", evidence_refs="not-json")
    elif invalid == "reason":
        row.update(judgment="unassessed", rationale="Claim")
    elif invalid == "pending":
        row["rationale"] = "Partial unsaved assessment"
    elif invalid == "timing":
        values["cases"][0]["timing"].update(
            method="self_reported", elapsed_seconds="1", active_seconds="2", note="manual"
        )
    elif invalid == "forged_method":
        values["cases"][0]["timing"]["method"] = "measured"
    else:
        values["cases"][0]["axes"].pop()
    assert "error" in node_export(render(assignment), values, tmp_path)


@pytest.mark.parametrize(
    "refs",
    [
        '[{"document":"evidence","pointer":"/wrong","pointer":"/completion"}]',
        r'[{"document":"evidence","pointer":"/wrong","\u0070ointer":"/completion"}]',
        '[{"document":"evidence","pointer":{"x":1,"x":2}}]',
    ],
)
def test_export_rejects_duplicate_reference_keys_without_repair(assignment, tmp_path, refs):
    values = blank_values(assignment[1])
    values["cases"][0]["axes"][0].update(
        judgment="yes",
        evidence_refs=refs,
        rationale="Manual assessment.",
    )
    result = node_export(render(assignment), values, tmp_path)
    assert "Duplicate JSON key" in result.get("error", "")


@pytest.mark.parametrize("elapsed,active", [("12.5", ""), ("", "0")])
def test_self_reported_timing_preserves_unknown_measurement(assignment, tmp_path, elapsed, active):
    values = blank_values(assignment[1])
    values["cases"][0]["timing"].update(
        method="self_reported",
        elapsed_seconds=elapsed,
        active_seconds=active,
        note="Only this duration was recorded manually.",
    )
    response = node_export(render(assignment), values, tmp_path)["result"]
    timing = response["cases"][0]["timing"]
    assert timing["elapsed_seconds"] == (float(elapsed) if elapsed else None)
    assert timing["active_seconds"] == (float(active) if active else None)


def test_uncollected_timing_can_explain_why_without_inventing_time(assignment, tmp_path):
    values = blank_values(assignment[1])
    values["cases"][0]["timing"]["note"] = "No duration was recorded."
    response = node_export(render(assignment), values, tmp_path)["result"]
    assert response["cases"][0]["timing"] == {
        "method": "not_collected",
        "elapsed_seconds": None,
        "active_seconds": None,
        "note": "No duration was recorded.",
    }


def test_shared_source_navigation_exposes_exact_subobjects_and_copyable_refs(assignment):
    packet, template = assignment
    raw = Page(render(assignment))
    packet = deepcopy(packet)
    packet["presentation"] = "assisted"
    template = deepcopy(template)
    template["packet_sha256"] = digest(packet)
    assisted = Page(render((packet, template)))
    raw_refs = [attrs for tag, attrs in raw.tags if "data-source-reference" in attrs]
    assisted_refs = [attrs for tag, attrs in assisted.tags if "data-source-reference" in attrs]
    assert raw_refs and raw_refs == assisted_refs
    refs = [json.loads(attrs["value"]) for attrs in raw_refs]
    assert {"document": "evidence", "pointer": "/calls/0"} in refs
    assert {"document": "evidence", "pointer": "/completion"} in refs
    assert {ref["document"] for ref in refs} == set(packet["cases"][0]["documents"])
    for attrs, ref in zip(raw_refs, refs, strict=True):
        assert "readonly" in attrs
        value = packet["cases"][0]["documents"][ref["document"]]
        for token in ref["pointer"][1:].split("/") if ref["pointer"] else []:
            token = token.replace("~1", "/").replace("~0", "~")
            value = value[int(token)] if type(value) is list else value[token]
        assert attrs["data-value-sha256"] == digest(value)


def test_unavailable_explanation_preserves_sources_and_blank_axes(assignment):
    packet, template = deepcopy(assignment)
    case = packet["cases"][0]
    documents = case["documents"]
    documents["evidence"]["scenario_sha256"] = "0" * 64
    args = [documents[name] for name in ("scenario", "expectations", "evidence")]
    documents["oracle"] = verify_reconciliation(*args)
    case["explanation"] = explain_reconciliation(*args)
    assert case["explanation"]["status"] == "unavailable"
    case["source_bindings"] = {key + "_sha256": digest(value) for key, value in documents.items()}
    packet["presentation"] = "assisted"
    template["packet_sha256"] = digest(packet)
    page = Page(render((packet, template)))
    assert "Explanation unavailable; recorded event counts are unknown." in " ".join(page.text)
    assert len(page.source_text) == 4
    assert len([attrs for tag, attrs in page.tags if tag == "select" and "data-axis" in attrs]) == 6
    assert json.loads(page.scripts["operator-response-template"]) == template


def test_real_packet_node_export_and_import_preserve_pending_axes_and_unknown_active(
    assignment,
    tmp_path,
):
    from healthcraft.operator_review import build_operator_packet, import_operator_response
    from scripts.explain_reconciliation import write_explanation_bundle

    docs = assignment[0]["cases"][0]["documents"]
    inputs = {}
    for name in ("scenario", "expectations", "evidence"):
        inputs[name] = tmp_path / (name + ".json")
        inputs[name].write_text(json.dumps(docs[name]))
    source = tmp_path / "source"
    write_explanation_bundle(**inputs, output_dir=source, source_context=True)
    packet_dir = tmp_path / "packet"
    packet = build_operator_packet(
        {"case-one": source},
        packet_dir,
        protocol={"protocol_id": "integration-tutorial", "purpose": "engineering_tutorial"},
        assignment={
            "assignment_id": "assignment-one",
            "reviewer_id": "reviewer-one",
            "presentation": "assisted",
        },
    )
    before = {
        str(path.relative_to(packet_dir)): path.read_bytes()
        for path in packet_dir.rglob("*")
        if path.is_file()
    }
    template = json.loads((packet_dir / "response-template.json").read_bytes())
    values = blank_values(template)
    values["cases"][0]["axes"][0].update(
        judgment="yes",
        rationale="Synthetic test answer; not a participant judgment.",
        evidence_refs='[{"document":"evidence","pointer":"/completion"}]',
    )
    values["cases"][0]["timing"].update(
        method="self_reported",
        elapsed_seconds="12.5",
        note="Synthetic serializer test value.",
    )
    exported = node_export((packet_dir / "report.html").read_text(), values, tmp_path)["result"]
    response = tmp_path / "response.json"
    response.write_text(json.dumps(exported))
    receipt = import_operator_response(packet_dir / "manifest.json", response, tmp_path / "import")
    assert receipt["status"] == "recorded"
    assert receipt["packet_id"] == packet["packet_id"]
    assert receipt["counts"]["assigned_axes"] == 6
    assert receipt["counts"]["assessed_axes"] == 1
    assert receipt["counts"]["pending_axes"] == 5
    case = receipt["cases"][0]
    assert case["case_id"] == "case-one"
    assert case["axes"][0]["response"]["evidence_refs"] == [
        {"document": "evidence", "pointer": "/completion"}
    ]
    assert case["timing"]["elapsed_seconds"] == 12.5
    assert case["timing"]["active_seconds"] is None
    assert before == {
        str(path.relative_to(packet_dir)): path.read_bytes()
        for path in packet_dir.rglob("*")
        if path.is_file()
    }
