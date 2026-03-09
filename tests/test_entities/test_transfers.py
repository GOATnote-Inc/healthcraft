"""Tests for Transfer entity."""

from __future__ import annotations

import random

import pytest

from healthcraft.entities.base import EntityType
from healthcraft.entities.transfers import Transfer, generate_transfer


class TestTransferGeneration:
    """Test deterministic transfer generation."""

    def test_generate_returns_transfer(self) -> None:
        rng = random.Random(42)
        xfr = generate_transfer(rng, "ENC-001", "PAT-001")
        assert isinstance(xfr, Transfer)

    def test_generate_deterministic(self) -> None:
        x1 = generate_transfer(random.Random(42), "ENC-001", "PAT-001")
        x2 = generate_transfer(random.Random(42), "ENC-001", "PAT-001")
        assert x1.id == x2.id
        assert x1.direction == x2.direction

    def test_different_seeds_different_transfers(self) -> None:
        x1 = generate_transfer(random.Random(42), "ENC-001", "PAT-001")
        x2 = generate_transfer(random.Random(99), "ENC-001", "PAT-001")
        assert x1.id != x2.id

    def test_transfer_has_required_fields(self) -> None:
        rng = random.Random(42)
        xfr = generate_transfer(rng, "ENC-001", "PAT-001")
        assert xfr.entity_type == EntityType.TRANSFER
        assert xfr.encounter_id == "ENC-001"
        assert xfr.patient_id == "PAT-001"
        assert xfr.direction in ("incoming", "outgoing")
        assert xfr.status in (
            "requested",
            "accepted",
            "in_transit",
            "arrived",
            "cancelled",
            "declined",
        )
        assert xfr.sending_facility
        assert xfr.receiving_facility
        assert xfr.transport_mode in ("ground_als", "ground_bls", "helicopter", "fixed_wing")
        assert xfr.created_at is not None

    def test_transfer_is_frozen(self) -> None:
        rng = random.Random(42)
        xfr = generate_transfer(rng, "ENC-001", "PAT-001")
        with pytest.raises(AttributeError):
            xfr.status = "arrived"  # type: ignore[misc]

    def test_transfer_has_emtala_field(self) -> None:
        rng = random.Random(42)
        xfr = generate_transfer(rng, "ENC-001", "PAT-001")
        assert isinstance(xfr.emtala_compliant, bool)
