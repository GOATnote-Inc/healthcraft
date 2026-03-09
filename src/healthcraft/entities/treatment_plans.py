"""Treatment plan entity for the HEALTHCRAFT simulation."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from healthcraft.entities.base import Entity, EntityType


@dataclass(frozen=True)
class TreatmentPlan(Entity):
    """Immutable treatment plan entity for an active ED encounter.

    Extends Entity with ordered medications, procedures, labs, imaging,
    consults, and disposition planning tied to a clinical condition.
    """

    encounter_id: str = ""
    patient_id: str = ""
    condition_ref: str = ""  # References a ClinicalKnowledge condition_id
    status: str = ""  # "draft", "active", "completed", "cancelled"
    priority: str = ""  # "stat", "urgent", "routine"
    medications: tuple[dict[str, Any], ...] = ()
    procedures: tuple[dict[str, Any], ...] = ()
    labs_ordered: tuple[dict[str, Any], ...] = ()
    imaging_ordered: tuple[dict[str, Any], ...] = ()
    consults: tuple[dict[str, Any], ...] = ()
    disposition_plan: str = ""  # "admit", "discharge", "transfer", "observation", ""
    notes: str = ""
    created_by: str = ""  # Staff ID


# --- Condition -> typical treatment plan elements ---

_CONDITION_TEMPLATES: dict[str, dict[str, Any]] = {
    "STEMI": {
        "priority": "stat",
        "medications": (
            {
                "name": "Aspirin",
                "dose": "325mg",
                "route": "PO",
                "frequency": "once",
                "indication": "Antiplatelet therapy for STEMI",
            },
            {
                "name": "Heparin",
                "dose": "60 units/kg bolus",
                "route": "IV",
                "frequency": "once then infusion",
                "indication": "Anticoagulation for STEMI",
            },
            {
                "name": "Ticagrelor",
                "dose": "180mg",
                "route": "PO",
                "frequency": "once",
                "indication": "P2Y12 inhibitor loading dose",
            },
            {
                "name": "Nitroglycerin",
                "dose": "0.4mg",
                "route": "SL",
                "frequency": "q5min x3 PRN",
                "indication": "Chest pain relief",
            },
            {
                "name": "Morphine",
                "dose": "2-4mg",
                "route": "IV",
                "frequency": "PRN",
                "indication": "Pain refractory to nitroglycerin",
            },
        ),
        "procedures": (
            {
                "name": "Percutaneous coronary intervention",
                "indication": "Primary PCI for STEMI",
                "urgency": "stat",
            },
        ),
        "labs": (
            {"test_name": "Troponin I", "indication": "Myocardial injury marker", "stat": True},
            {"test_name": "CBC", "indication": "Baseline", "stat": True},
            {"test_name": "BMP", "indication": "Electrolytes and renal function", "stat": True},
            {"test_name": "Coagulation studies", "indication": "Pre-anticoagulation", "stat": True},
            {"test_name": "Type and screen", "indication": "Potential cath lab", "stat": True},
        ),
        "imaging": (
            {
                "modality": "XR",
                "body_part": "Chest",
                "indication": "Evaluate cardiac silhouette and pulmonary edema",
                "contrast": False,
            },
        ),
        "consults": (
            {
                "specialty": "Interventional Cardiology",
                "question": "STEMI activation for primary PCI",
                "urgency": "stat",
            },
        ),
        "disposition": "admit",
    },
    "STROKE_ISCHEMIC": {
        "priority": "stat",
        "medications": (
            {
                "name": "Alteplase (tPA)",
                "dose": "0.9 mg/kg (max 90mg)",
                "route": "IV",
                "frequency": "10% bolus, remainder over 60 min",
                "indication": "Thrombolysis for acute ischemic stroke within window",
            },
            {
                "name": "Labetalol",
                "dose": "10-20mg",
                "route": "IV",
                "frequency": "PRN",
                "indication": "Blood pressure management pre-tPA",
            },
        ),
        "procedures": (
            {
                "name": "Mechanical thrombectomy",
                "indication": "Large vessel occlusion",
                "urgency": "stat",
            },
        ),
        "labs": (
            {"test_name": "Glucose", "indication": "Rule out hypoglycemia mimic", "stat": True},
            {"test_name": "CBC", "indication": "Platelet count pre-tPA", "stat": True},
            {"test_name": "BMP", "indication": "Baseline electrolytes", "stat": True},
            {"test_name": "Coagulation studies", "indication": "Pre-thrombolysis", "stat": True},
        ),
        "imaging": (
            {
                "modality": "CT",
                "body_part": "Head",
                "indication": "Rule out hemorrhagic stroke",
                "contrast": False,
            },
            {
                "modality": "CT",
                "body_part": "Head and neck",
                "indication": "CTA for large vessel occlusion",
                "contrast": True,
            },
        ),
        "consults": (
            {
                "specialty": "Neurology",
                "question": "Acute stroke evaluation for tPA and thrombectomy candidacy",
                "urgency": "stat",
            },
        ),
        "disposition": "admit",
    },
    "SEPSIS": {
        "priority": "stat",
        "medications": (
            {
                "name": "Normal Saline",
                "dose": "30 mL/kg",
                "route": "IV",
                "frequency": "bolus",
                "indication": "Fluid resuscitation for sepsis",
            },
            {
                "name": "Piperacillin-Tazobactam",
                "dose": "4.5g",
                "route": "IV",
                "frequency": "q6h",
                "indication": "Broad-spectrum empiric antibiotics",
            },
            {
                "name": "Vancomycin",
                "dose": "25-30 mg/kg",
                "route": "IV",
                "frequency": "once then per pharmacy",
                "indication": "MRSA coverage",
            },
            {
                "name": "Norepinephrine",
                "dose": "0.1-0.5 mcg/kg/min",
                "route": "IV",
                "frequency": "continuous infusion",
                "indication": "Vasopressor for refractory hypotension",
            },
        ),
        "procedures": (),
        "labs": (
            {"test_name": "Blood cultures x2", "indication": "Identify organism", "stat": True},
            {"test_name": "CBC", "indication": "WBC and differential", "stat": True},
            {"test_name": "BMP", "indication": "Renal function and electrolytes", "stat": True},
            {"test_name": "Lactate", "indication": "Sepsis severity marker", "stat": True},
            {
                "test_name": "Procalcitonin",
                "indication": "Bacterial infection marker",
                "stat": True,
            },
            {"test_name": "Urinalysis", "indication": "Evaluate urinary source", "stat": True},
        ),
        "imaging": (
            {
                "modality": "XR",
                "body_part": "Chest",
                "indication": "Evaluate for pneumonia source",
                "contrast": False,
            },
        ),
        "consults": (
            {
                "specialty": "Critical Care",
                "question": "Septic shock requiring ICU admission",
                "urgency": "urgent",
            },
        ),
        "disposition": "admit",
    },
    "PNEUMOTHORAX_TENSION": {
        "priority": "stat",
        "medications": (
            {
                "name": "Fentanyl",
                "dose": "50-100 mcg",
                "route": "IV",
                "frequency": "PRN",
                "indication": "Procedural analgesia for chest tube",
            },
            {
                "name": "Midazolam",
                "dose": "1-2mg",
                "route": "IV",
                "frequency": "PRN",
                "indication": "Procedural sedation for chest tube",
            },
        ),
        "procedures": (
            {
                "name": "Needle decompression",
                "indication": "Emergent decompression of tension pneumothorax",
                "urgency": "stat",
            },
            {
                "name": "Chest tube insertion",
                "indication": "Definitive management after needle decompression",
                "urgency": "stat",
            },
        ),
        "labs": (
            {"test_name": "ABG", "indication": "Assess oxygenation and ventilation", "stat": True},
            {"test_name": "CBC", "indication": "Baseline", "stat": True},
            {
                "test_name": "Type and screen",
                "indication": "Potential surgical intervention",
                "stat": True,
            },
        ),
        "imaging": (
            {
                "modality": "XR",
                "body_part": "Chest",
                "indication": "Post-intervention chest tube placement verification",
                "contrast": False,
            },
        ),
        "consults": (
            {
                "specialty": "Trauma Surgery",
                "question": "Tension pneumothorax requiring chest tube, evaluate for surgical management",
                "urgency": "stat",
            },
        ),
        "disposition": "admit",
    },
    "APPENDICITIS": {
        "priority": "urgent",
        "medications": (
            {
                "name": "Normal Saline",
                "dose": "1000 mL",
                "route": "IV",
                "frequency": "bolus then maintenance",
                "indication": "IV hydration",
            },
            {
                "name": "Morphine",
                "dose": "4mg",
                "route": "IV",
                "frequency": "q4h PRN",
                "indication": "Abdominal pain management",
            },
            {
                "name": "Ondansetron",
                "dose": "4mg",
                "route": "IV",
                "frequency": "q6h PRN",
                "indication": "Nausea and vomiting",
            },
            {
                "name": "Piperacillin-Tazobactam",
                "dose": "3.375g",
                "route": "IV",
                "frequency": "q6h",
                "indication": "Perioperative antibiotic prophylaxis",
            },
        ),
        "procedures": (
            {
                "name": "Appendectomy",
                "indication": "Definitive surgical management of acute appendicitis",
                "urgency": "urgent",
            },
        ),
        "labs": (
            {"test_name": "CBC", "indication": "WBC for infection severity", "stat": True},
            {"test_name": "BMP", "indication": "Electrolytes and renal function", "stat": True},
            {"test_name": "Lipase", "indication": "Rule out pancreatitis", "stat": False},
            {"test_name": "Urinalysis", "indication": "Rule out urinary cause", "stat": False},
            {
                "test_name": "Pregnancy test",
                "indication": "Rule out ectopic (if applicable)",
                "stat": True,
            },
        ),
        "imaging": (
            {
                "modality": "CT",
                "body_part": "Abdomen and pelvis",
                "indication": "Confirm appendicitis, evaluate for perforation",
                "contrast": True,
            },
        ),
        "consults": (
            {
                "specialty": "General Surgery",
                "question": "Acute appendicitis for surgical evaluation and appendectomy",
                "urgency": "urgent",
            },
        ),
        "disposition": "admit",
    },
}

# --- Fallback building blocks for unknown conditions ---

_FALLBACK_MEDICATIONS = (
    {
        "name": "Normal Saline",
        "dose": "1000 mL",
        "route": "IV",
        "frequency": "bolus",
        "indication": "IV fluid resuscitation",
    },
    {
        "name": "Acetaminophen",
        "dose": "1000mg",
        "route": "PO",
        "frequency": "q6h PRN",
        "indication": "Analgesia and antipyretic",
    },
    {
        "name": "Ondansetron",
        "dose": "4mg",
        "route": "IV",
        "frequency": "q6h PRN",
        "indication": "Antiemetic",
    },
    {
        "name": "Ketorolac",
        "dose": "15mg",
        "route": "IV",
        "frequency": "once",
        "indication": "Anti-inflammatory analgesia",
    },
)

_FALLBACK_LABS = (
    {"test_name": "CBC", "indication": "Baseline hematology", "stat": True},
    {"test_name": "BMP", "indication": "Electrolytes and renal function", "stat": True},
    {"test_name": "Urinalysis", "indication": "Screening", "stat": False},
)

_FALLBACK_IMAGING = (
    {
        "modality": "XR",
        "body_part": "Chest",
        "indication": "Screening radiograph",
        "contrast": False,
    },
)

_STATUS_OPTIONS = ("draft", "active")
_PRIORITY_OPTIONS = ("stat", "urgent", "routine")
_DISPOSITION_OPTIONS = ("admit", "discharge", "transfer", "observation", "")

_NOTES_TEMPLATES = (
    "Plan discussed with patient and family.",
    "Awaiting lab results to finalize disposition.",
    "Patient stable, monitoring for clinical change.",
    "Risks, benefits, and alternatives discussed. Patient agrees with plan.",
    "Reassess after initial interventions. Consider escalation if no improvement.",
    "NPO for potential procedural intervention.",
    "Social work consult pending for discharge planning.",
    "Awaiting specialist recommendations before finalizing plan.",
)

_STAFF_IDS = (
    "STAFF-ATT-001",
    "STAFF-ATT-002",
    "STAFF-ATT-003",
    "STAFF-ATT-004",
    "STAFF-ATT-005",
    "STAFF-RES-001",
    "STAFF-RES-002",
    "STAFF-RES-003",
    "STAFF-PA-001",
    "STAFF-PA-002",
)


def generate_treatment_plan(
    rng: random.Random,
    encounter_id: str,
    patient_id: str,
    condition_ref: str,
) -> TreatmentPlan:
    """Generate a deterministic treatment plan entity for an ED encounter.

    When the condition_ref matches a known template, generates a clinically
    realistic plan with condition-appropriate medications, procedures, labs,
    imaging, and consults. Falls back to generic ED workup for unknown
    conditions.

    Args:
        rng: Seeded Random instance for deterministic generation.
        encounter_id: The encounter this plan belongs to.
        patient_id: The patient this plan is for.
        condition_ref: A ClinicalKnowledge condition_id driving plan content.

    Returns:
        A frozen TreatmentPlan instance.
    """
    plan_id = f"TP-{uuid.UUID(int=rng.getrandbits(128)).hex[:8].upper()}"

    template = _CONDITION_TEMPLATES.get(condition_ref)

    if template is not None:
        priority = template["priority"]
        medications = template["medications"]
        procedures = template["procedures"]
        labs_ordered = template["labs"]
        imaging_ordered = template["imaging"]
        consults = template["consults"]
        disposition_plan = template["disposition"]
    else:
        # Fallback: pick a subset of generic orders
        priority = rng.choice(_PRIORITY_OPTIONS)

        med_count = rng.randint(1, len(_FALLBACK_MEDICATIONS))
        medications = tuple(rng.sample(_FALLBACK_MEDICATIONS, med_count))

        procedures: tuple[dict[str, Any], ...] = ()

        lab_count = rng.randint(1, len(_FALLBACK_LABS))
        labs_ordered = tuple(rng.sample(_FALLBACK_LABS, lab_count))

        # 60% chance of imaging for unknown conditions
        if rng.random() < 0.6:
            imaging_ordered = _FALLBACK_IMAGING
        else:
            imaging_ordered = ()

        consults = ()
        disposition_plan = rng.choice(_DISPOSITION_OPTIONS)

    # Status: most plans start active, some are drafts
    status = rng.choices(_STATUS_OPTIONS, weights=[20, 80], k=1)[0]

    notes = rng.choice(_NOTES_TEMPLATES)
    created_by = rng.choice(_STAFF_IDS)

    now = datetime.now(timezone.utc)
    return TreatmentPlan(
        id=plan_id,
        entity_type=EntityType.TREATMENT_PLAN,
        created_at=now,
        updated_at=now,
        encounter_id=encounter_id,
        patient_id=patient_id,
        condition_ref=condition_ref,
        status=status,
        priority=priority,
        medications=medications,
        procedures=procedures,
        labs_ordered=labs_ordered,
        imaging_ordered=imaging_ordered,
        consults=consults,
        disposition_plan=disposition_plan,
        notes=notes,
        created_by=created_by,
    )
