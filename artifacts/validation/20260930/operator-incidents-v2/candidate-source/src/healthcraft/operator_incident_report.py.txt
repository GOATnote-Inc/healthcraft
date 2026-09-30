"""Offline incident and adjudication forms; source claims never become answers.

The renderer receives controlled public packets, not original HTML. It makes
no network requests and measures no time. Browser/visual usability remains to
be validated separately from the static and JavaScript contract tests.
"""

from __future__ import annotations

import hashlib
import json
import math
from html import escape

_DOCUMENTS = ("task", "scenario", "evidence", "runtime")
_AXES = (
    "execution_completion",
    "write_acknowledgement",
    "storage",
    "readback",
    "reconciliation_correctness",
    "evidence_sufficiency",
)
_CHECKS = (
    "target_attribution",
    "incident_accuracy_completeness",
    "evidence_support",
    "uncertainty_handling",
)
_REASONS = ("insufficient_evidence", "conflicting_evidence", "outside_scope", "reviewer_abstention")
_CATEGORIES = (
    "content",
    "target",
    "persistence",
    "execution",
    "tool",
    "provider",
    "grader",
    "evidence_gap",
    "source_uncertainty",
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _json(value):
    def check(item):
        if type(item) is dict:
            _require(all(type(key) is str for key in item), "JSON object keys must be strings")
            for child in item.values():
                check(child)
        elif type(item) is list:
            for child in item:
                check(child)
        elif type(item) is float:
            _require(math.isfinite(item), "Nonfinite JSON")
        else:
            _require(type(item) in (str, int, bool, type(None)), "Unsupported JSON type")

    check(value)
    result = json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )
    result.encode("utf-8")
    return result


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(text, object_pairs_hook=pairs)
    _json(value)
    return value


def _embedded(value):
    return (
        _json(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _blank_axis(identifier, key):
    row = {
        key: identifier,
        "judgment": None,
        "unassessed_reason": None,
        "rationale": "",
        "evidence_refs": [],
    }
    if key == "check_id":
        row["response_pointers"] = []
    return row


def _validate(packet, template, adjudication):
    _json(packet)
    _json(template)
    _require(type(packet) is dict and type(template) is dict, "Packet and template must be objects")
    prefix = "healthcraft-operator-incident-"
    _require(
        packet.get("schema_version")
        == prefix + ("adjudication-packet/v2" if adjudication else "packet/v2"),
        "Unsupported packet version",
    )
    _require(
        template.get("schema_version")
        == prefix + ("adjudication/v2" if adjudication else "response/v2"),
        "Unsupported response version",
    )
    actor = "adjudicator_id" if adjudication else "operator_id"
    common = {
        "schema_version",
        "packet_id",
        "assignment_id",
        actor,
        "protocol",
        "cases",
        "limitations",
    }
    packet_fields = (
        {"role", "operator_packet_sha256", "operator_response_sha256", "validity_rubric"}
        if adjudication
        else {"presentation", "axes"}
    )
    response_fields = {"role", "reviewer_declaration"} if adjudication else set()
    _require(set(packet) == common | packet_fields, "Unexpected packet fields")
    _require(
        set(template)
        == {"schema_version", "packet_id", "packet_sha256", "assignment_id", actor, "cases"}
        | response_fields,
        "Unexpected response template fields",
    )
    for key in ("packet_id", "assignment_id", actor):
        _require(
            type(packet.get(key)) is str
            and bool(packet[key].strip())
            and template.get(key) == packet[key],
            "Response identity mismatch",
        )
    _require(template.get("packet_sha256") == _digest(packet), "Packet digest mismatch")
    cases = packet.get("cases")
    _require(type(cases) is list and bool(cases), "Cases must be a nonempty array")
    _require(
        type(template.get("cases")) is list and len(template["cases"]) == len(cases),
        "Full assigned case cohort required",
    )
    ids = [case.get("review_case_id") for case in cases if type(case) is dict]
    _require(
        len(ids) == len(cases)
        and all(type(i) is str and i for i in ids)
        and len(set(ids)) == len(ids),
        "Invalid case identities",
    )
    if adjudication:
        _require(
            packet.get("role") in {"initial", "resolver"}
            and template.get("role") == packet["role"],
            "Invalid adjudicator role",
        )
        definitions = packet["validity_rubric"]["checks"]
        _require(
            packet["validity_rubric"].get("scope") == "engineering_report_validity",
            "Unsupported adjudication scope",
        )
        _require(
            [row.get("check_id") for row in definitions] == list(_CHECKS),
            "Four validity checks required",
        )
        _require(
            template.get("reviewer_declaration")
            == {"independent_review": None, "qualifications": "", "conflicts": ""},
            "Declaration template must be blank",
        )
    else:
        _require(packet.get("presentation") in {"raw", "assisted"}, "Unknown presentation")
        definitions = packet["axes"]
        _require(
            [row.get("axis_id") for row in definitions] == list(_AXES), "Six incident axes required"
        )
    for case, response in zip(cases, template["cases"], strict=True):
        fields = {"review_case_id", "scenario_family_id", "documents"}
        fields |= (
            {"operator_report_status"}
            if adjudication
            else {"attempt_sha256", "availability", "assistance"}
        )
        _require(set(case) == fields, "Unexpected case fields")
        docs = case.get("documents")
        names = set(_DOCUMENTS) | ({"response", "prior_judgments"} if adjudication else set())
        _require(
            type(docs) is dict and set(docs) == names, "Unexpected or missing public documents"
        )
        _require(
            all(type(docs[key]) is dict or docs[key] is None for key in _DOCUMENTS),
            "Public documents must be objects or unavailable",
        )
        if adjudication:
            expected = {
                "review_case_id": case["review_case_id"],
                "overall": None,
                "unassessed_reason": None,
                "rationale": "",
                "checks": [_blank_axis(key, "check_id") for key in _CHECKS],
            }
        else:
            availability = case.get("availability")
            _require(
                type(availability) is dict and set(availability) == set(_DOCUMENTS),
                "Document availability required",
            )
            for key in _DOCUMENTS:
                state = availability[key]
                if docs[key] is None:
                    _require(
                        state.get("status") == "unavailable"
                        and state.get("sha256") is None
                        and type(state.get("reason")) is str,
                        "Unknown document must remain explicitly unavailable",
                    )
                else:
                    _require(
                        state.get("status") == "available"
                        and state.get("sha256") == _digest(docs[key]),
                        "Source document digest mismatch",
                    )
            expected = {
                "review_case_id": case["review_case_id"],
                "identified_target": {
                    "status": None,
                    "patient_id": "",
                    "encounter_id": "",
                    "unassessed_reason": None,
                    "rationale": "",
                    "evidence_refs": [],
                },
                "axes": [_blank_axis(key, "axis_id") for key in _AXES],
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
        _require(
            response == expected,
            ("Response template must contain blank judgments and the exact assigned fields"),
        )
    return cases, definitions


def _pretty(value):
    return escape(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True))


def _source_navigation(documents, case_index, availability, index):
    counter = 0

    def tree(value, document, pointer="", raw_pointer=None):
        nonlocal counter
        identifier = f"source-{case_index}-{counter}"
        counter += 1
        ref = {"document": document, "pointer": pointer if raw_pointer is None else raw_pointer}
        if raw_pointer is not None:
            ref["decoded_json_pointer"] = pointer
        index[(case_index, _json(ref))] = identifier
        label = pointer or "(document root)"
        typename = (
            "object"
            if type(value) is dict
            else "array"
            if type(value) is list
            else "null"
            if value is None
            else type(value).__name__
        )
        body = (
            f'<details class="source-node" id="{identifier}"><summary>'
            f"<code>{escape(label)}</code> · {typename}</summary>"
        )
        if document == "response":
            body += (
                (
                    "<label>Operator response pointer (add to response_pointers"
                    ' array)<input readonly data-response-pointer="true" '
                    'value="'
                )
                + escape(_json(pointer), quote=True)
                + '"></label>'
            )
        else:
            body += (
                (
                    "<label>Copyable source reference (add to evidence_refs "
                    'array)<input readonly data-source-reference="true" value="'
                )
                + escape(_json(ref), quote=True)
                + '"></label>'
            )
        if type(value) in (dict, list):
            children = (
                ((key, value[key]) for key in sorted(value))
                if type(value) is dict
                else enumerate(value)
            )
            if not value:
                body += f"<pre>{_pretty(value)}</pre>"
            for key, child in children:
                token = str(key).replace("~", "~0").replace("/", "~1")
                body += tree(child, document, pointer + "/" + token, raw_pointer)
        else:
            body += (
                '<pre class="literal">'
                + (escape(value) if type(value) is str else _pretty(value))
                + "</pre>"
            )
            if (
                type(value) is str
                and value.lstrip().startswith(("{", "["))
                and raw_pointer is None
                and document != "response"
            ):
                try:
                    decoded = _strict_json(value)
                except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
                    body += (
                        '<p class="unavailable">Decoded JSON unavailable: '
                        + escape(str(exc))
                        + ". Raw captured text above remains available.</p>"
                    )
                else:
                    body += (
                        "<p>Decoded JSON inside this captured string; raw text "
                        "above is unchanged.</p>"
                    )
                    body += tree(decoded, document, "", pointer)
        return body + "</details>"

    documents = {
        key: documents[key]
        for key in (*_DOCUMENTS, "response", "prior_judgments")
        if key in documents
    }
    sections = []
    navigation = (
        '<nav aria-label="Source documents"><ul>'
        + "".join(
            f'<li><a href="#document-{case_index}-{name}">'
            f"{escape(name.replace('_', ' ').title())}</a></li>"
            for name in documents
        )
        + "</ul></nav>"
    )
    for name, value in documents.items():
        heading = name.replace("_", " ").title()
        reason = availability.get(name, {}).get("reason") or "No captured document was supplied."
        content = (
            tree(value, name)
            if value is not None
            else '<p class="unavailable">Unavailable: ' + escape(reason) + "</p>"
        )
        sections.append(
            f'<section class="document" id="document-{case_index}-{name}">'
            f"<h3>{escape(heading)}</h3>{content}</section>"
        )
    return (
        (
            '<section class="sources"><h2>Captured source '
            "documents</h2><p>Expand fields to inspect exact values and"
            " copy a citation. Raw strings remain readable; decoded "
            "JSON is offered only after strict parsing. A missing "
            "document is not an empty record.</p>"
        )
        + navigation
        + "".join(sections)
        + "</section>"
    )


def _refs(refs, case_index, index):
    links = []
    for ref in refs:
        key = (case_index, _json(ref))
        _require(key in index, "Assistance reference does not resolve to a public source")
        links.append(f'<a href="#{index[key]}"><code>{escape(_json(ref))}</code></a>')
    return "<ul>" + "".join("<li>" + link + "</li>" for link in links) + "</ul>"


def _assistance(value, documents, case_index, index):
    if value is None:
        return (
            '<section class="assistance"><h2>Derived '
            "assistance</h2><p>Unavailable; no diagnostic claims "
            "supplied.</p></section>"
        )
    _require(
        value.get("schema_version") == "healthcraft-incident-evidence/v1", "Unsupported assistance"
    )
    _require(
        value.get("document_sha256") == {key: _digest(documents[key]) for key in _DOCUMENTS},
        "Assistance document binding mismatch",
    )
    content = (
        (
            '<section class="assistance"><h2>Derived assistance — '
            "claims to inspect</h2><p>These source-linked observations "
            "are not your answers, report-validity judgments or "
            "clinical conclusions. Availability: "
        )
        + escape(value["status"])
        + ".</p>"
    )
    for claim in value["claims"]:
        content += (
            '<article class="claim"><h3>'
            + escape(claim["category"] + ": " + claim["summary"])
            + "</h3><p><code>"
            + escape(claim["code"])
            + "</code></p><details><summary>Recorded values</summary><pre>"
            + _pretty(claim["observed"])
            + "</pre></details>"
            + _refs(claim["refs"], case_index, index)
            + "</article>"
        )
    content += "<h3>Coverage and limitations</h3><pre>" + _pretty(value["coverage"]) + "</pre><ul>"
    content += "".join(
        "<li>" + escape(str(item)) + "</li>" for item in value.get("limitations", [])
    )
    content += (
        "</ul><p>Unassessed: " + escape(_json(value.get("unassessed", []))) + "</p></section>"
    )
    return content


def _label(text, control):
    return "<label>" + escape(text) + control + "</label>"


def _input(identifier, *, field=None):
    attrs = f' id="{identifier}"' if identifier else ""
    attrs += f' data-field="{field}"' if field else ""
    return '<input type="text"' + attrs + ' value="">'


def _area(identifier, value="", *, field=None):
    attrs = f' id="{identifier}"' if identifier else ""
    attrs += f' data-field="{field}"' if field else ""
    return '<textarea rows="3"' + attrs + ">" + escape(value) + "</textarea>"


def _select(identifier, options, *, field=None, axis=None, blank=True):
    attrs = f' id="{identifier}"' if identifier else ""
    attrs += f' data-field="{field}"' if field else ""
    attrs += f' data-axis="{axis}"' if axis else ""
    entries = ['<option value="">Pending — not answered</option>'] if blank else []
    entries.extend(
        f'<option value="{escape(value, quote=True)}">{escape(label)}</option>'
        for value, label in options
    )
    return "<select" + attrs + ">" + "".join(entries) + "</select>"


def _reason(prefix):
    return _label(
        "Reason when unassessed (optional draft selection)",
        _select(prefix + "-reason", [(v, v.replace("_", " ")) for v in _REASONS]),
    )


def _judgment(prefix, question, *, key=None, adjudication=False):
    choices = (
        ("supported", "unsupported", "unassessed") if adjudication else ("yes", "no", "unassessed")
    )
    content = "<fieldset><legend>" + escape(question) + "</legend>"
    content += _label(
        "Your judgment", _select(prefix + "-judgment", [(v, v) for v in choices], axis=key)
    )
    content += _reason(prefix) + _label(
        "Rationale / unfinished notes", _area(prefix + "-rationale")
    )
    content += _label("Source references (JSON array)", _area(prefix + "-refs", "[]"))
    if adjudication:
        content += _label(
            "Pointers into the original operator case response (JSON array)",
            _area(prefix + "-response-pointers", "[]"),
        )
    return content + "</fieldset>"


def _finding_template(ci):
    content = (
        f'<template id="finding-template-{ci}"><fieldset data-finding="true">'
        "<legend>Incident finding</legend>"
    )
    content += _label("Finding ID", _input(None, field="finding_id"))
    content += _label(
        "Category", _select(None, [(v, v.replace("_", " ")) for v in _CATEGORIES], field="category")
    )
    content += _label("What happened / source-backed claim", _area(None, field="claim"))
    content += _label("Observed patient ID (blank if unknown)", _input(None, field="patient_id"))
    content += _label(
        "Observed encounter ID (blank if unknown)", _input(None, field="encounter_id")
    )
    content += _label(
        "Implicated source IDs (JSON array; [] if none)", _area(None, "[]", field="source_ids")
    )
    content += _label(
        "Supporting source references (JSON array)", _area(None, "[]", field="evidence_refs")
    )
    return content + (
        '<button type="button" data-remove-finding="true">Remove '
        "this finding</button></fieldset></template>"
    )


def _incident_form(case, axes, ci):
    p = f"case-{ci}"
    content = (
        '<section class="response"><h2>Your incident '
        "report</h2><p>Blank statuses stay pending. Typed draft "
        "text and valid citations are preserved without inferring a"
        " judgment.</p><fieldset><legend>Identify the requested "
        "target</legend>"
    )
    content += _label(
        "Target assessment",
        _select(p + "-target-status", [("identified", "Identified"), ("unassessed", "Unassessed")]),
    )
    content += _label("Requested patient ID", _input(p + "-target-patient")) + _label(
        "Requested encounter ID", _input(p + "-target-encounter")
    )
    content += (
        _reason(p + "-target")
        + _label("Target rationale", _area(p + "-target-rationale"))
        + _label("Task/source references (JSON array)", _area(p + "-target-refs", "[]"))
        + "</fieldset>"
    )
    for ai, axis in enumerate(axes):
        content += '<p class="distinction">' + escape(axis["distinction"]) + "</p>"
        content += _judgment(f"{p}-axis-{ai}", axis["question"], key=axis["axis_id"])
    content += "<fieldset><legend>Identify the incident or limitation</legend>"
    content += _label(
        "Incident assessment",
        _select(
            p + "-incident-status",
            [
                ("findings_identified", "Findings identified"),
                ("none_identified", "No incident identified"),
                ("unassessed", "Unassessed"),
            ],
        ),
    )
    content += (
        _reason(p + "-incident")
        + _label("Summary / unfinished notes", _area(p + "-incident-summary"))
        + _label("Overall supporting references (JSON array)", _area(p + "-incident-refs", "[]"))
    )
    content += (
        "<p>A source disagreement or unknown date is not "
        "automatically an error. Separate content, target and "
        "persistence findings from provider, tool, grader and "
        "evidence limitations.</p>"
    )
    content += (
        f'<div id="findings-{ci}"></div>'
        f'<button type="button" data-add-finding="{ci}">Add finding</button>'
        + _finding_template(ci)
        + "</fieldset>"
    )
    content += (
        "<fieldset><legend>Optional manual timing</legend><p>No "
        "timer runs. Times are declarations; invalid timing is "
        "imported separately and must not erase the report. Leave "
        "unknown durations blank.</p>"
    )
    content += _label(
        "Timing provenance",
        _select(
            p + "-timing-method",
            [("not_collected", "Not collected"), ("self_reported", "Self-reported")],
            blank=False,
        ),
    )
    for field in ("elapsed_seconds", "active_seconds", "note"):
        content += _label(field.replace("_", " ").title(), _input(p + "-timing-" + field))
    return content + "</fieldset></section>"


def _adjudication_form(case, definitions, ci):
    p = f"case-{ci}"
    content = (
        '<section class="response"><h2>Independent report validity '
        "— your judgment</h2><p>Assess the original operator report"
        " against captured evidence. A model assertion, derived "
        "diagnosis, schema acceptance or prior vote does not "
        "establish validity.</p>"
    )
    for ai, definition in enumerate(definitions):
        content += _judgment(f"{p}-check-{ai}", definition["question"], adjudication=True)
    content += "<fieldset><legend>Overall report validity</legend>"
    content += _label(
        "Explicit overall judgment",
        _select(
            p + "-overall",
            [("valid", "Valid"), ("invalid", "Invalid"), ("unassessed", "Unassessed")],
        ),
    )
    content += _reason(p + "-overall") + _label(
        "Overall rationale / unfinished notes", _area(p + "-overall-rationale")
    )
    return content + (
        "<p>Leave overall pending while checks remain unfinished. "
        "This is engineering report validity, not a clinical safety"
        " verdict.</p></fieldset></section>"
    )


_SCRIPT = r"""
"use strict";
const packet=JSON.parse(document.getElementById("incident-packet").textContent);
const responseTemplate=JSON.parse(document.getElementById("incident-template").textContent);
const reasons=new Set(["insufficient_evidence",
"conflicting_evidence",
"outside_scope",
"reviewer_abstention"]);
const categories=new Set(["content",
"target",
"persistence",
"execution",
"tool",
"provider",
"grader",
"evidence_gap",
"source_uncertainty"]);
function need(value,
message){
  if(!value)throw new Error(message);
}
function text(value,
label){
  need(typeof value==="string",
  label+" must be text.");
  return value;
}
function nonempty(value,
label){
  text(value,
  label);
  need(value.trim()!=="",
  label+" is required.");
  return value;
}
function nullable(value){
  return value===""?null:value;
}
function clone(value){
  return JSON.parse(JSON.stringify(value));
}
function strictJSON(raw) {
  text(raw, "JSON input");
  const value = JSON.parse(raw);
  const stringToken = /"(?:[^"\\\u0000-\u001f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"/;
  const otherToken = /[{}\[\]:,]|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null/;
  const tokens = raw.match(new RegExp(stringToken.source + "|" + otherToken.source, "g"));
  let pos = 0;
  function visit() {
    const token = tokens[pos++];
    if (token === "{") {
      const seen = new Set();
      if (tokens[pos] === "}") { pos++; return; }
      while (true) {
        const key = JSON.parse(tokens[pos++]);
        need(!seen.has(key), "Duplicate JSON key: " + key);
        seen.add(key); pos++; visit();
        if (tokens[pos++] === "}") return;
      }
    } else if (token === "[") {
      if (tokens[pos] === "]") { pos++; return; }
      while (true) { visit(); if (tokens[pos++] === "]") return; }
    } else if (token[0] !== "\"" && !["true", "false", "null"].includes(token)) {
      need(Number.isFinite(Number(token)), "JSON numbers must be finite.");
    }
  }
  visit();
  return value;
}
function validPointer(p){
  if(typeof p!=="string" || (p!=="" && p[0]!=="/"))return false;
  for(let i=0;
  i<p.length;
  i++)if(p[i]==="~"){
    if(p[i+1]!=="0"&&p[i+1]!=="1")return false;
    i++;
  }
  return true;
}
function resolve(value,
p){
  need(validPointer(p),
  "Invalid RFC6901 pointer.");
  if(p==="")return value;
  for(const raw of p.slice(1).split("/")){
    const key=raw.replace(/~1/g,
    "/").replace(/~0/g,
    "~");
    if(Array.isArray(value)){
      need(/^(0|[1-9][0-9]*)$/.test(key)&&Number(key)<value.length,
      "Array pointer unavailable.");
      value=value[Number(key)];
    }
    else{
      need(value!==null&&typeof value==="object"&&Object.prototype.hasOwnProperty.call(value,
      key),
      "Source pointer unavailable.");
      value=value[key];
    }
  }
  return value;
}
function refs(raw,
docs,
adjudication=false){
  const result=strictJSON(raw);
  need(Array.isArray(result),
  "References must be a JSON array.");
  const seen=new Set();
  for(const ref of result){
    need(ref&&typeof ref==="object"&&!Array.isArray(ref),
    "Malformed reference.");
    need(Object.keys(ref).every(k=>["document",
    "pointer",
    "decoded_json_pointer"].includes(k))&&Object.hasOwn(ref,
    "document")&&Object.hasOwn(ref,
    "pointer"),
    "Unexpected reference fields.");
    const names=["task",
    "scenario",
    "evidence",
    "runtime",
    ...(adjudication?["prior_judgments"]:[])];
    need(names.includes(ref.document)&&docs[ref.document]!==null&&docs[ref.document]!==undefined,
    "Referenced document unavailable.");
    let value=resolve(docs[ref.document],
    ref.pointer);
    if(Object.hasOwn(ref,
    "decoded_json_pointer")){
      need(typeof value==="string",
      "Decoded reference must address captured text.");
      resolve(strictJSON(value),
      ref.decoded_json_pointer);
    }
    const key=JSON.stringify([ref.document,
    ref.pointer,
    ref.decoded_json_pointer]);
    need(!seen.has(key),
    "Duplicate source reference.");
    seen.add(key);
  }
  return result;
}
function reason(value){
  text(value,
  "Unassessed reason");
  need(value===""||reasons.has(value),
  "Unsupported unassessed reason.");
  return nullable(value);
}
function answer(input,
output,
docs,
adjudication=false){
  const judgment=text(input.judgment,
  "Judgment"),
  rationale=text(input.rationale,
  "Rationale"),
  why=reason(input.unassessed_reason);
  const evidence=refs(input.evidence_refs,
  docs,
  adjudication);
  const allowed=adjudication?["supported",
  "unsupported",
  "unassessed"]:["yes",
  "no",
  "unassessed"];
  need(judgment===""||allowed.includes(judgment),
  "Unsupported judgment.");
  let pointers=[];
  if(adjudication){
    pointers=strictJSON(input.response_pointers);
    need(Array.isArray(pointers)&&new Set(pointers).size===pointers.length,
    "Response pointers must be a unique array.");
    for(const p of pointers){
      need(docs.response!==null,
      "Original operator response unavailable.");
      resolve(docs.response,
      p);
    }
  }
  if(judgment!==""){
    nonempty(rationale,
    "Rationale");
    if(judgment==="unassessed")need(why!==null,
    "Unassessed judgment requires a reason.");
    else need(why===null&&evidence.length>0&&(!adjudication||pointers.length>0),
    (
    "Assessed judgment requires source citations, response pointers " +
    "when adjudicating, and no abstention reason."
    ));
  }
  output.judgment=nullable(judgment);
  output.unassessed_reason=why;
  output.rationale=rationale;
  output.evidence_refs=evidence;
  if(adjudication)output.response_pointers=pointers;
}
function timingNumber(raw){
  text(raw,
  "Timing value");
  if(raw.trim()==="")return null;
  const n=Number(raw);
  return Number.isFinite(n)&&
    /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(raw.trim())?n:raw;
}
function cohort(values,
template){
  need(values&&Array.isArray(values.cases)&&values.cases.length===template.cases.length,
  "Every assigned case must remain present.");
  return clone(template);
}
function buildIncidentResponse(values,
template,
sourcePacket){
  const result=cohort(values,
  template);
  result.cases.forEach((row,
  ci)=>{
    const input=values.cases[ci],
    docs=sourcePacket.cases[ci].documents;
    const t=input.identified_target;
    need(t&&typeof t==="object",
    "Target fields required.");
    const status=text(t.status,
    "Target status"),
    patient=text(t.patient_id,
    "Patient ID"),
    encounter=text(t.encounter_id,
    "Encounter ID"),
    why=reason(t.unassessed_reason),
    rationale=text(t.rationale,
    "Target rationale"),
    evidence=refs(t.evidence_refs,
    docs);
    need(["",
    "identified",
    "unassessed"].includes(status),
    "Unsupported target status.");
    if(status!==""){
      nonempty(rationale,
      "Target rationale");
      if(status==="identified"){
        nonempty(patient,
        "Patient ID");
        nonempty(encounter,
        "Encounter ID");
        need(why===null&&evidence.some(r=>["task",
        "scenario"].includes(r.document)),
        "Identified target needs a task/source citation and no abstention reason.");
      }
      else need(why!==null,
      "Unknown target requires a reason.");
    }
    row.identified_target={
      status:nullable(status),
      patient_id:patient,
      encounter_id:encounter,
      unassessed_reason:why,
      rationale,
      evidence_refs:evidence}
    ;
    need(Array.isArray(input.axes)&&input.axes.length===row.axes.length,
    "Every assigned axis must remain present.");
    row.axes.forEach((axis,
    ai)=>answer(input.axes[ai],
    axis,
    docs));
    const incident=input.incident_assessment;
    const state=text(incident.status,
    "Incident status"),
    summary=text(incident.summary,
    "Incident summary"),
    incidentReason=reason(incident.unassessed_reason),
    incidentRefs=refs(incident.evidence_refs,
    docs);
    need(["",
    "findings_identified",
    "none_identified",
    "unassessed"].includes(state),
    "Unsupported incident status.");
    need(Array.isArray(incident.findings),
    "Findings must remain an array.");
    const ids=new Set();
    const findings=incident.findings.map(f=>{
      const id=nonempty(f.finding_id,
      "Finding ID");
      need(id.length<=64&&/^[A-Za-z0-9][A-Za-z0-9_-]*$/.test(id)&&!/[\r\n]/.test(id),
      (
      "Finding ID must use ASCII letters, digits, underscore or hyphen," +
      " beginning with a letter or digit."
      ));
      need(!ids.has(id.toLowerCase()),
      "Duplicate finding ID.");
      ids.add(id.toLowerCase());
      need(categories.has(f.category),
      "Choose a finding category.");
      const claim=text(f.claim,
      "Finding claim"),
      sourceIds=strictJSON(f.source_ids);
      need(Array.isArray(sourceIds)&&sourceIds.every(v=>typeof v==="string"&&v.trim()!==""),
      "Source IDs must be nonempty strings.");
      need(new Set(sourceIds).size===sourceIds.length,
      "Duplicate source ID.");
      const citations=refs(f.evidence_refs,
      docs);
      if(state!==""){
        nonempty(claim,
        "Finding claim");
        need(citations.length>0,
        "Finding requires source evidence.");
      }
      const p=text(f.observed_target.patient_id,
      "Observed patient ID"),
      e=text(f.observed_target.encounter_id,
      "Observed encounter ID");
      need(p===""||p.trim()!=="",
      "Observed patient ID is blank whitespace.");
      need(e===""||e.trim()!=="",
      "Observed encounter ID is blank whitespace.");
      return {
        finding_id:id,
        category:f.category,
        claim,
        observed_target:{
          patient_id:nullable(p),
          encounter_id:nullable(e)}
        ,
        source_ids:sourceIds,
        evidence_refs:citations}
      ;
    }
    );
    if(state!==""){
      nonempty(summary,
      "Incident summary");
      if(state==="unassessed")need(incidentReason!==null&&findings.length===0,
      "Unassessed incident needs a reason and no asserted findings.");
      else{
        need(incidentReason===null&&incidentRefs.length>0,
        "Incident assessment requires references and no abstention reason.");
        need(state==="findings_identified"?findings.length>0:findings.length===0,
        "Finding list contradicts incident status.");
      }
    }
    row.incident_assessment={
      status:nullable(state),
      summary,
      findings,
      unassessed_reason:incidentReason,
      evidence_refs:incidentRefs}
    ;
    const time=input.timing;
    row.timing={
      method:text(time.method,
      "Timing method"),
      elapsed_seconds:timingNumber(time.elapsed_seconds),
      active_seconds:timingNumber(time.active_seconds),
      note:text(time.note,
      "Timing note")}
    ;
  }
  );
  return result;
}
function buildAdjudicationResponse(values,
template,
sourcePacket){
  const result=cohort(values,
  template);
  result.cases.forEach((row,
  ci)=>{
    const input=values.cases[ci],
    docs=sourcePacket.cases[ci].documents;
    need(Array.isArray(input.checks)&&input.checks.length===row.checks.length,
    "All four validity checks must remain present.");
    row.checks.forEach((check,
    i)=>answer(input.checks[i],
    check,
    docs,
    true));
    const overall=text(input.overall,
    "Overall judgment"),
    why=reason(input.unassessed_reason),
    rationale=text(input.rationale,
    "Overall rationale");
    need(["",
    "valid",
    "invalid",
    "unassessed"].includes(overall),
    "Unsupported overall judgment.");
    if(overall!==""){
      nonempty(rationale,
      "Overall rationale");
      need(row.checks.every(c=>c.judgment!==null),
      "Complete all four checks before an overall judgment.");
      const judgments=row.checks.map(c=>c.judgment);
      if(overall==="valid"){
        need(why===null&&judgments.every(j=>j==="supported"),
        "Valid requires all four checks supported.");
        need(sourcePacket.cases[ci].operator_report_status!=="pending",
        "An unfinished operator report cannot be declared valid.");
      }
      if(overall==="invalid")need(why===null&&judgments.includes("unsupported"),
      "Invalid requires an unsupported check.");
      if(overall==="unassessed")need(why!==null&&judgments.includes("unassessed")&&!judgments.includes("unsupported"),
      "Unassessed requires an unassessed check, a reason and no unsupported checks.");
    }
    row.overall=nullable(overall);
    row.unassessed_reason=why;
    row.rationale=rationale;
  }
  );
  const d=values.reviewer_declaration;
  need(d&&["",
  "true",
  "false"].includes(d.independent_review),
  "Choose a declaration or leave unknown.");
  result.reviewer_declaration={
    independent_review:d.independent_review===""?null:d.independent_review==="true",
    qualifications:text(d.qualifications,
    "Qualifications"),
    conflicts:text(d.conflicts,
    "Conflicts")}
  ;
  return result;
}
function value(id){
  return document.getElementById(id).value;
}
function readJudgment(prefix,
adjudication=false){
  const row={
    judgment:value(prefix+"-judgment"),
    unassessed_reason:value(prefix+"-reason"),
    rationale:value(prefix+"-rationale"),
    evidence_refs:value(prefix+"-refs")}
  ;
  if(adjudication)row.response_pointers=value(prefix+"-response-pointers");
  return row;
}
function readIncidentForm(){
  return {
    cases:responseTemplate.cases.map((row,
    ci)=>{
      const p=`case-${ci}`;
      return {
        identified_target:{
          status:value(p+"-target-status"),
          patient_id:value(p+"-target-patient"),
          encounter_id:value(p+"-target-encounter"),
          unassessed_reason:value(p+"-target-reason"),
          rationale:value(p+"-target-rationale"),
          evidence_refs:value(p+"-target-refs")}
        ,
        axes:row.axes.map((_,
        ai)=>readJudgment(`${p}-axis-${ai}`)),
        incident_assessment:{
          status:value(p+"-incident-status"),
          summary:value(p+"-incident-summary"),
          unassessed_reason:value(p+"-incident-reason"),
          evidence_refs:value(p+"-incident-refs"),
          findings:Array.from(document.getElementById(`findings-${ci}`).querySelectorAll("[data-finding]")).map(node=>{
            const f=k=>node.querySelector(`[data-field="${k}"]`).value;
            return {
              finding_id:f("finding_id"),
              category:f("category"),
              claim:f("claim"),
              observed_target:{
                patient_id:f("patient_id"),
                encounter_id:f("encounter_id")}
              ,
              source_ids:f("source_ids"),
              evidence_refs:f("evidence_refs")}
            ;
          }
          )}
        ,
        timing:{
          method:value(p+"-timing-method"),
          elapsed_seconds:value(p+"-timing-elapsed_seconds"),
          active_seconds:value(p+"-timing-active_seconds"),
          note:value(p+"-timing-note")}
      }
      ;
    }
    )}
  ;
}
function readAdjudicationForm(){
  return {
    cases:responseTemplate.cases.map((row,
    ci)=>({
      checks:row.checks.map((_,
      i)=>readJudgment(`case-${ci}-check-${i}`,
      true)),
      overall:value(`case-${ci}-overall`),
      unassessed_reason:value(`case-${ci}-overall-reason`),
      rationale:value(`case-${ci}-overall-rationale`)}
    )),
    reviewer_declaration:{
      independent_review:value("declaration-independent"),
      qualifications:value("declaration-qualifications"),
      conflicts:value("declaration-conflicts")}
  }
  ;
}
const findingCounters={
}
;
for(const button of document.querySelectorAll("[data-add-finding]"))button.addEventListener("click",
()=>{
  const ci=button.dataset.addFinding,
  fragment=document.getElementById(`finding-template-${ci}`).content.cloneNode(true);
  findingCounters[ci]=(findingCounters[ci]||0)+1;
  fragment.querySelector('[data-field="finding_id"]').value=`finding-${findingCounters[ci]}`;
  const node=fragment.querySelector("[data-finding]");
  fragment.querySelector("[data-remove-finding]").addEventListener("click",
  ()=>node.remove());
  document.getElementById(`findings-${ci}`).appendChild(fragment);
}
);
for(const anchor of document.querySelectorAll('a[href^="#source-"]'))
anchor.addEventListener("click",
()=>{
  let node=document.getElementById(anchor.getAttribute("href").slice(1));
  while(node){
    if(node.tagName==="DETAILS")node.open=true;
    node=node.parentElement;
  }
}
);
document.getElementById("download-response").addEventListener("click",
()=>{
  const status=document.getElementById("export-status");
  try{
    const adjudication=
      packet.schema_version==="healthcraft-operator-incident-adjudication-packet/v2";
    const result=adjudication?buildAdjudicationResponse(readAdjudicationForm(),
    responseTemplate,
    packet):buildIncidentResponse(readIncidentForm(),
    responseTemplate,
    packet);
    const blob=new Blob([JSON.stringify(result,
    null,
    2)+"\n"],
    {
      type:"application/json"}
    ),
    url=URL.createObjectURL(blob),
    link=document.createElement("a");
    link.href=url;
    link.download=adjudication?"incident-adjudication.json":"incident-response.json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    status.textContent=(
    "Exported with original assignment identity. Pending fields " +
    "remain pending. Import validates structure; timing is checked " +
    "separately. Export does not establish report validity or " +
    "clinical safety."
    );
  }
  catch(error){
    status.textContent="Not exported: "+error.message+" Your entered fields remain in this form.";
  }
}
);
"""


_STYLE = """
body{font:16px/1.5 system-ui,sans-serif;
  margin:0;
  color:#152735;
  background:#f3f6f8}
main{max-width:1160px;
  margin:auto;
  padding:28px}
h1,h2,h3{line-height:1.2}
header,.case,section.response{background:white;
  border:1px solid #ccd7de;
  border-radius:10px;
  padding:22px;
  margin:18px 0}
nav ul{display:flex;
  flex-wrap:wrap;
  gap:16px;
  list-style:none;
  padding:0}
a{color:#075a80}
label{display:block;
  font-weight:600;
  margin:14px 0}
input,textarea,select{display:block;
  width:100%;
  box-sizing:border-box;
  margin-top:5px;
  padding:9px;
  border:1px solid #899ca9;
  border-radius:4px;
  font:inherit}
textarea{font-family:ui-monospace,monospace}
input[readonly]{font:12px/1.4 ui-monospace,monospace;
  background:#f4f7fa}
fieldset{border:1px solid #adbfc9;
  border-radius:6px;
  margin:20px 0;
  padding:18px}
legend{font-weight:700;
  padding:0 8px}
button{padding:10px 16px;
  background:#125e7b;
  color:white;
  border:0;
  border-radius:5px;
  cursor:pointer;
  font:inherit;
  margin:8px 8px 8px 0}
summary{cursor:pointer;
  padding:7px}
.source-node{margin:5px 0 5px 14px;
  border-left:2px solid #cad8e0;
  padding-left:9px}
.document{margin:18px 0}
.source-node:target{outline:3px solid #eab64a}
.literal,pre{white-space:pre-wrap;
  overflow-wrap:anywhere;
  background:#f4f7fa;
  padding:10px;
  font-size:13px}
.unavailable{border-left:4px solid #9e641d;
  padding:10px;
  background:#fff5e5}
.assistance{border:2px solid #9ab5c5;
  padding:18px;
  background:#f7fbfd}
.claim{padding:10px 0;
  border-bottom:1px solid #d7e0e5}
.distinction{color:#465c6b}
.export{position:sticky;
  bottom:0;
  background:#eaf2f6;
  border-top:1px solid #b5c9d5;
  padding:12px}
#export-status{margin:5px 0;
  font-size:14px}
@media(max-width:650px){main{padding:12px}
.case{padding:12px}
.source-node{margin-left:4px}
fieldset{padding:10px}
}

"""


def _render(packet, template, adjudication):
    cases, definitions = _validate(packet, template, adjudication)
    title = (
        "Adjudicate an operator incident report"
        if adjudication
        else "Review a captured source-reconciliation attempt"
    )
    index = {}
    content = (
        (
            '<!doctype html><html lang="en"><head><meta '
            'charset="utf-8"><meta name="viewport" '
            'content="width=device-width,initial-scale=1"><title>'
        )
        + title
        + "</title><style>"
        + _STYLE
        + "</style></head><body><main><header><h1>"
        + title
        + (
            "</h1><p>Offline development workflow. Recorded evidence, "
            "derived assistance and your judgments remain separate. No "
            "clinical validation or automatic correctness decision is "
            "produced. No timer runs.</p>"
        )
    )
    content += (
        "<p>Assignment <code>"
        + escape(packet["assignment_id"])
        + "</code> · "
        + (
            "Adjudicator declaration is self-reported."
            if adjudication
            else "Presentation: " + escape(packet["presentation"])
        )
        + '</p><nav aria-label="Assigned cases"><ul>'
    )
    content += (
        "".join(
            f'<li><a href="#case-{ci}">{escape(case["review_case_id"])}</a></li>'
            for ci, case in enumerate(cases)
        )
        + "</ul></nav><ul>"
    )
    content += (
        "".join("<li>" + escape(item) + "</li>" for item in packet.get("limitations", []))
        + "</ul></header>"
    )
    for ci, case in enumerate(cases):
        content += f'<article class="case" id="case-{ci}"><h2>{escape(case["review_case_id"])}</h2>'
        family = case["scenario_family_id"]
        content += (
            "<p>Scenario family: <code>"
            + ("Unknown — not captured" if family is None else escape(family))
            + "</code></p>"
        )
        content += _source_navigation(case["documents"], ci, case.get("availability", {}), index)
        if adjudication:
            content += (
                "<p>Imported operator report status: <strong>"
                + escape(case["operator_report_status"])
                + ("</strong>. This describes response completeness, not correctness.</p>")
            )
            content += _adjudication_form(case, definitions, ci)
        else:
            if packet["presentation"] == "assisted":
                content += _assistance(case["assistance"], case["documents"], ci, index)
            content += _incident_form(case, definitions, ci)
        content += "</article>"
    if adjudication:
        content += (
            '<section class="response"><h2>Reviewer '
            "declaration</h2><p>These declarations are retained, not "
            "authenticated. They do not establish independence, "
            "qualifications or clinical validation.</p>"
        )
        content += _label(
            "Independent review declaration",
            _select("declaration-independent", [("true", "Yes, self-declared"), ("false", "No")]),
        )
        content += (
            _label("Qualifications (self-reported)", _area("declaration-qualifications"))
            + _label("Conflicts (self-reported)", _area("declaration-conflicts"))
            + "</section>"
        )
    content += (
        "<p>For source references, copy one or more entries from "
        "the source navigator into a JSON array, for example <code>"
        "[{&quot;document&quot;:&quot;task&quot;,&quot;pointer&quot"
        ";:&quot;&quot;}]</code>. Cite only available documents. "
        "For an absent field, cite its existing parent and explain "
        "the absence.</p>"
    )
    content += (
        '<section class="export"><button type="button" '
        'id="download-response">Export response JSON</button><p '
        'id="export-status" role="status">Leave judgments blank to '
        "retain pending work. Save the downloaded response outside "
        "the original immutable packet.</p></section>"
    )
    content += (
        '<script id="incident-packet" type="application/json">'
        + _embedded(packet)
        + '</script><script id="incident-template" type="application/json">'
        + _embedded(template)
        + '</script><script id="incident-app">'
        + _SCRIPT
        + "</script></main></body></html>"
    )
    return content


def render_incident_packet(packet: dict, template: dict) -> str:
    "Render blank operator decisions beside common raw/assisted public sources."
    return _render(packet, template, False)


def render_adjudication_packet(packet: dict, template: dict) -> str:
    "Render blank independent validity judgments bound to an operator response."
    return _render(packet, template, True)
