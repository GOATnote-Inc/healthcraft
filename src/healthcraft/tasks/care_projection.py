"""Preserve authored mixed care context without inventing administration events."""

from copy import deepcopy
from typing import Any

from healthcraft.entities.encounters import AuthoredCareRecord
from healthcraft.tasks.source_values import require_finite_source

# Reviewed direct-patient fields only. Generic timelines, other patients,
# prior visits, and contingent recommendations retain their narrative scope.
CARE_COLLECTIONS = (
    "active_orders",
    "current_management",
    "current_treatment",
    "ems_interventions",
    "field_interventions",
    "medication_changes",
    "medication_error_details",
    "medications_from_bottles",
    "pending_order",
    "pending_orders",
    "prescribed_medications",
    "procedures_performed",
    "proposed_treatment",
    "psychiatric_medication_timeline",
    "response_to_initial_treatment",
    "sedation_medications",
    "treatments_given",
    "verbal_order_as_received",
    "original_prescriptions",
    "resuscitation_summary",
    "anesthesia_record",
    "transfusion_details",
)


def project_authored_care(patient_data: dict[str, Any]) -> tuple[AuthoredCareRecord, ...]:
    """Keep each supplied collection intact; its prose is not an event parser."""
    records = []
    for collection in CARE_COLLECTIONS:
        if collection not in patient_data:
            continue
        source = patient_data[collection]
        require_finite_source(source)
        records.append(
            AuthoredCareRecord(
                source_collection=collection,
                source_path=f"/patient/{collection}",
                source_data=deepcopy(source),
            )
        )
    return tuple(records)
