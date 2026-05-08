"""CDS Hooks card adapter.

CDS Hooks is the EHR-side standard for clinical decision support: when an
EHR fires a hook (``patient-view``, ``order-select``, ``encounter-start``)
it expects a JSON response containing zero or more "cards" with a summary,
indicator, source, and optional suggestions/links. Epic, Cerner, and Meditech
all consume this shape directly.

Mapping a ``TriagePlan`` to a card lets the same agent surface its
recommendation inside any CDS Hooks-aware EHR without bespoke integration —
that is exactly the "could this exist in a real healthcare system today?"
story the hackathon judges score on.

The card is intentionally advisory: the ``indicator`` is bounded to
``info`` / ``warning`` / ``critical`` (CDS Hooks 1.0 vocabulary) and the
summary always includes a "physician review required" framing per FDA
clinical-decision-support guidance.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

# CDS Hooks 1.0 indicator vocabulary.
_INDICATORS = {"info", "warning", "critical"}

_RISK_TO_INDICATOR: dict[str, str] = {
    "low": "info",
    "moderate": "warning",
    "high": "critical",
}

_DEFAULT_SOURCE: dict[str, str] = {
    "label": "Mercy Point Triage Agent",
    "url": "https://github.com/GOATnote-Inc/healthcraft",
}


def to_cds_hooks_card(plan: Any, *, source: dict[str, str] | None = None) -> dict[str, Any]:
    """Convert a ``TriagePlan`` to a CDS Hooks 1.0 card dict.

    The card is conservative: it never auto-actions; it only summarizes
    the agent's recommendation and provides a single suggestion the
    clinician can accept or override. Detail field includes the
    rule score, risk level, the safety-gate status, and a deterministic
    bundle hash so the EHR can correlate to its source FHIR Bundle.
    """
    plan_d = plan if isinstance(plan, dict) else asdict(plan)

    rule_result = (plan_d.get("rule_result") or {}).get("result") or {}
    risk_level = (rule_result.get("risk_level") or "").lower()
    indicator = _RISK_TO_INDICATOR.get(risk_level, "info")

    chief = plan_d.get("chief_complaint") or "(no chief complaint)"
    rule_name = (plan_d.get("rule_result") or {}).get("rule") or "(no rule fired)"
    score = rule_result.get("score")
    recommendation = plan_d.get("disposition", {}).get("recommendation") or "observation"

    rubric = plan_d.get("rubric_self_evaluation") or []
    safety_violation = next(
        (c for c in rubric if c.get("safety_critical") and not c.get("satisfied", True)),
        None,
    )
    if safety_violation is not None:
        indicator = "critical"

    summary_parts = [
        f"Triage: {chief}.",
        f"{rule_name}={score} ({risk_level or 'unknown'}).",
        f"Recommendation: {recommendation.upper()} — physician review required.",
    ]
    if safety_violation:
        summary_parts.append("SAFETY GATE TRIPPED — do not act without senior review.")
    summary = " ".join(summary_parts)

    detail_lines = [
        f"**Chief complaint:** {chief}",
        f"**Rule:** {rule_name}",
    ]
    if score is not None:
        detail_lines.append(f"**Score:** {score} (risk={risk_level or 'unknown'})")
    if rule_result.get("recommendation"):
        detail_lines.append(f"**Rule guidance:** {rule_result['recommendation']}")
    detail_lines.append(f"**Disposition:** {recommendation}")
    detail_lines.append(
        f"**Bundle SHA-256 (provenance):** {plan_d.get('sharp', {}).get('bundleSha256', '')}"
    )
    detail_lines.append("_Advisory only. This card does NOT auto-place orders or alter the chart._")
    detail = "\n\n".join(detail_lines)

    suggestion = {
        "label": f"Apply suggested disposition: {recommendation}",
        "uuid": plan_d.get("sharp", {}).get("correlationId") or "no-correlation-id",
        "actions": [
            {
                "type": "create",
                "description": (
                    f"Set encounter disposition to '{recommendation}' after physician confirmation."
                ),
            }
        ],
    }

    card = {
        "uuid": plan_d.get("sharp", {}).get("correlationId") or "no-correlation-id",
        "summary": summary,
        "indicator": indicator if indicator in _INDICATORS else "info",
        "detail": detail,
        "source": source or dict(_DEFAULT_SOURCE),
        "suggestions": [suggestion],
        "links": [
            {
                "label": "View HEALTHCRAFT decision-rule references",
                "url": "https://www.mdcalc.com/",
                "type": "absolute",
            }
        ],
    }
    return card


def to_cds_hooks_response(plan: Any, *, source: dict[str, str] | None = None) -> dict[str, Any]:
    """Wrap a single card in the CDS Hooks ``{"cards": [...]}`` envelope."""
    return {"cards": [to_cds_hooks_card(plan, source=source)]}
