"""Source-concordance checks use actual injection and detect lost evidence."""

from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = spec_from_file_location(
    "observation_certificate", ROOT / "scripts/certify_observation_fidelity.py"
)
certificate = module_from_spec(spec)
spec.loader.exec_module(certificate)


@pytest.fixture
def task_path(tmp_path):
    path = tmp_path / "task.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "id": "TEST-OBS",
                "category": "information_retrieval",
                "level": 1,
                "title": "Transport",
                "description": "Synthetic transport only",
                "setting": {"time": "2026-01-15T13:15:00Z"},
                "patient": {
                    "age": 50,
                    "sex": "M",
                    "arrival_time": "2026-01-15T10:45:00Z",
                    "vitals": {
                        "time_of_vitals": "2026-01-15T10:48:00.123456789Z",
                        "heart_rate": 92,
                    },
                    "vitals_series": [{"time": "10:50", "heart_rate": "undetectable"}],
                    "labs_available": {
                        "troponin": {"time": "2026-01-15T10:50:00Z", "value": 18, "unit": "ng/L"},
                        "pending": "NOT YET DRAWN",
                    },
                },
            },
            sort_keys=False,
        )
    )
    return path


def test_real_injection_and_tool_response_preserve_source_and_report_denominators(task_path):
    report = certificate.run_certificate([task_path])
    assert report["mechanical_passed"] is True
    assert report["benchmark_score"] is None
    assert report["clinical_criteria_assessed"] == report["safety_criteria_assessed"] == 0
    assert report["counts"] == {
        "tasks_expected": 1,
        "tasks_reported": 1,
        "patient_tasks": 1,
        "no_patient_tasks": 0,
        "vitals_expected": 2,
        "vitals_returned": 2,
        "labs_expected": 2,
        "labs_returned": 2,
        "tool_calls": 1,
    }
    assert report["source_hashes_before"] == report["source_hashes_after"]
    task = report["tasks"][0]
    assert task["status"] == "concordant"
    assert task["timing_status_counts"]["vitals"] == {"explicit": 1, "time_only": 1}
    assert task["timing_status_counts"]["labs"] == {"explicit": 1, "missing": 1}
    assert task["arrival"]["source"] == task["arrival"]["returned"] == "2026-01-15T10:45:00Z"
    assert task["triage"]["returned"] is None
    assert task["actual_calls"][0]["name"] == "getEncounterDetails"


@pytest.mark.parametrize(
    "mutation",
    ["missing", "altered", "numeric_type", "timestamp", "time_keys", "duplicate", "skipped"],
)
def test_actual_response_mutants_fail_closed(task_path, monkeypatch, mutation):
    original = certificate.execute_task

    def changed(raw):
        result = original(raw)
        if mutation == "skipped":
            return None
        data = result["calls"][0]["response"]["data"]
        if mutation == "missing":
            data["labs"].pop()
        elif mutation == "altered":
            data["labs"][0]["source_data"]["value"] = 19
        elif mutation == "numeric_type":
            data["labs"][0]["source_data"]["value"] = 18.0
        elif mutation == "timestamp":
            data["vitals"][0]["timestamp"] = "2026-01-15T10:48:00.123456Z"
        elif mutation == "time_keys":
            data["vitals"][0]["source_time_keys"] = []
        elif mutation == "duplicate":
            data["vitals"].append(deepcopy(data["vitals"][0]))
        return result

    monkeypatch.setattr(certificate, "execute_task", changed)
    report = certificate.run_certificate([task_path])
    assert report["mechanical_passed"] is False
    assert len(report["tasks"]) == 1
    assert report["tasks"][0]["errors"]


def test_drift_fails_even_when_all_observations_match(task_path, monkeypatch):
    hashes = iter([{"source": "before"}, {"source": "after"}])
    monkeypatch.setattr(certificate, "source_hashes", lambda paths: next(hashes))
    report = certificate.run_certificate([task_path])
    assert report["tasks"][0]["status"] == "concordant"
    assert report["provenance_stable"] is False
    assert report["mechanical_passed"] is False


def test_patientless_task_is_retained_as_unassessed(task_path):
    raw = yaml.safe_load(task_path.read_text())
    del raw["patient"]
    task_path.write_text(yaml.safe_dump(raw))
    report = certificate.run_certificate([task_path])
    assert report["tasks"][0]["status"] == "no_patient_unassessed"
    assert report["counts"]["tasks_reported"] == report["counts"]["no_patient_tasks"] == 1
    assert report["counts"]["tool_calls"] == 0


def test_default_catalog_cannot_silently_drop_task(task_path, monkeypatch):
    monkeypatch.setattr(certificate, "catalog_paths", lambda: [task_path])
    report = certificate.run_certificate()
    assert report["mechanical_passed"] is False
    assert report["errors"]
    assert report["counts"]["tasks_expected"] == 205


def test_existing_output_rejected_before_execution(tmp_path, monkeypatch):
    output = tmp_path / "certificate.json"
    output.write_text("unchanged")
    monkeypatch.setattr(
        certificate, "run_certificate", lambda *a, **kw: pytest.fail("must not run")
    )
    assert certificate.main(["--output", str(output)]) == 2
    assert output.read_text() == "unchanged"


def test_documentation_time_is_preserved_raw_without_becoming_measurement_time(task_path):
    raw = yaml.safe_load(task_path.read_text())
    raw["patient"]["vitals"] = {"heart_rate": 80, "last_documented": "2026-01-15T10:00:00Z"}
    task_path.write_text(yaml.safe_dump(raw))
    report = certificate.run_certificate([task_path])
    assert report["mechanical_passed"] is True
    row = report["tasks"][0]["actual_calls"][0]["response"]["data"]["vitals"][0]
    assert row["timestamp"] is None and row["source_time_keys"] == []
    assert row["source_data"]["last_documented"] == "2026-01-15T10:00:00Z"


def test_conflicting_measurement_times_remain_unknown_without_losing_raw_evidence(task_path):
    raw = yaml.safe_load(task_path.read_text())
    raw["patient"]["vitals"]["time"] = "2026-01-15T11:00:00Z"
    task_path.write_text(yaml.safe_dump(raw))
    report = certificate.run_certificate([task_path])
    assert report["mechanical_passed"] is True
    assert report["tasks"][0]["timing_status_counts"]["vitals"] == {
        "conflicting": 1,
        "time_only": 1,
    }


def test_cli_failure_still_leaves_strict_json_error_artifact(tmp_path, monkeypatch):
    import json

    output = tmp_path / "certificate.json"

    def broken():
        raise ValueError("source unavailable")

    monkeypatch.setattr(certificate, "run_certificate", broken)
    assert certificate.main(["--output", str(output)]) == 2
    report = json.loads(output.read_text())
    assert report["mechanical_passed"] is False
    assert report["benchmark_score"] is None
    assert "source unavailable" in report["errors"][0]
