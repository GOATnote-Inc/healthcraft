"""Tests for Resource entity."""

from __future__ import annotations

import random

import pytest

from healthcraft.entities.base import EntityType
from healthcraft.entities.resources import Resource, generate_ed_resources


class TestResourceGeneration:
    """Test ED resource generation."""

    def test_generate_returns_sequence(self) -> None:
        rng = random.Random(42)
        resources = generate_ed_resources(rng)
        assert isinstance(resources, (list, tuple))

    def test_generate_returns_resources(self) -> None:
        rng = random.Random(42)
        resources = generate_ed_resources(rng)
        for r in resources:
            assert isinstance(r, Resource)

    def test_generate_deterministic(self) -> None:
        r1 = generate_ed_resources(random.Random(42))
        r2 = generate_ed_resources(random.Random(42))
        assert len(r1) == len(r2)
        for a, b in zip(r1, r2):
            assert a.id == b.id
            assert a.status == b.status

    def test_resource_entity_type(self) -> None:
        resources = generate_ed_resources(random.Random(42))
        for r in resources:
            assert r.entity_type == EntityType.RESOURCE

    def test_resource_is_frozen(self) -> None:
        resources = generate_ed_resources(random.Random(42))
        with pytest.raises(AttributeError):
            resources[0].status = "available"  # type: ignore[misc]

    def test_has_resuscitation_bays(self) -> None:
        resources = generate_ed_resources(random.Random(42))
        resus = [r for r in resources if r.resource_type in ("trauma_bay", "resus_bay")]
        assert len(resus) >= 10  # Mercy Point has 12

    def test_has_acute_beds(self) -> None:
        resources = generate_ed_resources(random.Random(42))
        beds = [r for r in resources if r.resource_type == "bed"]
        assert len(beds) >= 15

    def test_has_ct_scanners(self) -> None:
        resources = generate_ed_resources(random.Random(42))
        ct = [r for r in resources if r.resource_type == "ct_scanner"]
        assert len(ct) >= 2

    def test_some_resources_occupied(self) -> None:
        """Noise: some resources should be pre-occupied."""
        resources = generate_ed_resources(random.Random(42))
        occupied = [r for r in resources if r.status == "occupied"]
        assert len(occupied) > 0

    def test_total_resource_count(self) -> None:
        """Should match Mercy Point facility layout (~100+ resources)."""
        resources = generate_ed_resources(random.Random(42))
        assert len(resources) >= 50
