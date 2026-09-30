"""Engineering regression labels are typed evidence, not clinician validation."""

from __future__ import annotations

import hashlib

import pytest
import yaml

from healthcraft.evals import grader_goldset as goldset
from healthcraft.tasks.loader import load_tasks


@pytest.fixture(scope="module")
def tasks():
    return load_tasks(goldset._TASKS_DIR)


@pytest.fixture(autouse=True)
def cached_tasks(monkeypatch, tasks):
    monkeypatch.setattr(goldset, "load_tasks", lambda _path: tasks)


@pytest.fixture
def case():
    return {
        "id": "criterion-control",
        "task_id": "MW-016",
        "criterion_id": "MW-016-C02",
        "channel": "v10",
        "safety_critical": True,
        "expected_satisfied": True,
        "orders": [{"tool": "createClinicalOrder", "params": {"medication": "levetiracetam"}}],
        "clinical_note": "This selected criterion excludes hydantoins; no full-care judgment.",
    }


def run(tmp_path, data):
    path = tmp_path / "fixtures.yaml"
    path.write_text(yaml.safe_dump(data))
    return goldset.run_goldset(path)


@pytest.mark.parametrize("field", ["expected_satisfied", "safety_critical"])
@pytest.mark.parametrize("invalid", ["false", "true", None, 0, 1, [], {}])
def test_labels_require_actual_booleans(tmp_path, case, field, invalid):
    case[field] = invalid
    report = run(tmp_path, {"cases": [case]})
    assert report.errors
    assert report.outcomes == []


def test_safety_label_must_match_effective_task_criterion(tmp_path, case):
    case["safety_critical"] = False
    report = run(tmp_path, {"cases": [case]})
    assert report.errors
    assert report.outcomes == []


@pytest.mark.parametrize("data", [None, [], {}, {"cases": []}, {"cases": {}}, {"cases": [None]}])
def test_empty_or_malformed_suite_is_a_harness_error(tmp_path, data):
    report = run(tmp_path, data)
    assert report.errors
    assert report.outcomes == []


def test_duplicate_ids_do_not_inflate_denominators(tmp_path, case):
    report = run(tmp_path, {"cases": [case, case]})
    assert report.errors
    assert len(report.outcomes) <= 1


def test_duplicate_ids_across_case_kinds_are_rejected(tmp_path, case):
    judge_case = {
        "id": case["id"],
        "expected_satisfied": True,
        "safety_critical": False,
        "judge_response": '{"satisfied":true,"evidence":"test"}',
    }
    report = run(tmp_path, {"cases": [case], "judge_parser_cases": [judge_case]})
    assert report.errors
    assert len(report.outcomes) <= 1


def test_nonboolean_grader_output_is_not_coerced(monkeypatch, tmp_path, case):
    monkeypatch.setattr(goldset, "_evaluate_world_case", lambda *_args: "false")
    report = run(tmp_path, {"cases": [case]})
    assert report.errors
    assert report.outcomes == []


@pytest.mark.parametrize("response", [None, False, 0, [], {}])
def test_malformed_judge_fixture_is_not_counted_as_parser_success(tmp_path, response):
    case = {
        "id": "malformed-fixture",
        "expected_satisfied": False,
        "safety_critical": True,
        "judge_response": response,
    }
    report = run(tmp_path, {"judge_parser_cases": [case]})
    assert report.errors
    assert report.outcomes == []


def test_world_case_cannot_use_unassessed_llm_placeholder(tmp_path, case):
    case.update(task_id="IR-002", criterion_id="IR-002-C04", safety_critical=False, channel="v8")
    report = run(tmp_path, {"cases": [case]})
    assert report.errors
    assert report.outcomes == []


def test_unmeasured_rates_are_unknown_and_display_as_unmeasured():
    group = goldset.GroupStats("world_state", "v10")
    assert group.false_pass_rate_ci()[0] is None
    assert group.false_fail_rate_ci()[0] is None
    report = goldset.Report(groups={("world_state", "v10"): group})
    rendered = goldset.format_report(report)
    assert "unmeasured" in rendered.lower()
    assert "0/0 0%" not in rendered


def test_report_records_scope_and_source_pins_without_adjudication_claim(tmp_path, case):
    path = tmp_path / "fixtures.yaml"
    path.write_text(yaml.safe_dump({"cases": [case], "label_basis": "EM-adjudicated"}))
    report = goldset.run_goldset(path)
    assert report.errors == []
    assert report.label_basis == "engineering_regression"
    assert report.clinician_adjudication_verified is False
    assert report.fixture_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert report.source_hashes["src/healthcraft/tasks/evaluator.py"]
    text = goldset.format_report(report).lower()
    assert "synthetic audit" in text and "not clinician" in text
    assert "not a population" in text


def test_cli_rejects_empty_report(monkeypatch):
    monkeypatch.setattr(goldset, "run_goldset", goldset.Report)
    assert goldset.main() == 1
