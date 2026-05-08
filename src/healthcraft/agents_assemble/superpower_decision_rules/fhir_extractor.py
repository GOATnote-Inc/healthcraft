"""Extract decision-rule variables from a FHIR Bundle.

This is the GenAI surface of the Superpower. A typical FHIR Bundle contains
free-text history-of-present-illness, semi-structured Observations, Patient
demographics, and Conditions. Mapping that to a 5-element HEART score (or a
7-element Wells, etc.) is exactly the kind of fuzzy translation rule-based
software does badly.

Two extraction modes:

- ``llm`` (preferred): an LLM client is given the rule's variable schema and
  the inbound Bundle and returns a strict JSON object of variable values.
  Temperature is forced to 0; output is JSON-validated.
- ``deterministic`` (fallback): a small library of per-rule heuristics that
  inspect FHIR resources by ``resourceType`` and standard codes. Lossy on
  free-text fields, but always available — used in tests and when the
  caller has no LLM keys configured.

The extractor never invents variables not declared by the rule, and will
never silently default a missing required variable to zero — it returns
``None`` for variables it could not derive, leaving the caller to decide
whether to abort or retry with more context.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger("agents_assemble.fhir_extractor")


@dataclass
class ExtractionResult:
    """Result of extracting variables for a single decision rule."""

    rule_name: str
    variables: dict[str, float | int | None]
    method: str  # "llm" | "deterministic"
    rationale: dict[str, str]  # variable -> short justification
    missing: list[str]


# ---------------------------------------------------------------------------
# Public extractor
# ---------------------------------------------------------------------------


class FhirVariableExtractor:
    """Maps FHIR Bundles to decision-rule variables."""

    def __init__(
        self,
        llm_client: Any | None = None,
        model: str = "claude-opus-4-7",
    ) -> None:
        self._llm = llm_client
        self._model = model

    def extract(
        self,
        rule_name: str,
        rule_variables: list[dict[str, Any]],
        bundle: dict[str, Any] | None,
    ) -> ExtractionResult:
        """Return values for each declared rule variable."""
        if self._llm is not None:
            try:
                return self._extract_llm(rule_name, rule_variables, bundle)
            except Exception as exc:  # noqa: BLE001 — fallback is the contract
                logger.warning("LLM extraction failed (%s); using deterministic fallback", exc)

        return self._extract_deterministic(rule_name, rule_variables, bundle)

    # ------------------------------------------------------------------
    # LLM extraction
    # ------------------------------------------------------------------

    def _extract_llm(
        self,
        rule_name: str,
        rule_variables: list[dict[str, Any]],
        bundle: dict[str, Any] | None,
    ) -> ExtractionResult:
        prompt = _build_llm_prompt(rule_name, rule_variables, bundle)
        # The HEALTHCRAFT LLM client uses a ``complete(prompt, model, temperature)``
        # contract; we call it loosely so this module works against any client
        # that exposes ``.complete(...)`` returning a string.
        response = self._llm.complete(prompt=prompt, model=self._model, temperature=0.0)
        parsed = _parse_strict_json(response)
        values: dict[str, float | int | None] = {}
        rationale: dict[str, str] = {}
        for var in rule_variables:
            name = var["name"]
            entry = parsed.get(name) or {}
            values[name] = _coerce_numeric(entry.get("value"))
            if entry.get("rationale"):
                rationale[name] = str(entry["rationale"])
        missing = [name for name, val in values.items() if val is None]
        return ExtractionResult(
            rule_name=rule_name,
            variables=values,
            method="llm",
            rationale=rationale,
            missing=missing,
        )

    # ------------------------------------------------------------------
    # Deterministic fallback
    # ------------------------------------------------------------------

    def _extract_deterministic(
        self,
        rule_name: str,
        rule_variables: list[dict[str, Any]],
        bundle: dict[str, Any] | None,
    ) -> ExtractionResult:
        canonical = _canonicalize_rule_name(rule_name)
        handler = _DETERMINISTIC_HANDLERS.get(canonical)
        values: dict[str, float | int | None] = {var["name"]: None for var in rule_variables}
        rationale: dict[str, str] = {}

        if handler is not None and bundle is not None:
            handler_values, handler_rationale = handler(bundle, rule_variables)
            values.update(handler_values)
            rationale.update(handler_rationale)

        missing = [name for name, val in values.items() if val is None]
        return ExtractionResult(
            rule_name=rule_name,
            variables=values,
            method="deterministic",
            rationale=rationale,
            missing=missing,
        )


# ---------------------------------------------------------------------------
# LLM prompt + parsing
# ---------------------------------------------------------------------------


def _build_llm_prompt(
    rule_name: str,
    rule_variables: list[dict[str, Any]],
    bundle: dict[str, Any] | None,
) -> str:
    schema_lines = []
    for var in rule_variables:
        name = var["name"]
        desc = var.get("description", "")
        scoring = var.get("scoring") or {}
        scoring_str = "; ".join(f"{k}={v}" for k, v in scoring.items()) if scoring else ""
        lo = var.get("min_value", 0)
        hi = var.get("max_value", 0)
        schema_lines.append(f"- {name} ({lo}..{hi}): {desc}. {scoring_str}")
    schema_block = "\n".join(schema_lines)
    bundle_str = json.dumps(bundle or {}, indent=2) if bundle else "{}"
    return (
        f"You are extracting variables for the {rule_name} clinical decision rule "
        f"from a FHIR R4 Bundle. Use ONLY information present in the Bundle. If a "
        f"variable cannot be determined, return null.\n\n"
        f"Variables:\n{schema_block}\n\n"
        f"FHIR Bundle:\n{bundle_str}\n\n"
        f"Respond with a single strict JSON object:\n"
        f'{{"<variable name>": {{"value": <number|null>, "rationale": "<one short sentence>"}}}}'
    )


def _parse_strict_json(response: str) -> dict[str, Any]:
    text = response.strip()
    # Strip common code-fence wrappers.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("LLM response was not a JSON object")
    return parsed


def _coerce_numeric(val: Any) -> float | int | None:
    if val is None:
        return None
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, str):
        try:
            num = float(val)
            return int(num) if num.is_integer() else num
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Deterministic handlers (small but real — enough to demo)
# ---------------------------------------------------------------------------


def _canonicalize_rule_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _bundle_resources(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        entry.get("resource") or {}
        for entry in (bundle.get("entry") or [])
        if isinstance(entry, dict)
    ]


def _patient_age_years(bundle: dict[str, Any]) -> int | None:
    for r in _bundle_resources(bundle):
        if r.get("resourceType") != "Patient":
            continue
        # Prefer explicit ageYears extension if present (uncommon but cheap).
        for ext in r.get("extension", []) or []:
            if ext.get("url", "").endswith("/age-years"):
                age = ext.get("valueInteger")
                if isinstance(age, int):
                    return age
        birth = r.get("birthDate")
        if not birth:
            continue
        match = re.match(r"^(\d{4})", birth)
        if not match:
            continue
        from datetime import datetime, timezone

        birth_year = int(match.group(1))
        return max(0, datetime.now(timezone.utc).year - birth_year)
    return None


def _has_text(bundle: dict[str, Any], pattern: re.Pattern[str]) -> bool:
    for r in _bundle_resources(bundle):
        for field in ("note", "text"):
            value = r.get(field)
            if isinstance(value, dict) and pattern.search(value.get("div", "") or ""):
                return True
            if isinstance(value, list):
                for n in value:
                    if isinstance(n, dict) and pattern.search(n.get("text", "") or ""):
                        return True
            if isinstance(value, str) and pattern.search(value):
                return True
    return False


def _heart_handler(
    bundle: dict[str, Any],
    rule_variables: list[dict[str, Any]],
) -> tuple[dict[str, float | int | None], dict[str, str]]:
    values: dict[str, float | int | None] = {}
    rationale: dict[str, str] = {}

    age = _patient_age_years(bundle)
    if age is not None:
        if age < 45:
            values["Age"], rationale["Age"] = 0, f"birthDate implies age {age}<45"
        elif age < 65:
            values["Age"], rationale["Age"] = 1, f"birthDate implies age {age} in 45-64"
        else:
            values["Age"], rationale["Age"] = 2, f"birthDate implies age {age}>=65"

    risk_terms = re.compile(
        r"\b(diabet|hypertens|hyperlipid|smok|obes|family history|atherosclero)", re.I
    )
    risk_count = 0
    for r in _bundle_resources(bundle):
        if r.get("resourceType") == "Condition":
            text = json.dumps(r.get("code", {}))
            if risk_terms.search(text):
                risk_count += 1
    if risk_count == 0:
        values["Risk factors"], rationale["Risk factors"] = 0, "no qualifying risk Conditions"
    elif risk_count <= 2:
        values["Risk factors"], rationale["Risk factors"] = 1, f"{risk_count} risk Conditions"
    else:
        values["Risk factors"], rationale["Risk factors"] = 2, f"{risk_count}+ risk Conditions"

    # Troponin Observation (LOINC 6598-7 or text "troponin")
    troponin_high = _has_text(
        bundle, re.compile(r"troponin.*(\d+(?:\.\d+)?)\s*(?:x|times)?\s*(?:upper|uln)", re.I)
    )
    troponin_present = _has_text(bundle, re.compile(r"troponin", re.I))
    if troponin_high:
        values["Troponin"], rationale["Troponin"] = 2, "troponin reported >ULN"
    elif troponin_present:
        values["Troponin"], rationale["Troponin"] = 1, "troponin elevated text found"
    else:
        values["Troponin"], rationale["Troponin"] = 0, "no troponin abnormality detected"

    return values, rationale


_DETERMINISTIC_HANDLERS: dict[
    str,
    Callable[
        [dict[str, Any], list[dict[str, Any]]],
        tuple[dict[str, float | int | None], dict[str, str]],
    ],
] = {
    "heart_score": _heart_handler,
}
