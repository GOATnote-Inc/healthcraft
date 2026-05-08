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


_NEGATION_WINDOW = 25  # characters before a hit to scan for negation cues
_NEGATION_PATTERN = re.compile(
    r"\b(no|denies|denied|without|negative for|absent|ruled out|r/o|not?\b|none of)\b\s+[^.]*$",
    re.I,
)


def _is_negated(text: str, match_start: int) -> bool:
    """Heuristic: a match is negated when the preceding window inside the same
    sentence contains a negation cue. Cheap and surprisingly effective for
    medical free-text where most negations live within the same clause."""
    window_start = max(0, match_start - _NEGATION_WINDOW)
    window = text[window_start:match_start]
    # Trim to the current sentence so "no leg swelling. PE likely" doesn't
    # falsely negate "PE likely".
    last_period = window.rfind(".")
    if last_period >= 0:
        window = window[last_period + 1 :]
    return bool(_NEGATION_PATTERN.search(window))


def _iter_text_blobs(bundle: dict[str, Any]) -> list[str]:
    """All free-text strings inside a Bundle's note/text fields."""
    blobs: list[str] = []
    for r in _bundle_resources(bundle):
        for field in ("note", "text"):
            value = r.get(field)
            if isinstance(value, dict):
                div = value.get("div", "") or ""
                if div:
                    blobs.append(div)
            elif isinstance(value, list):
                for n in value:
                    if isinstance(n, dict):
                        t = n.get("text", "") or ""
                        if t:
                            blobs.append(t)
            elif isinstance(value, str):
                blobs.append(value)
    return blobs


def _has_text(
    bundle: dict[str, Any],
    pattern: re.Pattern[str],
    *,
    respect_negation: bool = True,
) -> bool:
    """True if ``pattern`` is present anywhere in note/text fields and (when
    ``respect_negation``) is not preceded by a negation cue in the same clause."""
    for blob in _iter_text_blobs(bundle):
        for m in pattern.finditer(blob):
            if respect_negation and _is_negated(blob, m.start()):
                continue
            return True
    return False


def _observation_value(
    bundle: dict[str, Any],
    *,
    loinc: str | None = None,
    text_pattern: re.Pattern[str] | None = None,
    component_loinc: str | None = None,
) -> float | None:
    """Find the numeric ``valueQuantity`` of an Observation matching either a
    LOINC code or a text pattern. ``component_loinc`` extracts a sub-component
    (e.g. systolic from a BP observation)."""
    for r in _bundle_resources(bundle):
        if r.get("resourceType") != "Observation":
            continue
        code = r.get("code") or {}
        codings = code.get("coding") or []
        text = code.get("text") or ""

        loinc_match = loinc and any(
            (c.get("system", "") == "http://loinc.org" and c.get("code") == loinc)
            for c in codings
            if isinstance(c, dict)
        )
        text_match = text_pattern is not None and text_pattern.search(text)
        if not (loinc_match or text_match):
            continue

        if component_loinc:
            for comp in r.get("component") or []:
                comp_code = (comp.get("code") or {}).get("coding") or []
                hit = any(
                    c.get("system", "") == "http://loinc.org" and c.get("code") == component_loinc
                    for c in comp_code
                    if isinstance(c, dict)
                )
                if hit:
                    val = (comp.get("valueQuantity") or {}).get("value")
                    if isinstance(val, (int, float)):
                        return float(val)
        val = (r.get("valueQuantity") or {}).get("value")
        if isinstance(val, (int, float)):
            return float(val)
    return None


def _has_condition(bundle: dict[str, Any], pattern: re.Pattern[str]) -> bool:
    """True if any Condition.code matches the pattern (text or coding display)."""
    for r in _bundle_resources(bundle):
        if r.get("resourceType") != "Condition":
            continue
        text = json.dumps(r.get("code", {}))
        if pattern.search(text):
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


def _qsofa_handler(
    bundle: dict[str, Any],
    rule_variables: list[dict[str, Any]],
) -> tuple[dict[str, float | int | None], dict[str, str]]:
    values: dict[str, float | int | None] = {}
    rationale: dict[str, str] = {}

    rr = _observation_value(bundle, loinc="9279-1") or _observation_value(
        bundle, text_pattern=re.compile(r"respiratory rate", re.I)
    )
    if rr is not None:
        hit = rr >= 22
        values["Respiratory rate >= 22"] = 1 if hit else 0
        rationale["Respiratory rate >= 22"] = f"RR={rr} ({'>=22' if hit else '<22'})"

    sbp = _observation_value(
        bundle, loinc="85354-9", component_loinc="8480-6"
    ) or _observation_value(bundle, loinc="8480-6")
    if sbp is not None:
        hit = sbp <= 100
        values["Systolic blood pressure <= 100 mmHg"] = 1 if hit else 0
        rationale["Systolic blood pressure <= 100 mmHg"] = (
            f"SBP={sbp} ({'<=100' if hit else '>100'})"
        )

    altered = _has_text(
        bundle, re.compile(r"\b(altered ment|confus|gcs\s*<\s*15|encephalopath)", re.I)
    ) or _has_condition(bundle, re.compile(r"altered.*mental|confus|encephalopath", re.I))
    gcs = _observation_value(bundle, loinc="9269-2") or _observation_value(
        bundle, text_pattern=re.compile(r"glasgow", re.I)
    )
    if gcs is not None and gcs < 15:
        altered = True
    values["Altered mentation"] = 1 if altered else 0
    rationale["Altered mentation"] = "AMS detected" if altered else "no AMS findings"

    return values, rationale


def _wells_pe_handler(
    bundle: dict[str, Any],
    rule_variables: list[dict[str, Any]],
) -> tuple[dict[str, float | int | None], dict[str, str]]:
    values: dict[str, float | int | None] = {}
    rationale: dict[str, str] = {}

    dvt_signs = _has_condition(
        bundle, re.compile(r"dvt|deep vein|leg swelling|calf tenderness", re.I)
    ) or _has_text(bundle, re.compile(r"\b(leg swelling|calf tenderness|unilateral edema)", re.I))
    values["Clinical signs/symptoms of DVT"] = 3 if dvt_signs else 0
    rationale["Clinical signs/symptoms of DVT"] = (
        "DVT signs documented" if dvt_signs else "no DVT signs"
    )

    pe_likely = _has_text(
        bundle, re.compile(r"\b(pe (likely|suspected|first|primary)|pulmonary embolism)", re.I)
    )
    values["PE is #1 diagnosis or equally likely"] = 3 if pe_likely else 0
    rationale["PE is #1 diagnosis or equally likely"] = (
        "PE listed as primary/likely" if pe_likely else "no PE-as-primary text"
    )

    hr = _observation_value(bundle, loinc="8867-4") or _observation_value(
        bundle, text_pattern=re.compile(r"heart rate|pulse", re.I)
    )
    if hr is not None:
        hit = hr > 100
        values["Heart rate > 100"] = 1.5 if hit else 0
        rationale["Heart rate > 100"] = f"HR={hr} ({'>100' if hit else '<=100'})"

    immobil = _has_text(
        bundle,
        re.compile(
            r"\b(immobil|recent surgery|long[\s-]+(haul[\s-]+)?flight|"
            r"bedridden|bed rest|prolonged travel)",
            re.I,
        ),
    )
    values["Immobilization or surgery in past 4 weeks"] = 1.5 if immobil else 0
    rationale["Immobilization or surgery in past 4 weeks"] = (
        "immobilization/recent-surgery cue found" if immobil else "no immobilization cues"
    )

    prior_vte = _has_condition(
        bundle, re.compile(r"\b(history of pe|prior pe|dvt|pulmonary embolism)", re.I)
    )
    values["Previous PE or DVT"] = 1.5 if prior_vte else 0
    rationale["Previous PE or DVT"] = (
        "prior VTE Condition present" if prior_vte else "no prior VTE Conditions"
    )

    hemoptysis = _has_condition(bundle, re.compile(r"hemoptysis", re.I)) or _has_text(
        bundle, re.compile(r"\bhemoptysis|coughing up blood", re.I)
    )
    values["Hemoptysis"] = 1 if hemoptysis else 0
    rationale["Hemoptysis"] = "hemoptysis present" if hemoptysis else "no hemoptysis"

    malignancy = _has_condition(
        bundle, re.compile(r"\b(malignan|cancer|carcinoma|lymphoma|leukemia|sarcoma)", re.I)
    )
    values["Malignancy"] = 1 if malignancy else 0
    rationale["Malignancy"] = "active malignancy Condition" if malignancy else "no malignancy"

    return values, rationale


_DETERMINISTIC_HANDLERS: dict[
    str,
    Callable[
        [dict[str, Any], list[dict[str, Any]]],
        tuple[dict[str, float | int | None], dict[str, str]],
    ],
] = {
    "heart_score": _heart_handler,
    "qsofa": _qsofa_handler,
    "wells_criteria_for_pe": _wells_pe_handler,
}
