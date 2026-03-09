"""Tests for Encounter entity."""

from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest

from healthcraft.entities.base import EntityType
from healthcraft.entities.encounters import (
    Disposition,
    Encounter,
    ESILevel,
    VitalSigns,
    generate_encounter,
)
from healthcraft.entities.patients import generate_patient
from healthcraft.world.timeline import SimulationClock


@pytest.fixture
def patient() -> object:
    return generate_patient(random.Random(42))


@pytest.fixture
def clock() -> SimulationClock:
    return SimulationClock(datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc))


class TestEncounterGeneration:
    """Test deterministic encounter generation."""

    def test_generate_encounter_returns_encounter(
        self, patient: object, clock: SimulationClock
    ) -> None:
        rng = random.Random(42)
        encounter = generate_encounter(rng, patient, condition_id=None, clock=clock)
        assert isinstance(encounter, Encounter)

    def test_generate_encounter_deterministic(
        self, patient: object, clock: SimulationClock
    ) -> None:
        e1 = generate_encounter(random.Random(42), patient, None, clock)
        # Reset clock for second generation
        clock2 = SimulationClock(datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc))
        e2 = generate_encounter(random.Random(42), patient, None, clock2)
        assert e1.id == e2.id
        assert e1.chief_complaint == e2.chief_complaint
        assert e1.esi_level == e2.esi_level

    def test_encounter_has_required_fields(self, patient: object, clock: SimulationClock) -> None:
        rng = random.Random(42)
        encounter = generate_encounter(rng, patient, None, clock)
        assert encounter.id.startswith("ENC-")
        assert encounter.entity_type == EntityType.ENCOUNTER
        assert encounter.patient_id
        assert encounter.chief_complaint
        assert encounter.bed_assignment
        assert encounter.arrival_time is not None
        assert encounter.triage_time is not None

    def test_encounter_is_frozen(self, patient: object, clock: SimulationClock) -> None:
        encounter = generate_encounter(random.Random(42), patient, None, clock)
        with pytest.raises(AttributeError):
            encounter.chief_complaint = "Modified"  # type: ignore[misc]

    def test_encounter_has_initial_vitals(self, patient: object, clock: SimulationClock) -> None:
        encounter = generate_encounter(random.Random(42), patient, None, clock)
        assert len(encounter.vitals) >= 1
        assert isinstance(encounter.vitals[0], VitalSigns)

    def test_encounter_triage_after_arrival(self, patient: object, clock: SimulationClock) -> None:
        encounter = generate_encounter(random.Random(42), patient, None, clock)
        assert encounter.triage_time >= encounter.arrival_time


class TestESILevel:
    """Test ESI level enum."""

    def test_esi_values(self) -> None:
        assert ESILevel.RESUSCITATION == 1
        assert ESILevel.EMERGENT == 2
        assert ESILevel.URGENT == 3
        assert ESILevel.LESS_URGENT == 4
        assert ESILevel.NON_URGENT == 5

    def test_esi_from_int(self) -> None:
        assert ESILevel(1) == ESILevel.RESUSCITATION
        assert ESILevel(3) == ESILevel.URGENT

    def test_esi_ordering(self) -> None:
        assert ESILevel.RESUSCITATION < ESILevel.NON_URGENT


class TestDisposition:
    """Test Disposition enum."""

    def test_all_dispositions(self) -> None:
        assert Disposition.ADMITTED.value == "admitted"
        assert Disposition.DISCHARGED.value == "discharged"
        assert Disposition.TRANSFERRED.value == "transferred"
        assert Disposition.AMA.value == "ama"
        assert Disposition.EXPIRED.value == "expired"
        assert Disposition.LWBS.value == "lwbs"

    def test_disposition_count(self) -> None:
        assert len(Disposition) == 6
