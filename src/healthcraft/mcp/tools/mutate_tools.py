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

import random
import uuid
from dataclasses import asdict, replace
from typing import Any

from healthcraft.entities.clinical_tasks import generate_clinical_task
from healthcraft.entities.patients import generate_patient
from healthcraft.world.state import WorldState

# --- Valid enum values ---

_VALID_ORDER_TYPES = frozenset({"lab", "imaging", "medication", "procedure", "consult"})

_ORDER_TYPE_TO_TASK_TYPE = {
    "lab": "lab_draw",
    "imaging": "imaging",
    "medication": "medication_admin",
    "procedure": "procedure",
    "consult": "consult",
}

_VALID_TASK_STATUSES = frozenset({"pending", "in_progress", "completed", "cancelled", "on_hold"})


# --- Helpers ---


def _ok(data: Any) -> dict[str, Any]:
    """Build a success response."""
    return {"status": "ok", "data": data}


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
                allergies: tuple[str, ...] | list[str]
                if hasattr(patient, "allergies"):
                    allergies = patient.allergies
                elif isinstance(patient, dict):
                    allergies = patient.get("allergies", ())
                else:
                    allergies = ()

                medication_name = details.get("medication", details.get("name", ""))
                if medication_name:
                    med_lower = medication_name.lower()
                    for allergy in allergies:
                        if allergy.lower() in med_lower or med_lower in allergy.lower():
                            return _error(
                                "allergy_conflict",
                                f"Medication '{medication_name}' conflicts with "
                                f"patient allergy '{allergy}'",
                            )

    # Build the order entity (stored as a plain dict, not a dataclass)
    order_id = f"ORD-{uuid.uuid4().hex[:8]}"
    order: dict[str, Any] = {
        "id": order_id,
        "encounter_id": encounter_id,
        "order_type": order_type,
        "details": details,
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
        notes (optional): Notes to record (stored as clinical note, not on encounter).
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

    # Collect only the fields that were explicitly provided
    updatable_fields = ("disposition", "bed_assignment", "attending_id")
    changes: dict[str, Any] = {}
    for field in updatable_fields:
        if field in params:
            changes[field] = params[field]

    if not changes and "notes" not in params:
        return _error("no_updates", "No updatable fields provided")

    if hasattr(encounter, "__dataclass_fields__"):
        if changes:
            updated_encounter = replace(encounter, **changes)
        else:
            updated_encounter = encounter
        world.put_entity("encounter", encounter_id, updated_encounter)
        return _ok(_entity_to_dict(updated_encounter))
    else:
        encounter.update(changes)
        world.put_entity("encounter", encounter_id, encounter)
        return _ok(encounter)


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

    changes: dict[str, Any] = {}

    # Append-mode fields: allergies and medications
    if "allergies" in params:
        new_allergies = params["allergies"]
        if not isinstance(new_allergies, (list, tuple)):
            new_allergies = [new_allergies]
        existing = getattr(patient, "allergies", ()) if hasattr(patient, "allergies") else ()
        changes["allergies"] = tuple(existing) + tuple(new_allergies)

    if "medications" in params:
        new_meds = params["medications"]
        if not isinstance(new_meds, (list, tuple)):
            new_meds = [new_meds]
        existing = getattr(patient, "medications", ()) if hasattr(patient, "medications") else ()
        changes["medications"] = tuple(existing) + tuple(new_meds)

    # Replace-mode fields
    if "advance_directives" in params:
        changes["advance_directives"] = params["advance_directives"]

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
    """Register a new patient in the simulation.

    Params:
        first_name (required): Patient first name.
        last_name (required): Patient last name.
        dob (optional): Date of birth (ISO format string or date object).
        sex (optional): "M", "F", or "X".
        allergies (optional): List of known allergies.
        insurance_id (optional): Insurance identifier.

    Generates a patient using the standard generator seeded from the
    current simulation timestamp, then overrides fields with provided values.
    """
    missing = _require(params, "first_name", "last_name")
    if missing is not None:
        return _error("missing_param", f"Required parameter missing: {missing}")

    # Seed from current timestamp for deterministic-yet-unique generation
    seed_value = int(world.timestamp.timestamp() * 1_000_000)
    rng = random.Random(seed_value)

    patient = generate_patient(rng)

    # Override generated fields with provided params
    overrides: dict[str, Any] = {
        "first_name": params["first_name"],
        "last_name": params["last_name"],
    }

    if "dob" in params:
        from datetime import date

        dob = params["dob"]
        if isinstance(dob, str):
            overrides["dob"] = date.fromisoformat(dob)
        else:
            overrides["dob"] = dob

    if "sex" in params:
        overrides["sex"] = params["sex"]

    if "allergies" in params:
        allergies = params["allergies"]
        if not isinstance(allergies, (list, tuple)):
            allergies = [allergies]
        overrides["allergies"] = tuple(allergies)

    if "insurance_id" in params:
        overrides["insurance_id"] = params["insurance_id"]

    registered_patient = replace(patient, **overrides)
    world.put_entity("patient", registered_patient.id, registered_patient)

    return _ok(_entity_to_dict(registered_patient))


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

    # Find protocol by name (case-insensitive)
    protocols = world.list_entities("protocol")
    matched_protocol = None
    search_name = protocol_name.lower()

    for _pid, proto in protocols.items():
        name = ""
        if hasattr(proto, "name"):
            name = proto.name
        elif isinstance(proto, dict):
            name = proto.get("name", "")
        # Match exact or substring (allows "sepsis" to match "Sepsis Hour-1 Bundle")
        if name.lower() == search_name or search_name in name.lower():
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
