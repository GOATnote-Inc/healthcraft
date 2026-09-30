"""Mechanical IR-002 tool-execution proof, separate from benchmark scoring.

The caller supplies trusted profile context, the final in-process world, and
deep snapshots captured around synchronous MCP calls. Call IDs identify those
harness invocations; they are not provider-issued response IDs or signatures.
The verifier checks transport, source concordance, and persistence, not clinical
understanding or the semantic adequacy of arbitrary freeform documentation.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any

from healthcraft.tasks.loader import Task

_KIND = "healthcraft.ir002.mechanical_history_summary.v1"
_FACTS = ("chief_complaint", "diagnosis", "disposition", "notes")
_MECHANICAL = ("IR-002-C01", "IR-002-C02", "IR-002-C03", "IR-002-C07")
_UNASSESSED = ("IR-002-C04", "IR-002-C05", "IR-002-C06", "IR-002-C08")


def _field(entity: Any, name: str, default: Any = None) -> Any:
    return entity.get(name, default) if isinstance(entity, dict) else getattr(entity, name, default)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value


def _date(value: Any) -> date:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValueError("Expected a source calendar date in YYYY-MM-DD form")
    return date.fromisoformat(value)


def _ids(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and all(isinstance(item, str) and item for item in value)
        and len(set(value)) == len(value)
    )


def render_history_summary(records: list[dict[str, Any]]) -> str:
    """Transcribe actual returned history records into canonical grouped text.

    This is a mechanical JSON note, not a clinical summary or an oracle. The
    verifier independently compares parsed fields to the task's source records.
    """
    visits = []
    for record in records:
        visit = {"id": record["id"], "date": record["visit_date"]}
        visit.update({field: record[field] for field in _FACTS})
        if not all(isinstance(value, str) for value in visit.values()):
            raise ValueError("History summary fields must be source strings")
        visits.append(visit)
    visits.sort(key=lambda visit: (visit["date"], visit["id"]))
    return json.dumps(
        {"kind": _KIND, "visits": visits}, ensure_ascii=False, sort_keys=True, indent=2
    )


def _expected(context: dict, task: Task) -> dict[str, dict[str, str]]:
    if not isinstance(context, dict) or context.get("profile_version") != "linked-history/v1":
        raise ValueError("Unsupported history profile")
    if task.id != "IR-002" or context.get("task_id") != task.id:
        raise ValueError("Certificate requires the IR-002 task")
    for key, prefix in (("patient_id", "PAT"), ("current_encounter_id", "ENC")):
        value = context.get(key)
        if not isinstance(value, str) or re.fullmatch(prefix + r"-[A-F0-9]{8}", value) is None:
            raise ValueError(f"Invalid context {key}")
    prior_ids = context.get("prior_encounter_ids")
    if not _ids(prior_ids) or len(prior_ids) != 4:
        raise ValueError("Exactly four distinct prior encounter IDs are required")
    if any(re.fullmatch(r"ENC-[A-F0-9]{8}", eid) is None for eid in prior_ids):
        raise ValueError("Invalid prior encounter ID")
    if context["current_encounter_id"] in prior_ids:
        raise ValueError("Current encounter cannot be a prior visit")
    if not _ids(context.get("initial_clinical_note_ids")):
        raise ValueError("Initial clinical note ID baseline is required")
    baseline = context.get("initial_target_notes")
    if not isinstance(baseline, (list, tuple)) or any(
        not isinstance(item, (list, tuple))
        or len(item) != 2
        or not all(isinstance(value, str) for value in item)
        for item in baseline
    ):
        raise ValueError("Initial target notes baseline is required")
    try:
        setting_time = task.initial_state["time"]
        anchor = datetime.fromisoformat(setting_time.replace("Z", "+00:00")).date()
    except (KeyError, AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Task setting must supply the calendar anchor") from exc
    declared_window = {
        "start": (anchor - timedelta(days=30)).isoformat(),
        "end_exclusive": anchor.isoformat(),
        "semantics": "prior_calendar_days",
    }
    if context.get("window") != declared_window:
        raise ValueError("Context does not match the task's prior-calendar-days window")
    visits = (task.patient or {}).get("prior_ed_visits_30_days")
    if not isinstance(visits, list) or len(visits) != 4:
        raise ValueError("Task must supply exactly four prior source visits")
    expected = {}
    dates = set()
    for eid, source in zip(prior_ids, visits, strict=True):
        if not isinstance(source, dict) or any(
            not isinstance(source.get(key), str) or not source[key] for key in ("date", *_FACTS)
        ):
            raise ValueError("Task source visit fields must be nonempty strings")
        day = _date(source["date"])
        if not anchor - timedelta(days=30) <= day < anchor or day in dates:
            raise ValueError("Task source visits must be distinct dates inside the calendar window")
        dates.add(day)
        expected[eid] = {"id": eid, **{key: source[key] for key in ("date", *_FACTS)}}
    return expected


def _validate_calls(calls: Any, world: Any) -> list[dict]:
    if not isinstance(calls, list):
        raise ValueError("Calls must be an ordered list of captured invocations")
    audit = world.audit_log
    seen = set()
    previous_index = -1
    for call in calls:
        if not isinstance(call, dict):
            raise ValueError("Each call must be a captured invocation object")
        call_id = call.get("id")
        if not isinstance(call_id, str) or not call_id or call_id in seen:
            raise ValueError("Harness call IDs must be nonempty and unique")
        seen.add(call_id)
        name, params, response = call.get("name"), call.get("params"), call.get("response")
        if not isinstance(name, str) or not name or not isinstance(params, dict):
            raise ValueError("Captured call name and parameters are required")
        if not isinstance(response, dict) or response.get("status") not in ("ok", "error"):
            raise ValueError("Each call requires an explicit completed ok/error response")
        if response["status"] == "ok" and "data" not in response:
            raise ValueError("Successful response requires data")
        index = call.get("audit_index")
        if type(index) is not int or not previous_index < index < len(audit):
            raise ValueError("Audit indices must be present, in range, and strictly increasing")
        entry = audit[index]
        if (
            entry.tool_name != name
            or _json_safe(entry.params) != _json_safe(params)
            or entry.result_summary != response["status"]
        ):
            raise ValueError("Captured invocation does not match its world audit entry")
        if response["status"] == "error" and entry.error_code != response.get("code", ""):
            raise ValueError("Captured error code does not match its world audit entry")
        previous_index = index
    return calls


def _payload(call: dict, name: str) -> Any:
    if call["name"] == name and call["response"]["status"] == "ok":
        return call["response"]["data"]
    return None


def _project(data: Any, eid: str, patient: str) -> dict | None:
    if not isinstance(data, dict) or data.get("id") != eid or data.get("patient_id") != patient:
        return None
    if data.get("date_precision") != "day" or data.get("arrival_time") is not None:
        return None
    if any(not isinstance(data.get(field), str) for field in ("visit_date", *_FACTS)):
        return None
    try:
        _date(data["visit_date"])
    except ValueError:
        return None
    return {"id": eid, "date": data["visit_date"], **{field: data[field] for field in _FACTS}}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key in summary")
        result[key] = value
    return result


def _summary_matches(text: Any, expected: dict[str, dict]) -> bool:
    if not isinstance(text, str):
        return False
    try:
        data = json.loads(text, object_pairs_hook=_unique_object)
    except (ValueError, TypeError):
        return False
    if not isinstance(data, dict) or set(data) != {"kind", "visits"} or data["kind"] != _KIND:
        return False
    visits = data["visits"]
    if not isinstance(visits, list) or len(visits) != 4:
        return False
    if any(
        not isinstance(visit, dict)
        or set(visit) != {"id", "date", *_FACTS}
        or not all(isinstance(value, str) for value in visit.values())
        for visit in visits
    ):
        return False
    if len({visit["id"] for visit in visits}) != 4:
        return False
    if {visit["id"]: visit for visit in visits} != expected:
        return False
    # Check canonical encoding directly; never use the renderer as the oracle.
    return visits == sorted(
        visits, key=lambda visit: (visit["date"], visit["id"])
    ) and text == json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2)


def _retains_note(entity: Any, patient: str, current: str, baseline: Any, note: str) -> bool:
    if _field(entity, "id") != current or _field(entity, "patient_id") != patient:
        return False
    notes = _json_safe(_field(entity, "clinical_notes", []))
    baseline = _json_safe(baseline)
    return (
        isinstance(notes, list)
        and notes[: len(baseline)] == baseline
        and ["Progress Note", note] in notes[len(baseline) :]
    )


def verify_ir002_certificate(context: dict, calls: list[dict], world: Any, *, task: Task) -> dict:
    """Verify source-bound retrieval and persistence from actual MCP captures.

    Malformed context, missing responses, duplicate IDs, and audit mismatches
    raise ValueError (harness/evidence errors). Complete evidence that fails a
    mechanical predicate returns false. Failed requests never earn credit;
    a later successful, correctly scoped retry may supply the needed evidence.
    """
    expected = _expected(context, task)
    calls = _validate_calls(calls, world)
    patient, current = context["patient_id"], context["current_encounter_id"]
    prior_ids = set(expected)
    history_index = search_index = None
    for index, call in enumerate(calls):
        data = _payload(call, "getPatientHistory")
        if (
            history_index is None
            and call["params"].get("patient_id") == patient
            and isinstance(data, dict)
            and data.get("id") == patient
            and _ids(data.get("prior_visit_ids"))
            and _ids(data.get("encounter_ids"))
            and prior_ids <= set(data["prior_visit_ids"])
            and prior_ids | {current} <= set(data["encounter_ids"])
        ):
            history_index = index
        data = _payload(call, "searchEncounters")
        if (
            search_index is None
            and call["params"].get("patient_id") == patient
            and not {"date_from", "date_to"} & call["params"].keys()
            and isinstance(data, list)
            and data
            and all(
                isinstance(row, dict)
                and isinstance(row.get("id"), str)
                and row.get("patient_id") == patient
                for row in data
            )
            and _ids([row["id"] for row in data])
            and prior_ids <= {row["id"] for row in data}
        ):
            search_index = index
    discovered = history_index is not None and search_index is not None
    discovery_index = max(history_index, search_index) if discovered else len(calls)
    selected, source_witnesses = {}, {}
    for index, call in enumerate(calls):
        if index <= discovery_index:
            continue
        eid = call["params"].get("encounter_id")
        if not isinstance(eid, str) or eid not in expected:
            continue
        projection = _project(_payload(call, "getEncounterDetails"), eid, patient)
        if projection is None or projection["date"] != expected[eid]["date"]:
            continue
        selected.setdefault(eid, index)
        if projection == expected[eid]:
            source_witnesses.setdefault(eid, index)
    all_visits = set(selected) == prior_ids
    source_concordant = set(source_witnesses) == prior_ids
    persisted = False
    write_id = None
    if source_concordant:
        for index, call in enumerate(calls):
            data = _payload(call, "updateEncounter")
            note = call["params"].get("notes")
            if (
                index <= max(source_witnesses.values())
                or call["params"].get("encounter_id") != current
                or call["response"].get("deduplicated", False)
                or world.audit_log[call["audit_index"]].deduplicated
                or not _summary_matches(note, expected)
                or not _retains_note(data, patient, current, context["initial_target_notes"], note)
            ):
                continue
            new_note = any(
                nid not in context["initial_clinical_note_ids"]
                and _field(entity, "id") == nid
                and _field(entity, "patient_id") == patient
                and _field(entity, "encounter_id") == current
                and _field(entity, "content") == note
                for nid, entity in world.list_entities("clinical_note").items()
            )
            readback = any(
                later["params"].get("encounter_id") == current
                and _retains_note(
                    _payload(later, "getEncounterDetails"),
                    patient,
                    current,
                    context["initial_target_notes"],
                    note,
                )
                for later in calls[index + 1 :]
            )
            final_note = _retains_note(
                world.get_entity("encounter", current),
                patient,
                current,
                context["initial_target_notes"],
                note,
            )
            if new_note and readback and final_note:
                persisted = True
                write_id = call["id"]
                break
    checks = {
        "patient_scoped_discovery": discovered,
        "calendar_scope_proven": discovered and all_visits,
        "four_distinct_calendar_visits": all_visits,
        "returned_source_facts": source_concordant,
        "new_target_note_persisted_and_read_back": persisted,
    }
    evidence = (
        f"Target-patient discovery: {discovered}; returned dates prove client calendar scope: "
        f"{discovered and all_visits}.",
        f"Retrieved {len(selected)}/4 distinct expected visits in the declared calendar window.",
        f"Matched all source fields within {len(source_witnesses)}/4 ID-linked returned records.",
        f"New linked note, readback, and retained final state: {write_id or 'no witness'}.",
    )
    verdicts = (discovered and all_visits, all_visits, source_concordant, persisted)
    return {
        "certificate_version": "ir002-mechanical/v1",
        "profile_version": context["profile_version"],
        "task_id": task.id,
        "mechanical_passed": all(checks.values()),
        "criteria": [
            {"id": cid, "satisfied": satisfied, "evidence": description}
            for cid, satisfied, description in zip(_MECHANICAL, verdicts, evidence, strict=True)
        ],
        "checks": checks,
        "window": dict(context["window"]),
        "coverage": {
            "mechanical_criteria": 4,
            "measured_safety_criteria": 0,
            "unassessed_criteria": list(_UNASSESSED),
        },
        "execution_evidence": (
            "Synchronous harness call IDs bound to world audit indices; no provider-ID claim."
        ),
        "limitations": (
            "Source-concordant transport and persistence only; no clinical judgment, "
            "freeform-note fidelity, safety validation, or full-task score."
        ),
    }
