"""Original synthetic reconciliation through actual in-process MCP handlers.

The reference controller receives public target IDs and tool results only.
It does not import the oracle or its expected source facts. Journals preserve
pre-dispatch attempts, including calls with no simulator audit entry.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from healthcraft.mcp.server import create_server
from healthcraft.tasks.history_execution import _json_snapshot


def scenario_digest(scenario: dict) -> str:
    """Digest exact finite JSON values, independent of whitespace/key order."""
    payload = json.dumps(
        scenario, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ReconciliationRecorder:
    """Keep detached request/response evidence and an optional durable journal.

    The journal is append-only within a new file. A process killed between a
    request and its outcome leaves a visibly unresolved attempt. This is not a
    transaction log or authentication of third-party execution.
    """

    def __init__(self, server, world, *, journal_path: Path | None = None) -> None:
        self._server = server
        self._world = world
        self._calls: list[dict] = []
        self._journal = journal_path.open("x", encoding="utf-8") if journal_path else None

    @property
    def calls(self) -> list[dict]:
        return deepcopy(self._calls)

    def close(self) -> None:
        if self._journal:
            self._journal.close()
            self._journal = None

    def _event(self, event: str, call: dict) -> None:
        if self._journal:
            self._journal.write(json.dumps({"event": event, "call": call}, allow_nan=False) + "\n")
            self._journal.flush()
            os.fsync(self._journal.fileno())

    def call(self, name: str, params: dict) -> dict:
        call: dict[str, Any] = {
            "id": f"call-{len(self._calls) + 1:04d}",
            "name": name if type(name) is str else None,
            "audit_start": len(self._world.audit_log),
        }
        self._calls.append(call)
        stage = "request_serialization"
        try:
            if type(name) is not str or type(params) is not dict:
                raise ValueError("Tool name/parameters must be a string/object")
            # Snapshot before dispatch; the handler cannot rewrite the request.
            call["params"] = _json_snapshot(params)
            self._event("requested", call)
            stage = "dispatch"
            response = self._server.call_tool(name, deepcopy(call["params"]))
            stage = "response_serialization"
            if type(response) is not dict:
                raise ValueError("Tool response must be an object")
            call["response"] = _json_snapshot(response)
            call["audit_end"] = len(self._world.audit_log)
            self._event("returned", call)
            return deepcopy(call["response"])
        except (Exception, KeyboardInterrupt) as exc:
            call["audit_end"] = len(self._world.audit_log)
            call["error"] = {
                "stage": stage,
                "type": type(exc).__name__,
                "message": str(exc),
                "outcome": "not_dispatched" if stage == "request_serialization" else "unknown",
            }
            self._event("failed", call)
            raise


def _ok(recorder, name: str, params: dict) -> Any:
    response = recorder.call(name, params)
    if response.get("status") != "ok" or "data" not in response:
        raise ValueError(f"{name} failed: {response.get('code', 'invalid_response')}")
    return response["data"]


def _source_records(encounter: dict) -> list[dict]:
    """Read raw authored rows from returned projections, never typed guesses."""
    rows = []

    def collect(value: Any, *, collection: str, path: str) -> None:
        if isinstance(value, dict) and "source_id" in value:
            rows.append(
                {
                    "source_id": value["source_id"],
                    "patient_id": encounter["patient_id"],
                    "encounter_id": encounter["id"],
                    "source_collection": collection,
                    "source_path": path,
                    "source": deepcopy(value),
                }
            )
        elif isinstance(value, dict):
            for key, child in value.items():
                escaped = key.replace("~", "~0").replace("/", "~1")
                collect(child, collection=collection, path=f"{path}/{escaped}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                collect(child, collection=collection, path=f"{path}/{index}")

    for projection in (*encounter["authored_care"], *encounter["imaging"]):
        path = projection["source_path"]
        if not path.startswith("/patient/"):
            raise ValueError("Unexpected source pointer namespace")
        collect(
            projection["source_data"],
            collection=projection["source_collection"],
            path=path[len("/patient") :],
        )
    return rows


def execute_reference(recorder, *, target: dict) -> None:
    """Reconcile the closed synthetic same-name cohort and persist/read back.

    This narrow reference does not solve arbitrary clinical contradictions.
    It retains opposing literal reported-status assertions for the same event.
    Saturated searches are rejected because these handlers expose no offset.
    """
    patient_id, encounter_id = target["patient_id"], target["encounter_id"]
    history = _ok(recorder, "getPatientHistory", {"patient_id": patient_id})
    if history.get("id") != patient_id:
        raise ValueError("Patient history identity mismatch")
    name = f"{history['first_name']} {history['last_name']}"
    patients = _ok(recorder, "searchPatients", {"name": name})
    if len(patients) >= 10:
        raise ValueError("Patient search saturated; completeness cannot be established")
    if patient_id not in {row["id"] for row in patients}:
        raise ValueError("Target absent from same-name cohort")
    records = []
    seen_encounters = set()
    for patient in sorted(patients, key=lambda row: row["id"]):
        encounters = _ok(recorder, "searchEncounters", {"patient_id": patient["id"]})
        if len(encounters) >= 10:
            raise ValueError("Encounter search saturated; completeness cannot be established")
        for row in sorted(encounters, key=lambda row: row["id"]):
            if row["patient_id"] != patient["id"] or row["id"] in seen_encounters:
                raise ValueError("Encounter search identity mismatch or duplicate")
            seen_encounters.add(row["id"])
            details = _ok(recorder, "getEncounterDetails", {"encounter_id": row["id"]})
            if details.get("id") != row["id"] or details.get("patient_id") != patient["id"]:
                raise ValueError("Encounter details identity mismatch")
            records.extend(_source_records(details))
    if encounter_id not in seen_encounters:
        raise ValueError("Target encounter was not retrieved")
    ids = [row["source_id"] for row in records]
    if len(set(ids)) != len(ids):
        raise ValueError("Ambiguous duplicate source identifiers")
    included, excluded = [], []
    for row in sorted(records, key=lambda row: row["source_id"]):
        if row["patient_id"] == patient_id and row["encounter_id"] == encounter_id:
            included.append(row)
        else:
            excluded.append(
                {key: row[key] for key in ("source_id", "patient_id", "encounter_id")}
                | {
                    "reason": "other_patient"
                    if row["patient_id"] != patient_id
                    else "other_encounter"
                }
            )
    if not included:
        raise ValueError("No current-encounter source records")
    events: dict[str, list[dict]] = defaultdict(list)
    for row in included:
        if row["source"].get("event_id"):
            events[row["source"]["event_id"]].append(row)
    conflicts = []
    for event_id, rows in sorted(events.items()):
        statuses = {row["source"].get("reported_status") for row in rows}
        if {"administered", "not_administered"} <= statuses:
            conflicts.append(
                {
                    "source_ids": sorted(row["source_id"] for row in rows),
                    "event_id": event_id,
                    "field": "reported_status",
                }
            )
    note = {
        "schema_version": "healthcraft-reconciliation-note/v1",
        "patient_id": patient_id,
        "encounter_id": encounter_id,
        "observations": included,
        "unresolved_conflicts": conflicts,
        "scope_exclusions": excluded,
    }
    params = {
        "encounter_id": encounter_id,
        "notes": json.dumps(note, sort_keys=True, ensure_ascii=False, allow_nan=False),
        "idempotency_key": "synthetic-reconciliation-note-v1",
    }
    _ok(recorder, "updateEncounter", params)
    _ok(recorder, "updateEncounter", params)
    _ok(recorder, "getEncounterDetails", {"encounter_id": encounter_id})


def run_reconciliation_trial(
    *,
    scenario: dict | None = None,
    controller: Callable = execute_reference,
    server_factory: Callable = create_server,
    journal_path: Path | None = None,
) -> dict:
    """Capture one fresh world execution; incomplete attempts remain evidence.

    Fixture construction errors raise to the roster coordinator, which must
    retain them as preparation errors. Once execution starts, controller/tool
    failures produce a partial evidence record rather than an empty retry.
    """
    from healthcraft.reconciliation.fixture import build_world, load_scenario, snapshot_world

    scenario = deepcopy(scenario) if scenario is not None else load_scenario()
    world = build_world(scenario)
    before = snapshot_world(world)
    recorder = ReconciliationRecorder(server_factory(world), world, journal_path=journal_path)
    completion: dict = {"status": "completed"}
    try:
        controller(recorder, target=deepcopy(scenario["target"]))
    except (Exception, KeyboardInterrupt) as exc:
        completion = {
            "status": "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
    finally:
        recorder.close()
    return {
        "schema_version": "healthcraft-reconciliation-execution/v1",
        "execution_kind": "in_process_mcp_handlers",
        "scenario_sha256": scenario_digest(scenario),
        "before": before,
        "after": snapshot_world(world),
        "calls": recorder.calls,
        "audit": _json_snapshot([asdict(entry) for entry in world.audit_log]),
        "completion": completion,
    }
