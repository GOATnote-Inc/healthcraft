"""Inject task-described patient data into the world state.

Tasks define specific patients with detailed clinical data (vitals, labs,
imaging, allergies, medications). This module converts that YAML data into
proper entity instances and injects them into the world state so that MCP
tools can discover and return them.

Without injection, the task's patient doesn't exist in the seeded world
state, making tool-dependent criteria unsolvable.
"""

from __future__ import annotations

import hashlib
import math
from copy import deepcopy
from datetime import date
from typing import Any

from healthcraft.entities.base import EntityType
from healthcraft.entities.encounters import (
    Encounter,
    ESILevel,
    VitalSigns,
)
from healthcraft.entities.patients import Patient
from healthcraft.tasks.care_projection import project_authored_care
from healthcraft.tasks.imaging_projection import project_imaging
from healthcraft.tasks.lab_projection import project_labs
from healthcraft.tasks.source_values import require_finite_source
from healthcraft.temporal import instant_key, resolve_source_time
from healthcraft.world.state import WorldState


def _deterministic_id(prefix: str, task_id: str) -> str:
    """Generate a deterministic entity ID from task ID."""
    h = hashlib.md5(task_id.encode()).hexdigest()[:8].upper()
    return f"{prefix}-{h}"


_FEMALE_NAMES = [
    "Margaret",
    "Dorothy",
    "Helen",
    "Ruth",
    "Florence",
    "Virginia",
    "Martha",
    "Eleanor",
    "Catherine",
    "Alice",
    "Jean",
    "Louise",
    "Rose",
    "Marie",
    "Gloria",
    "Evelyn",
    "Irene",
    "Frances",
    "Dolores",
    "Beatrice",
]
_MALE_NAMES = [
    "Robert",
    "James",
    "William",
    "Charles",
    "George",
    "Edward",
    "Thomas",
    "Richard",
    "Joseph",
    "Harold",
    "Donald",
    "Henry",
    "Raymond",
    "Arthur",
    "Walter",
    "Eugene",
    "Albert",
    "Frank",
    "Howard",
    "Lawrence",
]
_LAST_NAMES = [
    "Johnson",
    "Williams",
    "Brown",
    "Davis",
    "Miller",
    "Wilson",
    "Moore",
    "Taylor",
    "Anderson",
    "Thomas",
    "Jackson",
    "White",
    "Harris",
    "Martin",
    "Thompson",
    "Garcia",
    "Martinez",
    "Robinson",
    "Clark",
    "Rodriguez",
]


def _generate_patient_name(task_id: str, sex: str) -> tuple[str, str]:
    """Generate a deterministic realistic patient name from task ID and sex."""
    h = int(hashlib.md5(task_id.encode()).hexdigest(), 16)
    first_pool = _FEMALE_NAMES if sex.upper() in ("F", "FEMALE") else _MALE_NAMES
    first_name = first_pool[h % len(first_pool)]
    last_name = _LAST_NAMES[(h // len(first_pool)) % len(_LAST_NAMES)]
    return first_name, last_name


def _parse_bp(bp_str: str | None) -> tuple[int | None, int | None]:
    """Parse blood pressure string like '128/84' into (systolic, diastolic)."""
    if not bp_str or not isinstance(bp_str, str):
        return None, None
    parts = bp_str.split("/")
    if len(parts) == 2:
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            return None, None
    return None, None


def _parse_vitals(vitals_data: dict[str, Any], source_path: str) -> VitalSigns:
    """Project explicit measurements and preserve all authored qualifiers."""
    sbp, dbp = _parse_bp(vitals_data.get("blood_pressure"))
    if sbp is None:
        sbp, dbp = _parse_bp(vitals_data.get("blood_pressure_right"))
    timestamp, status, keys = resolve_source_time(
        vitals_data, ("time", "timestamp", "time_of_vitals")
    )

    def numeric(key):
        value = vitals_data.get(key)
        if type(value) is int or (type(value) is float and math.isfinite(value)):
            return value
        return None

    return VitalSigns(
        timestamp=timestamp,
        heart_rate=numeric("heart_rate"),
        systolic_bp=sbp,
        diastolic_bp=dbp,
        respiratory_rate=numeric("respiratory_rate"),
        spo2=numeric("spo2"),
        temperature=numeric("temperature"),
        gcs=numeric("gcs"),
        pain_scale=numeric("pain_scale"),
        source_path=source_path,
        source_data=deepcopy(vitals_data),
        timing_status=status,
        source_time_keys=keys,
    )


# Direct index-patient observations only. Nested prior visits/other patients
# retain their own narrative context and must not be attributed to this patient.
_VITAL_KEYS = (
    "vitals_on_arrival",
    "vitals_at_arrival",
    "vitals",
    "vitals_current",
    "vitals_at_discharge",
    "vitals_at_presentation",
    "vitals_initial",
    "vitals_post_diltiazem",
    "vitals_post_treatment",
    "vitals_repeat",
    "vitals_30_minutes_later",
    "vitals_2_hours_later",
    "vitals_post_naloxone",
    "vitals_pre_sedation",
    "vitals_during_reaction",
    "vitals_5min_post_error",
    "vitals_intermediate",
    "vitals_at_tpa_bolus",
    "vitals_at_admission",
    "vitals_pre_reaction",
    "vitals_pre_error",
    "vitals_orthostatic",
    "pre_arrest_vitals",
    "field_vitals",
)
_VITAL_SERIES_KEYS = ("vitals_series", "serial_vitals")


def _format_note_value(value: Any) -> str:
    """Format an arbitrary YAML value into a readable clinical note string."""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                # Timeline entries: {time: "09:12", event: "...", ...}
                segments = []
                for k, v in item.items():
                    segments.append(f"{k}: {v}")
                parts.append("; ".join(segments))
            else:
                parts.append(str(item))
        return " | ".join(parts)
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            parts.append(f"{k.replace('_', ' ').title()}: {v}")
        return "; ".join(parts)
    return str(value)


def inject_task_patient(
    world: WorldState,
    task_id: str,
    patient_data: dict[str, Any],
    setting_data: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Inject a task-described patient into the world state.

    Creates a Patient entity and an Encounter entity from the task's
    patient YAML section and stores them in the world state so MCP tools
    can discover them.

    Args:
        world: The seeded world state to inject into.
        task_id: The task ID (used for deterministic entity ID generation).
        patient_data: The ``patient:`` section from the task YAML.
        setting_data: The ``setting:`` section (optional, for timestamps).

    Returns:
        Dict with ``patient_id`` and ``encounter_id`` of injected entities.
    """
    if not patient_data:
        return {}

    require_finite_source(patient_data)
    require_finite_source(setting_data)
    now = world.timestamp
    setting = setting_data or {}
    # A deterministic scaffold anchor for generated DOB only. It is never a
    # substitute for authored observation, care, imaging, or arrival time.
    try:
        encounter_time = instant_key(setting.get("time"))[0]
    except (ValueError, OverflowError):
        encounter_time = now

    # --- Create Patient entity ---
    patient_id = _deterministic_id("PAT", task_id)
    mrn = _deterministic_id("MRN", task_id)

    # Calculate DOB from age (handle string ages like "0 minutes (newborn)")
    raw_age = patient_data.get("age", 50)
    age_unit = patient_data.get("age_unit", "years")
    try:
        age = int(raw_age)
    except (ValueError, TypeError):
        # Parse descriptive ages: "0 minutes (newborn)", "3 days", etc.
        age = 0
        raw_str = str(raw_age).lower()
        if "minute" in raw_str or "newborn" in raw_str:
            age_unit = "days"
            age = 0
        elif "hour" in raw_str:
            age_unit = "days"
            age = 0
        elif "day" in raw_str:
            age_unit = "days"
            import re

            m = re.search(r"(\d+)", raw_str)
            age = int(m.group(1)) if m else 0
        elif "month" in raw_str:
            age_unit = "months"
            import re

            m = re.search(r"(\d+)", raw_str)
            age = int(m.group(1)) if m else 0
    if age_unit == "months":
        birth_year = encounter_time.year
        birth_month = max(1, encounter_time.month - age)
        dob = date(birth_year, birth_month, 15)
    elif age_unit == "days":
        dob = date(encounter_time.year, encounter_time.month, max(1, encounter_time.day - age))
    else:
        dob = date(max(1, encounter_time.year - age), 6, 15)

    sex = patient_data.get("sex", "")

    # Use task-specific names if provided, otherwise generate deterministically
    first_name = patient_data.get("first_name")
    last_name = patient_data.get("last_name")
    if not first_name or not last_name:
        first_name, last_name = _generate_patient_name(task_id, sex)

    allergies = tuple(patient_data.get("allergies", []))
    medications = tuple(patient_data.get("medications", []))
    pmh = tuple(patient_data.get("past_medical_history", []))
    social_raw = patient_data.get("social_history", [])
    if isinstance(social_raw, dict):
        social_history = tuple(
            f"{key}: {_format_note_value(value)}" for key, value in social_raw.items()
        )
    else:
        social_history = tuple(social_raw)
    family_history = tuple(patient_data.get("family_history", []))
    advance_directives = patient_data.get("advance_directives", "")

    patient = Patient(
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
        social_history=social_history,
        family_history=family_history,
        insurance_id="",
        advance_directives=advance_directives,
        prior_visit_ids=(),
    )

    # --- Create Encounter entity ---
    encounter_id = _deterministic_id("ENC", task_id)

    # Source labels and list position identify observations, not chronology.
    vitals_list: list[VitalSigns] = []
    for key in _VITAL_KEYS:
        source = patient_data.get(key)
        if isinstance(source, dict):
            vitals_list.append(_parse_vitals(source, f"/patient/{key}"))
    for key in _VITAL_SERIES_KEYS:
        source = patient_data.get(key)
        if isinstance(source, list):
            for index, entry in enumerate(source):
                if isinstance(entry, dict):
                    vitals_list.append(_parse_vitals(entry, f"/patient/{key}/{index}"))

    labs = project_labs(patient_data.get("labs"), "/patient/labs")

    # Preserve source reports and pending context; conditional guidance is withheld.
    imaging_projection = project_imaging(patient_data, task_id=task_id)

    # A request or mixed management statement is not an administration event.
    authored_care = project_authored_care(patient_data)

    # ESI level
    esi_raw = patient_data.get("esi_level", 3)
    try:
        esi_level = ESILevel(int(esi_raw))
    except (ValueError, TypeError):
        esi_level = ESILevel.URGENT

    # Bed assignment from location or setting
    bed = patient_data.get("location", setting.get("bed", ""))

    # Parse exam findings (physical exam data)
    exam_raw = patient_data.get("exam_findings", {})
    exam_list: list[tuple[str, str]] = []
    if exam_raw and isinstance(exam_raw, dict):
        exam_list.extend(
            (system.replace("_", " ").title(), str(finding)) for system, finding in exam_raw.items()
        )

    # Surface bilateral BP readings as an exam finding when present
    vitals_source = next(
        (
            patient_data[key]
            for key in _VITAL_KEYS
            if isinstance(patient_data.get(key), dict)
            and "blood_pressure_right" in patient_data[key]
        ),
        {},
    )
    bp_right = vitals_source.get("blood_pressure_right")
    bp_left = vitals_source.get("blood_pressure_left")
    if bp_right and bp_left:
        r_sys, _ = _parse_bp(bp_right)
        l_sys, _ = _parse_bp(bp_left)
        diff = abs(r_sys - l_sys) if r_sys and l_sys else None
        diff_note = f" ({diff} mmHg systolic differential)" if diff else ""
        exam_list.append(
            ("Bilateral Blood Pressures", f"Right arm {bp_right}, Left arm {bp_left}{diff_note}")
        )

    exam_findings: tuple[tuple[str, str], ...] = tuple(exam_list)

    # Parse additional lab sources (labs_post_rosc, labs_available, etc.)
    for lab_key in ("labs_post_rosc", "labs_available", "labs_at_discharge", "initial_labs"):
        extra_labs = patient_data.get(lab_key)
        if extra_labs and isinstance(extra_labs, dict):
            labs = labs + project_labs(extra_labs, f"/patient/{lab_key}")

    # Collect unhandled patient data as clinical notes (catch-all)
    _HANDLED_KEYS = {
        "age",
        "age_unit",
        "sex",
        "first_name",
        "last_name",
        "allergies",
        "medications",
        "past_medical_history",
        "advance_directives",
        "chief_complaint",
        "esi_level",
        "location",
        "vitals",
        "vitals_current",
        "vitals_at_discharge",
        "vitals_at_presentation",
        "vitals_initial",
        "vitals_on_arrival",
        "vitals_at_arrival",
        "vitals_post_diltiazem",
        "vitals_post_treatment",
        "vitals_repeat",
        "vitals_30_minutes_later",
        "vitals_2_hours_later",
        "vitals_post_naloxone",
        "vitals_pre_sedation",
        "vitals_during_reaction",
        "vitals_5min_post_error",
        "vitals_intermediate",
        "vitals_at_tpa_bolus",
        "vitals_at_admission",
        "vitals_pre_reaction",
        "vitals_pre_error",
        "vitals_series",
        "labs",
        "imaging",
        "imaging_results",
        "imaging_pending",
        "imaging_available",
        "bedside_echo",
        "fast_exam",
        "active_orders",
        "current_management",
        "exam_findings",
        "social_history",
        "family_history",
        "labs_post_rosc",
        "labs_available",
        "labs_at_discharge",
        "initial_labs",
    }
    notes_list: list[tuple[str, str]] = []
    for key, value in patient_data.items():
        if key in _HANDLED_KEYS:
            continue
        label = key.replace("_", " ").title()
        notes_list.append((label, _format_note_value(value)))
    clinical_notes: tuple[tuple[str, str], ...] = tuple(notes_list)

    encounter = Encounter(
        id=encounter_id,
        entity_type=EntityType.ENCOUNTER,
        created_at=now,
        updated_at=now,
        patient_id=patient_id,
        chief_complaint=patient_data.get("chief_complaint", ""),
        esi_level=esi_level,
        bed_assignment=bed,
        arrival_time=resolve_source_time(patient_data, ("arrival_time",))[0],
        triage_time=resolve_source_time(patient_data, ("triage_time",))[0],
        disposition=None,
        attending_id=setting.get("attending_on_duty", ""),
        vitals=tuple(vitals_list),
        labs=labs,
        imaging=imaging_projection.records,
        imaging_projection_notices=imaging_projection.notices,
        meds_administered=(),
        authored_care=authored_care,
        exam_findings=exam_findings,
        clinical_notes=clinical_notes,
    )

    # Projection/validation must finish before either entity becomes visible.
    world.put_entity(EntityType.PATIENT.value, patient_id, patient)
    world.put_entity(EntityType.ENCOUNTER.value, encounter_id, encounter)

    # Move task entities to front of their collections so they appear in the
    # first page of search results (pagination limit = 10, seeded world has
    # 500+ entities that would otherwise bury the task patient).
    for etype, eid in [
        (EntityType.PATIENT.value, patient_id),
        (EntityType.ENCOUNTER.value, encounter_id),
    ]:
        store = world._entities.get(etype, {})
        if eid in store:
            entity = store.pop(eid)
            world._entities[etype] = {eid: entity, **store}

    return {"patient_id": patient_id, "encounter_id": encounter_id}
