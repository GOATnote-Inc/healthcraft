"""Authored observation facts survive injection and real tool serialization."""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from healthcraft.mcp.server import create_server
from healthcraft.tasks.inject import inject_task_patient
from healthcraft.tasks.loader import load_task
from healthcraft.world.state import WorldState

ROOT = Path(__file__).resolve().parents[2]
CLOCK = datetime(2026, 1, 15, 7, tzinfo=timezone.utc)


def read_patient(patient, setting=None, task_id="TEMPORAL-FIXTURE"):
    world = WorldState(start_time=CLOCK)
    ids = inject_task_patient(world, task_id, patient, setting)
    server = create_server(world)
    response = server.call_tool("getEncounterDetails", {"encounter_id": ids["encounter_id"]})
    assert response["status"] == "ok"
    return world, ids, response["data"]


@pytest.mark.parametrize("task_number", [15, 18, 24])
def test_named_authored_sets_and_times_are_reachable_without_replacement(task_number):
    path = next((ROOT / "configs/tasks/temporal_reasoning").glob(f"task_{task_number:03d}_*.yaml"))
    task = load_task(path)
    before = deepcopy(task.patient)
    _, _, result = read_patient(task.patient, task.initial_state, task.id)
    rows = {v["source_path"]: v for v in result["vitals"]}
    expected = {
        key: value
        for key, value in task.patient.items()
        if key.startswith("vitals") and isinstance(value, dict)
    }
    assert set(rows) == {f"/patient/{key}" for key in expected}
    for key, source in expected.items():
        row = rows[f"/patient/{key}"]
        assert row["source_data"] == source
        assert row["timestamp"] == source.get("time_of_vitals")
        assert row["timing_status"] == ("explicit" if "time_of_vitals" in source else "missing")
    assert task.patient == before


def test_authored_arrival_remains_distinct_and_searchable_at_its_own_instant():
    patient = {
        "age": 50,
        "sex": "F",
        "arrival_time": "2026-01-15T10:45:00Z",
        "vitals": {"time_of_vitals": "2026-01-15T10:48:00Z", "heart_rate": 92},
    }
    world, ids, result = read_patient(patient, {"time": "2026-01-15T13:15:00Z"})
    assert result["arrival_time"] == patient["arrival_time"]
    assert result["triage_time"] is None
    assert result["vitals"][0]["timestamp"] == patient["vitals"]["time_of_vitals"]
    found = create_server(world).call_tool(
        "searchEncounters",
        {
            "patient_id": ids["patient_id"],
            "date_from": patient["arrival_time"],
            "date_to": patient["arrival_time"],
        },
    )
    assert [r["id"] for r in found["data"]] == [ids["encounter_id"]]


@pytest.mark.parametrize("time", [None, "2026-01-15", "14:35", "2026-01-15T14:35:00", "pending"])
def test_unknown_or_partial_time_is_never_completed_with_the_scenario_clock(time):
    vitals = {
        "heart_rate": 80,
        "gcs": "3T",
        "respiratory_rate": "assisted",
        "oxygen_device": "authored device",
    }
    if time is not None:
        vitals["time_of_vitals"] = time
    patient = {"age": 50, "sex": "F", "arrival_time": time, "vitals_post_treatment": vitals}
    world, _, result = read_patient(patient, {"time": "2026-01-15T13:15:00Z"})
    assert result["arrival_time"] is None
    assert result["triage_time"] is None
    row = result["vitals"][0]
    assert row["timestamp"] is None
    assert row["source_data"] == vitals
    assert row["gcs"] is None and row["respiratory_rate"] is None
    assert row["timing_status"] != "explicit"
    assert result["created_at"] == result["updated_at"] == world.timestamp == CLOCK


def test_coexisting_aliases_and_source_order_do_not_create_times_or_drop_records():
    patient = {
        "age": 50,
        "sex": "F",
        "vitals": {"heart_rate": 90},
        "vitals_current": {"heart_rate": 91},
        "vitals_initial": {"heart_rate": 120},
        "vitals_at_presentation": {"heart_rate": 110},
        "vitals_on_arrival": {"heart_rate": 100},
        "vitals_at_arrival": {"heart_rate": 101},
        "vitals_2_hours_later": {"heart_rate": 80},
    }
    _, _, first = read_patient(patient)
    _, _, second = read_patient(dict(reversed(list(patient.items()))))

    def projected(data):
        return {v["source_path"]: v for v in data["vitals"]}

    assert len(first["vitals"]) == 7
    assert all(v["timestamp"] is None for v in first["vitals"])
    assert projected(first) == projected(second)


def test_series_preserves_source_positions_values_and_high_precision_offsets():
    source = [
        {"time": "2026-01-15T10:00:00.123456789+01:00", "heart_rate": 95},
        {"time": "09:30", "heart_rate": "undetectable"},
    ]
    patient = {"age": 50, "sex": "F", "vitals_series": source}
    _, _, data = read_patient(patient)
    assert len(data["vitals"]) == 2
    for i, row in enumerate(data["vitals"]):
        assert row["source_path"] == f"/patient/vitals_series/{i}"
        assert row["source_data"] == source[i]
    assert data["vitals"][0]["timestamp"] == source[0]["time"]
    assert data["vitals"][1]["timestamp"] is None


def test_conflicting_times_remain_unresolved_instead_of_first_key_wins():
    source = {
        "time": "2026-01-15T10:00:00Z",
        "time_of_vitals": "2026-01-15T11:00:00Z",
        "heart_rate": 80,
    }
    _, _, data = read_patient({"age": 50, "sex": "F", "vitals": source})
    row = data["vitals"][0]
    assert row["timestamp"] is None
    assert row["timing_status"] == "conflicting"
    assert row["source_data"] == source


def test_injection_is_reproducible_without_a_wall_clock_or_setting_fallback():
    patient = {"age": 50, "sex": "F", "vitals": {"heart_rate": 80}}
    first, _, data = read_patient(patient, {"time": "invalid"})
    second, _, again = read_patient(patient, {"time": "invalid"})
    assert first.list_entities("patient") == second.list_entities("patient")
    assert data == again
    assert data["arrival_time"] is data["triage_time"] is None
    assert data["created_at"] == CLOCK


def test_documentation_clock_is_not_measurement_time_or_a_competing_alias():
    documented = "2026-01-15T11:00:00Z"
    measured = "2026-01-15T10:00:00Z"
    for explicit, expected in (({}, None), ({"time_of_vitals": measured}, measured)):
        source = {"heart_rate": 80, "last_documented": documented, **explicit}
        _, _, data = read_patient({"age": 50, "sex": "F", "pre_arrest_vitals": source})
        row = data["vitals"][0]
        assert row["timestamp"] == expected
        assert row["source_time_keys"] == tuple(explicit)
        assert row["source_data"] == source


def test_integer_source_measurement_is_preserved_without_float_conversion_overflow():
    value = 10**500
    _, _, data = read_patient({"age": 50, "sex": "F", "vitals": {"heart_rate": value}})
    assert data["vitals"][0]["heart_rate"] == value
    assert data["vitals"][0]["source_data"]["heart_rate"] == value


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("collection", ["labs", "vitals"])
def test_nonfinite_authored_source_is_rejected_before_world_mutation(nonfinite, collection):
    world = WorldState(start_time=CLOCK)
    patient = {"age": 50, "sex": "F", collection: {"arbitrary_nested": [nonfinite]}}
    before = deepcopy(world._entities)
    with pytest.raises(ValueError, match="non-finite"):
        inject_task_patient(world, "UNSUPPORTED-SOURCE", patient)
    assert world._entities == before


def test_malformed_lab_projection_cannot_leave_a_partial_patient():
    world = WorldState(start_time=CLOCK)
    before = deepcopy(world._entities)
    with pytest.raises(ValueError, match="lab data"):
        inject_task_patient(world, "MALFORMED-LABS", {"age": 50, "sex": "F", "labs": [1]})
    assert world._entities == before


def test_cyclic_authored_source_is_rejected_before_world_mutation():
    world = WorldState(start_time=CLOCK)
    patient = {"age": 50, "sex": "F", "vitals": {}}
    patient["vitals"]["nested"] = patient["vitals"]
    before = deepcopy(world._entities)
    with pytest.raises(ValueError, match="cyclic"):
        inject_task_patient(world, "CYCLIC-SOURCE", patient)
    assert world._entities == before


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_nested_source_key_cannot_escape_validation(nonfinite):
    world = WorldState(start_time=CLOCK)
    patient = {"age": 50, "sex": "F", "labs": {"panel": {nonfinite: "unsupported-key"}}}
    before = deepcopy(world._entities)
    with pytest.raises(ValueError, match="non-finite"):
        inject_task_patient(world, "NONFINITE-KEY", patient)
    assert world._entities == before
