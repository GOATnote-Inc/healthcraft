"""Maps OpenEM conditions to HEALTHCRAFT entities.

Handles the 370-condition -> entity generation pipeline, converting
OpenEM's condition format into ClinicalKnowledge entities and patient
presentation parameters.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

from healthcraft.entities.base import EntityType
from healthcraft.entities.clinical_knowledge import ClinicalKnowledge


def map_condition_to_knowledge(condition: dict[str, Any]) -> ClinicalKnowledge:
    """Convert an OpenEM condition dict to a ClinicalKnowledge entity.

    Handles both the OpenEM corpus format and the bundled subset format.

    Args:
        condition: A condition dict from OpenEM or bundled data.

    Returns:
        A frozen ClinicalKnowledge entity.
    """
    cid = condition.get("condition_id", condition.get("id", "UNKNOWN"))
    now = datetime.now(timezone.utc)

    return ClinicalKnowledge(
        id=f"CK-{cid}",
        entity_type=EntityType.CLINICAL_KNOWLEDGE,
        created_at=now,
        updated_at=now,
        condition_id=cid,
        condition_name=condition.get("condition_name", condition.get("name", "")),
        icd10=condition.get("icd10", condition.get("icd10_code", "")),
        esi=condition.get("esi", condition.get("esi_level", 3)),
        time_to_harm=condition.get("time_to_harm", ""),
        category=condition.get("category", ""),
        confusion_pairs=tuple(condition.get("confusion_pairs", ())),
        decision_rules=tuple(condition.get("decision_rules", ())),
        critical_actions=tuple(condition.get("critical_actions", ())),
        differentials=tuple(condition.get("differentials", ())),
        workup=tuple(condition.get("workup", ())),
        treatment=tuple(condition.get("treatment", ())),
        pitfalls=tuple(condition.get("pitfalls", ())),
    )


def map_condition_to_patient_presentation(
    condition: dict[str, Any],
    rng: random.Random,
) -> dict[str, Any]:
    """Generate patient presentation parameters from a condition.

    Creates a dict of presentation attributes (chief complaint, vitals
    ranges, expected labs, etc.) that can drive patient and encounter
    generation for this specific condition.

    Args:
        condition: A condition dict from OpenEM or bundled data.
        rng: Seeded Random instance for deterministic generation.

    Returns:
        Dict with presentation parameters for entity generation.
    """
    cid = condition.get("condition_id", condition.get("id", ""))
    category = condition.get("category", "")
    time_to_harm = condition.get("time_to_harm", "hours")
    esi = condition.get("esi", condition.get("esi_level", 3))

    # Chief complaint derived from condition name or custom mapping
    chief_complaint = condition.get(
        "chief_complaint",
        condition.get("condition_name", condition.get("name", "Undifferentiated complaint")),
    )

    # Demographics influenced by condition epidemiology
    age_range = _get_age_range(category, rng)
    sex_weight = _get_sex_weight(category, condition)

    # Acuity-driven vitals ranges
    vitals_profile = _get_vitals_profile(esi, time_to_harm, rng)

    return {
        "condition_id": cid,
        "chief_complaint": chief_complaint,
        "esi_level": esi,
        "age_min": age_range[0],
        "age_max": age_range[1],
        "sex_m_weight": sex_weight[0],
        "sex_f_weight": sex_weight[1],
        "vitals_profile": vitals_profile,
        "expected_workup": list(condition.get("workup", [])),
        "expected_treatment": list(condition.get("treatment", [])),
        "critical_actions": list(condition.get("critical_actions", [])),
    }


def _get_age_range(category: str, rng: random.Random) -> tuple[int, int]:
    """Determine age range based on condition category."""
    category_ages: dict[str, tuple[int, int]] = {
        "cardiovascular": (40, 90),
        "neurological": (30, 90),
        "pulmonary": (18, 85),
        "gastrointestinal": (18, 80),
        "infectious": (18, 90),
        "trauma": (18, 65),
        "toxicological": (18, 50),
        "obstetric": (18, 45),
        "pediatric": (0, 17),
        "psychiatric": (18, 70),
        "environmental": (18, 80),
        "endocrine": (25, 85),
        "renal": (30, 85),
        "hematologic": (18, 80),
    }
    return category_ages.get(category, (18, 85))


def _get_sex_weight(
    category: str,
    condition: dict[str, Any],
) -> tuple[float, float]:
    """Determine sex distribution weights based on condition epidemiology."""
    # Some conditions have strong sex predilections
    if category == "obstetric":
        return (0.0, 1.0)
    # Default roughly equal
    return (0.5, 0.5)


def _get_vitals_profile(
    esi: int,
    time_to_harm: str,
    rng: random.Random,
) -> dict[str, Any]:
    """Generate vitals profile ranges based on acuity."""
    if esi <= 1:
        return {
            "hr_range": (110, 160),
            "sbp_range": (60, 90),
            "rr_range": (24, 40),
            "spo2_range": (70, 90),
            "gcs_range": (3, 10),
        }
    elif esi == 2:
        return {
            "hr_range": (90, 130),
            "sbp_range": (80, 160),
            "rr_range": (18, 30),
            "spo2_range": (85, 96),
            "gcs_range": (10, 15),
        }
    elif esi == 3:
        return {
            "hr_range": (70, 110),
            "sbp_range": (100, 160),
            "rr_range": (14, 22),
            "spo2_range": (93, 99),
            "gcs_range": (15, 15),
        }
    else:
        return {
            "hr_range": (60, 100),
            "sbp_range": (110, 140),
            "rr_range": (12, 20),
            "spo2_range": (96, 100),
            "gcs_range": (15, 15),
        }
