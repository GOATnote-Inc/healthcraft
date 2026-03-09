"""Input validation for HEALTHCRAFT MCP tools."""

from __future__ import annotations

import re
from typing import Any


class ValidationError(Exception):
    """Raised when tool input validation fails."""

    pass


# --- ID format patterns ---

_PATIENT_ID_PATTERN = re.compile(r"^PAT-[A-F0-9]{8}$")
_ENCOUNTER_ID_PATTERN = re.compile(r"^ENC-[A-F0-9]{8}$")
_STAFF_ID_PATTERN = re.compile(r"^STAFF-\d{3}$")
_BED_ID_PATTERN = re.compile(r"^(BED|TRAUMA)-\d{3}$")


def validate_patient_id(patient_id: str) -> bool:
    """Validate a patient ID matches the expected format.

    Args:
        patient_id: The patient ID to validate.

    Returns:
        True if valid.
    """
    if not isinstance(patient_id, str):
        return False
    return bool(_PATIENT_ID_PATTERN.match(patient_id))


def validate_encounter_id(encounter_id: str) -> bool:
    """Validate an encounter ID matches the expected format.

    Args:
        encounter_id: The encounter ID to validate.

    Returns:
        True if valid.
    """
    if not isinstance(encounter_id, str):
        return False
    return bool(_ENCOUNTER_ID_PATTERN.match(encounter_id))


def validate_staff_id(staff_id: str) -> bool:
    """Validate a staff ID matches the expected format.

    Args:
        staff_id: The staff ID to validate.

    Returns:
        True if valid.
    """
    if not isinstance(staff_id, str):
        return False
    return bool(_STAFF_ID_PATTERN.match(staff_id))


def validate_bed_id(bed_id: str) -> bool:
    """Validate a bed/location ID matches the expected format.

    Args:
        bed_id: The bed ID to validate.

    Returns:
        True if valid.
    """
    if not isinstance(bed_id, str):
        return False
    return bool(_BED_ID_PATTERN.match(bed_id))


def validate_esi_level(level: int) -> bool:
    """Validate an ESI level is in range 1-5.

    Args:
        level: The ESI level to validate.

    Returns:
        True if valid.
    """
    if not isinstance(level, int):
        return False
    return 1 <= level <= 5


def validate_order_params(params: dict[str, Any]) -> tuple[bool, str]:
    """Validate parameters for an order (lab, imaging, or medication).

    Args:
        params: The order parameters dict.

    Returns:
        Tuple of (is_valid, error_message). Error message is empty if valid.
    """
    if not isinstance(params, dict):
        return False, "Order params must be a dict"

    # Must have encounter_id
    encounter_id = params.get("encounter_id")
    if not encounter_id:
        return False, "Missing required field: encounter_id"
    if not validate_encounter_id(encounter_id):
        return False, f"Invalid encounter_id: {encounter_id}"

    # Must have order_type or item_name
    has_type = bool(params.get("order_type") or params.get("item_name") or params.get("test_name"))
    if not has_type:
        return False, "Missing required field: order_type, item_name, or test_name"

    return True, ""
