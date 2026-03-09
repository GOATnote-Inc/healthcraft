"""Clinical task entity for the HEALTHCRAFT simulation."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from healthcraft.entities.base import Entity, EntityType


@dataclass(frozen=True)
class ClinicalTask(Entity):
    """Immutable clinical task entity representing work to be done for an encounter.

    Extends Entity with task tracking fields for lab draws, imaging studies,
    medication administration, procedures, consults, nursing tasks, and
    documentation.
    """

    task_id: str = ""
    encounter_id: str = ""
    treatment_plan_id: str = ""
    task_type: str = (
        ""  # lab_draw, imaging, medication_admin, procedure, consult, nursing, documentation
    )
    description: str = ""
    status: str = "pending"  # pending, in_progress, completed, cancelled, on_hold
    priority: str = "routine"  # stat, urgent, routine
    assigned_to: str = ""
    ordered_by: str = ""
    due_time: datetime | None = None
    completed_time: datetime | None = None
    result: str = ""
    notes: str = ""


# --- Task type definitions ---

_TASK_TYPES = (
    "lab_draw",
    "imaging",
    "medication_admin",
    "procedure",
    "consult",
    "nursing",
    "documentation",
)

_TASK_DESCRIPTIONS: dict[str, tuple[str, ...]] = {
    "lab_draw": (
        "CBC with differential",
        "BMP (basic metabolic panel)",
        "CMP (comprehensive metabolic panel)",
        "Troponin I",
        "D-dimer",
        "Lactate level",
        "Blood cultures x2",
        "Coagulation panel (PT/INR/PTT)",
        "Lipase",
        "Urinalysis with culture",
        "Type and screen",
        "BNP (brain natriuretic peptide)",
        "ABG (arterial blood gas)",
        "Procalcitonin",
        "Blood alcohol level",
        "Urine drug screen",
    ),
    "imaging": (
        "Chest X-ray PA and lateral",
        "CT head without contrast",
        "CT abdomen/pelvis with contrast",
        "CT angiography chest",
        "Portable chest X-ray",
        "X-ray extremity (specify side)",
        "Ultrasound RUQ (gallbladder)",
        "Ultrasound FAST exam",
        "CT cervical spine",
        "MRI brain with and without contrast",
        "X-ray pelvis AP",
        "CT angiography head and neck",
    ),
    "medication_admin": (
        "Normal saline 1L IV bolus",
        "Morphine 4mg IV push",
        "Ondansetron 4mg IV push",
        "Ketorolac 30mg IV push",
        "Ceftriaxone 1g IV",
        "Acetaminophen 1000mg PO",
        "Aspirin 325mg PO",
        "Heparin 5000 units IV bolus",
        "Nitroglycerin 0.4mg SL",
        "Albuterol 2.5mg nebulizer",
        "Methylprednisolone 125mg IV",
        "Diphenhydramine 50mg IV push",
        "Epinephrine 0.3mg IM",
        "Lorazepam 2mg IV push",
        "Metoclopramide 10mg IV",
    ),
    "procedure": (
        "Peripheral IV placement (18g)",
        "Peripheral IV placement (20g)",
        "Central line placement (IJ)",
        "Arterial line placement",
        "Foley catheter insertion",
        "Nasogastric tube insertion",
        "Lumbar puncture",
        "Chest tube insertion",
        "Wound irrigation and closure",
        "Incision and drainage",
        "Splint application",
        "Procedural sedation",
        "Rapid sequence intubation",
        "Cardioversion",
        "Needle decompression",
    ),
    "consult": (
        "Cardiology consult",
        "Surgery consult",
        "Neurology consult",
        "GI consult",
        "Orthopedics consult",
        "Psychiatry consult",
        "OB/GYN consult",
        "Nephrology consult",
        "Pulmonology consult",
        "Toxicology consult",
        "Interventional radiology consult",
        "Social work consult",
    ),
    "nursing": (
        "Continuous cardiac monitoring",
        "Pulse oximetry monitoring",
        "Repeat vital signs in 15 minutes",
        "Repeat vital signs in 1 hour",
        "Strict I&O monitoring",
        "Neuro checks q15 min",
        "Fall precautions",
        "Seizure precautions",
        "NPO status",
        "Wound care and dressing change",
        "Blood glucose monitoring q1h",
        "1:1 sitter for safety",
    ),
    "documentation": (
        "Complete H&P documentation",
        "Medical decision making note",
        "Procedure note",
        "Discharge instructions",
        "Transfer summary",
        "Consent form completion",
        "Against medical advice documentation",
        "Critical care time documentation",
        "Reassessment note",
        "Specialist communication note",
    ),
}

# --- Priority-specific notes ---

_STAT_NOTES = (
    "STAT order per attending",
    "Critical result expected - notify immediately",
    "Time-sensitive - do not delay",
    "Code team activated",
    "Stroke alert protocol",
)

_URGENT_NOTES = (
    "Expedite per attending",
    "Patient condition may deteriorate",
    "Needed before disposition decision",
    "Pending consult arrival",
    "Required for surgical clearance",
)

_ROUTINE_NOTES = (
    "",
    "",
    "Per ED protocol",
    "Standing order",
    "Follow-up from initial workup",
    "Reassessment per nursing protocol",
)

# --- Due time offsets by priority (minutes from order) ---

_DUE_TIME_RANGES: dict[str, tuple[int, int]] = {
    "stat": (5, 30),
    "urgent": (30, 120),
    "routine": (60, 360),
}

# --- Staff ID pools ---

_ATTENDING_IDS = (
    "STAFF-ATT-001",
    "STAFF-ATT-002",
    "STAFF-ATT-003",
    "STAFF-ATT-004",
    "STAFF-ATT-005",
    "STAFF-ATT-006",
)

_NURSE_IDS = (
    "STAFF-RN-001",
    "STAFF-RN-002",
    "STAFF-RN-003",
    "STAFF-RN-004",
    "STAFF-RN-005",
    "STAFF-RN-006",
    "STAFF-RN-007",
    "STAFF-RN-008",
)

_TECH_IDS = (
    "STAFF-TECH-001",
    "STAFF-TECH-002",
    "STAFF-TECH-003",
    "STAFF-TECH-004",
)

# --- Assignment rules by task type ---

_ASSIGNEE_POOL: dict[str, tuple[str, ...]] = {
    "lab_draw": _NURSE_IDS + _TECH_IDS,
    "imaging": _TECH_IDS,
    "medication_admin": _NURSE_IDS,
    "procedure": _ATTENDING_IDS,
    "consult": (),  # assigned_to left empty, external service
    "nursing": _NURSE_IDS,
    "documentation": _ATTENDING_IDS + _NURSE_IDS,
}


def generate_clinical_task(
    rng: random.Random,
    encounter_id: str,
    task_type: str,
) -> ClinicalTask:
    """Generate a deterministic clinical task entity.

    Args:
        rng: Seeded Random instance for deterministic generation.
        encounter_id: The encounter this task belongs to.
        task_type: One of: lab_draw, imaging, medication_admin, procedure,
            consult, nursing, documentation.

    Returns:
        A frozen ClinicalTask instance.

    Raises:
        ValueError: If task_type is not a recognized type.
    """
    if task_type not in _TASK_DESCRIPTIONS:
        raise ValueError(
            f"Unknown task_type: {task_type!r}. Must be one of: {', '.join(_TASK_TYPES)}"
        )

    task_id = f"TASK-{uuid.UUID(int=rng.getrandbits(128)).hex[:8].upper()}"

    description = rng.choice(_TASK_DESCRIPTIONS[task_type])

    # Priority distribution depends on task type
    if task_type in ("procedure", "medication_admin"):
        priority = rng.choices(
            population=["stat", "urgent", "routine"],
            weights=[30, 40, 30],
            k=1,
        )[0]
    elif task_type == "consult":
        priority = rng.choices(
            population=["stat", "urgent", "routine"],
            weights=[15, 50, 35],
            k=1,
        )[0]
    elif task_type == "lab_draw":
        priority = rng.choices(
            population=["stat", "urgent", "routine"],
            weights=[25, 35, 40],
            k=1,
        )[0]
    else:
        priority = rng.choices(
            population=["stat", "urgent", "routine"],
            weights=[10, 30, 60],
            k=1,
        )[0]

    # Ordering physician
    ordered_by = rng.choice(_ATTENDING_IDS)

    # Assignment: some task types get assigned, consults stay empty
    assignee_pool = _ASSIGNEE_POOL[task_type]
    if assignee_pool:
        assigned_to = rng.choice(assignee_pool)
    else:
        assigned_to = ""

    # Due time based on priority
    due_min, due_max = _DUE_TIME_RANGES[priority]
    due_offset_minutes = rng.randint(due_min, due_max)

    # Notes based on priority
    if priority == "stat":
        notes = rng.choice(_STAT_NOTES)
    elif priority == "urgent":
        notes = rng.choice(_URGENT_NOTES)
    else:
        notes = rng.choice(_ROUTINE_NOTES)

    now = datetime.now(timezone.utc)
    due_time = now + timedelta(minutes=due_offset_minutes)

    return ClinicalTask(
        id=task_id,
        entity_type=EntityType.CLINICAL_TASK,
        created_at=now,
        updated_at=now,
        task_id=task_id,
        encounter_id=encounter_id,
        treatment_plan_id="",
        task_type=task_type,
        description=description,
        status="pending",
        priority=priority,
        assigned_to=assigned_to,
        ordered_by=ordered_by,
        due_time=due_time,
        completed_time=None,
        result="",
        notes=notes,
    )
