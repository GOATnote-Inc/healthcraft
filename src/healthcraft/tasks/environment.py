"""Prepare task-specific records and identifier context for execution surfaces."""

from __future__ import annotations

from dataclasses import replace

from healthcraft.tasks.inject import inject_task_patient
from healthcraft.tasks.loader import Task
from healthcraft.world.state import WorldState


def prepare_task_environment(
    world: WorldState, task: Task, *, profile: str | None = None
) -> tuple[Task, dict]:
    """Keep published injection by default; opt-in profiles have separate identities."""
    if profile is not None:
        from healthcraft.tasks.roster_profile import PROFILE_VERSION, build_roster_profile

        if profile != PROFILE_VERSION:
            raise ValueError(f"Unknown scenario profile: {profile}")
        context = build_roster_profile(world, task)
        hint = (
            f"\n\nExperimental scenario profile: {profile}, not clinically validated. "
            "The following identifiers refer to separate task-supplied records. "
            "Retrieve their authored observations through the tools. Source assessments "
            "may be incorrect; missing facts and arrival timestamps remain unknown. "
            "These records do not allocate beds or assert that incoming patients have arrived.\n"
        )
        hint += "\n".join(
            f"{row['label']}: patient {row['patient_id']}, encounter {row['encounter_id']} "
            f"({row['source_context']})."
            for row in context["roster"]
        )
        return replace(task, description=task.description.rstrip() + hint), context
    if not task.patient:
        return task, {}
    context = inject_task_patient(world, task.id, task.patient, task.initial_state)
    hint = (
        f"\n\nRelevant patient ID: {context['patient_id']}. "
        f"Active encounter ID: {context['encounter_id']}."
    )
    return replace(task, description=task.description.rstrip() + hint), context
