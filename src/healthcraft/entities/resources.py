"""Resource availability entity for the HEALTHCRAFT simulation."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from healthcraft.entities.base import Entity, EntityType


@dataclass(frozen=True)
class Resource(Entity):
    """Immutable resource entity representing an ED resource.

    Extends Entity with resource attributes for beds, equipment, rooms,
    and other ED assets at Mercy Point.
    """

    resource_id: str = ""
    name: str = ""
    resource_type: str = ""  # bed, trauma_bay, resus_bay, obs_bed, fast_track, or_suite, ct_scanner, mri, ultrasound, xray, cath_lab, ventilator, cardiac_monitor, decontamination
    zone: str = ""  # trauma, acute, observation, fast_track, imaging, or, cath_lab
    status: str = ""  # available, occupied, cleaning, maintenance, reserved
    occupied_by: str = ""  # encounter_id if occupied, empty otherwise
    capacity: int = 1
    notes: str = ""


# --- Status weights for resource noise injection ---
_BED_STATUS_WEIGHTS = {
    "available": 30,
    "occupied": 55,
    "cleaning": 10,
    "maintenance": 3,
    "reserved": 2,
}

_EQUIPMENT_STATUS_WEIGHTS = {
    "available": 70,
    "occupied": 15,
    "maintenance": 10,
    "reserved": 5,
}


def _make_resource_id(rng: random.Random, prefix: str, index: int) -> str:
    """Generate a deterministic resource ID."""
    return f"RES-{prefix}-{index:03d}"


def _pick_status(rng: random.Random, weights: dict[str, int]) -> str:
    """Pick a status using weighted random selection."""
    statuses = list(weights.keys())
    w = list(weights.values())
    return rng.choices(statuses, weights=w, k=1)[0]


def _make_encounter_id(rng: random.Random) -> str:
    """Generate a fake encounter ID for occupied resources."""
    return f"ENC-{uuid.UUID(int=rng.getrandbits(128)).hex[:8].upper()}"


def generate_ed_resources(rng: random.Random) -> tuple[Resource, ...]:
    """Generate the full set of Mercy Point ED resources.

    Creates all beds, rooms, and equipment matching the Mercy Point facility
    layout. Approximately 60% of beds are pre-occupied (representing a busy
    ED), and some equipment is in maintenance.

    Args:
        rng: Seeded Random instance for deterministic generation.

    Returns:
        A tuple of frozen Resource instances.
    """
    resources: list[Resource] = []
    now = datetime.now(timezone.utc)

    def _add(
        resource_id: str,
        name: str,
        resource_type: str,
        zone: str,
        status_weights: dict[str, int],
        capacity: int = 1,
        notes: str = "",
    ) -> None:
        status = _pick_status(rng, status_weights)
        occupied_by = ""
        if status == "occupied":
            occupied_by = _make_encounter_id(rng)

        entity_id = f"RES-{uuid.UUID(int=rng.getrandbits(128)).hex[:8].upper()}"
        resources.append(
            Resource(
                id=entity_id,
                entity_type=EntityType.RESOURCE,
                created_at=now,
                updated_at=now,
                resource_id=resource_id,
                name=name,
                resource_type=resource_type,
                zone=zone,
                status=status,
                occupied_by=occupied_by,
                capacity=capacity,
                notes=notes,
            )
        )

    # --- Resuscitation bays (12 total) ---
    # Trauma Bays 1-4
    for i in range(1, 5):
        _add(
            resource_id=_make_resource_id(rng, "TRM", i),
            name=f"Trauma Bay {i}",
            resource_type="trauma_bay",
            zone="trauma",
            status_weights=_BED_STATUS_WEIGHTS,
            notes="Level I trauma activation bay" if i <= 2 else "Level II trauma activation bay",
        )

    # Resus 1-8
    for i in range(1, 9):
        _add(
            resource_id=_make_resource_id(rng, "RESUS", i),
            name=f"Resus {i}",
            resource_type="resus_bay",
            zone="trauma",
            status_weights=_BED_STATUS_WEIGHTS,
            notes="Full monitoring, ventilator-ready",
        )

    # --- Acute care beds (18) ---
    for i in range(1, 19):
        _add(
            resource_id=_make_resource_id(rng, "BED", i),
            name=f"Bed {i}",
            resource_type="bed",
            zone="acute",
            status_weights=_BED_STATUS_WEIGHTS,
            notes="Standard acute care bay with cardiac monitor",
        )

    # --- Observation beds (14) ---
    for i in range(1, 15):
        _add(
            resource_id=_make_resource_id(rng, "OBS", i),
            name=f"Obs {i}",
            resource_type="obs_bed",
            zone="observation",
            status_weights=_BED_STATUS_WEIGHTS,
            notes="Observation unit, 24-hour monitoring",
        )

    # --- Fast-track rooms (10) ---
    for i in range(1, 11):
        _add(
            resource_id=_make_resource_id(rng, "FT", i),
            name=f"FT {i}",
            resource_type="fast_track",
            zone="fast_track",
            status_weights=_BED_STATUS_WEIGHTS,
            notes="ESI 4-5, ambulatory patients",
        )

    # --- CT scanners (2) ---
    for i in range(1, 3):
        _add(
            resource_id=_make_resource_id(rng, "CT", i),
            name=f"CT Scanner {i}",
            resource_type="ct_scanner",
            zone="imaging",
            status_weights=_EQUIPMENT_STATUS_WEIGHTS,
            notes="24/7 availability, AI preliminary reads",
        )

    # --- MRI (1) ---
    _add(
        resource_id=_make_resource_id(rng, "MRI", 1),
        name="MRI 1",
        resource_type="mri",
        zone="imaging",
        status_weights=_EQUIPMENT_STATUS_WEIGHTS,
        notes="Shared with inpatient, available 07:00-23:00, after-hours by request",
    )

    # --- Ultrasound machines (4) ---
    for i in range(1, 5):
        is_portable = i > 2
        _add(
            resource_id=_make_resource_id(rng, "US", i),
            name=f"Ultrasound {i}",
            resource_type="ultrasound",
            zone="imaging",
            status_weights=_EQUIPMENT_STATUS_WEIGHTS,
            notes="Portable unit" if is_portable else "Department-owned, fixed location",
        )

    # --- X-ray rooms (3) ---
    for i in range(1, 4):
        _add(
            resource_id=_make_resource_id(rng, "XR", i),
            name=f"X-ray Room {i}",
            resource_type="xray",
            zone="imaging",
            status_weights=_EQUIPMENT_STATUS_WEIGHTS,
            notes="24/7 tech response < 10 minutes",
        )

    # --- OR suites (8) ---
    for i in range(1, 9):
        _add(
            resource_id=_make_resource_id(rng, "OR", i),
            name=f"OR Suite {i}",
            resource_type="or_suite",
            zone="or",
            status_weights=_EQUIPMENT_STATUS_WEIGHTS,
            notes="Shared with inpatient surgery",
        )

    # --- Cardiac cath lab (1) ---
    _add(
        resource_id=_make_resource_id(rng, "CATH", 1),
        name="Cardiac Cath Lab 1",
        resource_type="cath_lab",
        zone="cath_lab",
        status_weights=_EQUIPMENT_STATUS_WEIGHTS,
        notes="STEMI activation, door-to-balloon < 90 min target",
    )

    # --- Decontamination room (1) ---
    _add(
        resource_id=_make_resource_id(rng, "DECON", 1),
        name="Decontamination Room 1",
        resource_type="decontamination",
        zone="trauma",
        status_weights={
            "available": 90,
            "occupied": 5,
            "maintenance": 4,
            "reserved": 1,
        },
        notes="Chemical/radiological decontamination, external entrance",
    )

    # --- Ventilators (10) ---
    for i in range(1, 11):
        _add(
            resource_id=_make_resource_id(rng, "VENT", i),
            name=f"Ventilator {i}",
            resource_type="ventilator",
            zone="trauma",
            status_weights={
                "available": 60,
                "occupied": 25,
                "maintenance": 10,
                "reserved": 5,
            },
            notes="Portable, can be deployed to any bay",
        )

    # --- Cardiac monitors (20) ---
    for i in range(1, 21):
        _add(
            resource_id=_make_resource_id(rng, "MON", i),
            name=f"Cardiac Monitor {i}",
            resource_type="cardiac_monitor",
            zone="acute",
            status_weights={
                "available": 40,
                "occupied": 50,
                "maintenance": 7,
                "reserved": 3,
            },
            notes="Continuous telemetry, 12-lead capable",
        )

    return tuple(resources)
