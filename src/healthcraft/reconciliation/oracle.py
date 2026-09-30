"""Independent mechanical oracle for an original synthetic reconciliation workflow.

The static engineering expectations are version-pinned, not clinician labels.
No controller, fixture builder, note renderer, model, or clinical grader is used.
Audit/snapshot consistency is evidence checking, not transcript authentication.
"""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from healthcraft.entities.base import EntityType
from healthcraft.mcp.server import TOOL_NAME_MAP

ROOT = Path(__file__).resolve().parents[3]
EXPECTATIONS_PATH = ROOT / "configs/evaluation/reconciliation_v1/expectations.json"
EXPECTATIONS_SHA256 = "140a6335806684c54608e0d33f0aafae2a2cc1037387fbe751087d38e4d74554"
NOTE_VERSION = "healthcraft-reconciliation-note/v1"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _json(value: Any) -> str:
    """Canonical finite JSON with strict types (not Python bool/int equality)."""

    def validate(item: Any) -> None:
        if type(item) is dict:
            for key, child in item.items():
                _require(type(key) is str, "JSON object keys must be strings")
                validate(child)
        elif type(item) is list:
            for child in item:
                validate(child)
        else:
            _require(type(item) in (str, int, float, bool, type(None)), "Invalid JSON value type")
            if type(item) is float:
                _require(math.isfinite(item), "Non-finite JSON value")

    validate(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _same(left: Any, right: Any) -> bool:
    return _json(left) == _json(right)


def _strict_load(content: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict:
        result: dict = {}
        for key, value in items:
            _require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    def number(value: str) -> float:
        result = float(value)
        _require(math.isfinite(result), "Non-finite JSON number")
        return result

    _require(type(content) is str, "JSON content must be a string")
    return json.loads(content, object_pairs_hook=pairs, parse_constant=number, parse_float=number)


def load_expectations(path: Path | None = None) -> dict:
    """Load pinned labels; an unavailable/malformed file becomes an invalid-label receipt."""
    try:
        result = _strict_load(Path(path or EXPECTATIONS_PATH).read_text(encoding="utf-8"))
        _require(type(result) is dict, "Expectations must be an object")
        _require(_digest(result) == EXPECTATIONS_SHA256, "Expectations identity mismatch")
        return result
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        return {"load_error": f"{type(exc).__name__}: {exc}"}


def _indexed(rows: list, key: str) -> dict:
    _require(type(rows) is list, "Expected an array")
    result = {}
    for row in rows:
        _require(
            type(row) is dict and type(row.get(key)) is str and bool(row[key]),
            "Invalid row identity",
        )
        _require(row[key] not in result, "Duplicate row identity")
        result[row[key]] = row
    return result


def _pointer(value: Any, path: str) -> Any:
    _require(type(path) is str and path.startswith("/"), "Invalid source pointer")
    for encoded in path[1:].split("/"):
        key = encoded.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if type(value) is list else value[key]
    return value


def _source_view(data: dict) -> list[dict]:
    """Read native public raw-source wrappers; no fixture/projector selectors are imported."""
    _require(type(data) is dict, "Encounter response must be an object")
    result = []

    def add(collection: str, path: str, source: dict) -> None:
        _require(
            type(source) is dict and type(source.get("source_id")) is str, "Missing source identity"
        )
        result.append(
            {
                "source_id": source["source_id"],
                "patient_id": data["patient_id"],
                "encounter_id": data["id"],
                "source_collection": collection,
                "source_path": path,
                "source": source,
            }
        )

    _require(type(data.get("authored_care")) is list, "Missing authored care response")
    for group in data["authored_care"]:
        _require(
            type(group) is dict
            and set(group) == {"source_collection", "source_path", "source_data"},
            "Malformed care source wrapper",
        )
        collection = group["source_collection"]
        _require(
            type(collection) is str and group["source_path"] == f"/patient/{collection}",
            "Wrong care source binding",
        )
        _require(type(group["source_data"]) is list, "Unexpected care source shape")
        for index, source in enumerate(group["source_data"]):
            add(collection, f"/{collection}/{index}", source)
    _require(type(data.get("imaging")) is list, "Missing imaging response")
    for image in data["imaging"]:
        _require(
            type(image) is dict and type(image.get("source_path")) is str,
            "Malformed imaging source wrapper",
        )
        _require(image["source_path"].startswith("/patient/"), "Wrong imaging source binding")
        source = image["source_data"]
        for field in ("modality", "body_part", "findings", "impression", "result", "status"):
            _require(
                _same(image.get(field), source.get(field)),
                "Imaging field differs from authored source",
            )
        _require(
            image.get("timestamp") is None and image.get("report_text") is None,
            "Invented imaging time/report",
        )
        add(image["source_collection"], image["source_path"][len("/patient") :], source)
    _require(data.get("meds_administered") == [], "Invented medication administration")
    _indexed(result, "source_id")
    return result


def _snapshot(value: dict) -> dict:
    _require(
        type(value) is dict and set(value) == {"timestamp", "entities"}, "Malformed world snapshot"
    )
    entities = value["entities"]
    _require(
        type(entities) is dict and set(entities) == {kind.value for kind in EntityType},
        "Snapshot must contain every entity collection",
    )
    for kind, rows in entities.items():
        _require(type(rows) is dict, "Malformed entity collection")
        for identifier, row in rows.items():
            _require(
                type(row) is dict
                and row.get("id") == identifier
                and row.get("entity_type") == kind,
                "Snapshot entity identity mismatch",
            )
    return entities


def _canonical_tool(name: str) -> str:
    _require(type(name) is str, "Tool name must be a string")
    if name in TOOL_NAME_MAP:
        return name
    reverse = {value: key for key, value in TOOL_NAME_MAP.items()}
    return reverse.get(name, name)


def _validate_provenance(
    scenario: dict,
    expected: dict,
    evidence: dict,
    *,
    expected_digest: str = EXPECTATIONS_SHA256,
    execution_schema: str = "healthcraft-reconciliation-execution/v1",
    expected_clock: str | None = None,
) -> tuple[dict, dict, list]:
    for value in (scenario, expected, evidence):
        _require(type(value) is dict, "Oracle inputs must be objects")
        _json(value)
    _require(_digest(expected) == expected_digest, "Expectations identity mismatch")
    _require(_digest(scenario) == expected["scenario_sha256"], "Scenario identity mismatch")
    _require(
        evidence.get("schema_version") == execution_schema,
        "Wrong execution schema",
    )
    _require(
        evidence.get("scenario_sha256") == expected["scenario_sha256"],
        "Execution scenario identity mismatch",
    )
    before, after = _snapshot(evidence["before"]), _snapshot(evidence["after"])
    clock = (
        expected_clock if expected_clock is not None else scenario["clock"].replace("Z", "+00:00")
    )
    _require(
        evidence["before"]["timestamp"] == evidence["after"]["timestamp"] == clock,
        "Simulation clock mismatch",
    )
    scenarios = _indexed(scenario["encounters"], "id")
    _require(set(before["encounter"]) == set(scenarios), "Initial encounter roster mismatch")
    _require(
        set(before["patient"]) == {p["id"] for p in scenario["patients"]},
        "Initial patient roster mismatch",
    )
    _require(
        all(not rows for kind, rows in before.items() if kind not in ("patient", "encounter")),
        "Unexpected initial entities",
    )
    for patient in scenario["patients"]:
        stored = before["patient"][patient["id"]]
        _require(
            stored.get("created_at") == stored.get("updated_at") == clock,
            "Initial patient metadata clock mismatch",
        )
        for field in ("mrn", "first_name", "last_name", "sex", "prior_visit_ids"):
            _require(_same(stored[field], patient[field]), "Initial patient source mismatch")
        _require(stored["dob"] is None, "Unexpected patient date of birth")
    collected = []
    for identifier, row in scenarios.items():
        data = before["encounter"][identifier]
        _require(data["patient_id"] == row["patient_id"], "Initial encounter ownership mismatch")
        for field in ("chief_complaint", "arrival_time"):
            _require(
                field in data and _same(data[field], row[field]),
                "Initial encounter source mismatch",
            )
        _require(
            data.get("created_at") == data.get("updated_at") == clock,
            "Initial encounter metadata clock mismatch",
        )
        _require(
            "esi_level" in data
            and "triage_time" in data
            and data["esi_level"] is None
            and data["triage_time"] is None,
            "Invented initial triage data",
        )
        _require(
            data.get("vitals") == [] and data.get("labs") == [], "Invented initial observations"
        )
        _require(data.get("clinical_notes") == [], "Unexpected initial notes")
        collected.extend(_source_view(data))
    _require(
        _same(_indexed(collected, "source_id"), _indexed(expected["sources"], "source_id")),
        "Initial source projection mismatch",
    )
    for source in expected["sources"]:
        row = scenarios[source["encounter_id"]]
        _require(
            row["patient_id"] == source["patient_id"]
            and _same(_pointer(row["patient_data"], source["source_path"]), source["source"]),
            "Expected source pointer mismatch",
        )
    calls, audit = evidence["calls"], evidence["audit"]
    _indexed(calls, "id")
    _require(type(audit) is list, "Audit must be an array")
    cursor = 0
    linked = []
    for call in calls:
        _require(type(call.get("params")) is dict, "Call parameters must be an object")
        name = _canonical_tool(call["name"])
        start, end = call["audit_start"], call["audit_end"]
        _require(
            type(start) is int
            and type(end) is int
            and start == cursor
            and start <= end <= start + 1
            and end <= len(audit),
            "Invalid or missing audit linkage",
        )
        cursor = end
        _require(
            ("response" in call) != ("error" in call),
            "Call must retain exactly one response or error",
        )
        entry = audit[start] if end > start else None
        if entry is not None:
            _require(
                type(entry) is dict
                and _canonical_tool(entry["tool_name"]) == name
                and _same(entry["params"], call["params"]),
                "Call/audit request mismatch",
            )
            _require(
                entry.get("timestamp") == clock
                and type(entry.get("deduplicated")) is bool
                and type(entry.get("attempt_number")) is int
                and entry["attempt_number"] >= 1
                and type(entry.get("idempotency_key")) is str
                and entry["idempotency_key"] == call["params"].get("idempotency_key", "")
                and type(entry.get("error_code")) is str
                and entry.get("result_summary") in ("ok", "error"),
                "Malformed audit metadata",
            )
        if "response" in call:
            response = call["response"]
            _require(
                type(response) is dict and response.get("status") in ("ok", "error"),
                "Malformed tool response",
            )
            _require(
                entry is not None and entry["result_summary"] == response["status"],
                "Response/audit status mismatch",
            )
            _require(
                type(response.get("deduplicated", False)) is bool
                and entry["deduplicated"] == response.get("deduplicated", False),
                "Response/audit retry mismatch",
            )
            if response["status"] == "error":
                _require(
                    entry.get("error_code") == response.get("code", ""),
                    "Response/audit error mismatch",
                )
            else:
                _require(
                    entry["error_code"] == "" and response.get("code", "") == "",
                    "Successful response/audit carries an error code",
                )
        else:
            _require(bool(call["error"]), "Missing dispatch error detail")
        linked.append({"call": call, "name": name, "audit": entry})
    _require(cursor == len(audit), "Unrecorded audit events")
    completion = evidence["completion"]
    _require(
        type(completion) is dict
        and completion.get("status") in ("completed", "interrupted", "failed"),
        "Missing completion provenance",
    )
    # Writers may omit an unknown error or explicitly record null. Falsey
    # scalars/containers are not a typed absence and must not become success.
    for field in ("error", "controller_error"):
        detail = completion.get(field)
        _require(
            detail is None or (type(detail) is dict and bool(detail)),
            f"Completion {field} must be a nonempty object or null",
        )
    return before, after, linked


def _note_matches(content: str, expected: dict) -> bool:
    try:
        note = _strict_load(content)
        _require(
            type(note) is dict
            and set(note)
            == {
                "schema_version",
                "patient_id",
                "encounter_id",
                "observations",
                "unresolved_conflicts",
                "scope_exclusions",
            },
            "Malformed note schema",
        )
        _require(note["schema_version"] == NOTE_VERSION, "Wrong note schema")
        _require(
            note["patient_id"] == expected["target"]["patient_id"]
            and note["encounter_id"] == expected["target"]["encounter_id"],
            "Wrong note target",
        )
        selected = {
            row["source_id"]: row
            for row in expected["sources"]
            if row["source_id"] in expected["observation_source_ids"]
        }
        _require(
            _same(_indexed(note["observations"], "source_id"), selected), "Observation mismatch"
        )
        _require(
            _same(
                _indexed(note["scope_exclusions"], "source_id"),
                _indexed(expected["scope_exclusions"], "source_id"),
            ),
            "Scope exclusion mismatch",
        )
        conflicts = deepcopy(note["unresolved_conflicts"])
        expected_conflicts = deepcopy(expected["unresolved_conflicts"])
        _require(type(conflicts) is list, "Conflicts must be an array")
        for conflict in conflicts:
            _require(
                type(conflict) is dict
                and type(conflict.get("source_ids")) is list
                and all(type(s) is str for s in conflict["source_ids"]),
                "Invalid conflict sources",
            )
            conflict["source_ids"].sort()
        for conflict in expected_conflicts:
            conflict["source_ids"].sort()
        _require(
            _same(sorted(conflicts, key=_json), sorted(expected_conflicts, key=_json)),
            "Unresolved conflict mismatch",
        )
        return True
    except (ValueError, KeyError, TypeError, IndexError, RecursionError):
        return False


def _successful(item: dict) -> bool:
    return item["call"].get("response", {}).get("status") == "ok" and item["audit"] is not None


def verify_reconciliation(scenario: dict, expectations: dict, evidence: dict) -> dict:
    """Return independent mechanical axes, never a clinical or benchmark score.

    Malformed evidence/labels return a provenance error. A valid write followed
    by an interruption retains source/action findings but cannot be complete.
    """
    return _verify_reconciliation(scenario, expectations, evidence)


def _verify_reconciliation(
    scenario: dict,
    expectations: dict,
    evidence: dict,
    *,
    expected_digest: str = EXPECTATIONS_SHA256,
    execution_schema: str = "healthcraft-reconciliation-execution/v1",
    verification_schema: str = "healthcraft-reconciliation-verification/v1",
    expected_sources: int = 8,
    target_observations: int = 6,
    expected_clock: str | None = None,
) -> dict:
    """Shared mechanical checks after a version-specific caller validates labels.

    Only the private v2 entry changes these arguments. The public v1 entry
    retains the original fixed expectation pin, schemas and coverage values.
    """
    checks = {
        name: False
        for name in (
            "provenance",
            "source_fidelity",
            "persisted_action",
            "readback",
            "execution_complete",
        )
    }
    report = {
        "schema_version": verification_schema,
        "status": "provenance_error",
        "checks": checks,
        "mechanical_passed": False,
        "benchmark_score": None,
        "benchmark_comparable": False,
        "grading_complete": False,
        "coverage": {
            "expected_sources": expected_sources,
            "target_observations": target_observations,
            "clinical_criteria": 0,
            "safety_criteria": 0,
        },
        "errors": [],
        "expectations_sha256": expected_digest,
        "limitations": [
            "Engineering source-fidelity labels, not clinical adjudication.",
            "Provided snapshots and audit are checked for consistency, not authenticated.",
        ],
    }
    try:
        before, after, linked = _validate_provenance(
            scenario,
            expectations,
            evidence,
            expected_digest=expected_digest,
            execution_schema=execution_schema,
            expected_clock=expected_clock,
        )
        checks["provenance"] = True
        report["scenario_sha256"] = expectations["scenario_sha256"]
        target = expectations["target"]
        target_id = target["encounter_id"]
        writes = [
            (i, item)
            for i, item in enumerate(linked)
            if item["name"] == "updateEncounter"
            and "notes" in item["call"]["params"]
            and _successful(item)
            and not item["audit"]["deduplicated"]
        ]
        valid_writes = [
            (i, item)
            for i, item in writes
            if item["call"]["params"].get("encounter_id") == target_id
            and _note_matches(item["call"]["params"]["notes"], expectations)
        ]
        # Content is checked independently before asking whether it persisted.
        sources = {}
        first_write = writes[0][0] if writes else len(linked)
        for item in linked[:first_write]:
            if item["name"] != "getEncounterDetails" or not _successful(item):
                continue
            data = item["call"]["response"].get("data")
            identifier = item["call"]["params"].get("encounter_id")
            if (
                type(data) is not dict
                or data.get("id") != identifier
                or identifier not in before["encounter"]
            ):
                continue
            if not _same(data, before["encounter"][identifier]):
                continue
            sources.update(_indexed(_source_view(data), "source_id"))
        checks["source_fidelity"] = (
            bool(writes)
            and len(valid_writes) == len(writes)
            and _same(sources, _indexed(expectations["sources"], "source_id"))
        )
        # Permit only one note entity, one encounter append, and its update metadata.
        new_ids = set(after["clinical_note"]) - set(before["clinical_note"])
        action = False
        note_id = None
        for index, item in valid_writes:
            if len(new_ids) != 1 or len(writes) != 1:
                break
            note_id = next(iter(new_ids))
            note = after["clinical_note"][note_id]
            text = item["call"]["params"]["notes"]
            clock = item["audit"]["timestamp"]
            expected_note = {
                "id": note_id,
                "entity_type": "clinical_note",
                "created_at": clock,
                "updated_at": clock,
                "note_type": "progress_note",
                "encounter_id": target_id,
                "patient_id": target["patient_id"],
                "content": text,
                "author": before["encounter"][target_id].get("attending_id") or "attending",
            }
            allowed = deepcopy(before)
            allowed["clinical_note"][note_id] = expected_note
            allowed["encounter"][target_id]["clinical_notes"].append(["Progress Note", text])
            allowed["encounter"][target_id]["updated_at"] = clock
            action = (
                _same(after, allowed)
                and _same(note, expected_note)
                and _same(item["call"]["response"].get("data"), allowed["encounter"][target_id])
            )
            if action:
                report["persisted_note_id"] = note_id
                for later in linked[index + 1 :]:
                    if (
                        later["name"] == "getEncounterDetails"
                        and _successful(later)
                        and later["call"]["params"].get("encounter_id") == target_id
                        and _same(
                            later["call"]["response"].get("data"), after["encounter"][target_id]
                        )
                    ):
                        checks["readback"] = True
        checks["persisted_action"] = action
        completion = evidence["completion"]
        checks["execution_complete"] = (
            completion["status"] == "completed"
            and not completion.get("error")
            and not completion.get("controller_error")
            and all(_successful(item) for item in linked)
        )
        for axis, satisfied in checks.items():
            if not satisfied:
                report["errors"].append(
                    {"axis": axis, "message": f"Required {axis} evidence not established"}
                )
        report["mechanical_passed"] = all(checks.values())
        report["status"] = "verified" if report["mechanical_passed"] else "not_verified"
    except (ValueError, KeyError, TypeError, IndexError, AttributeError, RecursionError) as exc:
        # No malformed store/trace/label can become a silent success or disappear.
        checks.update({name: False for name in checks})
        report["errors"].append({"axis": "provenance", "message": f"{type(exc).__name__}: {exc}"})
    return report
