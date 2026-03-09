"""Tests for TreatmentPlan entity."""

from __future__ import annotations

import random

import pytest

from healthcraft.entities.base import EntityType
from healthcraft.entities.treatment_plans import TreatmentPlan, generate_treatment_plan


class TestTreatmentPlanGeneration:
    """Test deterministic treatment plan generation."""

    def test_generate_returns_treatment_plan(self) -> None:
        rng = random.Random(42)
        plan = generate_treatment_plan(rng, "ENC-001", "PAT-001", "SEPSIS")
        assert isinstance(plan, TreatmentPlan)

    def test_generate_deterministic(self) -> None:
        p1 = generate_treatment_plan(random.Random(42), "ENC-001", "PAT-001", "SEPSIS")
        p2 = generate_treatment_plan(random.Random(42), "ENC-001", "PAT-001", "SEPSIS")
        assert p1.id == p2.id

    def test_different_seeds_different_plans(self) -> None:
        p1 = generate_treatment_plan(random.Random(42), "ENC-001", "PAT-001", "SEPSIS")
        p2 = generate_treatment_plan(random.Random(99), "ENC-001", "PAT-001", "SEPSIS")
        assert p1.id != p2.id

    def test_plan_has_required_fields(self) -> None:
        rng = random.Random(42)
        plan = generate_treatment_plan(rng, "ENC-001", "PAT-001", "STEMI")
        assert plan.entity_type == EntityType.TREATMENT_PLAN
        assert plan.encounter_id == "ENC-001"
        assert plan.patient_id == "PAT-001"
        assert plan.condition_ref == "STEMI"
        assert plan.status in ("draft", "active", "completed", "cancelled")
        assert plan.priority in ("stat", "urgent", "routine")
        assert isinstance(plan.medications, tuple)
        assert isinstance(plan.procedures, tuple)
        assert isinstance(plan.labs_ordered, tuple)
        assert isinstance(plan.imaging_ordered, tuple)
        assert isinstance(plan.consults, tuple)
        assert plan.created_at is not None

    def test_plan_is_frozen(self) -> None:
        rng = random.Random(42)
        plan = generate_treatment_plan(rng, "ENC-001", "PAT-001", "SEPSIS")
        with pytest.raises(AttributeError):
            plan.status = "completed"  # type: ignore[misc]

    def test_known_condition_has_medications(self) -> None:
        rng = random.Random(42)
        plan = generate_treatment_plan(rng, "ENC-001", "PAT-001", "SEPSIS")
        assert len(plan.medications) > 0 or len(plan.labs_ordered) > 0
