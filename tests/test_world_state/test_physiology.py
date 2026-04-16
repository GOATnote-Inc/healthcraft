"""Physiology module tests.

Locks the core properties of the vitals trajectory system:

1. Seed determinism -- same (world_seed, patient_id) always produces
   identical trajectories.
2. Clinical realism -- sepsis shows monotonic HR rise and BP drop;
   ACS shows initial hypertension; respiratory failure shows SpO2 decline;
   stable_improving normalizes.
3. Interpolation -- boundary clamping, midpoint accuracy, edge cases.
4. Trajectory validation -- at least 2 waypoints, sorted offsets.
5. Registry -- all 4 types accessible via create_trajectory.
"""

from __future__ import annotations

import pytest

from healthcraft.world.physiology import (
    VitalsSnapshot,
    VitalsTrajectory,
    acs_trajectory,
    create_trajectory,
    interpolate,
    respiratory_failure_trajectory,
    sepsis_trajectory,
    stable_improving_trajectory,
)

SEED = 42
PATIENT = "PAT-TEST001"


# ---------------------------------------------------------------------------
# Seed determinism
# ---------------------------------------------------------------------------


class TestSeedDeterminism:
    """Same inputs always produce identical outputs."""

    def test_sepsis_deterministic(self) -> None:
        a = sepsis_trajectory(SEED, PATIENT)
        b = sepsis_trajectory(SEED, PATIENT)
        assert a == b

    def test_acs_deterministic(self) -> None:
        a = acs_trajectory(SEED, PATIENT)
        b = acs_trajectory(SEED, PATIENT)
        assert a == b

    def test_respiratory_deterministic(self) -> None:
        a = respiratory_failure_trajectory(SEED, PATIENT)
        b = respiratory_failure_trajectory(SEED, PATIENT)
        assert a == b

    def test_stable_deterministic(self) -> None:
        a = stable_improving_trajectory(SEED, PATIENT)
        b = stable_improving_trajectory(SEED, PATIENT)
        assert a == b

    def test_different_seeds_differ(self) -> None:
        a = sepsis_trajectory(42, PATIENT)
        b = sepsis_trajectory(99, PATIENT)
        assert a != b

    def test_different_patients_differ(self) -> None:
        a = sepsis_trajectory(SEED, "PAT-A")
        b = sepsis_trajectory(SEED, "PAT-B")
        assert a != b


# ---------------------------------------------------------------------------
# Clinical realism (trajectory shape)
# ---------------------------------------------------------------------------


class TestClinicalRealism:
    """Trajectory generators produce clinically plausible vitals arcs."""

    def test_sepsis_hr_rises(self) -> None:
        traj = sepsis_trajectory(SEED, PATIENT)
        first = traj.timeline[0]
        last = traj.timeline[-1]
        assert last.heart_rate > first.heart_rate

    def test_sepsis_bp_drops(self) -> None:
        traj = sepsis_trajectory(SEED, PATIENT)
        first = traj.timeline[0]
        last = traj.timeline[-1]
        assert last.systolic_bp < first.systolic_bp

    def test_sepsis_febrile(self) -> None:
        traj = sepsis_trajectory(SEED, PATIENT)
        assert traj.timeline[0].temperature > 38.0

    def test_acs_initial_hypertension(self) -> None:
        traj = acs_trajectory(SEED, PATIENT)
        assert traj.timeline[0].systolic_bp > 140

    def test_acs_bp_trends_down(self) -> None:
        traj = acs_trajectory(SEED, PATIENT)
        first = traj.timeline[0]
        last = traj.timeline[-1]
        assert last.systolic_bp < first.systolic_bp

    def test_respiratory_spo2_drops(self) -> None:
        traj = respiratory_failure_trajectory(SEED, PATIENT)
        first = traj.timeline[0]
        last = traj.timeline[-1]
        assert last.spo2 < first.spo2

    def test_respiratory_rr_rises(self) -> None:
        traj = respiratory_failure_trajectory(SEED, PATIENT)
        first = traj.timeline[0]
        last = traj.timeline[-1]
        assert last.respiratory_rate > first.respiratory_rate

    def test_stable_hr_normalizes(self) -> None:
        traj = stable_improving_trajectory(SEED, PATIENT)
        first = traj.timeline[0]
        last = traj.timeline[-1]
        assert last.heart_rate < first.heart_rate

    def test_stable_spo2_improves(self) -> None:
        traj = stable_improving_trajectory(SEED, PATIENT)
        first = traj.timeline[0]
        last = traj.timeline[-1]
        assert last.spo2 >= first.spo2


# ---------------------------------------------------------------------------
# Interpolation
# ---------------------------------------------------------------------------


class TestInterpolation:
    """interpolate() returns correct vitals at arbitrary time offsets."""

    def test_at_first_waypoint(self) -> None:
        traj = sepsis_trajectory(SEED, PATIENT)
        snap = interpolate(traj, 0)
        assert snap.heart_rate == traj.timeline[0].heart_rate

    def test_at_last_waypoint(self) -> None:
        traj = sepsis_trajectory(SEED, PATIENT)
        last_offset = traj.timeline[-1].offset_minutes
        snap = interpolate(traj, last_offset)
        assert snap.heart_rate == traj.timeline[-1].heart_rate

    def test_before_first_clamps(self) -> None:
        traj = sepsis_trajectory(SEED, PATIENT)
        snap = interpolate(traj, -10)
        assert snap.heart_rate == traj.timeline[0].heart_rate
        assert snap.offset_minutes == -10

    def test_after_last_clamps(self) -> None:
        traj = sepsis_trajectory(SEED, PATIENT)
        far_future = traj.timeline[-1].offset_minutes + 100
        snap = interpolate(traj, far_future)
        assert snap.heart_rate == traj.timeline[-1].heart_rate

    def test_midpoint_interpolates(self) -> None:
        traj = sepsis_trajectory(SEED, PATIENT)
        wp0 = traj.timeline[0]
        wp1 = traj.timeline[1]
        mid = (wp0.offset_minutes + wp1.offset_minutes) / 2
        snap = interpolate(traj, mid)
        # Heart rate should be between the two waypoints
        lo = min(wp0.heart_rate, wp1.heart_rate)
        hi = max(wp0.heart_rate, wp1.heart_rate)
        assert lo <= snap.heart_rate <= hi

    def test_returns_vitals_snapshot(self) -> None:
        traj = sepsis_trajectory(SEED, PATIENT)
        snap = interpolate(traj, 10)
        assert isinstance(snap, VitalsSnapshot)


# ---------------------------------------------------------------------------
# Trajectory validation
# ---------------------------------------------------------------------------


class TestTrajectoryValidation:
    """VitalsTrajectory enforces invariants."""

    def test_requires_at_least_2_waypoints(self) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            VitalsTrajectory(
                patient_id="X",
                trajectory_type="test",
                timeline=(VitalsSnapshot(0, 80, 120, 80, 16, 98, 37.0, 15),),
            )

    def test_rejects_unsorted_timeline(self) -> None:
        with pytest.raises(ValueError, match="sorted"):
            VitalsTrajectory(
                patient_id="X",
                trajectory_type="test",
                timeline=(
                    VitalsSnapshot(10, 80, 120, 80, 16, 98, 37.0, 15),
                    VitalsSnapshot(5, 90, 110, 70, 18, 96, 37.2, 15),
                ),
            )

    def test_all_generators_produce_3_waypoints(self) -> None:
        for gen in (
            sepsis_trajectory,
            acs_trajectory,
            respiratory_failure_trajectory,
            stable_improving_trajectory,
        ):
            traj = gen(SEED, PATIENT)
            assert len(traj.timeline) == 3


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    """create_trajectory dispatches to the correct generator."""

    @pytest.mark.parametrize(
        "ttype",
        ["sepsis", "acs", "respiratory_failure", "stable_improving"],
    )
    def test_known_types(self, ttype: str) -> None:
        traj = create_trajectory(ttype, SEED, PATIENT)
        assert traj.trajectory_type == ttype

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown trajectory type"):
            create_trajectory("unknown", SEED, PATIENT)
