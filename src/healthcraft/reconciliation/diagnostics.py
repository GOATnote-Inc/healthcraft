"""Source-linked observations explaining reconciliation, without changing its oracle.

This limited sidecar describes recorded events and exclusion differences. It is
not a second grader: observation/conflict fidelity and retrieval coverage remain
unexplained here. Consistent evidence is not authenticated execution evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from typing import Any

from healthcraft.mcp.server import TOOL_NAME_MAP
from healthcraft.reconciliation.oracle import verify_reconciliation


def _canonical(value: Any) -> str:
    def validate(item: Any) -> None:
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError("JSON object keys must be strings")
                validate(child)
        elif type(item) is list:
            for child in item:
                validate(child)
        elif type(item) not in (str, int, float, bool, type(None)):
            raise ValueError("Unsupported JSON value type")
        elif type(item) is float and not math.isfinite(item):
            raise ValueError("Non-finite JSON value")

    validate(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _parse_note(text: str) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def number(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError("Non-finite JSON number")
        return value

    if type(text) is not str:
        raise ValueError("Note content must be a JSON string")
    note = json.loads(text, object_pairs_hook=pairs, parse_constant=number, parse_float=number)
    if type(note) is not dict:
        raise ValueError("Note must contain a JSON object")
    _canonical(note).encode("utf-8")
    return note


def _escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _ref(document: str, pointer: str, decoded: str | None = None) -> dict:
    result = {"document": document, "pointer": pointer}
    if decoded is not None:
        result["decoded_json_pointer"] = decoded
    return result


def _exclusions(content: str, expected: dict, pointer: str) -> dict:
    issues = []
    try:
        note = _parse_note(content)
        rows = note.get("scope_exclusions")
        if type(rows) is not list:
            raise ValueError("scope_exclusions must be an array")
        by_id: dict[str, list[tuple[int, dict]]] = {}
        for index, row in enumerate(rows):
            if (
                type(row) is not dict
                or type(row.get("source_id")) is not str
                or not row["source_id"]
            ):
                raise ValueError("Each scope exclusion requires a nonempty string source_id")
            by_id.setdefault(row["source_id"], []).append((index, row))
        expected_ids = {
            row["source_id"]: (i, row) for i, row in enumerate(expected["scope_exclusions"])
        }
        for source_id in sorted(expected_ids.keys() - by_id.keys()):
            index, row = expected_ids[source_id]
            issues.append(
                {
                    "code": "exclusion_missing",
                    "source_id": source_id,
                    "expected": row,
                    "evidence_refs": [_ref("evidence", pointer, "/scope_exclusions")],
                    "expectation_refs": [_ref("expectations", f"/scope_exclusions/{index}")],
                }
            )
        for source_id in sorted(by_id.keys() - expected_ids.keys()):
            for index, row in by_id[source_id]:
                issues.append(
                    {
                        "code": "exclusion_unexpected",
                        "source_id": source_id,
                        "observed": row,
                        "evidence_refs": [_ref("evidence", pointer, f"/scope_exclusions/{index}")],
                        "expectation_refs": [_ref("expectations", "/scope_exclusions")],
                    }
                )
        for source_id, entries in sorted(by_id.items()):
            if len(entries) > 1:
                issues.append(
                    {
                        "code": "exclusion_duplicate",
                        "source_id": source_id,
                        "evidence_refs": [
                            _ref("evidence", pointer, f"/scope_exclusions/{i}") for i, _ in entries
                        ],
                    }
                )
                continue  # No arbitrary first/last winner for conflicting duplicate rows.
            if source_id not in expected_ids:
                continue
            index, observed = entries[0]
            expected_index, wanted = expected_ids[source_id]
            for field in sorted(observed.keys() | wanted.keys()):
                if (
                    field in observed
                    and field in wanted
                    and _canonical(observed[field]) == _canonical(wanted[field])
                ):
                    continue
                issue = {"source_id": source_id, "field": field}
                observed_path = f"/scope_exclusions/{index}"
                expected_path = f"/scope_exclusions/{expected_index}"
                if field in observed:
                    issue["observed"] = observed[field]
                    observed_path += f"/{_escape(field)}"
                if field in wanted:
                    issue["expected"] = wanted[field]
                    expected_path += f"/{_escape(field)}"
                issue["code"] = (
                    "exclusion_field_missing"
                    if field not in observed
                    else "exclusion_field_unexpected"
                    if field not in wanted
                    else "exclusion_field_mismatch"
                )
                issue["evidence_refs"] = [_ref("evidence", pointer, observed_path)]
                issue["expectation_refs"] = [_ref("expectations", expected_path)]
                issues.append(issue)
        return {"status": "different" if issues else "matched", "issues": issues}
    except (ValueError, TypeError, KeyError, RecursionError, UnicodeError) as exc:
        return {
            "status": "malformed",
            "issues": [
                {
                    "code": "exclusions_not_parseable",
                    "message": f"{type(exc).__name__}: {exc}",
                    "evidence_refs": [_ref("evidence", pointer)],
                }
            ],
        }


def _handler(call: dict) -> str:
    return TOOL_NAME_MAP.get(call["name"], call["name"])


def _ok(call: dict) -> bool:
    return call.get("response", {}).get("status") == "ok"


def _text_present(data: dict, text: str) -> bool:
    rows = data.get("clinical_notes")
    return type(rows) is list and any(
        type(row) is list and len(row) == 2 and type(row[1]) is str and row[1] == text
        for row in rows
    )


def explain_reconciliation(scenario: dict, expectations: dict, evidence: dict) -> dict:
    """Explain observed writes/readbacks and exact exclusions; never alter verdicts.

    Canonical hashes bind this detached sidecar to the inputs and public oracle
    output. Invalid provenance yields no authoritative event/content diagnosis.
    Scope deliberately excludes full note fidelity and source-retrieval analysis.
    """
    result = {
        "schema_version": "healthcraft-reconciliation-explanation/v1",
        "status": "unavailable",
        "bindings": {},
        "oracle_checks": None,
        "coverage": {
            "assessed": [
                "successful_write_calls",
                "new_stored_notes",
                "postwrite_readback",
                "scope_exclusions",
            ],
            "unassessed": [
                "observations",
                "unresolved_conflicts",
                "retrieval_coverage",
                "clinical_validity",
            ],
        },
        "observed_execution": None,
        "notes": [],
        "errors": [],
        "limitations": [
            "Recorded events and exclusion differences are not a replacement oracle.",
            "Successful write calls are acknowledgements, not proof of storage.",
            "Matching stored note IDs describe final-state text matches, "
            "not unique call attribution.",
            "A note can be stored and read back without satisfying the requested reconciliation.",
            "Input consistency and hashes do not authenticate execution.",
        ],
    }
    try:
        oracle = verify_reconciliation(scenario, expectations, evidence)
        for name, value in (
            ("scenario", scenario),
            ("expectations", expectations),
            ("evidence", evidence),
            ("oracle", oracle),
        ):
            result["bindings"][name + "_sha256"] = _digest(value)
        result["oracle_checks"] = deepcopy(oracle["checks"])
        if oracle["checks"]["provenance"] is not True:
            result["errors"] = deepcopy(oracle["errors"])
            return result
        before, after = evidence["before"]["entities"], evidence["after"]["entities"]
        target = expectations["target"]
        new_ids = sorted(set(after["clinical_note"]) - set(before["clinical_note"]))
        observed = {
            "successful_write_calls": [],
            "deduplicated_retries": [],
            "new_stored_notes": [],
        }
        for identifier in new_ids:
            note = after["clinical_note"][identifier]
            observed["new_stored_notes"].append(
                {
                    "note_id": identifier,
                    "patient_id": note.get("patient_id"),
                    "encounter_id": note.get("encounter_id"),
                    "reference": _ref(
                        "evidence", f"/after/entities/clinical_note/{_escape(identifier)}"
                    ),
                }
            )
        for index, call in enumerate(evidence["calls"]):
            if (
                _handler(call) != "update_encounter"
                or "notes" not in call["params"]
                or not _ok(call)
            ):
                continue
            entry = evidence["audit"][call["audit_start"]]
            write = {
                "call_id": call["id"],
                "call_index": index,
                "encounter_id": call["params"].get("encounter_id"),
                "reference": _ref("evidence", f"/calls/{index}"),
            }
            if entry["deduplicated"]:
                observed["deduplicated_retries"].append(write)
                continue
            observed["successful_write_calls"].append(write)
            text = call["params"]["notes"]
            response_data = call["response"].get("data")
            # A later real write must not rehabilitate an earlier ACK-only call.
            # This links matching final text to the recorded write response; it
            # does not claim that a final snapshot proves the precise creation event.
            response_contains_note = (
                type(response_data) is dict
                and response_data.get("id") == target["encounter_id"]
                and response_data.get("patient_id") == target["patient_id"]
                and type(text) is str
                and _text_present(response_data, text)
            )
            stored_ids = [
                identifier
                for identifier in new_ids
                if response_contains_note
                and after["clinical_note"][identifier].get("content") == text
                and type(text) is str
                and after["clinical_note"][identifier].get("patient_id") == target["patient_id"]
                and after["clinical_note"][identifier].get("encounter_id") == target["encounter_id"]
                and call["params"].get("encounter_id") == target["encounter_id"]
            ]
            readback = {
                "attempted_call_ids": [],
                "successful_target_call_ids": [],
                "stored_text_seen_call_ids": [],
                "references": [],
                "oracle_verified": oracle["checks"]["readback"],
            }
            for later_index, later in enumerate(evidence["calls"][index + 1 :], index + 1):
                if (
                    _handler(later) != "get_encounter_details"
                    or later["params"].get("encounter_id") != target["encounter_id"]
                ):
                    continue
                readback["attempted_call_ids"].append(later["id"])
                readback["references"].append(_ref("evidence", f"/calls/{later_index}"))
                data = later.get("response", {}).get("data")
                if (
                    not _ok(later)
                    or type(data) is not dict
                    or data.get("id") != target["encounter_id"]
                    or data.get("patient_id") != target["patient_id"]
                ):
                    continue
                readback["successful_target_call_ids"].append(later["id"])
                if (
                    stored_ids
                    and _text_present(data, text)
                    and _text_present(after["encounter"][target["encounter_id"]], text)
                ):
                    readback["stored_text_seen_call_ids"].append(later["id"])
            result["notes"].append(
                {
                    "call_id": call["id"],
                    "reference": _ref("evidence", f"/calls/{index}/params/notes"),
                    "matching_stored_note_ids": stored_ids,
                    "scope_exclusions": _exclusions(
                        text, expectations, f"/calls/{index}/params/notes"
                    ),
                    "readback": readback,
                }
            )
        result["observed_execution"] = observed
        result["status"] = "available"
        return deepcopy(result)
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        AttributeError,
        RecursionError,
        UnicodeError,
    ) as exc:
        result["status"] = "unavailable"
        result["observed_execution"] = None
        result["notes"] = []
        result["errors"].append(
            {"code": "diagnostic_unavailable", "message": f"{type(exc).__name__}: {exc}"}
        )
        return result
