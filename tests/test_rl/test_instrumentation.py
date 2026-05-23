"""Tests for healthcraft.rl.instrumentation (PR-D / WS-6)."""

from __future__ import annotations

import pytest

from healthcraft.rl.instrumentation import (
    CanaryReport,
    cohens_kappa,
    degenerate_group_fraction,
    group_reward_variance,
    judge_kappa_drift,
    kl_overoptimisation_signal,
    prevalence_drift,
    restraint_inflation_signal,
)

# ---------------------------------------------------------------------------
# group_reward_variance + degenerate_group_fraction
# ---------------------------------------------------------------------------


def test_empty_group_is_degenerate():
    g = group_reward_variance([])
    assert g.is_degenerate is True
    assert g.n == 0


def test_uniform_group_is_degenerate():
    """All-pass (or all-fail) groups have zero gradient — must be flagged."""
    g = group_reward_variance([1.0, 1.0, 1.0, 1.0])
    assert g.is_degenerate is True
    assert g.variance == 0.0


def test_mixed_group_is_not_degenerate():
    g = group_reward_variance([1.0, 0.0, 0.5, 0.75])
    assert g.is_degenerate is False
    assert g.variance > 0.0


def test_degenerate_fraction_aggregates():
    groups = [
        group_reward_variance([1.0, 1.0]),
        group_reward_variance([0.0, 0.0]),
        group_reward_variance([0.5, 1.0]),
        group_reward_variance([0.0, 1.0]),
    ]
    assert degenerate_group_fraction(groups) == pytest.approx(0.5)


def test_degenerate_fraction_handles_empty():
    assert degenerate_group_fraction([]) == 0.0


# ---------------------------------------------------------------------------
# prevalence_drift + restraint_inflation_signal
# ---------------------------------------------------------------------------


def test_prevalence_drift_subtracts_baseline():
    drifts = prevalence_drift(
        current={"C1": 0.95, "C2": 0.50, "C3": 0.30},
        baseline={"C1": 0.90, "C2": 0.55, "C3": 0.30},
    )
    assert drifts == {"C1": pytest.approx(0.05), "C2": pytest.approx(-0.05), "C3": 0.0}


def test_prevalence_drift_drops_unpaired_keys():
    drifts = prevalence_drift(
        current={"C1": 1.0, "ONLY_IN_CURRENT": 0.5},
        baseline={"C1": 0.5, "ONLY_IN_BASELINE": 0.5},
    )
    assert "ONLY_IN_CURRENT" not in drifts
    assert "ONLY_IN_BASELINE" not in drifts


def test_restraint_inflation_isolates_high_prevalence():
    """Only criteria with baseline >= threshold contribute."""
    drifts = {"HIGH": 0.10, "LOW": 0.30}
    baselines = {"HIGH": 0.95, "LOW": 0.20}
    s = restraint_inflation_signal(drifts, baselines, high_prevalence_threshold=0.9)
    # Only HIGH counts; LOW (baseline 0.20) is below threshold.
    assert s == pytest.approx(0.10)


def test_restraint_inflation_zero_when_no_high_prev():
    s = restraint_inflation_signal({"LOW": 0.5}, {"LOW": 0.3}, high_prevalence_threshold=0.9)
    assert s == 0.0


# ---------------------------------------------------------------------------
# cohens_kappa + judge_kappa_drift
# ---------------------------------------------------------------------------


def test_kappa_perfect_agreement_is_one():
    assert cohens_kappa([True, True, False, False], [True, True, False, False]) == 1.0


def test_kappa_perfect_disagreement_is_negative():
    k = cohens_kappa([True, True, False, False], [False, False, True, True])
    assert k < 0.0


def test_kappa_raises_on_length_mismatch():
    with pytest.raises(ValueError):
        cohens_kappa([True], [True, False])


def test_kappa_raises_on_empty():
    with pytest.raises(ValueError):
        cohens_kappa([], [])


def test_kappa_drift_detects_drop():
    drift = judge_kappa_drift(
        paired_votes_now=[(True, False), (False, True), (True, True), (False, False)],
        paired_votes_baseline=[(True, True), (False, False), (True, True), (False, False)],
    )
    # baseline κ is high (perfect agreement), now κ has disagreements
    assert drift["kappa_baseline"] > drift["kappa_now"]
    assert drift["kappa_drift"] < 0.0


# ---------------------------------------------------------------------------
# kl_overoptimisation_signal
# ---------------------------------------------------------------------------


def test_kl_overoptimisation_detected_when_curves_diverge():
    """Proxy rising while gold falls past peak → overoptimising."""
    proxy = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    gold = [0.5, 0.5, 0.5, 0.4, 0.3, 0.2, 0.1, 0.1]
    s = kl_overoptimisation_signal(proxy, gold)
    assert s["proxy_slope"] > 0
    assert s["gold_slope"] < 0
    assert s["overoptimising"] is True


def test_kl_overoptimisation_clean_when_both_rising():
    proxy = [0.1, 0.2, 0.3, 0.4, 0.5]
    gold = [0.1, 0.2, 0.3, 0.4, 0.5]
    s = kl_overoptimisation_signal(proxy, gold)
    assert s["overoptimising"] is False


def test_kl_overoptimisation_handles_short_curve():
    s = kl_overoptimisation_signal([], [])
    assert s["proxy_slope"] == 0.0
    assert s["gold_slope"] == 0.0
    assert s["overoptimising"] is False


# ---------------------------------------------------------------------------
# CanaryReport.any_red
# ---------------------------------------------------------------------------


def test_canary_clean_when_all_signals_in_bounds():
    r = CanaryReport(
        step=100,
        degenerate_group_fraction=0.2,
        restraint_inflation=0.01,
        kappa_drift=-0.02,
        overoptimising=False,
    )
    assert r.any_red() is False


def test_canary_fires_on_high_degenerate_fraction():
    r = CanaryReport(
        step=100,
        degenerate_group_fraction=0.8,
        restraint_inflation=0.0,
        kappa_drift=0.0,
        overoptimising=False,
    )
    assert r.any_red() is True


def test_canary_fires_on_restraint_inflation():
    r = CanaryReport(
        step=100,
        degenerate_group_fraction=0.1,
        restraint_inflation=0.10,
        kappa_drift=0.0,
        overoptimising=False,
    )
    assert r.any_red() is True


def test_canary_fires_on_large_kappa_drop():
    r = CanaryReport(
        step=100,
        degenerate_group_fraction=0.1,
        restraint_inflation=0.0,
        kappa_drift=-0.20,
        overoptimising=False,
    )
    assert r.any_red() is True


def test_canary_fires_on_overoptimising_flag():
    r = CanaryReport(
        step=100,
        degenerate_group_fraction=0.1,
        restraint_inflation=0.0,
        kappa_drift=0.0,
        overoptimising=True,
    )
    assert r.any_red() is True
