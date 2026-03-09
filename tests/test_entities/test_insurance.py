"""Tests for Insurance entity."""

from __future__ import annotations

import random

import pytest

from healthcraft.entities.base import EntityType
from healthcraft.entities.insurance import Insurance, generate_insurance


class TestInsuranceGeneration:
    """Test deterministic insurance generation."""

    def test_generate_returns_insurance(self) -> None:
        rng = random.Random(42)
        ins = generate_insurance(rng, "PAT-001")
        assert isinstance(ins, Insurance)

    def test_generate_deterministic(self) -> None:
        i1 = generate_insurance(random.Random(42), "PAT-001")
        i2 = generate_insurance(random.Random(42), "PAT-001")
        assert i1.id == i2.id
        assert i1.plan_type == i2.plan_type

    def test_different_seeds_different_insurance(self) -> None:
        i1 = generate_insurance(random.Random(42), "PAT-001")
        i2 = generate_insurance(random.Random(99), "PAT-001")
        assert i1.id != i2.id

    def test_insurance_has_required_fields(self) -> None:
        rng = random.Random(42)
        ins = generate_insurance(rng, "PAT-001")
        assert ins.entity_type == EntityType.INSURANCE
        assert ins.patient_id == "PAT-001"
        assert ins.plan_type in (
            "commercial",
            "medicare",
            "medicaid",
            "tricare",
            "self_pay",
            "uninsured",
        )
        assert ins.created_at is not None

    def test_insurance_is_frozen(self) -> None:
        rng = random.Random(42)
        ins = generate_insurance(rng, "PAT-001")
        with pytest.raises(AttributeError):
            ins.plan_type = "commercial"  # type: ignore[misc]

    def test_distribution_includes_commercial(self) -> None:
        """Over 100 samples, at least some should be commercial."""
        types = set()
        for seed in range(100):
            ins = generate_insurance(random.Random(seed), f"PAT-{seed:03d}")
            types.add(ins.plan_type)
        assert "commercial" in types

    def test_distribution_includes_medicare(self) -> None:
        types = set()
        for seed in range(100):
            ins = generate_insurance(random.Random(seed), f"PAT-{seed:03d}")
            types.add(ins.plan_type)
        assert "medicare" in types

    def test_prior_auth_is_tuple(self) -> None:
        rng = random.Random(42)
        ins = generate_insurance(rng, "PAT-001")
        assert isinstance(ins.prior_auth_required, tuple)
