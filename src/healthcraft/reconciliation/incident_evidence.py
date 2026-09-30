"""Inspectable source claims for operator review, independent of any answer key.

Only public task, authored scenario, execution capture and runtime documents are
accepted. This is an assistance ledger, not a grader or operator adjudication.
Hashes bind supplied content; they do not authenticate an execution.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from copy import deepcopy
from typing import Any

from healthcraft.mcp.server import TOOL_NAME_MAP
from healthcraft.reconciliation.fixture_v2 import source_rows

SCHEMA_VERSION = "healthcraft-incident-evidence/v1"
_CATEGORIES = ("completion", "writes", "storage", "readback", "source_concordance", "runtime")
_DOCUMENTS = {"task", "scenario", "evidence", "runtime"}


def _canonical(value: Any) -> str:
    def validate(item):
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError("JSON keys must be strings")
                validate(child)
        elif type(item) is list:
            for child in item:
                validate(child)
        elif type(item) not in (str, int, float, bool, type(None)):
            raise ValueError("Unsupported JSON value")
        elif type(item) is float and not math.isfinite(item):
            raise ValueError("JSON numbers must be finite")

    validate(value)
    result = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    result.encode("utf-8")
    return result


def _strict_note(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"Nonfinite JSON number: {value}")

    value = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)
    _canonical(value)
    if type(value) is not dict:
        raise ValueError("Note JSON must be an object")
    return value


def _escape(value):
    return str(value).replace("~", "~0").replace("/", "~1")


def _closest(value, path):
    """Return an existing parent when the requested field is absent or malformed."""
    traversed = []
    for part in path.split("/")[1:] if path else []:
        key = part.replace("~1", "/").replace("~0", "~")
        if type(value) is dict and key in value:
            value = value[key]
        elif type(value) is list and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        else:
            break
        traversed.append(part)
    return "" if not traversed else "/" + "/".join(traversed)


def _same(left, right):
    return _canonical(left) == _canonical(right)


class _Ledger:
    def __init__(self, documents):
        self.docs = documents
        self.claims = []
        self.states = {category: [] for category in _CATEGORIES}

    def ref(self, document, path="", *, note=None, decoded=None):
        if self.docs[document] is None:
            available = next((key for key in sorted(self.docs) if self.docs[key] is not None), None)
            if available is None:
                return None
            return {"document": available, "pointer": ""}
        result = {"document": document, "pointer": _closest(self.docs[document], path)}
        if decoded is not None:
            result["decoded_json_pointer"] = _closest(note, decoded)
        return result

    def add(self, category, code, summary, observed, refs, state="available"):
        self.states[category].append(state)
        # Missing-document fallbacks may share an existing source parent.
        # Preserve first occurrence order and the public reference contract.
        refs = list({_canonical(ref): ref for ref in refs if ref is not None}.values())
        if not refs:
            return
        self.claims.append(
            {
                "id": f"claim-{len(self.claims) + 1:04d}",
                "category": category,
                "code": code,
                "summary": summary,
                "observed": deepcopy(observed),
                "refs": deepcopy(refs),
            }
        )

    def unavailable(self, category, code, summary, observed, document, path=""):
        self.add(category, code, summary, observed, [self.ref(document, path)], "unavailable")


def _completion(ledger, evidence):
    completion = evidence.get("completion") if type(evidence) is dict else None
    good = type(completion) is dict and completion.get("status") in (
        "completed",
        "failed",
        "interrupted",
    )
    if good:
        for key in ("error", "controller_error"):
            error = completion.get(key)
            if error is not None and (type(error) is not dict or not error):
                good = False
            if completion["status"] == "completed" and error is not None:
                good = False
    if good:
        ledger.add(
            "completion",
            "recorded_completion",
            "Recorded termination is separate from task correctness.",
            completion,
            [ledger.ref("evidence", "/completion")],
        )
    else:
        ledger.unavailable(
            "completion",
            "completion_unresolved",
            "Completion is missing or internally inconsistent; no completion conclusion is "
            "supplied.",
            {"recorded": completion},
            "evidence",
            "/completion",
        )


def _linked_calls(ledger, evidence):
    calls = evidence.get("calls") if type(evidence) is dict else None
    audit = evidence.get("audit") if type(evidence) is dict else None
    if type(calls) is not list or type(audit) is not list:
        ledger.unavailable(
            "writes",
            "call_capture_unavailable",
            "The call or audit capture is unavailable; it does not establish absence of actions.",
            {"calls_available": type(calls) is list, "audit_available": type(audit) is list},
            "evidence",
        )
        return [], False, calls
    linked, seen_ids, used_audits = [], set(), set()
    previous_end = 0
    complete = True
    for index, call in enumerate(calls):
        path = f"/calls/{index}"
        good = type(call) is dict
        if good:
            start, end = call.get("audit_start"), call.get("audit_end")
            response = call.get("response")
            good = (
                type(call.get("id")) is str
                and bool(call["id"])
                and call["id"] not in seen_ids
                and type(call.get("name")) is str
                and type(call.get("params")) is dict
                and type(start) is int
                and type(end) is int
                and start == previous_end
                and end == start + 1
                and end <= len(audit)
                and start not in used_audits
                and type(response) is dict
                and call.get("error") is None
            )
        if good:
            entry = audit[start]
            handler = TOOL_NAME_MAP.get(call["name"], call["name"])
            status = response.get("status")
            good = (
                type(entry) is dict
                and type(entry.get("tool_name")) is str
                and TOOL_NAME_MAP.get(entry.get("tool_name"), entry.get("tool_name")) == handler
                and _same(entry.get("params"), call["params"])
                and status in ("ok", "error")
                and entry.get("result_summary") == status
                and type(entry.get("timestamp")) is str
                and bool(entry["timestamp"])
                and type(entry.get("deduplicated")) is bool
                and type(response.get("deduplicated", False)) is bool
                and entry["deduplicated"] == response.get("deduplicated", False)
            )
            if good:
                good = (
                    (entry.get("error_code") == "" and response.get("code", "") == "")
                    if status == "ok"
                    else (
                        type(response.get("code")) is str
                        and bool(response["code"])
                        and entry.get("error_code") == response["code"]
                    )
                )
        if not good:
            complete = False
            ledger.add(
                "writes",
                "call_linkage_unresolved",
                "This call cannot be linked consistently to its captured audit outcome; it "
                "is not counted as a successful acknowledgement.",
                {"call_index": index},
                [ledger.ref("evidence", path), ledger.ref("evidence", "/audit")],
                "unavailable",
            )
            continue
        previous_end = end
        seen_ids.add(call["id"])
        used_audits.add(start)
        linked.append((index, call, entry))
        if status == "error":
            ledger.add(
                "runtime",
                "tool_error",
                "A tool returned the recorded error below; this is not a clinical safety judgment.",
                {
                    "call_id": call["id"],
                    "name": call["name"],
                    "params": call["params"],
                    "response": response,
                },
                [ledger.ref("evidence", path), ledger.ref("evidence", f"/audit/{start}")],
            )
    if len(used_audits) != len(audit):
        complete = False
        ledger.add(
            "writes",
            "audit_entries_unlinked",
            "Some audit entries are not linked to the supplied call sequence.",
            {"linked_entries": len(used_audits), "captured_entries": len(audit)},
            [ledger.ref("evidence", "/calls"), ledger.ref("evidence", "/audit")],
            "unavailable",
        )
    return linked, complete, calls


def _writes(ledger, linked, calls, capture_complete):
    writes = []
    for index, call, entry in linked:
        if (
            TOOL_NAME_MAP.get(call["name"], call["name"]) != "update_encounter"
            or call["response"]["status"] != "ok"
            or type(call["params"].get("notes")) is not str
        ):
            continue
        writes.append((index, call, entry))
        ledger.add(
            "writes",
            "write_acknowledgement",
            "A successful audit-linked write call is an acknowledgement, not independent "
            "proof of note storage.",
            {
                "call_id": call["id"],
                "encounter_id": call["params"].get("encounter_id"),
                "deduplicated": entry["deduplicated"],
            },
            [
                ledger.ref("evidence", f"/calls/{index}"),
                ledger.ref("evidence", f"/audit/{call['audit_start']}"),
            ],
        )
    ledger.add(
        "writes",
        "write_acknowledgements",
        "Counts cover successful audit-linked write calls in the supplied capture; retries "
        "are separate from new storage.",
        {
            "count": len(writes) if capture_complete else None,
            "observed_count": len(writes),
            "deduplicated_count": sum(entry["deduplicated"] for _, _, entry in writes)
            if capture_complete
            else None,
        },
        [ledger.ref("evidence", "/calls"), ledger.ref("evidence", "/audit")],
        "available" if capture_complete else "unavailable",
    )
    return writes


def _note_store(snapshot):
    if type(snapshot) is not dict or type(snapshot.get("entities")) is not dict:
        return None
    rows = snapshot["entities"].get("clinical_note")
    if type(rows) is not dict:
        return None
    for key, row in rows.items():
        if (
            type(row) is not dict
            or row.get("id") != key
            or not all(
                type(row.get(field)) is str
                for field in ("id", "patient_id", "encounter_id", "content")
            )
        ):
            return None
    return rows


def _storage(ledger, evidence, target):
    before = _note_store(evidence.get("before")) if type(evidence) is dict else None
    after = _note_store(evidence.get("after")) if type(evidence) is dict else None
    if before is None or after is None:
        ledger.add(
            "storage",
            "new_note_count",
            "New-note count is unavailable because a required note-store snapshot is "
            "missing or malformed. This is not a zero-storage observation.",
            {
                "count": None,
                "before_available": before is not None,
                "after_available": after is not None,
            },
            [ledger.ref("evidence", "/before"), ledger.ref("evidence", "/after")],
            "unavailable",
        )
        return None
    notes = {key: row for key, row in after.items() if key not in before}
    ledger.add(
        "storage",
        "new_note_count",
        "New note IDs present in the final store compared with the initial store, "
        "including notes on other targets.",
        {"count": len(notes)},
        [
            ledger.ref("evidence", "/before/entities/clinical_note"),
            ledger.ref("evidence", "/after/entities/clinical_note"),
        ],
    )
    for key, row in notes.items():
        ledger.add(
            "storage",
            "new_stored_note",
            "A new note record is present in the captured final state. Target placement is "
            "reported separately from content.",
            {
                "note_id": key,
                "patient_id": row["patient_id"],
                "encounter_id": row["encounter_id"],
                "on_requested_target": all(row[field] == value for field, value in target.items())
                if target is not None
                else None,
            },
            [
                ledger.ref("evidence", f"/after/entities/clinical_note/{_escape(key)}"),
                ledger.ref("scenario", "/target"),
            ],
        )
    return notes


def _text_counts(data):
    if type(data) is not dict or type(data.get("clinical_notes")) is not list:
        return None
    if any(
        type(row) is not list or len(row) != 2 or not all(type(v) is str for v in row)
        for row in data["clinical_notes"]
    ):
        return None
    return Counter(row[1] for row in data["clinical_notes"])


def _readback(ledger, notes, linked, writes, capture_complete):
    if notes is None:
        ledger.unavailable(
            "readback",
            "stored_text_readback_count",
            "Stored-text readback count is unavailable without both note-store snapshots.",
            {"count": None, "observed_matching_count": None},
            "evidence",
        )
        return
    groups = defaultdict(list)
    for key, note in notes.items():
        groups[(note["patient_id"], note["encounter_id"], note["content"])].append(key)
    observed = Counter()
    unresolved = not capture_complete
    for index, call, _ in linked:
        if (
            TOOL_NAME_MAP.get(call["name"], call["name"]) != "get_encounter_details"
            or call["response"]["status"] != "ok"
        ):
            continue
        data = call["response"].get("data")
        counts = _text_counts(data)
        if counts is None:
            unresolved = True
            ledger.add(
                "readback",
                "readback_response_unresolved",
                "A successful detail response has no usable note-list shape.",
                {"call_id": call["id"]},
                [ledger.ref("evidence", f"/calls/{index}/response")],
                "unavailable",
            )
            continue
        if any(
            type(value) is not str or not value
            for value in (
                data.get("id"),
                data.get("patient_id"),
                call["params"].get("encounter_id"),
            )
        ):
            unresolved = True
            ledger.add(
                "readback",
                "readback_ownership_unresolved",
                "A detail response or its request lacks usable ownership identifiers; "
                "it cannot establish either matching readback or its absence.",
                {"call_id": call["id"]},
                [ledger.ref("evidence", f"/calls/{index}")],
                "unavailable",
            )
            continue
        for (patient, encounter, text), identifiers in groups.items():
            if (
                data.get("id") != encounter
                or data.get("patient_id") != patient
                or call["params"].get("encounter_id") != encounter
            ):
                continue
            prior = []
            for write_index, write, entry in writes:
                if not (
                    write_index < index
                    and not entry["deduplicated"]
                    and write["params"].get("encounter_id") == encounter
                    and write["params"].get("notes") == text
                ):
                    continue
                write_data = write["response"].get("data")
                write_counts = _text_counts(write_data)
                if write_counts is None or any(
                    type(write_data.get(field)) is not str or not write_data[field]
                    for field in ("id", "patient_id")
                ):
                    unresolved = True
                    ledger.add(
                        "readback",
                        "write_readback_linkage_unresolved",
                        "An earlier matching write acknowledgement lacks the ownership or "
                        "note-list detail needed to link this returned text. Known matching "
                        "readbacks remain visible separately.",
                        {"write_call_id": write["id"], "read_call_id": call["id"]},
                        [
                            ledger.ref("evidence", f"/calls/{write_index}/response"),
                            ledger.ref("evidence", f"/calls/{index}/response"),
                        ],
                        "unavailable",
                    )
                    continue
                if (
                    write_data.get("id") == encounter
                    and write_data.get("patient_id") == patient
                    and write_counts[text] > 0
                ):
                    prior.append(write_index)
            if not prior or not counts[text]:
                continue
            multiplicity = min(len(identifiers), counts[text])
            observed[(patient, encounter, text)] = max(
                observed[(patient, encounter, text)], multiplicity
            )
            refs = [
                ledger.ref("evidence", f"/calls/{index}/response"),
                *[ledger.ref("evidence", f"/calls/{i}") for i in prior],
                *[
                    ledger.ref("evidence", f"/after/entities/clinical_note/{_escape(key)}")
                    for key in identifiers
                ],
            ]
            ledger.add(
                "readback",
                "stored_text_returned_after_write",
                "A later successful owned encounter read returned exact stored text. "
                "Matching final-state records do not prove unique creation by one call or "
                "content correctness.",
                {
                    "call_id": call["id"],
                    "patient_id": patient,
                    "encounter_id": encounter,
                    "matching_final_note_ids": identifiers,
                    "matching_record_count": multiplicity,
                },
                refs,
            )
    ledger.add(
        "readback",
        "stored_text_readback_count",
        "Counts use owned post-write responses and preserve duplicate-note multiplicity. "
        "Unresolved capture prevents an exhaustive count.",
        {
            "count": None if unresolved else sum(observed.values()),
            "observed_matching_count": sum(observed.values()),
        },
        [ledger.ref("evidence", "/calls"), ledger.ref("evidence", "/after/entities/clinical_note")],
        "unavailable" if unresolved else "available",
    )


def _source_catalog(ledger, scenario):
    if scenario is None:
        ledger.unavailable(
            "source_concordance",
            "source_catalog_unavailable",
            "The authored scenario is unavailable; no source comparison is made.",
            {"source_count": None},
            "scenario",
        )
        return None, None, []
    try:
        rows = source_rows(scenario)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        ledger.unavailable(
            "source_concordance",
            "source_catalog_unavailable",
            "The authored source shape is unsupported or malformed; no source comparison is made.",
            {"source_count": None, "reason": f"{type(exc).__name__}: {exc}"},
            "scenario",
        )
        return None, None, []
    target = scenario["target"]
    encounter_indices = {row["id"]: i for i, row in enumerate(scenario["encounters"])}
    catalog = {}
    conflicts = defaultdict(list)
    for row in rows:
        source_path = (
            f"/encounters/{encounter_indices[row['encounter_id']]}/patient_data{row['source_path']}"
        )
        scope = (
            "other_patient"
            if row["patient_id"] != target["patient_id"]
            else "other_encounter"
            if row["encounter_id"] != target["encounter_id"]
            else "target_encounter"
        )
        catalog[row["source_id"]] = (row, source_path, scope)
        ledger.add(
            "source_concordance",
            "authored_source_row",
            "An authored source assertion and its original ownership; no assertion of "
            "clinical truth is made.",
            {**row, "scope": scope},
            [
                ledger.ref("scenario", source_path),
                ledger.ref("scenario", f"/encounters/{encounter_indices[row['encounter_id']]}"),
                ledger.ref("scenario", "/target"),
            ],
        )
        event_id = row["source"].get("event_id")
        if (
            scope == "target_encounter"
            and row["source_collection"] == "treatments_given"
            and type(event_id) is str
            and event_id
        ):
            conflicts[event_id].append(row)
    groups = []
    for event, members in conflicts.items():
        if not {"administered", "not_administered"} <= {
            row["source"].get("reported_status") for row in members
        }:
            continue
        group = {
            "event_id": event,
            "source_ids": [row["source_id"] for row in members],
            "field": "reported_status",
        }
        groups.append(group)
        ledger.add(
            "source_concordance",
            "opposing_source_reports",
            "These same-event source rows contain opposing literal reported-status "
            "assertions. All members are retained; the ledger does not decide which "
            "assertion is true.",
            {
                **group,
                "reported_statuses": [row["source"].get("reported_status") for row in members],
            },
            [ledger.ref("scenario", catalog[row["source_id"]][1]) for row in members],
        )
    return catalog, target, groups


def _note_rows(ledger, note, content_path, field):
    rows = note.get(field)
    if type(rows) is not list:
        ledger.add(
            "source_concordance",
            f"note_{field}_unavailable",
            f"The note's {field} field is missing or not an array; no rows are inferred.",
            {"field_present": field in note, "recorded": rows},
            [ledger.ref("evidence", content_path, note=note, decoded=f"/{field}")],
            "unavailable",
        )
        return None
    return rows


def _compare_sources(ledger, note, content_path, catalog, field):
    rows = _note_rows(ledger, note, content_path, field)
    if rows is None:
        return

    def refs(i=None, key=None):
        return ledger.ref(
            "evidence",
            content_path,
            note=note,
            decoded=f"/{field}"
            + (f"/{i}" if i is not None else "")
            + (f"/{_escape(key)}" if key is not None else ""),
        )

    by_id = defaultdict(list)
    for index, recorded in enumerate(rows):
        if type(recorded) is not dict or type(recorded.get("source_id")) is not str:
            ledger.add(
                "source_concordance",
                f"{field}_source_id_unresolved",
                "A note row has no usable source ID; no source row is guessed for it.",
                {"recorded": recorded},
                [refs(index)],
                "unavailable",
            )
            continue
        by_id[recorded["source_id"]].append((index, recorded))
    for source_id, entries in by_id.items():
        if len(entries) > 1:
            ledger.add(
                "source_concordance",
                f"duplicate_{field}_source_id",
                "A source ID is repeated in this note array; no first or last row is "
                "selected as authoritative.",
                {"source_id": source_id, "count": len(entries)},
                [refs(i) for i, _ in entries],
            )
        if source_id not in catalog:
            ledger.add(
                "source_concordance",
                f"unrecognized_{field}_source_id",
                "This note source ID is not present in the supplied authored scenario.",
                {"source_id": source_id},
                [*[refs(i) for i, _ in entries], ledger.ref("scenario", "/encounters")],
            )
            continue
        authored, path, scope = catalog[source_id]
        for index, recorded in entries:
            sr = ledger.ref("scenario", path)
            if field == "observations":
                if scope != "target_encounter":
                    ledger.add(
                        "source_concordance",
                        "observation_outside_target",
                        "The authored row belongs to another encounter or patient but "
                        "appears in target observations.",
                        {
                            "source_id": source_id,
                            "authored_patient_id": authored["patient_id"],
                            "authored_encounter_id": authored["encounter_id"],
                            "authored_scope": scope,
                            "recorded_patient_id": recorded.get("patient_id"),
                            "recorded_encounter_id": recorded.get("encounter_id"),
                        },
                        [refs(index), sr, ledger.ref("scenario", "/target")],
                    )
                unchanged = "source" in recorded and _same(recorded["source"], authored["source"])
                ledger.add(
                    "source_concordance",
                    "observation_raw_source_unchanged"
                    if unchanged
                    else "observation_raw_source_difference",
                    "The recorded raw source object is unchanged."
                    if unchanged
                    else (
                        "The recorded raw source object differs from the authored object, or is "
                        "missing. Literal values and types are compared without time or status "
                        "normalization."
                    ),
                    {
                        "source_id": source_id,
                        "authored": authored["source"],
                        "recorded_present": "source" in recorded,
                        "recorded": recorded.get("source"),
                    },
                    [refs(index, "source"), sr],
                )
                for key in ("source_path", "patient_id", "encounter_id", "source_collection"):
                    if key not in recorded or not _same(recorded[key], authored[key]):
                        ledger.add(
                            "source_concordance",
                            "observation_path_difference"
                            if key == "source_path"
                            else "observation_attribution_difference",
                            "A descriptor field differs from the original source location "
                            "or ownership; this is separate from the raw source value.",
                            {
                                "source_id": source_id,
                                "field": key,
                                "authored": authored[key],
                                "recorded_present": key in recorded,
                                "recorded": recorded.get(key),
                                "raw_source_unchanged": unchanged,
                            },
                            [refs(index, key), sr, ledger.ref("scenario", "/target")],
                        )
                keys = set(authored)
            else:
                if scope == "target_encounter":
                    ledger.add(
                        "source_concordance",
                        "exclusion_lists_target_source",
                        "The listed exclusion refers to a source in the target encounter.",
                        {"source_id": source_id},
                        [refs(index), sr, ledger.ref("scenario", "/target")],
                    )
                for key, value in {
                    "patient_id": authored["patient_id"],
                    "encounter_id": authored["encounter_id"],
                    "reason": scope,
                }.items():
                    if key not in recorded or not _same(recorded[key], value):
                        ledger.add(
                            "source_concordance",
                            "scope_exclusion_difference",
                            "The exclusion's ownership or scope differs from its authored "
                            "source relationship to the target.",
                            {
                                "source_id": source_id,
                                "field": key,
                                "authored_relationship": value,
                                "recorded_present": key in recorded,
                                "recorded": recorded.get(key),
                            },
                            [refs(index, key), sr, ledger.ref("scenario", "/target")],
                        )
                keys = {"source_id", "patient_id", "encounter_id", "reason"}
            if set(recorded) != keys:
                ledger.add(
                    "source_concordance",
                    "source_descriptor_fields_difference",
                    "This note row's descriptor fields differ from the public note layout.",
                    {
                        "source_id": source_id,
                        "missing_fields": sorted(keys - recorded.keys()),
                        "extra_fields": sorted(recorded.keys() - keys),
                    },
                    [refs(index), ledger.ref("task")],
                )
    for source_id, (_, path, scope) in catalog.items():
        relevant = (
            (scope == "target_encounter")
            if field == "observations"
            else (scope != "target_encounter")
        )
        if relevant and source_id not in by_id:
            ledger.add(
                "source_concordance",
                "target_source_not_listed"
                if field == "observations"
                else "scope_source_not_listed",
                "An authored source ID is absent from this note array; this does not imply "
                "its assertion is true or false.",
                {"source_id": source_id, "authored_scope": scope, "note_array": field},
                [refs(), ledger.ref("scenario", path), ledger.ref("scenario", "/target")],
            )


def _compare_conflicts(ledger, note, content_path, catalog, groups):
    rows = _note_rows(ledger, note, content_path, "unresolved_conflicts")
    if rows is None:
        return

    def normalized(row):
        result = deepcopy(row)
        if (
            type(result) is dict
            and type(result.get("source_ids")) is list
            and all(type(v) is str for v in result["source_ids"])
        ):
            result["source_ids"].sort()
        return result

    captured = Counter(_canonical(normalized(row)) for row in rows)
    authored = Counter(_canonical(normalized(row)) for row in groups)
    for group in groups:
        if not captured[_canonical(normalized(group))]:
            ledger.add(
                "source_concordance",
                "opposing_group_not_listed",
                "The complete group of authored opposing reports is not listed exactly in "
                "the note. No majority or clinical truth judgment is applied.",
                group,
                [
                    ledger.ref(
                        "evidence", content_path, note=note, decoded="/unresolved_conflicts"
                    ),
                    *[ledger.ref("scenario", catalog[key][1]) for key in group["source_ids"]],
                ],
            )
    for index, row in enumerate(rows):
        key = _canonical(normalized(row))
        if authored[key] > 0:
            authored[key] -= 1
        else:
            ledger.add(
                "source_concordance",
                "listed_conflict_differs_from_sources",
                "A listed group or extra group copy does not match the complete same-event "
                "opposing literal reports in the authored target sources.",
                {"recorded": row},
                [
                    ledger.ref(
                        "evidence",
                        content_path,
                        note=note,
                        decoded=f"/unresolved_conflicts/{index}",
                    ),
                    ledger.ref("scenario", "/encounters"),
                    ledger.ref("scenario", "/target"),
                ],
            )


def _notes(ledger, notes, catalog, groups, target):
    if notes is None:
        ledger.unavailable(
            "source_concordance",
            "stored_note_content_unavailable",
            "A complete new-note store comparison is unavailable, so no new-note content "
            "is inferred.",
            {"new_notes_available": False},
            "evidence",
            "/after",
        )
        return
    for key, stored in notes.items():
        content_path = f"/after/entities/clinical_note/{_escape(key)}/content"
        try:
            note = _strict_note(stored["content"])
        except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
            ledger.add(
                "source_concordance",
                "note_json_unresolved",
                "The stored string cannot be interpreted as a strict JSON object. "
                "Duplicate keys, invalid numbers or malformed text are not repaired.",
                {"note_id": key, "reason": f"{type(exc).__name__}: {exc}"},
                [ledger.ref("evidence", content_path)],
                "unavailable",
            )
            continue
        ledger.add(
            "source_concordance",
            "note_json_available",
            "The stored string parses as a strict JSON object; parsing is not a "
            "correctness judgment.",
            {"note_id": key},
            [ledger.ref("evidence", content_path)],
        )
        keys = {
            "schema_version",
            "patient_id",
            "encounter_id",
            "observations",
            "unresolved_conflicts",
            "scope_exclusions",
        }
        if set(note) != keys or note.get("schema_version") != "healthcraft-reconciliation-note/v1":
            ledger.add(
                "source_concordance",
                "note_layout_difference",
                "The note's fields or schema marker differ from the public note layout.",
                {
                    "missing_fields": sorted(keys - note.keys()),
                    "extra_fields": sorted(note.keys() - keys),
                    "recorded_schema_version": note.get("schema_version"),
                },
                [ledger.ref("evidence", content_path, note=note, decoded=""), ledger.ref("task")],
            )
        for field in ("patient_id", "encounter_id"):
            if target is not None and (field not in note or not _same(note[field], target[field])):
                ledger.add(
                    "source_concordance",
                    "note_target_difference",
                    "The note header differs from the requested target identity.",
                    {
                        "field": field,
                        "requested": target[field],
                        "recorded_present": field in note,
                        "recorded": note.get(field),
                    },
                    [
                        ledger.ref("evidence", content_path, note=note, decoded=f"/{field}"),
                        ledger.ref("scenario", f"/target/{field}"),
                    ],
                )
            if field not in note or not _same(note[field], stored[field]):
                ledger.add(
                    "source_concordance",
                    "note_storage_identity_difference",
                    "The note header differs from the identity on its stored note record.",
                    {
                        "field": field,
                        "stored": stored[field],
                        "recorded_present": field in note,
                        "recorded": note.get(field),
                    },
                    [
                        ledger.ref("evidence", content_path, note=note, decoded=f"/{field}"),
                        ledger.ref(
                            "evidence", f"/after/entities/clinical_note/{_escape(key)}/{field}"
                        ),
                    ],
                )
        if catalog is None:
            continue
        for field in ("observations", "scope_exclusions"):
            _compare_sources(ledger, note, content_path, catalog, field)
        _compare_conflicts(ledger, note, content_path, catalog, groups)


def _runtime(ledger, runtime):
    if runtime is None:
        ledger.unavailable(
            "runtime",
            "runtime_unavailable",
            "No runtime document was supplied; model requests, inference and runtime "
            "errors are not inferred.",
            {"available": False},
            "runtime",
        )
        return
    ledger.add(
        "runtime",
        "runtime_capture_supplied",
        "A runtime capture was supplied for inspection; no inference count or independent "
        "execution attestation is inferred from its presence.",
        {"available": True},
        [ledger.ref("runtime")],
    )

    def walk(value, path):
        if type(value) is dict:
            for key, child in value.items():
                child_path = path + "/" + _escape(key)
                if (
                    key
                    in {
                        "error",
                        "execution_error",
                        "runner_error",
                        "postflight_error",
                        "capture_errors",
                    }
                    and child is not None
                    and child != {}
                ):
                    ledger.add(
                        "runtime",
                        "recorded_runtime_error",
                        "A runtime error field is retained exactly as supplied; inspect "
                        "its source and scope.",
                        {"recorded": child},
                        [ledger.ref("runtime", child_path)],
                    )
                else:
                    walk(child, child_path)
        elif type(value) is list:
            for index, child in enumerate(value):
                walk(child, path + f"/{index}")

    walk(runtime, "")


def describe_incident(documents: dict) -> dict:
    """Return detached, deterministic claims to inspect, never reviewer answers.

    The four document slots are exact; a null slot means unavailable. Invalid
    outer JSON raises ValueError. Missing/malformed captured internals produce
    explicit uncertainty, with references to existing parents rather than
    fabricated paths or automatic zeros. Source rows are read from the authored
    scenario without loading expectations, control labels, or any oracle.
    """
    if (
        type(documents) is not dict
        or set(documents) != _DOCUMENTS
        or any(type(value) not in (dict, type(None)) for value in documents.values())
    ):
        raise ValueError(
            "Incident documents must be exactly task/scenario/evidence/runtime objects or null"
        )
    try:
        canonical = _canonical(documents)
    except (TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError(f"Invalid JSON documents: {exc}") from exc
    docs = json.loads(canonical)

    def exclude_private(value):
        if type(value) is dict:
            if {
                "expectations",
                "verification",
                "designated_control",
                "original_evidence",
            } & value.keys():
                raise ValueError("Incident documents contain structured private assessment data")
            for child in value.values():
                exclude_private(child)
        elif type(value) is list:
            for child in value:
                exclude_private(child)

    # Captured text is preserved verbatim, even when it mentions a control.
    # Do not parse strings as private metadata or silently remove any fields.
    exclude_private(docs)
    ledger = _Ledger(docs)
    catalog, target, groups = _source_catalog(ledger, docs["scenario"])
    _completion(ledger, docs["evidence"])
    linked, complete, calls = _linked_calls(ledger, docs["evidence"])
    writes = _writes(ledger, linked, calls, complete)
    notes = _storage(ledger, docs["evidence"], target)
    _readback(ledger, notes, linked, writes, complete)
    _notes(ledger, notes, catalog, groups, target)
    _runtime(ledger, docs["runtime"])
    coverage = {}
    for category, states in ledger.states.items():
        coverage[category] = (
            "available"
            if states and all(s == "available" for s in states)
            else "partial"
            if "available" in states
            else "unavailable"
        )
    status = (
        "available"
        if all(s == "available" for s in coverage.values())
        else "unavailable"
        if all(s == "unavailable" for s in coverage.values())
        else "partial"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "document_sha256": {
            key: hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()
            for key, value in docs.items()
        },
        "coverage": coverage,
        "claims": ledger.claims,
        "limitations": [
            "Derived assistance consists of claims to inspect, not operator answers or "
            "adjudication.",
            "Recorded completion, write acknowledgement, final-state storage and returned "
            "text are distinct facts.",
            "Content hashes and consistent receipts do not authenticate execution.",
            "Source comparisons preserve literal values and unknowns; they do not "
            "establish clinical truth.",
            "Final matching note IDs do not uniquely attribute creation to one write call.",
            "Unavailable capture is not evidence that an action did not occur.",
        ],
        "unassessed": [
            "operator judgment",
            "clinical correctness",
            "clinical safety",
            "healthcare value",
            "comparative superiority",
            "authenticity of execution",
        ],
    }
