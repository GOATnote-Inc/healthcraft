"""Original reconciliation sources remain reachable, isolated and uninferred."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from healthcraft.entities.base import EntityType
from healthcraft.mcp.server import create_server
from healthcraft.reconciliation import (
    build_world,
    fixture,
    load_scenario,
    snapshot_world,
    source_rows,
)

SCENARIO = (
    Path(__file__).resolve().parents[2] / "configs/evaluation/reconciliation_v1/scenario.json"
)


def original():
    # Test validation independently of the loader under test.
    return json.loads(SCENARIO.read_text())


def resolve_pointer(value, pointer):
    for part in pointer.split("/")[1:]:
        key = part.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def test_original_case_loads_without_an_oracle_and_is_detached():
    data = load_scenario()
    assert data == original()
    assert data["schema_version"] == "healthcraft-reconciliation-scenario/v1"
    assert data["id"] == "synthetic-ed-reconciliation/v1"
    assert len(data["patients"]) == 2
    assert len(data["encounters"]) == 3
    assert set(data) == {"schema_version", "id", "clock", "target", "patients", "encounters"}
    data["encounters"][0]["patient_data"]["active_orders"][0]["status"] = "Changed"
    assert (
        load_scenario()["encounters"][0]["patient_data"]["active_orders"][0]["status"] == "planned"
    )


def test_source_descriptors_resolve_exact_original_rows_and_preserve_unknowns():
    scenario = original()
    rows = source_rows(scenario)
    assert [row["source_id"] for row in rows] == [f"SRC-A{i:02d}" for i in range(1, 8)] + [
        "SRC-B01"
    ]
    encounters = {row["id"]: row for row in scenario["encounters"]}
    for row in rows:
        assert set(row) == {
            "source_id",
            "patient_id",
            "encounter_id",
            "source_collection",
            "source_path",
            "source",
        }
        encounter = encounters[row["encounter_id"]]
        assert row["patient_id"] == encounter["patient_id"]
        assert row["source"] == resolve_pointer(encounter["patient_data"], row["source_path"])
        assert row["source_id"] == row["source"]["source_id"]
    assert rows[0]["source_path"] == "/active_orders/0"
    assert rows[5]["source_path"] == "/imaging_pending/study_01"
    assert rows[2]["source"]["status"] is None
    assert rows[2]["source"]["time"] is None
    assert rows[3]["source"]["reported_status"] == "administered"
    assert rows[4]["source"]["reported_status"] == "not_administered"
    rows[0]["source"]["status"] = "Changed output"
    assert scenario == original()


def test_rfc6901_source_paths_escape_keys():
    scenario = original()
    studies = scenario["encounters"][0]["patient_data"]["imaging_pending"]
    studies["study~/01"] = studies.pop("study_01")
    row = next(row for row in source_rows(scenario) if row["source_id"] == "SRC-A06")
    assert row["source_path"] == "/imaging_pending/study~0~101"
    assert (
        resolve_pointer(scenario["encounters"][0]["patient_data"], row["source_path"])
        == row["source"]
    )


def test_real_tools_retrieve_all_sources_with_correct_patient_scope():
    scenario = original()
    world = build_world(scenario)
    server = create_server(world)
    people = server.call_tool("searchPatients", {"name": "Rowan Example"})
    assert people["status"] == "ok"
    assert {p["id"] for p in people["data"]} == {"PAT-AAAAAAAA", "PAT-BBBBBBBB"}
    history = server.call_tool("getPatientHistory", {"patient_id": "PAT-AAAAAAAA"})
    assert history["data"]["prior_visit_ids"] == ("ENC-CCCCCCCC",)
    assert set(history["data"]["encounter_ids"]) == {"ENC-AAAAAAAA", "ENC-CCCCCCCC"}
    search = server.call_tool("searchEncounters", {"patient_id": "PAT-AAAAAAAA"})
    assert {e["id"] for e in search["data"]} == {"ENC-AAAAAAAA", "ENC-CCCCCCCC"}
    rows = source_rows(scenario)
    observed = []
    for encounter in scenario["encounters"]:
        response = server.call_tool("getEncounterDetails", {"encounter_id": encounter["id"]})
        assert response["status"] == "ok"
        data = response["data"]
        assert data["patient_id"] == encounter["patient_id"]
        assert data["arrival_time"] == encounter["arrival_time"]
        assert data["esi_level"] is None and data["triage_time"] is None
        for key in ("meds_administered", "vitals", "labs", "clinical_notes"):
            assert data[key] == ()
        for group in data["authored_care"]:
            assert group["source_path"] == f"/patient/{group['source_collection']}"
            observed.extend(group["source_data"])
        for study in data["imaging"]:
            observed.append(study["source_data"])
            assert study["status"] == "pending"
            assert study["findings"] is None
            assert study["timestamp"] is None and study["timing_status"] == "missing"
        expected_ids = {r["source_id"] for r in rows if r["encounter_id"] == encounter["id"]}
        assert {r["source_id"] for r in observed if r["source_id"] in expected_ids} == expected_ids
    assert {r["source_id"]: r for r in observed} == {r["source_id"]: r["source"] for r in rows}
    assert not world.list_entities("order") and not world.list_entities("clinical_task")
    assert scenario == original()


def test_fresh_world_snapshots_are_deterministic_detached_and_exclude_audit():
    scenario = original()
    first, second = build_world(scenario), build_world(scenario)
    before = snapshot_world(first)
    assert before == snapshot_world(second)
    assert set(before) == {"timestamp", "entities"}
    assert before["timestamp"] == "2026-09-30T14:30:00+00:00"
    assert set(before["entities"]) == {kind.value for kind in EntityType}
    assert before["entities"]["clinical_note"] == {}
    assert json.loads(json.dumps(before, allow_nan=False)) == before
    server = create_server(first)
    server.call_tool("getPatientHistory", {"patient_id": "PAT-AAAAAAAA"})
    assert snapshot_world(first) == before  # Reads only change the separately captured audit.
    response = server.call_tool("getEncounterDetails", {"encounter_id": "ENC-AAAAAAAA"})
    response["data"]["authored_care"][0]["source_data"][0]["status"] = "Changed response"
    before["entities"]["encounter"]["ENC-AAAAAAAA"]["authored_care"][0]["source_data"][0][
        "status"
    ] = "Changed snapshot"
    scenario["encounters"][0]["patient_data"]["active_orders"][0]["status"] = "Changed input"
    assert snapshot_world(first) == snapshot_world(second)


def test_actual_note_write_stays_on_target_and_preserves_source_records():
    world = build_world(original())
    before = snapshot_world(world)
    server = create_server(world)
    note = (
        '{"schema_version":"healthcraft-reconciliation-note/v1","text":"Synthetic write control"}'
    )
    response = server.call_tool("updateEncounter", {"encounter_id": "ENC-AAAAAAAA", "notes": note})
    assert response["status"] == "ok"
    readback = server.call_tool("getEncounterDetails", {"encounter_id": "ENC-AAAAAAAA"})
    assert readback["data"]["clinical_notes"] == (("Progress Note", note),)
    after = snapshot_world(world)
    assert after["entities"]["patient"] == before["entities"]["patient"]
    for eid in ("ENC-CCCCCCCC", "ENC-BBBBBBBB"):
        assert after["entities"]["encounter"][eid] == before["entities"]["encounter"][eid]
    assert (
        after["entities"]["encounter"]["ENC-AAAAAAAA"]["authored_care"]
        == before["entities"]["encounter"]["ENC-AAAAAAAA"]["authored_care"]
    )
    notes = list(after["entities"]["clinical_note"].values())
    assert len(notes) == 1
    assert notes[0]["content"] == note
    assert notes[0]["patient_id"] == "PAT-AAAAAAAA" and notes[0]["encounter_id"] == "ENC-AAAAAAAA"
    assert notes[0]["created_at"] == before["timestamp"]


def change(scenario, kind):
    if kind == "wrong_schema":
        scenario["schema_version"] = "wrong"
    elif kind == "wrong_case":
        scenario["id"] = "other"
    elif kind == "clock_naive":
        scenario["clock"] = "2026-09-30T14:30:00"
    elif kind == "clock_date":
        scenario["clock"] = "2026-09-30"
    elif kind == "target_missing":
        scenario["target"]["encounter_id"] = "ENC-DDDDDDDD"
    elif kind == "target_wrong_patient":
        scenario["target"]["patient_id"] = "PAT-BBBBBBBB"
    elif kind == "duplicate_patient":
        scenario["patients"][1]["id"] = "PAT-AAAAAAAA"
    elif kind == "duplicate_mrn":
        scenario["patients"][1]["mrn"] = "SYNTHETIC-A"
    elif kind == "bad_patient_id":
        scenario["patients"][0]["id"] = "PAT-aaaaaaaa"
    elif kind == "duplicate_encounter":
        scenario["encounters"][2]["id"] = "ENC-AAAAAAAA"
    elif kind == "missing_patient":
        scenario["encounters"][2]["patient_id"] = "PAT-CCCCCCCC"
    elif kind == "bad_arrival":
        scenario["encounters"][1]["arrival_time"] = "2026-09-30"
    elif kind == "bad_dob":
        scenario["patients"][0]["date_of_birth"] = "not-a-date"
    elif kind == "wrong_prior_link":
        scenario["patients"][0]["prior_visit_ids"] = ["ENC-BBBBBBBB"]
    elif kind == "duplicate_prior_link":
        scenario["patients"][0]["prior_visit_ids"] *= 2
    elif kind == "target_prior_link":
        scenario["patients"][0]["prior_visit_ids"] = ["ENC-AAAAAAAA"]
    elif kind == "unknown_collection":
        scenario["encounters"][2]["patient_data"]["unknown"] = []
    elif kind == "duplicate_source":
        scenario["encounters"][2]["patient_data"]["treatments_given"][0]["source_id"] = "SRC-A01"
    elif kind == "missing_source_id":
        del scenario["encounters"][2]["patient_data"]["treatments_given"][0]["source_id"]
    elif kind == "malformed_last_row":
        scenario["encounters"][2]["patient_data"]["treatments_given"][0] = []
    elif kind == "naive_source_time":
        scenario["encounters"][2]["patient_data"]["treatments_given"][0]["event_time"] = (
            "2026-09-30T14:05:00"
        )
    elif kind == "answer_label":
        scenario["encounters"][2]["patient_data"]["treatments_given"][0]["expected"] = True
    elif kind == "source_nonfinite":
        scenario["encounters"][2]["patient_data"]["treatments_given"][0]["item"] = float("nan")
    elif kind == "extra_top_field":
        scenario["answer"] = "No hidden oracle in observations"
    elif kind == "tuple_array":
        scenario["patients"] = tuple(scenario["patients"])
    elif kind == "nonstring_key":
        scenario["target"][1] = "value"
    else:
        raise AssertionError(kind)


@pytest.mark.parametrize(
    "kind",
    [
        "wrong_schema",
        "wrong_case",
        "clock_naive",
        "clock_date",
        "target_missing",
        "target_wrong_patient",
        "duplicate_patient",
        "duplicate_mrn",
        "bad_patient_id",
        "duplicate_encounter",
        "missing_patient",
        "bad_arrival",
        "bad_dob",
        "wrong_prior_link",
        "duplicate_prior_link",
        "target_prior_link",
        "unknown_collection",
        "duplicate_source",
        "missing_source_id",
        "malformed_last_row",
        "naive_source_time",
        "answer_label",
        "source_nonfinite",
        "extra_top_field",
        "tuple_array",
        "nonstring_key",
    ],
)
def test_invalid_scenario_fails_before_world_construction_and_preserves_input(kind, monkeypatch):
    scenario = original()
    change(scenario, kind)
    before = deepcopy(scenario)
    created = []
    monkeypatch.setattr(fixture, "WorldState", lambda *a, **kw: created.append((a, kw)))
    with pytest.raises(ValueError):
        build_world(scenario)
    assert not created
    # NaN is intentionally not equality-comparable, so compare strict representations here.
    assert repr(scenario) == repr(before)
    with pytest.raises(ValueError):
        source_rows(scenario)


@pytest.mark.parametrize(
    "bad_json",
    [
        '{"schema_version":"x","schema_version":"y"}',
        '{"value":NaN}',
        '{"value":Infinity}',
        '{"value":-Infinity}',
        "[]",
        '{"nested":{"a":1,"a":2}}',
    ],
)
def test_loader_rejects_nonfinite_duplicate_and_nonobject_json(tmp_path, bad_json):
    path = tmp_path / "case.json"
    path.write_text(bad_json)
    with pytest.raises(ValueError):
        load_scenario(path)


def test_loader_validates_explicit_path_and_does_not_fall_back(tmp_path):
    path = tmp_path / "invalid.json"
    scenario = original()
    change(scenario, "duplicate_source")
    path.write_text(json.dumps(scenario))
    with pytest.raises(ValueError):
        load_scenario(path)
    with pytest.raises(FileNotFoundError):
        load_scenario(tmp_path / "missing.json")


def test_source_timestamp_spelling_is_preserved_and_not_used_as_clock():
    scenario = original()
    precise = "2026-09-30T11:05:00.0000001-03:00"
    scenario["encounters"][0]["patient_data"]["treatments_given"][0]["event_time"] = precise
    world = build_world(scenario)
    data = create_server(world).call_tool("getEncounterDetails", {"encounter_id": "ENC-AAAAAAAA"})[
        "data"
    ]
    treatment = next(
        group for group in data["authored_care"] if group["source_collection"] == "treatments_given"
    )
    assert treatment["source_data"][0]["event_time"] == precise
    assert snapshot_world(world)["timestamp"] == "2026-09-30T14:30:00+00:00"


def test_loader_rejects_source_shape_native_projection_cannot_preserve(tmp_path, monkeypatch):
    scenario = original()
    imaging = scenario["encounters"][0]["patient_data"]["imaging_pending"]
    imaging["study_if_ordered"] = imaging.pop("study_01")
    path = tmp_path / "conditional.json"
    path.write_text(json.dumps(scenario))
    with pytest.raises(ValueError, match="conditional"):
        load_scenario(path)
    with pytest.raises(ValueError, match="conditional"):
        source_rows(scenario)
    constructed = []
    monkeypatch.setattr(fixture, "WorldState", lambda *a, **kw: constructed.append(True))
    with pytest.raises(ValueError, match="conditional"):
        build_world(scenario)
    assert constructed == []


def test_world_clock_precision_is_never_silently_truncated():
    scenario = original()
    scenario["clock"] = "2026-09-30T14:30:00.0000001Z"
    with pytest.raises(ValueError, match="precision"):
        build_world(scenario)
    scenario["clock"] = "2026-09-30T11:30:00.123456-03:00"
    assert snapshot_world(build_world(scenario))["timestamp"] == "2026-09-30T14:30:00.123456+00:00"
