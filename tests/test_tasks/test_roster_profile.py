"""Authored roster observations must be reachable without answer-label leakage."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from healthcraft.mcp.server import create_server
from healthcraft.tasks.environment import prepare_task_environment
from healthcraft.tasks.loader import load_tasks
from healthcraft.tasks.roster_profile import PROFILE_VERSION, build_roster_profile
from healthcraft.world.state import WorldState

ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="module")
def tasks():
    return {task.id: task for task in load_tasks(ROOT / "configs/tasks")}


@pytest.mark.parametrize(
    "task_id,count",
    [("CC-022", 4), ("CC-027", 3), ("CC-028", 7), ("IR-018", 7), ("IR-023", 7), ("IR-025", 5)],
)
def test_every_roster_member_is_retrievable_with_its_own_patient(tasks, task_id, count):
    world = WorldState()
    before = deepcopy(tasks[task_id])
    context = build_roster_profile(world, tasks[task_id])
    assert context["profile_version"] == PROFILE_VERSION
    assert len(context["roster"]) == count
    assert len(world.list_entities("patient")) == len(world.list_entities("encounter")) == count
    server = create_server(world)
    for row in context["roster"]:
        patient = server.call_tool("getPatientHistory", {"patient_id": row["patient_id"]})
        encounter = server.call_tool("getEncounterDetails", {"encounter_id": row["encounter_id"]})
        search = server.call_tool("searchEncounters", {"patient_id": row["patient_id"]})
        assert patient["status"] == encounter["status"] == search["status"] == "ok"
        assert encounter["data"]["patient_id"] == patient["data"]["id"]
        assert patient["data"]["encounter_ids"] == [row["encounter_id"]]
        assert [r["id"] for r in search["data"]] == [row["encounter_id"]]
        assert (
            encounter["data"]["authored_observations"] == patient["data"]["authored_observations"]
        )
        assert encounter["data"]["arrival_time"] is None
        assert "dob" not in patient["data"] and "allergies" not in patient["data"]
    assert tasks[task_id] == before


def test_ems_source_assessments_are_preserved_but_expected_answers_are_private(tasks):
    task = tasks["IR-025"]
    world = WorldState()
    context = build_roster_profile(world, task)
    server = create_server(world)
    for row, raw in zip(context["roster"], task.source_data["incoming_patients"]):
        result = server.call_tool("getEncounterDetails", {"encounter_id": row["encounter_id"]})
        observations = result["data"]["authored_observations"]
        assert observations == {
            key: raw[key] for key in ("ems_id", "age", "sex", "ems_report", "ems_triage")
        }
        assert "actual_priority" not in json.dumps(result)
        assert raw["note"] not in json.dumps(result, ensure_ascii=False)
    assert len(context["withheld"]) == 10
    assert all("value" not in item for item in context["withheld"])


def test_profile_context_exposes_ids_and_labels_without_copying_answers_or_case_facts(tasks):
    task = tasks["IR-025"]
    prepared, context = prepare_task_environment(WorldState(), task, profile=PROFILE_VERSION)
    for row, raw in zip(context["roster"], task.source_data["incoming_patients"]):
        assert row["patient_id"] in prepared.description
        assert row["encounter_id"] in prepared.description
        assert raw["ems_id"] in prepared.description
        assert raw["ems_report"] not in prepared.description
        assert raw["note"] not in prepared.description
    assert "not clinically validated" in prepared.description


@pytest.mark.parametrize(
    "alteration",
    ["extra_field", "duplicate", "missing_identity", "wrong_count", "wrong_task", "nested_value"],
)
def test_invalid_sources_fail_before_any_world_change(tasks, alteration):
    task = deepcopy(tasks["CC-022"])
    rows = task.source_data["patients_requiring_action"]
    if alteration == "extra_field":
        rows[-1]["unreviewed_answer"] = "never expose this"
    elif alteration == "duplicate":
        rows[-1]["bed"] = rows[0]["bed"]
    elif alteration == "missing_identity":
        del rows[-1]["bed"]
    elif alteration == "wrong_count":
        rows.pop()
    elif alteration == "wrong_task":
        task.source_data["id"] = "IR-025"
    else:
        rows[-1]["summary"] = {"answer": "unexpected nesting"}
    world = WorldState()
    with pytest.raises(ValueError):
        build_roster_profile(world, task)
    assert world.list_entities("patient") == world.list_entities("encounter") == {}
    assert world.audit_log == []


def test_existing_people_are_not_merged_by_bed_and_collisions_never_overwrite(tasks):
    world = WorldState()
    world.put_entity("patient", "PAT-UNRELATED", {"id": "PAT-UNRELATED", "bed": 3})
    context = build_roster_profile(world, tasks["CC-022"])
    assert len(world.list_entities("patient")) == 5
    snapshot = deepcopy(world.list_entities("encounter"))
    with pytest.raises(ValueError, match="collision"):
        build_roster_profile(world, tasks["CC-022"])
    assert world.list_entities("encounter") == snapshot
    assert "PAT-UNRELATED" not in {r["patient_id"] for r in context["roster"]}


def test_deterministic_identity_and_source_change_are_recorded(tasks):
    task = deepcopy(tasks["CC-022"])
    a = build_roster_profile(WorldState(), task)
    b = build_roster_profile(WorldState(), task)
    assert a == b
    task.source_data["patients_requiring_action"][0]["summary"] += " New supplied observation."
    c = build_roster_profile(WorldState(), task)
    assert a["source_sha256"] != c["source_sha256"]
    assert a["contract_sha256"] == c["contract_sha256"]
    assert a["roster"] == c["roster"]


def test_tool_mutation_targets_only_the_requested_roster_member(tasks):
    world = WorldState()
    context = build_roster_profile(world, tasks["CC-022"])
    first, second = context["roster"][:2]
    server = create_server(world)
    changed = server.call_tool(
        "updateEncounter",
        {
            "encounter_id": first["encounter_id"],
            "notes": "Source reviewed; allocation decision pending.",
        },
    )
    assert changed["status"] == "ok"
    first_result = server.call_tool("getEncounterDetails", {"encounter_id": first["encounter_id"]})
    second_result = server.call_tool(
        "getEncounterDetails", {"encounter_id": second["encounter_id"]}
    )
    assert "allocation decision pending" in json.dumps(first_result, default=str)
    assert "allocation decision pending" not in json.dumps(second_result, default=str)


def test_unsupported_task_or_missing_authored_source_cannot_use_profile(tasks):
    for task in (tasks["IR-002"], replace(tasks["CC-022"], source_data={})):
        with pytest.raises(ValueError):
            build_roster_profile(WorldState(), task)
