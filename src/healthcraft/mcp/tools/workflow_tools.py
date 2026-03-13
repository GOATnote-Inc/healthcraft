"""Workflow MCP tool handlers for HEALTHCRAFT ED simulation.

Implements the Wave 4 (complex workflow) tools:
- processDischarge → process_discharge
- processTransfer  → process_transfer

Each handler takes (world: WorldState, params: dict) -> dict.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, replace
from typing import Any

from healthcraft.world.state import WorldState

# --- Known transfer facilities (hardcoded registry) ---

_KNOWN_FACILITIES: frozenset[str] = frozenset(
    {
        "Riverside Community Hospital",
        "University Medical Center",
        "Children's Memorial Hospital",
        "Regional Burn Center",
        "Lakeside Psychiatric",
        "St. Mary's Rehabilitation",
        "Metro Level I Trauma",
        "County General Hospital",
    }
)

_VALID_TRANSPORT_MODES: frozenset[str] = frozenset(
    {
        "ground_als",
        "ground_bls",
        "helicopter",
        "fixed_wing",
    }
)


def _error(code: str, message: str) -> dict[str, Any]:
    """Build a standard error response."""
    return {"status": "error", "code": code, "message": message}


def _ok(data: dict[str, Any]) -> dict[str, Any]:
    """Build a standard success response."""
    return {"status": "ok", "data": data}


# ---------------------------------------------------------------------------
# 1. processDischarge
# ---------------------------------------------------------------------------


def process_discharge(world: WorldState, params: dict[str, Any]) -> dict[str, Any]:
    """Process a patient discharge from the ED.

    Multi-step workflow:
      a) Verify encounter exists and retrieve the patient.
      b) Check all pending clinical tasks for the encounter (warn if any
         are still pending or in-progress).
      c) Update encounter disposition to "discharged".
      d) Generate discharge documentation (summary, medication reconciliation,
         follow-up plan).
      e) Store the discharge document as a ``clinical_note`` entity.
      f) Return the full discharge package.

    Args:
        world: The simulation WorldState.
        params: Dict containing:
            - encounter_id (str, required)
            - diagnosis (str, required)
            - discharge_instructions (str, optional)
            - follow_up_plan (str, optional)
            - medications_prescribed (list[dict], optional) — each dict has
              name, dose, route, frequency.

    Returns:
        Standard response dict with ``status`` and ``data`` or error fields.
    """
    # --- Validate required params ---
    encounter_id = params.get("encounter_id")
    if not encounter_id:
        return _error("missing_param", "encounter_id is required")

    diagnosis = params.get("diagnosis")
    if not diagnosis:
        return _error("missing_param", "diagnosis is required")

    # --- (a) Verify encounter and patient ---
    encounter = world.get_entity("encounter", encounter_id)
    if encounter is None:
        return _error("not_found", f"Encounter {encounter_id} not found")

    patient_id = encounter.patient_id
    patient = world.get_entity("patient", patient_id) if patient_id else None
    if patient is None:
        return _error("not_found", f"Patient {patient_id} not found for encounter {encounter_id}")

    # --- (b) Check pending clinical tasks ---
    pending_tasks_warning: list[dict[str, Any]] = []
    all_tasks = world.list_entities("clinical_task")
    for task_id, task in all_tasks.items():
        if task.encounter_id == encounter_id and task.status in ("pending", "in_progress"):
            pending_tasks_warning.append(
                {
                    "task_id": task_id,
                    "description": task.description,
                    "status": task.status,
                    "priority": task.priority,
                }
            )

    # --- (c) Update encounter disposition ---
    from healthcraft.entities.encounters import Disposition

    now = world.timestamp
    updated_encounter = replace(
        encounter,
        disposition=Disposition.DISCHARGED,
        updated_at=now,
    )
    world.put_entity("encounter", encounter_id, updated_encounter)

    # --- (d) Generate discharge documentation ---
    discharge_instructions = params.get("discharge_instructions", "")
    follow_up_plan = params.get("follow_up_plan", "")
    medications_prescribed = params.get("medications_prescribed", [])

    # Build treatments summary from meds administered during encounter
    treatments: list[str] = []
    for med_admin in encounter.meds_administered:
        treatments.append(f"{med_admin.medication_name} {med_admin.dose} {med_admin.route}")

    treatments_text = (
        "; ".join(treatments) if treatments else "No medications administered during visit"
    )

    patient_name = f"{patient.first_name} {patient.last_name}"
    discharge_summary = (
        f"Discharge Summary for {patient_name} (MRN: {patient.mrn})\n"
        f"Encounter: {encounter_id}\n"
        f"Chief Complaint: {encounter.chief_complaint}\n"
        f"Diagnosis: {diagnosis}\n"
        f"Treatments During Visit: {treatments_text}\n"
        f"Discharge Instructions: {discharge_instructions or 'Standard discharge instructions provided'}\n"
        f"Disposition: Discharged"
    )

    # Medication reconciliation: compare prescribed vs home medications
    home_meds = list(patient.medications) if patient.medications else []
    prescribed_meds = medications_prescribed or []
    reconciliation_lines: list[str] = []

    if home_meds:
        reconciliation_lines.append("Home Medications:")
        for med in home_meds:
            reconciliation_lines.append(f"  - {med} [CONTINUE]")

    if prescribed_meds:
        reconciliation_lines.append("New Prescriptions:")
        for med in prescribed_meds:
            name = med.get("name", "Unknown")
            dose = med.get("dose", "")
            route = med.get("route", "")
            frequency = med.get("frequency", "")
            reconciliation_lines.append(f"  - {name} {dose} {route} {frequency}".strip())

    if not reconciliation_lines:
        reconciliation_lines.append("No medications to reconcile")

    medication_reconciliation = "\n".join(reconciliation_lines)

    follow_up_text = follow_up_plan or "Follow up with primary care provider within 48-72 hours"

    # --- (e) Store discharge note as clinical_note entity ---
    from healthcraft.entities.base import Entity, EntityType

    note_id = f"NOTE-{uuid.uuid4().hex[:8].upper()}"
    full_note_content = (
        f"{discharge_summary}\n\n"
        f"--- Medication Reconciliation ---\n{medication_reconciliation}\n\n"
        f"--- Follow-Up Plan ---\n{follow_up_text}"
    )

    # Create a generic Entity for the clinical_note since there is no
    # dedicated ClinicalNote dataclass — store as a dict-like entity.
    discharge_note = Entity(
        id=note_id,
        entity_type=EntityType.CLINICAL_NOTE,
        created_at=now,
        updated_at=now,
    )
    # Store as a dict so we can include the rich content fields that
    # the base Entity dataclass does not carry.
    note_record: dict[str, Any] = {
        **asdict(discharge_note),
        "note_type": "discharge_summary",
        "encounter_id": encounter_id,
        "patient_id": patient_id,
        "content": full_note_content,
        "diagnosis": diagnosis,
        "author": encounter.attending_id or "system",
    }
    world.put_entity("clinical_note", note_id, note_record)

    # --- (f) Build and return discharge package ---
    discharged_at = now.isoformat()

    data: dict[str, Any] = {
        "encounter_id": encounter_id,
        "patient_id": patient_id,
        "disposition": "discharged",
        "diagnosis": diagnosis,
        "discharge_summary": discharge_summary,
        "medications_prescribed": prescribed_meds,
        "follow_up": follow_up_text,
        "discharged_at": discharged_at,
    }

    if pending_tasks_warning:
        data["pending_tasks_warning"] = pending_tasks_warning

    return _ok(data)


# ---------------------------------------------------------------------------
# 2. processTransfer
# ---------------------------------------------------------------------------


def process_transfer(world: WorldState, params: dict[str, Any]) -> dict[str, Any]:
    """Process an inter-facility transfer from the ED.

    Multi-step workflow:
      a) Verify encounter exists.
      b) Verify receiving facility is known.
      c) EMTALA compliance check — patient must be stabilized OR the
         transfer benefits outweigh risks (caller must supply
         ``emtala_justification`` in params if patient is not stabilized).
      d) Create a transfer record entity.
      e) Update encounter disposition to "transferred".
      f) Generate transfer documentation.
      g) Return the transfer package.

    Args:
        world: The simulation WorldState.
        params: Dict containing:
            - encounter_id (str, required)
            - receiving_facility (str, required)
            - reason (str, required)
            - transport_mode (str, optional — default "ground_als")
            - accepting_physician (str, optional)
            - clinical_summary (str, optional)
            - emtala_justification (str, optional — required when patient
              is not stabilized)

    Returns:
        Standard response dict with ``status`` and ``data`` or error fields.
    """
    # --- Validate required params ---
    encounter_id = params.get("encounter_id")
    if not encounter_id:
        return _error("missing_param", "encounter_id is required")

    receiving_facility = params.get("receiving_facility") or params.get("destination_facility")
    if not receiving_facility:
        return _error("missing_param", "receiving_facility or destination_facility is required")

    reason = params.get("reason")
    if not reason:
        return _error("missing_param", "reason is required")

    transport_mode = params.get("transport_mode", "ground_als")
    # Map schema shorthand "ground" to handler's "ground_als" for backward compat
    if transport_mode == "ground":
        transport_mode = "ground_als"
    if transport_mode not in _VALID_TRANSPORT_MODES:
        return _error(
            "invalid_param",
            f"transport_mode must be one of: {', '.join(sorted(_VALID_TRANSPORT_MODES))}",
        )

    accepting_physician = params.get("accepting_physician", "")
    clinical_summary_param = params.get("clinical_summary", "")
    emtala_justification = params.get("emtala_justification", "")

    # --- (a) Verify encounter ---
    encounter = world.get_entity("encounter", encounter_id)
    if encounter is None:
        return _error("not_found", f"Encounter {encounter_id} not found")

    patient_id = encounter.patient_id

    # --- (b) Verify receiving facility is known ---
    # Check hardcoded list first, then search transfer entities for
    # any previously registered facilities.
    facility_known = receiving_facility in _KNOWN_FACILITIES
    if not facility_known:
        all_transfers = world.list_entities("transfer")
        for _tid, transfer_entity in all_transfers.items():
            rf = getattr(transfer_entity, "receiving_facility", None)
            sf = getattr(transfer_entity, "sending_facility", None)
            if receiving_facility in (rf, sf):
                facility_known = True
                break

    # Accept unknown facilities with a warning rather than blocking the transfer.
    # In a real ED, transfers go to facilities not in the directory.
    facility_warning = ""
    if not facility_known:
        facility_warning = (
            f"Note: '{receiving_facility}' is not in the known facility directory. "
            "Proceeding with transfer."
        )

    # --- (c) EMTALA compliance check ---
    # Determine stabilization status from the encounter's most recent vitals.
    emtala_compliant = True
    emtala_notes = "Patient stabilized prior to transfer"

    patient_stabilized = _assess_stabilization(encounter)

    if not patient_stabilized:
        if emtala_justification:
            emtala_compliant = True
            emtala_notes = (
                f"Patient not fully stabilized. Transfer justified: {emtala_justification}. "
                "Benefits of transfer outweigh risks per EMTALA."
            )
        else:
            emtala_compliant = False
            emtala_notes = (
                "WARNING: Patient may not be stabilized. No emtala_justification provided. "
                "Transfer may violate EMTALA. Provide emtala_justification param confirming "
                "benefits outweigh risks."
            )

    # --- (d) Create transfer record entity ---
    now = world.timestamp
    transfer_id = f"XFR-{uuid.uuid4().hex[:6].upper()}"

    # Build a clinical summary if not provided
    if clinical_summary_param:
        clinical_summary = clinical_summary_param
    else:
        patient = world.get_entity("patient", patient_id)
        if patient is not None:
            patient_name = f"{patient.first_name} {patient.last_name}"
            clinical_summary = (
                f"Patient {patient_name} (MRN: {getattr(patient, 'mrn', 'N/A')}) "
                f"presenting with {encounter.chief_complaint}. "
                f"ESI Level: {encounter.esi_level.value}. "
                f"Transfer reason: {reason}."
            )
        else:
            clinical_summary = (
                f"Patient {patient_id} presenting with {encounter.chief_complaint}. "
                f"Transfer reason: {reason}."
            )

    from healthcraft.entities.base import EntityType
    from healthcraft.entities.transfers import Transfer

    transfer_record = Transfer(
        id=transfer_id,
        entity_type=EntityType.TRANSFER,
        created_at=now,
        updated_at=now,
        transfer_id=transfer_id,
        encounter_id=encounter_id,
        patient_id=patient_id,
        direction="outgoing",
        status="requested",
        sending_facility="Mercy Point Emergency Department",
        receiving_facility=receiving_facility,
        reason=reason,
        transport_mode=transport_mode,
        estimated_time_minutes=None,
        accepting_physician=accepting_physician,
        documentation_complete=False,
        emtala_compliant=emtala_compliant,
        clinical_summary=clinical_summary,
        requested_at=now,
        departed_at=None,
    )
    world.put_entity("transfer", transfer_id, transfer_record)

    # --- (e) Update encounter disposition ---
    from healthcraft.entities.encounters import Disposition

    updated_encounter = replace(
        encounter,
        disposition=Disposition.TRANSFERRED,
        updated_at=now,
    )
    world.put_entity("encounter", encounter_id, updated_encounter)

    # --- (f, g) Return the transfer package ---
    data: dict[str, Any] = {
        "transfer_id": transfer_id,
        "encounter_id": encounter_id,
        "patient_id": patient_id,
        "receiving_facility": receiving_facility,
        "transport_mode": transport_mode,
        "reason": reason,
        "emtala_compliant": emtala_compliant,
        "emtala_notes": emtala_notes,
        "clinical_summary": clinical_summary,
        "status": "requested",
        "requested_at": now.isoformat(),
    }

    if facility_warning:
        data["facility_warning"] = facility_warning

    return _ok(data)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assess_stabilization(encounter: Any) -> bool:
    """Heuristic stabilization assessment based on the encounter's most recent vitals.

    A patient is considered stabilized if their most recent vital signs are
    within broad acceptable ranges.  If no vitals are available, we
    conservatively assume **not** stabilized.

    Returns:
        True if the patient appears hemodynamically stable.
    """
    vitals = getattr(encounter, "vitals", ())
    if not vitals:
        return False

    latest = vitals[-1]

    # Check for gross instability indicators
    hr = getattr(latest, "heart_rate", None)
    sbp = getattr(latest, "systolic_bp", None)
    spo2 = getattr(latest, "spo2", None)
    gcs = getattr(latest, "gcs", None)

    if hr is not None and (hr < 50 or hr > 140):
        return False
    if sbp is not None and sbp < 80:
        return False
    if spo2 is not None and spo2 < 88:
        return False
    if gcs is not None and gcs < 9:
        return False

    return True
