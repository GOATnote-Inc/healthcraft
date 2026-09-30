"""Source-bound, single-attempt execution for the opt-in reconciliation casebook.

The controller sees public tool responses and target IDs only. Completion is
termination of that controller, not a claim that the independently verified
source, storage, scope, conflict or readback requirements were satisfied.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from healthcraft.mcp.server import create_server
from healthcraft.reconciliation.execution import (
    ReconciliationRecorder,
    execute_reference,
    scenario_digest,
)
from healthcraft.reconciliation.fixture import _json_copy, _keys, _text, snapshot_world
from healthcraft.reconciliation.fixture_v2 import build_world, validate_scenario
from healthcraft.tasks.history_execution import _json_snapshot

_CASE_FIELDS = {
    "schema_version",
    "case_id",
    "scenario_family_id",
    "exposure",
    "label_status",
    "casebook_sha256",
    "scenario_sha256",
    "expectations_sha256",
    "scenario",
    "expectations",
    "designated_control",
}
_BINDING_FIELDS = (
    "case_id",
    "casebook_sha256",
    "scenario_sha256",
    "expectations_sha256",
    "scenario_family_id",
)


def _validated_case(case: dict) -> dict:
    data = _json_copy(case)
    _keys(data, _CASE_FIELDS)
    if data["schema_version"] != "healthcraft-reconciliation-case/v2":
        raise ValueError("Unsupported reconciliation case version")
    if type(data["case_id"]) is not str or not re.fullmatch(r"REC2-[0-9]{3}", data["case_id"]):
        raise ValueError("Invalid case identifier")
    for field in ("scenario_family_id", "designated_control"):
        _text(data[field])
    if data["exposure"] != "development" or data["label_status"] != (
        "engineering_authored_independent_review_pending"
    ):
        raise ValueError(
            "Only the explicitly exposed engineering-development casebook is supported"
        )
    for field in ("casebook_sha256", "scenario_sha256", "expectations_sha256"):
        if type(data[field]) is not str or not re.fullmatch(r"[a-f0-9]{64}", data[field]):
            raise ValueError(f"Invalid {field}")
    scenario = validate_scenario(data["scenario"])
    if scenario["id"] != f"synthetic-ed-reconciliation/v2/{data['case_id']}":
        raise ValueError("Case identifier does not match scenario")
    if type(data["expectations"]) is not dict:
        raise ValueError("Expected an independent expectations object")
    for field in ("scenario", "expectations"):
        if scenario_digest(data[field]) != data[f"{field}_sha256"]:
            raise ValueError(f"Case {field} content does not match its bound digest")
    # A single case cannot authenticate the complete casebook. Its loader
    # checks that inventory; this boundary preserves the supplied book digest.
    return data


def run_case(
    case: dict,
    *,
    controller: Callable | None = None,
    server_factory: Callable = create_server,
    journal_path: Path | None = None,
) -> dict:
    """Run once in a fresh native world, retaining failed/partial execution.

    Invalid source/binding or fixture construction raises before execution.
    Once the initial world exists, server/journal setup and controller errors
    become explicit evidence with the original exception type/message. No
    retry, answer-driven controller input, or historical artifact mutation is
    performed. The optional durable journal must be a new file.
    """
    data = _validated_case(case)
    selected_controller = execute_reference if controller is None else controller
    if not callable(selected_controller) or not callable(server_factory):
        raise ValueError("Controller and server factory must be callable")
    world = build_world(data["scenario"])
    before = snapshot_world(world)
    recorder = None
    completion: dict = {"status": "completed"}
    try:
        recorder = ReconciliationRecorder(server_factory(world), world, journal_path=journal_path)
        selected_controller(recorder, target=deepcopy(data["scenario"]["target"]))
    except (Exception, KeyboardInterrupt) as exc:
        completion = {
            "status": "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
    finally:
        if recorder is not None:
            recorder.close()
    return {
        "schema_version": "healthcraft-reconciliation-execution/v2",
        "execution_kind": "in_process_mcp_handlers",
        "case_binding": {field: data[field] for field in _BINDING_FIELDS},
        "scenario_sha256": data["scenario_sha256"],
        "before": before,
        "after": snapshot_world(world),
        "calls": recorder.calls if recorder is not None else [],
        "audit": _json_snapshot([asdict(entry) for entry in world.audit_log]),
        "completion": completion,
    }
