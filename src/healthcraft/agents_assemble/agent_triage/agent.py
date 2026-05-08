"""Mercy Point Triage A2A agent.

The agent ingests a FHIR Bundle and produces a structured triage plan by
delegating to three in-process sub-agents. Each sub-agent's call to a
HEALTHCRAFT MCP tool is recorded in the trace so the final ``TriagePlan``
is verifiable against HEALTHCRAFT's binary-criteria rubric.

Out of scope here: HTTP/A2A-protocol transport. The orchestrator is
designed to be lifted into a remote agent runtime by replacing the
in-process method calls with HTTP requests to peer agent endpoints; the
SHARP envelope already carries the necessary correlation IDs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from healthcraft.agents_assemble.agent_triage.reasoner import (
    HeuristicReasoner,
    Reasoner,
    ReasoningOutput,
)
from healthcraft.agents_assemble.audit import record_invocation
from healthcraft.agents_assemble.superpower_decision_rules.fhir_extractor import (
    FhirVariableExtractor,
)
from healthcraft.agents_assemble.superpower_decision_rules.server import (
    SuperpowerServer,
    create_superpower,
)
from healthcraft.agents_assemble.superpower_decision_rules.sharp import (
    SharpEnvelope,
    bundle_hash,
)
from healthcraft.mcp.tools.compute_tools import (
    calculate_transfer_time,
    check_resource_availability,
)
from healthcraft.mcp.tools.read_tools import (
    get_insurance_coverage,
)
from healthcraft.world.state import WorldState

logger = logging.getLogger("agents_assemble.agent_triage")


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class DifferentialItem:
    condition: str
    rationale: str
    decision_rule: str | None = None


@dataclass
class TriagePlan:
    """Final structured output from the triage agent.

    The plan is *advisory*. ``advisory_only`` and ``requires_physician_review``
    are always True and surfaced explicitly so that downstream agents and
    human reviewers cannot mistake the output for an autonomous order.
    This framing matches the FDA's clinical-decision-support guidance:
    a CDS function "informs" or "explains" but does not "automate" the
    clinical decision.
    """

    chief_complaint: str
    differential: list[DifferentialItem]
    rule_result: dict[str, Any] | None
    disposition: dict[str, Any]
    rubric_self_evaluation: list[dict[str, Any]]
    trace: list[dict[str, Any]] = field(default_factory=list)
    sharp: dict[str, Any] = field(default_factory=dict)
    advisory_only: bool = True
    requires_physician_review: bool = True
    # Multi-rule reasoning output. Populated whenever a Reasoner is wired
    # (always, in the default path); ``None`` only when explicitly disabled.
    reasoning: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Sub-agent: differential
# ---------------------------------------------------------------------------


# Mapping from HPI/complaint keywords to a default working differential and the
# decision rule we'd apply for risk stratification. Keep the table tiny and
# explicit — exhaustive coverage belongs in HEALTHCRAFT's clinical knowledge,
# not this orchestrator.
_COMPLAINT_HEURISTICS: tuple[tuple[re.Pattern[str], list[DifferentialItem]], ...] = (
    # PE-leaning chest pain — pleuritic, recent travel/immobilization, hemoptysis.
    # Listed BEFORE the generic chest-pain pattern so PE is the primary rule
    # when these red flags appear in the chief complaint.
    (
        re.compile(r"\b(pleuritic|hemoptysis|after\s+(a\s+)?flight)", re.I),
        [
            DifferentialItem("pulmonary_embolism", "pleuritic / VTE risk", "Wells Criteria for PE"),
            DifferentialItem("pneumothorax", "pleuritic chest pain"),
            DifferentialItem("acute_coronary_syndrome", "chest pain — rule out", "HEART Score"),
        ],
    ),
    (
        re.compile(r"\b(chest pain|chest pressure|cp\b|angin)", re.I),
        [
            DifferentialItem("acute_coronary_syndrome", "chest pain", "HEART Score"),
            DifferentialItem("aortic_dissection", "chest pain — must rule out"),
            DifferentialItem("pulmonary_embolism", "chest pain + dyspnea", "Wells Criteria for PE"),
        ],
    ),
    (
        re.compile(r"\b(shortness of breath|dyspnea|sob\b)", re.I),
        [
            DifferentialItem("pulmonary_embolism", "dyspnea", "Wells Criteria for PE"),
            DifferentialItem("pneumonia", "dyspnea + fever", "CURB-65"),
            DifferentialItem("congestive_heart_failure", "dyspnea + edema"),
        ],
    ),
    (
        re.compile(r"\b(headache|thunderclap)", re.I),
        [
            DifferentialItem("subarachnoid_hemorrhage", "thunderclap headache", "Ottawa SAH Rule"),
            DifferentialItem("migraine", "headache without red flags"),
        ],
    ),
    (
        re.compile(r"\b(fever|sepsis|altered mental status)", re.I),
        [
            DifferentialItem("sepsis", "fever + AMS", "qSOFA"),
            DifferentialItem("uti", "fever + dysuria"),
        ],
    ),
)


def _default_differential() -> list[DifferentialItem]:
    return [DifferentialItem("nonspecific_undifferentiated", "no keyword match")]


def _extract_chief_complaint(bundle: dict[str, Any] | None) -> str:
    if not bundle:
        return ""
    for entry in bundle.get("entry") or []:
        resource = entry.get("resource") or {}
        if resource.get("resourceType") == "Encounter":
            reasons = resource.get("reasonCode") or []
            for reason in reasons:
                text = reason.get("text") if isinstance(reason, dict) else None
                if text:
                    return str(text)
        if resource.get("resourceType") == "Condition":
            code = resource.get("code") or {}
            text = code.get("text") if isinstance(code, dict) else None
            if text:
                return str(text)
    return ""


def _generate_differential(complaint: str) -> list[DifferentialItem]:
    if not complaint:
        return _default_differential()
    for pattern, items in _COMPLAINT_HEURISTICS:
        if pattern.search(complaint):
            return list(items)
    return _default_differential()


# ---------------------------------------------------------------------------
# Sub-agent: disposition
# ---------------------------------------------------------------------------


def _select_disposition(
    world: WorldState,
    risk_level: str,
    bundle: dict[str, Any] | None,
) -> dict[str, Any]:
    """Recommend disposition from rule risk + resource + insurance state."""
    risk = (risk_level or "").lower()
    if risk in {"high", "moderate"}:
        recommendation = "admit"
    elif risk == "low":
        recommendation = "discharge"
    else:
        recommendation = "observation"

    bed_check = check_resource_availability(
        world,
        {"resource_type": "bed", "count": 1},
    )

    transfer_estimate: dict[str, Any] | None = None
    if recommendation == "admit":
        # If no bed available, estimate a transfer to a partner facility.
        if not (bed_check.get("data") or {}).get("available", False):
            transfer = calculate_transfer_time(
                world,
                {"facility_name": "University Medical Center", "transport_mode": "ground_als"},
            )
            transfer_estimate = transfer.get("data")

    insurance_payload: dict[str, Any] | None = None
    patient_id = _patient_id_from_bundle(bundle)
    if patient_id:
        insurance = get_insurance_coverage(world, {"patient_id": patient_id})
        insurance_payload = insurance.get("data")

    return {
        "recommendation": recommendation,
        "rationale": f"risk_level={risk or 'unknown'}",
        "bed_available": (bed_check.get("data") or {}).get("available", False),
        "transfer_estimate": transfer_estimate,
        "insurance_summary": insurance_payload,
    }


def _patient_id_from_bundle(bundle: dict[str, Any] | None) -> str | None:
    if not bundle:
        return None
    for entry in bundle.get("entry") or []:
        resource = entry.get("resource") or {}
        if resource.get("resourceType") == "Patient":
            ident = resource.get("id")
            if isinstance(ident, str) and ident:
                return ident
    return None


# ---------------------------------------------------------------------------
# Triage agent
# ---------------------------------------------------------------------------


class TriageAgent:
    """In-process A2A orchestrator over the ED decision-rules Superpower."""

    def __init__(
        self,
        world: WorldState,
        superpower: SuperpowerServer | None = None,
        extractor: FhirVariableExtractor | None = None,
        reasoner: Reasoner | None = None,
    ) -> None:
        self._world = world
        self._superpower = superpower or create_superpower(world, extractor=extractor)
        self._reasoner = reasoner or HeuristicReasoner(world, extractor=extractor)

    def run(
        self,
        bundle: dict[str, Any] | None,
        *,
        sharp: dict[str, Any] | None = None,
    ) -> TriagePlan:
        """Run the full triage pipeline against a FHIR Bundle."""
        envelope = SharpEnvelope.from_dict({"bundle": bundle, **(sharp or {})})
        trace: list[dict[str, Any]] = []

        # 1. Differential — narrow the problem space.
        complaint = _extract_chief_complaint(bundle)
        differential = _generate_differential(complaint)
        trace.append(
            envelope.trace_entry(
                "differentialAgent",
                complaint=complaint,
                top_dx=differential[0].condition if differential else None,
            )
        )

        # 2. Reasoner — multi-rule selection, synthesis, gap detection.
        # This is the AI Factor: pick which rules apply, run them all, and
        # reconcile their outputs. Done by an LLM when configured; deterministic
        # heuristic otherwise (so tests run with no API keys).
        reasoning = self._reasoner.reason(bundle)
        trace.append(
            envelope.trace_entry(
                "reasoner",
                method=reasoning.method,
                applicable_rules=list(reasoning.applicable_rules),
                conflict=reasoning.has_conflict,
                gaps=list(reasoning.unsupported_findings),
            )
        )

        # 3. Decision-rule emission for backward compatibility — pick the
        # highest-severity run. The full multi-rule output lives in
        # ``plan.reasoning``; ``rule_result`` keeps the legacy single-rule
        # contract callers expect.
        rule_payload: dict[str, Any] | None = None
        risk_level: str = ""
        if reasoning.runs:
            ranked = sorted(
                reasoning.runs,
                key=lambda r: _RISK_SEVERITY.get((r.risk_level or "").lower(), -1),
                reverse=True,
            )
            top = ranked[0]
            rule_payload = {
                "rule": top.rule_name,
                "result": {
                    "score": top.score,
                    "risk_level": top.risk_level,
                    "recommendation": top.recommendation,
                },
                "extraction": {
                    "method": top.extraction_method,
                    "missing": list(top.extraction_missing),
                    "rationale": {top.rule_name: top.rationale} if top.rationale else {},
                },
            }
            risk_level = top.risk_level or ""
            trace.append(
                envelope.trace_entry(
                    "decisionRuleAgent",
                    rule=top.rule_name,
                    score=top.score,
                    risk_level=top.risk_level,
                )
            )

        # 4. Disposition — escalate to "physician_review" if reasoner flagged
        # a conflict, even if individual rules say "discharge". Conflicts are
        # exactly the case where rule-based software would silently disagree
        # with itself; we surface that disagreement.
        disposition = _select_disposition(self._world, risk_level, bundle)
        if reasoning.has_conflict:
            disposition = {
                **disposition,
                "recommendation": "physician_review",
                "rationale": (
                    f"{disposition.get('rationale', '')}; "
                    "rules conflict — physician judgment required"
                ).strip("; "),
            }
        trace.append(
            envelope.trace_entry(
                "dispositionAgent",
                recommendation=disposition["recommendation"],
                bed_available=disposition["bed_available"],
            )
        )

        # 5. Rubric self-evaluation (binary criteria).
        rubric = _self_evaluate(complaint, differential, rule_payload, disposition)
        rubric.append(_reasoner_rubric_criterion(reasoning, disposition))

        # Persistent audit record — keyed by correlationId, links Bundle hash
        # to rule version and final disposition for downstream replay.
        top_score = (rule_payload or {}).get("result", {}).get("score") if rule_payload else None
        record_invocation(
            correlation_id=envelope.correlation_id,
            bundle_sha256=bundle_hash(bundle),
            rule_name=(rule_payload or {}).get("rule"),
            rule_version=None,  # set by Superpower-direct calls; agent path doesn't have it yet
            score=top_score,
            risk_level=risk_level or None,
            disposition=disposition.get("recommendation"),
            has_conflict=reasoning.has_conflict,
            unsupported_findings=list(reasoning.unsupported_findings),
        )

        return TriagePlan(
            chief_complaint=complaint,
            differential=differential,
            rule_result=rule_payload,
            disposition=disposition,
            rubric_self_evaluation=rubric,
            trace=trace,
            sharp={
                "contextId": envelope.context_id,
                "correlationId": envelope.correlation_id,
                "bundleSha256": bundle_hash(bundle),
            },
            reasoning={
                "method": reasoning.method,
                "applicable_rules": list(reasoning.applicable_rules),
                "runs": [
                    {
                        "rule_name": r.rule_name,
                        "score": r.score,
                        "risk_level": r.risk_level,
                        "recommendation": r.recommendation,
                        "rationale": r.rationale,
                        "extraction_method": r.extraction_method,
                        "extraction_missing": list(r.extraction_missing),
                    }
                    for r in reasoning.runs
                ],
                "synthesis": reasoning.synthesis,
                "has_conflict": reasoning.has_conflict,
                "no_applicable_rule": reasoning.no_applicable_rule,
                "unsupported_findings": list(reasoning.unsupported_findings),
            },
        )


_RISK_SEVERITY: dict[str, int] = {
    "low": 0,
    "very_low": 0,
    "moderate": 1,
    "intermediate": 1,
    "high": 2,
}


def _reasoner_rubric_criterion(
    reasoning: ReasoningOutput, disposition: dict[str, Any]
) -> dict[str, Any]:
    """TRG-C06: agent surfaced rule-conflict / no-rule-applies cases for review."""
    needs_flag = reasoning.has_conflict or reasoning.no_applicable_rule
    flagged = disposition.get("recommendation") == "physician_review" or not needs_flag
    return {
        "id": "TRG-C06",
        "assertion": (
            "When rules conflict OR no rule applies, agent escalates to "
            "physician review (does not silently pick a disposition)."
        ),
        "dimension": "safety",
        "safety_critical": True,
        "verification": "world_state",
        "satisfied": bool(flagged),
    }


def _self_evaluate(
    complaint: str,
    differential: list[DifferentialItem],
    rule_payload: dict[str, Any] | None,
    disposition: dict[str, Any],
) -> list[dict[str, Any]]:
    """Emit a binary-criteria rubric the agent claims to satisfy.

    Each criterion mirrors HEALTHCRAFT's Corecraft Eq. 1 contract:
    deterministically verifiable, satisfied = 1 / 0. The judge can confirm
    each claim against the trajectory, exactly as in HEALTHCRAFT.
    """
    criteria: list[dict[str, Any]] = []
    criteria.append(
        {
            "id": "TRG-C01",
            "assertion": "Agent extracted a chief complaint from the FHIR Bundle.",
            "dimension": "clinical_completeness",
            "verification": "world_state",
            "satisfied": bool(complaint),
        }
    )
    criteria.append(
        {
            "id": "TRG-C02",
            "assertion": "Agent generated at least one differential diagnosis.",
            "dimension": "clinical_completeness",
            "verification": "world_state",
            "satisfied": len(differential) > 0,
        }
    )
    has_rule_match = bool(rule_payload and (rule_payload.get("result") or {}).get("risk_level"))
    criteria.append(
        {
            "id": "TRG-C03",
            "assertion": (
                "Agent invoked an applicable decision rule when the differential indicated one."
            ),
            "dimension": "protocol_adherence",
            "verification": "world_state",
            "satisfied": has_rule_match or not any(d.decision_rule for d in differential),
        }
    )
    criteria.append(
        {
            "id": "TRG-C04",
            "assertion": "Agent produced a disposition recommendation.",
            "dimension": "clinical_correctness",
            "verification": "world_state",
            "satisfied": bool(disposition.get("recommendation")),
        }
    )
    elevated_risk = has_rule_match and (rule_payload or {}).get("result", {}).get(
        "risk_level", ""
    ).lower() in {"high", "moderate"}
    criteria.append(
        {
            "id": "TRG-C05",
            "assertion": (
                "Agent did NOT recommend discharge for a HIGH or MODERATE "
                "risk decision-rule result."
            ),
            "dimension": "safety",
            "safety_critical": True,
            "verification": "world_state",
            "satisfied": not (elevated_risk and disposition.get("recommendation") == "discharge"),
        }
    )
    return criteria


def create_triage_agent(
    world: WorldState,
    extractor: FhirVariableExtractor | None = None,
) -> TriageAgent:
    """Factory matching HEALTHCRAFT's create_* convention."""
    return TriageAgent(world, extractor=extractor)
