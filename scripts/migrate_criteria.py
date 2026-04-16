"""Propose llm_judge -> world_state criterion migrations for v9 channel.

Walks every ``llm_judge`` criterion across all tasks and applies heuristics
to determine whether the criterion could be deterministically verified via
the audit log. Writes proposals (NOT live rewrites) to a YAML file.

Heuristics:

  1. **Retrieval assertions** -- "Agent retrieved X", "reviewed X", "looked up X"
     -> ``audit_log contains call to <inferred_tool>``

  2. **Ordering assertions** -- "Agent ordered X", "placed an order for X"
     -> ``audit_log contains call to createClinicalOrder for <order_type>``

  3. **Negation assertions** -- "Agent did NOT order X", "avoided X"
     -> ``audit_log does NOT contain createClinicalOrder with medication matching X``

  4. **Sequencing assertions** -- "before", "prior to", "after", "then"
     -> ``<clause_A> BEFORE <clause_B>`` (v9 temporal operator)

Each proposal includes:
  - ``criterion_id``: the criterion ID
  - ``task_id``: owning task
  - ``original_assertion``: what the criterion says in prose
  - ``proposed_verification``: ``world_state``
  - ``proposed_check``: the rewritten check string
  - ``confidence``: high / medium / low
  - ``reason``: why this heuristic applied

Proposals with confidence=low should be reviewed by a clinician before
inclusion in the overlay.

Usage:
    python scripts/migrate_criteria.py --dry-run
    python scripts/migrate_criteria.py --output configs/rubrics/v9_migrations_proposed.yaml
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

import yaml  # noqa: E402

from healthcraft.tasks.evaluator import _parse_criteria  # noqa: E402
from healthcraft.tasks.loader import load_tasks  # noqa: E402
from healthcraft.tasks.rubrics import VerificationMethod  # noqa: E402

TASK_DIR = PROJECT_ROOT / "configs" / "tasks"

# Tool name inference from assertion keywords
_RETRIEVAL_TOOL_MAP = {
    "patient history": "getPatientHistory",
    "history": "getPatientHistory",
    "encounter details": "getEncounterDetails",
    "encounter": "getEncounterDetails",
    "ecg": "getEncounterDetails",
    "lab": "getEncounterDetails",
    "vitals": "getEncounterDetails",
    "imaging": "getEncounterDetails",
    "clinical knowledge": "searchClinicalKnowledge",
    "protocol": "getProtocolDetails",
    "reference": "searchReferenceMaterials",
    "insurance": "getInsuranceCoverage",
    "transfer status": "getTransferStatus",
    "resource": "checkResourceAvailability",
    "decision rule": "runDecisionRule",
}

_ORDER_TYPE_MAP = {
    "lab": "lab",
    "cbc": "lab",
    "bmp": "lab",
    "troponin": "lab",
    "lactate": "lab",
    "blood culture": "lab",
    "type and screen": "lab",
    "crossmatch": "lab",
    "imaging": "imaging",
    "ct": "imaging",
    "x-ray": "imaging",
    "xray": "imaging",
    "ultrasound": "imaging",
    "mri": "imaging",
    "medication": "medication",
    "antibiotic": "medication",
    "analgesic": "medication",
    "iv fluid": "medication",
    "blood product": "blood_product",
    "transfusion": "blood_product",
    "procedure": "procedure",
    "consult": "consult",
}


def _propose_retrieval(assertion: str) -> dict[str, str] | None:
    """Try to map a retrieval-style assertion to an audit-log check."""
    lower = assertion.lower()
    retrieval_verbs = ["retrieved", "reviewed", "looked up", "checked", "obtained", "queried"]
    if not any(verb in lower for verb in retrieval_verbs):
        return None
    for keyword, tool in _RETRIEVAL_TOOL_MAP.items():
        if keyword in lower:
            return {
                "proposed_check": f"audit_log contains call to {tool}",
                "confidence": "medium",
                "reason": f"Retrieval verb + '{keyword}' -> {tool}",
            }
    return None


def _propose_ordering(assertion: str) -> dict[str, str] | None:
    """Try to map an ordering assertion to an audit-log check."""
    lower = assertion.lower()
    order_verbs = ["ordered", "placed an order", "requested"]
    if not any(verb in lower for verb in order_verbs):
        return None
    for keyword, order_type in _ORDER_TYPE_MAP.items():
        if keyword in lower:
            return {
                "proposed_check": (
                    f"audit_log contains call to createClinicalOrder for {order_type}"
                ),
                "confidence": "high",
                "reason": f"Order verb + '{keyword}' -> createClinicalOrder for {order_type}",
            }
    # Generic order without specific type
    return {
        "proposed_check": "audit_log contains call to createClinicalOrder",
        "confidence": "low",
        "reason": "Order verb detected but could not infer order_type",
    }


def _propose_negation(assertion: str) -> dict[str, str] | None:
    """Try to map a negation assertion to an audit-log check."""
    lower = assertion.lower()
    negation_patterns = [
        r"did not (?:order|prescribe|administer)",
        r"avoided",
        r"refrained from ordering",
    ]
    if not any(re.search(p, lower) for p in negation_patterns):
        return None
    # Try to extract what was avoided
    for keyword, order_type in _ORDER_TYPE_MAP.items():
        if keyword in lower:
            return {
                "proposed_check": (
                    f"audit_log does NOT contain createClinicalOrder for {order_type}"
                ),
                "confidence": "medium",
                "reason": f"Negation + '{keyword}' -> negative check for {order_type}",
            }
    # Try to find a drug name after "order" or "prescribe"
    match = re.search(r"(?:order|prescribe|administer)\s+(\w+(?:\s+\w+)?)", lower)
    if match:
        substance = match.group(1).strip()
        return {
            "proposed_check": (
                f"audit_log does NOT contain createClinicalOrder "
                f"with medication matching {substance}"
            ),
            "confidence": "medium",
            "reason": f"Negation + substance '{substance}'",
        }
    return None


def _propose_sequencing(assertion: str) -> dict[str, str] | None:
    """Detect sequencing language for BEFORE/AFTER v9 operators."""
    lower = assertion.lower()
    if "before" not in lower and "prior to" not in lower and "after" not in lower:
        return None
    return {
        "proposed_check": "",
        "confidence": "low",
        "reason": (
            "Sequencing language detected. Manual rewrite needed for v9 BEFORE/AFTER operators."
        ),
    }


def propose_migration(
    task_id: str,
    crit_id: str,
    assertion: str,
) -> dict[str, Any] | None:
    """Try all heuristics; return the highest-confidence proposal or None."""
    for fn in (_propose_negation, _propose_ordering, _propose_retrieval, _propose_sequencing):
        result = fn(assertion)
        if result:
            return {
                "criterion_id": crit_id,
                "task_id": task_id,
                "original_assertion": assertion,
                "proposed_verification": "world_state",
                **result,
            }
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output",
        "-o",
        default="",
        help="Output YAML path (default: stdout)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print summary only, do not write file",
    )
    args = parser.parse_args()

    tasks = load_tasks(TASK_DIR)
    proposals: list[dict[str, Any]] = []

    for task in tasks:
        for crit in _parse_criteria(task.criteria):
            if crit.verification != VerificationMethod.LLM_JUDGE:
                continue
            proposal = propose_migration(task.id, crit.id, crit.assertion)
            if proposal:
                proposals.append(proposal)

    # Summary
    by_conf: dict[str, int] = {}
    for p in proposals:
        conf = p["confidence"]
        by_conf[conf] = by_conf.get(conf, 0) + 1

    print(f"Proposed migrations: {len(proposals)} / 1420 llm_judge criteria")
    for conf in ("high", "medium", "low"):
        print(f"  {conf}: {by_conf.get(conf, 0)}")

    if args.dry_run:
        return 0

    output_data = {
        "version": 1,
        "description": (
            "Proposed llm_judge -> world_state criterion migrations for v9 channel. "
            "Generated by scripts/migrate_criteria.py. Review each proposal before "
            "adding to configs/rubrics/v9_deterministic_overlay.yaml."
        ),
        "n_proposals": len(proposals),
        "proposals": proposals,
    }

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            yaml.dump(output_data, default_flow_style=False, sort_keys=False, width=120),
            encoding="utf-8",
        )
        print(f"Wrote {len(proposals)} proposals to {out_path}")
    else:
        print(yaml.dump(output_data, default_flow_style=False, sort_keys=False, width=120))

    return 0


if __name__ == "__main__":
    sys.exit(main())
