"""Tests for healthcraft.world.transition (PR-C / WS-3).

Covers the bounded-residual closed-loop physiology overlay: ramp/decay
envelope, multi-action superposition, physiologic clipping, action
classification, and audit-log → action extraction.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from healthcraft.entities.base import EntityType
from healthcraft.entities.encounters import Encounter, ESILevel
from healthcraft.world.physiology import VitalsSnapshot
from healthcraft.world.state import AuditEntry, WorldState
from healthcraft.world.transition import (
    ACTION_EFFECTS,
    ActionEffect,
    _classify_action,
    actions_for_patient,
    actions_from_audit_log,
    apply_action_effects_to_vitals,
    evaluate_action_contribution,
)

_BASE = VitalsSnapshot(
    offset_minutes=0,
    heart_rate=100,
    systolic_bp=90,
    diastolic_bp=55,
    respiratory_rate=22,
    spo2=94,
    temperature=38.8,
    gcs=15,
)

_T0 = datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
_T5 = datetime(2026, 1, 15, 7, 5, 0, tzinfo=timezone.utc)


def _audit(
    tool_name: str,
    params: dict,
    *,
    summary: str = "ok",
    when: datetime = _T5,
) -> AuditEntry:
    return AuditEntry(
        tool_name=tool_name,
        timestamp=when,
        params=params,
        result_summary=summary,
    )


# ---------------------------------------------------------------------------
# evaluate_action_contribution
# ---------------------------------------------------------------------------


def test_no_contribution_before_action():
    eff = ActionEffect(delta={"heart_rate": 10})
    assert evaluate_action_contribution(eff, -1.0) == {}


def test_contribution_ramps_linearly_to_peak():
    eff = ActionEffect(delta={"systolic_bp": 10}, onset_minutes=10, duration_minutes=30)
    # Half-way through onset → half the peak delta.
    assert evaluate_action_contribution(eff, 5.0)["systolic_bp"] == 5.0
    # At onset → full peak.
    assert evaluate_action_contribution(eff, 10.0)["systolic_bp"] == 10.0


def test_contribution_decays_linearly_from_peak():
    eff = ActionEffect(delta={"systolic_bp": 10}, onset_minutes=10, duration_minutes=30)
    # Just past peak — slightly less than 10.
    assert evaluate_action_contribution(eff, 11.0)["systolic_bp"] < 10.0
    # Half-decay.
    assert evaluate_action_contribution(eff, 25.0)["systolic_bp"] == pytest.approx(5.0, abs=0.05)
    # Past end of decay window → spent.
    assert evaluate_action_contribution(eff, 50.0) == {}


def test_zero_onset_is_immediate_peak():
    eff = ActionEffect(delta={"heart_rate": 5}, onset_minutes=0.0, duration_minutes=10.0)
    # At t=0 with zero onset, scale is 1.0 (immediate peak).
    assert evaluate_action_contribution(eff, 0.0)["heart_rate"] == 5.0


# ---------------------------------------------------------------------------
# apply_action_effects_to_vitals
# ---------------------------------------------------------------------------


def test_no_actions_returns_base_after_round_and_clip():
    out = apply_action_effects_to_vitals(_BASE, [], current_time_minutes=0)
    assert out.heart_rate == _BASE.heart_rate
    assert out.systolic_bp == _BASE.systolic_bp
    assert out.temperature == _BASE.temperature


def test_single_vasopressor_raises_bp():
    eff = ACTION_EFFECTS["createClinicalOrder:medication:vasopressor"]
    out = apply_action_effects_to_vitals(_BASE, [(0.0, eff)], current_time_minutes=10.0)
    assert out.systolic_bp > _BASE.systolic_bp
    assert out.diastolic_bp > _BASE.diastolic_bp


def test_superposition_two_doses_add_within_bounds():
    eff = ACTION_EFFECTS["createClinicalOrder:medication:vasopressor"]
    one = apply_action_effects_to_vitals(_BASE, [(0.0, eff)], current_time_minutes=10.0)
    two = apply_action_effects_to_vitals(_BASE, [(0.0, eff), (0.0, eff)], current_time_minutes=10.0)
    assert two.systolic_bp >= one.systolic_bp


def test_spo2_capped_at_100():
    """SpO2 cannot exceed 100% no matter how much oxygen-equivalent we stack."""
    huge = ActionEffect(delta={"spo2": 30.0}, onset_minutes=1, duration_minutes=60)
    out = apply_action_effects_to_vitals(_BASE, [(0.0, huge)], current_time_minutes=1.0)
    assert out.spo2 == 100


def test_systolic_bp_floored_at_lower_bound():
    crash = ActionEffect(delta={"systolic_bp": -300.0}, onset_minutes=1, duration_minutes=60)
    out = apply_action_effects_to_vitals(_BASE, [(0.0, crash)], current_time_minutes=1.0)
    assert out.systolic_bp >= 40


def test_temperature_rounded_to_one_decimal():
    eff = ActionEffect(delta={"temperature": -0.5}, onset_minutes=1, duration_minutes=60)
    out = apply_action_effects_to_vitals(_BASE, [(0.0, eff)], current_time_minutes=1.0)
    # 38.8 - 0.5 = 38.3
    assert out.temperature == 38.3


def test_no_action_yields_byte_identical_to_base_for_int_vitals():
    """When no actions apply, all integer vitals match base exactly."""
    out = apply_action_effects_to_vitals(_BASE, [], current_time_minutes=0)
    for vital in ("heart_rate", "systolic_bp", "diastolic_bp", "respiratory_rate", "spo2", "gcs"):
        assert getattr(out, vital) == getattr(_BASE, vital)


# ---------------------------------------------------------------------------
# _classify_action
# ---------------------------------------------------------------------------


def test_classify_vasopressor():
    e = _audit(
        "createClinicalOrder",
        {"order_type": "medication", "details": {"medication": "norepinephrine 8 mcg/min"}},
    )
    assert _classify_action(e) == "createClinicalOrder:medication:vasopressor"


def test_classify_antibiotic():
    e = _audit(
        "createClinicalOrder",
        {"order_type": "medication", "details": {"medication": "vancomycin 1g IV"}},
    )
    assert _classify_action(e) == "createClinicalOrder:medication:antibiotic"


def test_classify_fluid():
    e = _audit(
        "createClinicalOrder",
        {"order_type": "medication", "details": {"medication": "normal saline bolus 1L"}},
    )
    assert _classify_action(e) == "createClinicalOrder:medication:fluid"


def test_classify_oxygen_procedure():
    e = _audit(
        "createClinicalOrder",
        {"order_type": "procedure", "details": {"name": "oxygen via nasal cannula 4L"}},
    )
    assert _classify_action(e) == "createClinicalOrder:procedure:oxygen"


def test_classify_unknown_medication_returns_none():
    e = _audit(
        "createClinicalOrder",
        {"order_type": "lab", "details": {"test": "CBC"}},
    )
    assert _classify_action(e) is None


def test_classify_error_status_returns_none():
    e = _audit(
        "createClinicalOrder",
        {"order_type": "medication", "details": {"medication": "vancomycin"}},
        summary="error",
    )
    assert _classify_action(e) is None


def test_classify_non_mutate_tool_returns_none():
    e = _audit("searchPatients", {"name": "Smith"})
    assert _classify_action(e) is None


# ---------------------------------------------------------------------------
# actions_from_audit_log
# ---------------------------------------------------------------------------


def test_actions_extracted_from_log():
    log = [
        _audit(
            "createClinicalOrder",
            {"order_type": "medication", "details": {"medication": "norepinephrine"}},
        ),
        _audit("searchPatients", {"name": "Smith"}),  # ignored — read tool
        _audit(
            "createClinicalOrder",
            {"order_type": "medication", "details": {"medication": "vancomycin 1g"}},
        ),
    ]
    actions = actions_from_audit_log(log, _T0)
    assert len(actions) == 2
    # Both at 5 minutes (the _audit fixture's default timestamp).
    assert all(t == 5.0 for t, _ in actions)


# ---------------------------------------------------------------------------
# actions_for_patient — encounter_id → patient lookup
# ---------------------------------------------------------------------------


def _encounter(eid: str, patient_id: str) -> Encounter:
    return Encounter(
        id=eid,
        entity_type=EntityType.ENCOUNTER,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        patient_id=patient_id,
        chief_complaint="x",
        esi_level=ESILevel.URGENT,
    )


def test_actions_filter_by_encounter_to_patient():
    w = WorldState(start_time=_T0)
    w.put_entity("encounter", "ENC-MATCH", _encounter("ENC-MATCH", "PAT-TARGET"))
    w.put_entity("encounter", "ENC-OTHER", _encounter("ENC-OTHER", "PAT-OTHER"))
    log = [
        _audit(
            "createClinicalOrder",
            {
                "encounter_id": "ENC-MATCH",
                "order_type": "medication",
                "details": {"medication": "norepinephrine"},
            },
        ),
        _audit(
            "createClinicalOrder",
            {
                "encounter_id": "ENC-OTHER",
                "order_type": "medication",
                "details": {"medication": "vancomycin"},
            },
        ),
    ]
    actions = actions_for_patient(log, "PAT-TARGET", w, _T0)
    assert len(actions) == 1  # only ENC-MATCH's action


def test_actions_filter_direct_patient_id_match():
    w = WorldState(start_time=_T0)
    log = [
        _audit(
            "createClinicalOrder",
            {
                "patient_id": "PAT-DIRECT",
                "order_type": "medication",
                "details": {"medication": "norepinephrine"},
            },
        ),
    ]
    actions = actions_for_patient(log, "PAT-DIRECT", w, _T0)
    assert len(actions) == 1
