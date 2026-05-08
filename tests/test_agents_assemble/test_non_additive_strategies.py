"""Tests for non-additive scoring strategies (MELD-Na, Tokyo Guidelines).

The additive strategy is exhaustively covered by ``test_fuzz`` and
``test_scoring_strategies``. These cases pin behavior of the regression /
categorical strategies that the additive engine cannot model.
"""

from __future__ import annotations

import pytest

from healthcraft.agents_assemble.superpower_decision_rules.scoring_strategies import (
    score_rule,
)
from healthcraft.entities.decision_rules import load_decision_rules


@pytest.fixture(scope="module")
def meld_na_rule():
    rules = load_decision_rules()
    return next(r.__dict__ for r in rules.values() if r.name == "MELD-Na")


@pytest.fixture(scope="module")
def tokyo_rule():
    rules = load_decision_rules()
    return next(
        r.__dict__ for r in rules.values() if r.name == "Tokyo Guidelines (Cholangitis Severity)"
    )


# ---------------------------------------------------------------------------
# MELD-Na (regression)
# ---------------------------------------------------------------------------


def test_meld_na_returns_low_score_for_normal_labs(meld_na_rule) -> None:
    """Healthy patient (creat 1.0, bili 1.0, INR 1.0, Na 137) -> MELD-Na 6 = low."""
    out = score_rule(
        {
            "Creatinine (mg/dL)": 1.0,
            "Bilirubin (mg/dL)": 1.0,
            "INR": 1.0,
            "Sodium (mmol/L)": 137,
        },
        meld_na_rule,
    )
    assert out["score"] <= 9
    assert out["risk_level"] == "low"


def test_meld_na_returns_high_score_for_decompensated_labs(meld_na_rule) -> None:
    """Decompensated cirrhotic (creat 3.5, bili 8, INR 3, Na 128) -> MELD-Na high."""
    out = score_rule(
        {
            "Creatinine (mg/dL)": 3.5,
            "Bilirubin (mg/dL)": 8.0,
            "INR": 3.0,
            "Sodium (mmol/L)": 128,
        },
        meld_na_rule,
    )
    assert out["score"] >= 25
    assert out["risk_level"] in {"high", "very_high", "extreme"}


def test_meld_na_caps_creatinine_and_clamps_sodium(meld_na_rule) -> None:
    """Creatinine 10 (dialysis) gets capped to 4.0; Na 110 clamped to 125."""
    capped = score_rule(
        {
            "Creatinine (mg/dL)": 10.0,
            "Bilirubin (mg/dL)": 5.0,
            "INR": 2.0,
            "Sodium (mmol/L)": 110,
        },
        meld_na_rule,
    )
    natural_cap = score_rule(
        {
            "Creatinine (mg/dL)": 4.0,
            "Bilirubin (mg/dL)": 5.0,
            "INR": 2.0,
            "Sodium (mmol/L)": 125,
        },
        meld_na_rule,
    )
    assert capped["score"] == natural_cap["score"]


def test_meld_na_clamps_to_unos_score_range(meld_na_rule) -> None:
    """Score is always within [6, 40] per UNOS implementation."""
    extreme = score_rule(
        {
            "Creatinine (mg/dL)": 4.0,
            "Bilirubin (mg/dL)": 50.0,
            "INR": 10.0,
            "Sodium (mmol/L)": 125,
        },
        meld_na_rule,
    )
    assert 6 <= extreme["score"] <= 40


# ---------------------------------------------------------------------------
# Tokyo Guidelines (categorical)
# ---------------------------------------------------------------------------


def test_tokyo_no_findings_is_grade_i_mild(tokyo_rule) -> None:
    out = score_rule({}, tokyo_rule)
    assert out["score"] == 1
    assert out["risk_level"] == "low"
    assert "Grade I" in out["variables_used"]["rationale"]


def test_tokyo_two_grade_ii_criteria_is_grade_ii_moderate(tokyo_rule) -> None:
    out = score_rule(
        {"Fever >= 39C": 1, "Age >= 75": 1},
        tokyo_rule,
    )
    assert out["score"] == 2
    assert out["risk_level"] == "moderate"


def test_tokyo_one_grade_ii_is_grade_i(tokyo_rule) -> None:
    """A single Grade-II criterion alone does NOT escalate to moderate."""
    out = score_rule({"Age >= 75": 1}, tokyo_rule)
    assert out["score"] == 1
    assert out["risk_level"] == "low"


def test_tokyo_any_grade_iii_organ_dysfunction_escalates_to_severe(tokyo_rule) -> None:
    """Even a single organ-dysfunction criterion -> Grade III, regardless of
    Grade-II count. This matters: real organ failure must always escalate."""
    out = score_rule(
        {"Cardiovascular dysfunction (pressors required)": 1},
        tokyo_rule,
    )
    assert out["score"] == 3
    assert out["risk_level"] == "high"
    assert "organ dysfunction" in out["variables_used"]["rationale"].lower()


def test_tokyo_grade_iii_dominates_grade_ii(tokyo_rule) -> None:
    """A Grade III criterion + several Grade II criteria still grade as III,
    not 'super-moderate'. The decision tree is hierarchical, not additive."""
    out = score_rule(
        {
            "Renal dysfunction (Cr > 2 or oliguria)": 1,
            "Fever >= 39C": 1,
            "Age >= 75": 1,
            "Total bilirubin >= 5": 1,
        },
        tokyo_rule,
    )
    assert out["score"] == 3
    assert out["risk_level"] == "high"


# ---------------------------------------------------------------------------
# Loader integration
# ---------------------------------------------------------------------------


def test_non_additive_rules_carry_their_scorer_field() -> None:
    rules = load_decision_rules()
    meld = next(r for r in rules.values() if r.name == "MELD-Na")
    tokyo = next(r for r in rules.values() if r.name == "Tokyo Guidelines (Cholangitis Severity)")
    assert getattr(meld, "scorer", "") == "meld_na"
    assert getattr(tokyo, "scorer", "") == "tokyo_cholangitis"


def test_additive_rules_default_to_additive_scorer() -> None:
    rules = load_decision_rules()
    heart = next(r for r in rules.values() if r.name == "HEART Score")
    assert getattr(heart, "scorer", "additive") == "additive"


def test_rule_count_after_breadth_expansion() -> None:
    rules = load_decision_rules()
    assert len(rules) >= 57, f"expected >=57 rules after breadth expansion, got {len(rules)}"
