"""Transfer entity for the HEALTHCRAFT simulation."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from healthcraft.entities.base import Entity, EntityType


@dataclass(frozen=True)
class Transfer(Entity):
    """Immutable transfer entity representing an inter-facility transfer.

    Extends Entity with fields for incoming/outgoing patient transfers,
    transport logistics, and EMTALA compliance tracking.
    """

    transfer_id: str = ""
    encounter_id: str = ""
    patient_id: str = ""
    direction: str = ""  # "incoming", "outgoing"
    status: str = ""  # "requested", "accepted", "in_transit", "arrived", "cancelled", "declined"
    sending_facility: str = ""
    receiving_facility: str = ""
    reason: str = ""
    transport_mode: str = ""  # "ground_als", "ground_bls", "helicopter", "fixed_wing"
    estimated_time_minutes: int | None = None
    accepting_physician: str = ""
    documentation_complete: bool = False
    emtala_compliant: bool = True
    clinical_summary: str = ""
    requested_at: datetime | None = None
    departed_at: datetime | None = None


# --- Bundled facilities ---

_BUNDLED_FACILITIES: dict[str, dict[str, str]] = {
    "Metro Level I Trauma Center": {
        "type": "level_i_trauma",
        "address": "1200 University Ave",
    },
    "Regional Level I Trauma Center": {
        "type": "level_i_trauma",
        "address": "4500 Medical Pkwy",
    },
    "Riverside Community Hospital": {
        "type": "community",
        "address": "780 Riverside Dr",
    },
    "Valley General Hospital": {
        "type": "community",
        "address": "320 Valley Rd",
    },
    "Children's Medical Center": {
        "type": "childrens",
        "address": "900 Pediatric Blvd",
    },
    "Regional Burn Center": {
        "type": "burn",
        "address": "155 Burn Unit Ln",
    },
    "Lakeview Psychiatric Hospital": {
        "type": "psychiatric",
        "address": "2100 Lakeview Cir",
    },
    "Pinecrest Rehabilitation Facility": {
        "type": "rehabilitation",
        "address": "610 Pinecrest Way",
    },
}

_HOME_FACILITY = "Mercy Point Emergency Department"

_TRANSFER_REASONS = (
    "Higher level of care",
    "Specialty not available",
    "Bed unavailable",
    "Burn unit required",
    "Pediatric specialty required",
    "Psychiatric evaluation required",
    "Neurosurgical intervention needed",
    "Cardiac catheterization required",
    "Rehabilitation placement",
    "Patient/family request",
)

_TRANSPORT_MODES = ("ground_als", "ground_bls", "helicopter", "fixed_wing")

_TRANSFER_STATUSES = (
    "requested",
    "accepted",
    "in_transit",
    "arrived",
    "cancelled",
    "declined",
)

_ACCEPTING_PHYSICIANS = (
    "Dr. A. Ramirez",
    "Dr. S. Patel",
    "Dr. K. Johansson",
    "Dr. M. Tanaka",
    "Dr. L. Carter",
    "Dr. R. Ahmed",
    "Dr. J. Okafor",
    "Dr. C. Lindstrom",
)

_CLINICAL_SUMMARY_TEMPLATES = (
    "{age}yo {sex} presenting with {complaint}. Hemodynamically {stability}. "
    "Requires transfer for {reason}.",
    "{age}yo {sex} with {complaint}. Current vitals {stability}. Transfer indicated: {reason}.",
    "{age}yo {sex}, {complaint}. {stability} on current management. Transferring for {reason}.",
)


def load_facilities() -> dict[str, dict[str, str]]:
    """Return the bundled facility registry.

    Returns:
        A dict mapping facility name to metadata (type, address).
    """
    return dict(_BUNDLED_FACILITIES)


def _build_clinical_summary(rng: random.Random, reason: str) -> str:
    """Build a short clinical summary string for the transfer record."""
    age = rng.randint(18, 92)
    sex = rng.choice(("male", "female"))
    complaint = rng.choice(
        (
            "chest pain",
            "severe burns",
            "altered mental status",
            "multisystem trauma",
            "acute abdomen",
            "respiratory failure",
            "pediatric seizures",
            "acute psychosis",
            "STEMI",
            "suicidal ideation",
        )
    )
    stability = rng.choice(("stable", "unstable", "borderline stable"))
    template = rng.choice(_CLINICAL_SUMMARY_TEMPLATES)
    return template.format(
        age=age,
        sex=sex,
        complaint=complaint,
        stability=stability,
        reason=reason.lower(),
    )


def _pick_facility_pair(
    rng: random.Random,
    direction: str,
    reason: str,
) -> tuple[str, str]:
    """Choose sending/receiving facilities based on direction and reason.

    For outgoing transfers, the sending facility is Mercy Point.
    For incoming transfers, the receiving facility is Mercy Point.
    The partner facility is selected from the bundled set, biased by reason.
    """
    # Map reasons to preferred facility types
    reason_facility_preference: dict[str, tuple[str, ...]] = {
        "Burn unit required": ("burn",),
        "Pediatric specialty required": ("childrens",),
        "Psychiatric evaluation required": ("psychiatric",),
        "Rehabilitation placement": ("rehabilitation",),
        "Higher level of care": ("level_i_trauma",),
        "Neurosurgical intervention needed": ("level_i_trauma",),
        "Cardiac catheterization required": ("level_i_trauma",),
    }

    preferred_types = reason_facility_preference.get(reason, ())
    facility_names = list(_BUNDLED_FACILITIES.keys())

    # Try to pick a facility matching the preferred type
    partner = ""
    if preferred_types:
        candidates = [
            name for name, meta in _BUNDLED_FACILITIES.items() if meta["type"] in preferred_types
        ]
        if candidates:
            partner = rng.choice(candidates)

    if not partner:
        partner = rng.choice(facility_names)

    if direction == "outgoing":
        return _HOME_FACILITY, partner
    return partner, _HOME_FACILITY


def generate_transfer(
    rng: random.Random,
    encounter_id: str = "",
    patient_id: str = "",
) -> Transfer:
    """Generate a deterministic transfer entity.

    Args:
        rng: Seeded Random instance for deterministic generation.
        encounter_id: The encounter ID this transfer belongs to.
        patient_id: The patient ID being transferred.

    Returns:
        A frozen Transfer instance.
    """
    transfer_id = f"XFR-{uuid.UUID(int=rng.getrandbits(128)).hex[:6].upper()}"

    direction = rng.choices(
        population=["outgoing", "incoming"],
        weights=[70, 30],
        k=1,
    )[0]

    reason = rng.choice(_TRANSFER_REASONS)
    sending_facility, receiving_facility = _pick_facility_pair(rng, direction, reason)

    # Status distribution: most transfers are completed or in progress
    status = rng.choices(
        population=list(_TRANSFER_STATUSES),
        weights=[15, 30, 20, 20, 10, 5],
        k=1,
    )[0]

    # Transport mode: ground ALS most common, helicopter for critical
    if reason in (
        "Higher level of care",
        "Neurosurgical intervention needed",
        "Cardiac catheterization required",
    ):
        transport_mode = rng.choices(
            _TRANSPORT_MODES,
            weights=[50, 5, 35, 10],
            k=1,
        )[0]
    else:
        transport_mode = rng.choices(
            _TRANSPORT_MODES,
            weights=[45, 35, 15, 5],
            k=1,
        )[0]

    # Estimated transport time based on mode
    if transport_mode == "ground_bls":
        estimated_time_minutes = rng.randint(15, 60)
    elif transport_mode == "ground_als":
        estimated_time_minutes = rng.randint(15, 45)
    elif transport_mode == "helicopter":
        estimated_time_minutes = rng.randint(20, 90)
    else:  # fixed_wing
        estimated_time_minutes = rng.randint(60, 240)

    accepting_physician = rng.choice(_ACCEPTING_PHYSICIANS)

    # Documentation and EMTALA compliance
    documentation_complete = status in ("in_transit", "arrived")
    # EMTALA non-compliance is rare but important to model
    emtala_compliant = rng.random() > 0.05

    clinical_summary = _build_clinical_summary(rng, reason)

    # Timestamps
    now = datetime.now(timezone.utc)
    requested_offset_minutes = rng.randint(30, 360)
    requested_at = now - timedelta(minutes=requested_offset_minutes)

    departed_at: datetime | None = None
    if status in ("in_transit", "arrived"):
        depart_delay = rng.randint(15, 90)
        departed_at = requested_at + timedelta(minutes=depart_delay)

    return Transfer(
        id=transfer_id,
        entity_type=EntityType.TRANSFER,
        created_at=now,
        updated_at=now,
        transfer_id=transfer_id,
        encounter_id=encounter_id,
        patient_id=patient_id,
        direction=direction,
        status=status,
        sending_facility=sending_facility,
        receiving_facility=receiving_facility,
        reason=reason,
        transport_mode=transport_mode,
        estimated_time_minutes=estimated_time_minutes,
        accepting_physician=accepting_physician,
        documentation_complete=documentation_complete,
        emtala_compliant=emtala_compliant,
        clinical_summary=clinical_summary,
        requested_at=requested_at,
        departed_at=departed_at,
    )
