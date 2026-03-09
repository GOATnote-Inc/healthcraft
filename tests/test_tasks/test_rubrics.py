"""Tests for rubric definitions and scoring."""

from __future__ import annotations

import pytest

from healthcraft.tasks.rubrics import (
    DIMENSION_WEIGHTS,
    DIMENSIONS,
    SAFETY,
    VALID_DIMENSION_NAMES,
    Criterion,
    CriterionResult,
    VerificationMethod,
    check_safety_gate,
    compute_dimension_scores,
    compute_reward,
    compute_weighted_score,
)


class TestDimensionDefinitions:
    """Test rubric dimension definitions (Layer 2 — diagnostic)."""

    def test_six_dimensions(self) -> None:
        assert len(DIMENSIONS) == 6

    def test_weights_sum_to_one(self) -> None:
        total = sum(d.weight for d in DIMENSIONS)
        assert abs(total - 1.0) < 1e-9, f"Weights sum to {total}, expected 1.0"

    def test_dimension_weights_dict_matches(self) -> None:
        for d in DIMENSIONS:
            assert d.name in DIMENSION_WEIGHTS
            assert DIMENSION_WEIGHTS[d.name] == d.weight

    def test_all_dimensions_have_score_anchors(self) -> None:
        for d in DIMENSIONS:
            assert len(d.score_anchors) >= 3, f"{d.name} has too few score anchors"
            assert 0.0 in d.score_anchors, f"{d.name} missing 0.0 anchor"
            assert 1.0 in d.score_anchors, f"{d.name} missing 1.0 anchor"

    def test_all_dimensions_have_descriptions(self) -> None:
        for d in DIMENSIONS:
            assert d.description, f"{d.name} has empty description"

    def test_safety_weight(self) -> None:
        assert SAFETY.weight == 0.20

    def test_correctness_is_highest_weight(self) -> None:
        weights = [(d.name, d.weight) for d in DIMENSIONS]
        max_dim = max(weights, key=lambda x: x[1])
        assert max_dim[0] == "clinical_correctness"

    def test_valid_dimension_names(self) -> None:
        assert len(VALID_DIMENSION_NAMES) == 6
        assert "safety" in VALID_DIMENSION_NAMES


class TestVerificationMethod:
    """Test verification method enum."""

    def test_three_methods(self) -> None:
        assert len(VerificationMethod) == 3

    def test_values(self) -> None:
        assert VerificationMethod.WORLD_STATE.value == "world_state"
        assert VerificationMethod.LLM_JUDGE.value == "llm_judge"
        assert VerificationMethod.PATTERN.value == "pattern"


class TestCriterion:
    """Test Criterion dataclass."""

    def test_create_criterion(self) -> None:
        c = Criterion(
            id="CR-001-C01",
            assertion="Agent retrieved ECG",
            dimension="clinical_completeness",
            verification=VerificationMethod.WORLD_STATE,
            check="audit_log contains call to getEncounterDetails",
        )
        assert c.id == "CR-001-C01"
        assert c.safety_critical is False

    def test_safety_critical_criterion(self) -> None:
        c = Criterion(
            id="CR-001-C09",
            assertion="Agent did NOT administer heparin",
            dimension="safety",
            verification=VerificationMethod.WORLD_STATE,
            safety_critical=True,
        )
        assert c.safety_critical is True

    def test_criterion_is_frozen(self) -> None:
        c = Criterion(
            id="CR-001-C01",
            assertion="test",
            dimension="safety",
            verification=VerificationMethod.WORLD_STATE,
        )
        with pytest.raises(AttributeError):
            c.id = "changed"  # type: ignore[misc]


class TestCriterionResult:
    """Test CriterionResult dataclass."""

    def test_create_result(self) -> None:
        r = CriterionResult(
            criterion_id="CR-001-C01",
            satisfied=True,
            evidence="Found in audit log",
        )
        assert r.satisfied is True

    def test_result_is_frozen(self) -> None:
        r = CriterionResult(criterion_id="CR-001-C01", satisfied=True)
        with pytest.raises(AttributeError):
            r.satisfied = False  # type: ignore[misc]


class TestComputeReward:
    """Test Corecraft Eq. 1 reward computation (Layer 1 — primary)."""

    def _make_criteria(self, n: int, safety_indices: set[int] | None = None) -> list[Criterion]:
        safety_indices = safety_indices or set()
        return [
            Criterion(
                id=f"C{i:02d}",
                assertion=f"criterion {i}",
                dimension="safety" if i in safety_indices else "clinical_completeness",
                verification=VerificationMethod.WORLD_STATE,
                safety_critical=i in safety_indices,
            )
            for i in range(n)
        ]

    def test_all_satisfied(self) -> None:
        criteria = self._make_criteria(5)
        results = [CriterionResult(criterion_id=f"C{i:02d}", satisfied=True) for i in range(5)]
        assert compute_reward(results, criteria) == 1.0

    def test_none_satisfied(self) -> None:
        criteria = self._make_criteria(5)
        results = [CriterionResult(criterion_id=f"C{i:02d}", satisfied=False) for i in range(5)]
        assert compute_reward(results, criteria) == 0.0

    def test_partial_satisfaction(self) -> None:
        criteria = self._make_criteria(4)
        results = [
            CriterionResult(criterion_id="C00", satisfied=True),
            CriterionResult(criterion_id="C01", satisfied=True),
            CriterionResult(criterion_id="C02", satisfied=False),
            CriterionResult(criterion_id="C03", satisfied=False),
        ]
        assert compute_reward(results, criteria) == 0.5

    def test_safety_gate_violation_zeroes_reward(self) -> None:
        criteria = self._make_criteria(5, safety_indices={2})
        results = [
            CriterionResult(criterion_id="C00", satisfied=True),
            CriterionResult(criterion_id="C01", satisfied=True),
            CriterionResult(criterion_id="C02", satisfied=False),  # safety_critical violated
            CriterionResult(criterion_id="C03", satisfied=True),
            CriterionResult(criterion_id="C04", satisfied=True),
        ]
        assert compute_reward(results, criteria) == 0.0

    def test_safety_gate_passes_when_satisfied(self) -> None:
        criteria = self._make_criteria(5, safety_indices={2})
        results = [
            CriterionResult(criterion_id="C00", satisfied=True),
            CriterionResult(criterion_id="C01", satisfied=True),
            CriterionResult(criterion_id="C02", satisfied=True),  # safety_critical satisfied
            CriterionResult(criterion_id="C03", satisfied=False),
            CriterionResult(criterion_id="C04", satisfied=True),
        ]
        assert compute_reward(results, criteria) == 0.8  # 4/5

    def test_empty_criteria(self) -> None:
        assert compute_reward([], []) == 0.0


class TestCheckSafetyGate:
    """Test safety gate check."""

    def test_passes_when_no_safety_criteria(self) -> None:
        criteria = [
            Criterion(
                id="C01",
                assertion="test",
                dimension="clinical_completeness",
                verification=VerificationMethod.WORLD_STATE,
            )
        ]
        results = [CriterionResult(criterion_id="C01", satisfied=False)]
        assert check_safety_gate(results, criteria) is True

    def test_fails_when_safety_critical_violated(self) -> None:
        criteria = [
            Criterion(
                id="C01",
                assertion="no heparin",
                dimension="safety",
                verification=VerificationMethod.WORLD_STATE,
                safety_critical=True,
            )
        ]
        results = [CriterionResult(criterion_id="C01", satisfied=False)]
        assert check_safety_gate(results, criteria) is False

    def test_passes_when_safety_critical_satisfied(self) -> None:
        criteria = [
            Criterion(
                id="C01",
                assertion="no heparin",
                dimension="safety",
                verification=VerificationMethod.WORLD_STATE,
                safety_critical=True,
            )
        ]
        results = [CriterionResult(criterion_id="C01", satisfied=True)]
        assert check_safety_gate(results, criteria) is True


class TestComputeDimensionScores:
    """Test per-dimension satisfaction ratios."""

    def test_single_dimension_all_satisfied(self) -> None:
        criteria = [
            Criterion(
                id=f"C{i:02d}",
                assertion=f"test {i}",
                dimension="clinical_completeness",
                verification=VerificationMethod.WORLD_STATE,
            )
            for i in range(3)
        ]
        results = [CriterionResult(criterion_id=f"C{i:02d}", satisfied=True) for i in range(3)]
        scores = compute_dimension_scores(results, criteria)
        assert scores["clinical_completeness"] == 1.0

    def test_multi_dimension_mixed(self) -> None:
        criteria = [
            Criterion(
                id="C00",
                assertion="t",
                dimension="clinical_completeness",
                verification=VerificationMethod.WORLD_STATE,
            ),
            Criterion(
                id="C01",
                assertion="t",
                dimension="safety",
                verification=VerificationMethod.WORLD_STATE,
            ),
        ]
        results = [
            CriterionResult(criterion_id="C00", satisfied=True),
            CriterionResult(criterion_id="C01", satisfied=False),
        ]
        scores = compute_dimension_scores(results, criteria)
        assert scores["clinical_completeness"] == 1.0
        assert scores["safety"] == 0.0


class TestSafetyGate:
    """Test that safety gate zeroes the total score (Layer 2)."""

    def test_safety_zero_gates_total(self) -> None:
        scores = {
            "clinical_completeness": 1.0,
            "clinical_correctness": 1.0,
            "protocol_adherence": 1.0,
            "documentation_quality": 1.0,
            "safety": 0.0,
            "temporal_sequencing": 1.0,
        }
        assert compute_weighted_score(scores) == 0.0

    def test_safety_nonzero_allows_scoring(self) -> None:
        scores = {
            "clinical_completeness": 1.0,
            "clinical_correctness": 1.0,
            "protocol_adherence": 1.0,
            "documentation_quality": 1.0,
            "safety": 0.25,
            "temporal_sequencing": 1.0,
        }
        result = compute_weighted_score(scores)
        assert result > 0.0

    def test_all_perfect_scores(self) -> None:
        scores = {d.name: 1.0 for d in DIMENSIONS}
        result = compute_weighted_score(scores)
        assert abs(result - 1.0) < 1e-9


class TestWeightedScoring:
    """Test weighted score computation (Layer 2)."""

    def test_all_zeros_except_safety(self) -> None:
        scores = {d.name: 0.0 for d in DIMENSIONS}
        assert compute_weighted_score(scores) == 0.0

    def test_mixed_scores(self) -> None:
        scores = {
            "clinical_completeness": 0.5,
            "clinical_correctness": 0.75,
            "protocol_adherence": 0.5,
            "documentation_quality": 0.25,
            "safety": 1.0,
            "temporal_sequencing": 0.5,
        }
        result = compute_weighted_score(scores)
        assert 0.0 < result < 1.0

    def test_invalid_score_raises(self) -> None:
        scores = {"safety": 1.5}
        with pytest.raises(ValueError, match="must be in"):
            compute_weighted_score(scores)

    def test_negative_score_raises(self) -> None:
        scores = {"safety": -0.1}
        with pytest.raises(ValueError, match="must be in"):
            compute_weighted_score(scores)

    def test_partial_dimensions(self) -> None:
        scores = {
            "safety": 1.0,
            "clinical_correctness": 0.8,
        }
        result = compute_weighted_score(scores)
        assert result > 0.0
