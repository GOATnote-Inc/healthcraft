"""State-mutating MCP tool handlers for the HEALTHCRAFT ED simulation.

Implements the 6 write tools from Wave 3 (Corecraft Section 5):
    createClinicalOrder, updateTaskStatus, updateEncounter,
    updatePatientRecord, registerPatient, applyProtocol

Each function takes (world: WorldState, params: dict) -> dict and returns
either {"status": "ok", "data": ...} or {"status": "error", "code": ..., "message": ...}.

Entities are frozen dataclasses. All mutations produce new instances via
dataclasses.replace().
"""

from __future__ import annotations

import hashlib
import os
import random
import uuid
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import date
from typing import Any

from healthcraft.entities.base import EntityType
from healthcraft.entities.clinical_tasks import generate_clinical_task
from healthcraft.entities.encounters import Encounter
from healthcraft.entities.patients import Patient
from healthcraft.world.state import WorldState

# --- Valid enum values ---

_VALID_ORDER_TYPES = frozenset(
    {"lab", "imaging", "medication", "procedure", "consult", "blood_product"}
)

_ORDER_TYPE_TO_TASK_TYPE = {
    "lab": "lab_draw",
    "imaging": "imaging",
    "medication": "medication_admin",
    "procedure": "procedure",
    "consult": "consult",
    "blood_product": "blood_admin",
}

_VALID_TASK_STATUSES = frozenset({"pending", "in_progress", "completed", "cancelled", "on_hold"})

_TERMINAL_TASK_STATUSES = frozenset({"completed", "cancelled"})


def _idempotent_tools_enabled() -> bool:
    """Idempotent tools default to ON (PR-B / WS-5).

    Opt-out for V8 byte-identical replay: ``HC_IDEMPOTENT_TOOLS=0``. The
    flag itself is preserved so the integrity test suite that replays V8
    trajectories without expecting Phase-4 dedup semantics can keep
    passing.
    """
    return os.environ.get("HC_IDEMPOTENT_TOOLS", "1") != "0"


def _deterministic_order_id(encounter_id: str, order_type: str, idem_key: str) -> str:
    """Derive a deterministic order ID from (encounter_id, order_type, idempotency_key)."""
    combined = f"{encounter_id}:{order_type}:{idem_key}"
    h = hashlib.sha256(combined.encode()).hexdigest()[:8]
    return f"ORD-{h}"


def _deterministic_patient_id(idem_key: str, first_name: str, last_name: str) -> str:
    """Derive a deterministic patient ID from (idempotency_key, first_name, last_name)."""
    combined = f"patient:{idem_key}:{first_name}:{last_name}"
    h = hashlib.sha256(combined.encode()).hexdigest()[:8]
    return f"PAT-{h.upper()}"


def _is_idempotent_replay(world: WorldState, tool_name: str, idem_key: str) -> bool:
    """Return True iff a prior committed (ok-status) call recorded the same
    ``(tool_name, idempotency_key)``. The current call is NOT yet in the
    audit log when handlers are invoked, so this scans only previously-
    committed entries — first attempts execute normally; second-and-later
    attempts dedup.

    Tool name comparison is case-insensitive so the camelCase MCP name and
    the snake_case handler name both match.
    """
    if not idem_key:
        return False
    tn_lower = tool_name.lower()
    for entry in world.audit_log:
        if (
            entry.idempotency_key == idem_key
            and entry.tool_name.lower() == tn_lower
            and entry.result_summary == "ok"
        ):
            return True
    return False


# --- Helpers ---


def _ok(data: Any) -> dict[str, Any]:
    """Build a detached success response without exposing mutable world records."""
    return {"status": "ok", "data": deepcopy(data)}


def _error(code: str, message: str) -> dict[str, Any]:
    """Build an error response."""
    return {"status": "error", "code": code, "message": message}


def _require(params: dict, *keys: str) -> str | None:
    """Return the first missing required key, or None if all present."""
    for key in keys:
        if key not in params or params[key] is None:
            return key
    return None


def _entity_to_dict(entity: Any) -> Any:
    """Convert an entity to a dict, handling both dataclasses and plain dicts."""
    if hasattr(entity, "__dataclass_fields__"):
        return asdict(entity)
    return entity


def _get_field(entity: Any, name: str, default: Any = None) -> Any:
    """Read generated dataclasses and task-injected dictionary records alike."""
    return entity.get(name, default) if isinstance(entity, dict) else getattr(entity, name, default)


def _append_records(existing: Any, additions: Any, *, dedup: bool) -> tuple:
    """Append records in order without requiring structured records to be hashable."""
    if not isinstance(additions, (list, tuple)):
        additions = [additions]
    combined = deepcopy(tuple(existing) + tuple(additions))
    if not dedup:
        return combined
    unique = []
    for record in combined:
        if record not in unique:
            unique.append(record)
    return tuple(unique)


def _registration_data(world: WorldState, patient: Any) -> dict:
    """Include documented IDs while retaining the legacy patient response fields."""
    data = dict(_entity_to_dict(patient))
    data["patient_id"] = data["id"]
    for encounter_id, encounter in world.list_entities("encounter").items():
        if _get_field(encounter, "patient_id") == data["id"]:
            data["encounter_id"] = encounter_id
            break
    return data


_ROMAN_TO_ARABIC = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5"}
_ARABIC_TO_ROMAN = {v: k for k, v in _ROMAN_TO_ARABIC.items()}


def _normalize_protocol_name(name: str) -> str:
    """Normalize protocol name for comparison.

    Strips underscores, hyphens, and extra whitespace, then lowercases.
    Also normalizes roman numerals to arabic (I->1, II->2) and vice versa
    so "trauma_activation_level1" matches "Trauma Activation Level I".
    """
    result = name.lower().replace("_", " ").replace("-", " ")
    # Normalize roman numeral suffixes to arabic
    words = result.split()
    normalized_words = []
    for w in words:
        if w in _ROMAN_TO_ARABIC:
            normalized_words.append(_ROMAN_TO_ARABIC[w])
        elif w in _ARABIC_TO_ROMAN:
            normalized_words.append(w)  # keep arabic as-is
        else:
            # Handle "level1" -> "level 1"
            import re

            m = re.match(r"^(\D+)(\d+)$", w)
            if m:
                normalized_words.extend([m.group(1), m.group(2)])
            else:
                normalized_words.append(w)
            continue
        continue
    return " ".join(normalized_words).strip()


# ---------------------------------------------------------------------------
# 1. create_clinical_order
# ---------------------------------------------------------------------------


def create_clinical_order(world: WorldState, params: dict) -> dict:
    """Create a new clinical order and its associated clinical task.

    Params:
        encounter_id (required): The encounter to order against.
        order_type (required): One of "lab", "imaging", "medication",
            "procedure", "consult".
        details (required): Dict with order-specific information.

    For medication orders, validates against the patient's allergy list.
    Returns the created order dict on success.
    """
    missing = _require(params, "encounter_id", "order_type", "details")
    if missing is not None:
        return _error("missing_param", f"Required parameter missing: {missing}")

    encounter_id: str = params["encounter_id"]
    order_type: str = params["order_type"]
    details: dict = params["details"]

    if order_type not in _VALID_ORDER_TYPES:
        return _error(
            "invalid_order_type",
            f"order_type must be one of: {', '.join(sorted(_VALID_ORDER_TYPES))}",
        )

    if not isinstance(details, dict):
        return _error("invalid_details", "details must be a dict")

    # Resolve encounter
    encounter = world.get_entity("encounter", encounter_id)
    if encounter is None:
        return _error("encounter_not_found", f"Encounter not found: {encounter_id}")

    # --- Medication allergy check ---
    if order_type == "medication":
        patient_id = (
            encounter.patient_id
            if hasattr(encounter, "patient_id")
            else encounter.get("patient_id", "")
        )
        if patient_id:
            patient = world.get_entity("patient", patient_id)
            if patient is not None:
                allergies: tuple | list
                if hasattr(patient, "allergies"):
                    allergies = patient.allergies
                elif isinstance(patient, dict):
                    allergies = patient.get("allergies", ())
                else:
                    allergies = ()

                medication_name = details.get("medication", details.get("name", ""))
                if medication_name:
                    if not isinstance(medication_name, str):
                        return _error("invalid_details", "Medication name must be a string")
                    med_lower = medication_name.lower()
                    for allergy in allergies:
                        allergy_name = allergy.get("name") if isinstance(allergy, dict) else allergy
                        if not isinstance(allergy_name, str) or not allergy_name.strip():
                            return _error(
                                "invalid_patient_data", "Patient allergy must have a nonempty name"
                            )
                        allergy_lower = allergy_name.strip().lower()
                        if allergy_lower in med_lower or med_lower in allergy_lower:
                            return _error(
                                "allergy_conflict",
                                f"Medication '{medication_name}' conflicts with "
                                f"patient allergy '{allergy_name}'",
                            )

    # Build the order entity (stored as a plain dict, not a dataclass)
    idem_key = params.get("idempotency_key", "")

    if _idempotent_tools_enabled() and idem_key:
        # Deterministic order ID from (encounter_id, order_type, key)
        order_id = _deterministic_order_id(encounter_id, order_type, idem_key)
        existing = world.get_entity("order", order_id)
        if existing is not None:
            # Deduplicated: return existing order without creating a new one
            result = _ok(existing if isinstance(existing, dict) else _entity_to_dict(existing))
            result["deduplicated"] = True
            return result
    else:
        order_id = f"ORD-{uuid.uuid4().hex[:8]}"

    order: dict[str, Any] = {
        "id": order_id,
        "encounter_id": encounter_id,
        "order_type": order_type,
        "details": deepcopy(details),
        "status": "pending",
        "ordered_at": world.timestamp.isoformat(),
        "ordered_by": "attending",
    }
    world.put_entity("order", order_id, order)

    # Create a corresponding clinical task
    task_type = _ORDER_TYPE_TO_TASK_TYPE[order_type]
    rng = random.Random(hash(order_id))
    task = generate_clinical_task(rng, encounter_id, task_type)
    world.put_entity("clinical_task", task.id, task)

    return _ok(order)


# ---------------------------------------------------------------------------
# 2. update_task_status
# ---------------------------------------------------------------------------


def update_task_status(world: WorldState, params: dict) -> dict:
    """Update the status of an existing clinical task.

    Params:
        task_id (required): The clinical task ID to update.
        status (required): New status — one of "pending", "in_progress",
            "completed", "cancelled", "on_hold".
        notes (optional): Additional notes to attach.

    Handles both frozen dataclass and plain dict task entities.
    """
    missing = _require(params, "task_id", "status")
    if missing is not None:
        return _error("missing_param", f"Required parameter missing: {missing}")

    task_id: str = params["task_id"]
    new_status: str = params["status"]

    if new_status not in _VALID_TASK_STATUSES:
        return _error(
            "invalid_status",
            f"status must be one of: {', '.join(sorted(_VALID_TASK_STATUSES))}",
        )

    task = world.get_entity("clinical_task", task_id)
    if task is None:
        return _error("task_not_found", f"Clinical task not found: {task_id}")

    # Idempotency: dedup on prior committed call with same key (PR-B / WS-5).
    idem_key = str(params.get("idempotency_key", "") or "")
    if (
        _idempotent_tools_enabled()
        and idem_key
        and _is_idempotent_replay(world, "updateTaskStatus", idem_key)
    ):
        result = _ok(_entity_to_dict(task) if hasattr(task, "__dataclass_fields__") else task)
        result["deduplicated"] = True
        return result

    # Terminal status guard (flag-gated)
    if _idempotent_tools_enabled():
        current_status = task.status if hasattr(task, "status") else task.get("status", "")
        if current_status in _TERMINAL_TASK_STATUSES:
            result = _ok(
                _entity_to_dict(task) if hasattr(task, "__dataclass_fields__") else task,
            )
            result["deduplicated"] = True
            return result

    notes = params.get("notes")

    if hasattr(task, "__dataclass_fields__"):
        # Frozen dataclass — use replace
        changes: dict[str, Any] = {"status": new_status}
        if notes is not None:
            changes["notes"] = notes
        if new_status == "completed":
            changes["completed_time"] = world.timestamp
        updated_task = replace(task, **changes)
        world.put_entity("clinical_task", task_id, updated_task)
        return _ok(_entity_to_dict(updated_task))
    else:
        # Plain dict — update in-place
        task["status"] = new_status
        if notes is not None:
            task["notes"] = notes
        if new_status == "completed":
            task["completed_time"] = world.timestamp.isoformat()
        world.put_entity("clinical_task", task_id, task)
        return _ok(task)


# ---------------------------------------------------------------------------
# 3. update_encounter
# ---------------------------------------------------------------------------


def update_encounter(world: WorldState, params: dict) -> dict:
    """Update fields on an existing encounter.

    Params:
        encounter_id (required): The encounter to update.
        disposition (optional): New disposition value.
        notes (optional): Notes stored as a linked clinical note and encounter history.
        bed_assignment (optional): New bed assignment.
        attending_id (optional): New attending physician ID.

    Only fields present in params are updated. Uses dataclasses.replace()
    for frozen dataclass encounters.
    """
    missing = _require(params, "encounter_id")
    if missing is not None:
        return _error("missing_param", f"Required parameter missing: {missing}")

    encounter_id: str = params["encounter_id"]
    encounter = world.get_entity("encounter", encounter_id)
    if encounter is None:
        return _error("encounter_not_found", f"Encounter not found: {encounter_id}")

    # Idempotency: dedup on prior committed call with same key (PR-B / WS-5).
    idem_key = str(params.get("idempotency_key", "") or "")
    if (
        _idempotent_tools_enabled()
        and idem_key
        and _is_idempotent_replay(world, "updateEncounter", idem_key)
    ):
        result = _ok(
            _entity_to_dict(encounter) if hasattr(encounter, "__dataclass_fields__") else encounter
        )
        result["deduplicated"] = True
        return result

    # Collect only the fields that were explicitly provided
    updatable_fields = ("disposition", "bed_assignment", "attending_id")
    changes: dict[str, Any] = {}
    for field in updatable_fields:
        if field in params:
            changes[field] = params[field]

    if not changes and "notes" not in params:
        return _error("no_updates", "No updatable fields provided")

    note = None
    if "notes" in params:
        if not isinstance(params["notes"], str):
            return _error("invalid_param", "notes must be a string")
        changes["clinical_notes"] = tuple(_get_field(encounter, "clinical_notes", ())) + (
            ("Progress Note", params["notes"]),
        )
        index = len(world.list_entities("clinical_note"))
        while True:
            basis = f"{encounter_id}:{world.timestamp.isoformat()}:{index}"
            note_id = f"NOTE-{hashlib.sha256(basis.encode()).hexdigest()[:8].upper()}"
            if world.get_entity("clinical_note", note_id) is None:
                break
            index += 1
        note = {
            "id": note_id,
            "entity_type": EntityType.CLINICAL_NOTE,
            "created_at": world.timestamp,
            "updated_at": world.timestamp,
            "note_type": "progress_note",
            "encounter_id": encounter_id,
            "patient_id": _get_field(encounter, "patient_id", ""),
            "content": params["notes"],
            "author": _get_field(encounter, "attending_id", "") or "attending",
        }
    changes["updated_at"] = world.timestamp
    if hasattr(encounter, "__dataclass_fields__"):
        updated_encounter = replace(encounter, **changes)
    else:
        updated_encounter = {**encounter, **changes}
    world.put_entity("encounter", encounter_id, updated_encounter)
    if note is not None:
        world.put_entity("clinical_note", note["id"], note)
    return _ok(_entity_to_dict(updated_encounter))


# ---------------------------------------------------------------------------
# 4. update_patient_record
# ---------------------------------------------------------------------------


def update_patient_record(world: WorldState, params: dict) -> dict:
    """Update a patient's record, appending to list fields.

    Params:
        patient_id (required): The patient to update.
        allergies (optional): List of allergies to APPEND.
        advance_directives (optional): New advance directives value (replaces).
        medications (optional): List of medications to APPEND.

    For allergies and medications, new values are appended to the existing
    tuples rather than replacing them.
    """
    missing = _require(params, "patient_id")
    if missing is not None:
        return _error("missing_param", f"Required parameter missing: {missing}")

    patient_id: str = params["patient_id"]
    patient = world.get_entity("patient", patient_id)
    if patient is None:
        return _error("patient_not_found", f"Patient not found: {patient_id}")

    # Idempotency: dedup on prior committed call with same key (PR-B / WS-5).
    idem_key = str(params.get("idempotency_key", "") or "")
    if (
        _idempotent_tools_enabled()
        and idem_key
        and _is_idempotent_replay(world, "updatePatientRecord", idem_key)
    ):
        result = _ok(
            _entity_to_dict(patient) if hasattr(patient, "__dataclass_fields__") else patient
        )
        result["deduplicated"] = True
        return result

    changes: dict[str, Any] = {}

    # Append-mode fields: allergies and medications
    # Equality-based dedup preserves both structured records and legacy strings.
    dedup = _idempotent_tools_enabled()

    if "allergies" in params:
        changes["allergies"] = _append_records(
            _get_field(patient, "allergies", ()), params["allergies"], dedup=dedup
        )

    if "medications" in params:
        changes["medications"] = _append_records(
            _get_field(patient, "medications", ()), params["medications"], dedup=dedup
        )

    # Replace-mode fields
    if "advance_directives" in params:
        changes["advance_directives"] = deepcopy(params["advance_directives"])

    if not changes:
        return _error("no_updates", "No updatable fields provided")

    if hasattr(patient, "__dataclass_fields__"):
        updated_patient = replace(patient, **changes)
        world.put_entity("patient", patient_id, updated_patient)
        return _ok(_entity_to_dict(updated_patient))
    else:
        patient.update(changes)
        world.put_entity("patient", patient_id, patient)
        return _ok(patient)


# ---------------------------------------------------------------------------
# 5. register_patient
# ---------------------------------------------------------------------------


def register_patient(world: WorldState, params: dict) -> dict:
    """Register supplied demographics and a linked, untriaged ED encounter.

    Params:
        first_name (required): Patient first name.
        last_name (required): Patient last name.
        date_of_birth (optional): Date of birth (legacy alias: dob).
        sex (optional): "M", "F", or "X".
        allergies (optional): List of known allergies.
        arrival_mode (optional): Supplied arrival mode, otherwise unknown.
        insurance (optional): Unverified supplied insurance details.
        insurance_id (optional): Legacy insurance link, exclusive with insurance.

    IDs are deterministic for equivalent world state and collision-checked.
    Clinical history and triage findings are not generated during registration.
    """
    missing = _require(params, "first_name", "last_name")
    if missing is not None:
        return _error("missing_param", f"Required parameter missing: {missing}")

    first_name = params["first_name"]
    last_name = params["last_name"]
    idem_key = str(params.get("idempotency_key", "") or "")

    for field in ("arrival_mode", "insurance_id"):
        if field in params and not isinstance(params[field], str):
            return _error("invalid_param", f"{field} must be a string")
    if "insurance" in params:
        if not isinstance(params["insurance"], dict):
            return _error("invalid_param", "insurance must be an object")
        if "insurance_id" in params:
            return _error("conflicting_params", "Supply insurance or insurance_id, not both")

    # Idempotency: derive a deterministic patient ID and dedup against an
    # existing patient with that ID (PR-B / WS-5). For create-tools, the
    # natural dedup signal is "entity already exists" — checking the audit
    # log would also work but the entity-lookup is more direct.
    if _idempotent_tools_enabled() and idem_key:
        deterministic_id = _deterministic_patient_id(idem_key, first_name, last_name)
        existing = world.get_entity("patient", deterministic_id)
        if existing is not None:
            result = _ok(_registration_data(world, existing))
            result["deduplicated"] = True
            return result

    dob = params.get("date_of_birth", params.get("dob"))
    if isinstance(dob, str):
        try:
            dob = date.fromisoformat(dob)
        except ValueError:
            return _error("invalid_param", "date_of_birth must be an ISO date")
    elif dob is not None and not isinstance(dob, date):
        return _error("invalid_param", "date_of_birth must be an ISO date")

    # Allocation depends only on simulation state, not wall time. Check both
    # identifiers and MRNs so separate registrations never replace a record.
    seed_value = int(world.timestamp.timestamp() * 1_000_000)
    patients = world.list_entities("patient")
    existing_mrns = {_get_field(patient, "mrn", "") for patient in patients.values()}
    index = len(patients)
    while True:
        rng = random.Random(seed_value + index)
        suffix = uuid.UUID(int=rng.getrandbits(128)).hex[:8].upper()
        patient_id = (
            _deterministic_patient_id(idem_key, first_name, last_name)
            if _idempotent_tools_enabled() and idem_key
            else f"PAT-{suffix}"
        )
        encounter_id = f"ENC-{suffix}"
        mrn = f"MRN-{rng.randint(100000, 999999)}"
        if (
            world.get_entity("patient", patient_id) is None
            and world.get_entity("encounter", encounter_id) is None
            and mrn not in existing_mrns
        ):
            break
        index += 1

    allergies = params.get("allergies", ())
    if not isinstance(allergies, (list, tuple)):
        allergies = [allergies]
    insurance_id = params.get("insurance_id", "")
    insurance_record = None
    if "insurance" in params:
        insurance_index = 0
        while True:
            basis = f"registration-insurance:{patient_id}:{insurance_index}"
            insurance_id = f"INS-{hashlib.sha256(basis.encode()).hexdigest()[:8].upper()}"
            if world.get_entity("insurance", insurance_id) is None:
                break
            insurance_index += 1
        # Keep the complete submitted object even when its keys collide with
        # trusted linkage/provenance fields. No coverage facts are generated.
        insurance_record = {
            **deepcopy(params["insurance"]),
            "id": insurance_id,
            "insurance_id": insurance_id,
            "patient_id": patient_id,
            "entity_type": EntityType.INSURANCE,
            "created_at": world.timestamp,
            "updated_at": world.timestamp,
            "verification_status": "unverified",
            "submitted_details": deepcopy(params["insurance"]),
        }
    registered_patient = Patient(
        id=patient_id,
        entity_type=EntityType.PATIENT,
        created_at=world.timestamp,
        updated_at=world.timestamp,
        mrn=mrn,
        first_name=first_name,
        last_name=last_name,
        dob=dob,
        sex=params.get("sex", ""),
        allergies=deepcopy(tuple(allergies)),
        insurance_id=insurance_id,
    )
    encounter = Encounter(
        id=encounter_id,
        entity_type=EntityType.ENCOUNTER,
        created_at=world.timestamp,
        updated_at=world.timestamp,
        patient_id=patient_id,
        chief_complaint=params.get("chief_complaint", ""),
        arrival_time=world.timestamp,
        esi_level=None,
        triage_time=None,
        arrival_mode=params.get("arrival_mode", ""),
    )
    world.put_entity("patient", registered_patient.id, registered_patient)
    world.put_entity("encounter", encounter.id, encounter)
    if insurance_record is not None:
        world.put_entity("insurance", insurance_id, insurance_record)

    return _ok(_registration_data(world, registered_patient))


# ---------------------------------------------------------------------------
# 6. apply_protocol
# ---------------------------------------------------------------------------


def apply_protocol(world: WorldState, params: dict) -> dict:
    """Activate a clinical protocol for an encounter.

    Params:
        encounter_id (required): The encounter to apply the protocol to.
        protocol_name (required): Name of the protocol (case-insensitive match).

    Looks up the protocol by name across all stored protocol entities,
    creates a clinical task for each protocol step, and returns a summary
    of all created tasks.
    """
    missing = _require(params, "encounter_id", "protocol_name")
    if missing is not None:
        return _error("missing_param", f"Required parameter missing: {missing}")

    encounter_id: str = params["encounter_id"]
    protocol_name: str = params["protocol_name"]

    # Verify encounter exists
    encounter = world.get_entity("encounter", encounter_id)
    if encounter is None:
        return _error("encounter_not_found", f"Encounter not found: {encounter_id}")

    # Idempotency: dedup on prior committed call with same key (PR-B / WS-5).
    idem_key = str(params.get("idempotency_key", "") or "")
    if (
        _idempotent_tools_enabled()
        and idem_key
        and _is_idempotent_replay(world, "applyProtocol", idem_key)
    ):
        return {
            "status": "ok",
            "data": {
                "protocol_applied": protocol_name,
                "encounter_id": encounter_id,
                "tasks_created": [],
                "steps": [],
                "note": "Protocol previously applied for this idempotency key.",
            },
            "deduplicated": True,
        }

    # Find protocol by name (normalized comparison)
    protocols = world.list_entities("protocol")
    matched_protocol = None
    search_name = _normalize_protocol_name(protocol_name)

    search_words = set(search_name.split())
    for _pid, proto in protocols.items():
        name = ""
        if hasattr(proto, "name"):
            name = proto.name
        elif isinstance(proto, dict):
            name = proto.get("name", "")
        normalized_name = _normalize_protocol_name(name)
        # Match exact, substring, or all search words present in name
        if (
            normalized_name == search_name
            or search_name in normalized_name
            or search_words <= set(normalized_name.split())
        ):
            matched_protocol = proto
            break

    if matched_protocol is None:
        return _error(
            "protocol_not_found",
            f"No protocol found matching name: {protocol_name}",
        )

    # Extract steps from the protocol
    if hasattr(matched_protocol, "steps"):
        steps = matched_protocol.steps
    elif isinstance(matched_protocol, dict):
        steps = matched_protocol.get("steps", ())
    else:
        steps = ()

    protocol_display_name = (
        matched_protocol.name
        if hasattr(matched_protocol, "name")
        else matched_protocol.get("name", protocol_name)
    )

    # Create a clinical task for each step
    task_ids: list[str] = []
    step_names: list[str] = []

    for i, step in enumerate(steps):
        step_name = step.get("name", f"Step {i + 1}") if isinstance(step, dict) else f"Step {i + 1}"
        step_names.append(step_name)

        # Use a deterministic seed per step
        rng = random.Random(hash((encounter_id, protocol_name, i)))

        # Default task type to "nursing" for protocol steps; procedure steps
        # could be refined further based on step content
        task = generate_clinical_task(rng, encounter_id, "nursing")

        # Override description with the protocol step info
        step_desc = step.get("description", step_name) if isinstance(step, dict) else step_name
        task = replace(
            task,
            description=f"[{protocol_display_name}] {step_desc}",
            notes=f"Protocol step {i + 1}: {step_name}",
        )

        world.put_entity("clinical_task", task.id, task)
        task_ids.append(task.id)

    return _ok(
        {
            "protocol_applied": protocol_display_name,
            "encounter_id": encounter_id,
            "tasks_created": task_ids,
            "steps": step_names,
        }
    )
