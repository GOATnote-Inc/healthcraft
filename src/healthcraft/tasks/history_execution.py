"""Actual tool execution for the opt-in IR-002 mechanical reference certificate.

The reference controller receives target IDs and a calendar window, never
the task's expected visit facts. A separate verifier reads those source facts.
"""

from __future__ import annotations

import hashlib
import json
import platform
from copy import deepcopy
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from healthcraft.llm.checkpoint import content_digest, environment_digest
from healthcraft.mcp.server import HealthcraftServer, create_server
from healthcraft.tasks.loader import load_task
from healthcraft.world.seed import WorldSeeder
from healthcraft.world.state import WorldState

ROOT = Path(__file__).resolve().parents[3]
TASK_PATH = ROOT / "configs/tasks/information_retrieval/task_002_encounter_lookup.yaml"
WORLD_PATH = ROOT / "configs/world/mercy_point_v1.yaml"


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Unsupported evidence type: {type(value).__name__}")


def _json_snapshot(value: Any) -> Any:
    return json.loads(json.dumps(value, default=_json_default, allow_nan=False))


class ExecutionRecorder:
    """Snapshot synchronous in-process requests and actual tool responses.

    IDs identify recorder calls, not provider-generated tool messages. Evidence
    is tied to the corresponding real world audit entry; hashes detect changed
    content but do not attest the trustworthiness of a third-party transcript.
    """

    def __init__(self, server: HealthcraftServer, world: WorldState) -> None:
        self._server = server
        self._world = world
        self._calls: list[dict[str, Any]] = []

    @property
    def calls(self) -> list[dict[str, Any]]:
        return deepcopy(self._calls)

    def call(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        request = deepcopy(params)
        audit_index = len(self._world.audit_log)
        response = self._server.call_tool(name, deepcopy(request))
        if len(self._world.audit_log) != audit_index + 1:
            raise ValueError("Tool dispatch must produce exactly one world audit entry")
        self._calls.append(
            _json_snapshot(
                {
                    "id": f"call-{len(self._calls) + 1:04d}",
                    "name": name,
                    "params": request,
                    "response": response,
                    "audit_index": audit_index,
                }
            )
        )
        return deepcopy(response)


def execute_history_reference(
    recorder: ExecutionRecorder,
    *,
    patient_id: str,
    current_encounter_id: str,
    window: dict[str, str],
) -> None:
    """Retrieve linked records, select by calendar date, then persist/read back.

    Selection is client-side because these authored visits contain no arrival
    instants. No expected visit IDs, count, diagnoses, or notes enter this API.
    """
    from healthcraft.tasks.history_certificate import render_history_summary

    searched = recorder.call("searchEncounters", {"patient_id": patient_id})
    history = recorder.call("getPatientHistory", {"patient_id": patient_id})
    if searched.get("status") != "ok" or history.get("status") != "ok":
        raise ValueError("Reference retrieval failed")
    found = {row["id"] for row in searched["data"] if row.get("patient_id") == patient_id}
    selected = []
    start, end = date.fromisoformat(window["start"]), date.fromisoformat(window["end_exclusive"])
    for encounter_id in history["data"]["prior_visit_ids"]:
        if encounter_id not in found:
            raise ValueError("Linked prior encounter is absent from patient search")
        response = recorder.call("getEncounterDetails", {"encounter_id": encounter_id})
        if response.get("status") != "ok":
            raise ValueError("Reference detail retrieval failed")
        record = response["data"]
        if record.get("patient_id") != patient_id:
            raise ValueError("Prior encounter belongs to another patient")
        visit_date = date.fromisoformat(record["visit_date"])
        if start <= visit_date < end:
            selected.append(record)
    summary = render_history_summary(selected)
    updated = recorder.call(
        "updateEncounter", {"encounter_id": current_encounter_id, "notes": summary}
    )
    if updated.get("status") != "ok":
        raise ValueError("Reference documentation failed")
    readback = recorder.call("getEncounterDetails", {"encounter_id": current_encounter_id})
    if readback.get("status") != "ok":
        raise ValueError("Reference documentation readback failed")


def _source_hashes() -> dict[str, str]:
    files = set((ROOT / "src/healthcraft").rglob("*.py"))
    files.update(
        {
            TASK_PATH,
            WORLD_PATH,
            ROOT / "configs/mcp-tools.json",
            ROOT / "scripts/certify_history_task.py",
        }
    )
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(files)
    }


def run_ir002_reference(*, world: WorldState | None = None, seed: int = 42) -> dict[str, Any]:
    """Run the versioned mechanical witness without model calls or score changes."""
    from healthcraft.tasks.history_certificate import verify_ir002_certificate
    from healthcraft.tasks.history_profile import build_ir002_profile

    task = load_task(TASK_PATH)
    supplied_world = world is not None
    if world is None:
        world = WorldSeeder(seed=seed).seed_world(WORLD_PATH)
    setting_time = datetime.fromisoformat(task.initial_state["time"].replace("Z", "+00:00"))
    delta = (setting_time - world.timestamp).total_seconds()
    if delta < 0 or delta % 60:
        raise ValueError("Reference world clock must precede the setting by whole minutes")
    world.advance_time(int(delta / 60))
    context = build_ir002_profile(world, task)
    recorder = ExecutionRecorder(create_server(world), world)
    execute_history_reference(
        recorder,
        patient_id=context["patient_id"],
        current_encounter_id=context["current_encounter_id"],
        window=context["window"],
    )
    calls = recorder.calls
    verification = verify_ir002_certificate(context, calls, world, task=task)
    hashes = _source_hashes()
    return _json_snapshot(
        {
            "schema_version": "healthcraft-reference-certificate/v1",
            "execution_kind": "in_process_mcp_handlers",
            "profile_version": context["profile_version"],
            "task_id": task.id,
            "task_sha256": hashes[str(TASK_PATH.relative_to(ROOT))],
            "world_preparation": "caller_supplied" if supplied_world else "seeded_mercy_point",
            "seed": None if supplied_world else seed,
            "python_version": platform.python_version(),
            "environment_sha256": environment_digest(ROOT),
            "source_hashes": hashes,
            "context": context,
            "calls": calls,
            "trace_sha256": content_digest(calls),
            "verification": verification,
            "limitations": (
                "An engineering-authored reference witness for one opt-in profile. "
                "It checks exact source-fact transport and persistence, not clinical reasoning, "
                "freeform summary quality, model performance, MCP network transport, FHIR "
                "conformance, or clinical readiness. Recorder call IDs are synchronous harness "
                "identities, not provider message IDs. Content hashes are not attestations. "
                "Historical tasks, reward computation, and results are unchanged."
            ),
        }
    )
