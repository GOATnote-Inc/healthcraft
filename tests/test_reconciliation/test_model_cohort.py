"""Fixed local-model cohorts retain missing, failed and incorrectly completed attempts."""

import hashlib
import importlib
import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest

from healthcraft.reconciliation.casebook import canonical_bytes, digest, load_cases
from healthcraft.reconciliation.controller import PilotSettings, command_format_identity
from healthcraft.reconciliation.execution_v2 import run_case


def save(path, value):
    path.write_bytes(canonical_bytes(value) + b"\n")


@pytest.fixture
def api():
    return importlib.import_module("healthcraft.reconciliation.model_cohort")


@pytest.fixture
def plan(api, tmp_path):
    from healthcraft.reconciliation.public_case import public_case_context

    cases = load_cases()[:2]
    models = []
    for name in ("one", "two"):
        models.append(
            {
                "id": name,
                "config": {
                    "model": f"fixture-{name}:latest",
                    "expected_digest": ("a" if name == "one" else "b") * 64,
                    "expected_runtime": "test",
                    "settings": asdict(PilotSettings()),
                    "command_format": command_format_identity(),
                },
            }
        )
    value = {
        "schema_version": "healthcraft-reconciliation-model-cohort-plan/v2",
        "exposure": "development",
        "casebook_sha256": cases[0]["casebook_sha256"],
        "models": models,
        "cases": [
            {
                "case_id": case["case_id"],
                "initial_messages_sha256": public_case_context(case["scenario"]["target"])[
                    "initial_messages_sha256"
                ],
            }
            for case in cases
        ],
        "roster": [
            {
                "id": f"{case['case_id']}/{model['id']}",
                "case_id": case["case_id"],
                "model_id": model["id"],
            }
            for case in cases
            for model in models
        ],
    }
    folder = tmp_path / "plans"
    folder.mkdir()
    path = folder / "plan.json"
    save(path, value)
    return path, value


def reference_attempt(case, config, output_dir):
    output_dir.mkdir(parents=True)
    evidence = run_case(case, journal_path=output_dir / "native.jsonl")
    save(output_dir / "execution.json", evidence)
    receipt = {
        "schema_version": "healthcraft-reconciliation-model-attempt/v2",
        "status": "completed",
        "case_binding": evidence["case_binding"],
        "model_config": deepcopy(config),
        "model_calls": 0,
        "worker_receipt": None,
        "error": None,
    }
    save(output_dir / "receipt.json", receipt)
    return receipt


def execute(api, plan, output, **kwargs):
    return api.run_model_cohort(
        plan[0],
        output,
        expected_sha256=digest(plan[1]),
        attempt_runner=kwargs.pop("attempt_runner", reference_attempt),
        **kwargs,
    )


def test_fixed_roster_exclusive_files_and_separate_completion_grading(api, plan, tmp_path):
    output = tmp_path / "out"
    result = execute(api, plan, output)
    assert result["schema_version"] == "healthcraft-reconciliation-model-cohort/v2"
    assert result["status"] == "completed"
    assert result["counts"] == {
        "scheduled": 4,
        "attempted": 4,
        "completed": 4,
        "failed": 0,
        "interrupted": 0,
        "not_attempted": 0,
        "grading_errors": 0,
        "mechanical_passed": 4,
        "mechanical_not_verified": 0,
    }
    assert result["benchmark_score"] is None and result["clinical_criteria"] == 0
    assert result["plan_sha256"] == digest(plan[1])
    assert result["sources_unchanged"] is True
    assert result["files"] == {
        p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in output.rglob("*")
        if p.is_file() and p.name != "manifest.json"
    }
    assert json.loads((output / "manifest.json").read_bytes()) == result
    before = (output / "manifest.json").read_bytes()
    with pytest.raises(OSError):
        execute(api, plan, output)
    assert (output / "manifest.json").read_bytes() == before


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_case",
        "duplicate_model",
        "same_weights",
        "missing_roster",
        "duplicate_roster",
        "unknown_case",
        "unknown_model",
        "path_traversal",
        "prompt_hash",
        "casebook_hash",
        "cloud",
        "settings",
        "unsupported_claim",
        "wrong_pin",
    ],
)
def test_invalid_plan_fails_before_attempts_or_outputs(api, plan, tmp_path, change):
    path, value = plan
    if change == "duplicate_case":
        value["cases"].append(deepcopy(value["cases"][0]))
    elif change == "duplicate_model":
        value["models"][1]["id"] = "one"
    elif change == "same_weights":
        value["models"][1]["config"]["expected_digest"] = value["models"][0]["config"][
            "expected_digest"
        ]
    elif change == "missing_roster":
        value["roster"].pop()
    elif change == "duplicate_roster":
        value["roster"].append(deepcopy(value["roster"][0]))
    elif change == "unknown_case":
        value["cases"][0]["case_id"] = "REC2-999"
    elif change == "unknown_model":
        value["roster"][0]["model_id"] = "unknown"
    elif change == "path_traversal":
        value["roster"][0]["id"] = "../escape"
    elif change == "prompt_hash":
        value["cases"][0]["initial_messages_sha256"] = "0" * 64
    elif change == "casebook_hash":
        value["casebook_sha256"] = "0" * 64
    elif change == "cloud":
        value["models"][0]["config"]["model"] = "model:cloud"
    elif change == "settings":
        value["models"][0]["config"]["settings"]["max_model_responses"] = True
    elif change == "unsupported_claim":
        value["exposure"] = "held_out"
    save(path, value)
    seen = []
    with pytest.raises(ValueError):
        api.run_model_cohort(
            path,
            tmp_path / "out",
            expected_sha256="0" * 64 if change == "wrong_pin" else digest(value),
            attempt_runner=lambda *args: seen.append(args),
        )
    assert not seen and not (tmp_path / "out").exists()


def test_no_output_inside_plan_or_casebook(api, plan):
    with pytest.raises(ValueError, match="inside|within"):
        execute(api, plan, plan[0].parent / "out")


def test_completed_but_wrong_content_is_not_an_execution_error(api, plan, tmp_path):
    from healthcraft.reconciliation.case_controls import run_control

    def wrong(case, config, output_dir):
        receipt = reference_attempt(case, config, output_dir)
        if case["case_id"] == "REC2-002":
            save(output_dir / "execution.json", run_control(case)["evidence"])
        return receipt

    result = execute(api, plan, tmp_path / "out", attempt_runner=wrong)
    assert result["status"] == "completed"
    assert result["counts"]["completed"] == 4
    assert result["counts"]["mechanical_not_verified"] == 2
    assert result["counts"]["failed"] == 0
    assert result["outcomes"][2]["observed_actions"]["stored_note_count"] == 1
    assert result["outcomes"][2]["observed_actions"]["stored_note_readback_count"] == 1


def test_attempt_exception_and_grader_error_preserve_remaining_roster(
    api, plan, tmp_path, monkeypatch
):
    seen = []

    def first_fail(case, config, output_dir):
        seen.append(case["case_id"])
        if len(seen) == 1:
            raise RuntimeError("first model unavailable")
        return reference_attempt(case, config, output_dir)

    actual = api.verify_case
    graded = []

    def grade(case, evidence):
        graded.append(case["case_id"])
        if len(graded) == 1:
            raise ValueError("grader unavailable")
        return actual(case, evidence)

    monkeypatch.setattr(api, "verify_case", grade)
    result = execute(api, plan, tmp_path / "out", attempt_runner=first_fail)
    assert len(seen) == len(result["outcomes"]) == 4
    assert result["counts"]["failed"] == 1 and result["counts"]["grading_errors"] == 1
    assert result["counts"]["mechanical_passed"] == 2
    assert (tmp_path / "out/REC2-001/two/execution.json").exists()
    assert result["status"] == "incomplete"


def test_interruption_retains_full_roster_without_starting_more_models(api, plan, tmp_path):
    seen = []

    def interrupt(case, config, output_dir):
        seen.append(case["case_id"])
        raise KeyboardInterrupt("user stopped cohort")

    result = execute(api, plan, tmp_path / "out", attempt_runner=interrupt)
    assert len(seen) == 1 and len(result["outcomes"]) == 4
    assert result["counts"]["interrupted"] == 1 and result["counts"]["not_attempted"] == 3
    assert result["status"] == "interrupted"


def test_execution_binding_mismatch_remains_grading_error(api, plan, tmp_path):
    def mismatched(case, config, output_dir):
        receipt = reference_attempt(case, config, output_dir)
        receipt["case_binding"]["case_id"] = "REC2-999"
        return receipt

    result = execute(api, plan, tmp_path / "out", attempt_runner=mismatched)
    assert result["counts"]["failed"] == 4
    assert result["counts"]["mechanical_passed"] == 0


def test_implementation_drift_withholds_completed_cohort(api, plan, tmp_path, monkeypatch):
    snapshots = iter([{"a": "1"}, {"a": "2"}])
    monkeypatch.setattr(api, "_source_hashes", lambda: next(snapshots))
    result = execute(api, plan, tmp_path / "out")
    assert result["status"] == "implementation_changed"
    assert result["sources_unchanged"] is False
    assert result["counts"]["attempted"] == 4


def test_outcome_file_collision_retains_error_and_continues_roster(api, plan, tmp_path):
    seen = []

    def collide(case, config, output_dir):
        receipt = reference_attempt(case, config, output_dir)
        seen.append(case["case_id"])
        if len(seen) == 1:
            (output_dir / "cohort-outcome.json").write_text("original collision bytes")
        return receipt

    output = tmp_path / "out"
    result = execute(api, plan, output, attempt_runner=collide)
    assert len(seen) == len(result["outcomes"]) == 4
    assert result["status"] == "incomplete"
    assert result["counts"]["failed"] == 1
    assert result["outcomes"][0]["capture_error"]["type"] == "FileExistsError"
    assert (output / "REC2-001/one/cohort-outcome.json").read_text() == "original collision bytes"


def test_literal_readback_preserves_duplicate_note_multiplicity(api):
    evidence = {
        "after": {
            "entities": {
                "clinical_note": {
                    "n1": {"id": "n1", "patient_id": "p", "encounter_id": "e", "content": "same"},
                    "n2": {"id": "n2", "patient_id": "p", "encounter_id": "e", "content": "same"},
                }
            }
        },
        "calls": [
            {
                "name": "getEncounterDetails",
                "response": {
                    "status": "ok",
                    "data": {
                        "id": "e",
                        "patient_id": "p",
                        "clinical_notes": [["Progress Note", "same"]],
                    },
                },
            }
        ],
    }
    actions = api._observed_actions(evidence)
    assert actions["stored_note_count"] == 2
    assert actions["stored_note_readback_count"] == 1


@pytest.mark.parametrize(
    "error", [False, {}, "failed", {"type": "Error", "message": "late failure"}]
)
def test_completed_receipt_with_error_is_not_completed_cohort(api, plan, tmp_path, error):
    def inconsistent(case, config, output_dir):
        receipt = reference_attempt(case, config, output_dir)
        receipt["error"] = error
        return receipt

    result = execute(api, plan, tmp_path / "out", attempt_runner=inconsistent)
    assert result["status"] == "incomplete"
    assert result["counts"]["failed"] == 4


@pytest.mark.parametrize(
    "field,value", [("mechanical_passed", 1), ("status", "verified"), ("case_binding", None)]
)
def test_malformed_grader_receipt_is_retained_as_unassessed(
    api, plan, tmp_path, monkeypatch, field, value
):
    actual = api.verify_case

    def wrong(case, evidence):
        report = actual(case, evidence)
        if field == "status":
            report["checks"]["readback"] = False
        report[field] = value
        return report

    monkeypatch.setattr(api, "verify_case", wrong)
    result = execute(api, plan, tmp_path / "out")
    assert result["counts"]["grading_errors"] == 4
    assert result["counts"]["mechanical_passed"] == 0
    assert result["counts"]["mechanical_not_verified"] == 0
    assert (tmp_path / "out/REC2-001/one/verification.json").exists()


def test_real_cli_rejects_bad_pin_outside_repository_before_inference(api, plan, tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts/reconciliation_local_cohort.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--plan",
            str(plan[0]),
            "--expected-sha256",
            "0" * 64,
            "--output-dir",
            str(tmp_path / "out"),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 2
    assert json.loads(result.stderr)["status"] == "preflight_or_io_error"
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "status,code",
    [("completed", 0), ("incomplete", 1), ("interrupted", 1), ("implementation_changed", 1)],
)
def test_cli_completion_is_not_a_clinical_or_task_pass(api, tmp_path, monkeypatch, status, code):
    import importlib.util

    script = Path(__file__).resolve().parents[2] / "scripts/reconciliation_local_cohort.py"
    spec = importlib.util.spec_from_file_location("cohort_cli_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module,
        "run_model_cohort",
        lambda *a, **k: {
            "status": status,
            "counts": {"mechanical_passed": 0},
            "sources_unchanged": True,
            "benchmark_score": None,
        },
    )
    assert (
        module.main(
            [
                "--plan",
                "plan.json",
                "--expected-sha256",
                "a" * 64,
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
        == code
    )
