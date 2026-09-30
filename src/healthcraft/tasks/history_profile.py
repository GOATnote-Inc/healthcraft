"""Opt-in experimental materialization of linked IR-002 visit history.

This module is not part of default task injection. Date-only source records
remain date-only: no arrival instant, triage finding, or treatment is inferred.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta

from healthcraft.tasks.inject import inject_task_patient
from healthcraft.tasks.loader import Task
from healthcraft.world.state import WorldState

PROFILE_VERSION = "linked-history/v1"
_HISTORY_FIELD = "prior_ed_visits_30_days"
_FACT_FIELDS = ("chief_complaint", "diagnosis", "disposition", "notes")


def build_ir002_profile(world: WorldState, task: Task) -> dict:
    """Add linked history only after every input and destination passes preflight.

    The four visits must have unique ISO calendar dates in the 30 calendar days
    before the setting's local date. All clinical strings are copied verbatim.
    Reapplication and existing target identifiers raise ``ValueError`` instead
    of overwriting evidence. The returned JSON-safe context contains identifiers
    and baseline notes, not an oracle for the historical facts.
    """
    if task.id != "IR-002":
        raise ValueError("The linked-history/v1 profile is restricted to IR-002")
    if not isinstance(task.patient, dict) or not task.patient:
        raise ValueError("IR-002 requires a supplied patient record")
    if not isinstance(world.timestamp, datetime) or world.timestamp.utcoffset() is None:
        raise ValueError("The profile requires an aware world timestamp")

    setting = deepcopy(task.initial_state)
    if not isinstance(setting, dict) or not isinstance(setting.get("time"), str):
        raise ValueError("IR-002 setting.time must be an aware date-time string")
    try:
        # Preserve the declared zone and normalize Z for the legacy injector on
        # Python 3.10; it otherwise silently falls back to wall-clock time.
        setting_time = setting["time"]
        if setting_time.endswith(("Z", "z")):
            setting_time = setting_time[:-1] + "+00:00"
        arrival = datetime.fromisoformat(setting_time)
        if arrival.utcoffset() is None:
            raise ValueError("Missing timezone")
        end_date = arrival.date()
        start_date = end_date - timedelta(days=30)
    except (ValueError, OverflowError) as exc:
        raise ValueError("IR-002 setting.time must be a valid aware date-time") from exc
    setting["time"] = arrival.isoformat()

    rows = deepcopy(task.patient.get(_HISTORY_FIELD))
    if not isinstance(rows, list) or len(rows) != 4:
        raise ValueError("IR-002 requires exactly four supplied prior visits")
    seen_dates = set()
    prior_ids = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"Prior visit {index} must be a record")
        raw_date = row.get("date")
        if not isinstance(raw_date, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw_date
        ):
            raise ValueError(f"Prior visit {index} requires a date-only ISO date")
        try:
            visit_date = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise ValueError(f"Prior visit {index} has an invalid calendar date") from exc
        if visit_date in seen_dates or not start_date <= visit_date < end_date:
            raise ValueError(
                f"Prior visit {index} date must be unique and within the prior calendar window"
            )
        seen_dates.add(visit_date)
        for field in _FACT_FIELDS:
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f"Prior visit {index} requires a nonempty {field}")
        identity = f"{task.id}:{PROFILE_VERSION}:{raw_date}:{index}"
        prior_ids.append(f"ENC-{hashlib.sha256(identity.encode()).hexdigest()[:8].upper()}")

    # The legacy injector can fail while constructing a current encounter.
    # Stage it privately so such failures cannot partially change this world.
    staged = WorldState(start_time=world.timestamp)
    injected = inject_task_patient(staged, task.id, deepcopy(task.patient), setting)
    patient_id, current_id = injected["patient_id"], injected["encounter_id"]
    encounter_ids = [current_id, *prior_ids]
    if len(set(encounter_ids)) != len(encounter_ids):
        raise ValueError("Profile encounter identifier collision")
    targets = [("patient", patient_id), *(("encounter", eid) for eid in encounter_ids)]
    for kind, entity_id in targets:
        if world.get_entity(kind, entity_id) is not None:
            raise ValueError(f"Profile identifier collision: {entity_id} already exists")

    patient = replace(
        staged.get_entity("patient", patient_id),
        created_at=world.timestamp,
        updated_at=world.timestamp,
        prior_visit_ids=tuple(prior_ids),
    )
    current = replace(
        staged.get_entity("encounter", current_id),
        created_at=world.timestamp,
        updated_at=world.timestamp,
        arrival_time=arrival,
    )
    historical = [
        {
            "id": entity_id,
            "entity_type": "encounter",
            "patient_id": patient_id,
            "arrival_time": None,
            "visit_date": row["date"],
            "date_precision": "day",
            **{field: row[field] for field in _FACT_FIELDS},
            "profile_version": PROFILE_VERSION,
        }
        for entity_id, row in zip(prior_ids, rows)
    ]
    context = {
        "profile_version": PROFILE_VERSION,
        "task_id": task.id,
        "patient_id": patient_id,
        "current_encounter_id": current_id,
        "window": {
            "start": start_date.isoformat(),
            "end_exclusive": end_date.isoformat(),
            "semantics": "prior_calendar_days",
        },
        "prior_encounter_ids": list(prior_ids),
        "initial_clinical_note_ids": sorted(world.list_entities("clinical_note")),
        "initial_target_notes": json.loads(json.dumps(current.clinical_notes)),
    }

    # All validation and construction is complete before the first target write.
    world.put_entity("patient", patient_id, patient)
    world.put_entity("encounter", current_id, current)
    for record in historical:
        world.put_entity("encounter", record["id"], record)
    return deepcopy(context)
