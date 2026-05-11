"""Coverage-matrix invariants — rules named must exist; gaps must be real gaps.

The matrix at ``configs/agents_assemble/coverage_matrix.yaml`` is the
source of truth for "which rules apply to which clinical context." If a
rule is renamed in the library or added without updating the matrix,
these tests fail. If a "gap" entry names a rule that's actually
bundled, the gap is fake and the test fails.

Also exercises the parallel-fan-out shape: every rule listed for a
complaint is independent (same Bundle in -> same score out), so a
downstream A2A agent can submit them concurrently.
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import asdict

import pytest

from healthcraft.agents_assemble.coverage import (
    CoverageMatrix,
    _complaint_slug,
)
from healthcraft.agents_assemble.superpower_decision_rules.scoring_strategies import (
    score_rule,
)
from healthcraft.entities.decision_rules import load_decision_rules


@pytest.fixture(scope="module")
def matrix() -> CoverageMatrix:
    return CoverageMatrix.load()


@pytest.fixture(scope="module")
def bundled_names() -> set[str]:
    return {r.name for r in load_decision_rules().values()}


# ---------------------------------------------------------------------------
# Loader sanity
# ---------------------------------------------------------------------------


def test_matrix_loads_with_expected_top_level_sections(matrix: CoverageMatrix) -> None:
    assert matrix.version == 1
    assert matrix.library_size >= 100
    assert matrix.complaints, "expected non-empty chief_complaints"
    assert matrix.organ_systems, "expected non-empty organ_systems"
    assert matrix.age_bands, "expected non-empty age_bands"


def test_matrix_advertises_actual_library_size(matrix: CoverageMatrix) -> None:
    """library_size in the YAML must match the count actually loadable. If
    new rules are added the matrix author must update the field."""
    assert matrix.library_size == len(load_decision_rules()), (
        "coverage_matrix.yaml library_size is stale; sync with load_decision_rules()"
    )


# ---------------------------------------------------------------------------
# Every named rule resolves to a bundled rule
# ---------------------------------------------------------------------------


def test_every_complaint_rule_resolves_to_a_bundled_rule(
    matrix: CoverageMatrix, bundled_names: set[str]
) -> None:
    unresolved: list[tuple[str, str]] = []
    for slug, c in matrix.complaints.items():
        for r in c.primary + c.secondary:
            if r not in bundled_names:
                unresolved.append((slug, r))
        for q, qrules in c.qualifiers.items():
            for r in qrules:
                if r not in bundled_names:
                    unresolved.append((f"{slug}.{q}", r))
    assert not unresolved, f"complaints reference unbundled rules: {unresolved[:5]}"


def test_every_organ_system_rule_resolves(matrix: CoverageMatrix, bundled_names: set[str]) -> None:
    unresolved: list[tuple[str, str]] = []
    for system, rules in matrix.organ_systems.items():
        for r in rules:
            if r not in bundled_names:
                unresolved.append((system, r))
    assert not unresolved, f"organ_systems reference unbundled rules: {unresolved[:5]}"


def test_every_age_band_rule_resolves(matrix: CoverageMatrix, bundled_names: set[str]) -> None:
    unresolved: list[tuple[str, str]] = []
    for band, rules in matrix.age_bands.items():
        for r in rules:
            if r == "ALL_REMAINING":
                continue
            if r not in bundled_names:
                unresolved.append((band, r))
    assert not unresolved, f"age_bands reference unbundled rules: {unresolved[:5]}"


# ---------------------------------------------------------------------------
# Gap entries must be real gaps
# ---------------------------------------------------------------------------


def test_gap_entries_dont_name_bundled_rules(
    matrix: CoverageMatrix, bundled_names: set[str]
) -> None:
    """Each ``gaps[*].candidates_for_future`` rule name MUST NOT be in the
    bundled library. Otherwise the matrix is lying about a gap."""
    leaks: list[tuple[str, str]] = []
    for entry in matrix.gaps:
        ctx = entry.get("context", "?")
        for cand in entry.get("candidates_for_future") or []:
            if cand in bundled_names:
                leaks.append((ctx, cand))
    assert not leaks, f"gap entries name bundled rules: {leaks}"


# ---------------------------------------------------------------------------
# Query API
# ---------------------------------------------------------------------------


def test_complaint_lookup_by_slug(matrix: CoverageMatrix) -> None:
    rules = matrix.rules_for_complaint("chest_pain")
    assert "HEART Score" in rules
    assert rules.index("HEART Score") < rules.index("Marburg Heart Score"), (
        "primary rules must rank above secondary"
    )


def test_complaint_lookup_with_qualifier_appends_branch(matrix: CoverageMatrix) -> None:
    base = matrix.rules_for_complaint("chest_pain")
    with_q = matrix.rules_for_complaint("chest_pain", qualifier="pleuritic_or_dyspnea")
    assert set(base) <= set(with_q), "qualifier rules must be additive over primary/secondary"
    assert "Wells Criteria for PE" in with_q


def test_complaint_lookup_handles_freetext(matrix: CoverageMatrix) -> None:
    rules = matrix.rules_for_complaint("chest pain")
    assert "HEART Score" in rules


def test_complaint_lookup_fuzzy_falls_back_on_token_overlap(matrix: CoverageMatrix) -> None:
    rules = matrix.rules_for_complaint("acute pleuritic chest pain after a long flight")
    # Should fuzzy-match either chest_pain or pediatric_respiratory_distress; the
    # returned set should at minimum mention HEART or Wells.
    assert any(r in {"HEART Score", "Wells Criteria for PE"} for r in rules)


def test_organ_system_lookup_returns_ranked_list(matrix: CoverageMatrix) -> None:
    cardio = matrix.rules_for_organ("cardiovascular")
    assert cardio[0] == "HEART Score"
    assert "CHA2DS2-VASc" in cardio


def test_age_band_lookup_returns_ranked_list(matrix: CoverageMatrix) -> None:
    peds = matrix.rules_for_age_band("pediatric")
    assert "APGAR" in peds
    assert "PEWS" in peds
    assert "PECARN Head CT" in peds


# ---------------------------------------------------------------------------
# Slug helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("chest pain", "chest_pain"),
        ("Chest Pain!", "chest_pain"),
        ("PE / DVT workup", "pe_dvt_workup"),
        ("AFib  with  spaces ", "afib_with_spaces"),
    ],
)
def test_complaint_slug_normalizes(raw: str, expected: str) -> None:
    assert _complaint_slug(raw) == expected


# ---------------------------------------------------------------------------
# Parallel fan-out — pivotal for the "agent teams" claim
# ---------------------------------------------------------------------------


def test_rules_for_a_complaint_are_independent_under_parallel_fanout(
    matrix: CoverageMatrix,
) -> None:
    """Pin the parallel-execution claim: every rule listed for a complaint
    can be scored concurrently against the same Bundle, with the same per-
    rule outputs as the serial baseline. This is the property a downstream
    A2A agent relies on when fanning out N scorers."""
    rules_lib = {r.name: asdict(r) for r in load_decision_rules().values()}
    candidate_names = matrix.rules_for_complaint("chest_pain", qualifier="pleuritic_or_dyspnea")
    candidate_rules = [rules_lib[name] for name in candidate_names if name in rules_lib]
    assert len(candidate_rules) >= 4, "expected several rules for chest_pain+pleuritic"

    # Use a representative variable set the rules share by name.
    variables = {
        "Age": 1,
        "Risk factors": 1,
        "Troponin": 1,
        "ECG": 1,
        "History": 1,
        "Heart rate > 100": 1.5,
        "Hemoptysis": 1,
        "Malignancy": 0,
        "Previous PE or DVT": 0,
        "Immobilization or surgery in past 4 weeks": 0,
        "PE is #1 diagnosis or equally likely": 3,
        "Clinical signs/symptoms of DVT": 0,
    }

    serial = [score_rule(variables, r) for r in candidate_rules]

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        parallel = list(pool.map(lambda r: score_rule(variables, r), candidate_rules))

    for s, p, name in zip(serial, parallel, candidate_names):
        assert s["score"] == p["score"], f"score for {name} differs under parallel execution"
        assert s["risk_level"] == p["risk_level"], (
            f"risk_level for {name} differs under parallel execution"
        )
