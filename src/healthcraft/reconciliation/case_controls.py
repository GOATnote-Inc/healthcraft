"""Explicit engineering controls for the exposed v2 development casebook.

These are constructed failure demonstrations, never model attempts or clinical
labels. Tool parameters change before native dispatch. Only incomplete_capture
deliberately omits recorded evidence; that transformation retains the original.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from healthcraft.mcp.server import create_server
from healthcraft.mcp.tools.read_tools import get_encounter_details
from healthcraft.reconciliation.casebook import CONTROLS
from healthcraft.reconciliation.execution import execute_reference
from healthcraft.reconciliation.execution_v2 import run_case


class _ControlledCalls:
    def __init__(self, recorder, control: str):
        self.recorder = recorder
        self.control = control
        self.writes = 0
        self.write_target = None

    def call(self, name: str, params: dict) -> dict:
        params = deepcopy(params)
        if name == "updateEncounter" and "notes" in params:
            self.writes += 1
            note = json.loads(params["notes"])
            if self.control == "wrong_exclusion":
                prior = next(
                    (row for row in note["scope_exclusions"] if row["reason"] == "other_encounter"),
                    None,
                )
                if prior is None:
                    raise ValueError(
                        "wrong_exclusion requires a prior source from the same patient"
                    )
                prior["reason"] = "other_patient"
            elif self.control == "wrong_target":
                other = next(
                    (row for row in note["scope_exclusions"] if row["reason"] == "other_patient"),
                    None,
                )
                if other is None:
                    raise ValueError(
                        "wrong_target requires an encounter belonging to another patient"
                    )
                self.write_target = other["encounter_id"]
                params["encounter_id"] = self.write_target
            elif self.control == "duplicate_notes":
                params["idempotency_key"] = f"development-duplicate-note-{self.writes}"
            elif self.control == "incorrect_content_readback":
                unknown = next(
                    (
                        row
                        for row in note["observations"]
                        if "status" in row["source"] and row["source"]["status"] is None
                    ),
                    None,
                )
                if unknown is None or not note["unresolved_conflicts"]:
                    raise ValueError(
                        "incorrect_content_readback requires unknown status and conflict"
                    )
                unknown["source"]["status"] = "administered"
                note["unresolved_conflicts"][0]["source_ids"].pop()
            params["notes"] = json.dumps(note, sort_keys=True, ensure_ascii=False, allow_nan=False)
        elif name == "getEncounterDetails" and self.writes and self.write_target:
            params["encounter_id"] = self.write_target
        response = self.recorder.call(name, params)
        if self.control == "interrupted_after_write" and self.writes and name == "updateEncounter":
            raise KeyboardInterrupt(
                "Development control: interrupted after the first persisted write"
            )
        return response


def _acknowledgement_only_server(world):
    server = create_server(world)

    def acknowledge_without_mutation(current_world, params):
        # A deliberately defective test handler under real validation/audit
        # middleware. Return the actual unchanged encounter, never a fake note.
        return get_encounter_details(current_world, {"encounter_id": params["encounter_id"]})

    server._handlers["update_encounter"] = acknowledge_without_mutation
    return server


def run_control(
    case: dict,
    *,
    control: str | None = None,
    journal_path: Path | None = None,
) -> dict:
    """Run one explicit development control without accessing expectation rows."""
    selected = case.get("designated_control") if control is None else control
    if type(selected) is not str or selected not in CONTROLS:
        raise ValueError("Unknown development control")

    def controller(recorder, *, target):
        execute_reference(_ControlledCalls(recorder, selected), target=target)

    evidence = run_case(
        case,
        controller=controller,
        journal_path=journal_path,
        server_factory=_acknowledgement_only_server
        if selected == "ack_without_storage"
        else create_server,
    )
    original, transformation = None, None
    if selected == "incomplete_capture" and (
        evidence["completion"]["status"] != "completed" or not evidence["calls"]
    ):
        # Preserve the actual partial attempt and its original failure. An
        # intended demonstration must never discard an unexpected outcome.
        transformation = {"kind": "not_applied", "reason": "original_capture_not_complete"}
    elif selected == "incomplete_capture":
        original = deepcopy(evidence)
        evidence["after"] = None
        last = evidence["calls"][-1]
        last.pop("response", None)
        last.pop("audit_end", None)
        evidence["audit"] = evidence["audit"][: last["audit_start"]]
        evidence["completion"] = {
            "status": "interrupted",
            "error": {
                "type": "DeliberateCaptureOmission",
                "message": (
                    "Development transformation withheld final snapshot and last tool outcome"
                ),
            },
        }
        transformation = {
            "kind": "deliberate_capture_omission",
            "source": "original_evidence",
            "withheld_call_id": last["id"],
            "withheld": ["final_snapshot", "last_call_response", "last_call_audit_outcome"],
            "actual_execution_interrupted": False,
        }
    return {
        "schema_version": "healthcraft-reconciliation-control-capture/v2",
        "control": selected,
        "model_calls": 0,
        "evidence": evidence,
        "original_evidence": original,
        "capture_transformation": transformation,
    }
