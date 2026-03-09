"""Tests for ClinicalTask entity."""

from __future__ import annotations

import random

import pytest

from healthcraft.entities.base import EntityType
from healthcraft.entities.clinical_tasks import ClinicalTask, generate_clinical_task


class TestClinicalTaskGeneration:
    """Test deterministic clinical task generation."""

    def test_generate_returns_clinical_task(self) -> None:
        rng = random.Random(42)
        task = generate_clinical_task(rng, encounter_id="ENC-001", task_type="lab_draw")
        assert isinstance(task, ClinicalTask)

    def test_generate_deterministic(self) -> None:
        t1 = generate_clinical_task(random.Random(42), "ENC-001", "lab_draw")
        t2 = generate_clinical_task(random.Random(42), "ENC-001", "lab_draw")
        assert t1.id == t2.id
        assert t1.description == t2.description

    def test_different_seeds_different_tasks(self) -> None:
        t1 = generate_clinical_task(random.Random(42), "ENC-001", "lab_draw")
        t2 = generate_clinical_task(random.Random(99), "ENC-001", "lab_draw")
        assert t1.id != t2.id

    def test_task_has_required_fields(self) -> None:
        rng = random.Random(42)
        task = generate_clinical_task(rng, "ENC-001", "medication_admin")
        assert task.entity_type == EntityType.CLINICAL_TASK
        assert task.encounter_id == "ENC-001"
        assert task.task_type == "medication_admin"
        assert task.status in ("pending", "in_progress", "completed", "cancelled", "on_hold")
        assert task.priority in ("stat", "urgent", "routine")
        assert task.created_at is not None

    def test_task_is_frozen(self) -> None:
        rng = random.Random(42)
        task = generate_clinical_task(rng, "ENC-001", "lab_draw")
        with pytest.raises(AttributeError):
            task.status = "completed"  # type: ignore[misc]

    def test_valid_task_types(self) -> None:
        valid_types = (
            "lab_draw",
            "imaging",
            "medication_admin",
            "procedure",
            "consult",
            "nursing",
            "documentation",
        )
        rng = random.Random(42)
        for task_type in valid_types:
            task = generate_clinical_task(rng, "ENC-001", task_type)
            assert task.task_type == task_type
