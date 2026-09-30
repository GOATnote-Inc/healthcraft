"""Experimental IR-002 history is linked, date-honest, isolated, and atomic."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from healthcraft.entities.base import EntityType
from healthcraft.mcp.server import create_server
from healthcraft.tasks.history_profile import PROFILE_VERSION, build_ir002_profile
from healthcraft.tasks.loader import load_task
from healthcraft.world.state import WorldState

TASK_PATH = (
    Path(__file__).resolve().parents[2]
    / "configs/tasks/information_retrieval/task_002_encounter_lookup.yaml"
)
HISTORY_FIELD = "prior_ed_visits_30_days"


@pytest.fixture
def task():
    return load_task(TASK_PATH)


@pytest.fixture
def world():
    world = WorldState()
    world.put_entity(
        "patient", "PAT-FFFFFFFF", {"id": "PAT-FFFFFFFF", "notes": {"raw": ["preserve"]}}
    )
    world.put_entity(
        "encounter", "ENC-FFFFFFFF", {"id": "ENC-FFFFFFFF", "patient_id": "PAT-FFFFFFFF"}
    )
    world.put_entity(
        "clinical_note", "NOTE-existing", {"id": "NOTE-existing", "content": "Existing note"}
    )
    world.record_audit("existing", {"nested": ["preserve"]}, "ok")
    return world


def _state(world):
    return deepcopy(
        {
            "entities": {kind.value: world.list_entities(kind.value) for kind in EntityType},
            "timestamp": world.timestamp,
            "audit": world.audit_log,
        }
    )


def _with_history(task, rows):
    patient = deepcopy(task.patient)
    patient[HISTORY_FIELD] = rows
    return replace(task, patient=patient)


def test_profile_materializes_exact_history_and_json_safe_context(world, task):
    original_task = deepcopy(task)
    original = _state(world)
    context = build_ir002_profile(world, task)

    assert context["profile_version"] == PROFILE_VERSION == "linked-history/v1"
    assert context["task_id"] == "IR-002"
    assert context["window"] == {
        "start": "2025-12-16",
        "end_exclusive": "2026-01-15",
        "semantics": "prior_calendar_days",
    }
    assert json.loads(json.dumps(context)) == context
    assert len(context["prior_encounter_ids"]) == len(set(context["prior_encounter_ids"])) == 4
    assert context["current_encounter_id"] not in context["prior_encounter_ids"]
    assert context["initial_clinical_note_ids"] == ["NOTE-existing"]
    for encounter_id, row in zip(context["prior_encounter_ids"], task.patient[HISTORY_FIELD]):
        encounter = world.get_entity("encounter", encounter_id)
        assert encounter == {
            "id": encounter_id,
            "entity_type": "encounter",
            "patient_id": context["patient_id"],
            "arrival_time": None,
            "visit_date": row["date"],
            "date_precision": "day",
            "chief_complaint": row["chief_complaint"],
            "diagnosis": row["diagnosis"],
            "disposition": row["disposition"],
            "notes": row["notes"],
            "profile_version": PROFILE_VERSION,
        }
    patient = world.get_entity("patient", context["patient_id"])
    current = world.get_entity("encounter", context["current_encounter_id"])
    assert patient.prior_visit_ids == tuple(context["prior_encounter_ids"])
    assert patient.created_at == patient.updated_at == world.timestamp
    assert current.created_at == current.updated_at == world.timestamp
    assert current.arrival_time == datetime(2026, 1, 15, 8, 45, tzinfo=timezone.utc)
    assert context["initial_target_notes"] == json.loads(json.dumps(current.clinical_notes))
    assert all(row["notes"] in str(current.clinical_notes) for row in task.patient[HISTORY_FIELD])
    for kind, entities in original["entities"].items():
        for entity_id, record in entities.items():
            assert world.get_entity(kind, entity_id) == record
    assert world.timestamp == original["timestamp"]
    assert world.audit_log == original["audit"]
    assert task == original_task


def test_profile_links_are_discoverable_through_real_tools(world, task):
    context = build_ir002_profile(world, task)
    server = create_server(world)
    history = server.call_tool("getPatientHistory", {"patient_id": context["patient_id"]})
    assert history["status"] == "ok"
    expected = set(context["prior_encounter_ids"]) | {context["current_encounter_id"]}
    assert set(history["data"]["encounter_ids"]) == expected
    assert list(history["data"]["prior_visit_ids"]) == context["prior_encounter_ids"]
    result = server.call_tool("searchEncounters", {"patient_id": context["patient_id"]})
    assert result["status"] == "ok"
    assert {record["id"] for record in result["data"]} == expected
    bounded = server.call_tool(
        "searchEncounters",
        {
            "patient_id": context["patient_id"],
            "date_from": "2025-12-16T00:00:00Z",
            "date_to": "2026-01-14T23:59:59Z",
        },
    )
    assert bounded["data"] == []  # Day precision is not fabricated into timestamp precision.
    for encounter_id, row in zip(context["prior_encounter_ids"], task.patient[HISTORY_FIELD]):
        detail = server.call_tool("getEncounterDetails", {"encounter_id": encounter_id})
        assert detail["status"] == "ok"
        assert detail["data"]["notes"] == row["notes"]
        assert detail["data"]["visit_date"] == row["date"]
        detail["data"]["notes"] = "rewritten"
        assert world.get_entity("encounter", encounter_id)["notes"] == row["notes"]


def test_context_and_input_copies_cannot_rewrite_profile_entities(world, task):
    context = build_ir002_profile(world, task)
    patient_id = context["patient_id"]
    current_id = context["current_encounter_id"]
    expected = _state(world)
    context["prior_encounter_ids"].clear()
    context["initial_target_notes"][0][1] = "rewritten"
    context["window"]["start"] = "1900-01-01"
    task.patient[HISTORY_FIELD][0]["notes"] = "rewritten input"
    task.patient["medications"].append("Unrelated injected medication")
    assert _state(world) == expected
    assert world.get_entity("patient", patient_id).prior_visit_ids
    assert world.get_entity("encounter", current_id).clinical_notes


def test_equivalent_worlds_produce_identical_profile_and_context(task):
    worlds = [WorldState(), WorldState()]
    contexts = [build_ir002_profile(world, task) for world in worlds]
    assert contexts[0] == contexts[1]
    assert _state(worlds[0]) == _state(worlds[1])


@pytest.mark.parametrize("field", ["chief_complaint", "diagnosis", "disposition", "notes"])
@pytest.mark.parametrize("bad_value", ["", "   ", None, 12])
def test_invalid_fourth_history_record_does_not_partially_mutate_world(
    world, task, field, bad_value
):
    rows = deepcopy(task.patient[HISTORY_FIELD])
    rows[3][field] = bad_value
    before = _state(world)
    with pytest.raises(ValueError):
        build_ir002_profile(world, _with_history(task, rows))
    assert _state(world) == before


@pytest.mark.parametrize(
    "bad_date", ["2026-01-15", "2025-12-15", "2026-02-30", "2026-01-09T00:00:00Z", "2026-1-9", None]
)
def test_out_of_window_or_imprecise_dates_are_rejected_atomically(world, task, bad_date):
    rows = deepcopy(task.patient[HISTORY_FIELD])
    rows[3]["date"] = bad_date
    before = _state(world)
    with pytest.raises(ValueError):
        build_ir002_profile(world, _with_history(task, rows))
    assert _state(world) == before


def test_duplicate_visit_date_is_rejected_atomically(world, task):
    rows = deepcopy(task.patient[HISTORY_FIELD])
    rows[3]["date"] = rows[0]["date"]
    before = _state(world)
    with pytest.raises(ValueError):
        build_ir002_profile(world, _with_history(task, rows))
    assert _state(world) == before


@pytest.mark.parametrize("rows", [None, {}, [], [None] * 4, [{"date": "2026-01-09"}] * 3])
def test_history_requires_exactly_four_complete_records(world, task, rows):
    before = _state(world)
    with pytest.raises(ValueError):
        build_ir002_profile(world, _with_history(task, rows))
    assert _state(world) == before


def test_wrong_task_is_rejected_without_mutation(world, task):
    before = _state(world)
    with pytest.raises(ValueError, match="IR-002"):
        build_ir002_profile(world, replace(task, id="IR-001"))
    assert _state(world) == before


@pytest.mark.parametrize("time", [None, "2026-01-15", "2026-01-15T08:45:00", "invalid", 12])
def test_setting_requires_valid_aware_time(world, task, time):
    before = _state(world)
    with pytest.raises(ValueError):
        build_ir002_profile(world, replace(task, initial_state={"time": time}))
    assert _state(world) == before


def test_reapplication_is_rejected_without_overwriting(world, task):
    build_ir002_profile(world, task)
    before = _state(world)
    with pytest.raises(ValueError, match="collision|already"):
        build_ir002_profile(world, task)
    assert _state(world) == before


@pytest.mark.parametrize("collision", ["patient_id", "current_encounter_id", "prior_encounter_ids"])
def test_preexisting_identifier_collision_is_atomic(world, task, collision):
    ids = build_ir002_profile(WorldState(), task)
    collision_id = ids[collision][3] if collision == "prior_encounter_ids" else ids[collision]
    kind = "patient" if collision == "patient_id" else "encounter"
    world.put_entity(kind, collision_id, {"sentinel": "unrelated existing entity"})
    before = _state(world)
    with pytest.raises(ValueError, match="collision|already"):
        build_ir002_profile(world, task)
    assert _state(world) == before


def test_injector_failure_cannot_leave_partial_profile_in_target_world(world, task, monkeypatch):
    from healthcraft.tasks import history_profile

    def fail_after_patient_write(target, *args):
        target.put_entity("patient", "PAT-partial", {"partial": True})
        raise ValueError("Synthetic injection failure")

    monkeypatch.setattr(history_profile, "inject_task_patient", fail_after_patient_write)
    before = _state(world)
    with pytest.raises(ValueError, match="Synthetic injection failure"):
        build_ir002_profile(world, task)
    assert _state(world) == before


def test_day_window_uses_setting_calendar_date_and_includes_start_day(world, task):
    rows = deepcopy(task.patient[HISTORY_FIELD])
    rows[0]["date"] = "2025-12-16"
    setting = {**task.initial_state, "time": "2026-01-15T01:00:00+03:00"}
    changed_task = replace(_with_history(task, rows), initial_state=setting)
    context = build_ir002_profile(world, changed_task)
    assert context["window"]["end_exclusive"] == "2026-01-15"
    assert context["window"]["start"] == "2025-12-16"
    current = world.get_entity("encounter", context["current_encounter_id"])
    assert current.arrival_time.isoformat() == "2026-01-15T01:00:00+03:00"


def test_raw_strings_are_preserved_without_whitespace_or_disposition_rewriting(world, task):
    rows = deepcopy(task.patient[HISTORY_FIELD])
    for field in ("chief_complaint", "diagnosis", "disposition", "notes"):
        rows[3][field] = "  " + rows[3][field] + "\n"
    context = build_ir002_profile(world, _with_history(task, rows))
    record = world.get_entity("encounter", context["prior_encounter_ids"][3])
    for field in ("chief_complaint", "diagnosis", "disposition", "notes"):
        assert record[field] == rows[3][field]


def test_profile_arrival_anchor_does_not_invent_triage_or_vital_measurement_times(world, task):
    context = build_ir002_profile(world, task)
    current = world.get_entity("encounter", context["current_encounter_id"])
    expected = datetime(2026, 1, 15, 8, 45, tzinfo=timezone.utc)
    assert current.arrival_time == expected
    assert current.triage_time is None
    assert current.vitals
    assert all(vitals.timestamp is None for vitals in current.vitals)
    assert all(vitals.timing_status == "missing" for vitals in current.vitals)


def test_profile_rejects_naive_world_clock_without_mutation(task):
    world = WorldState(start_time=datetime(2026, 1, 15, 8, 45))
    before = _state(world)
    with pytest.raises(ValueError, match="world timestamp"):
        build_ir002_profile(world, task)
    assert _state(world) == before


def test_profile_keeps_original_injected_ids_and_default_injection_unchanged(task):
    from healthcraft.tasks.inject import inject_task_patient

    default_world = WorldState()
    original_ids = inject_task_patient(
        default_world, task.id, deepcopy(task.patient), deepcopy(task.initial_state)
    )
    context = build_ir002_profile(WorldState(), task)
    assert context["patient_id"] == original_ids["patient_id"]
    assert context["current_encounter_id"] == original_ids["encounter_id"]
    assert len(default_world.list_entities("encounter")) == 1
    assert default_world.get_entity("patient", original_ids["patient_id"]).prior_visit_ids == ()
