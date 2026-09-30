"""Inert standalone HTML for the bounded reconciliation explanation v1 contract."""

from __future__ import annotations

import json
import math
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


def _references(items: list[dict]) -> str:
    rows = []
    for ref in items:
        text = f"<strong>{escape(ref['document'])}</strong>: <code>{escape(ref['pointer'])}</code>"
        if "decoded_json_pointer" in ref:
            text += f"<br>Inside the JSON note: <code>{escape(ref['decoded_json_pointer'])}</code>"
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


def _note_html(note: dict) -> str:
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
        sources = _references(issue["evidence_refs"] + issue.get("expectation_refs", []))
        issues.append(
            f'<article class="issue"><h4>{escape(label)}'
            f"{': ' + identity if identity else ''}</h4>{details}{sources}</article>"
        )
    exclusion_summary = (
        "Exclusion records match supplied expectations."
        if not issues
        else "Exclusion differences below are separate from the full oracle verdict."
    )
    return f"""<article class="note"><h3>Write call {escape(note["call_id"])}</h3>
<p>Matching final stored note IDs: {_ids(note["matching_stored_note_ids"])}.</p>
<p class="muted">These are final-state text matches, not unique call attribution.</p>
{_references([note["reference"]])}<h4>Observed readback</h4><p>{read_summary}</p>
<dl><dt>Attempted target reads</dt><dd>{_ids(rb["attempted_call_ids"])}</dd>
<dt>Successful target reads</dt><dd>{_ids(rb["successful_target_call_ids"])}</dd>
<dt>Reads containing matching stored text</dt><dd>{_ids(rb["stored_text_seen_call_ids"])}</dd></dl>
{_references(rb["references"])}<h4>Scope exclusions</h4>
<p>{exclusion_summary}</p>{"".join(issues)}</article>"""


def render_reconciliation_explanation(
    explanation: dict, *, title: str = "Reconciliation evidence report"
) -> str:
    """Render supported v1 evidence without scripts, active links, or new verdicts.

    Unsupported or malformed input raises ValueError. The renderer checks shape
    and consistency only; source hashes/pointers require the original documents.
    """
    _require(type(title) is str, "title must be text")
    _validate(explanation)
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
                    f"{_references([record['reference']])}"
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
    notes = "".join(_note_html(note) for note in explanation["notes"])
    notes = notes or "<p>No per-write diagnosis available.</p>"
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
<section><h2>Write and exclusion details</h2>{notes}</section>{scope}
<section><h2>Input bindings</h2><p>Hashes bind this sidecar to its inputs and oracle output;
this page does not independently authenticate them.
Source pointers are inert text to locate the original evidence.</p><dl>{bindings}</dl></section>
<section><h2>Interpretation limits</h2><ul>{limits}</ul></section>
<footer>Offline explanation only. No clinical validity, comparative value,
or superiority is established.</footer></main></body></html>"""
