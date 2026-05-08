"""Coverage for the scoring-strategy registry.

The default ``additive`` strategy must produce the same outputs as
``healthcraft.mcp.tools.compute_tools.run_decision_rule`` for every
bundled rule. New strategies (e.g. ``grace_logistic``) can be registered
without modifying any existing rules.
"""

from __future__ import annotations

import random
from dataclasses import asdict
from typing import Any

import pytest

from healthcraft.agents_assemble.superpower_decision_rules.scoring_strategies import (
    get_scorer,
    known_scorers,
    register_scorer,
    score_rule,
)
from healthcraft.entities.decision_rules import load_decision_rules
from healthcraft.mcp.tools.compute_tools import run_decision_rule
from healthcraft.world.state import WorldState


@pytest.fixture(scope="module")
def world() -> WorldState:
    w = WorldState()
    for rid, r in load_decision_rules().items():
        w.put_entity("decision_rule", rid, r)
    return w


@pytest.fixture(scope="module")
def all_rules() -> list[dict[str, Any]]:
    return [asdict(r) for r in load_decision_rules().values()]


def test_default_strategy_is_additive() -> None:
    assert "additive" in known_scorers()
    assert get_scorer("additive") is not None


def test_score_rule_falls_back_to_additive_when_scorer_unknown(
    all_rules: list[dict[str, Any]],
) -> None:
    rule = dict(all_rules[0])
    rule["scorer"] = "this-strategy-does-not-exist"
    out = score_rule({}, rule)
    assert "score" in out
    assert "risk_level" in out


def test_additive_strategy_matches_engine_for_random_inputs(
    world: WorldState, all_rules: list[dict[str, Any]]
) -> None:
    """For every bundled rule, ``score_rule`` (default additive strategy)
    must produce the same score and risk_level as ``run_decision_rule``."""
    rng = random.Random(42)
    for rule in all_rules:
        variables: dict[str, float] = {}
        for v in rule["variables"]:
            scoring = v.get("scoring")
            if isinstance(scoring, dict) and scoring:
                variables[v["name"]] = float(rng.choice(list(scoring.keys())))
                continue
            lo, hi = float(v["min_value"]), float(v["max_value"])
            if lo.is_integer() and hi.is_integer():
                variables[v["name"]] = float(rng.randint(int(lo), int(hi)))
            else:
                variables[v["name"]] = round(rng.uniform(lo, hi) * 2) / 2

        engine = run_decision_rule(world, {"rule_name": rule["name"], "variables": variables})
        strategy = score_rule(variables, rule)
        assert engine["status"] == "ok", rule["name"]
        assert engine["data"]["score"] == strategy["score"], rule["name"]
        assert engine["data"]["risk_level"] == strategy["risk_level"], rule["name"]


def test_register_scorer_round_trips() -> None:
    @register_scorer("test_constant_high")
    def _constant_high(_variables, _rule):
        return {"score": 999, "risk_level": "high", "recommendation": "test"}

    rule = {"name": "T", "variables": [], "score_ranges": [], "scorer": "test_constant_high"}
    out = score_rule({"x": 1}, rule)
    assert out["score"] == 999
    assert out["risk_level"] == "high"
    assert "test_constant_high" in known_scorers()


def test_rule_count_supports_breadth_claim() -> None:
    """Sanity check: the bundled library is large enough to make the
    'broad ED coverage' claim credible without LLM-side hand-waving."""
    rules = load_decision_rules()
    assert len(rules) >= 45, f"expected >=45 rules, got {len(rules)}"
