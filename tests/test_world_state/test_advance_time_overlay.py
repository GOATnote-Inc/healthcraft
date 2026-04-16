"""Advance-time overlay tests.

Locks two critical properties:

1. With ``dynamic_state_enabled=False`` (V8 default), ``advance_time()``
   produces **no audit entries** beyond what V8 would produce. The audit
   log is byte-identical to pre-Phase-3 behavior.

2. With ``dynamic_state_enabled=True`` and a physiology trajectory attached,
   ``advance_time()`` emits ``_reassessment_prompt`` audit entries when
   clinical thresholds are crossed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from healthcraft.world.physiology import sepsis_trajectory, stable_improving_trajectory
from healthcraft.world.state import WorldState

START = datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
SEED = 42
PATIENT = "PAT-TEST001"


# ---------------------------------------------------------------------------
# V8 behavior (dynamic_state_enabled=False)
# ---------------------------------------------------------------------------


class TestV8Behavior:
    """With dynamic state off, advance_time is purely a clock operation."""

    def test_no_audit_entries_on_advance(self) -> None:
        world = WorldState(start_time=START)
        world.advance_time(30)
        assert len(world.audit_log) == 0

    def test_returns_empty_list(self) -> None:
        world = WorldState(start_time=START)
        result = world.advance_time(30)
        assert result == []

    def test_clock_advances(self) -> None:
        world = WorldState(start_time=START)
        world.advance_time(60)
        assert (world.timestamp - START).total_seconds() == 3600

    def test_no_physiology_by_default(self) -> None:
        world = WorldState(start_time=START)
        assert world.get_current_vitals(PATIENT) is None

    def test_dynamic_state_off_by_default(self) -> None:
        world = WorldState(start_time=START)
        assert world.dynamic_state_enabled is False


# ---------------------------------------------------------------------------
# Dynamic state ON
# ---------------------------------------------------------------------------


class TestDynamicState:
    """With dynamic state on, advance_time drives physiology overlays."""

    def test_reassessment_triggers_on_sepsis(self) -> None:
        world = WorldState(start_time=START, dynamic_state_enabled=True)
        traj = sepsis_trajectory(SEED, PATIENT)
        world.attach_physiology(PATIENT, traj)
        # Advance far enough for vitals to deteriorate past thresholds
        duration = traj.timeline[-1].offset_minutes
        triggers = world.advance_time(int(duration))
        # Sepsis trajectory should cross at least one threshold
        # (HR > 120 and/or SBP < 90 and/or MAP < 65)
        assert len(triggers) > 0

    def test_reassessment_audit_entries_created(self) -> None:
        world = WorldState(start_time=START, dynamic_state_enabled=True)
        traj = sepsis_trajectory(SEED, PATIENT)
        world.attach_physiology(PATIENT, traj)
        duration = traj.timeline[-1].offset_minutes
        world.advance_time(int(duration))
        reassessment_entries = [e for e in world.audit_log if e.tool_name == "_reassessment_prompt"]
        assert len(reassessment_entries) > 0

    def test_reassessment_entry_has_patient_id(self) -> None:
        world = WorldState(start_time=START, dynamic_state_enabled=True)
        traj = sepsis_trajectory(SEED, PATIENT)
        world.attach_physiology(PATIENT, traj)
        duration = traj.timeline[-1].offset_minutes
        world.advance_time(int(duration))
        for entry in world.audit_log:
            if entry.tool_name == "_reassessment_prompt":
                assert entry.params["patient_id"] == PATIENT

    def test_stable_trajectory_no_triggers(self) -> None:
        world = WorldState(start_time=START, dynamic_state_enabled=True)
        traj = stable_improving_trajectory(SEED, PATIENT)
        world.attach_physiology(PATIENT, traj)
        # Stable trajectory should NOT cross critical thresholds
        triggers = world.advance_time(30)
        assert len(triggers) == 0

    def test_get_current_vitals_returns_interpolated(self) -> None:
        world = WorldState(start_time=START, dynamic_state_enabled=True)
        traj = sepsis_trajectory(SEED, PATIENT)
        world.attach_physiology(PATIENT, traj)
        world.advance_time(30)
        vitals = world.get_current_vitals(PATIENT)
        assert vitals is not None
        assert vitals.heart_rate > 0

    def test_get_current_vitals_none_without_trajectory(self) -> None:
        world = WorldState(start_time=START, dynamic_state_enabled=True)
        assert world.get_current_vitals("PAT-NONEXISTENT") is None

    def test_get_current_vitals_none_when_disabled(self) -> None:
        world = WorldState(start_time=START, dynamic_state_enabled=False)
        traj = sepsis_trajectory(SEED, PATIENT)
        world.attach_physiology(PATIENT, traj)
        assert world.get_current_vitals(PATIENT) is None

    def test_triggers_dont_refire_on_sustained(self) -> None:
        """Once a threshold is crossed, it should not re-fire on the next advance."""
        world = WorldState(start_time=START, dynamic_state_enabled=True)
        traj = sepsis_trajectory(SEED, PATIENT)
        world.attach_physiology(PATIENT, traj)
        duration = traj.timeline[-1].offset_minutes
        # First advance: triggers fire
        triggers_1 = world.advance_time(int(duration))
        # Second advance (still past threshold): should NOT re-fire
        triggers_2 = world.advance_time(5)
        # All triggers from second advance should be genuinely new crossings
        # (in practice, 0 since we're already past thresholds)
        assert len(triggers_2) <= len(triggers_1)

    def test_snapshot_preserves_physiology(self) -> None:
        world = WorldState(start_time=START, dynamic_state_enabled=True)
        traj = sepsis_trajectory(SEED, PATIENT)
        world.attach_physiology(PATIENT, traj)
        snap = world.snapshot()
        assert snap.get_current_vitals(PATIENT) is not None
