"""Shared test fixtures for HEALTHCRAFT."""

from __future__ import annotations

import random

import pytest

from healthcraft.entities.base import EntityType
from healthcraft.entities.encounters import Encounter, generate_encounter
from healthcraft.entities.patients import Patient, generate_patient
from healthcraft.world.state import WorldState
from healthcraft.world.timeline import SimulationClock


@pytest.fixture
def sample_rng() -> random.Random:
    """Seeded RNG for deterministic tests."""
    return random.Random(42)


@pytest.fixture
def sample_patient(sample_rng: random.Random) -> Patient:
    """A deterministically generated patient."""
    return generate_patient(sample_rng)


@pytest.fixture
def sample_encounter(sample_rng: random.Random, sample_patient: Patient) -> Encounter:
    """A deterministically generated encounter."""
    # Use a fresh RNG seeded from the same base to avoid consuming
    # state from the patient generation
    enc_rng = random.Random(42)
    # Burn the same number of draws as generate_patient
    # Instead, just use a new seed
    enc_rng = random.Random(100)
    clock = SimulationClock()
    return generate_encounter(enc_rng, sample_patient, condition_id=None, clock=clock)


@pytest.fixture
def sample_world_state(sample_patient: Patient, sample_encounter: Encounter) -> WorldState:
    """A WorldState populated with a few entities for testing."""
    world = WorldState()
    world.put_entity(EntityType.PATIENT.value, sample_patient.id, sample_patient)
    world.put_entity(EntityType.ENCOUNTER.value, sample_encounter.id, sample_encounter)

    # Add a staff member
    staff = {
        "id": "STAFF-001",
        "entity_type": "staff",
        "first_name": "James",
        "last_name": "Chen",
        "role": "attending",
        "active": True,
    }
    world.put_entity(EntityType.STAFF.value, "STAFF-001", staff)

    # Add a location
    location = {
        "id": "BED-001",
        "entity_type": "location",
        "name": "Bed 1",
        "type": "bed",
        "zone": "main",
        "occupied": False,
    }
    world.put_entity(EntityType.LOCATION.value, "BED-001", location)

    return world
