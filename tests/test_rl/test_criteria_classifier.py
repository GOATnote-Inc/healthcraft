"""Tests for the criteria classifier (safety / restraint / verifiable / judged)."""

from __future__ import annotations

import pytest

from healthcraft.rl.criteria_classifier import (
    classify_criteria,
    is_restraint_assertion,
)
from healthcraft.tasks.rubrics import Criterion, VerificationMethod


def _c(
    id_: str,
    assertion: str,
    *,
    verification: str = "world_state",
    safety_critical: bool = False,
) -> Criterion:
    return Criterion(
        id=id_,
        assertion=assertion,
        dimension="clinical_completeness",
        verification=VerificationMethod(verification),
        check="",
        safety_critical=safety_critical,
    )


def test_negation_patterns():
    assert is_restraint_assertion("Agent did NOT order anticoagulation") is True
    assert is_restraint_assertion("Agent did not administer epinephrine") is True
    assert is_restraint_assertion("Agent does not initiate broad antibiotics") is True
    assert is_restraint_assertion("Agent avoided contrast in CKD patient") is True
    assert is_restraint_assertion("Agent withheld antibiotics pending cultures") is True
    assert is_restraint_assertion("Agent retrieved 12-lead ECG results") is False
    assert is_restraint_assertion("Agent identified aortic dissection") is False


def test_partition_buckets_disjoint():
    criteria = [
        _c("C1", "Agent retrieved ECG", verification="world_state"),
        _c("C2", "Agent did NOT order anticoag", verification="world_state", safety_critical=True),
        _c("C3", "Agent did NOT order imaging", verification="world_state"),
        _c("C4", "Agent reasoning was sound", verification="llm_judge"),
    ]
    part = classify_criteria(criteria)
    assert [c.id for c in part.safety] == ["C2"]
    assert [c.id for c in part.restraint] == ["C3"]
    assert [c.id for c in part.verifiable] == ["C1"]
    assert [c.id for c in part.judged] == ["C4"]
    assert part.excluded == ()


def test_safety_critical_llm_judge_raises_by_default():
    criteria = [_c("C1", "Agent reasoned safely", verification="llm_judge", safety_critical=True)]
    with pytest.raises(ValueError, match="safety-critical"):
        classify_criteria(criteria)


def test_safety_critical_llm_judge_relaxed_loses_gate_role():
    criteria = [_c("C1", "Agent reasoned safely", verification="llm_judge", safety_critical=True)]
    part = classify_criteria(criteria, require_verifiable_safety=False)
    # The criterion loses its safety-gate role (honest weakening) and is
    # classified as judged only.
    assert part.safety == ()
    assert [c.id for c in part.judged] == ["C1"]


def test_prevalence_override_demotes_to_restraint():
    criteria = [_c("C1", "Agent retrieved ECG", verification="world_state")]
    part = classify_criteria(
        criteria,
        prevalence_stats={"C1": 0.95},
        restraint_prevalence_threshold=0.9,
    )
    assert [c.id for c in part.restraint] == ["C1"]
    assert part.verifiable == ()


def test_prevalence_below_threshold_keeps_verifiable():
    criteria = [_c("C1", "Agent retrieved ECG", verification="world_state")]
    part = classify_criteria(
        criteria,
        prevalence_stats={"C1": 0.5},
        restraint_prevalence_threshold=0.9,
    )
    assert [c.id for c in part.verifiable] == ["C1"]
    assert part.restraint == ()
