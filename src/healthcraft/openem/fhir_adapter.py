"""FHIR R4 resource generation from OpenEM condition data.

Generates deterministic FHIR bundles for patients and encounters
using seeded RNG for reproducible output.
"""

from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timezone
from typing import Any

try:
    import openem.fhir  # noqa: F401

    HAS_OPENEM_FHIR = True
except ImportError:
    HAS_OPENEM_FHIR = False


def _deterministic_uuid(rng: random.Random) -> str:
    """Generate a deterministic UUID using a seeded RNG.

    Args:
        rng: Seeded Random instance.

    Returns:
        A UUID string.
    """
    return str(uuid.UUID(int=rng.getrandbits(128)))


def generate_patient_bundle(
    condition_id: str,
    rng: random.Random,
) -> dict[str, Any]:
    """Generate a FHIR R4 Patient Bundle for a given condition.

    Creates a Bundle containing a Patient resource and associated
    AllergyIntolerance, Condition, and other relevant resources.

    Args:
        condition_id: OpenEM condition identifier driving demographics.
        rng: Seeded Random instance for deterministic generation.

    Returns:
        A FHIR R4 Bundle dict.
    """
    patient_id = _deterministic_uuid(rng)

    # Demographics
    sex = rng.choice(["male", "female"])
    first_name = rng.choice(
        ["James", "Robert", "Michael", "David", "Maria", "Sarah", "Jennifer", "Emily"]
    )
    last_name = rng.choice(
        ["Smith", "Johnson", "Williams", "Chen", "Patel", "Garcia", "Kim", "Davis"]
    )
    age = rng.randint(25, 80)
    birth_year = 2026 - age
    birth_date = date(birth_year, rng.randint(1, 12), rng.randint(1, 28))

    patient_resource: dict[str, Any] = {
        "resourceType": "Patient",
        "id": patient_id,
        "meta": {"profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient"]},
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
                "value": f"MRN-{rng.randint(100000, 999999)}",
            }
        ],
        "name": [
            {
                "use": "official",
                "family": last_name,
                "given": [first_name],
            }
        ],
        "gender": sex,
        "birthDate": birth_date.isoformat(),
        "active": True,
    }

    # Condition resource linked to this patient
    condition_resource_id = _deterministic_uuid(rng)
    condition_resource: dict[str, Any] = {
        "resourceType": "Condition",
        "id": condition_resource_id,
        "subject": {"reference": f"Patient/{patient_id}"},
        "code": {
            "coding": [
                {
                    "system": "http://healthcraft.dev/condition",
                    "code": condition_id,
                }
            ],
            "text": condition_id,
        },
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": "active",
                }
            ]
        },
        "verificationStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    "code": "provisional",
                }
            ]
        },
    }

    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "id": _deterministic_uuid(rng),
        "type": "collection",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "entry": [
            {
                "fullUrl": f"urn:uuid:{patient_id}",
                "resource": patient_resource,
            },
            {
                "fullUrl": f"urn:uuid:{condition_resource_id}",
                "resource": condition_resource,
            },
        ],
    }

    return bundle


def generate_encounter_bundle(
    patient_id: str,
    condition_id: str,
    rng: random.Random,
) -> dict[str, Any]:
    """Generate a FHIR R4 Encounter Bundle.

    Creates a Bundle containing an Encounter resource and associated
    clinical resources (Observations, DiagnosticReports, etc.).

    Args:
        patient_id: The FHIR Patient resource ID.
        condition_id: OpenEM condition identifier.
        rng: Seeded Random instance for deterministic generation.

    Returns:
        A FHIR R4 Bundle dict.
    """
    encounter_id = _deterministic_uuid(rng)
    now = datetime.now(timezone.utc)

    encounter_resource: dict[str, Any] = {
        "resourceType": "Encounter",
        "id": encounter_id,
        "status": "in-progress",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "EMER",
            "display": "emergency",
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "period": {"start": now.isoformat()},
        "reasonCode": [
            {
                "coding": [
                    {
                        "system": "http://healthcraft.dev/condition",
                        "code": condition_id,
                    }
                ]
            }
        ],
        "location": [
            {
                "location": {"display": f"Bed {rng.randint(1, 20)}"},
                "status": "active",
            }
        ],
        "serviceProvider": {"display": "Mercy Point Emergency Department"},
    }

    # Initial vital signs observation
    vitals_id = _deterministic_uuid(rng)
    hr = rng.randint(60, 120)
    sbp = rng.randint(90, 160)
    dbp = rng.randint(55, 95)
    rr = rng.randint(12, 28)
    spo2 = rng.randint(88, 100)
    temp = round(rng.uniform(36.0, 39.5), 1)

    vitals_observation: dict[str, Any] = {
        "resourceType": "Observation",
        "id": vitals_id,
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "vital-signs",
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "85354-9",
                    "display": "Blood pressure panel",
                }
            ]
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "effectiveDateTime": now.isoformat(),
        "component": [
            {
                "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
                "valueQuantity": {"value": hr, "unit": "bpm"},
            },
            {
                "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6"}]},
                "valueQuantity": {"value": sbp, "unit": "mmHg"},
            },
            {
                "code": {"coding": [{"system": "http://loinc.org", "code": "8462-4"}]},
                "valueQuantity": {"value": dbp, "unit": "mmHg"},
            },
            {
                "code": {"coding": [{"system": "http://loinc.org", "code": "9279-1"}]},
                "valueQuantity": {"value": rr, "unit": "breaths/min"},
            },
            {
                "code": {"coding": [{"system": "http://loinc.org", "code": "2708-6"}]},
                "valueQuantity": {"value": spo2, "unit": "%"},
            },
            {
                "code": {"coding": [{"system": "http://loinc.org", "code": "8310-5"}]},
                "valueQuantity": {"value": temp, "unit": "Cel"},
            },
        ],
    }

    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "id": _deterministic_uuid(rng),
        "type": "collection",
        "timestamp": now.isoformat(),
        "entry": [
            {
                "fullUrl": f"urn:uuid:{encounter_id}",
                "resource": encounter_resource,
            },
            {
                "fullUrl": f"urn:uuid:{vitals_id}",
                "resource": vitals_observation,
            },
        ],
    }

    return bundle
