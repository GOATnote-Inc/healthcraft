"""Scoring-strategy registry — extension point for non-additive rules.

The current decision-rule engine (``run_decision_rule`` in
``healthcraft.mcp.tools.compute_tools``) is purely additive: score equals
sum of supplied variable values. That covers ~85% of validated ED rules
because each variable is a pre-computed point contribution.

Two classes of rule the additive engine cannot yet score natively:

1. **Logistic / regression rules** — e.g. full GRACE uses logistic
   regression with continuous coefficients per variable, an intercept,
   and a final sigmoid to produce a probability. Score is not a sum.
2. **Categorical lookup rules** — e.g. Tokyo Guidelines for cholangitis
   severity classify based on combinations of categories, not a numeric
   sum.

This module is the extension point. A strategy is a callable

    (variables: Mapping[str, float], rule: Mapping[str, Any]) -> dict[str, Any]

that returns ``{"score": <number>, "risk_level": <str>, "recommendation":
<str>, ...}``. Rules that opt into a strategy add a ``scorer`` field
naming the registered strategy; the default ``"additive"`` strategy is
implemented here and matches the existing engine bit-for-bit.

Usage:

    from healthcraft.agents_assemble.superpower_decision_rules.scoring_strategies import (
        register_scorer, score_rule,
    )

    @register_scorer("grace_logistic")
    def grace_logistic(variables, rule):
        # ... logistic regression here ...
        return {"score": prob, "risk_level": ..., "recommendation": ...}

The Superpower MCP server checks each rule's ``scorer`` field and routes
to the registered strategy when it isn't ``"additive"``. No core changes
to ``healthcraft.mcp.tools.compute_tools`` are required.

Why this lives in the agents-assemble package: it's a hackathon-time
extension. If the pattern is adopted into HEALTHCRAFT core later, this
file moves; until then it stays scoped to the submission so the core
engine remains unchanged.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any

ScoringStrategy = Callable[[Mapping[str, float], Mapping[str, Any]], dict[str, Any]]

_REGISTRY: dict[str, ScoringStrategy] = {}


def register_scorer(name: str) -> Callable[[ScoringStrategy], ScoringStrategy]:
    """Decorator that registers ``name`` -> strategy in the global registry."""

    def _decorator(fn: ScoringStrategy) -> ScoringStrategy:
        _REGISTRY[name] = fn
        return fn

    return _decorator


def get_scorer(name: str) -> ScoringStrategy | None:
    """Return the registered strategy or ``None`` if absent."""
    return _REGISTRY.get(name)


def known_scorers() -> tuple[str, ...]:
    """Sorted list of registered strategy names; useful for tests + CLI help."""
    return tuple(sorted(_REGISTRY))


# ---------------------------------------------------------------------------
# Built-in: additive (default)
# ---------------------------------------------------------------------------


@register_scorer("additive")
def _additive(variables: Mapping[str, float], rule: Mapping[str, Any]) -> dict[str, Any]:
    """Sum-of-variables strategy — bit-for-bit compatible with
    ``healthcraft.mcp.tools.compute_tools.run_decision_rule``."""
    score: float = 0.0
    variables_used: dict[str, Any] = {}
    for var_def in rule.get("variables") or ():
        var_name = (
            var_def.get("name") if isinstance(var_def, dict) else getattr(var_def, "name", "")
        )
        if not var_name:
            continue
        supplied: Any = None
        for k, v in variables.items():
            if str(k).lower() == str(var_name).lower():
                supplied = v
                break
        if supplied is None:
            variables_used[var_name] = 0
            continue
        score += float(supplied)
        variables_used[var_name] = supplied

    risk_level = "unknown"
    recommendation = "No matching score range found"
    for sr in rule.get("score_ranges") or ():
        lo = sr.get("min_score") if isinstance(sr, dict) else getattr(sr, "min_score", 0)
        hi = sr.get("max_score") if isinstance(sr, dict) else getattr(sr, "max_score", 0)
        if lo <= score <= hi:
            risk_level = (
                sr.get("risk_level")
                if isinstance(sr, dict)
                else getattr(sr, "risk_level", "unknown")
            )
            recommendation = (
                sr.get("recommendation")
                if isinstance(sr, dict)
                else getattr(sr, "recommendation", "")
            )
            break

    score_out: int | float = int(score) if score == int(score) else score
    return {
        "score": score_out,
        "risk_level": risk_level,
        "recommendation": recommendation,
        "variables_used": variables_used,
    }


# ---------------------------------------------------------------------------
# Built-in: meld_na (regression strategy demonstration)
# ---------------------------------------------------------------------------


@register_scorer("meld_na")
def _meld_na(variables: Mapping[str, float], rule: Mapping[str, Any]) -> dict[str, Any]:
    """MELD-Na: regression-based liver-disease severity (UNOS 2016+).

    Formula (per MDCalc / UNOS):

        MELD = round((0.957 * ln(creat) + 0.378 * ln(bili) + 1.12 * ln(INR) + 0.643) * 10)
        MELD-Na = MELD + 1.32 * (137 - Na) - 0.033 * MELD * (137 - Na)

    Caps per UNOS: each lab floored at 1.0 to avoid log domain errors;
    creatinine capped at 4.0 (above = dialysis-equivalent); Na bounded
    to [125, 137]. Final score clamped to [6, 40].
    """

    def _v(name: str, default: float = 1.0) -> float:
        for k, val in variables.items():
            if str(k).lower() == name.lower():
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return default
        return default

    creat = max(1.0, min(4.0, _v("Creatinine (mg/dL)")))
    bili = max(1.0, _v("Bilirubin (mg/dL)"))
    inr = max(1.0, _v("INR"))
    na = max(125.0, min(137.0, _v("Sodium (mmol/L)", default=137.0)))

    meld_raw = 0.957 * math.log(creat) + 0.378 * math.log(bili) + 1.12 * math.log(inr) + 0.643
    meld = max(6, round(meld_raw * 10))
    meld_na = meld + round(1.32 * (137 - na) - 0.033 * meld * (137 - na))
    score = max(6, min(40, meld_na))

    risk_level = "unknown"
    recommendation = "No matching score range found"
    for sr in rule.get("score_ranges") or ():
        lo = sr.get("min_score") if isinstance(sr, dict) else getattr(sr, "min_score", 0)
        hi = sr.get("max_score") if isinstance(sr, dict) else getattr(sr, "max_score", 0)
        if lo <= score <= hi:
            risk_level = (
                sr.get("risk_level")
                if isinstance(sr, dict)
                else getattr(sr, "risk_level", "unknown")
            )
            recommendation = (
                sr.get("recommendation")
                if isinstance(sr, dict)
                else getattr(sr, "recommendation", "")
            )
            break

    return {
        "score": int(score),
        "risk_level": risk_level,
        "recommendation": recommendation,
        "variables_used": {
            "creatinine_capped": creat,
            "bilirubin_floor": bili,
            "inr_floor": inr,
            "sodium_clamped": na,
            "meld_intermediate": meld,
        },
    }


# ---------------------------------------------------------------------------
# Built-in: tokyo_cholangitis (categorical-lookup strategy demonstration)
# ---------------------------------------------------------------------------


_GRADE_III_CRITERIA: tuple[str, ...] = (
    "Cardiovascular dysfunction (pressors required)",
    "Neurologic dysfunction (consciousness)",
    "Respiratory dysfunction (PaO2/FiO2 < 300)",
    "Renal dysfunction (Cr > 2 or oliguria)",
    "Hepatic dysfunction (PT-INR > 1.5)",
    "Hematologic dysfunction (platelets < 100K)",
)
_GRADE_II_CRITERIA: tuple[str, ...] = (
    "WBC < 4 or > 12",
    "Fever >= 39C",
    "Age >= 75",
    "Total bilirubin >= 5",
    "Albumin < 0.7 x lower limit normal",
)


@register_scorer("tokyo_cholangitis")
def _tokyo_cholangitis(variables: Mapping[str, float], rule: Mapping[str, Any]) -> dict[str, Any]:
    """Tokyo Guidelines TG18 severity grading for acute cholangitis.

    Categorical decision tree:

    - Any Grade III (organ-dysfunction) criterion present -> Grade III (severe).
    - Else >=2 Grade II criteria -> Grade II (moderate).
    - Else -> Grade I (mild).

    Encoded as a numeric score (1=mild, 2=moderate, 3=severe) so the
    downstream consumers (CDS card, audit log) keep a uniform shape with
    additive rules.
    """

    def _is_set(name: str) -> bool:
        for k, val in variables.items():
            if str(k).lower() == name.lower():
                try:
                    return float(val) >= 1.0
                except (TypeError, ValueError):
                    return False
        return False

    g3_present = [c for c in _GRADE_III_CRITERIA if _is_set(c)]
    g2_present = [c for c in _GRADE_II_CRITERIA if _is_set(c)]

    if g3_present:
        score, risk_level = 3, "high"
        rationale = "Grade III (severe): organ dysfunction — " + ", ".join(g3_present)
    elif len(g2_present) >= 2:
        score, risk_level = 2, "moderate"
        rationale = f"Grade II (moderate): {len(g2_present)} non-organ criteria"
    else:
        score, risk_level = 1, "low"
        rationale = "Grade I (mild): no organ dysfunction; <2 Grade-II criteria"

    recommendation = ""
    for sr in rule.get("score_ranges") or ():
        lo = sr.get("min_score") if isinstance(sr, dict) else getattr(sr, "min_score", 0)
        hi = sr.get("max_score") if isinstance(sr, dict) else getattr(sr, "max_score", 0)
        if lo <= score <= hi:
            recommendation = (
                sr.get("recommendation")
                if isinstance(sr, dict)
                else getattr(sr, "recommendation", "")
            )
            break

    return {
        "score": score,
        "risk_level": risk_level,
        "recommendation": recommendation,
        "variables_used": {
            "grade3_criteria_present": list(g3_present),
            "grade2_criteria_count": len(g2_present),
            "rationale": rationale,
        },
    }


# ---------------------------------------------------------------------------
# Public dispatch
# ---------------------------------------------------------------------------


def score_rule(variables: Mapping[str, float], rule: Mapping[str, Any]) -> dict[str, Any]:
    """Dispatch a rule's scoring to its registered strategy.

    Falls back to ``additive`` when ``rule.scorer`` is missing or unknown
    so existing rule manifests work unchanged.
    """
    scorer_name = "additive"
    if isinstance(rule, dict):
        scorer_name = str(rule.get("scorer") or "additive")
    elif hasattr(rule, "scorer"):
        scorer_name = str(getattr(rule, "scorer", None) or "additive")

    strategy = _REGISTRY.get(scorer_name)
    if strategy is None:
        strategy = _REGISTRY["additive"]
    return strategy(variables, rule)
