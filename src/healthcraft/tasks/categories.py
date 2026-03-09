"""Task categories and difficulty levels for HEALTHCRAFT.

Defines the 6 task categories (matching Corecraft + 2 new) and 5 difficulty
levels with associated metadata about expected complexity.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum


class TaskCategory(Enum):
    """The 6 HEALTHCRAFT task categories.

    Categories 1-4 map from Corecraft. Categories 5-6 are new for EM.
    """

    INFORMATION_RETRIEVAL = "information_retrieval"
    CLINICAL_COMMUNICATION = "clinical_communication"
    CLINICAL_REASONING = "clinical_reasoning"
    MULTI_STEP_WORKFLOWS = "multi_step_workflows"
    TEMPORAL_REASONING = "temporal_reasoning"
    SAFETY_CRITICAL_JUDGMENT = "safety_critical_judgment"


class DifficultyLevel(IntEnum):
    """Task difficulty levels (1=simplest, 5=most complex).

    Levels 1-4 map from Corecraft. Level 5 is new for EM.
    """

    TRIAGE = 1  # 1-2 tool calls
    WORKUP = 2  # 2-4 tool calls
    TREATMENT = 3  # 4-8 tool calls
    RESUSCITATION = 4  # 8-15 tool calls
    MASS_CASUALTY = 5  # 15+ tool calls


@dataclass(frozen=True)
class CategoryMetadata:
    """Metadata describing expected complexity for a task category."""

    category: TaskCategory
    expected_tool_call_min: int
    expected_tool_call_max: int
    entity_type_count: int
    temporal_reasoning_level: int  # 0=none, 1=basic, 2=moderate, 3=critical
    description: str


CATEGORY_METADATA: dict[TaskCategory, CategoryMetadata] = {
    TaskCategory.INFORMATION_RETRIEVAL: CategoryMetadata(
        category=TaskCategory.INFORMATION_RETRIEVAL,
        expected_tool_call_min=1,
        expected_tool_call_max=4,
        entity_type_count=3,
        temporal_reasoning_level=0,
        description=(
            "Entity lookup and search tasks. Verify patient records, "
            "check allergies, retrieve encounter history."
        ),
    ),
    TaskCategory.CLINICAL_COMMUNICATION: CategoryMetadata(
        category=TaskCategory.CLINICAL_COMMUNICATION,
        expected_tool_call_min=3,
        expected_tool_call_max=8,
        entity_type_count=4,
        temporal_reasoning_level=1,
        description=(
            "Communication tasks: discharge instructions, consult requests, "
            "transfer summaries, MDM documentation."
        ),
    ),
    TaskCategory.CLINICAL_REASONING: CategoryMetadata(
        category=TaskCategory.CLINICAL_REASONING,
        expected_tool_call_min=4,
        expected_tool_call_max=15,
        entity_type_count=6,
        temporal_reasoning_level=2,
        description=(
            "Differential diagnosis and clinical decision-making. "
            "Includes confusion pairs, decision rule application, "
            "and treatment planning."
        ),
    ),
    TaskCategory.MULTI_STEP_WORKFLOWS: CategoryMetadata(
        category=TaskCategory.MULTI_STEP_WORKFLOWS,
        expected_tool_call_min=8,
        expected_tool_call_max=20,
        entity_type_count=8,
        temporal_reasoning_level=2,
        description=(
            "Complex multi-step clinical workflows: sepsis bundles, "
            "STEMI alerts, trauma activations, regulatory navigation."
        ),
    ),
    TaskCategory.TEMPORAL_REASONING: CategoryMetadata(
        category=TaskCategory.TEMPORAL_REASONING,
        expected_tool_call_min=10,
        expected_tool_call_max=50,
        entity_type_count=10,
        temporal_reasoning_level=3,
        description=(
            "Time-critical sequencing with overlapping protocols, "
            "competing demands, and resource allocation under load."
        ),
    ),
    TaskCategory.SAFETY_CRITICAL_JUDGMENT: CategoryMetadata(
        category=TaskCategory.SAFETY_CRITICAL_JUDGMENT,
        expected_tool_call_min=6,
        expected_tool_call_max=15,
        entity_type_count=6,
        temporal_reasoning_level=1,
        description=(
            "Judgment under uncertainty: capacity assessment, EMTALA, "
            "protocol override, ethical dilemmas, regulatory compliance."
        ),
    ),
}
