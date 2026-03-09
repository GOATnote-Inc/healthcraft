"""Clinical knowledge entity bridging OpenEM condition data to HEALTHCRAFT."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from healthcraft.entities.base import Entity, EntityType


@dataclass(frozen=True)
class ClinicalKnowledge(Entity):
    """Immutable clinical knowledge entity derived from OpenEM conditions.

    Contains structured clinical data used by the task engine and MCP tools
    to drive clinically realistic scenarios.
    """

    condition_id: str = ""
    condition_name: str = ""
    icd10: str = ""
    esi: int = 3  # Default ESI level
    time_to_harm: str = ""  # e.g. "minutes", "hours", "days"
    category: str = ""
    confusion_pairs: tuple[dict[str, Any], ...] = ()
    decision_rules: tuple[dict[str, Any], ...] = ()
    critical_actions: tuple[str, ...] = ()
    differentials: tuple[str, ...] = ()
    workup: tuple[str, ...] = ()
    treatment: tuple[str, ...] = ()
    pitfalls: tuple[str, ...] = ()


# --- Bundled fallback subset (when OpenEM is not installed) ---

_BUNDLED_CONDITIONS: dict[str, dict[str, Any]] = {
    "STEMI": {
        "condition_id": "STEMI",
        "condition_name": "ST-Elevation Myocardial Infarction",
        "icd10": "I21.3",
        "esi": 1,
        "time_to_harm": "minutes",
        "category": "cardiovascular",
        "critical_actions": (
            "12-lead ECG within 10 minutes",
            "Activate cath lab",
            "Aspirin 325mg",
            "Heparin bolus",
            "Door-to-balloon < 90 minutes",
        ),
        "differentials": (
            "Aortic dissection",
            "Pulmonary embolism",
            "Pericarditis",
            "Takotsubo cardiomyopathy",
        ),
        "workup": ("ECG", "Troponin", "CBC", "BMP", "Coagulation studies", "Chest X-ray"),
        "treatment": (
            "Aspirin",
            "Heparin",
            "P2Y12 inhibitor",
            "Percutaneous coronary intervention",
            "Morphine PRN",
        ),
        "pitfalls": (
            "Delayed ECG interpretation",
            "Missing posterior STEMI",
            "Thrombolytics in dissection",
        ),
    },
    "STROKE_ISCHEMIC": {
        "condition_id": "STROKE_ISCHEMIC",
        "condition_name": "Acute Ischemic Stroke",
        "icd10": "I63.9",
        "esi": 1,
        "time_to_harm": "minutes",
        "category": "neurological",
        "critical_actions": (
            "CT head without contrast STAT",
            "Check glucose",
            "Establish time of onset / last known well",
            "tPA if within window",
            "Neurology consult",
        ),
        "differentials": (
            "Hemorrhagic stroke",
            "Todd's paralysis",
            "Hypoglycemia",
            "Complex migraine",
            "Bell's palsy",
        ),
        "workup": ("CT head", "CTA head/neck", "Glucose", "CBC", "BMP", "Coagulation studies"),
        "treatment": ("tPA (alteplase)", "Blood pressure management", "Thrombectomy if LVO"),
        "pitfalls": (
            "Stroke mimics delaying treatment",
            "Missing posterior circulation stroke",
            "Not checking glucose before tPA",
        ),
    },
    "SEPSIS": {
        "condition_id": "SEPSIS",
        "condition_name": "Sepsis",
        "icd10": "A41.9",
        "esi": 2,
        "time_to_harm": "hours",
        "category": "infectious",
        "critical_actions": (
            "Blood cultures before antibiotics",
            "Broad-spectrum antibiotics within 1 hour",
            "30 mL/kg crystalloid for hypotension",
            "Lactate level",
            "Reassess after fluid bolus",
        ),
        "differentials": (
            "Cardiogenic shock",
            "Anaphylaxis",
            "Adrenal crisis",
            "Hypovolemic shock",
        ),
        "workup": (
            "Blood cultures x2",
            "CBC",
            "BMP",
            "Lactate",
            "Urinalysis",
            "Chest X-ray",
            "Procalcitonin",
        ),
        "treatment": (
            "IV crystalloid bolus",
            "Broad-spectrum antibiotics",
            "Vasopressors if refractory hypotension",
            "Source control",
        ),
        "pitfalls": (
            "Delayed antibiotics",
            "Insufficient fluid resuscitation",
            "Missing the source",
        ),
    },
    "PNEUMOTHORAX_TENSION": {
        "condition_id": "PNEUMOTHORAX_TENSION",
        "condition_name": "Tension Pneumothorax",
        "icd10": "J93.0",
        "esi": 1,
        "time_to_harm": "minutes",
        "category": "pulmonary",
        "critical_actions": (
            "Needle decompression",
            "Chest tube placement",
            "Do NOT delay for imaging",
        ),
        "differentials": (
            "Simple pneumothorax",
            "Hemothorax",
            "Cardiac tamponade",
            "Massive PE",
        ),
        "workup": ("Clinical diagnosis", "Chest X-ray (post-intervention)", "ABG"),
        "treatment": (
            "Needle decompression (2nd ICS MCL or 5th ICS MAL)",
            "Chest tube (28-32 Fr)",
            "Supplemental oxygen",
        ),
        "pitfalls": (
            "Waiting for chest X-ray in unstable patient",
            "Needle too short for decompression",
            "Missing in intubated patient",
        ),
    },
    "APPENDICITIS": {
        "condition_id": "APPENDICITIS",
        "condition_name": "Acute Appendicitis",
        "icd10": "K35.80",
        "esi": 3,
        "time_to_harm": "hours",
        "category": "gastrointestinal",
        "critical_actions": (
            "Surgical consult",
            "IV access and fluids",
            "Pain management",
            "NPO status",
        ),
        "differentials": (
            "Ovarian torsion",
            "Ectopic pregnancy",
            "Mesenteric lymphadenitis",
            "Crohn's disease",
            "Right lower lobe pneumonia",
        ),
        "workup": (
            "CBC",
            "BMP",
            "Lipase",
            "Urinalysis",
            "CT abdomen/pelvis with contrast",
            "Pregnancy test (if applicable)",
        ),
        "treatment": ("Appendectomy", "IV antibiotics", "IV fluids", "Analgesia"),
        "pitfalls": (
            "Atypical presentation in elderly",
            "Missing perforation",
            "Anchoring on UTI with RLQ pain",
        ),
    },
}


def load_clinical_knowledge(
    condition_map: dict[str, Any] | None = None,
) -> dict[str, ClinicalKnowledge]:
    """Load clinical knowledge entities.

    When a condition_map (from OpenEM) is provided, converts all conditions.
    Otherwise falls back to the bundled subset.

    Args:
        condition_map: Optional dict of condition_id -> condition data from OpenEM.

    Returns:
        Dict of condition_id -> ClinicalKnowledge.
    """
    now = datetime.now(timezone.utc)
    result: dict[str, ClinicalKnowledge] = {}

    source = condition_map if condition_map is not None else _BUNDLED_CONDITIONS

    for cid, data in source.items():
        # Handle both OpenEM format and bundled format
        ck = ClinicalKnowledge(
            id=f"CK-{cid}",
            entity_type=EntityType.CLINICAL_KNOWLEDGE,
            created_at=now,
            updated_at=now,
            condition_id=data.get("condition_id", cid),
            condition_name=data.get("condition_name", data.get("name", cid)),
            icd10=data.get("icd10", data.get("icd10_code", "")),
            esi=data.get("esi", data.get("esi_level", 3)),
            time_to_harm=data.get("time_to_harm", ""),
            category=data.get("category", ""),
            confusion_pairs=tuple(data.get("confusion_pairs", ())),
            decision_rules=tuple(data.get("decision_rules", ())),
            critical_actions=tuple(data.get("critical_actions", ())),
            differentials=tuple(data.get("differentials", ())),
            workup=tuple(data.get("workup", ())),
            treatment=tuple(data.get("treatment", ())),
            pitfalls=tuple(data.get("pitfalls", ())),
        )
        result[cid] = ck

    return result
