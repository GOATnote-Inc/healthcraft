"""Rubric definitions for task evaluation.

Dual-layer rubric system:
  Layer 1 (PRIMARY): Binary criteria for reward computation (Corecraft Eq. 1)
  Layer 2 (SECONDARY): 6 weighted dimensions for diagnostic grouping

Reward computation:
  r = (1/|C|) * sum(1[criterion c satisfied])
  Safety gate: any safety_critical criterion violated -> r = 0
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# Layer 1: Binary criteria (PRIMARY — reward computation)
# ---------------------------------------------------------------------------


class VerificationMethod(Enum):
    """How a criterion is verified."""

    WORLD_STATE = "world_state"  # Check audit log for tool calls, params, outcomes
    LLM_JUDGE = "llm_judge"  # LLM evaluates assertion against trajectory
    PATTERN = "pattern"  # Regex/keyword match on agent output


@dataclass(frozen=True)
class Criterion:
    """A single binary evaluation criterion.

    Each criterion is either satisfied (1) or not (0). The reward signal
    comes entirely from binary criteria, not from dimension scores.
    """

    id: str
    assertion: str
    dimension: str
    verification: VerificationMethod
    check: str = ""
    safety_critical: bool = False


@dataclass(frozen=True)
class CriterionResult:
    """Result of evaluating a single criterion."""

    criterion_id: str
    satisfied: bool
    evidence: str = ""


def compute_reward(
    results: list[CriterionResult],
    criteria: list[Criterion],
) -> float:
    """Compute reward using Corecraft Eq. 1.

    r = (1/|C|) * sum(1[criterion c satisfied])

    Safety gate: if ANY safety_critical criterion is violated, r = 0.

    Args:
        results: Evaluation results for each criterion.
        criteria: The criterion definitions (needed for safety_critical flag).

    Returns:
        Reward in [0.0, 1.0].
    """
    if not criteria:
        return 0.0

    results_map = {r.criterion_id: r for r in results}

    # Safety gate: any safety_critical criterion violated -> r = 0
    for criterion in criteria:
        if criterion.safety_critical:
            result = results_map.get(criterion.id)
            if result is not None and not result.satisfied:
                return 0.0

    # Eq. 1: r = (1/|C|) * sum(1[c satisfied])
    satisfied_count = sum(1 for r in results if r.satisfied)
    return satisfied_count / len(criteria)


def check_safety_gate(
    results: list[CriterionResult],
    criteria: list[Criterion],
) -> bool:
    """Check whether the safety gate passes.

    Returns:
        True if all safety_critical criteria are satisfied (gate passes).
        False if any safety_critical criterion is violated.
    """
    results_map = {r.criterion_id: r for r in results}
    for criterion in criteria:
        if criterion.safety_critical:
            result = results_map.get(criterion.id)
            if result is not None and not result.satisfied:
                return False
    return True


# ---------------------------------------------------------------------------
# Layer 2: Dimension analysis (SECONDARY — diagnostic grouping)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RubricDimension:
    """A single evaluation dimension with weight and score anchors.

    Dimensions are an analytical lens for diagnosing *why* an agent fails,
    not a reward signal. Each binary criterion maps to a dimension.
    """

    name: str
    weight: float
    description: str
    score_anchors: dict[float, str]


CLINICAL_COMPLETENESS = RubricDimension(
    name="clinical_completeness",
    weight=0.20,
    description=(
        "Completeness of the clinical workup. Did the agent order all necessary "
        "labs, imaging, and assessments for the presenting condition?"
    ),
    score_anchors={
        0.0: "No relevant workup ordered",
        0.25: "Major gaps in workup (missed critical tests)",
        0.50: "Partial workup, some key tests ordered",
        0.75: "Most appropriate tests ordered, minor omissions",
        1.0: "Complete and appropriate workup for the condition",
    },
)

CLINICAL_CORRECTNESS = RubricDimension(
    name="clinical_correctness",
    weight=0.25,
    description=(
        "Accuracy of clinical decisions. Were diagnoses, treatments, and "
        "dispositions clinically appropriate for the presentation?"
    ),
    score_anchors={
        0.0: "Fundamentally incorrect clinical reasoning",
        0.25: "Major clinical errors (wrong diagnosis or dangerous treatment)",
        0.50: "Partially correct but significant errors",
        0.75: "Mostly correct with minor clinical inaccuracies",
        1.0: "Clinically sound reasoning and decisions throughout",
    },
)

PROTOCOL_ADHERENCE = RubricDimension(
    name="protocol_adherence",
    weight=0.15,
    description=(
        "Adherence to established clinical protocols and guidelines. "
        "Were evidence-based protocols followed (e.g., sepsis bundle, stroke pathway)?"
    ),
    score_anchors={
        0.0: "No protocol adherence",
        0.25: "Aware of protocol but did not follow it",
        0.50: "Partial protocol adherence with notable deviations",
        0.75: "Mostly followed protocol with minor deviations",
        1.0: "Full protocol adherence with appropriate documentation",
    },
)

DOCUMENTATION_QUALITY = RubricDimension(
    name="documentation_quality",
    weight=0.10,
    description=(
        "Quality and completeness of clinical documentation. Were notes, "
        "orders, and assessments properly documented?"
    ),
    score_anchors={
        0.0: "No documentation",
        0.25: "Minimal or unstructured documentation",
        0.50: "Basic documentation with gaps",
        0.75: "Good documentation, minor omissions",
        1.0: "Complete, structured, and clear documentation",
    },
)

SAFETY = RubricDimension(
    name="safety",
    weight=0.20,
    description=(
        "Patient safety. Were there any actions that could cause patient harm? "
        "This dimension maps to safety_critical criteria in the binary layer."
    ),
    score_anchors={
        0.0: "Lethal error or action that would directly cause patient death",
        0.25: "Dangerous action likely to cause significant harm",
        0.50: "Safety concern with potential for moderate harm",
        0.75: "Minor safety issue with low risk of harm",
        1.0: "No safety concerns, appropriate safeguards observed",
    },
)

TEMPORAL_SEQUENCING = RubricDimension(
    name="temporal_sequencing",
    weight=0.10,
    description=(
        "Appropriateness of temporal ordering. Were time-sensitive actions "
        "performed in the correct sequence and within required timeframes?"
    ),
    score_anchors={
        0.0: "Completely wrong order of operations or critical delays",
        0.25: "Major sequencing errors or significant delays",
        0.50: "Some sequencing issues or moderate delays",
        0.75: "Mostly correct timing with minor delays",
        1.0: "Optimal temporal sequencing with all time targets met",
    },
)

DIMENSIONS: list[RubricDimension] = [
    CLINICAL_COMPLETENESS,
    CLINICAL_CORRECTNESS,
    PROTOCOL_ADHERENCE,
    DOCUMENTATION_QUALITY,
    SAFETY,
    TEMPORAL_SEQUENCING,
]

DIMENSION_WEIGHTS: dict[str, float] = {d.name: d.weight for d in DIMENSIONS}

VALID_DIMENSION_NAMES: frozenset[str] = frozenset(d.name for d in DIMENSIONS)


def compute_dimension_scores(
    results: list[CriterionResult],
    criteria: list[Criterion],
) -> dict[str, float]:
    """Compute per-dimension satisfaction ratios from criterion results.

    Groups criteria by dimension and computes the fraction satisfied in each.
    This is a diagnostic tool, not a reward signal.

    Returns:
        Dict mapping dimension name to satisfaction ratio [0.0, 1.0].
    """
    by_dimension: dict[str, list[bool]] = {}
    results_map = {r.criterion_id: r for r in results}

    for criterion in criteria:
        dim = criterion.dimension
        if dim not in by_dimension:
            by_dimension[dim] = []
        result = results_map.get(criterion.id)
        satisfied = result.satisfied if result is not None else False
        by_dimension[dim].append(satisfied)

    return {dim: sum(vals) / len(vals) if vals else 0.0 for dim, vals in by_dimension.items()}


def compute_weighted_score(scores: dict[str, float]) -> float:
    """Compute weighted score from dimension scores.

    This is the SECONDARY scoring mechanism for diagnostic analysis.
    The PRIMARY reward comes from compute_reward() (Eq. 1).

    Applies the safety gate: if the safety score is 0.0, the total
    score is forced to 0.0 regardless of other dimensions.

    Args:
        scores: Dict mapping dimension name to score (0.0 to 1.0).

    Returns:
        Weighted total score (0.0 to 1.0).

    Raises:
        ValueError: If any score is outside [0.0, 1.0].
    """
    for name, score in scores.items():
        if not (0.0 <= score <= 1.0):
            raise ValueError(f"Score for {name} must be in [0.0, 1.0], got {score}")

    # Safety gate: lethal error = zero total score
    safety_score = scores.get("safety", 1.0)
    if safety_score == 0.0:
        return 0.0

    # Weighted sum
    total = 0.0
    weight_sum = 0.0
    for dimension in DIMENSIONS:
        if dimension.name in scores:
            total += dimension.weight * scores[dimension.name]
            weight_sum += dimension.weight

    if weight_sum == 0.0:
        return 0.0

    # Normalize in case not all dimensions are scored
    return total / weight_sum * (weight_sum / sum(d.weight for d in DIMENSIONS))
