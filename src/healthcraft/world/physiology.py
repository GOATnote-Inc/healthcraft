"""Physiology module -- seeded vital-sign trajectories for dynamic patient state.

Provides pure, deterministic generators for clinical trajectories (sepsis, ACS,
respiratory failure, stable/improving). Each trajectory is a frozen dataclass
holding a timeline of ``VitalsSnapshot`` waypoints. ``interpolate()`` returns
the vitals at any simulation time by linear interpolation between waypoints.

All generators are seeded from ``(world_seed, patient_id)`` so results are
fully reproducible.

This module is **default off**. It is only wired into WorldState when
``dynamic_state_enabled=True`` (Phase 3 flag, controlled by ``--dynamic-state``
CLI flag or ``HC_DYNAMIC_STATE`` env var).
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class VitalsSnapshot:
    """A single interpolated vital-signs reading at a point in time.

    ``offset_minutes`` is relative to trajectory start (t=0 = encounter arrival).
    """

    offset_minutes: float
    heart_rate: int
    systolic_bp: int
    diastolic_bp: int
    respiratory_rate: int
    spo2: int
    temperature: float
    gcs: int


@dataclass(frozen=True)
class VitalsTrajectory:
    """Immutable timeline of vital-sign waypoints for one patient.

    ``timeline`` is a tuple of ``VitalsSnapshot`` sorted by ``offset_minutes``.
    Interpolation between waypoints yields vitals at any simulation time.
    """

    patient_id: str
    trajectory_type: str  # sepsis, acs, respiratory_failure, stable_improving
    timeline: tuple[VitalsSnapshot, ...]

    def __post_init__(self) -> None:
        if len(self.timeline) < 2:
            raise ValueError("VitalsTrajectory requires at least 2 waypoints")
        offsets = [wp.offset_minutes for wp in self.timeline]
        if offsets != sorted(offsets):
            raise ValueError("Timeline waypoints must be sorted by offset_minutes")


def _patient_rng(world_seed: int, patient_id: str) -> random.Random:
    """Create a deterministic RNG from (world_seed, patient_id)."""
    combined = f"{world_seed}:{patient_id}"
    seed_int = int(hashlib.sha256(combined.encode()).hexdigest()[:16], 16)
    return random.Random(seed_int)


def _jitter(rng: random.Random, base: int | float, pct: float = 0.05) -> int:
    """Add small seeded jitter to a base value."""
    delta = base * pct
    return round(base + rng.uniform(-delta, delta))


def _jitterf(rng: random.Random, base: float, pct: float = 0.05) -> float:
    """Add small seeded jitter to a float base value."""
    delta = base * pct
    return round(base + rng.uniform(-delta, delta), 1)


# ---------------------------------------------------------------------------
# Trajectory generators
# ---------------------------------------------------------------------------


def sepsis_trajectory(world_seed: int, patient_id: str) -> VitalsTrajectory:
    """Generate a sepsis deterioration trajectory.

    Pattern: initial presentation (febrile, tachycardic) -> progressive
    deterioration over 60-120 minutes if untreated. HR rises, BP drops,
    SpO2 drifts down, temperature spikes, GCS may decline.

    The trajectory models untreated sepsis. Treatment branches (fluid
    resuscitation, antibiotics) would flatten or reverse the curve -- those
    are not modeled here (future: treatment-response variants).
    """
    rng = _patient_rng(world_seed, patient_id)

    # Baseline (presentation)
    hr0 = _jitter(rng, 105, 0.10)
    sbp0 = _jitter(rng, 100, 0.08)
    dbp0 = _jitter(rng, 62, 0.08)
    rr0 = _jitter(rng, 22, 0.10)
    spo2_0 = _jitter(rng, 95, 0.02)
    temp0 = _jitterf(rng, 38.8, 0.03)
    gcs0 = 15

    # Duration of full deterioration arc
    duration = rng.randint(60, 120)
    mid = duration // 2

    timeline = (
        VitalsSnapshot(
            offset_minutes=0,
            heart_rate=hr0,
            systolic_bp=sbp0,
            diastolic_bp=dbp0,
            respiratory_rate=rr0,
            spo2=spo2_0,
            temperature=temp0,
            gcs=gcs0,
        ),
        VitalsSnapshot(
            offset_minutes=mid,
            heart_rate=_jitter(rng, 118, 0.08),
            systolic_bp=_jitter(rng, 88, 0.08),
            diastolic_bp=_jitter(rng, 52, 0.08),
            respiratory_rate=_jitter(rng, 26, 0.08),
            spo2=_jitter(rng, 93, 0.02),
            temperature=_jitterf(rng, 39.2, 0.02),
            gcs=15,
        ),
        VitalsSnapshot(
            offset_minutes=duration,
            heart_rate=_jitter(rng, 130, 0.08),
            systolic_bp=_jitter(rng, 76, 0.10),
            diastolic_bp=_jitter(rng, 42, 0.10),
            respiratory_rate=_jitter(rng, 30, 0.08),
            spo2=_jitter(rng, 90, 0.03),
            temperature=_jitterf(rng, 39.6, 0.02),
            gcs=rng.choice([14, 14, 13]),
        ),
    )

    return VitalsTrajectory(
        patient_id=patient_id,
        trajectory_type="sepsis",
        timeline=timeline,
    )


def acs_trajectory(world_seed: int, patient_id: str) -> VitalsTrajectory:
    """Generate an acute coronary syndrome trajectory.

    Pattern: chest pain presentation with moderate tachycardia and
    hypertension. Without treatment, HR gradually rises, BP may drop
    if progressing toward cardiogenic shock. SpO2 dips modestly.
    With treatment (nitroglycerin, aspirin, heparin), HR and BP stabilize.
    This models the untreated arc.
    """
    rng = _patient_rng(world_seed, patient_id)

    hr0 = _jitter(rng, 88, 0.10)
    sbp0 = _jitter(rng, 155, 0.08)
    dbp0 = _jitter(rng, 92, 0.08)
    rr0 = _jitter(rng, 20, 0.10)
    spo2_0 = _jitter(rng, 96, 0.02)
    temp0 = _jitterf(rng, 37.0, 0.01)
    gcs0 = 15

    duration = rng.randint(45, 90)
    mid = duration // 2

    timeline = (
        VitalsSnapshot(
            offset_minutes=0,
            heart_rate=hr0,
            systolic_bp=sbp0,
            diastolic_bp=dbp0,
            respiratory_rate=rr0,
            spo2=spo2_0,
            temperature=temp0,
            gcs=gcs0,
        ),
        VitalsSnapshot(
            offset_minutes=mid,
            heart_rate=_jitter(rng, 98, 0.08),
            systolic_bp=_jitter(rng, 140, 0.08),
            diastolic_bp=_jitter(rng, 85, 0.08),
            respiratory_rate=_jitter(rng, 22, 0.08),
            spo2=_jitter(rng, 95, 0.02),
            temperature=temp0,
            gcs=15,
        ),
        VitalsSnapshot(
            offset_minutes=duration,
            heart_rate=_jitter(rng, 108, 0.08),
            systolic_bp=_jitter(rng, 118, 0.10),
            diastolic_bp=_jitter(rng, 72, 0.10),
            respiratory_rate=_jitter(rng, 24, 0.08),
            spo2=_jitter(rng, 93, 0.03),
            temperature=temp0,
            gcs=15,
        ),
    )

    return VitalsTrajectory(
        patient_id=patient_id,
        trajectory_type="acs",
        timeline=timeline,
    )


def respiratory_failure_trajectory(
    world_seed: int,
    patient_id: str,
) -> VitalsTrajectory:
    """Generate a respiratory failure trajectory.

    Pattern: initial hypoxia and tachypnea, progressive desaturation.
    HR rises compensatorily. BP relatively stable until late. GCS may
    decline with severe hypoxia.
    """
    rng = _patient_rng(world_seed, patient_id)

    hr0 = _jitter(rng, 100, 0.10)
    sbp0 = _jitter(rng, 130, 0.08)
    dbp0 = _jitter(rng, 78, 0.08)
    rr0 = _jitter(rng, 28, 0.10)
    spo2_0 = _jitter(rng, 90, 0.03)
    temp0 = _jitterf(rng, 37.2, 0.02)
    gcs0 = 15

    duration = rng.randint(30, 75)
    mid = duration // 2

    timeline = (
        VitalsSnapshot(
            offset_minutes=0,
            heart_rate=hr0,
            systolic_bp=sbp0,
            diastolic_bp=dbp0,
            respiratory_rate=rr0,
            spo2=spo2_0,
            temperature=temp0,
            gcs=gcs0,
        ),
        VitalsSnapshot(
            offset_minutes=mid,
            heart_rate=_jitter(rng, 115, 0.08),
            systolic_bp=_jitter(rng, 128, 0.06),
            diastolic_bp=_jitter(rng, 76, 0.06),
            respiratory_rate=_jitter(rng, 34, 0.08),
            spo2=_jitter(rng, 85, 0.03),
            temperature=temp0,
            gcs=15,
        ),
        VitalsSnapshot(
            offset_minutes=duration,
            heart_rate=_jitter(rng, 128, 0.08),
            systolic_bp=_jitter(rng, 120, 0.08),
            diastolic_bp=_jitter(rng, 70, 0.08),
            respiratory_rate=_jitter(rng, 38, 0.08),
            spo2=_jitter(rng, 78, 0.05),
            temperature=temp0,
            gcs=rng.choice([14, 13, 13]),
        ),
    )

    return VitalsTrajectory(
        patient_id=patient_id,
        trajectory_type="respiratory_failure",
        timeline=timeline,
    )


def stable_improving_trajectory(
    world_seed: int,
    patient_id: str,
) -> VitalsTrajectory:
    """Generate a stable/improving trajectory.

    Pattern: mildly abnormal presentation that normalizes over time.
    Used for patients whose condition is expected to improve with
    standard treatment or observation.
    """
    rng = _patient_rng(world_seed, patient_id)

    hr0 = _jitter(rng, 92, 0.08)
    sbp0 = _jitter(rng, 138, 0.06)
    dbp0 = _jitter(rng, 84, 0.06)
    rr0 = _jitter(rng, 20, 0.08)
    spo2_0 = _jitter(rng, 96, 0.02)
    temp0 = _jitterf(rng, 37.6, 0.02)
    gcs0 = 15

    duration = rng.randint(60, 120)
    mid = duration // 2

    timeline = (
        VitalsSnapshot(
            offset_minutes=0,
            heart_rate=hr0,
            systolic_bp=sbp0,
            diastolic_bp=dbp0,
            respiratory_rate=rr0,
            spo2=spo2_0,
            temperature=temp0,
            gcs=gcs0,
        ),
        VitalsSnapshot(
            offset_minutes=mid,
            heart_rate=_jitter(rng, 82, 0.06),
            systolic_bp=_jitter(rng, 128, 0.06),
            diastolic_bp=_jitter(rng, 78, 0.06),
            respiratory_rate=_jitter(rng, 18, 0.06),
            spo2=_jitter(rng, 97, 0.01),
            temperature=_jitterf(rng, 37.2, 0.02),
            gcs=15,
        ),
        VitalsSnapshot(
            offset_minutes=duration,
            heart_rate=_jitter(rng, 76, 0.06),
            systolic_bp=_jitter(rng, 122, 0.05),
            diastolic_bp=_jitter(rng, 74, 0.05),
            respiratory_rate=_jitter(rng, 16, 0.06),
            spo2=_jitter(rng, 98, 0.01),
            temperature=_jitterf(rng, 37.0, 0.01),
            gcs=15,
        ),
    )

    return VitalsTrajectory(
        patient_id=patient_id,
        trajectory_type="stable_improving",
        timeline=timeline,
    )


# ---------------------------------------------------------------------------
# Trajectory type registry
# ---------------------------------------------------------------------------

TRAJECTORY_GENERATORS = {
    "sepsis": sepsis_trajectory,
    "acs": acs_trajectory,
    "respiratory_failure": respiratory_failure_trajectory,
    "stable_improving": stable_improving_trajectory,
}


def create_trajectory(
    trajectory_type: str,
    world_seed: int,
    patient_id: str,
) -> VitalsTrajectory:
    """Create a trajectory by type name.

    Args:
        trajectory_type: One of "sepsis", "acs", "respiratory_failure",
            "stable_improving".
        world_seed: Deterministic world seed.
        patient_id: Patient identifier (used as part of RNG seed).

    Returns:
        A frozen VitalsTrajectory.

    Raises:
        ValueError: If trajectory_type is unknown.
    """
    gen = TRAJECTORY_GENERATORS.get(trajectory_type)
    if gen is None:
        valid = ", ".join(sorted(TRAJECTORY_GENERATORS))
        raise ValueError(f"Unknown trajectory type: {trajectory_type!r}. Valid types: {valid}")
    return gen(world_seed, patient_id)


# ---------------------------------------------------------------------------
# Interpolation
# ---------------------------------------------------------------------------


def _lerp(a: int | float, b: int | float, t: float) -> int | float:
    """Linear interpolation between a and b at fraction t in [0, 1]."""
    result = a + (b - a) * t
    if isinstance(a, int) and isinstance(b, int):
        return round(result)
    return round(result, 1)


def interpolate(trajectory: VitalsTrajectory, offset_minutes: float) -> VitalsSnapshot:
    """Interpolate vitals at a given time offset.

    If ``offset_minutes`` is before the first waypoint, returns the first
    waypoint's values. If after the last, returns the last waypoint's values
    (no extrapolation beyond the trajectory).

    Args:
        trajectory: The vitals trajectory to interpolate.
        offset_minutes: Minutes since trajectory start (t=0).

    Returns:
        An interpolated VitalsSnapshot.
    """
    timeline = trajectory.timeline

    # Clamp to trajectory bounds
    if offset_minutes <= timeline[0].offset_minutes:
        return VitalsSnapshot(
            offset_minutes=offset_minutes,
            heart_rate=timeline[0].heart_rate,
            systolic_bp=timeline[0].systolic_bp,
            diastolic_bp=timeline[0].diastolic_bp,
            respiratory_rate=timeline[0].respiratory_rate,
            spo2=timeline[0].spo2,
            temperature=timeline[0].temperature,
            gcs=timeline[0].gcs,
        )

    if offset_minutes >= timeline[-1].offset_minutes:
        return VitalsSnapshot(
            offset_minutes=offset_minutes,
            heart_rate=timeline[-1].heart_rate,
            systolic_bp=timeline[-1].systolic_bp,
            diastolic_bp=timeline[-1].diastolic_bp,
            respiratory_rate=timeline[-1].respiratory_rate,
            spo2=timeline[-1].spo2,
            temperature=timeline[-1].temperature,
            gcs=timeline[-1].gcs,
        )

    # Find bounding waypoints
    for i in range(len(timeline) - 1):
        wp_a = timeline[i]
        wp_b = timeline[i + 1]
        if wp_a.offset_minutes <= offset_minutes <= wp_b.offset_minutes:
            span = wp_b.offset_minutes - wp_a.offset_minutes
            t = (offset_minutes - wp_a.offset_minutes) / span if span > 0 else 0.0
            return VitalsSnapshot(
                offset_minutes=offset_minutes,
                heart_rate=_lerp(wp_a.heart_rate, wp_b.heart_rate, t),
                systolic_bp=_lerp(wp_a.systolic_bp, wp_b.systolic_bp, t),
                diastolic_bp=_lerp(wp_a.diastolic_bp, wp_b.diastolic_bp, t),
                respiratory_rate=_lerp(wp_a.respiratory_rate, wp_b.respiratory_rate, t),
                spo2=_lerp(wp_a.spo2, wp_b.spo2, t),
                temperature=_lerp(wp_a.temperature, wp_b.temperature, t),
                gcs=_lerp(wp_a.gcs, wp_b.gcs, t),
            )

    # Should not reach here if timeline is properly sorted
    return VitalsSnapshot(
        offset_minutes=offset_minutes,
        heart_rate=timeline[-1].heart_rate,
        systolic_bp=timeline[-1].systolic_bp,
        diastolic_bp=timeline[-1].diastolic_bp,
        respiratory_rate=timeline[-1].respiratory_rate,
        spo2=timeline[-1].spo2,
        temperature=timeline[-1].temperature,
        gcs=timeline[-1].gcs,
    )
