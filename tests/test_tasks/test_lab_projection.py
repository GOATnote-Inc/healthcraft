"""Authored laboratory evidence survives projection without invented measurements."""

from copy import deepcopy
from pathlib import Path

import pytest

from healthcraft.tasks.lab_projection import project_labs
from healthcraft.tasks.loader import load_task

ROOT = Path(__file__).resolve().parents[2]


def test_real_tr024_structured_result_preserves_fields_and_authored_time():
    task = load_task(
        ROOT / "configs/tasks/temporal_reasoning/task_024_serial_troponin_protocol.yaml"
    )
    source = task.patient["labs_available"]
    results = project_labs(source, "/patient/labs_available")
    result = results[0]
    assert result.test_name == "Hs Ctni T0"
    assert type(result.value) is int and result.value == 18
    assert result.unit == "ng/L"
    assert result.reference_range == "URL 99th percentile: 14 ng/L"
    assert result.timestamp == source["hs_ctni_t0"]["time"]
    assert result.timing_status == "explicit"
    assert result.source_time_keys == ("time",)
    assert result.source_path == "/patient/labs_available/hs_ctni_t0"
    assert result.source_data == source["hs_ctni_t0"]
    assert result.abnormal is None  # The word "below" is not an authored boolean.
    assert len(results) == len(source)


@pytest.mark.parametrize(
    "value", ["<1.0 mg/dL (normal)", "pending — NOT YET DRAWN", 0, 18, 0.12, None]
)
def test_raw_scalar_type_is_preserved_without_inferred_unit_time_or_severity(value):
    (result,) = project_labs({"test": value}, "/patient/labs")
    assert type(result.value) is type(value)
    assert result.value == value
    assert result.source_data == value
    assert result.unit is result.reference_range is result.timestamp is result.abnormal is None
    assert result.timing_status == "missing"
    assert result.source_time_keys == ()


@pytest.mark.parametrize("value", [True, False, ["pending"], {"nested": {"value": 18}}])
def test_unstructured_panels_and_wrong_scalar_types_stay_raw_not_dictionary_repr(value):
    (result,) = project_labs({"test": value}, "/patient/labs")
    assert result.value is None
    assert result.source_data == value
    assert result.abnormal is None


def test_real_panels_keep_grouping_and_do_not_assign_subvalues_to_scalar_value():
    task = load_task(ROOT / "configs/tasks/clinical_reasoning/task_013_co_poisoning.yaml")
    source = task.patient["labs"]["co_oximetry"]
    (result,) = project_labs({"co_oximetry": source}, "/patient/labs")
    assert result.value is result.unit is result.reference_range is result.timestamp is None
    assert result.source_data == source
    assert result.source_data["carboxyhemoglobin_child_1"] == 22
    assert result.source_data["units"] == "% (normal non-smoker <3%)"


def test_drawn_time_is_not_silently_treated_as_result_time():
    source = {"value": "B positive", "drawn_time": "2026-01-16T03:25:00Z"}
    (result,) = project_labs({"type_and_screen": source}, "/patient/labs")
    assert result.timestamp is None and result.timing_status == "missing"
    assert result.source_data["drawn_time"] == source["drawn_time"]
    assert result.abnormal is None


@pytest.mark.parametrize(
    "abnormal,expected", [(True, True), (False, False), ("false", None), (0, None), (None, None)]
)
def test_only_explicit_strict_boolean_abnormality_is_projected(abnormal, expected):
    (result,) = project_labs({"test": {"value": 18, "abnormal": abnormal}}, "/patient/labs")
    assert result.abnormal is expected
    assert result.source_data["abnormal"] == abnormal


@pytest.mark.parametrize(
    "fields,expected",
    [
        ({"reference": "<14"}, "<14"),
        ({"reference_range": "<14"}, "<14"),
        ({"reference": "<14", "reference_range": "<14"}, "<14"),
        ({"reference": "<14", "reference_range": "<20"}, None),
        ({"reference": 14, "reference_range": "<14"}, None),
        ({"reference": None, "reference_range": "<14"}, None),
        ({"reference": ""}, ""),
    ],
)
def test_reference_aliases_preserve_single_or_agreeing_values_and_refuse_silent_conflicts(
    fields, expected
):
    raw = {"value": 18, **fields}
    (result,) = project_labs({"test": raw}, "/patient/labs")
    assert result.reference_range == expected
    assert result.source_data == raw


@pytest.mark.parametrize(
    "value,unit", [(False, 7), (["18"], ["ng/L"]), ({"qualifier": "<", "number": 4}, None)]
)
def test_wrong_structured_field_types_are_unknown_and_remain_in_raw_source(value, unit):
    raw = {"value": value, "unit": unit}
    (result,) = project_labs({"test": raw}, "/patient/labs")
    assert result.value is result.unit is None
    assert result.source_data == raw


def test_nested_source_copy_and_rfc6901_key_escaping():
    raw = {"value": 18, "notes": {"comments": ["Keep literal note"]}}
    original = deepcopy(raw)
    (result,) = project_labs({"a/b~c": raw}, "/patient/labs")
    raw["notes"]["comments"].append("Changed caller")
    assert result.source_data == original
    assert result.source_path == "/patient/labs/a~1b~0c"


@pytest.mark.parametrize("time", ["2026-01-15T10:50:00", "10:50", "pending", None])
def test_unresolved_times_never_fall_back_to_scenario_or_wall_clock(time):
    raw = {"value": 18, "time": time}
    (result,) = project_labs({"test": raw}, "/patient/labs")
    assert result.timestamp is None
    assert result.timing_status != "explicit"
    assert result.source_data == raw


def test_all_entries_and_duplicate_display_names_keep_distinct_source_paths():
    results = project_labs({"a_b": 0, "a b": 1, "panel": {"first": 2}}, "/patient/labs")
    assert [r.value for r in results] == [0, 1, None]
    assert len({r.source_path for r in results}) == 3


@pytest.mark.parametrize("empty", [None, {}])
def test_absent_lab_group_is_empty(empty):
    assert project_labs(empty, "/patient/labs") == ()


@pytest.mark.parametrize("malformed", [["lab"], 12, "pending", {1: 12}])
def test_malformed_top_level_lab_container_rejected_clearly(malformed):
    with pytest.raises(ValueError, match="lab"):
        project_labs(malformed, "/patient/labs")


def test_current_catalog_lab_entries_retain_their_complete_authored_subtrees():
    groups = ("labs", "labs_post_rosc", "labs_available", "labs_at_discharge", "initial_labs")
    observed = 0
    for path in sorted((ROOT / "configs/tasks").rglob("*.yaml")):
        patient = load_task(path).patient or {}
        for group in groups:
            source = patient.get(group)
            if not isinstance(source, dict):
                continue
            projected = project_labs(source, f"/patient/{group}")
            assert len(projected) == len(source), path
            for (key, expected), actual in zip(source.items(), projected, strict=True):
                assert actual.source_data == expected, (path, group, key)
                assert type(actual.source_data) is type(expected), (path, group, key)
                observed += 1
    assert observed == 991


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_raw_source_is_rejected_in_standalone_projection(value):
    with pytest.raises(ValueError, match="non-finite"):
        project_labs({"panel": {"nested": [value]}}, "/patient/labs")
