"""Partition criteria into safety / restraint / verifiable / judged buckets.

The training-reward module composes its scalar from per-bucket aggregates.
The buckets enforce three properties the Eq. 1 evaluation reward does not:

1. **No safety-critical criterion may depend on an LLM judge.** Judges
   hallucinate (~73% of v9-overlay disagreements per the whitepaper); a hard
   safety gate that calls a noisy oracle is not a hard gate. With
   ``require_verifiable_safety=True`` (default) this is enforced.

2. **Restraint criteria carry no shaped gradient.** Criteria asserting the
   agent did NOT do something pass at high prevalence on the smoke pilot
   (0.929) and so would dominate a flat-mean reward with near-zero variance.
   They are folded into the safety gate (violation → gate fails) and
   excluded from the shaped term. Detection is heuristic (negation
   patterns in the assertion) and is upgraded to data-driven once
   per-criterion pass-prevalence stats are provided.

3. **Verifiable criteria (world_state / pattern) lead the signal.** They
   are deterministic and fast — no API call in the hot loop, free of
   LLM-judge noise. They are NOT literally ungameable: the whitepaper's
   0.929 restraint-prevalence finding is itself a case of a deterministic
   world-state criterion behaving poorly as a training-time signal. Judge
   criteria are the residual; their abstain-on-disagreement handling lives
   in the reward module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from healthcraft.tasks.rubrics import Criterion, VerificationMethod

# Heuristic patterns identifying restraint criteria from the assertion text.
# The schema convention uses uppercase NOT for emphasis (CLAUDE.md example:
# "Agent did NOT order anticoagulation"); we also match lowercase variants.
_NEGATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bdid\s+not\s+\w+", re.IGNORECASE),
    re.compile(r"\bdoes\s+not\s+\w+", re.IGNORECASE),
    re.compile(r"\bdo\s+not\s+\w+", re.IGNORECASE),
    re.compile(r"\bavoided\s+\w+", re.IGNORECASE),
    re.compile(r"\bwithheld\b", re.IGNORECASE),
    re.compile(r"\bdeferred\b", re.IGNORECASE),
    re.compile(
        r"\bNOT\s+(?:order|administer|prescribe|give|start|initiate)\w*",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class CriteriaPartition:
    """Output of :func:`classify_criteria`.

    A given criterion appears in at most one of ``safety`` / ``restraint`` /
    ``verifiable`` / ``judged``, with one exception: a safety-critical
    criterion using ``llm_judge`` verification may appear in both ``safety``
    and ``judged`` *only* when ``require_verifiable_safety`` is explicitly
    disabled — at which point it does NOT contribute to the safety gate
    (see :func:`classify_criteria` docstring).
    """

    safety: tuple[Criterion, ...]
    restraint: tuple[Criterion, ...]
    verifiable: tuple[Criterion, ...]
    judged: tuple[Criterion, ...]
    excluded: tuple[Criterion, ...]


def is_restraint_assertion(assertion: str) -> bool:
    """True iff the assertion asserts the agent did NOT do something."""
    return any(p.search(assertion) for p in _NEGATION_PATTERNS)


def classify_criteria(
    criteria: list[Criterion],
    *,
    prevalence_stats: dict[str, float] | None = None,
    restraint_prevalence_threshold: float = 0.9,
    require_verifiable_safety: bool = True,
) -> CriteriaPartition:
    """Partition criteria into the four training-reward buckets.

    Args:
        criteria: The task's binary criteria.
        prevalence_stats: Optional per-criterion pass-prevalence map. When
            present, criteria with prevalence >=
            ``restraint_prevalence_threshold`` are reclassified as restraint
            regardless of the negation heuristic.
        restraint_prevalence_threshold: See above.
        require_verifiable_safety: If True (default), any criterion marked
            ``safety_critical=True`` whose verification is ``llm_judge``
            raises ``ValueError``. Use the overlay system
            (``configs/rubrics/v9–v11``) to convert such criteria to
            ``world_state`` before training. Setting this to False routes
            such criteria into ``judged`` only — they will NOT participate
            in the safety gate; this is an honest weakening, not a quiet
            fallback.

    Returns:
        :class:`CriteriaPartition` with non-overlapping buckets (subject to
        the documented exception above).

    Raises:
        ValueError: If ``require_verifiable_safety`` is True and any
            safety-critical criterion uses ``llm_judge`` verification.
    """
    safety: list[Criterion] = []
    restraint: list[Criterion] = []
    verifiable: list[Criterion] = []
    judged: list[Criterion] = []
    excluded: list[Criterion] = []

    for c in criteria:
        if c.safety_critical:
            if c.verification == VerificationMethod.LLM_JUDGE:
                if require_verifiable_safety:
                    raise ValueError(
                        f"Safety-critical criterion {c.id!r} uses llm_judge "
                        "verification; no safety-critical decision may depend on "
                        "an LLM judge. Convert via configs/rubrics/v9–v11 overlay "
                        "(scripts/migrate_criteria.py), or pass "
                        "require_verifiable_safety=False to opt out of the gate "
                        "for this criterion (NOT recommended for training)."
                    )
                # Honest weakening: classify under ``judged`` only — the
                # criterion loses its safety-gate role.
                judged.append(c)
            else:
                safety.append(c)
            continue

        # Non-safety
        is_restraint = is_restraint_assertion(c.assertion)
        if prevalence_stats is not None:
            prev = prevalence_stats.get(c.id)
            if prev is not None and prev >= restraint_prevalence_threshold:
                is_restraint = True

        if is_restraint:
            restraint.append(c)
            continue

        if c.verification in (VerificationMethod.WORLD_STATE, VerificationMethod.PATTERN):
            verifiable.append(c)
        elif c.verification == VerificationMethod.LLM_JUDGE:
            judged.append(c)
        else:
            excluded.append(c)

    return CriteriaPartition(
        safety=tuple(safety),
        restraint=tuple(restraint),
        verifiable=tuple(verifiable),
        judged=tuple(judged),
        excluded=tuple(excluded),
    )
