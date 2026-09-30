"""Inert standalone HTML for the bounded reconciliation explanation v1 contract."""

from __future__ import annotations

import hashlib
import json
import math
import re
from html import escape

from jsonschema import Draft202012Validator

_CHECKS = {
    "provenance": "Evidence binding",
    "source_fidelity": "Source fidelity under the full oracle contract",
    "persisted_action": "Correct note persisted under the full oracle contract",
    "readback": "Correct note verified by readback",
    "execution_complete": "Recorded execution complete",
}
_ASSESSED = {
    "successful_write_calls": "Write acknowledgements",
    "new_stored_notes": "New stored notes in the final state",
    "postwrite_readback": "Recorded post-write reads",
    "scope_exclusions": "Exact scope-exclusion differences",
}
_UNASSESSED = {
    "observations": "Observation content",
    "unresolved_conflicts": "Unresolved-conflict content",
    "retrieval_coverage": "Source retrieval coverage",
    "clinical_validity": "Clinical validity",
}
_ISSUES = {
    "exclusion_missing": "Required exclusion missing",
    "exclusion_unexpected": "Unexpected exclusion",
    "exclusion_duplicate": "Duplicate exclusion identifier",
    "exclusion_field_missing": "Required field missing",
    "exclusion_field_unexpected": "Unexpected field",
    "exclusion_field_mismatch": "Field differs from expectations",
    "exclusions_not_parseable": "Exclusion section could not be parsed",
}
_STRING = {"type": "string", "minLength": 1}
_STRINGS = {"type": "array", "items": _STRING, "uniqueItems": True}
_NULLABLE_STRING = {"type": ["string", "null"]}


def _object(properties: dict, required: list | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


def _array(items: dict) -> dict:
    return {"type": "array", "items": items}


_POINTER = {"type": "string", "pattern": r"^(?:/(?:[^~]|~[01])*)?$"}
_REFERENCE = _object(
    {
        "document": {"enum": ["evidence", "expectations", "scenario"]},
        "pointer": _POINTER,
        "decoded_json_pointer": _POINTER,
    },
    ["document", "pointer"],
)
_ISSUE = _object(
    {
        "code": {"enum": list(_ISSUES)},
        "source_id": _STRING,
        "field": _STRING,
        "observed": {},
        "expected": {},
        "message": _STRING,
        "evidence_refs": {**_array(_REFERENCE), "minItems": 1},
        "expectation_refs": {**_array(_REFERENCE), "minItems": 1},
    },
    ["code", "evidence_refs"],
)
_WRITE = _object(
    {
        "call_id": _STRING,
        "call_index": {"type": "integer", "minimum": 0},
        "encounter_id": _NULLABLE_STRING,
        "reference": _REFERENCE,
    }
)
_READBACK = _object(
    {
        "attempted_call_ids": _STRINGS,
        "successful_target_call_ids": _STRINGS,
        "stored_text_seen_call_ids": _STRINGS,
        "references": _array(_REFERENCE),
        "oracle_verified": {"type": "boolean"},
    }
)
_NOTE = _object(
    {
        "call_id": _STRING,
        "reference": _REFERENCE,
        "matching_stored_note_ids": _STRINGS,
        "scope_exclusions": _object(
            {"status": {"enum": ["matched", "different", "malformed"]}, "issues": _array(_ISSUE)}
        ),
        "readback": _READBACK,
    }
)
_SCHEMA = _object(
    {
        "schema_version": {"const": "healthcraft-reconciliation-explanation/v1"},
        "status": {"enum": ["available", "unavailable"]},
        "bindings": _object(
            {
                key + "_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}
                for key in ("scenario", "expectations", "evidence", "oracle")
            },
            [],
        ),
        "oracle_checks": {
            "anyOf": [{"type": "null"}, _object({key: {"type": "boolean"} for key in _CHECKS})]
        },
        "coverage": _object(
            {
                "assessed": {**_STRINGS, "items": {"enum": list(_ASSESSED)}},
                "unassessed": {**_STRINGS, "items": {"enum": list(_UNASSESSED)}},
            }
        ),
        "observed_execution": {
            "anyOf": [
                {"type": "null"},
                _object(
                    {
                        "successful_write_calls": _array(_WRITE),
                        "deduplicated_retries": _array(_WRITE),
                        "new_stored_notes": _array(
                            _object(
                                {
                                    "note_id": _STRING,
                                    "patient_id": _NULLABLE_STRING,
                                    "encounter_id": _NULLABLE_STRING,
                                    "reference": _REFERENCE,
                                }
                            )
                        ),
                    }
                ),
            ]
        },
        "notes": _array(_NOTE),
        "errors": _array(
            _object({"message": _STRING, "axis": _STRING, "code": _STRING}, ["message"])
        ),
        "limitations": _STRINGS,
    }
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError("Malformed reconciliation explanation: " + message)


def _finite_json(value) -> None:
    if type(value) is dict:
        for key, child in value.items():
            _require(type(key) is str, "object key must be a string")
            _finite_json(child)
    elif type(value) is list:
        for child in value:
            _finite_json(child)
    else:
        _require(type(value) in (str, int, float, bool, type(None)), "unsupported JSON value")
        _require(type(value) is not float or math.isfinite(value), "non-finite number")


def _validate(value: dict) -> None:
    try:
        _finite_json(value)
        json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
        errors = list(Draft202012Validator(_SCHEMA).iter_errors(value))
        _require(not errors, errors[0].message if errors else "invalid schema")
        _require(set(value["coverage"]["assessed"]) == set(_ASSESSED), "unsupported assessed scope")
        _require(
            set(value["coverage"]["unassessed"]) == set(_UNASSESSED), "unsupported unassessed scope"
        )
        if value["status"] == "unavailable":
            _require(
                value["observed_execution"] is None
                and value["notes"] == []
                and bool(value["errors"]),
                "unavailable evidence must not assert events",
            )
            return
        _require(len(value["bindings"]) == 4, "available evidence requires all input bindings")
        _require(
            value["oracle_checks"] is not None and value["oracle_checks"]["provenance"] is True,
            "available explanation requires valid provenance",
        )
        _require(
            value["observed_execution"] is not None and not value["errors"],
            "available event evidence missing or contradictory",
        )
        observed = value["observed_execution"]
        writes, retries, stored = (
            observed[key]
            for key in ("successful_write_calls", "deduplicated_retries", "new_stored_notes")
        )
        call_ids = [row["call_id"] for row in writes + retries]
        _require(len(set(call_ids)) == len(call_ids), "duplicate write/retry call IDs")
        stored_ids = {row["note_id"] for row in stored}
        _require(len(stored_ids) == len(stored), "duplicate stored-note IDs")
        note_ids = [row["call_id"] for row in value["notes"]]
        _require(
            len(set(note_ids)) == len(note_ids)
            and set(note_ids) == {row["call_id"] for row in writes},
            "note details must match acknowledged writes",
        )
        for note in value["notes"]:
            _require(
                set(note["matching_stored_note_ids"]) <= stored_ids, "unknown matching stored note"
            )
            rb = note["readback"]
            _require(
                set(rb["stored_text_seen_call_ids"])
                <= set(rb["successful_target_call_ids"])
                <= set(rb["attempted_call_ids"]),
                "readback call subsets inconsistent",
            )
            _require(
                len(rb["references"]) == len(rb["attempted_call_ids"]),
                "readback source references missing",
            )
            _require(
                rb["oracle_verified"] is value["oracle_checks"]["readback"],
                "readback oracle snapshot inconsistent",
            )
            _require(
                not rb["stored_text_seen_call_ids"] or bool(note["matching_stored_note_ids"]),
                "stored text claimed without matching note",
            )
            exclusion = note["scope_exclusions"]
            _require(
                (exclusion["status"] == "matched") == (not exclusion["issues"]),
                "exclusion status contradicts issues",
            )
            for issue in exclusion["issues"]:
                code = issue["code"]
                required = {
                    "exclusion_missing": {"source_id", "expected", "expectation_refs"},
                    "exclusion_unexpected": {"source_id", "observed", "expectation_refs"},
                    "exclusion_duplicate": {"source_id"},
                    "exclusion_field_missing": {
                        "source_id",
                        "field",
                        "expected",
                        "expectation_refs",
                    },
                    "exclusion_field_unexpected": {
                        "source_id",
                        "field",
                        "observed",
                        "expectation_refs",
                    },
                    "exclusion_field_mismatch": {
                        "source_id",
                        "field",
                        "observed",
                        "expected",
                        "expectation_refs",
                    },
                    "exclusions_not_parseable": {"message"},
                }[code]
                _require(required <= issue.keys(), "issue detail missing")
                _require(
                    (exclusion["status"] == "malformed") == (code == "exclusions_not_parseable"),
                    "malformed exclusion classification inconsistent",
                )
    except (TypeError, KeyError, IndexError, RecursionError, UnicodeError) as exc:
        raise ValueError(f"Malformed reconciliation explanation: {type(exc).__name__}") from exc


SOURCE_CONTEXT_VERSION = "healthcraft-reconciliation-source-context/v1"
_SOURCE_LABELS = {
    "evidence": "Observed evidence",
    "expectations": "Expected contract — engineering expectations, not clinical truth",
    "scenario": "Authored scenario — source assertions",
    "oracle": "Original oracle output",
}


def _canonical_source(value) -> str:
    _finite_json(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _resolve_pointer(value, pointer: str) -> dict:
    """Resolve RFC6901 without conflating a missing location with JSON null."""
    if pointer == "":
        return {"available": True, "value": value, "context": value, "context_pointer": ""}
    segments = pointer[1:].split("/")
    context, context_pointer = value, ""
    for index, segment in enumerate(segments):
        token = segment.replace("~1", "/").replace("~0", "~")
        context, context_pointer = value, "/" + "/".join(segments[:index]) if index else ""
        reason = None
        if type(value) is dict:
            if token not in value:
                reason = f"Missing object member: {token}"
            else:
                value = value[token]
        elif type(value) is list:
            if not re.fullmatch(r"0|[1-9][0-9]*", token):
                reason = f"Invalid array index: {token}"
            elif len(token) > len(str(len(value))) or int(token) >= len(value):
                reason = f"Array index out of range: {token}"
            else:
                value = value[int(token)]
        else:
            reason = "Cannot descend into a scalar"
        if reason:
            return {
                "available": False,
                "reason": reason,
                "context": context,
                "context_pointer": context_pointer,
            }
    return {
        "available": True,
        "value": value,
        "context": context,
        "context_pointer": context_pointer,
    }


def _embedded_note(raw) -> dict:
    if type(raw) is not str:
        raise ValueError("Embedded JSON note must be a string")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"Non-finite JSON constant: {value}")

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    _canonical_source(value).encode("utf-8")
    if type(value) is not dict:
        raise ValueError("Embedded JSON note must contain an object")
    return value


def _source_value(value) -> str:
    return (
        "<pre>"
        + escape(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))
        + "</pre>"
    )


class _SourceContext:
    """One render's bound source documents and deduplicated fragment targets."""

    def __init__(self, explanation: dict, documents: dict | None):
        _require(
            type(documents) is dict and set(documents) == set(_SOURCE_LABELS),
            "source-context documents must contain scenario, expectations, evidence and oracle",
        )
        try:
            bindings = {}
            for name, value in documents.items():
                _require(type(value) is dict, "source-context documents must be JSON objects")
                bindings[name + "_sha256"] = hashlib.sha256(
                    _canonical_source(value).encode("utf-8")
                ).hexdigest()
            _require(explanation["bindings"] == bindings, "source-context binding mismatch")
            _require(
                _canonical_source(documents["oracle"].get("checks"))
                == _canonical_source(explanation["oracle_checks"]),
                "source-context oracle checks mismatch",
            )
        except (TypeError, RecursionError, UnicodeError) as exc:
            raise ValueError(f"Invalid source-context documents: {type(exc).__name__}") from exc
        self.documents = documents
        self.references: dict[str, dict] = {}
        self.note_references: set[str] = set()

    def anchor(self, ref: dict) -> str:
        for key in ("pointer", "decoded_json_pointer"):
            if key in ref:
                # JSON Schema's search-based `$` can stop before a final newline.
                # Match the whole pointer before indexing or parsing a note.
                _require(
                    re.fullmatch(r"(?:/(?:[^~]|~[01])*)?", ref[key]) is not None,
                    f"Invalid RFC6901 source-context {key}",
                )
        identifier = "source-" + hashlib.sha256(_canonical_source(ref).encode("utf-8")).hexdigest()
        self.references.setdefault(identifier, ref)
        return identifier

    def render(self) -> str:
        cards = []
        for identifier, ref in self.references.items():
            resolved = _resolve_pointer(self.documents[ref["document"]], ref["pointer"])
            raw_note = ""
            decoded = ref.get("decoded_json_pointer")
            context_label = "Original document"
            note_status = None
            if (decoded is not None or identifier in self.note_references) and resolved[
                "available"
            ]:
                raw = resolved["value"]
                raw_html = "<h4>Raw captured JSON note</h4>" + (
                    "<pre>" + escape(raw) + "</pre>" if type(raw) is str else _source_value(raw)
                )
                raw_note = raw_html
                try:
                    parsed = _embedded_note(raw)
                    note_status = "available"
                    if decoded is not None:
                        resolved = _resolve_pointer(parsed, decoded)
                        context_label = "Decoded JSON note"
                except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
                    note_status = "unavailable"
                    reason = f"Embedded JSON unavailable: {type(exc).__name__}: {exc}"
                    raw_note = (
                        '<p role="status"><strong>Decoded JSON note unavailable.</strong> '
                        + escape(reason)
                        + "</p>"
                        + raw_html
                    )
                    if decoded is not None:
                        resolved = {
                            "available": False,
                            "reason": reason,
                            "context": resolved["context"],
                            "context_pointer": resolved["context_pointer"],
                        }
            status = "available" if resolved["available"] else "unavailable"
            value_html = (
                "<h4>Exact captured value</h4>" + _source_value(resolved["value"])
                if resolved["available"]
                else '<p role="status"><strong>Source value unavailable.</strong> '
                + escape(resolved["reason"])
                + "</p>"
            )
            context_heading = (
                "Parent context" if resolved["available"] else "Nearest existing context"
            )
            context_pointer = resolved["context_pointer"] or "(document root)"
            decoded_attr = (
                f' data-decoded-pointer="{escape(decoded, quote=True)}"'
                if decoded is not None
                else ""
            )
            note_attr = f' data-note-resolution="{note_status}"' if note_status else ""
            decoded_text = (
                f"<p>Inside the JSON note: <code>{escape(decoded or '(root)')}</code></p>"
                if decoded is not None
                else ""
            )
            cards.append(
                f'<article id="{identifier}" data-source-card="true" '
                f'data-document="{escape(ref["document"], quote=True)}" '
                f'data-pointer="{escape(ref["pointer"], quote=True)}"{decoded_attr} '
                f'data-resolution="{status}"{note_attr}><h3>{_SOURCE_LABELS[ref["document"]]}</h3>'
                f"<p>Original pointer: <code>{escape(ref['pointer'] or '(root)')}</code></p>"
                f"{decoded_text}{value_html}{raw_note}<details><summary>{context_heading} "
                f"— {context_label}: <code>{escape(context_pointer)}</code></summary>"
                f"{_source_value(resolved['context'])}</details></article>"
            )
        return (
            "<section><h2>Captured source context</h2><p>Values below are captured inputs, "
            "not new verification or clinical judgments. Missing locations remain unavailable. "
            "Hash matching establishes input identity, not execution authenticity or proof that "
            "this explanation was faithfully derived.</p>"
            + ("".join(cards) or "<p>No source references available in this explanation.</p>")
            + "</section>"
        )


def _references(items: list[dict], sources: _SourceContext | None = None) -> str:
    rows = []
    seen = set()
    for ref in items:
        if sources is not None:
            identifier = sources.anchor(ref)
            if identifier in seen:
                continue
            seen.add(identifier)
        text = f"<strong>{escape(ref['document'])}</strong>: <code>{escape(ref['pointer'])}</code>"
        if "decoded_json_pointer" in ref:
            text += f"<br>Inside the JSON note: <code>{escape(ref['decoded_json_pointer'])}</code>"
        if sources is not None:
            text = f'<a href="#{identifier}">{text}</a>'
        rows.append(f"<li>{text}</li>")
    return '<ul class="sources">' + "".join(rows) + "</ul>" if rows else ""


def _ids(values: list[str]) -> str:
    return ", ".join(f"<code>{escape(value)}</code>" for value in values) or "None recorded"


def _value(issue: dict, key: str) -> str:
    if key not in issue:
        return "<em>Not supplied</em>"
    return (
        "<pre>"
        + escape(
            json.dumps(issue[key], indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        )
        + "</pre>"
    )


def _note_html(note: dict, sources: _SourceContext | None = None) -> str:
    if sources is not None:
        sources.note_references.add(sources.anchor(note["reference"]))
    rb = note["readback"]
    if not rb["attempted_call_ids"]:
        read_summary = "No post-write target read recorded."
    elif rb["stored_text_seen_call_ids"]:
        read_summary = (
            "Stored text was returned in a later target read. This does not establish "
            "that the note satisfies the requested reconciliation."
        )
    elif rb["successful_target_call_ids"]:
        read_summary = "Target read completed; matching stored text not established."
    else:
        read_summary = "Readback attempted; no successful target read recorded."
    issues = []
    for issue in note["scope_exclusions"]["issues"]:
        label = _ISSUES[issue["code"]]
        identity = " · ".join(escape(issue[key]) for key in ("source_id", "field") if key in issue)
        details = f"<p>{escape(issue['message'])}</p>" if "message" in issue else ""
        if "observed" in issue or "expected" in issue:
            details += (
                "<table><caption>Exact source comparison</caption><thead><tr>"
                '<th scope="col">Observed value</th><th scope="col">Required value</th>'
                f"</tr></thead><tbody><tr><td>{_value(issue, 'observed')}</td>"
                f"<td>{_value(issue, 'expected')}</td></tr></tbody></table>"
            )
        references = _references(
            issue["evidence_refs"] + issue.get("expectation_refs", []), sources
        )
        issues.append(
            f'<article class="issue"><h4>{escape(label)}'
            f"{': ' + identity if identity else ''}</h4>{details}{references}</article>"
        )
    exclusion_summary = (
        "Exclusion records match supplied expectations."
        if not issues
        else "Exclusion differences below are separate from the full oracle verdict."
    )
    return f"""<article class="note"><h3>Write call {escape(note["call_id"])}</h3>
<p>Matching final stored note IDs: {_ids(note["matching_stored_note_ids"])}.</p>
<p class="muted">These are final-state text matches, not unique call attribution.</p>
{_references([note["reference"]], sources)}<h4>Observed readback</h4><p>{read_summary}</p>
<dl><dt>Attempted target reads</dt><dd>{_ids(rb["attempted_call_ids"])}</dd>
<dt>Successful target reads</dt><dd>{_ids(rb["successful_target_call_ids"])}</dd>
<dt>Reads containing matching stored text</dt><dd>{_ids(rb["stored_text_seen_call_ids"])}</dd></dl>
{_references(rb["references"], sources)}<h4>Scope exclusions</h4>
<p>{exclusion_summary}</p>{"".join(issues)}</article>"""


def render_reconciliation_explanation(
    explanation: dict,
    *,
    title: str = "Reconciliation evidence report",
    source_context: bool = False,
    source_documents: dict | None = None,
) -> str:
    """Render v1 evidence; opt into internal links to hash-bound source context.

    The default remains inert. Source context requires all four original parsed
    documents, including the oracle, and does not create or alter verdicts.
    """
    _require(type(source_context) is bool, "source_context must be a boolean")
    _require(type(title) is str, "title must be text")
    _validate(explanation)
    sources = _SourceContext(explanation, source_documents) if source_context else None
    title_text = escape(title)
    if explanation["status"] == "unavailable":
        events = (
            '<aside role="alert"><h2>Explanation unavailable</h2>'
            "<p>Event counts unavailable. No source or action diagnosis can be established "
            "from this sidecar.</p></aside>"
        )
        events += (
            "<ul>"
            + "".join(f"<li>{escape(error['message'])}</li>" for error in explanation["errors"])
            + "</ul>"
        )
    else:
        observed = explanation["observed_execution"]
        reads = {
            identifier
            for note in explanation["notes"]
            for identifier in note["readback"]["successful_target_call_ids"]
        }
        counts = (
            (
                "Write acknowledgements",
                "write-acknowledgements",
                len(observed["successful_write_calls"]),
            ),
            ("New stored notes", "stored-notes", len(observed["new_stored_notes"])),
            ("Actual post-write target reads", "target-reads", len(reads)),
            ("Identical retries acknowledged", "retries", len(observed["deduplicated_retries"])),
        )
        events = (
            '<section><h2>Observed execution</h2><dl class="counts">'
            + "".join(
                f'<div><dt>{label}</dt><dd data-count="{key}">{count}</dd></div>'
                for label, key, count in counts
            )
            + "</dl><p>Acknowledgement does not prove storage. Stored-note counts come "
            "from the final state; matching text does not establish a correct note.</p>"
        )
        for key, label in (
            ("successful_write_calls", "Acknowledged write calls"),
            ("deduplicated_retries", "Acknowledged retries"),
            ("new_stored_notes", "Final-state new notes"),
        ):
            events += f"<details><summary>{label}</summary>"
            for record in observed[key]:
                identity = record.get("call_id", record.get("note_id"))
                events += (
                    f"<p><code>{escape(identity)}</code> · encounter "
                    f"<code>{escape(str(record['encounter_id']))}</code></p>"
                    f"{_references([record['reference']], sources)}"
                )
            events += "</details>"
        events += "</section>"
    oracle = explanation["oracle_checks"]
    check_rows = ""
    for key, label in _CHECKS.items():
        verdict = "Unassessed" if oracle is None else "Verified" if oracle[key] else "Not verified"
        check_rows += f'<tr><th scope="row">{label}</th><td>{verdict}</td></tr>'
    scope = "".join(
        f"<section><h2>{heading}</h2><ul>"
        + "".join(f"<li>{escape(labels[key])}</li>" for key in explanation["coverage"][group])
        + "</ul></section>"
        for group, heading, labels in (
            ("assessed", "What this sidecar explains", _ASSESSED),
            ("unassessed", "Unassessed by this sidecar", _UNASSESSED),
        )
    )
    bindings = (
        "".join(
            f"<dt>{escape(key)}</dt><dd><code>{escape(value)}</code></dd>"
            for key, value in sorted(explanation["bindings"].items())
        )
        or "<p>No input bindings available.</p>"
    )
    limits = "".join(f"<li>{escape(value)}</li>" for value in explanation["limitations"])
    notes = "".join(_note_html(note, sources) for note in explanation["notes"])
    notes = notes or "<p>No per-write diagnosis available.</p>"
    source_html = sources.render() if sources is not None else ""
    pointer_notice = (
        "Source links open captured values and their context on this page."
        if sources is not None
        else "Source pointers are inert text to locate the original evidence."
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title_text}</title><style>
:root{{color-scheme:light;color:#173340;background:#f5f7f6;font:16px/1.55 system-ui,sans-serif}}
*{{box-sizing:border-box}}body{{margin:0}}main{{max-width:1100px;margin:auto;padding:32px 24px}}
h1{{font-size:2rem;line-height:1.2}}h2{{margin-top:30px}}h3,h4{{margin-bottom:8px}}
section,.note,aside{{background:white;padding:20px;margin:18px 0;
border:1px solid #cbd8dd;border-radius:8px}}
aside,.issue{{border-left:4px solid #8b4820}}
.issue{{padding:8px 16px;margin:18px 0;background:#fffaf4}}
.counts{{display:flex;flex-wrap:wrap;gap:24px}}.counts div{{flex:1;min-width:150px}}
.counts dd{{font-size:1.7rem;margin:0;font-weight:650}}
dt{{font-weight:650}}dd{{margin:4px 0 14px}}
table{{width:100%;border-collapse:collapse;table-layout:fixed}}
caption{{text-align:left;font-weight:650;padding:10px 0}}
th,td{{text-align:left;padding:12px;border:1px solid #cbd8dd;vertical-align:top}}
pre,code{{white-space:pre-wrap;overflow-wrap:anywhere}}pre{{margin:0;font-size:13px}}.sources{{font-size:13px;padding-left:20px}}
.muted,footer{{color:#465e68}}summary{{cursor:pointer;font-weight:650}}
details{{padding:10px 0}}@media(max-width:600px){{main{{padding:20px 12px}}th,td{{padding:8px}}}}
</style></head><body><main><header><h1>{title_text}</h1>
<p>Recorded actions and source differences, with the original oracle checks kept separate.</p>
<p><strong>No clinical assessment or benchmark score.</strong></p></header>
{events}<section><h2>Original oracle checks</h2>
<p>These existing checks apply the full requested reconciliation contract.
A false readback check can coexist with a real read of an incorrect note.</p>
<table><caption>Content-qualified verification</caption><thead><tr>
<th scope="col">Check</th><th scope="col">Recorded result</th></tr></thead>
<tbody>{check_rows}</tbody></table></section>
<section><h2>Write and exclusion details</h2>{notes}</section>{scope}{source_html}
<section><h2>Input bindings</h2><p>Hashes bind this sidecar to its inputs and oracle output;
this page does not independently authenticate them.
{pointer_notice}</p><dl>{bindings}</dl></section>
<section><h2>Interpretation limits</h2><ul>{limits}</ul></section>
<footer>Offline explanation only. No clinical validity, comparative value,
or superiority is established.</footer></main></body></html>"""
