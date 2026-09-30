"""Independent source checks reject altered actual care/imaging responses."""

import json
from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = spec_from_file_location("care_imaging_certificate", ROOT / "scripts/certify_care_imaging.py")
certificate = module_from_spec(spec)
spec.loader.exec_module(certificate)


@pytest.fixture
def task_path(tmp_path):
    path = tmp_path / "task.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "id": "MW-006",
                "setting": {"time": "2026-01-15T12:00:00Z"},
                "patient": {
                    "age": 52,
                    "sex": "F",
                    "active_orders": [{"name": "Authored instruction", "time": "11:00"}],
                    "treatments_given": {"dose": 1, "status": "unverified source wording"},
                    "imaging": {
                        "ct_head_noncontrast": {
                            "status": "pending",
                            "expected_finding": "private future target",
                            "modality": "MR",
                            "body_part": "authored organ",
                            "result": "source result",
                            "findings": " source findings\n",
                            "time": "2026-01-15T11:00:00.123456789+01:00",
                        },
                        "read_by": "source reader",
                        "exam": "NOT OBTAINED",
                    },
                    "bedside_echo": {"rv": "authored observation", "started": "11:00"},
                },
            },
            sort_keys=False,
        )
    )
    return path


def test_actual_tool_roundtrip_and_denominators_have_no_clinical_score(task_path):
    report = certificate.run_certificate([task_path])
    assert report["mechanical_passed"] is True
    assert report["benchmark_score"] is report["clinical_grade"] is report["safety_passed"] is None
    assert report["clinical_criteria_assessed"] == report["safety_criteria_assessed"] == 0
    assert report["counts"] == {
        "tasks_expected": 1,
        "tasks_reported": 1,
        "patient_tasks": 1,
        "no_patient_tasks": 0,
        "care_tasks": 1,
        "care_expected": 2,
        "care_returned": 2,
        "imaging_tasks": 1,
        "imaging_expected": 4,
        "imaging_returned": 4,
        "notices_expected": 1,
        "notices_returned": 1,
        "withheld_fields": 1,
        "tool_calls": 1,
    }
    row = report["tasks"][0]
    assert row["status"] == "concordant"
    assert row["timing_status_counts"] == {"explicit": 1, "missing": 3}
    assert row["actual_calls"][0]["name"] == row["audit"][0]["tool_name"] == "getEncounterDetails"
    assert report["source_hashes_before"] == report["source_hashes_after"]
    assert report["runtime_before"] == report["runtime_after"]
    for path in (
        "scripts/certify_care_imaging.py",
        "scripts/certify_observation_fidelity.py",
        "configs/mcp-tools.json",
        "constraints-security.txt",
    ):
        assert path in report["source_hashes_before"]


@pytest.mark.parametrize(
    "mutation",
    [
        "lost_care",
        "care_number_type",
        "fabricated_admin",
        "missing_imaging",
        "wrong_modality",
        "inferred_impression",
        "changed_result",
        "changed_text",
        "time_precision",
        "time_keys",
        "leaked_raw_guidance",
        "leaked_notice_guidance",
        "leaked_note_guidance",
        "missing_notice",
        "duplicate_image",
        "wrong_role",
        "wrong_patient",
        "wrong_audit",
        "failed_response",
        "missing_call_id",
        "skipped",
    ],
)
def test_mutated_actual_responses_fail_closed(task_path, monkeypatch, mutation):
    execute = certificate.execute_task

    def changed(raw):
        result = execute(raw)
        if mutation == "skipped":
            return None
        call = result["calls"][0]
        data = call["response"]["data"]
        image = next(row for row in data["imaging"] if row["source_label"] == "ct_head_noncontrast")
        care = next(
            row for row in data["authored_care"] if row["source_collection"] == "treatments_given"
        )
        if mutation == "lost_care":
            data["authored_care"].pop()
        elif mutation == "care_number_type":
            care["source_data"]["dose"] = 1.0
        elif mutation == "fabricated_admin":
            data["meds_administered"] = [{"medication_name": "fictional administration"}]
        elif mutation == "missing_imaging":
            data["imaging"].pop()
        elif mutation == "wrong_modality":
            image["modality"] = "CT"
        elif mutation == "inferred_impression":
            image["impression"] = image["findings"]
        elif mutation == "changed_result":
            image["result"] = "modified"
        elif mutation == "changed_text":
            next(row for row in data["imaging"] if row["source_label"] == "exam")["report_text"] = (
                None
            )
        elif mutation == "time_precision":
            image["timestamp"] = "2026-01-15T11:00:00.123456+01:00"
        elif mutation == "time_keys":
            image["source_time_keys"] = []
        elif mutation == "leaked_raw_guidance":
            image["source_data"]["expected_finding"] = "private future target"
        elif mutation == "leaked_notice_guidance":
            data["imaging_projection_notices"][0]["target"] = "private future target"
        elif mutation == "leaked_note_guidance":
            data["clinical_notes"].append(["2026-01-15T12:00:00Z", "private future target"])
        elif mutation == "missing_notice":
            data["imaging_projection_notices"] = []
        elif mutation == "duplicate_image":
            data["imaging"].append(deepcopy(image))
        elif mutation == "wrong_role":
            image["source_role"] = "performed_study"
        elif mutation == "wrong_patient":
            data["patient_id"] = "OTHER"
        elif mutation == "wrong_audit":
            result["audit"][0]["params"]["encounter_id"] = "OTHER"
        elif mutation == "failed_response":
            call["response"]["status"] = "error"
        elif mutation == "missing_call_id":
            del call["id"]
        return result

    monkeypatch.setattr(certificate, "execute_task", changed)
    report = certificate.run_certificate([task_path])
    assert report["mechanical_passed"] is False
    assert len(report["tasks"]) == 1
    assert report["tasks"][0]["errors"]


@pytest.mark.parametrize("kind", ["source", "runtime"])
def test_provenance_drift_fails_after_concordant_transport(task_path, monkeypatch, kind):
    values = iter([{"version": "before"}, {"version": "after"}])
    method = "source_hashes" if kind == "source" else "runtime_metadata"
    monkeypatch.setattr(certificate, method, lambda *args: next(values))
    report = certificate.run_certificate([task_path])
    assert report["tasks"][0]["status"] == "concordant"
    assert report["mechanical_passed"] is False and report["provenance_stable"] is False


def test_default_catalog_missing_task_fails_without_dropping_denominator(task_path, monkeypatch):
    monkeypatch.setattr(certificate, "catalog_paths", lambda: [task_path])
    report = certificate.run_certificate()
    assert report["mechanical_passed"] is False
    assert report["counts"]["tasks_expected"] == 205
    assert report["errors"]


def test_no_patient_task_retained_unassessed(task_path):
    task_path.write_text("id: NO-PATIENT\n")
    report = certificate.run_certificate([task_path])
    assert report["mechanical_passed"] is True
    assert report["tasks"][0]["status"] == "no_patient_unassessed"
    assert report["counts"]["no_patient_tasks"] == 1
    assert report["counts"]["tool_calls"] == 0


def test_empty_or_duplicate_catalog_fails(task_path):
    assert certificate.run_certificate([])["mechanical_passed"] is False
    duplicate = certificate.run_certificate([task_path, task_path])
    assert duplicate["mechanical_passed"] is False
    assert len(duplicate["tasks"]) == 2


def test_existing_output_is_immutable_and_rejected_before_execution(tmp_path, monkeypatch):
    output = tmp_path / "report.json"
    output.write_text("unchanged")
    monkeypatch.setattr(certificate, "run_certificate", lambda: pytest.fail("must not execute"))
    assert certificate.main(["--output", str(output)]) == 2
    assert output.read_text() == "unchanged"


def test_cli_unexpected_failure_keeps_strict_json_receipt(tmp_path, monkeypatch):
    output = tmp_path / "report.json"
    monkeypatch.setattr(certificate, "run_certificate", lambda: {"bad": float("nan")})
    assert certificate.main(["--output", str(output)]) == 2
    report = json.loads(output.read_text())
    assert report["status"] == "harness_error"
    assert report["mechanical_passed"] is False and report["benchmark_score"] is None


@pytest.mark.parametrize("task_id", ["MW-006", "MW-009", "SCJ-017"])
def test_actual_reviewed_tasks_keep_all_conditional_guidance_private(task_id):
    paths = [
        path
        for path in certificate.catalog_paths()
        if yaml.safe_load(path.read_text())["id"] == task_id
    ]
    report = certificate.run_certificate(paths)
    assert report["mechanical_passed"] is True
    assert report["counts"]["notices_returned"] == 1
    assert report["counts"]["withheld_fields"] == {"MW-006": 2, "MW-009": 4, "SCJ-017": 2}[task_id]


def test_independent_catalog_selection_matches_frozen_inventory_denominators():
    # Source inventory only; no full-cohort execution or artifact generation.
    totals = {
        "tasks": 0,
        "patients": 0,
        "care": 0,
        "care_tasks": 0,
        "imaging": 0,
        "imaging_tasks": 0,
        "notices": 0,
        "omitted": 0,
    }
    for path in certificate.catalog_paths():
        raw = yaml.safe_load(path.read_text())
        totals["tasks"] += 1
        if raw.get("patient") is None:
            continue
        totals["patients"] += 1
        care, imaging, notices, omitted, _ = certificate.expected_records(raw)
        totals["care"] += len(care)
        totals["care_tasks"] += bool(care)
        totals["imaging"] += len(imaging)
        totals["imaging_tasks"] += bool(imaging)
        totals["notices"] += len(notices)
        totals["omitted"] += len(omitted)
    assert totals == {
        "tasks": 205,
        "patients": 196,
        "care": 32,
        "care_tasks": 29,
        "imaging": 115,
        "imaging_tasks": 76,
        "notices": 3,
        "omitted": 8,
    }


@pytest.mark.parametrize(
    "value,status",
    [
        (None, "missing"),
        ("11:00", "time_only"),
        ("2026", "date_only"),
        ("2026-01", "date_only"),
        ("2026-01-15", "date_only"),
        ("2026-01-15T11:00:00", "naive"),
        ("pending", "unresolved"),
        ("2026-99-15", "invalid"),
        ("2026-01-15T11:60:00Z", "invalid"),
        ("2026-01-15T11:00:00+01:60", "invalid"),
        (123, "invalid"),
        ("2026-01-15T11:59:60Z", "unsupported"),
    ],
)
def test_unresolved_timestamp_status_and_null_are_checked_independently(task_path, value, status):
    raw = yaml.safe_load(task_path.read_text())
    raw["patient"]["imaging"] = {"source": {"time": value}}
    del raw["patient"]["bedside_echo"]
    task_path.write_text(yaml.safe_dump(raw))
    report = certificate.run_certificate([task_path])
    assert report["mechanical_passed"] is True
    assert report["timing_status_counts"] == {status: 1}


def test_wrong_uncertainty_label_fails_even_when_timestamp_remains_null(task_path, monkeypatch):
    execute = certificate.execute_task

    def changed(raw):
        result = execute(raw)
        image = next(
            row
            for row in result["calls"][0]["response"]["data"]["imaging"]
            if row["source_label"] == "exam"
        )
        image["timing_status"] = "time_only"
        return result

    monkeypatch.setattr(certificate, "execute_task", changed)
    assert certificate.run_certificate([task_path])["mechanical_passed"] is False


@pytest.mark.parametrize("kind", ["source", "runtime"])
def test_postflight_provenance_failure_retains_completed_evidence(task_path, monkeypatch, kind):
    method = "source_hashes" if kind == "source" else "runtime_metadata"
    original = getattr(certificate, method)
    calls = 0

    def fails_after_execution(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("Synthetic final provenance failure")
        return original(*args)

    monkeypatch.setattr(certificate, method, fails_after_execution)
    actual_run = certificate.run_certificate
    monkeypatch.setattr(certificate, "run_certificate", lambda: actual_run([task_path]))
    output = task_path.parent / "report.json"
    assert certificate.main(["--output", str(output)]) == 1
    report = json.loads(output.read_text())
    assert report["mechanical_passed"] is report["provenance_stable"] is False
    assert report["counts"]["tasks_expected"] == report["counts"]["tasks_reported"] == 1
    assert report["counts"]["tool_calls"] == 1
    assert report["tasks"][0]["status"] == "concordant"
    assert report["tasks"][0]["actual_calls"][0]["response"]["status"] == "ok"
    assert report["tasks"][0]["audit"][0]["result_summary"] == "ok"
    assert any("Synthetic final provenance failure" in error for error in report["errors"])
    assert report[f"{'source_hashes' if kind == 'source' else 'runtime'}_after"] is None
