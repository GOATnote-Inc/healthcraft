"""Tests for the three pilot invariants on task MW-011.

Coverage strategy: per validator, exercise all three verdicts --
VERIFIED, CONTRADICTED, INSUFFICIENT_EVIDENCE -- against a synthetic
WorldState. No LLM calls, no fixtures from disk.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from healthcraft.evaluator import (
    Verdict,
    get_validator,
    registered_criteria,
    validate,
)
from healthcraft.world.state import AuditEntry, WorldState

# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 2, 10, 16, 42, 0, tzinfo=timezone.utc)


def _ws_with_patient(weight_kg: float | None = 15.0) -> WorldState:
    """Build a WorldState with a single pediatric patient and empty log."""
    ws = WorldState(start_time=_T0)
    if weight_kg is not None:
        ws.put_entity(
            "patient",
            "PAT-MW011",
            {"id": "PAT-MW011", "weight_kg": weight_kg, "age": 3},
        )
    else:
        ws.put_entity("patient", "PAT-MW011", {"id": "PAT-MW011", "age": 3})
    return ws


def _append(
    ws: WorldState,
    tool_name: str,
    params: dict[str, Any],
    t_offset_sec: int,
    result_summary: str = "",
) -> None:
    entry = AuditEntry(
        tool_name=tool_name,
        timestamp=_T0 + timedelta(seconds=t_offset_sec),
        params=params,
        result_summary=result_summary,
    )
    ws._audit_log.append(entry)  # tests are allowed to poke the private


# ---------------------------------------------------------------------------
# Registry sanity
# ---------------------------------------------------------------------------


def test_registry_contains_three_pilot_criteria():
    ids = registered_criteria()
    assert "MW-011-C01" in ids
    assert "MW-011-C02" in ids
    assert "MW-011-C05" in ids


def test_unknown_criterion_returns_insufficient():
    ws = _ws_with_patient()
    r = validate("NONEXISTENT-C99", ws)
    assert r.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert "no_validator_registered" in r.evidence


# ---------------------------------------------------------------------------
# MW-011-C01: weight confirmation before pediatric dosing
# ---------------------------------------------------------------------------


def test_c01_verified_when_weight_lookup_precedes_order():
    ws = _ws_with_patient()
    _append(
        ws,
        "getEncounterDetails",
        {"encounter_id": "ENC-1"},
        t_offset_sec=0,
        result_summary="weight_kg=15 per Broselow tape yellow zone",
    )
    _append(
        ws,
        "createClinicalOrder",
        {"medication": "epinephrine", "dose_mg": 0.15},
        t_offset_sec=60,
    )
    r = validate("MW-011-C01", ws)
    assert r.verdict is Verdict.VERIFIED


def test_c01_contradicted_when_order_precedes_weight_lookup():
    ws = _ws_with_patient()
    _append(
        ws,
        "createClinicalOrder",
        {"medication": "epinephrine", "dose_mg": 0.15},
        t_offset_sec=0,
    )
    _append(
        ws,
        "getEncounterDetails",
        {"encounter_id": "ENC-1"},
        t_offset_sec=60,
        result_summary="weight_kg=15",
    )
    r = validate("MW-011-C01", ws)
    assert r.verdict is Verdict.CONTRADICTED
    assert "no prior weight lookup" in r.evidence


def test_c01_insufficient_when_no_peds_drug_orders():
    ws = _ws_with_patient()
    _append(
        ws,
        "getEncounterDetails",
        {"encounter_id": "ENC-1"},
        t_offset_sec=0,
        result_summary="weight_kg=15",
    )
    # No createClinicalOrder for a pediatric drug.
    r = validate("MW-011-C01", ws)
    assert r.verdict is Verdict.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# MW-011-C02: epinephrine dose within 1% of 0.01 mg/kg x weight_kg
# ---------------------------------------------------------------------------


def test_c02_verified_at_correct_pediatric_dose():
    ws = _ws_with_patient(weight_kg=15.0)
    _append(
        ws,
        "createClinicalOrder",
        {"medication": "epinephrine", "dose_mg": 0.15},  # 0.01 * 15
        t_offset_sec=60,
    )
    r = validate("MW-011-C02", ws)
    assert r.verdict is Verdict.VERIFIED


def test_c02_contradicted_at_adult_code_dose():
    ws = _ws_with_patient(weight_kg=15.0)
    _append(
        ws,
        "createClinicalOrder",
        {"medication": "epinephrine", "dose_mg": 1.0},  # adult code dose
        t_offset_sec=60,
    )
    r = validate("MW-011-C02", ws)
    assert r.verdict is Verdict.CONTRADICTED
    assert "outside" in r.evidence


def test_c02_insufficient_when_weight_unknown():
    ws = _ws_with_patient(weight_kg=None)
    _append(
        ws,
        "createClinicalOrder",
        {"medication": "epinephrine", "dose_mg": 0.15},
        t_offset_sec=60,
    )
    r = validate("MW-011-C02", ws)
    assert r.verdict is Verdict.INSUFFICIENT_EVIDENCE


def test_c02_insufficient_when_dose_missing():
    ws = _ws_with_patient(weight_kg=15.0)
    _append(
        ws,
        "createClinicalOrder",
        {"medication": "epinephrine"},  # dose_mg absent
        t_offset_sec=60,
    )
    r = validate("MW-011-C02", ws)
    assert r.verdict is Verdict.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# MW-011-C05: pediatric dextrose (D25 2 mL/kg or D10 5 mL/kg); D50 forbidden
# ---------------------------------------------------------------------------


def test_c05_verified_with_d25_correct_volume():
    ws = _ws_with_patient(weight_kg=15.0)
    _append(
        ws,
        "createClinicalOrder",
        {"medication": "D25", "dose_ml": 30.0},  # 2 mL/kg * 15
        t_offset_sec=60,
    )
    r = validate("MW-011-C05", ws)
    assert r.verdict is Verdict.VERIFIED


def test_c05_verified_with_d10_correct_volume():
    ws = _ws_with_patient(weight_kg=15.0)
    _append(
        ws,
        "createClinicalOrder",
        {"medication": "D10 dextrose", "dose_ml": 75.0},  # 5 mL/kg * 15
        t_offset_sec=60,
    )
    r = validate("MW-011-C05", ws)
    assert r.verdict is Verdict.VERIFIED


def test_c05_contradicted_on_any_d50_order():
    ws = _ws_with_patient(weight_kg=15.0)
    _append(
        ws,
        "createClinicalOrder",
        {"medication": "D50 dextrose", "dose_ml": 30.0},
        t_offset_sec=60,
    )
    r = validate("MW-011-C05", ws)
    assert r.verdict is Verdict.CONTRADICTED
    assert "D50" in r.evidence


def test_c05_insufficient_when_no_dextrose_ordered():
    ws = _ws_with_patient(weight_kg=15.0)
    _append(
        ws,
        "createClinicalOrder",
        {"medication": "epinephrine", "dose_mg": 0.15},
        t_offset_sec=60,
    )
    r = validate("MW-011-C05", ws)
    assert r.verdict is Verdict.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# Registry API
# ---------------------------------------------------------------------------


def test_get_validator_returns_callable_for_registered_id():
    fn = get_validator("MW-011-C02")
    assert fn is not None
    ws = _ws_with_patient(weight_kg=15.0)
    _append(
        ws,
        "createClinicalOrder",
        {"medication": "epinephrine", "dose_mg": 0.15},
        t_offset_sec=0,
    )
    r = fn(ws)
    assert r.verdict is Verdict.VERIFIED


def test_get_validator_returns_none_for_unknown():
    assert get_validator("NONEXISTENT-C99") is None
