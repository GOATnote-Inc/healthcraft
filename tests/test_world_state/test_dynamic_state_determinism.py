"""Dynamic state determinism tests.

Locks the property that same seed produces identical interpolated vitals
at every audit timestamp. Also verifies all 195 V8 task YAMLs load
without requiring the ``clinical_trajectory`` field (additive optional).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from healthcraft.tasks.loader import load_tasks
from healthcraft.world.physiology import (
    create_trajectory,
    interpolate,
    sepsis_trajectory,
)
from healthcraft.world.state import WorldState

SEED = 42
PATIENT = "PAT-DETERM"
START = datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
_TASKS_DIR = Path(__file__).resolve().parents[2] / "configs" / "tasks"


# ---------------------------------------------------------------------------
# Determinism: same seed -> identical vitals at every time step
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Interpolated vitals are fully deterministic from seed."""

    def test_identical_vitals_at_every_step(self) -> None:
        traj_a = sepsis_trajectory(SEED, PATIENT)
        traj_b = sepsis_trajectory(SEED, PATIENT)
        # Sample at 10 time points across the trajectory
        duration = traj_a.timeline[-1].offset_minutes
        for i in range(11):
            t = duration * i / 10
            va = interpolate(traj_a, t)
            vb = interpolate(traj_b, t)
            assert va == vb, f"Mismatch at t={t}"

    def test_world_state_vitals_deterministic(self) -> None:
        """Two independent WorldState instances produce same vitals."""
        for _ in range(2):
            world = WorldState(start_time=START, dynamic_state_enabled=True)
            traj = sepsis_trajectory(SEED, PATIENT)
            world.attach_physiology(PATIENT, traj)
            world.advance_time(30)
            vitals = world.get_current_vitals(PATIENT)
            assert vitals is not None
            # Store first run's values
            if _ == 0:
                first_hr = vitals.heart_rate
                first_spo2 = vitals.spo2
            else:
                assert vitals.heart_rate == first_hr
                assert vitals.spo2 == first_spo2

    @pytest.mark.parametrize(
        "ttype",
        ["sepsis", "acs", "respiratory_failure", "stable_improving"],
    )
    def test_all_trajectory_types_deterministic(self, ttype: str) -> None:
        a = create_trajectory(ttype, SEED, PATIENT)
        b = create_trajectory(ttype, SEED, PATIENT)
        assert a == b


# ---------------------------------------------------------------------------
# Task YAML backward compatibility
# ---------------------------------------------------------------------------


class TestTaskYAMLCompat:
    """All V8 task YAMLs load without the clinical_trajectory field."""

    def test_all_tasks_load(self) -> None:
        if not _TASKS_DIR.exists():
            pytest.skip("Task configs not available")
        tasks = load_tasks(_TASKS_DIR)
        assert len(tasks) >= 195

    def test_no_task_requires_clinical_trajectory(self) -> None:
        """clinical_trajectory is optional -- V8 tasks must not have it."""
        if not _TASKS_DIR.exists():
            pytest.skip("Task configs not available")
        tasks = load_tasks(_TASKS_DIR)
        for task in tasks:
            # initial_state may or may not have clinical_trajectory;
            # the point is that loading succeeds without it
            ct = task.initial_state.get("clinical_trajectory") if task.initial_state else None
            # V8 tasks should not have this field
            assert ct is None, (
                f"Task {task.id} has clinical_trajectory={ct}. V8 tasks should not have this field."
            )
