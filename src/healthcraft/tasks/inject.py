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
from datetime import date, datetime, timedelta, timezone
from typing import Any

from healthcraft.entities.base import EntityType
from healthcraft.entities.encounters import (
    Encounter,
    ESILevel,
    ImagingStudy,
    LabResult,
    MedicationAdministration,
    VitalSigns,
)
from healthcraft.entities.patients import Patient
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


def _parse_vitals(vitals_data: dict[str, Any], timestamp: datetime) -> VitalSigns:
    """Convert task YAML vitals dict to a VitalSigns dataclass."""
    sbp, dbp = _parse_bp(vitals_data.get("blood_pressure"))

    # Fall back to right arm BP if standard BP not present (bilateral readings)
    if sbp is None:
        sbp, dbp = _parse_bp(vitals_data.get("blood_pressure_right"))

    hr = vitals_data.get("heart_rate")
    if isinstance(hr, str):
        hr = None  # e.g., "undetectable"

    spo2 = vitals_data.get("spo2")
    if isinstance(spo2, str):
        spo2 = None

    return VitalSigns(
        timestamp=timestamp,
        heart_rate=hr,
        systolic_bp=sbp,
        diastolic_bp=dbp,
        respiratory_rate=vitals_data.get("respiratory_rate"),
        spo2=spo2,
        temperature=vitals_data.get("temperature"),
        gcs=vitals_data.get("gcs"),
        pain_scale=vitals_data.get("pain_scale"),
    )


def _parse_labs(labs_data: dict[str, Any], timestamp: datetime) -> tuple[LabResult, ...]:
    """Convert task YAML labs dict to LabResult tuples.

    Task YAML format: ``troponin_i: "0.02 ng/mL (normal <0.04)"``
    """
    if not labs_data or not isinstance(labs_data, dict):
        return ()

    results = []
    for test_name, value_str in labs_data.items():
        if not isinstance(value_str, str):
            value_str = str(value_str)

        abnormal = any(
            marker in value_str.lower()
            for marker in ("elevated", "low", "high", "abnormal", "positive", "critical")
        )

        results.append(
            LabResult(
                test_name=test_name.replace("_", " ").title(),
                value=value_str,
                unit="",
                reference_range="",
                timestamp=timestamp,
                abnormal=abnormal,
            )
        )
    return tuple(results)


def _parse_imaging(imaging_data: dict[str, Any], timestamp: datetime) -> tuple[ImagingStudy, ...]:
    """Convert task YAML imaging dict to ImagingStudy tuples.

    Supports formats like:
        imaging:
          chest_xray:
            findings: "..."
            impression: "..."   (optional)
          ct_abdomen:
            findings: "..."
            impression: "..."
    """
    if not imaging_data or not isinstance(imaging_data, dict):
        return ()

    modality_map = {
        "xray": "XR",
        "x_ray": "XR",
        "chest_xray": "XR",
        "ct": "CT",
        "ct_abdomen": "CT",
        "ct_head": "CT",
        "ct_chest": "CT",
        "ct_angiography": "CT",
        "mri": "MRI",
        "mri_brain": "MRI",
        "us": "US",
        "ultrasound": "US",
        "echo": "US",
    }

    body_part_map = {
        "chest_xray": "chest",
        "ct_abdomen": "abdomen/pelvis",
        "ct_head": "head",
        "ct_chest": "chest",
        "ct_angiography": "chest",
        "mri_brain": "brain",
    }

    results = []
    for study_key, study_data in imaging_data.items():
        if not isinstance(study_data, dict):
            continue

        modality = modality_map.get(study_key, "XR")
        body_part = body_part_map.get(study_key, study_key.replace("_", " "))
        findings = study_data.get("findings", "")
        impression = study_data.get("impression", findings[:200] if findings else "")

        results.append(
            ImagingStudy(
                modality=modality,
                body_part=body_part,
                findings=findings.strip() if isinstance(findings, str) else str(findings),
                impression=impression.strip() if isinstance(impression, str) else str(impression),
                timestamp=timestamp,
            )
        )
    return tuple(results)


def _parse_meds_administered(
    meds_data: list[str] | None, timestamp: datetime
) -> tuple[MedicationAdministration, ...]:
    """Convert active_orders or current_management to MedicationAdministration."""
    if not meds_data or not isinstance(meds_data, list):
        return ()

    results = []
    for med_str in meds_data:
        if not isinstance(med_str, str):
            continue
        # Extract route hints from the string
        route = "PO"
        if " IV " in med_str or med_str.endswith(" IV"):
            route = "IV"
        elif " IM " in med_str:
            route = "IM"
        elif " INH" in med_str or "inhale" in med_str.lower() or "nebulizer" in med_str.lower():
            route = "INH"

        results.append(
            MedicationAdministration(
                medication_name=med_str,
                dose="",
                route=route,
                timestamp=timestamp,
            )
        )
    return tuple(results)


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

    now = datetime.now(timezone.utc)
    setting = setting_data or {}

    # Parse setting time for encounter timestamps
    setting_time_str = setting.get("time")
    if setting_time_str:
        try:
            encounter_time = datetime.fromisoformat(setting_time_str)
        except (ValueError, TypeError):
            encounter_time = now
    else:
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
    social_history = tuple(patient_data.get("social_history", []))
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

    world.put_entity(EntityType.PATIENT.value, patient_id, patient)

    # --- Create Encounter entity ---
    encounter_id = _deterministic_id("ENC", task_id)

    # Parse vitals — support multiple naming conventions across tasks
    vitals_list: list[VitalSigns] = []
    vitals_data = (
        patient_data.get("vitals")
        or patient_data.get("vitals_current")
        or patient_data.get("vitals_at_discharge")
        or patient_data.get("vitals_at_presentation")
        or patient_data.get("vitals_initial")
    )
    if vitals_data and isinstance(vitals_data, dict):
        vitals_list.append(_parse_vitals(vitals_data, encounter_time))

    # Also parse arrival vitals if present (multiple naming conventions)
    vitals_arrival = patient_data.get("vitals_on_arrival") or patient_data.get("vitals_at_arrival")
    if vitals_arrival and isinstance(vitals_arrival, dict):
        arrival_time = encounter_time - timedelta(hours=2)
        vitals_list.insert(0, _parse_vitals(vitals_arrival, arrival_time))

    # Also parse post-treatment / follow-up vitals if present
    _POST_VITALS_KEYS = (
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
    )
    for idx, key in enumerate(_POST_VITALS_KEYS):
        post_vitals = patient_data.get(key)
        if post_vitals and isinstance(post_vitals, dict):
            post_time = encounter_time + timedelta(minutes=30 * (idx + 1))
            vitals_list.append(_parse_vitals(post_vitals, post_time))

    # Parse vitals_series (list of timestamped vitals dicts)
    vitals_series = patient_data.get("vitals_series")
    if vitals_series and isinstance(vitals_series, list):
        for entry in vitals_series:
            if not isinstance(entry, dict):
                continue
            ts_str = entry.get("time")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                except (ValueError, TypeError):
                    ts = encounter_time
            else:
                ts = encounter_time
            vitals_list.append(_parse_vitals(entry, ts))

    # Parse labs
    labs = _parse_labs(patient_data.get("labs"), encounter_time)

    # Parse imaging
    imaging = _parse_imaging(patient_data.get("imaging"), encounter_time)

    # Parse administered medications from active_orders or current_management
    meds_admin = _parse_meds_administered(
        patient_data.get("active_orders") or patient_data.get("current_management"),
        encounter_time,
    )

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
    vitals_source = vitals_data or {}
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
            labs = labs + _parse_labs(extra_labs, encounter_time)

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
        arrival_time=encounter_time,
        triage_time=encounter_time,
        disposition=None,
        attending_id=setting.get("attending_on_duty", ""),
        vitals=tuple(vitals_list),
        labs=labs,
        imaging=imaging,
        meds_administered=meds_admin,
        exam_findings=exam_findings,
        clinical_notes=clinical_notes,
    )

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
