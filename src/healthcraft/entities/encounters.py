"""Encounter entity for the HEALTHCRAFT simulation."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum, IntEnum
from typing import Any

from healthcraft.entities.base import Entity, EntityType
from healthcraft.world.timeline import SimulationClock


class ESILevel(IntEnum):
    """Emergency Severity Index (ESI) triage levels."""

    RESUSCITATION = 1
    EMERGENT = 2
    URGENT = 3
    LESS_URGENT = 4
    NON_URGENT = 5


class Disposition(Enum):
    """Encounter disposition outcomes."""

    ADMITTED = "admitted"
    DISCHARGED = "discharged"
    TRANSFERRED = "transferred"
    AMA = "ama"  # Against medical advice
    EXPIRED = "expired"
    LWBS = "lwbs"  # Left without being seen


@dataclass(frozen=True)
class VitalSigns:
    """A single set of vital signs recorded at a point in time."""

    timestamp: datetime
    heart_rate: int | None = None  # bpm
    systolic_bp: int | None = None  # mmHg
    diastolic_bp: int | None = None  # mmHg
    respiratory_rate: int | None = None  # breaths/min
    spo2: int | None = None  # percent
    temperature: float | None = None  # Celsius
    gcs: int | None = None  # Glasgow Coma Scale 3-15
    pain_scale: int | None = None  # 0-10


@dataclass(frozen=True)
class LabResult:
    """A laboratory result."""

    test_name: str
    value: str
    unit: str
    reference_range: str
    timestamp: datetime
    abnormal: bool = False


@dataclass(frozen=True)
class ImagingStudy:
    """An imaging study result."""

    modality: str  # XR, CT, MRI, US
    body_part: str
    findings: str
    impression: str
    timestamp: datetime


@dataclass(frozen=True)
class MedicationAdministration:
    """A medication administered during the encounter."""

    medication_name: str
    dose: str
    route: str  # IV, PO, IM, SQ, IN, PR, SL, INH
    timestamp: datetime
    administered_by: str = ""


@dataclass(frozen=True)
class Encounter(Entity):
    """Immutable encounter entity representing an ED visit.

    Extends Entity with all clinical data generated during the encounter.
    """

    patient_id: str = ""
    chief_complaint: str = ""
    esi_level: ESILevel = ESILevel.URGENT
    bed_assignment: str = ""
    arrival_time: datetime | None = None
    triage_time: datetime | None = None
    disposition: Disposition | None = None
    attending_id: str = ""
    vitals: tuple[VitalSigns, ...] = ()
    labs: tuple[LabResult, ...] = ()
    imaging: tuple[ImagingStudy, ...] = ()
    meds_administered: tuple[MedicationAdministration, ...] = ()
    exam_findings: tuple[tuple[str, str], ...] = ()


# --- Chief complaints by ESI level ---

_CHIEF_COMPLAINTS: dict[ESILevel, tuple[str, ...]] = {
    ESILevel.RESUSCITATION: (
        "Cardiac arrest",
        "Severe respiratory distress",
        "Major trauma - MVC",
        "Active GI hemorrhage",
        "Acute stroke symptoms",
    ),
    ESILevel.EMERGENT: (
        "Chest pain",
        "Altered mental status",
        "Severe abdominal pain",
        "Shortness of breath",
        "Seizure",
        "Allergic reaction with swelling",
    ),
    ESILevel.URGENT: (
        "Abdominal pain",
        "Back pain",
        "Headache",
        "Laceration",
        "Fever and cough",
        "Urinary symptoms",
        "Extremity pain after fall",
    ),
    ESILevel.LESS_URGENT: (
        "Sore throat",
        "Rash",
        "Minor burn",
        "Earache",
        "Medication refill",
        "Wound recheck",
    ),
    ESILevel.NON_URGENT: (
        "Insect bite",
        "Minor abrasion",
        "Work physical",
        "Prescription question",
        "Cold symptoms x 1 day",
    ),
}


def _generate_initial_vitals(
    rng: random.Random,
    esi_level: ESILevel,
    timestamp: datetime,
) -> VitalSigns:
    """Generate initial vital signs appropriate for the ESI level."""
    if esi_level == ESILevel.RESUSCITATION:
        hr = rng.randint(110, 160)
        sbp = rng.randint(60, 90)
        dbp = rng.randint(30, 50)
        rr = rng.randint(24, 40)
        spo2 = rng.randint(70, 88)
        temp = round(rng.uniform(35.0, 40.5), 1)
        gcs = rng.randint(3, 8)
    elif esi_level == ESILevel.EMERGENT:
        hr = rng.randint(90, 130)
        sbp = rng.randint(85, 160)
        dbp = rng.randint(50, 100)
        rr = rng.randint(18, 30)
        spo2 = rng.randint(85, 95)
        temp = round(rng.uniform(36.0, 39.5), 1)
        gcs = rng.randint(10, 15)
    elif esi_level == ESILevel.URGENT:
        hr = rng.randint(70, 110)
        sbp = rng.randint(100, 160)
        dbp = rng.randint(60, 95)
        rr = rng.randint(14, 22)
        spo2 = rng.randint(93, 99)
        temp = round(rng.uniform(36.5, 39.0), 1)
        gcs = 15
    else:
        hr = rng.randint(60, 100)
        sbp = rng.randint(110, 140)
        dbp = rng.randint(65, 85)
        rr = rng.randint(12, 20)
        spo2 = rng.randint(96, 100)
        temp = round(rng.uniform(36.5, 37.5), 1)
        gcs = 15

    return VitalSigns(
        timestamp=timestamp,
        heart_rate=hr,
        systolic_bp=sbp,
        diastolic_bp=dbp,
        respiratory_rate=rr,
        spo2=spo2,
        temperature=temp,
        gcs=gcs,
        pain_scale=rng.randint(0, 10),
    )


def generate_encounter(
    rng: random.Random,
    patient: Any,
    condition_id: str | None,
    clock: SimulationClock,
) -> Encounter:
    """Generate a deterministic encounter entity.

    Args:
        rng: Seeded Random instance for deterministic generation.
        patient: The patient entity (Patient dataclass or dict with 'id').
        condition_id: Optional OpenEM condition ID for clinical realism.
        clock: The simulation clock for timestamps.

    Returns:
        A frozen Encounter instance.
    """
    encounter_id = f"ENC-{uuid.UUID(int=rng.getrandbits(128)).hex[:8].upper()}"

    # Determine patient ID
    patient_id = patient.id if hasattr(patient, "id") else patient.get("id", "")

    # ESI level distribution: weighted toward 3 (most common in real EDs)
    esi_level = ESILevel(
        rng.choices(
            population=[1, 2, 3, 4, 5],
            weights=[2, 15, 45, 25, 13],
            k=1,
        )[0]
    )

    chief_complaint = rng.choice(_CHIEF_COMPLAINTS[esi_level])

    # Timing
    arrival_time = clock.now()
    triage_delay = rng.randint(1, 15)  # minutes
    triage_time = arrival_time + timedelta(minutes=triage_delay)

    # Bed assignment
    if esi_level == ESILevel.RESUSCITATION:
        bed_assignment = f"TRAUMA-{rng.randint(1, 2):03d}"
    else:
        bed_assignment = f"BED-{rng.randint(1, 20):03d}"

    # Initial vitals at triage
    initial_vitals = _generate_initial_vitals(rng, esi_level, triage_time)

    now = datetime.now(timezone.utc)
    return Encounter(
        id=encounter_id,
        entity_type=EntityType.ENCOUNTER,
        created_at=now,
        updated_at=now,
        patient_id=patient_id,
        chief_complaint=chief_complaint,
        esi_level=esi_level,
        bed_assignment=bed_assignment,
        arrival_time=arrival_time,
        triage_time=triage_time,
        disposition=None,
        attending_id="",
        vitals=(initial_vitals,),
        labs=(),
        imaging=(),
        meds_administered=(),
    )
