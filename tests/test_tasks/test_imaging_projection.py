"""Imaging source facts survive without manufactured studies or future targets."""

import json
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

import pytest

from healthcraft.tasks.imaging_projection import project_imaging
from healthcraft.tasks.loader import load_task

ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=None)
def task(task_id):
    for path in (ROOT / "configs/tasks").rglob("*.yaml"):
        candidate = load_task(path)
        if candidate.id == task_id:
            return candidate
    raise AssertionError(f"Task not found: {task_id}")


def project(source, task_id="SYNTHETIC-IMAGING"):
    return project_imaging(source, task_id=task_id)


def test_explicit_fields_are_distinct_exact_strings_without_key_derived_facts():
    raw = {
        "result": " authored result\n",
        "findings": "  finding  ",
        "impression": "impression\n",
        "modality": "MR",
        "body_part": "heart",
        "status": "preliminary",
        "time": "2026-01-15T10:00:00.123456789+01:00",
    }
    projection = project({"imaging": {"misleading_xray_label": raw}})
    (record,) = projection.records
    for key in ("result", "findings", "impression", "modality", "body_part", "status"):
        assert getattr(record, key) == raw[key]
    assert record.timestamp == raw["time"]
    assert record.timing_status == "explicit" and record.source_time_keys == ("time",)
    assert record.report_text is None
    assert record.source_data == raw
    assert record.source_collection == "imaging"
    assert record.source_label == "misleading_xray_label"
    assert record.source_path == "/patient/imaging/misleading_xray_label"
    assert record.source_role == "authored_context"
    assert projection.notices == ()


def test_missing_impression_modality_bodypart_and_time_are_not_fabricated():
    raw = {"findings": "  Literal finding " + "x" * 300 + "\n"}
    (record,) = project({"imaging": {"ct_head": raw}}).records
    assert record.findings == raw["findings"]
    assert record.impression is record.modality is record.body_part is record.timestamp is None
    assert record.result is record.report_text is record.status is None
    assert record.timing_status == "missing"


@pytest.mark.parametrize("value", ["NOT YET OBTAINED", "ordered, pending", "", " literal result\n"])
def test_scalar_strings_are_report_text_only_and_preserved(value):
    (record,) = project({"imaging": {"ct_head": value}}).records
    assert record.report_text == record.source_data == value
    assert record.findings is record.result is record.impression is record.status is None
    assert record.modality is record.body_part is record.timestamp is None


@pytest.mark.parametrize("value", [True, False])
def test_boolean_source_assertion_is_not_an_imaging_result(value):
    (record,) = project({"imaging": {"skeletal_survey_recommended": value}}).records
    assert record.source_role == "source_assertion"
    assert record.source_data is value
    assert record.result is record.report_text is record.status is None


def test_collection_reader_metadata_is_not_a_study_result():
    (record,) = project({"imaging": {"read_by": "Named reader"}}).records
    assert record.source_role == "collection_metadata"
    assert record.source_data == record.report_text == "Named reader"
    assert record.result is record.findings is record.modality is None


def test_all_explicit_containers_and_standalones_without_patient_echo_recursion():
    patient = {
        "imaging": {"a": "one"},
        "imaging_results": {"b": "two"},
        "imaging_available": {"c": "three"},
        "imaging_pending": {"d": "four"},
        "bedside_echo": {"rv": "source"},
        "fast_exam": {"rup": "source"},
        "patient_echo": {"imaging": {"forbidden": "other patient"}},
        "prior_visits": [{"imaging": {"forbidden": "historical"}}],
    }
    result = project(patient)
    assert len(result.records) == 6
    assert {r.source_collection for r in result.records} == {
        "imaging",
        "imaging_results",
        "imaging_available",
        "imaging_pending",
        "bedside_echo",
        "fast_exam",
    }
    assert "other patient" not in json.dumps(asdict(result))
    assert "historical" not in json.dumps(asdict(result))


def test_arbitrary_nested_findings_remain_raw_without_stringification_or_slicing():
    raw = {
        "findings": {"left": ["literal", None]},
        "modality": False,
        "impression": None,
        "result": 12,
        "unknown": {"qualifier": "preserve"},
    }
    original = deepcopy(raw)
    result = project({"imaging": {"a/b~c": raw}})
    (record,) = result.records
    raw["findings"]["left"].append("caller mutation")
    assert record.source_data == original
    assert record.source_path == "/patient/imaging/a~1b~0c"
    assert record.findings is record.modality is record.impression is record.result is None


@pytest.mark.parametrize("field", ["issued", "started", "report_issued", "prehospital_ecg_time"])
def test_distinct_event_roles_do_not_supply_generic_timestamp(field):
    raw = {field: "2026-01-15T10:00:00Z"}
    (record,) = project({"imaging": {"study": raw}}).records
    assert record.timestamp is None and record.timing_status == "missing"
    assert record.source_data == raw


@pytest.mark.parametrize("stamp", [None, "10:00", "2026-01-15", "2026-01-15T10:00:00", "pending"])
def test_partial_unknown_time_is_not_completed(stamp):
    (record,) = project({"imaging": {"study": {"time": stamp}}}).records
    assert record.timestamp is None and record.timing_status != "explicit"
    assert record.source_data["time"] == stamp


def test_conflicting_generic_time_aliases_are_not_silently_resolved():
    raw = {"time": "2026-01-15T10:00:00Z", "time_of_study": "2026-01-15T11:00:00Z"}
    (record,) = project({"imaging": {"study": raw}}).records
    assert record.timestamp is None and record.timing_status == "conflicting"
    assert record.source_data == raw


@pytest.mark.parametrize("task_id,count", [("MW-006", 2), ("MW-009", 4), ("SCJ-017", 2)])
def test_reviewed_future_targets_are_absent_from_entire_public_projection(task_id, count):
    source = task(task_id).patient
    before = deepcopy(source)
    projection = project(source, task_id=task_id)
    encoded = json.dumps(asdict(projection))
    assert sum(n["omitted_field_count"] for n in projection.notices) == count
    for notice in projection.notices:
        assert notice == {
            "source_collection": "imaging",
            "source_path": "/patient/imaging",
            "omitted_field_count": count,
            "notice": "Authored conditional guidance withheld from observations",
        }
    for label, entry in source["imaging"].items():
        if label.endswith("_if_ordered"):
            assert json.dumps(entry) not in encoded
            assert not any(r.source_label == label for r in projection.records)
        if isinstance(entry, dict):
            for key, value in entry.items():
                if key.startswith("expected_"):
                    assert key not in encoded and json.dumps(value) not in encoded
    assert source == before


@pytest.mark.parametrize(
    "source",
    [
        {"imaging": {"study": {"expected_finding": "hidden target"}}},
        {"imaging_results": {"study_if_ordered": "hidden target"}},
        {"bedside_echo": {"nested": [{"expected_new_fact": "hidden target"}]}},
        {"imaging": {"study": {"nested": {"Expected_Finding": "hidden target"}}}},
    ],
)
def test_unreviewed_conditional_source_fails_instead_of_leaking(source):
    with pytest.raises(ValueError, match="Unreviewed") as error:
        project(source)
    assert "hidden target" not in str(error.value)


def test_known_path_for_wrong_task_is_not_silently_treated_as_reviewed():
    with pytest.raises(ValueError, match="Unreviewed"):
        project(task("MW-006").patient, task_id="DIFFERENT-TASK")


def test_actual_cr006_result_and_tr025_time_survive_without_inference():
    cr = project(task("CR-006").patient, task_id="CR-006")
    cta = next(r for r in cr.records if r.source_label == "cta_chest")
    assert cta.result == task("CR-006").patient["imaging"]["cta_chest"]["result"]
    assert cta.findings is cta.impression is cta.modality is None
    tr = project(task("TR-025").patient, task_id="TR-025")
    head = next(r for r in tr.records if r.source_label == "ct_head")
    assert head.timestamp == "2026-01-15T06:45:00Z"
    assert head.result and head.findings is None


def test_whole_conditional_omission_still_produces_notice_without_fake_record():
    result = project({"imaging": {"ct_head_if_ordered": "private target"}}, task_id="SCJ-017")
    assert result.records == ()
    assert result.notices[0]["omitted_field_count"] == 1
    assert "private target" not in json.dumps(asdict(result))


@pytest.mark.parametrize("value", [None, 0, 1.5, ["literal", {"qualifier": "source"}]])
def test_nonstring_source_entries_remain_raw_without_fabricated_text(value):
    (record,) = project({"imaging": {"study": value}}).records
    assert record.source_data == value
    assert record.report_text is record.result is record.findings is None


@pytest.mark.parametrize(
    "collection", ["imaging", "imaging_results", "imaging_pending", "imaging_available"]
)
def test_null_collection_has_no_records_but_malformed_collection_fails(collection):
    assert project({collection: None}).records == ()
    with pytest.raises(ValueError, match="mapping with string keys"):
        project({collection: ["not a named collection"]})


def test_explicit_null_standalone_is_retained_as_unknown_source():
    (record,) = project({"fast_exam": None}).records
    assert record.source_path == "/patient/fast_exam"
    assert record.source_data is record.report_text is None


@pytest.mark.parametrize(
    "source",
    [
        {"imaging": {1: "bad label"}},
        {"imaging": {"study": {1: "bad nested key"}}},
        {"imaging": {"study": {"nested": float("nan")}}},
    ],
)
def test_invalid_selected_source_is_rejected_without_mutation(source):
    with pytest.raises(ValueError):
        project(source)


@pytest.mark.parametrize("task_id", [None, 4, "", "  "])
def test_task_identity_is_required_for_visibility_review(task_id):
    with pytest.raises(ValueError, match="task_id"):
        project({}, task_id=task_id)
