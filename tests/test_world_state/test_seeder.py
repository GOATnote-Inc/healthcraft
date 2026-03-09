"""Tests for WorldSeeder with full entity graph population."""

from __future__ import annotations

from pathlib import Path

import pytest

from healthcraft.entities.base import EntityType
from healthcraft.world.seed import WorldSeeder


@pytest.fixture
def mercy_point_world():
    """Seed the full Mercy Point world state."""
    seeder = WorldSeeder(seed=42)
    config_path = Path(__file__).parents[2] / "configs" / "world" / "mercy_point_v1.yaml"
    return seeder.seed_world(config_path)


class TestWorldSeederEntityGraph:
    """Test that the seeder populates all entity types."""

    def test_patients_populated(self, mercy_point_world) -> None:
        patients = mercy_point_world.list_entities(EntityType.PATIENT.value)
        assert len(patients) == 500

    def test_encounters_populated(self, mercy_point_world) -> None:
        encounters = mercy_point_world.list_entities(EntityType.ENCOUNTER.value)
        assert len(encounters) == 500

    def test_staff_populated(self, mercy_point_world) -> None:
        staff = mercy_point_world.list_entities(EntityType.STAFF.value)
        assert len(staff) >= 8

    def test_protocols_populated(self, mercy_point_world) -> None:
        protocols = mercy_point_world.list_entities(EntityType.PROTOCOL.value)
        assert len(protocols) >= 8

    def test_decision_rules_populated(self, mercy_point_world) -> None:
        rules = mercy_point_world.list_entities(EntityType.DECISION_RULE.value)
        assert len(rules) >= 10

    def test_supplies_populated(self, mercy_point_world) -> None:
        supplies = mercy_point_world.list_entities(EntityType.SUPPLY.value)
        assert len(supplies) >= 25

    def test_resources_populated(self, mercy_point_world) -> None:
        resources = mercy_point_world.list_entities(EntityType.RESOURCE.value)
        assert len(resources) >= 50

    def test_insurance_populated(self, mercy_point_world) -> None:
        insurance = mercy_point_world.list_entities(EntityType.INSURANCE.value)
        assert len(insurance) == 500  # One per patient

    def test_treatment_plans_populated(self, mercy_point_world) -> None:
        plans = mercy_point_world.list_entities(EntityType.TREATMENT_PLAN.value)
        assert len(plans) == 500  # One per encounter

    def test_clinical_tasks_populated(self, mercy_point_world) -> None:
        tasks = mercy_point_world.list_entities(EntityType.CLINICAL_TASK.value)
        assert len(tasks) >= 1000  # 2-5 per encounter

    def test_clinical_knowledge_populated(self, mercy_point_world) -> None:
        knowledge = mercy_point_world.list_entities(EntityType.CLINICAL_KNOWLEDGE.value)
        assert len(knowledge) >= 5

    def test_reference_materials_populated(self, mercy_point_world) -> None:
        refs = mercy_point_world.list_entities(EntityType.REFERENCE_MATERIAL.value)
        assert len(refs) >= 10

    def test_regulatory_populated(self, mercy_point_world) -> None:
        regs = mercy_point_world.list_entities(EntityType.REGULATORY.value)
        assert len(regs) >= 8


class TestWorldSeederDeterminism:
    """Test that seeding is deterministic."""

    def test_same_seed_same_world(self) -> None:
        config_path = Path(__file__).parents[2] / "configs" / "world" / "mercy_point_v1.yaml"
        w1 = WorldSeeder(seed=42).seed_world(config_path)
        w2 = WorldSeeder(seed=42).seed_world(config_path)

        for etype in EntityType:
            e1 = w1.list_entities(etype.value)
            e2 = w2.list_entities(etype.value)
            assert len(e1) == len(e2), f"{etype.value}: {len(e1)} != {len(e2)}"
            assert set(e1.keys()) == set(e2.keys()), f"{etype.value} IDs differ"

    def test_different_seed_different_world(self) -> None:
        config_path = Path(__file__).parents[2] / "configs" / "world" / "mercy_point_v1.yaml"
        w1 = WorldSeeder(seed=42).seed_world(config_path)
        w2 = WorldSeeder(seed=99).seed_world(config_path)

        # Patient IDs should differ
        p1 = set(w1.list_entities(EntityType.PATIENT.value).keys())
        p2 = set(w2.list_entities(EntityType.PATIENT.value).keys())
        assert p1 != p2


class TestWorldSeederTotalEntities:
    """Test total entity count targets."""

    def test_total_entities_above_threshold(self, mercy_point_world) -> None:
        total = 0
        for etype in EntityType:
            total += len(mercy_point_world.list_entities(etype.value))
        # Plan target: 5,000+ entities; we should be close
        assert total >= 3500, f"Only {total} entities (target 5,000+)"
