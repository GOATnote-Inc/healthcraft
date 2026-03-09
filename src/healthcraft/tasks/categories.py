"""Task categories and difficulty levels for HEALTHCRAFT.

Defines the 6 task categories and 5 difficulty levels with associated
metadata about expected complexity.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum


class TaskCategory(Enum):
    """The 6 HEALTHCRAFT task categories."""

    TRIAGE = "triage"
    RESUSCITATION = "resuscitation"
    WORKUP = "workup"
    DISPOSITION = "disposition"
    PROCEDURES = "procedures"
    MASS_CASUALTY = "mass_casualty"


class DifficultyLevel(IntEnum):
    """Task difficulty levels (1=simplest, 5=most complex)."""

    TRIAGE = 1
    SINGLE_PATIENT = 2
    MULTI_SYSTEM = 3
    MULTI_PATIENT = 4
    MASS_CASUALTY = 5


@dataclass(frozen=True)
class CategoryMetadata:
    """Metadata describing expected complexity for a task category."""

    category: TaskCategory
    expected_tool_call_min: int
    expected_tool_call_max: int
    entity_type_count: int  # How many entity types are typically involved
    temporal_reasoning_level: int  # 0=none, 1=basic, 2=moderate, 3=critical
    description: str


# --- Module-level category metadata ---

CATEGORY_METADATA: dict[TaskCategory, CategoryMetadata] = {
    TaskCategory.TRIAGE: CategoryMetadata(
        category=TaskCategory.TRIAGE,
        expected_tool_call_min=3,
        expected_tool_call_max=8,
        entity_type_count=3,
        temporal_reasoning_level=1,
        description=(
            "Initial patient assessment and ESI assignment. "
            "Requires vitals, chief complaint evaluation, and bed assignment."
        ),
    ),
    TaskCategory.RESUSCITATION: CategoryMetadata(
        category=TaskCategory.RESUSCITATION,
        expected_tool_call_min=10,
        expected_tool_call_max=25,
        entity_type_count=8,
        temporal_reasoning_level=3,
        description=(
            "Life-threatening emergencies requiring immediate intervention. "
            "Strict temporal constraints (e.g., door-to-needle, ROSC)."
        ),
    ),
    TaskCategory.WORKUP: CategoryMetadata(
        category=TaskCategory.WORKUP,
        expected_tool_call_min=5,
        expected_tool_call_max=15,
        entity_type_count=6,
        temporal_reasoning_level=1,
        description=(
            "Diagnostic evaluation of undifferentiated complaints. "
            "Requires appropriate lab, imaging, and assessment orders."
        ),
    ),
    TaskCategory.DISPOSITION: CategoryMetadata(
        category=TaskCategory.DISPOSITION,
        expected_tool_call_min=4,
        expected_tool_call_max=12,
        entity_type_count=5,
        temporal_reasoning_level=1,
        description=(
            "Clinical decision-making for patient disposition. "
            "Requires synthesis of workup results into admit/discharge decision."
        ),
    ),
    TaskCategory.PROCEDURES: CategoryMetadata(
        category=TaskCategory.PROCEDURES,
        expected_tool_call_min=6,
        expected_tool_call_max=15,
        entity_type_count=6,
        temporal_reasoning_level=2,
        description=(
            "Procedural tasks (intubation, chest tube, central line, etc.). "
            "Requires correct sequencing, documentation, and safety checks."
        ),
    ),
    TaskCategory.MASS_CASUALTY: CategoryMetadata(
        category=TaskCategory.MASS_CASUALTY,
        expected_tool_call_min=20,
        expected_tool_call_max=50,
        entity_type_count=10,
        temporal_reasoning_level=3,
        description=(
            "Multiple simultaneous patients requiring triage, "
            "resource allocation, and parallel management. "
            "Highest complexity level."
        ),
    ),
}
