"""Offline presentation and manual response export for operator tutorial packets.

This module does not import the packet/import core. It validates the supplied
packet and blank template, regenerates the mechanical explanation, and presents
recorded data separately from the operator's answers. No timing is measured.
"""

from __future__ import annotations

import hashlib
import json
import math
from html import escape

from healthcraft.reconciliation.diagnostics import explain_reconciliation
from healthcraft.reconciliation.oracle import verify_reconciliation

_AXES = (
    "execution_completion",
    "write_acknowledgement",
    "storage",
    "readback",
    "reconciliation_correctness",
    "evidence_sufficiency",
)
_REASONS = (
    "insufficient_evidence",
    "conflicting_evidence",
    "outside_scope",
    "reviewer_abstention",
)
_DOCUMENTS = {
    "scenario": ("Authored scenario", "Synthetic source assertions and target identities."),
    "evidence": ("Observed evidence", "Captured requests, responses, audit and state snapshots."),
    "expectations": (
        "Engineering expected contract",
        "Source/persistence expectations, not clinical truth.",
    ),
    "oracle": ("Mechanical oracle", "Recorded mechanical checks, not your review answers."),
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError("Invalid operator presentation: " + message)


def _json(value) -> str:
    def validate(item):
        if type(item) is dict:
            _require(all(type(key) is str for key in item), "JSON keys must be strings")
            for child in item.values():
                validate(child)
        elif type(item) is list:
            for child in item:
                validate(child)
        else:
            _require(type(item) in (str, int, float, bool, type(None)), "unsupported JSON value")
            _require(type(item) is not float or math.isfinite(item), "non-finite JSON")

    try:
        validate(value)
        text = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        text.encode("utf-8")
        return text
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("Invalid operator presentation JSON") from exc


def _digest(value) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _keys(value, expected: set[str], name: str) -> None:
    _require(type(value) is dict and set(value) == expected, name + " fields mismatch")


def _text(value, name: str) -> None:
    _require(type(value) is str and bool(value.strip()), name + " must be nonempty text")


def _validate(packet: dict, template: dict) -> list[dict]:
    _json(packet)
    _json(template)
    _keys(
        packet,
        {
            "schema_version",
            "packet_id",
            "assignment_id",
            "reviewer_id",
            "presentation",
            "protocol",
            "scope",
            "cases",
            "limitations",
        },
        "packet",
    )
    _keys(
        template,
        {"schema_version", "packet_id", "packet_sha256", "assignment_id", "reviewer_id", "cases"},
        "response template",
    )
    _require(
        packet["schema_version"] == "healthcraft-operator-review-packet/v1",
        "unsupported packet version",
    )
    _require(
        template["schema_version"] == "healthcraft-operator-review-response/v1",
        "unsupported response version",
    )
    for key in ("packet_id", "assignment_id", "reviewer_id"):
        _text(packet[key], key)
        _require(template[key] == packet[key], key + " mismatch")
    _require(template["packet_sha256"] == _digest(packet), "packet digest mismatch")
    _require(packet["presentation"] in ("raw", "assisted"), "unsupported presentation")
    _keys(packet["protocol"], {"protocol_id", "purpose"}, "protocol")
    _text(packet["protocol"]["protocol_id"], "protocol_id")
    _require(packet["protocol"]["purpose"] == "engineering_tutorial", "unsupported purpose")
    _require(packet["scope"] == "exposed_tutorial_operator_review", "unsupported scope")
    _require(type(packet["limitations"]) is list, "limitations must be a list")
    for item in packet["limitations"]:
        _text(item, "limitation")
    _require(type(packet["cases"]) is list and bool(packet["cases"]), "cases must be nonempty")
    _require(
        type(template["cases"]) is list and len(template["cases"]) == len(packet["cases"]),
        "case denominator mismatch",
    )
    seen = set()
    explanations = []
    for case, response in zip(packet["cases"], template["cases"], strict=True):
        _keys(
            case,
            {
                "case_id",
                "scenario_family_id",
                "source_bindings",
                "documents",
                "explanation",
                "axes",
            },
            "case",
        )
        _keys(response, {"case_id", "axes", "timing"}, "response case")
        _text(case["case_id"], "case_id")
        _text(case["scenario_family_id"], "scenario_family_id")
        _require(case["case_id"] not in seen, "duplicate case_id")
        seen.add(case["case_id"])
        _require(response["case_id"] == case["case_id"], "response case identity mismatch")
        docs = case["documents"]
        _keys(docs, set(_DOCUMENTS), "documents")
        _require(all(type(value) is dict for value in docs.values()), "documents must be objects")
        _require(
            case["source_bindings"]
            == {key + "_sha256": _digest(value) for key, value in docs.items()},
            "source bindings mismatch",
        )
        arguments = [docs[name] for name in ("scenario", "expectations", "evidence")]
        _require(
            _json(verify_reconciliation(*arguments)) == _json(docs["oracle"]), "oracle mismatch"
        )
        explanation = explain_reconciliation(*arguments)
        _require(_json(explanation) == _json(case["explanation"]), "explanation mismatch")
        explanations.append(explanation)
        _require(
            type(case["axes"]) is list and len(case["axes"]) == 6, "six assigned axes required"
        )
        _require(
            type(response["axes"]) is list and len(response["axes"]) == 6,
            "six response axes required",
        )
        axis_ids = []
        for axis, row in zip(case["axes"], response["axes"], strict=True):
            _keys(axis, {"axis_id", "question", "scope_note"}, "axis")
            _text(axis["question"], "axis question")
            _text(axis["scope_note"], "axis scope note")
            axis_ids.append(axis["axis_id"])
            _require(
                row
                == {
                    "axis_id": axis["axis_id"],
                    "judgment": None,
                    "unassessed_reason": None,
                    "evidence_refs": [],
                    "rationale": "",
                },
                "response axes must be blank",
            )
        _require(
            len(set(axis_ids)) == 6 and set(axis_ids) == set(_AXES), "unsupported or duplicate axes"
        )
        _require(
            response["timing"]
            == {
                "method": "not_collected",
                "elapsed_seconds": None,
                "active_seconds": None,
                "note": "",
            },
            "timing template must be blank",
        )
    return explanations


def _pretty(value) -> str:
    return escape(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))


def _source_navigation(value: dict, document: str, case_index: int) -> str:
    """Expose bounded-depth pointers without reparsing values in JavaScript."""
    entries = []

    def children(parent, pointer):
        items = (
            parent.items()
            if type(parent) is dict
            else enumerate(parent)
            if type(parent) is list
            else []
        )
        return [
            (pointer + "/" + str(key).replace("~", "~0").replace("/", "~1"), child)
            for key, child in items
        ]

    for pointer, child in children(value, ""):
        entries.append((pointer, child))
        entries.extend(children(child, pointer))
    links, cards = [], []
    for number, (pointer, child) in enumerate(entries):
        identifier = f"source-{case_index}-{document}-{number}"
        reference = _json({"document": document, "pointer": pointer})
        links.append(f'<li><a href="#{identifier}"><code>{escape(pointer)}</code></a></li>')
        cards.append(
            f'<article id="{identifier}" class="source-value">'
            f"<h4><code>{escape(pointer)}</code></h4>"
            f'<label for="{identifier}-ref">Copyable source reference</label>'
            f'<input id="{identifier}-ref" type="text" readonly data-source-reference="true" '
            f'data-value-sha256="{_digest(child)}" value="{escape(reference, quote=True)}">'
            "<details><summary>Read exact captured value</summary>"
            f'<pre data-source-value="{identifier}">{_pretty(child)}</pre></details></article>'
        )
    return (
        "<p>Browse top-level fields and their immediate children. These pointers address this "
        "captured document; deeper values remain in the complete JSON. Copy a reference into "
        "your evidence-reference array; nothing is selected as an answer.</p>"
        '<nav aria-label="Source field pointers"><ul>'
        + "".join(links)
        + "</ul></nav>"
        + "".join(cards)
    )


def _refs(references: list[dict], case_index: int) -> str:
    return (
        "<ul>"
        + "".join(
            f'<li><a href="#document-{case_index}-{escape(ref["document"])}">'
            f"{escape(_DOCUMENTS[ref['document']][0])}</a>: "
            f"<code>{escape(ref['pointer'] or '(document root)')}</code>"
            + (
                " · inside JSON note <code>"
                f"{escape(ref['decoded_json_pointer'] or '(root)')}</code>"
                if "decoded_json_pointer" in ref
                else ""
            )
            + "</li>"
            for ref in references
        )
        + "</ul>"
    )


def _assistance(explanation: dict, case_index: int) -> str:
    content = (
        '<section class="assistance"><h3>Automated explanation</h3>'
        "<p>This is recomputed mechanical assistance, "
        "not your response or clinical adjudication.</p>"
    )
    if explanation["status"] == "unavailable":
        content += (
            '<p role="status">Explanation unavailable; recorded event counts are unknown.</p>'
        )
        content += (
            "<ul>"
            + "".join(f"<li>{escape(error['message'])}</li>" for error in explanation["errors"])
            + "</ul>"
        )
    else:
        observed = explanation["observed_execution"]
        content += (
            "<dl>"
            + "".join(
                f"<dt>{label}</dt><dd>{len(observed[key])}</dd>"
                for key, label in (
                    ("successful_write_calls", "Write acknowledgements"),
                    ("new_stored_notes", "New notes in final storage"),
                    ("deduplicated_retries", "Acknowledged identical retries"),
                )
            )
            + "</dl><p>Acknowledgements and real stored notes "
            "do not establish correct reconciliation.</p>"
        )
        for note in explanation["notes"]:
            rb = note["readback"]
            content += f"<article><h4>Write {escape(note['call_id'])}</h4>"
            content += _refs([note["reference"]], case_index)
            stored_ids = ", ".join(note["matching_stored_note_ids"]) or "None recorded"
            content += f"<p>Matching final note IDs: <code>{escape(stored_ids)}</code>.</p>"
            content += (
                "<p>Post-write successful target reads: "
                f"{len(rb['successful_target_call_ids'])}; reads containing matching stored text: "
                f"{len(rb['stored_text_seen_call_ids'])}. "
                "This is separate from the full oracle result.</p>"
            )
            content += _refs(rb["references"], case_index)
            for issue in note["scope_exclusions"]["issues"]:
                content += f'<div class="issue"><h5>{escape(issue["code"].replace("_", " "))}</h5>'
                for name in ("source_id", "field", "message"):
                    if name in issue:
                        content += f"<p>{escape(name)}: {escape(issue[name])}</p>"
                for name in ("observed", "expected"):
                    if name in issue:
                        content += f"<h6>{name.title()} value</h6><pre>{_pretty(issue[name])}</pre>"
                content += (
                    _refs(issue["evidence_refs"] + issue.get("expectation_refs", []), case_index)
                    + "</div>"
                )
            content += "</article>"
    return (
        content
        + "<p>Observation/conflict content, retrieval coverage and clinical validity remain "
        "unassessed by this explanation. Source hashes establish identity, "
        "not execution authenticity.</p></section>"
    )


def _select(identifier: str, options: list[tuple[str, str]], *, axis: str | None = None) -> str:
    extra = f' data-axis="{escape(axis)}"' if axis is not None else ""
    return (
        f'<select id="{identifier}"{extra}>'
        + "".join(
            f'<option value="{escape(value)}">{escape(label)}</option>' for value, label in options
        )
        + "</select>"
    )


def _case_form(case: dict, index: int) -> str:
    rows = []
    for position, axis in enumerate(case["axes"]):
        prefix = f"case-{index}-axis-{position}"
        rows.append(
            f"<fieldset><legend>{escape(axis['question'])}</legend><p>{escape(axis['scope_note'])}</p>"
            f'<label for="{prefix}-judgment">Your assessment</label>'
            + _select(
                prefix + "-judgment",
                [
                    ("", "Pending — unanswered"),
                    ("yes", "Yes"),
                    ("no", "No"),
                    ("unassessed", "Unassessed / abstain"),
                ],
                axis=axis["axis_id"],
            )
            + f'<label for="{prefix}-reason">Reason, only when unassessed</label>'
            + _select(
                prefix + "-reason",
                [("", "No reason selected")] + [(key, key.replace("_", " ")) for key in _REASONS],
            )
            + f'<label for="{prefix}-refs">Evidence references (JSON array)</label>'
            f'<textarea id="{prefix}-refs" rows="3" spellcheck="false">[]</textarea>'
            f'<label for="{prefix}-rationale">Your rationale</label>'
            f'<textarea id="{prefix}-rationale" rows="3"></textarea></fieldset>'
        )
    prefix = f"case-{index}-timing"
    rows.append(
        "<fieldset><legend>Optional manual timing</legend><p>No timer runs on this page. "
        "These values are self-reported, not verified measurements. "
        "Leave an unknown duration blank.</p>"
        + f'<label for="{prefix}-method">Timing provenance</label>'
        + _select(
            prefix + "-method",
            [("not_collected", "Not collected"), ("self_reported", "Self-reported")],
        )
        + f'<label for="{prefix}-elapsed">Elapsed seconds, if self-reported</label>'
        f'<input id="{prefix}-elapsed" type="number" min="0" step="any">'
        f'<label for="{prefix}-active">Active review seconds, if self-reported</label>'
        f'<input id="{prefix}-active" type="number" min="0" step="any">'
        f'<label for="{prefix}-note">Timing note</label>'
        f'<textarea id="{prefix}-note" rows="2"></textarea></fieldset>'
    )
    return (
        '<section class="response"><h3>Your incident review</h3>'
        "<p>Recorded facts above are not prefilled answers. Blank questions remain pending.</p>"
        + "".join(rows)
        + "</section>"
    )


_SCRIPT = r"""
"use strict";
const responseTemplate = JSON.parse(
  document.getElementById("operator-response-template").textContent);
const reasons = new Set([
  "insufficient_evidence","conflicting_evidence","outside_scope","reviewer_abstention"]);
const documents = new Set(["scenario","expectations","evidence","oracle"]);
function requireValue(condition,message) { if (!condition) throw new Error(message); }
function pointerValid(value) {
  if (typeof value !== "string" || (value !== "" && value[0] !== "/")) return false;
  for (let i=0;i<value.length;i++) if(value[i]==="~") {
    if (value[i+1]!=="0" && value[i+1]!=="1") return false; i++;
  }
  return true;
}
function strictJSON(text) {
  // Parse the entire grammar first, then inspect decoded keys before accepting it.
  const value=JSON.parse(text);
  const stringToken=/"(?:[^"\\\u0000-\u001f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"/;
  const otherToken=/[{}\[\]:,]|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null/;
  const tokens=text.match(new RegExp(stringToken.source+"|"+otherToken.source,"g"));
  let position=0;
  function visit() {
    const token=tokens[position++];
    if(token==="{") {
      const keys=new Set();
      if(tokens[position]==="}") {position++;return;}
      while(true) {
        const key=JSON.parse(tokens[position++]);
        requireValue(!keys.has(key),"Duplicate JSON key: "+key);keys.add(key);
        position++;visit();
        if(tokens[position++]==="}") return;
      }
    } else if(token==="[") {
      if(tokens[position]==="]") {position++;return;}
      while(true) {visit();if(tokens[position++]==="]") return;}
    } else if(token[0]!=="\"" && !["true","false","null"].includes(token)) {
      requireValue(Number.isFinite(Number(token)),"JSON numbers must be finite.");
    }
  }
  visit();return value;
}
function evidenceRefs(text) {
  const refs=strictJSON(text);
  requireValue(Array.isArray(refs),"Evidence references must be a JSON array.");
  const seen=new Set();
  for(const ref of refs) {
    requireValue(ref!==null && typeof ref==="object" && !Array.isArray(ref),
      "Invalid evidence reference.");
    const keys=["document","pointer","decoded_json_pointer"];
    requireValue(Object.keys(ref).every(key=>keys.includes(key)) &&
      documents.has(ref.document) && pointerValid(ref.pointer),
      "Use a common document and valid RFC6901 pointer.");
    requireValue(!Object.hasOwn(ref,"decoded_json_pointer") ||
      pointerValid(ref.decoded_json_pointer),"Invalid decoded-note pointer.");
    const key=JSON.stringify([ref.document,ref.pointer,ref.decoded_json_pointer]);
    requireValue(!seen.has(key),"Duplicate evidence reference.");seen.add(key);
  }
  return refs;
}
function numberOrNull(text) {
  requireValue(typeof text==="string","Timing must be entered as text.");
  if(text.trim()==="") return null;
  requireValue(/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(text),
    "Timing requires nonnegative decimal seconds.");
  const value=Number(text);
  requireValue(Number.isFinite(value),"Timing must be finite.");return value;
}
function buildOperatorResponse(values,template) {
  requireValue(values && Array.isArray(values.cases) &&
    values.cases.length===template.cases.length,"Every assigned case must remain present.");
  const result=JSON.parse(JSON.stringify(template));
  result.cases.forEach((row,ci)=>{
    const input=values.cases[ci];
    requireValue(input && Array.isArray(input.axes) && input.axes.length===row.axes.length,
      "Every assigned axis must remain present.");
    row.axes.forEach((axis,ai)=>{
      const answer=input.axes[ai];
      const fields=["judgment","unassessed_reason","evidence_refs","rationale"];
      requireValue(answer && fields.every(key=>typeof answer[key]==="string"),
        "Malformed form answer.");
      const refs=evidenceRefs(answer.evidence_refs);
      if(answer.judgment==="") {
        requireValue(answer.unassessed_reason==="" && refs.length===0 && answer.rationale==="",
          "Choose an assessment or clear a partially filled question.");return;
      }
      requireValue(["yes","no","unassessed"].includes(answer.judgment),"Unsupported assessment.");
      requireValue(answer.rationale.trim()!=="","A submitted assessment requires a rationale.");
      if(answer.judgment==="unassessed") requireValue(reasons.has(answer.unassessed_reason),
        "Unassessed answers require a reason.");
      else requireValue(answer.unassessed_reason==="" && refs.length>0,
        "Yes/no answers require evidence references and no abstention reason.");
      axis.judgment=answer.judgment;axis.unassessed_reason=answer.unassessed_reason||null;
      axis.evidence_refs=refs;axis.rationale=answer.rationale;
    });
    const timing=input.timing;
    const timingFields=["method","elapsed_seconds","active_seconds","note"];
    requireValue(timing && timingFields.every(key=>typeof timing[key]==="string"),
      "Malformed timing fields.");
    requireValue(["not_collected","self_reported"].includes(timing.method),
      "Timing can only be uncollected or self-reported.");
    const elapsed=numberOrNull(timing.elapsed_seconds),active=numberOrNull(timing.active_seconds);
    if(timing.method==="not_collected") requireValue(elapsed===null && active===null,
      "Uncollected timing cannot include durations.");
    else {
      requireValue(elapsed!==null || active!==null,
        "Self-reported timing requires at least one duration.");
      requireValue(elapsed===null || active===null || active<=elapsed,
        "Self-reported active time cannot exceed elapsed time.");
      requireValue(timing.note.trim()!=="","Self-reported timing requires a note.");
    }
    row.timing={method:timing.method,elapsed_seconds:elapsed,active_seconds:active,note:timing.note};
  });
  return result;
}
function readOperatorForm() {
  const value=id=>document.getElementById(id).value;
  return {cases:responseTemplate.cases.map((row,ci)=>({
    axes:row.axes.map((axis,ai)=>{const prefix=`case-${ci}-axis-${ai}`;return {
      judgment:value(prefix+"-judgment"),unassessed_reason:value(prefix+"-reason"),
      evidence_refs:value(prefix+"-refs"),rationale:value(prefix+"-rationale")};}),
    timing:{method:value(`case-${ci}-timing-method`),elapsed_seconds:value(`case-${ci}-timing-elapsed`),
      active_seconds:value(`case-${ci}-timing-active`),note:value(`case-${ci}-timing-note`)}
  }))};
}
document.getElementById("download-response").addEventListener("click",()=>{
  const status=document.getElementById("export-status");
  try {
    const result=buildOperatorResponse(readOperatorForm(),responseTemplate);
    const blob=new Blob([JSON.stringify(result,null,2)+"\n"],{type:"application/json"});
    const url=URL.createObjectURL(blob);const link=document.createElement("a");
    link.href=url;link.download="operator-response.json";document.body.appendChild(link);
    link.click();link.remove();URL.revokeObjectURL(url);
    status.textContent="Response exported. Import it for contract validation; "+
      "this is not a correctness or clinical assessment.";
  } catch(error) {status.textContent="Response not exported: "+error.message;}
});
"""


def render_operator_packet(packet: dict, response_template: dict) -> str:
    """Render a validated tutorial assignment with blank manually entered responses."""
    explanations = _validate(packet, response_template)
    sections = []
    for index, (case, explanation) in enumerate(zip(packet["cases"], explanations, strict=True)):
        sources = []
        for name, (label, description) in _DOCUMENTS.items():
            sources.append(
                f'<section id="document-{index}-{name}"><h3>{label}</h3><p>{description}</p>'
                f"<details><summary>Read complete captured {name} JSON</summary>"
                f'<pre data-case="{escape(case["case_id"], quote=True)}" '
                f'data-document="{name}">{_pretty(case["documents"][name])}</pre></details>'
                + _source_navigation(case["documents"][name], name, index)
                + "</section>"
            )
        navigation = " · ".join(
            f'<a href="#document-{index}-{name}">{label}</a>'
            for name, (label, _) in _DOCUMENTS.items()
        )
        sections.append(
            f'<article class="case" id="case-{index}"><h2>Case {escape(case["case_id"])}</h2>'
            f"<p>Scenario family: {escape(case['scenario_family_id'])}. "
            "Exposed engineering tutorial.</p>"
            f'<nav aria-label="Case {index + 1} source documents">{navigation}</nav>'
            + "".join(sources)
            + (_assistance(explanation, index) if packet["presentation"] == "assisted" else "")
            + _case_form(case, index)
            + "</article>"
        )
    embedded = (
        _json(response_template)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    case_links = " · ".join(
        f'<a href="#case-{i}">{escape(case["case_id"])}</a>'
        for i, case in enumerate(packet["cases"])
    )
    limits = "".join(f"<li>{escape(item)}</li>" for item in packet["limitations"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Operator incident review — exposed tutorial</title><style>
:root{{font:16px/1.55 system-ui,sans-serif;color:#173340;background:#f5f7f6}}
*{{box-sizing:border-box}}
body{{margin:0}}main{{max-width:1080px;margin:auto;padding:28px 22px}}
h1{{line-height:1.2}}h3{{margin-bottom:8px}}
section,fieldset,.case,aside{{background:white;border:1px solid #cbd8dd;
border-radius:8px;padding:18px;margin:18px 0}}
.assistance{{border-left:5px solid #426e85}}.response{{border-left:5px solid #506b40}}
.issue{{border-left:3px solid #a56a31;padding:12px;margin:12px 0}}
pre,code{{white-space:pre-wrap;overflow-wrap:anywhere}}pre{{font-size:13px}}summary,button{{cursor:pointer}}
label{{display:block;font-weight:600;margin-top:12px}}select,input,textarea,button{{font:inherit;max-width:100%;padding:8px}}
textarea{{display:block;width:100%}}legend{{font-weight:650}}
dt{{font-weight:650}}dd{{margin-left:0}}nav{{padding:12px 0}}
.source-value{{border-top:1px solid #cbd8dd;padding:12px 0}}
.source-value input{{width:100%;font-family:monospace}}
button{{background:#173340;color:white;border:0;border-radius:5px}}a{{color:#135a82}}
:target{{outline:3px solid #c79531;outline-offset:4px}}
</style></head><body><main><h1>Operator incident review</h1>
<p><strong>Exposed engineering tutorial — no clinical assessment, independent-participant evidence
or comparative result.</strong></p>
<p>Review the recorded facts, then enter your own assessment for each of the six questions.
No answers are filled from the oracle or explanation.</p>
<p>Presentation: {escape(packet["presentation"])}.
Assignment: <code>{escape(packet["assignment_id"])}</code>.
Reviewer alias: <code>{escape(packet["reviewer_id"])}</code>.</p>
<nav aria-label="Assigned cases">{case_links}</nav><aside>
<h2>Evidence references and responses</h2>
<p>Use the same document names in either presentation: <code>scenario</code>,
<code>evidence</code>, <code>expectations</code>, <code>oracle</code>.
A reference uses an RFC6901 pointer; the empty pointer identifies a document root.</p>
<pre>[{{"document":"evidence","pointer":"/calls/0"}}]</pre>
<p>For a JSON note string, add <code>decoded_json_pointer</code> for a location inside it.
Cite an existing parent when explaining a missing field. Reference existence is checked by the
offline importer. Expected contracts and mechanical oracle outputs are distinct
from observed facts.</p>
<p>Blank answers stay pending. Yes/no requires evidence and rationale; unassessed requires a reason.
Timing is optional and self-reported only. There is no timer, network submission
or automatic saving.
You may also edit the separately supplied response-template.json offline.</p></aside>
{"".join(sections)}<section><h2>Export your response</h2>
<button id="download-response" type="button">Download response JSON</button>
<p id="export-status" role="status" aria-live="polite">No response exported yet.</p>
<noscript>JavaScript is unavailable. Edit the supplied response-template.json offline;
preserve its identities and all assigned case/axis rows.</noscript></section>
<section><h2>Limits</h2><ul>{limits}</ul><p>Identity hashes do not authenticate execution or
participant independence. Response import validates the contract, not the correctness of your
judgments. No clinical labels or study outcome are generated here.</p></section>
<script id="operator-response-template" type="application/json">{embedded}</script>
<script id="operator-app">{_SCRIPT}</script></main></body></html>"""
