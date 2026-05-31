"""Structural check-linter — the recurrence guard for the grader bug family.

Two duties:
  * GUARD: every ACTIVE check (base-task world_state criteria + v9/v10/v11
    overlay entries) is clean. A future edit (human or auto-proposer) that
    re-introduces a dangling operator, an OR-of-negations, or a member-not-class
    literal turns this red.
  * PROOF: each rule actually fires on its bug pattern (a guard that never bites
    is worse than none).
"""

from __future__ import annotations

from pathlib import Path

from healthcraft.tasks.check_linter import (
    SINGLE_DRUG_ALLOWLIST,
    lint_active_checks,
    lint_check,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
# GUARD: all active checks are clean
# --------------------------------------------------------------------------- #


def test_no_violations_in_active_checks() -> None:
    violations = lint_active_checks(REPO_ROOT)
    assert violations == [], "active checks have linter violations:\n  " + "\n  ".join(violations)


# --------------------------------------------------------------------------- #
# PROOF: each rule bites
# --------------------------------------------------------------------------- #


def test_catches_dangling_or() -> None:
    # The exact MW-016 truncation: "...matching fosphenytoin or".
    v = lint_check(
        "X-C01",
        "audit_log does NOT contain createClinicalOrder with medication matching fosphenytoin or",
    )
    assert any("dangling" in s for s in v), v


def test_catches_dangling_and() -> None:
    v = lint_check("X-C01", "audit_log does NOT contain processDischarge and")
    assert any("dangling" in s for s in v), v


def test_catches_or_of_negations() -> None:
    v = lint_check(
        "X-C01",
        "audit_log does NOT contain createClinicalOrder with medication matching triptan "
        "OR audit_log does NOT contain createClinicalOrder with medication matching ergot_abortive",
    )
    assert any("OR-of-negations" in s for s in v), v


def test_catches_member_not_class() -> None:
    # 'enoxaparin' is a MEMBER of the anticoagulant class -> should be the class.
    v = lint_check(
        "X-C01",
        "audit_log does NOT contain createClinicalOrder with medication matching enoxaparin",
    )
    assert any("MEMBER" in s for s in v), v
    # 'labetalol' is a member of iv_antihypertensive / beta_blocker (the NEG-004 bug).
    v2 = lint_check(
        "X-C01", "audit_log does NOT contain createClinicalOrder with medication matching labetalol"
    )
    assert any("MEMBER" in s for s in v2), v2


# --------------------------------------------------------------------------- #
# PROOF: legitimate forms are NOT flagged (zero false positives)
# --------------------------------------------------------------------------- #


def test_class_usage_passes() -> None:
    assert (
        lint_check(
            "X-C01",
            "audit_log does NOT contain createClinicalOrder with medication matching anticoagulant",
        )
        == []
    )


def test_and_of_negations_passes() -> None:
    assert (
        lint_check(
            "X-C01",
            "audit_log does NOT contain createClinicalOrder with medication matching triptan "
            "AND audit_log does NOT contain createClinicalOrder with medication matching ergot_abortive",
        )
        == []
    )


def test_allowlisted_single_drugs_pass() -> None:
    for drug in SINGLE_DRUG_ALLOWLIST:
        v = lint_check(
            "X-C01",
            f"audit_log does NOT contain createClinicalOrder with medication matching {drug}",
        )
        assert v == [], f"{drug} is allowlisted but flagged: {v}"


def test_non_member_literals_pass() -> None:
    # Single tests / diagnoses / non-classed drugs are inherently single-item
    # (no class to prefer) and must not be flagged.
    for tgt in (
        "ct head",
        "cholecystitis",
        "methotrexate",
        "lumbar puncture",
        "sodium bicarbonate",
    ):
        v = lint_check(
            "X-C01",
            f"audit_log does NOT contain createClinicalOrder with medication matching {tgt}",
        )
        assert v == [], f"{tgt!r} should pass (not a class member): {v}"
