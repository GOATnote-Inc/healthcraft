"""Structural linter for rubric ``world_state`` check strings.

Closes the BUG FAMILY the 2026-05-31 grader audit found so it cannot recur — from
the auto-proposer OR a human edit — with a few zero-false-positive structural
rules. It is deliberately simple: complexity-with-errors is exactly what would
kill this evaluation from ever being trusted.

Rules:
  1. DANGLING-OPERATOR — a check ending in a bare ``or`` / ``and`` with no
     following clause: the exact truncation that dropped "phenytoin" from the
     MW-016 gate ("...matching fosphenytoin or").
  2. OR-OF-NEGATIONS — two ``does NOT contain`` clauses joined by ``OR``: this
     false-passes whenever only one forbidden drug is absent. Multi-drug
     prohibitions must be AND-of-negations.
  3. MEMBER-NOT-CLASS — ``matching <X>`` where X is a MEMBER of an em_vocab class
     (so the author should match the CLASS, which catches every sibling drug)
     rather than the class key: the bypass behind NEG-004 / NEG-003 / CR-041 /
     MW-016 / CR-024. Allowed only for the curated ``SINGLE_DRUG_ALLOWLIST`` of
     deliberate single-drug checks (e.g. a documented single-agent allergy).

Enforced over every ACTIVE check (base-task world_state criteria + v9/v10/v11
overlay entries) by ``tests/test_evaluator_integrity/test_check_linter.py`` and
called by ``scripts/propose_overlay_entries.py`` to reject a bad proposed check
at the source.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from healthcraft.tasks import em_vocab

# Deliberate single-drug checks whose target is a class MEMBER but where matching
# ONLY that one drug is the clinical intent. Each is a reviewed exception; adding
# one is a deliberate act that must carry a clinical justification.
SINGLE_DRUG_ALLOWLIST: dict[str, str] = {
    "ketorolac": "CC-012-C04: ketorolac contraindicated per documented allergy",
    "metoprolol": "TR-011-C03: metoprolol-specific (IV amiodarone + residual diltiazem effect)",
    "ciprofloxacin": "CR-002-C10: documented ciprofloxacin allergy",
    "nicardipine": "CR-030-C05: a specific correct acute pheochromocytoma agent (positive OR)",
    "nitroprusside": "CR-030-C05: a specific correct acute pheochromocytoma agent (positive OR)",
    "lisinopril": "NEG-004-C07: resume the patient's oral home agent (rewarded)",
}

# Matches the matcher's stable "matching <X>" grammar (X runs to the next AND/OR
# clause operator or end-of-string). Verified to extract the same targets the
# evaluator's _audit_entry_matches_params resolves.
_MATCH_RE = re.compile(
    r"matching\s+([a-z0-9_][a-z0-9_ \-/]*?)(?=\s+(?:AND|OR)\b|\s*$)", re.IGNORECASE
)
_DANGLING_RE = re.compile(r"\b(or|and)\s*$", re.IGNORECASE)
_NEGATION_RE = re.compile(r"does\s+not\s+contain", re.IGNORECASE)


@lru_cache(maxsize=1)
def _member_to_classes() -> dict[str, list[str]]:
    """Surface form -> the class key(s) it belongs to, excluding forms that are
    themselves a class key."""
    classes = set(em_vocab.available_classes())
    out: dict[str, list[str]] = {}
    for cls in classes:
        for form in em_vocab.expand_class(cls):
            if form in classes:
                continue
            out.setdefault(form, []).append(cls)
    return out


def lint_check(criterion_id: str, check: str) -> list[str]:
    """Return a list of human-readable violations for one check string (empty = clean)."""
    violations: list[str] = []
    c = (check or "").strip()
    if not c:
        return violations

    m = _DANGLING_RE.search(c)
    if m:
        violations.append(
            f"{criterion_id}: dangling '{m.group(1).lower()}' operator with no following "
            f"clause (truncation signature) in {c!r}"
        )

    or_clauses = re.split(r"\s+OR\s+", c)
    if len(or_clauses) >= 2 and sum(1 for cl in or_clauses if _NEGATION_RE.search(cl)) >= 2:
        violations.append(
            f"{criterion_id}: OR-of-negations — multi-drug prohibitions must be AND-of-negations "
            f"(OR false-passes when only one forbidden drug is absent) in {c!r}"
        )

    members = _member_to_classes()
    classes = set(em_vocab.available_classes())
    for tgt in _MATCH_RE.finditer(c):
        x = tgt.group(1).strip().lower()
        if x in classes:
            continue  # correct class usage
        if x in members and x not in SINGLE_DRUG_ALLOWLIST:
            violations.append(
                f"{criterion_id}: 'matching {x}' uses a MEMBER of em_vocab class {members[x]} as a "
                f"literal — match the class (catches every sibling drug), or add '{x}' to "
                f"SINGLE_DRUG_ALLOWLIST with a clinical justification if a single-drug check is "
                f"truly intended."
            )
    return violations


def active_checks(repo_root: Path) -> list[tuple[str, str, str]]:
    """(source, criterion_id, check) for base-task world_state criteria + v9/v10/v11 overlays."""
    from healthcraft.llm.orchestrator import _load_overlay
    from healthcraft.tasks.loader import load_tasks

    out: list[tuple[str, str, str]] = []
    for task in load_tasks(repo_root / "configs" / "tasks"):
        for cr in task.criteria:
            if cr.get("verification") == "world_state" and cr.get("check"):
                out.append((f"task:{task.id}", cr["id"], cr["check"]))
    for channel in ("v9", "v10", "v11"):
        for crit_id, overlay in _load_overlay(channel).items():
            if overlay.get("check"):
                out.append((channel, crit_id, overlay["check"]))
    return out


def lint_active_checks(repo_root: Path) -> list[str]:
    """Lint every active check; return all violations across sources."""
    violations: list[str] = []
    for source, crit_id, check in active_checks(repo_root):
        violations.extend(f"[{source}] {v}" for v in lint_check(crit_id, check))
    return violations
