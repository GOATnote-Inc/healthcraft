"""Property-based / fuzz invariants for the ED Decision Rules Superpower.

Curated clinical scenarios prove the agent works on a few cases. The
hackathon claim, however, is that the Superpower handles the *full
variable space of every rule it exposes*. These tests assert the
properties that must hold across every rule and every randomized input
the rule's manifest declares legal.

Invariants checked, for **all 12 bundled decision rules**:

1. **Score arithmetic** — returned score equals the sum of supplied
   variable values. This is the Corecraft Eq. 1 contract.
2. **Risk-level lookup** — returned risk level is the one whose
   ``score_ranges`` entry contains the score (no off-by-one).
3. **Idempotence** — same variables in -> same score/risk out, regardless
   of variable insertion order.
4. **Monotonicity** — increasing any single variable cannot decrease
   the score (the rule scoring is additive by construction).
5. **Risk-level vocabulary** — every returned risk level appears in
   the rule's declared ``score_ranges`` (no "unknown" leaks for legal
   inputs).
"""

from __future__ import annotations

import random
from dataclasses import asdict
from typing import Any

import pytest

from healthcraft.entities.decision_rules import load_decision_rules
from healthcraft.mcp.tools.compute_tools import run_decision_rule
from healthcraft.world.state import WorldState

N_TRIALS_PER_RULE = 75
SEED = 42


@pytest.fixture(scope="module")
def world() -> WorldState:
    w = WorldState()
    for rid, r in load_decision_rules().items():
        w.put_entity("decision_rule", rid, r)
    return w


@pytest.fixture(scope="module")
def all_rules() -> list[dict[str, Any]]:
    return [asdict(r) for r in load_decision_rules().values()]


def _random_assignment(rule: dict[str, Any], rng: random.Random) -> dict[str, float]:
    out: dict[str, float] = {}
    for v in rule["variables"]:
        lo, hi = float(v["min_value"]), float(v["max_value"])
        if lo.is_integer() and hi.is_integer() and (hi - lo) <= 5:
            out[v["name"]] = float(rng.choice([int(lo), int(hi)]))
        else:
            out[v["name"]] = round(rng.uniform(lo, hi) * 2) / 2
    return out


def _expected_risk(rule: dict[str, Any], score: float) -> str:
    for sr in rule["score_ranges"]:
        if sr["min_score"] <= score <= sr["max_score"]:
            return sr["risk_level"]
    return "unknown"


@pytest.mark.parametrize("trial", range(N_TRIALS_PER_RULE))
def test_score_arithmetic_and_risk_lookup_hold_for_all_rules(
    world: WorldState, all_rules: list[dict[str, Any]], trial: int
) -> None:
    rng = random.Random(SEED + trial)
    for rule in all_rules:
        variables = _random_assignment(rule, rng)
        result = run_decision_rule(world, {"rule_name": rule["name"], "variables": variables})
        assert result["status"] == "ok", (rule["name"], result)
        data = result["data"]
        expected_score = sum(variables.values())
        assert abs(data["score"] - expected_score) < 1e-6, (rule["name"], data, variables)
        assert data["risk_level"] == _expected_risk(rule, expected_score), (
            rule["name"],
            data,
            variables,
        )


def test_score_is_idempotent_to_variable_insertion_order(
    world: WorldState, all_rules: list[dict[str, Any]]
) -> None:
    rng = random.Random(SEED)
    for rule in all_rules:
        variables = _random_assignment(rule, rng)
        # Two permutations must yield byte-identical score+risk.
        keys = list(variables.keys())
        rng.shuffle(keys)
        permuted = {k: variables[k] for k in keys}

        a = run_decision_rule(world, {"rule_name": rule["name"], "variables": variables})
        b = run_decision_rule(world, {"rule_name": rule["name"], "variables": permuted})
        assert a["data"]["score"] == b["data"]["score"], rule["name"]
        assert a["data"]["risk_level"] == b["data"]["risk_level"], rule["name"]


def test_score_is_monotonic_in_each_variable(
    world: WorldState, all_rules: list[dict[str, Any]]
) -> None:
    """Increasing one variable's value (within its declared range) must not
    decrease the total score. Holds for every additive rule by construction."""
    rng = random.Random(SEED + 7)
    for rule in all_rules:
        baseline = _random_assignment(rule, rng)
        baseline_result = run_decision_rule(
            world, {"rule_name": rule["name"], "variables": baseline}
        )
        baseline_score = baseline_result["data"]["score"]
        for var in rule["variables"]:
            name = var["name"]
            hi = float(var["max_value"])
            bumped = dict(baseline)
            bumped[name] = max(bumped[name], hi)  # never decrease
            bumped_result = run_decision_rule(
                world, {"rule_name": rule["name"], "variables": bumped}
            )
            assert bumped_result["data"]["score"] >= baseline_score - 1e-6, (
                rule["name"],
                name,
                baseline,
                bumped,
            )


def test_risk_level_is_always_in_declared_vocabulary(
    world: WorldState, all_rules: list[dict[str, Any]]
) -> None:
    rng = random.Random(SEED + 13)
    for rule in all_rules:
        declared = {sr["risk_level"] for sr in rule["score_ranges"]}
        for _ in range(20):
            variables = _random_assignment(rule, rng)
            result = run_decision_rule(world, {"rule_name": rule["name"], "variables": variables})
            risk = result["data"]["risk_level"]
            assert risk in declared, (rule["name"], risk, variables)
