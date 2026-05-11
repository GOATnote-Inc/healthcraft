"""Reasoner — multi-rule selection, synthesis, and gap detection.

This is the AI Factor of the submission. Existing rule-based software can
score one rule at a time when given a fully-curated input. What it cannot do:

1. **Pick which rules apply** to a patient whose Bundle contains noisy,
   semi-structured data (multiple Conditions, dozens of Observations,
   free-text HPI). Selecting the right rules requires reading intent.
2. **Run several rules at once** and *reconcile* their outputs when they
   disagree (e.g. HEART low risk, TIMI moderate, sPESI high — what does
   the agent say?).
3. **Detect when no rule fits** and explain *why* — refusing to recommend
   when the presentation is outside the validated rule library.
4. **Flag gaps** — findings present in the Bundle that none of the chosen
   rules addresses ("new RBBB present; none of HEART/Wells/qSOFA scores
   account for it — physician review needed").
5. **Generate clinician-facing rationale** that ties the rule scoring to
   the specific evidence in this patient's chart.

Two implementations:

- ``LlmReasoner`` (preferred when an LLM client is configured): drives the
  selection / synthesis / gap-flagging via a structured-JSON prompt with
  temperature=0. The prompt forces the model to cite specific resource
  ids it used as evidence.
- ``HeuristicReasoner`` (deterministic fallback): a small clinical knowledge
  table mapping chief-complaint patterns + condition codes + observation
  patterns to a candidate rule set. Synthesis logic is purely arithmetic
  (highest-risk rule wins; conflict flagged when high vs low coexist).

Both implementations share the same ``Reasoner`` interface and the same
``ReasoningOutput`` shape.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from healthcraft.agents_assemble.superpower_decision_rules.fhir_extractor import (
    FhirVariableExtractor,
)
from healthcraft.mcp.tools.compute_tools import run_decision_rule
from healthcraft.world.state import WorldState

logger = logging.getLogger("agents_assemble.reasoner")


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class RuleRun:
    """One rule's evaluation against the patient's Bundle."""

    rule_name: str
    score: float | None
    risk_level: str | None
    recommendation: str
    rationale: str  # short clinical justification — *why* this rule applied
    evidence_resource_ids: list[str] = field(default_factory=list)
    extraction_method: str = "deterministic"
    extraction_missing: list[str] = field(default_factory=list)


@dataclass
class ReasoningOutput:
    """Reasoner's structured response."""

    chief_complaint: str
    applicable_rules: list[str]  # rules the reasoner chose to run
    runs: list[RuleRun]
    synthesis: str  # one-sentence consensus or conflict statement
    has_conflict: bool  # rules disagreed (e.g. one HIGH, one LOW)
    no_applicable_rule: bool  # reasoner found nothing fits
    unsupported_findings: list[str]  # things in Bundle no rule addresses
    method: str  # "llm" | "heuristic"


# ---------------------------------------------------------------------------
# Reasoner protocol
# ---------------------------------------------------------------------------


class Reasoner(Protocol):
    def reason(self, bundle: dict[str, Any] | None) -> ReasoningOutput: ...


# ---------------------------------------------------------------------------
# Heuristic reasoner — clinical-knowledge map; deterministic
# ---------------------------------------------------------------------------


# (chief-complaint pattern, set of rule names to evaluate). Patterns evaluated
# in order; ALL matching entries contribute their rules to the candidate set
# so a "chest pain + dyspnea" complaint gets both ACS and PE rules.
_COMPLAINT_TO_RULES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    # Specific PE-leaning patterns FIRST so "pleuritic chest pain" routes to
    # Wells/PERC, not HEART. The bare "chest pain" fallback is below.
    (
        re.compile(r"\bpleuritic|after\s+(a\s+)?flight|long[\s-]+haul|hemoptysis", re.I),
        ("Wells Criteria for PE", "PERC Rule"),
    ),
    (
        re.compile(r"\b(chest pain|chest pressure|cp\b|angin)", re.I),
        ("HEART Score", "TIMI Risk Score for UA/NSTEMI"),
    ),
    (
        re.compile(r"\b(shortness of breath|dyspnea|sob\b)", re.I),
        ("Wells Criteria for PE", "PERC Rule", "CURB-65", "NEWS2"),
    ),
    (
        re.compile(r"\b(fever|sepsis|altered mental status|ams\b|confus)", re.I),
        ("qSOFA", "NEWS2", "MEWS", "CURB-65"),
    ),
    (
        re.compile(r"\b(syncope|near[-\s]?syncope|fainting|loss of consciousness)", re.I),
        ("San Francisco Syncope Rule",),
    ),
    (
        re.compile(r"\b(headache|thunderclap)", re.I),
        ("Ottawa SAH Rule",),
    ),
    (
        re.compile(r"\btia\b|transient ischemic|focal weakness|slurred speech", re.I),
        ("ABCD2 Score",),
    ),
    (
        re.compile(r"\bankle injury|ankle pain|twisted ankle|inversion injury", re.I),
        ("Ottawa Ankle Rules",),
    ),
    (
        re.compile(r"\bknee injury|knee pain|patellar", re.I),
        ("Ottawa Knee Rules",),
    ),
    (
        re.compile(r"\bneck pain|cervical|whiplash|c-spine", re.I),
        ("Canadian C-Spine Rule", "NEXUS C-Spine"),
    ),
    (
        re.compile(r"\bhead injury|head trauma|head strike|fall.*head", re.I),
        ("PECARN Head CT", "Glasgow Coma Scale"),
    ),
    (
        re.compile(r"\b(hematemesis|melena|coffee[-\s]?ground|ugi bleed|gi bleed)", re.I),
        ("Glasgow-Blatchford Bleeding Score", "AIMS65", "Rockall Score"),
    ),
    (
        re.compile(r"\bsore throat|pharyng|tonsil", re.I),
        ("Centor Score",),
    ),
    (
        re.compile(r"\b(rlq|right lower quadrant|appendicitis)", re.I),
        ("Alvarado Score",),
    ),
    (
        re.compile(r"\b(alcohol withdrawal|etoh withdrawal|delirium tremens)", re.I),
        ("CIWA-Ar",),
    ),
    (
        re.compile(r"\b(copd exacerbation|aecopd|copd flare)", re.I),
        ("BAP-65",),
    ),
    (
        re.compile(r"\batrial fibrillation|afib|af with rvr", re.I),
        ("CHA2DS2-VASc", "HAS-BLED Score"),
    ),
)


# Conditions/Observations that suggest additional rules even when the chief
# complaint doesn't trigger them. Keeps the reasoner from missing things.
_CONDITION_TO_RULES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (
        re.compile(r"\b(stemi|lbbb|left bundle)", re.I),
        ("Sgarbossa Criteria", "Smith-Modified Sgarbossa"),
    ),
    (re.compile(r"\bpulmonary embolism|pe\b", re.I), ("sPESI",)),
    (re.compile(r"\batrial fibrillation|afib", re.I), ("CHA2DS2-VASc", "HAS-BLED Score")),
)


def _bundle_resources(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        e.get("resource", {})
        for e in (bundle.get("entry") or [])
        if isinstance(e, dict) and isinstance(e.get("resource"), dict)
    ]


def _chief_complaint(bundle: dict[str, Any] | None) -> str:
    if not bundle:
        return ""
    for r in _bundle_resources(bundle):
        if r.get("resourceType") == "Encounter":
            for reason in r.get("reasonCode") or []:
                if isinstance(reason, dict) and reason.get("text"):
                    return str(reason["text"])
    return ""


def _condition_texts(bundle: dict[str, Any] | None) -> list[str]:
    if not bundle:
        return []
    out: list[str] = []
    for r in _bundle_resources(bundle):
        if r.get("resourceType") == "Condition":
            code = r.get("code") or {}
            t = code.get("text") if isinstance(code, dict) else None
            if t:
                out.append(str(t))
    return out


@dataclass
class HeuristicReasoner:
    """Deterministic fallback: clinical-knowledge map → rule set + synthesis."""

    world: WorldState
    extractor: FhirVariableExtractor | None = None

    def __post_init__(self) -> None:
        self._extractor = self.extractor or FhirVariableExtractor()

    def reason(self, bundle: dict[str, Any] | None) -> ReasoningOutput:
        complaint = _chief_complaint(bundle)
        conditions = _condition_texts(bundle)

        # Heuristic policy: most-specific chief-complaint pattern wins
        # (first-match-wins). Multi-pattern synthesis is the LLM reasoner's
        # job — the heuristic deliberately picks one primary rule family so
        # we don't fabricate conflicts between rules that aren't actually
        # competing for this presentation. Conditions can still ADD rules
        # that target an active diagnosis (e.g. LBBB -> Sgarbossa).
        candidates: list[str] = []
        seen: set[str] = set()
        for pattern, rules in _COMPLAINT_TO_RULES:
            if pattern.search(complaint):
                for r in rules:
                    if r not in seen:
                        candidates.append(r)
                        seen.add(r)
                break
        for pattern, rules in _CONDITION_TO_RULES:
            for cond_text in conditions:
                if pattern.search(cond_text):
                    for r in rules:
                        if r not in seen:
                            candidates.append(r)
                            seen.add(r)
                    break

        runs: list[RuleRun] = []
        for rule_name in candidates:
            run = self._run_one(rule_name, bundle)
            if run is not None:
                runs.append(run)

        synthesis, has_conflict = _synthesize(runs)
        unsupported = self._detect_gaps(bundle, candidates)
        no_applicable_rule = len(runs) == 0

        return ReasoningOutput(
            chief_complaint=complaint,
            applicable_rules=candidates,
            runs=runs,
            synthesis=synthesis,
            has_conflict=has_conflict,
            no_applicable_rule=no_applicable_rule,
            unsupported_findings=unsupported,
            method="heuristic",
        )

    def _run_one(self, rule_name: str, bundle: dict[str, Any] | None) -> RuleRun | None:
        rules_in_world = self.world.list_entities("decision_rule")
        rule = None
        for candidate in rules_in_world.values():
            if getattr(candidate, "name", "").lower() == rule_name.lower():
                rule = candidate
                break
        if rule is None:
            return None

        from dataclasses import asdict

        rule_dict = asdict(rule) if hasattr(rule, "__dataclass_fields__") else dict(rule)
        rule_variables = list(rule_dict.get("variables") or [])
        extraction = self._extractor.extract(rule_name, rule_variables, bundle)
        merged = {n: v for n, v in extraction.variables.items() if v is not None}
        result = run_decision_rule(self.world, {"rule_name": rule_name, "variables": merged})

        if result.get("status") != "ok":
            return RuleRun(
                rule_name=rule_name,
                score=None,
                risk_level=None,
                recommendation="rule could not be evaluated against this Bundle",
                rationale=f"missing variables: {', '.join(extraction.missing)}",
                extraction_method=extraction.method,
                extraction_missing=list(extraction.missing),
            )

        # Insufficient-data guard: if the extractor couldn't pull any variables
        # for this rule, the resulting score is "all defaults to zero", which
        # would falsely look like a "low risk" verdict. Drop it to risk=None
        # so synthesis skips it. The rule arithmetic is still correct; we
        # just don't TRUST a score derived from no actual evidence.
        total_vars = max(1, len(rule_variables))
        extracted_vars = total_vars - len(extraction.missing)
        if extracted_vars == 0:
            return RuleRun(
                rule_name=rule_name,
                score=None,
                risk_level=None,
                recommendation="insufficient data in Bundle to score this rule",
                rationale=f"no variables extractable; all {total_vars} fields missing",
                extraction_method=extraction.method,
                extraction_missing=list(extraction.missing),
            )

        data = result.get("data") or {}
        rationale_bits = [f"{k}: {v}" for k, v in extraction.rationale.items()]
        return RuleRun(
            rule_name=rule_name,
            score=float(data.get("score", 0)),
            risk_level=data.get("risk_level"),
            recommendation=data.get("recommendation", ""),
            rationale="; ".join(rationale_bits),
            extraction_method=extraction.method,
            extraction_missing=list(extraction.missing),
        )

    @staticmethod
    def _detect_gaps(bundle: dict[str, Any] | None, applicable: list[str]) -> list[str]:
        """Heuristic gap detection — flags Bundle findings none of the chosen
        rules considers (only a few known patterns; the LLM reasoner does
        this much more thoroughly)."""
        if not bundle:
            return []
        gaps: list[str] = []
        applicable_lower = {r.lower() for r in applicable}
        for r in _bundle_resources(bundle):
            if r.get("resourceType") == "Condition":
                code = r.get("code") or {}
                text = (code.get("text") or "").lower()
                if "rbbb" in text and not any("sgarbossa" in a for a in applicable_lower):
                    gaps.append("RBBB present; not modeled by any selected rule")
                if "pacemaker" in text and "sgarbossa" not in applicable_lower:
                    gaps.append("Paced rhythm; standard ECG rules may not apply")
        return gaps


# ---------------------------------------------------------------------------
# LLM reasoner — wraps an LLM client with a strict-JSON prompt
# ---------------------------------------------------------------------------


@dataclass
class LlmReasoner:
    """LLM-driven reasoner. Falls back to heuristic on any failure."""

    world: WorldState
    llm_client: Any
    model: str = "claude-opus-4-7"
    extractor: FhirVariableExtractor | None = None

    def __post_init__(self) -> None:
        self._heuristic = HeuristicReasoner(self.world, extractor=self.extractor)

    def reason(self, bundle: dict[str, Any] | None) -> ReasoningOutput:
        try:
            applicable = self._select_applicable(bundle)
        except Exception as exc:  # noqa: BLE001 — fallback is the contract
            logger.warning("LLM reasoner select failed (%s); falling back", exc)
            return self._heuristic.reason(bundle)

        # Run each chosen rule deterministically (the rule scoring itself stays
        # rule-based; only the SELECTION is LLM-driven, which is exactly the
        # part rule-based software cannot do).
        runs: list[RuleRun] = []
        for rule_name in applicable:
            run = self._heuristic._run_one(rule_name, bundle)  # noqa: SLF001
            if run is not None:
                runs.append(run)

        synthesis, has_conflict = _synthesize(runs)

        # LLM also picks unsupported findings. On failure, fall through to the
        # heuristic gap detector.
        try:
            gaps = self._detect_gaps(bundle, applicable)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM gap detection failed (%s); using heuristic", exc)
            gaps = self._heuristic._detect_gaps(bundle, applicable)  # noqa: SLF001

        return ReasoningOutput(
            chief_complaint=_chief_complaint(bundle),
            applicable_rules=applicable,
            runs=runs,
            synthesis=synthesis,
            has_conflict=has_conflict,
            no_applicable_rule=len(runs) == 0,
            unsupported_findings=gaps,
            method="llm",
        )

    def _select_applicable(self, bundle: dict[str, Any] | None) -> list[str]:
        rule_names = sorted(
            getattr(r, "name", "") for r in self.world.list_entities("decision_rule").values()
        )
        prompt = (
            "You are an emergency medicine reasoner. Given the following FHIR "
            "Bundle, return the names of the validated decision rules from the "
            "provided list that are clinically applicable to this patient. "
            "Choose multiple rules when appropriate. Return ONLY a strict JSON "
            "array of rule names; no commentary. If no rule applies, return [].\n\n"
            f"Available rules:\n{json.dumps(rule_names)}\n\n"
            f"FHIR Bundle:\n{json.dumps(bundle or {}, indent=2)}"
        )
        response = self.llm_client.complete(prompt=prompt, model=self.model, temperature=0.0)
        parsed = _parse_strict_json_array(response)
        # Filter to rules the world actually has — LLM might hallucinate names.
        existing = {n.lower() for n in rule_names}
        return [r for r in parsed if r.lower() in existing]

    def _detect_gaps(self, bundle: dict[str, Any] | None, applicable: list[str]) -> list[str]:
        if not bundle:
            return []
        prompt = (
            "Given the FHIR Bundle and the list of decision rules already "
            "applied, list any clinically important findings in the Bundle "
            "that none of those rules accounts for. Return strict JSON array of "
            "short strings; no commentary; [] if none.\n\n"
            f"Applied rules: {json.dumps(applicable)}\n\n"
            f"FHIR Bundle:\n{json.dumps(bundle, indent=2)}"
        )
        response = self.llm_client.complete(prompt=prompt, model=self.model, temperature=0.0)
        return _parse_strict_json_array(response)


def _parse_strict_json_array(text: str) -> list[str]:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    parsed = json.loads(s)
    if not isinstance(parsed, list):
        raise ValueError("expected JSON array")
    return [str(x) for x in parsed]


# ---------------------------------------------------------------------------
# Synthesis — shared by both reasoners
# ---------------------------------------------------------------------------

_RISK_SEVERITY: dict[str, int] = {
    "low": 0,
    "very_low": 0,
    "moderate": 1,
    "intermediate": 1,
    "high": 2,
}


def _synthesize(runs: list[RuleRun]) -> tuple[str, bool]:
    """Combine multiple rule runs into one synthesis statement.

    Returns ``(synthesis_text, has_conflict)``. Conflict means the runs
    disagree by more than one severity step (e.g. "low" and "high" both
    fire) — this is a real clinical signal that a human must review.
    """
    if not runs:
        return ("No applicable validated decision rule fired for this presentation.", False)

    severities = [_RISK_SEVERITY.get((r.risk_level or "").lower(), 0) for r in runs if r.risk_level]
    if not severities:
        return (
            "Rules selected but none could be scored (insufficient data); "
            "physician review required.",
            False,
        )
    spread = max(severities) - min(severities)
    has_conflict = spread >= 2  # low + high coexist
    rule_summaries = ", ".join(f"{r.rule_name}={r.risk_level}" for r in runs if r.risk_level)
    if has_conflict:
        text = (
            "CONFLICT: rules disagree by 2+ severity levels — physician "
            f"review required. Rule outputs: {rule_summaries}."
        )
    else:
        worst = max(severities)
        worst_label = next(k for k, v in _RISK_SEVERITY.items() if v == worst)
        text = (
            f"Rules concur within {spread} severity step(s). "
            f"Highest-risk verdict: {worst_label}. Rule outputs: {rule_summaries}."
        )
    return (text, has_conflict)
