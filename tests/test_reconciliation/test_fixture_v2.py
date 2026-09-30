"""Varied original casebook sources stay exact, bounded and discoverable."""

from copy import deepcopy

import pytest

from healthcraft.mcp.server import create_server
from healthcraft.reconciliation.execution import _source_records
from healthcraft.reconciliation.fixture import snapshot_world


def scenario(*, patient_count=2, encounter_count=3, source_count=5):
    patients = [
        {
            "id": f"PAT-{i + 1:08X}",
            "mrn": f"SYNTHETIC-V2-{i + 1}",
            "first_name": "Casebook",
            "last_name": "Example",
            "date_of_birth": None,
            "sex": "",
            "prior_visit_ids": [],
        }
        for i in range(patient_count)
    ]
    encounters = [
        {
            "id": f"ENC-{i + 1:08X}",
            "patient_id": patients[i % patient_count]["id"],
            "chief_complaint": "Original source reconciliation exercise",
            "arrival_time": None,
            "patient_data": {"active_orders": []},
        }
        for i in range(encounter_count)
    ]
    for i in range(source_count):
        encounters[i % encounter_count]["patient_data"]["active_orders"].append(
            {
                "source_id": f"SRC-{chr(65 + i // 99)}{i % 99 + 1:02}",
                "order_id": f"ORDER-{i + 1}",
                "item": f"Literal synthetic source {i + 1}",
                "status": None if i % 2 else "planned",
                "time": None,
            }
        )
    for patient in patients:
        patient["prior_visit_ids"] = [
            e["id"] for e in encounters[1:] if e["patient_id"] == patient["id"]
        ]
    return {
        "schema_version": "healthcraft-reconciliation-scenario/v2",
        "id": "synthetic-ed-reconciliation/v2/REC2-001",
        "clock": "2026-09-30T11:30:00.123456-03:00",
        "target": {"patient_id": patients[0]["id"], "encounter_id": encounters[0]["id"]},
        "patients": patients,
        "encounters": encounters,
    }


def api():
    from healthcraft.reconciliation import fixture_v2

    return fixture_v2


@pytest.mark.parametrize("counts", [(1, 1, 1), (2, 3, 5), (3, 5, 11), (8, 16, 128)])
def test_varied_bounds_build_real_detached_world_with_exact_reachable_sources(counts):
    source = scenario(patient_count=counts[0], encounter_count=counts[1], source_count=counts[2])
    original = deepcopy(source)
    validated = api().validate_scenario(source)
    world = api().build_world(source)
    rows = api().source_rows(source)
    assert validated == original and validated is not source
    assert len(rows) == counts[2]
    assert world.timestamp.isoformat() == "2026-09-30T14:30:00.123456+00:00"
    server = create_server(world)
    people = server.call_tool("searchPatients", {"name": "Casebook Example"})["data"]
    assert len(people) == counts[0]
    observed = []
    for patient in people:
        found = server.call_tool("searchEncounters", {"patient_id": patient["id"]})["data"]
        assert len(found) < 10
        history = server.call_tool("getPatientHistory", {"patient_id": patient["id"]})["data"]
        assert set(history["encounter_ids"]) == {e["id"] for e in found}
        for encounter in found:
            detail = server.call_tool("getEncounterDetails", {"encounter_id": encounter["id"]})
            data = detail["data"]
            assert data["patient_id"] == patient["id"]
            assert data["arrival_time"] is None and data["triage_time"] is None
            assert data["esi_level"] is None
            for key in ("clinical_notes", "vitals", "labs", "meds_administered"):
                assert data[key] == ()
            observed.extend(_source_records(data))
    assert sorted(observed, key=lambda r: r["source_id"]) == sorted(
        rows, key=lambda r: r["source_id"]
    )
    assert source == original
    before = snapshot_world(world)
    rows[0]["source"]["item"] = "Changed descriptor"
    source["encounters"][0]["patient_data"]["active_orders"][0]["item"] = "Changed source"
    validated["patients"][0]["first_name"] = "Changed copy"
    assert snapshot_world(world) == before
    assert before == snapshot_world(api().build_world(original))


def test_literal_escaped_imaging_path_and_fractional_source_time_survive():
    data = scenario(patient_count=1, encounter_count=1, source_count=1)
    data["encounters"][0]["patient_data"] = {
        "imaging_pending": {
            "study~/01": {
                "source_id": "SRC-Z99",
                "study_id": "STUDY-1",
                "modality": "CT",
                "body_part": "literal synthetic region",
                "status": "pending",
                "time": "2026-09-30T14:00:00.123456789Z",
            }
        }
    }
    rows = api().source_rows(data)
    assert rows[0]["source_path"] == "/imaging_pending/study~0~101"
    actual = create_server(api().build_world(data)).call_tool(
        "getEncounterDetails", {"encounter_id": data["target"]["encounter_id"]}
    )["data"]
    assert _source_records(actual) == rows
    assert rows[0]["source"]["time"].endswith(".123456789Z")


def mutate(data, kind):
    if kind == "empty_patients":
        data["patients"] = []
    elif kind == "too_many_patients":
        data["patients"] *= 5
    elif kind == "empty_encounters":
        data["encounters"] = []
    elif kind == "too_many_encounters":
        data["encounters"] *= 6
    elif kind == "empty_sources":
        for e in data["encounters"]:
            e["patient_data"] = {}
    elif kind == "too_many_sources":
        data["encounters"][0]["patient_data"]["active_orders"] *= 100
    elif kind == "duplicate_patient":
        data["patients"][1]["id"] = data["patients"][0]["id"]
    elif kind == "duplicate_mrn":
        data["patients"][1]["mrn"] = data["patients"][0]["mrn"]
    elif kind == "different_name":
        data["patients"][1]["last_name"] = "Outside cohort"
    elif kind == "supplied_dob":
        data["patients"][0]["date_of_birth"] = "1990-01-01"
    elif kind == "duplicate_encounter":
        data["encounters"][1]["id"] = data["encounters"][0]["id"]
    elif kind == "unlinked_patient":
        data["encounters"][0]["patient_id"] = "PAT-FFFFFFFF"
    elif kind == "wrong_target":
        data["target"]["patient_id"] = data["patients"][1]["id"]
    elif kind == "wrong_prior":
        data["patients"][0]["prior_visit_ids"] = [data["encounters"][1]["id"]]
    elif kind == "current_prior":
        data["patients"][0]["prior_visit_ids"] = [data["target"]["encounter_id"]]
    elif kind == "duplicate_prior":
        data["patients"][0]["prior_visit_ids"] *= 2
    elif kind == "no_target_sources":
        data["encounters"][0]["patient_data"] = {}
    elif kind == "answer_label":
        data["encounters"][0]["patient_data"]["active_orders"][0]["expected"] = True
    elif kind == "unknown_collection":
        data["encounters"][0]["patient_data"]["vitals"] = []
    elif kind == "bad_last_record":
        data["encounters"][-1]["patient_data"]["active_orders"][-1] = []
    elif kind == "duplicate_source":
        data["encounters"][-1]["patient_data"]["active_orders"][-1]["source_id"] = "SRC-A01"
    elif kind == "nonfinite":
        data["encounters"][0]["patient_data"]["active_orders"][0]["item"] = float("inf")
    elif kind == "tuple":
        data["patients"] = tuple(data["patients"])
    elif kind == "nonstring_key":
        data["target"][1] = None
    elif kind == "naive_clock":
        data["clock"] = "2026-09-30T14:30:00"
    elif kind == "clock_precision":
        data["clock"] = "2026-09-30T14:30:00.0000001Z"
    elif kind == "date_arrival":
        data["encounters"][0]["arrival_time"] = "2026-09-30"
    elif kind == "naive_source_time":
        data["encounters"][0]["patient_data"]["active_orders"][0]["time"] = "2026-09-30T14:30:00"
    elif kind == "wrong_version":
        data["schema_version"] = "healthcraft-reconciliation-scenario/v1"
    elif kind == "wrong_id":
        data["id"] = "synthetic-ed-reconciliation/v2/REC2-001/extra"
    else:
        raise AssertionError(kind)


@pytest.mark.parametrize(
    "kind",
    [
        "empty_patients",
        "too_many_patients",
        "empty_encounters",
        "too_many_encounters",
        "empty_sources",
        "too_many_sources",
        "duplicate_patient",
        "duplicate_mrn",
        "different_name",
        "supplied_dob",
        "duplicate_encounter",
        "unlinked_patient",
        "wrong_target",
        "wrong_prior",
        "current_prior",
        "duplicate_prior",
        "no_target_sources",
        "answer_label",
        "unknown_collection",
        "bad_last_record",
        "duplicate_source",
        "nonfinite",
        "tuple",
        "nonstring_key",
        "naive_clock",
        "clock_precision",
        "date_arrival",
        "naive_source_time",
        "wrong_version",
        "wrong_id",
    ],
)
def test_rejects_invalid_source_before_any_world_is_constructed(kind, monkeypatch):
    data = scenario()
    mutate(data, kind)
    module = api()
    made = []
    monkeypatch.setattr(module, "WorldState", lambda **kw: made.append(kw))
    with pytest.raises(ValueError):
        module.build_world(data)
    assert made == []


def test_ten_encounters_for_one_patient_rejected_before_truncated_search():
    with pytest.raises(ValueError, match="nine|9"):
        api().build_world(scenario(patient_count=1, encounter_count=10, source_count=10))


def test_unique_129th_source_is_rejected_by_count_not_collision():
    with pytest.raises(ValueError, match="128"):
        api().validate_scenario(scenario(source_count=129))
