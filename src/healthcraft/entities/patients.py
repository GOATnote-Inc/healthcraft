"""Patient entity for the HEALTHCRAFT simulation."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

from healthcraft.entities.base import Entity, EntityType


@dataclass(frozen=True)
class Patient(Entity):
    """Immutable patient entity with demographics and medical history.

    Extends Entity with emergency-medicine-relevant patient attributes.
    """

    mrn: str = ""
    first_name: str = ""
    last_name: str = ""
    dob: date | None = None
    sex: str = ""  # M, F, X
    allergies: tuple[str, ...] = ()
    medications: tuple[str, ...] = ()
    pmh: tuple[str, ...] = ()  # Past medical history
    insurance_id: str = ""
    advance_directives: str = ""  # "full_code", "dnr", "dnr_dni", "comfort_only", ""
    prior_visit_ids: tuple[str, ...] = ()


# --- Generation data ---

_FIRST_NAMES_M = (
    "James",
    "Robert",
    "Michael",
    "William",
    "David",
    "Richard",
    "Joseph",
    "Thomas",
    "Christopher",
    "Daniel",
    "Carlos",
    "Ahmed",
    "Wei",
    "Hiroshi",
    "Pavel",
)
_FIRST_NAMES_F = (
    "Mary",
    "Patricia",
    "Jennifer",
    "Linda",
    "Elizabeth",
    "Barbara",
    "Susan",
    "Jessica",
    "Sarah",
    "Karen",
    "Maria",
    "Fatima",
    "Mei",
    "Yuki",
    "Olga",
)
_LAST_NAMES = (
    "Smith",
    "Johnson",
    "Williams",
    "Brown",
    "Jones",
    "Garcia",
    "Miller",
    "Davis",
    "Rodriguez",
    "Martinez",
    "Chen",
    "Kim",
    "Patel",
    "Nguyen",
    "Kowalski",
    "Al-Farsi",
    "Tanaka",
    "Okafor",
    "Johansson",
    "Mueller",
)
_COMMON_ALLERGIES = (
    "Penicillin",
    "Sulfa",
    "Aspirin",
    "Ibuprofen",
    "Codeine",
    "Morphine",
    "Latex",
    "Contrast dye",
    "Cephalosporins",
    "Vancomycin",
)
_COMMON_MEDICATIONS = (
    "Lisinopril 10mg",
    "Metformin 500mg",
    "Atorvastatin 20mg",
    "Omeprazole 20mg",
    "Amlodipine 5mg",
    "Metoprolol 25mg",
    "Levothyroxine 50mcg",
    "Albuterol inhaler",
    "Aspirin 81mg",
    "Gabapentin 300mg",
    "Sertraline 50mg",
    "Hydrochlorothiazide 25mg",
)
_COMMON_PMH = (
    "Hypertension",
    "Type 2 Diabetes",
    "Hyperlipidemia",
    "GERD",
    "Asthma",
    "COPD",
    "Coronary artery disease",
    "Atrial fibrillation",
    "Hypothyroidism",
    "Osteoarthritis",
    "Depression",
    "Anxiety",
    "Chronic kidney disease",
    "Heart failure",
    "Prior stroke",
)
_ADVANCE_DIRECTIVE_OPTIONS = ("full_code", "dnr", "dnr_dni", "comfort_only", "")


def generate_patient(
    rng: random.Random,
    condition_id: str | None = None,
) -> Patient:
    """Generate a deterministic patient entity.

    Args:
        rng: Seeded Random instance for deterministic generation.
        condition_id: Optional OpenEM condition ID to influence demographics.

    Returns:
        A frozen Patient instance.
    """
    patient_id = f"PAT-{uuid.UUID(int=rng.getrandbits(128)).hex[:8].upper()}"
    mrn = f"MRN-{rng.randint(100000, 999999)}"

    sex = rng.choice(["M", "F"])
    if sex == "M":
        first_name = rng.choice(_FIRST_NAMES_M)
    else:
        first_name = rng.choice(_FIRST_NAMES_F)
    last_name = rng.choice(_LAST_NAMES)

    # Age distribution skewed toward older for ED population
    age = rng.choices(
        population=list(range(18, 95)),
        weights=[1] * 12 + [2] * 20 + [3] * 20 + [4] * 15 + [2] * 10,
        k=1,
    )[0]
    birth_year = 2026 - age
    dob = date(birth_year, rng.randint(1, 12), rng.randint(1, 28))

    # Allergies: 70% have none, 20% have 1, 10% have 2+
    allergy_roll = rng.random()
    if allergy_roll < 0.7:
        allergies: tuple[str, ...] = ()
    elif allergy_roll < 0.9:
        allergies = (rng.choice(_COMMON_ALLERGIES),)
    else:
        count = rng.randint(2, 3)
        allergies = tuple(rng.sample(_COMMON_ALLERGIES, min(count, len(_COMMON_ALLERGIES))))

    # Medications: correlate with age
    med_count = 0
    if age > 50:
        med_count = rng.randint(1, 4)
    elif age > 35:
        med_count = rng.randint(0, 2)
    else:
        med_count = rng.randint(0, 1)
    medications = tuple(rng.sample(_COMMON_MEDICATIONS, min(med_count, len(_COMMON_MEDICATIONS))))

    # PMH: correlate with age
    pmh_count = 0
    if age > 60:
        pmh_count = rng.randint(2, 5)
    elif age > 40:
        pmh_count = rng.randint(0, 3)
    else:
        pmh_count = rng.randint(0, 1)
    pmh = tuple(rng.sample(_COMMON_PMH, min(pmh_count, len(_COMMON_PMH))))

    insurance_id = f"INS-{rng.randint(100000000, 999999999)}"

    # Advance directives: mostly full code, more DNR/DNI in elderly
    if age > 75:
        advance_directives = rng.choices(
            _ADVANCE_DIRECTIVE_OPTIONS, weights=[50, 25, 15, 5, 5], k=1
        )[0]
    else:
        advance_directives = rng.choices(_ADVANCE_DIRECTIVE_OPTIONS, weights=[85, 5, 3, 1, 6], k=1)[
            0
        ]

    now = datetime.now(timezone.utc)
    return Patient(
        id=patient_id,
        entity_type=EntityType.PATIENT,
        created_at=now,
        updated_at=now,
        mrn=mrn,
        first_name=first_name,
        last_name=last_name,
        dob=dob,
        sex=sex,
        allergies=allergies,
        medications=medications,
        pmh=pmh,
        insurance_id=insurance_id,
        advance_directives=advance_directives,
        prior_visit_ids=(),
    )


def patient_to_fhir(patient: Patient) -> dict:
    """Convert a Patient entity to a FHIR R4 Patient resource.

    Args:
        patient: The Patient entity to convert.

    Returns:
        A dict representing a valid FHIR R4 Patient resource.
    """
    resource: dict = {
        "resourceType": "Patient",
        "id": patient.id,
        "identifier": [
            {
                "type": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                            "code": "MR",
                        }
                    ]
                },
                "value": patient.mrn,
            }
        ],
        "name": [
            {
                "use": "official",
                "family": patient.last_name,
                "given": [patient.first_name],
            }
        ],
        "gender": {
            "M": "male",
            "F": "female",
            "X": "other",
        }.get(patient.sex, "unknown"),
        "active": True,
    }

    if patient.dob:
        resource["birthDate"] = patient.dob.isoformat()

    if patient.insurance_id:
        resource["identifier"].append(
            {
                "type": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                            "code": "SN",
                        }
                    ]
                },
                "value": patient.insurance_id,
            }
        )

    return resource
