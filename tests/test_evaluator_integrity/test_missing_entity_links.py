"""Missing-entity-link error path tests.

When a mutating tool is called with an ID that does not exist in world state,
it must return a documented error (not crash, not succeed silently). Without
this, the agent cannot recover and the audit log records a fake "ok" that the
evaluator credits as a successful tool call.

Coverage:

  * createClinicalOrder on a missing encounter -> error code `encounter_not_found`
  * applyProtocol on a missing encounter        -> error code `encounter_not_found`
  * updateEncounter on a missing encounter      -> error code `encounter_not_found`
  * updatePatientRecord on a missing patient    -> error code `patient_not_found`
  * updateTaskStatus on a missing task          -> error code `task_not_found`
  * Every task's `setting.active_encounters`    -> resolves after seed + injection

The active_encounters check is the V8 lesson: a task that names ENC-XYZ in
its setting but the world seeder never produces ENC-XYZ will silently fail
on every run. The seeder + injector is the contract; this test enforces it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from healthcraft.mcp.server import create_server
from healthcraft.tasks.inject import inject_task_patient
from healthcraft.tasks.loader import load_tasks
from healthcraft.world.seed import WorldSeeder
from healthcraft.world.state import WorldState

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_DIR = REPO_ROOT / "configs" / "tasks"
WORLD_CONFIG = REPO_ROOT / "configs" / "world" / "mercy_point_v1.yaml"


def _empty_world() -> WorldState:
    """Empty world state (no entities). Useful for negative-path tests."""
    return WorldState(start_time=datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc))


# ---------------------------------------------------------------------------
# Negative-path tests: missing entity returns a documented error
# ---------------------------------------------------------------------------


def test_create_clinical_order_missing_encounter() -> None:
    """createClinicalOrder must surface encounter_not_found, not silently 'ok'."""
    server = create_server(_empty_world())
    result = server.call_tool(
        "createClinicalOrder",
        {
            "encounter_id": "ENC-DEADBEEF",
            "order_type": "lab",
            "details": {"test": "CBC"},
        },
    )
    assert result["status"] == "error", f"expected error, got {result}"
    assert result["code"] == "encounter_not_found", (
        f"expected encounter_not_found, got {result['code']!r}"
    )


def test_apply_protocol_missing_encounter() -> None:
    """applyProtocol must surface encounter_not_found before searching protocols."""
    server = create_server(_empty_world())
    result = server.call_tool(
        "applyProtocol",
        {"encounter_id": "ENC-DEADBEEF", "protocol_name": "sepsis_bundle"},
    )
    assert result["status"] == "error"
    assert result["code"] == "encounter_not_found"


def test_update_encounter_missing_encounter() -> None:
    """updateEncounter must surface encounter_not_found."""
    server = create_server(_empty_world())
    result = server.call_tool(
        "updateEncounter",
        {"encounter_id": "ENC-DEADBEEF", "notes": "test"},
    )
    assert result["status"] == "error"
    assert result["code"] == "encounter_not_found"


def test_update_patient_record_missing_patient() -> None:
    """updatePatientRecord must surface patient_not_found."""
    server = create_server(_empty_world())
    result = server.call_tool(
        "updatePatientRecord",
        {"patient_id": "PAT-DEADBEEF", "allergies": ["sulfa"]},
    )
    assert result["status"] == "error"
    assert result["code"] == "patient_not_found"


def test_update_task_status_missing_task() -> None:
    """updateTaskStatus must surface task_not_found."""
    server = create_server(_empty_world())
    result = server.call_tool(
        "updateTaskStatus",
        {"task_id": "TSK-DEADBEEF", "status": "completed"},
    )
    assert result["status"] == "error"
    assert result["code"] == "task_not_found"


def test_get_patient_history_missing_patient_returns_error() -> None:
    """Read-only get_patient_history on a missing patient must not crash."""
    server = create_server(_empty_world())
    result = server.call_tool("getPatientHistory", {"patient_id": "PAT-DEADBEEF"})
    # Read-only tools are allowed to return either 'error' or 'ok' with
    # empty data, but must not internal_error.
    assert result.get("code") != "internal_error"


# ---------------------------------------------------------------------------
# Positive-path: failure code does NOT match the success code on real entities
# ---------------------------------------------------------------------------


def test_negative_codes_distinct_from_positive() -> None:
    """encounter_not_found must be distinguishable from success.

    Otherwise the evaluator's `result_summary == 'ok'` check could be tricked
    by a not-found that returns 'ok' status with empty data.
    """
    server = create_server(_empty_world())
    result = server.call_tool(
        "createClinicalOrder",
        {
            "encounter_id": "ENC-DEADBEEF",
            "order_type": "lab",
            "details": {"test": "CBC"},
        },
    )
    assert result["status"] != "ok", (
        "Negative path must NOT return status='ok'. The evaluator's "
        "world_state verification credits any 'ok' audit entry; a silent "
        "success on a missing entity would inflate scores."
    )


# ---------------------------------------------------------------------------
# Task setting integrity: active_encounters resolves after seed + injection
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def seeded_world() -> WorldState:
    """A seeded world (matches what the orchestrator builds at trial start)."""
    return WorldSeeder(seed=42).seed_world(WORLD_CONFIG)


def test_all_task_active_encounters_resolve(seeded_world: WorldState) -> None:
    """Every task's active_encounters/encounter_id must exist post-injection.

    The orchestrator seeds a fresh world per trial, then calls
    inject_task_patient() to inject task-described patients/encounters. After
    injection, every encounter referenced in the task setting must resolve to
    an entity in world state. If not, the agent has no encounter to operate
    on and the world_state criteria will all fail.
    """
    tasks = load_tasks(TASK_DIR)
    failures: list[str] = []

    for task in tasks:
        # Seed fresh per task so injection state from one task doesn't leak.
        world = WorldSeeder(seed=42).seed_world(WORLD_CONFIG)
        if task.patient:
            try:
                inject_task_patient(world, task.id, task.patient, task.initial_state)
            except Exception as e:
                failures.append(f"{task.id}: inject_task_patient raised {e}")
                continue

        active = task.initial_state.get("active_encounters", [])
        if isinstance(active, str):
            active = [active]
        for enc_id in active:
            ent = world.get_entity("encounter", enc_id)
            if ent is None:
                failures.append(
                    f"{task.id}: setting.active_encounters references "
                    f"{enc_id!r} which is absent from world state after seed+injection"
                )

    assert not failures, "active_encounters integrity failures:\n  " + "\n  ".join(failures)
