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
            # Compose 3 closest-match suggestions so the agent can self-correct.
            all_names = []
            for r in self._world.list_entities("decision_rule").values():
                n = getattr(r, "name", None) or (r.get("name") if isinstance(r, dict) else "")
                if n:
                    all_names.append(n)
            suggestions = _closest_rule_names(rule_name, all_names, n=3)
            return reply_envelope(
                envelope,
                {
                    "status": "error",
                    # Legacy top-level keys preserved for backward compat.
                    "code": "rule_not_found",
                    "message": (
                        f"Decision rule '{rule_name}' not found. "
                        f"Closest matches: {', '.join(suggestions) if suggestions else '(none)'}"
                    ),
                    # New structured error object carrying suggestions.
                    "error": {
                        "code": "rule_not_found",
                        "message": (
                            f"Decision rule '{rule_name}' not found. "
                            f"Closest matches: {', '.join(suggestions) if suggestions else '(none)'}"
                        ),
                        "suggestions": suggestions,
                    },
                },
                tool_name="applyDecisionRule",
                trace_detail={"ruleName": rule_name, "suggestions": suggestions},
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

        # Coerce natural-language variable values to integers. An LLM agent
        # reading FHIR Conditions sees "coronary artery disease" not "2";
        # without coercion, the additive scorer multiplies string by weight
        # and raises. Per-rule semantic synonym tables map common natural-
        # language descriptors to the canonical integer encoding.
        def _coerce(rule: str, var: str, value: Any) -> Any:
            if value is None:
                return None
            if isinstance(value, (int, float)):
                return value
            if isinstance(value, bool):
                return int(value)
            text = str(value).strip().lower()
            # Try direct int parse first ("2", "0").
            try:
                return int(text)
            except ValueError:
                pass
            try:
                return float(text)
            except ValueError:
                pass
            # Per-rule semantic mapping. Keys are the rule's canonical
            # variable name lowercased; values map descriptor -> int.
            heart_history = {
                "highly suspicious": 2, "high": 2, "definite": 2, "classic": 2,
                "typical": 2, "anginal": 2, "cardiac": 2,
                "moderately suspicious": 1, "moderate": 1,
                "atypical with concerning features": 1, "concerning": 1,
                "atypical": 1, "intermediate": 1,
                "slightly suspicious": 0, "low": 0, "non-suspicious": 0,
                "non-cardiac": 0, "musculoskeletal": 0, "pleuritic": 0,
                "reproducible": 0, "no": 0, "none": 0,
            }
            heart_ecg = {
                "significant st depression": 2, "st elevation": 2,
                "st-segment depression": 2, "st depression": 2,
                "non-specific repolarization": 1, "non-specific st-t": 1,
                "non-specific st-t wave changes": 1, "non-specific st changes": 1,
                "non-specific repolarisation disturbance": 1,
                "lbbb": 1, "lvh": 1, "abnormal": 1, "t-wave inversion": 1,
                "normal": 0, "no changes": 0, "unremarkable": 0,
            }
            heart_age = {"<45": 0, "45-64": 1, ">=65": 2, "65+": 2, "elderly": 2}
            heart_risk = {
                "none": 0, "no risk factors": 0,
                "1-2 risk factors": 1, "one risk factor": 1, "two risk factors": 1,
                ">=3 risk factors": 2, "three or more": 2,
                "history of atherosclerotic disease": 2,
                "coronary artery disease": 2, "coronary disease": 2,
                "cad": 2, "atherosclerosis": 2, "prior mi": 2, "prior stent": 2,
                "prior cabg": 2,
            }
            heart_troponin = {
                "normal": 0, "<= normal limit": 0,
                "1-3x normal limit": 1, "1-3x uln": 1, "mildly elevated": 1,
                ">3x normal limit": 2, ">3x uln": 2, "markedly elevated": 2,
                "elevated": 1,  # default elevated->1 (conservative)
            }
            mappings = {
                "HEART Score": {
                    "history": heart_history,
                    "ecg": heart_ecg,
                    "age": heart_age,
                    "risk factors": heart_risk,
                    "troponin": heart_troponin,
                },
            }
            rule_map = mappings.get(rule, {})
            var_map = rule_map.get(var.lower(), {})
            if text in var_map:
                return var_map[text]
            # Partial-match fallback — useful when LLM emits a phrase that
            # contains the key word, e.g. "history of CAD on stent" -> "cad".
            for k, v in var_map.items():
                if k in text:
                    return v
            return value  # unmappable — pass through; scorer will error visibly

        merged_variables: dict[str, float | int] = {}
        for name, value in extraction.variables.items():
            norm = _norm_key(name)
            raw_val = None
            if name in supplied_raw:
                raw_val = supplied_raw[name]
            elif norm in supplied_lookup:
                raw_val = supplied_lookup[norm]
            else:
                # Substring fallback: an LLM agent that sees the canonical
                # "Eye opening response" may pass just "eye"; match if the
                # supplied normalized key is a substring of the canonical
                # normalized name (or vice versa). Length floor of 2 chars
                # prevents stray single-letter collisions.
                substring_hit = None
                for sk, sv in supplied_lookup.items():
                    if len(sk) >= 2 and (sk in norm or norm in sk):
                        substring_hit = sv
                        break
                if substring_hit is not None:
                    raw_val = substring_hit
                elif value is not None:
                    raw_val = value
            if raw_val is None:
                continue
            merged_variables[name] = _coerce(rule_name, name, raw_val)

        # F1: Refuse to score a rule when zero variables resolved — silently
        # producing 0/N is clinically dangerous (Glasgow Coma Scale's minimum
        # is 3, not 0; HEART score 0 implies thorough negative workup, not
        # missing data). Surface as missing_variables status with the list
        # of expected variable names so the caller can supply them.
        if not merged_variables and rule_variables:
            expected_names = [
                v.get("name") if isinstance(v, dict) else getattr(v, "name", str(v))
                for v in rule_variables
            ]
            return reply_envelope(
                envelope,
                {
                    "status": "error",
                    "rule": rule_dict.get("name", rule_name),
                    "ruleVersion": rule_version(rule),
                    "error": {
                        "code": "missing_variables",
                        "message": (
                            f"Cannot score '{rule_dict.get('name', rule_name)}' — "
                            f"no variables supplied and FHIR extractor found none. "
                            f"Required: {', '.join(filter(None, expected_names))}"
                        ),
                        "required": [n for n in expected_names if n],
                    },
                    "extraction": {
                        "method": extraction.method,
                        "missing": extraction.missing,
                        "supplied": list(supplied_raw.keys()),
                    },
                },
                tool_name="applyDecisionRule",
                trace_detail={"ruleName": rule_name, "missingVariables": expected_names},
            )

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

        # F3: Annotate the result with an evidence note when the score falls
        # in a tier where current literature actively contests the original
        # recommendation. Without this, agents cite our recommendation as
        # authoritative when downstream clinicians know it's under revision.
        evidence_note = _evidence_note_for(rule_dict.get("name", rule_name), data)
        if evidence_note and isinstance(data, dict):
            data = dict(data)
            data["evidence_note"] = evidence_note

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


# Common aliases — short forms and punctuation drops that an LLM agent or
# clinician would naturally type. Maps lowercased input -> canonical rule
# name fragment that matches uniquely against the loaded rules.
_RULE_ALIASES = {
    "heart": "HEART Score",
    "wells pe": "Wells Criteria for PE",
    "wells dvt": "Wells Criteria for DVT",
    "hasbled": "HAS-BLED Score",
    "has bled": "HAS-BLED Score",
    "has-bled": "HAS-BLED Score",
    "curb65": "CURB-65",
    "curb 65": "CURB-65",
    "qsofa": "qSOFA",
    "cha2ds2": "CHA2DS2-VASc",
    "chads2": "CHADS2",
    "glasgow coma": "Glasgow Coma Scale",
    "gcs": "Glasgow Coma Scale",
    "news 2": "NEWS2",
    "perc": "PERC Rule",
    "abcd2": "ABCD2 Score",
    "alvarado": "Alvarado Score",
    "meld na": "MELD-Na",
    "meld": "MELD",
    "san francisco syncope": "San Francisco Syncope Rule",
    "sirs": "SIRS Criteria",
}


def _norm_name(text: str) -> str:
    """Aggressive normalization for fuzzy rule-name matching."""
    import re

    return re.sub(r"[^a-z0-9]", "", text.lower())


def _closest_rule_names(rule_name: str, all_names: list[str], n: int = 3) -> list[str]:
    """Return the ``n`` closest canonical names by difflib ratio."""
    import difflib

    return difflib.get_close_matches(rule_name, all_names, n=n, cutoff=0.0)


def _evidence_note_for(rule_name: str, result_data: Any) -> str | None:
    """Return a citation-grade note when current literature is in active
    tension with the bundled recommendation. Returns ``None`` if the result
    is within the rule's well-established consensus tier."""
    if not isinstance(result_data, dict):
        return None
    score = result_data.get("score")
    if rule_name == "HEART Score" and isinstance(score, (int, float)) and 1 <= score <= 3:
        return (
            "Recent evidence — 2025 single-center validation (Cureus, PMC12151265) "
            "found 4.4% 30-day MACE at HEART<=3, exceeding the 2% ACEP "
            "safe-discharge threshold. Some institutions are recalibrating "
            "the low-risk cutoff to <=2. Consider serial troponin or shared "
            "decision-making for HEART 2-3."
        )
    return None


def list_rule_schemas(world: WorldState) -> dict[str, Any]:
    """Return schemas for every loaded rule — used by the getRuleSchema tool."""
    out: dict[str, Any] = {}
    for r in world.list_entities("decision_rule").values():
        rule_dict = asdict(r) if hasattr(r, "__dataclass_fields__") else dict(r)
        name = rule_dict.get("name")
        if not name:
            continue
        out[name] = {
            "name": name,
            "fullName": rule_dict.get("full_name", ""),
            "category": rule_dict.get("category", ""),
            "description": rule_dict.get("description", ""),
            "scorer": rule_dict.get("scorer", "additive"),
            "evidenceLevel": rule_dict.get("evidence_level", ""),
            "url": rule_dict.get("url", ""),
            "variables": [
                {"name": v} if isinstance(v, str) else dict(v) if hasattr(v, "items") else {"name": str(v)}
                for v in (rule_dict.get("variables") or [])
            ],
            "scoreRanges": list(rule_dict.get("score_ranges") or []),
        }
    return out


def _lookup_rule(world: WorldState, rule_name: str) -> Any | None:
    """Resolve a rule by exact, case-insensitive, alias, or fuzzy match.

    Resolution order (each step short-circuits on hit):

    1. Case-insensitive equality on canonical name.
    2. Alias-table lookup (lowercased, normalized).
    3. Normalized-string equality (drop all non-alphanumerics, case-fold).
    4. Substring match (input is a substring of canonical, or vice versa).
    5. difflib closest-match with cutoff 0.6.

    Returns the matched rule entity, or ``None`` on miss.
    """
    rules = world.list_entities("decision_rule")
    by_name = {}
    for rule in rules.values():
        name = getattr(rule, "name", None) or (rule.get("name") if isinstance(rule, dict) else "")
        if name:
            by_name[name] = rule

    if not rule_name:
        return None

    target = rule_name.strip()
    target_lower = target.lower()
    target_norm = _norm_name(target)

    # Step 1: exact case-insensitive.
    for name, rule in by_name.items():
        if name.lower() == target_lower:
            return rule

    # Step 2: alias table.
    alias_lookup_keys = [target_lower, _norm_name(target)]
    for k in alias_lookup_keys:
        for alias_key, canonical in _RULE_ALIASES.items():
            if k == _norm_name(alias_key):
                # Resolve canonical fragment against loaded rules.
                for name, rule in by_name.items():
                    if canonical.lower() == name.lower():
                        return rule
                # Canonical fragment as substring match.
                for name, rule in by_name.items():
                    if canonical.lower() in name.lower():
                        return rule

    # Step 3: normalized-string equality.
    for name, rule in by_name.items():
        if _norm_name(name) == target_norm:
            return rule

    # Step 4: substring containment (both directions).
    candidates = [
        (name, rule)
        for name, rule in by_name.items()
        if target_norm in _norm_name(name) or _norm_name(name) in target_norm
    ]
    if len(candidates) == 1:
        return candidates[0][1]
    # If multiple substring hits, prefer the shortest canonical name —
    # avoids "Wells" matching three different Wells rules.
    if candidates:
        candidates.sort(key=lambda kv: len(kv[0]))
        return candidates[0][1]

    # Step 5: difflib closest match with cutoff.
    import difflib

    matches = difflib.get_close_matches(target, list(by_name.keys()), n=1, cutoff=0.6)
    if matches:
        return by_name[matches[0]]

    return None


def create_superpower(
    world: WorldState,
    extractor: FhirVariableExtractor | None = None,
) -> SuperpowerServer:
    """Factory mirroring HEALTHCRAFT's ``create_server`` convention."""
    return SuperpowerServer(world, extractor=extractor)
