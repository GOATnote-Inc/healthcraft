"""Reassessment trigger detection for dynamic patient state.

Computes reassessment triggers when vitals cross clinical thresholds during
``advance_time()``. Triggers are audit-only: they emit ``_reassessment_prompt``
audit entries but do **not** change criterion satisfaction. This gives the agent
a signal that the patient's condition has changed without altering the scoring
contract.

Thresholds are deliberately conservative -- they fire only for clinically
significant changes (e.g., MAP < 65, SpO2 < 90, HR > 120) rather than
minor fluctuations.

This module is only active when ``dynamic_state_enabled=True``.
"""

from __future__ import annotations

from dataclasses import dataclass

from healthcraft.world.physiology import VitalsSnapshot


@dataclass(frozen=True)
class ReassessmentTrigger:
    """A detected reassessment event."""

    patient_id: str
    trigger_type: str  # vital_sign, lab_change
    parameter: str  # e.g., "spo2", "systolic_bp"
    value: int | float
    threshold: int | float
    direction: str  # "below", "above"
    message: str


# ---------------------------------------------------------------------------
# Threshold definitions
# ---------------------------------------------------------------------------

# (parameter, direction, threshold, message_template)
_VITAL_THRESHOLDS: list[tuple[str, str, int | float, str]] = [
    ("spo2", "below", 90, "SpO2 dropped below 90% ({value}%)"),
    ("spo2", "below", 85, "CRITICAL: SpO2 dropped below 85% ({value}%)"),
    ("systolic_bp", "below", 90, "Systolic BP dropped below 90 mmHg ({value} mmHg)"),
    ("systolic_bp", "below", 70, "CRITICAL: Systolic BP dropped below 70 mmHg ({value} mmHg)"),
    ("heart_rate", "above", 120, "Heart rate exceeded 120 bpm ({value} bpm)"),
    ("heart_rate", "above", 140, "CRITICAL: Heart rate exceeded 140 bpm ({value} bpm)"),
    ("heart_rate", "below", 50, "Heart rate dropped below 50 bpm ({value} bpm)"),
    ("respiratory_rate", "above", 30, "Respiratory rate exceeded 30/min ({value}/min)"),
    ("respiratory_rate", "below", 8, "Respiratory rate dropped below 8/min ({value}/min)"),
    ("temperature", "above", 39.5, "Temperature exceeded 39.5C ({value}C)"),
    ("gcs", "below", 14, "GCS declined below 14 ({value})"),
    ("gcs", "below", 9, "CRITICAL: GCS dropped below 9 ({value})"),
]


def _compute_map(snapshot: VitalsSnapshot) -> float:
    """Compute Mean Arterial Pressure from systolic/diastolic."""
    return (snapshot.systolic_bp + 2 * snapshot.diastolic_bp) / 3


# Additional MAP threshold
_MAP_THRESHOLD = 65  # mmHg


def check_reassessment_triggers(
    patient_id: str,
    previous: VitalsSnapshot | None,
    current: VitalsSnapshot,
) -> list[ReassessmentTrigger]:
    """Check if the current vitals snapshot triggers any reassessment alerts.

    Only fires for NEW threshold crossings: if the previous snapshot was
    already below a threshold, the trigger does not re-fire. This prevents
    spam on sustained abnormality.

    Args:
        patient_id: Patient identifier.
        previous: The previous vitals snapshot (None on first check).
        current: The current vitals snapshot.

    Returns:
        List of triggered reassessment events (may be empty).
    """
    triggers: list[ReassessmentTrigger] = []

    for param, direction, threshold, msg_template in _VITAL_THRESHOLDS:
        current_val = getattr(current, param, None)
        if current_val is None:
            continue

        prev_val = getattr(previous, param, None) if previous else None

        crossed = False
        if direction == "below":
            # Trigger if current is below threshold AND previous was not
            if current_val < threshold:
                if prev_val is None or prev_val >= threshold:
                    crossed = True
        elif direction == "above":
            if current_val > threshold:
                if prev_val is None or prev_val <= threshold:
                    crossed = True

        if crossed:
            triggers.append(
                ReassessmentTrigger(
                    patient_id=patient_id,
                    trigger_type="vital_sign",
                    parameter=param,
                    value=current_val,
                    threshold=threshold,
                    direction=direction,
                    message=msg_template.format(value=current_val),
                )
            )

    # MAP threshold
    current_map = _compute_map(current)
    if current_map < _MAP_THRESHOLD:
        prev_map = _compute_map(previous) if previous else None
        if prev_map is None or prev_map >= _MAP_THRESHOLD:
            triggers.append(
                ReassessmentTrigger(
                    patient_id=patient_id,
                    trigger_type="vital_sign",
                    parameter="map",
                    value=round(current_map, 1),
                    threshold=_MAP_THRESHOLD,
                    direction="below",
                    message=f"MAP dropped below 65 mmHg ({current_map:.1f} mmHg)",
                )
            )

    return triggers
