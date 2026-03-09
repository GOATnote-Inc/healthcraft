"""Tests for rubric definitions and scoring."""

from __future__ import annotations

import pytest

from healthcraft.tasks.rubrics import (
    DIMENSION_WEIGHTS,
    DIMENSIONS,
    SAFETY,
    compute_weighted_score,
)


class TestDimensionDefinitions:
    """Test rubric dimension definitions."""

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


class TestSafetyGate:
    """Test that safety gate zeroes the total score."""

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
    """Test weighted score computation."""

    def test_all_zeros_except_safety(self) -> None:
        scores = {d.name: 0.0 for d in DIMENSIONS}
        # Safety=0 triggers gate
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
        # Scoring with only some dimensions provided
        scores = {
            "safety": 1.0,
            "clinical_correctness": 0.8,
        }
        result = compute_weighted_score(scores)
        assert result > 0.0
