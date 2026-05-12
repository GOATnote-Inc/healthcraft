"""MCP Superpower server — ED Decision Rules.

Exposes three tools to a Prompt Opinion / MCP host:

- ``applyDecisionRule`` — top-level Superpower. Accepts a SHARP envelope
  with a FHIR Bundle and a rule name; uses the variable extractor to
  populate rule inputs, then runs HEALTHCRAFT's deterministic
  ``run_decision_rule`` handler. Returns score + risk + recommendation.
- ``getProtocolDetails`` — pass-through to HEALTHCRAFT's protocol read tool.
- ``getReferenceArticle`` — pass-through to HEALTHCRAFT's reference tool.

The server is a lightweight wrapper: it does not own world state. Callers
provide a ``WorldState`` (typically the Prompt Opinion sandbox) when
constructing the server. For local tests a fresh seeded world is used.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from healthcraft.agents_assemble.superpower_decision_rules.fhir_extractor import (
    FhirVariableExtractor,
)
from healthcraft.agents_assemble.superpower_decision_rules.rule_version import (
    rule_version,
    short_version,
)
from healthcraft.agents_assemble.superpower_decision_rules.scoring_strategies import (
    score_rule,
)
from healthcraft.agents_assemble.superpower_decision_rules.sharp import (
    SharpEnvelope,
    bundle_hash,
    reply_envelope,
)
from healthcraft.mcp.tools.compute_tools import run_decision_rule
from healthcraft.mcp.tools.read_tools import get_protocol_details, get_reference_article
from healthcraft.world.state import WorldState

logger = logging.getLogger("agents_assemble.superpower")


SUPERPOWER_TOOLS: tuple[str, ...] = (
    "applyDecisionRule",
    "getProtocolDetails",
    "getReferenceArticle",
)


class SuperpowerServer:
    """Thin MCP-compatible dispatcher over HEALTHCRAFT decision-rule tooling."""

    def __init__(
        self,
        world: WorldState,
        extractor: FhirVariableExtractor | None = None,
    ) -> None:
        self._world = world
        self._extractor = extractor or FhirVariableExtractor()

    @property
    def available_tools(self) -> tuple[str, ...]:
        return SUPERPOWER_TOOLS

    def call(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a tool call. ``params`` is the SHARP envelope payload."""
        envelope = SharpEnvelope.from_dict(params)

        if tool_name == "applyDecisionRule":
            return self._apply_decision_rule(envelope, params)
        if tool_name == "getProtocolDetails":
            payload = get_protocol_details(self._world, params)
            return reply_envelope(envelope, payload, tool_name=tool_name)
        if tool_name == "getReferenceArticle":
            payload = get_reference_article(self._world, params)
            return reply_envelope(envelope, payload, tool_name=tool_name)
        return reply_envelope(
            envelope,
            {"status": "error", "code": "unknown_tool", "message": f"Unknown tool: {tool_name}"},
            tool_name=tool_name,
        )

    # ------------------------------------------------------------------
    # applyDecisionRule
    # ------------------------------------------------------------------

    def _apply_decision_rule(
        self,
        envelope: SharpEnvelope,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        rule_name = params.get("ruleName") or params.get("rule_name")
        if not rule_name:
            return reply_envelope(
                envelope,
                {"status": "error", "code": "missing_param", "message": "ruleName is required"},
                tool_name="applyDecisionRule",
            )

        rule = _lookup_rule(self._world, rule_name)
        if rule is None:
            return reply_envelope(
                envelope,
                {
                    "status": "error",
                    "code": "rule_not_found",
                    "message": f"Decision rule '{rule_name}' not loaded in world state",
                },
                tool_name="applyDecisionRule",
                trace_detail={"ruleName": rule_name},
            )

        rule_dict = asdict(rule) if hasattr(rule, "__dataclass_fields__") else dict(rule)
        rule_variables = list(rule_dict.get("variables") or [])

        # Allow callers to pre-supply variables; extractor fills the gaps.
        # Match supplied keys case- + space- + underscore-insensitively so
        # an LLM agent that emits ``risk_factors`` matches the rule's
        # canonical ``Risk factors``. Without this normalization, a high-risk
        # patient (troponin elevation, positive history, age >= 65) would
        # silently score 0 and recommend discharge — a clinically dangerous
        # false-negative. See PR notes; spotted in demo dry-run with Tamera
        # (46 F) on 2026-05-11.
        import re

        # Clinical synonyms — common interchangeable abbreviations in EM
        # documentation. EKG (German Elektrokardiogramm) and ECG (English
        # Electrocardiogram) name the same study; agents emit either.
        _CLINICAL_ALIASES = {
            "ekg": "ecg",
            "electrocardiogram": "ecg",
            "creat": "creatinine",
            "scr": "creatinine",
            "spo2": "saturation",
            "sat": "saturation",
            "bp": "bloodpressure",
            "sbp": "systolicbloodpressure",
            "dbp": "diastolicbloodpressure",
            "hr": "heartrate",
            "rr": "respiratoryrate",
            "temp": "temperature",
            "wbc": "whitebloodcells",
            "plt": "platelets",
            "hgb": "hemoglobin",
            "hb": "hemoglobin",
        }

        def _norm_key(k: str) -> str:
            stripped = re.sub(r"[\s_\-]+", "", str(k)).lower()
            return _CLINICAL_ALIASES.get(stripped, stripped)

        supplied_raw = dict(params.get("variables") or {})
        supplied_lookup = {_norm_key(k): v for k, v in supplied_raw.items()}
        extraction = self._extractor.extract(rule_name, rule_variables, envelope.bundle)
        merged_variables: dict[str, float | int] = {}
        for name, value in extraction.variables.items():
            norm = _norm_key(name)
            if name in supplied_raw:
                merged_variables[name] = supplied_raw[name]
            elif norm in supplied_lookup:
                merged_variables[name] = supplied_lookup[norm]
            elif value is not None:
                merged_variables[name] = value

        # Dispatch via the scoring-strategy registry. ``additive`` (default)
        # is bit-for-bit equivalent to ``run_decision_rule``; non-additive
        # rules (``meld_na``, ``tokyo_cholangitis``, future logistic /
        # categorical strategies) supply their own ``scorer`` field and are
        # routed accordingly.
        scorer_name = rule_dict.get("scorer") or "additive"
        if scorer_name == "additive":
            compute_result = run_decision_rule(
                self._world, {"rule_name": rule_name, "variables": merged_variables}
            )
            data = compute_result.get("data") if compute_result.get("status") == "ok" else None
            err = compute_result if compute_result.get("status") == "error" else None
        else:
            data = score_rule(merged_variables, rule_dict)
            err = None

        payload = {
            "status": "error" if err else "ok",
            "rule": rule_dict.get("name", rule_name),
            "ruleVersion": rule_version(rule),
            "ruleVersionShort": short_version(rule),
            "scorer": scorer_name,
            "result": data,
            "extraction": {
                "method": extraction.method,
                "rationale": extraction.rationale,
                "missing": extraction.missing,
                "supplied": list(supplied_raw.keys()),
            },
        }
        if err:
            payload["error"] = {
                "code": err.get("code"),
                "message": err.get("message"),
            }

        return reply_envelope(
            envelope,
            payload,
            tool_name="applyDecisionRule",
            trace_detail={
                "ruleName": rule_name,
                "ruleVersion": rule_version(rule),
                "extractionMethod": extraction.method,
                "missingVariables": extraction.missing,
                "bundleSha256": bundle_hash(envelope.bundle),
            },
        )


def _lookup_rule(world: WorldState, rule_name: str) -> Any | None:
    rules = world.list_entities("decision_rule")
    for rule in rules.values():
        name = getattr(rule, "name", None) or (rule.get("name") if isinstance(rule, dict) else "")
        if name and name.lower() == rule_name.lower():
            return rule
    return None


def create_superpower(
    world: WorldState,
    extractor: FhirVariableExtractor | None = None,
) -> SuperpowerServer:
    """Factory mirroring HEALTHCRAFT's ``create_server`` convention."""
    return SuperpowerServer(world, extractor=extractor)
