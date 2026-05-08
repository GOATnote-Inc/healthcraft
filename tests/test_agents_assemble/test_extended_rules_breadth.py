"""Breadth tests for additive rules added by the loop / inline expansion.

Each new rule gets:

- Loadability check (loader returns it by name).
- Low-risk and high-risk hand-crafted scoring assertions.
- Score-range gap audit (sum of max_value covered with no gaps).

These tests are the "TDD step 1" gate for any new rule: they're written
before the rule is appended to ``decision_rules_extended.py``.
"""

from __future__ import annotations

from dataclasses import asdict

import pytest

from healthcraft.agents_assemble.superpower_decision_rules.scoring_strategies import (
    score_rule,
)
from healthcraft.entities.decision_rules import load_decision_rules


def _rule_by_name(name: str) -> dict:
    rules = load_decision_rules()
    for r in rules.values():
        if r.name == name:
            return asdict(r)
    raise AssertionError(f"rule {name!r} not loaded")


def _assert_no_score_gaps(rule: dict) -> None:
    max_total = sum(float(v.get("max_value", 0)) for v in rule["variables"])
    min_total = sum(float(v.get("min_value", 0)) for v in rule["variables"])
    covered: list[tuple[float, float]] = sorted(
        (float(sr["min_score"]), float(sr["max_score"])) for sr in rule["score_ranges"]
    )
    assert covered, f"{rule['name']}: no score ranges declared"
    assert covered[0][0] <= min_total, (
        f"{rule['name']}: lowest range starts at {covered[0][0]} > min sum {min_total}"
    )
    assert covered[-1][1] >= max_total, (
        f"{rule['name']}: highest range ends at {covered[-1][1]} < max sum {max_total}"
    )
    for (_, prev_hi), (next_lo, _) in zip(covered, covered[1:]):
        assert next_lo - prev_hi <= 1, f"{rule['name']}: gap between {prev_hi} and {next_lo}"


# ---------------------------------------------------------------------------
# NEXUS Chest Decision Instrument (blunt thoracic trauma)
# ---------------------------------------------------------------------------


def test_nexus_chest_decision_instrument_loads_and_scores() -> None:
    rule = _rule_by_name("NEXUS Chest Decision Instrument")
    _assert_no_score_gaps(rule)
    low = score_rule({}, rule)
    assert low["risk_level"] == "low"
    high = score_rule(
        {
            "Age > 60": 1,
            "Rapid deceleration mechanism": 1,
            "Chest pain": 1,
            "Intoxication": 0,
            "Altered mental status": 0,
            "Distracting injury": 1,
            "Tenderness to chest wall palpation": 1,
        },
        rule,
    )
    assert high["risk_level"] == "high"


# ---------------------------------------------------------------------------
# A-DROP (Japanese pneumonia severity)
# ---------------------------------------------------------------------------


def test_a_drop_pneumonia_loads_and_scores() -> None:
    rule = _rule_by_name("A-DROP")
    _assert_no_score_gaps(rule)
    low = score_rule({}, rule)
    assert low["risk_level"] == "low"
    high = score_rule(
        {
            "Age (M >= 70 / F >= 75)": 1,
            "Dehydration (BUN >= 21 mg/dL)": 1,
            "Respiratory failure (SpO2 <= 90%)": 1,
            "Orientation disturbance": 1,
            "Low blood pressure (SBP <= 90)": 0,
        },
        rule,
    )
    assert high["risk_level"] == "high"


# ---------------------------------------------------------------------------
# Bova Score (PE intermediate-risk subgrouping)
# ---------------------------------------------------------------------------


def test_bova_score_pe_loads_and_scores() -> None:
    rule = _rule_by_name("Bova Score")
    _assert_no_score_gaps(rule)
    low = score_rule({}, rule)
    assert low["risk_level"] == "low"
    high = score_rule(
        {
            "Heart rate >= 110": 1,
            "Systolic BP 90-100": 2,
            "Elevated cardiac troponin": 2,
            "RV dysfunction on imaging": 2,
        },
        rule,
    )
    assert high["risk_level"] == "high"


# ---------------------------------------------------------------------------
# HEAR Score (chest pain triage without troponin)
# ---------------------------------------------------------------------------


def test_hear_score_loads_and_scores() -> None:
    rule = _rule_by_name("HEAR Score")
    _assert_no_score_gaps(rule)
    low = score_rule({}, rule)
    assert low["risk_level"] == "low"
    high = score_rule(
        {
            "History suspicious": 2,
            "ECG findings": 2,
            "Age tier": 2,
            "Risk factors": 2,
        },
        rule,
    )
    assert high["risk_level"] == "high"


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# PHQ-9 (depression screen used in ED for psychiatric triage)
# ---------------------------------------------------------------------------


def test_phq9_loads_and_scores() -> None:
    rule = _rule_by_name("PHQ-9")
    _assert_no_score_gaps(rule)
    low = score_rule({}, rule)
    assert low["risk_level"] == "low"
    severe = score_rule(
        {f"PHQ-9 item {i}": 3 for i in range(1, 10)},
        rule,
    )
    assert severe["risk_level"] in {"high", "very_high", "extreme"}


# ---------------------------------------------------------------------------
# Pediatric Appendicitis Score (PAS)
# ---------------------------------------------------------------------------


def test_pas_pediatric_appendicitis_loads_and_scores() -> None:
    rule = _rule_by_name("Pediatric Appendicitis Score (PAS)")
    _assert_no_score_gaps(rule)
    low = score_rule({}, rule)
    assert low["risk_level"] == "low"
    high = score_rule(
        {
            "Cough/percussion/hopping tenderness": 2,
            "Anorexia": 1,
            "Pyrexia (>= 38C)": 1,
            "Nausea/emesis": 1,
            "RLQ tenderness": 2,
            "Leukocytosis (WBC > 10K)": 1,
            "Polymorphonuclear neutrophilia (>75%)": 1,
            "Migration of pain to RLQ": 1,
        },
        rule,
    )
    assert high["risk_level"] == "high"


# ---------------------------------------------------------------------------
# Geneva Score (revised) for PE
# ---------------------------------------------------------------------------


def test_geneva_score_revised_loads_and_scores() -> None:
    rule = _rule_by_name("Geneva Score (Revised)")
    _assert_no_score_gaps(rule)
    low = score_rule({}, rule)
    assert low["risk_level"] == "low"
    high = score_rule(
        {
            "Age > 65": 1,
            "Previous DVT or PE": 3,
            "Surgery or fracture in past month": 2,
            "Active malignancy": 2,
            "Unilateral lower limb pain": 3,
            "Hemoptysis": 2,
            "Heart rate 75-94": 0,
            "Heart rate >= 95": 5,
            "Pain on lower limb deep palpation and unilateral edema": 4,
        },
        rule,
    )
    assert high["risk_level"] == "high"


# ---------------------------------------------------------------------------
# CART Score (cardiac arrest risk on wards)
# ---------------------------------------------------------------------------


def test_cart_score_loads_and_scores() -> None:
    rule = _rule_by_name("CART Score")
    _assert_no_score_gaps(rule)
    low = score_rule({}, rule)
    assert low["risk_level"] == "low"
    high = score_rule(
        {
            "Respiratory rate points": 22,
            "Heart rate points": 13,
            "Diastolic BP points": 23,
            "Age points": 9,
        },
        rule,
    )
    assert high["risk_level"] == "high"


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "NEXUS Chest Decision Instrument",
        "A-DROP",
        "Bova Score",
        "HEAR Score",
        "PHQ-9",
        "Pediatric Appendicitis Score (PAS)",
        "Geneva Score (Revised)",
        "CART Score",
    ],
)
def test_new_rules_round_trip_and_have_no_score_gaps(name: str) -> None:
    rule = _rule_by_name(name)
    _assert_no_score_gaps(rule)
    assert rule["evidence_level"] == "validated"
    assert rule["url"].startswith("https://")
