"""Independently labeled replay challenges report defects instead of hiding them."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from healthcraft.tasks import challenges

REPO_ROOT = Path(__file__).resolve().parents[2]


def _fixture(tmp_path, cases):
    data = json.loads(challenges.DEFAULT_CHALLENGES.read_text())
    data["cases"] = cases
    path = tmp_path / "challenges.json"
    path.write_text(json.dumps(data))
    return path


def _cases():
    return json.loads(challenges.DEFAULT_CHALLENGES.read_text())["cases"]


def test_known_semantic_defects_are_reported_against_independent_labels():
    report = challenges.run_challenges(rubric_channel="v10")
    outcomes = {row["id"]: row for row in report["outcomes"]}

    for case_id in ("unrelated-bed-lookup", "wrong-patient-history", "empty-history"):
        row = outcomes[case_id]
        assert row["expected"] is False
        assert row["actual"] is True
        assert row["outcome"] == "false_pass"
        assert row["error"] is None
    assert report["summary"]["false_pass"] == 3
    assert report["summary"]["false_fail"] == 0
    assert report["summary"]["errors"] == 0
    assert report["coverage"] == {
        "cases": 7,
        "tasks": 2,
        "criteria": 2,
        "measured_safety_cases": 0,
    }
    assert report["replay_only"] is True
    assert "clinical" in report["limitations"].lower()


def test_unmeasured_safety_is_not_reported_as_zero_error_rate():
    report = challenges.run_challenges()

    assert all(row["safety_critical"] is False for row in report["outcomes"])
    safety = report["safety_groups"]["safety_critical"]
    assert safety["total"] == 0
    assert safety["evaluated"] == 0
    assert safety["false_pass_rate"] is None
    assert safety["false_fail_rate"] is None
    assert report["safety_groups"]["non_safety"]["evaluated"] == 7


def test_response_failure_missing_and_mismatched_ids_do_not_earn_credit():
    outcomes = {
        row["id"]: row for row in challenges.run_challenges(rubric_channel="v8")["outcomes"]
    }
    for case_id in ("failed-history", "missing-history-response", "wrong-response-id"):
        assert outcomes[case_id]["actual"] is False
        assert outcomes[case_id]["outcome"] == "match"
    positive = outcomes["complete-history"]
    assert positive["expected"] is True
    assert positive["actual"] is True
    assert positive["outcome"] == "match"


def test_real_replay_runs_and_label_does_not_drive_actual(tmp_path, monkeypatch):
    original = challenges.replay_from_trajectory
    calls = []

    def record(*args, **kwargs):
        calls.append((args[1].id, kwargs["rubric_channel"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(challenges, "replay_from_trajectory", record)
    case = copy.deepcopy(_cases()[0])
    case["expected_satisfied"] = True
    report = challenges.run_challenges(_fixture(tmp_path, [case]), rubric_channel="v9")

    assert calls == [("IR-001", "v9")]
    assert report["outcomes"][0]["actual"] is True
    assert report["outcomes"][0]["outcome"] == "match"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expected_satisfied", "false"),
        ("expected_satisfied", 0),
        ("criterion_id", "IR-001-NO-SUCH-CRITERION"),
        ("task_id", "IR-OTHER"),
        ("assertion", "A changed assertion cannot reuse the old label"),
        ("trajectory", {"task_id": "IR-OTHER", "turns": []}),
        ("category", ""),
        ("category", []),
        ("category", ["malformed"]),
        ("category", 42),
        ("id", []),
    ],
)
def test_invalid_case_is_harness_error_not_false_fail(tmp_path, field, value):
    case = copy.deepcopy(_cases()[0])
    case[field] = value
    report = challenges.run_challenges(_fixture(tmp_path, [case]))

    assert report["summary"]["errors"] == 1
    assert report["summary"]["evaluated"] == 0
    assert report["summary"]["false_fail"] == 0
    assert report["summary"]["false_pass"] == 0
    row = report["outcomes"][0]
    assert row["actual"] is None
    assert row["outcome"] == "error"
    assert row["error"]


def test_missing_and_duplicate_rows_are_reported_without_silent_deduplication(tmp_path):
    case = copy.deepcopy(_cases()[0])
    report = challenges.run_challenges(_fixture(tmp_path, [case, case, None, {}]))

    assert len(report["outcomes"]) == 4
    assert report["summary"]["errors"] == 3
    assert report["summary"]["evaluated"] == 1


def test_errors_are_excluded_from_category_denominators(tmp_path):
    cases = copy.deepcopy(_cases()[:1])
    invalid = copy.deepcopy(cases[0])
    invalid.update(id="bad-criterion", criterion_id="missing", expected_satisfied=True)
    report = challenges.run_challenges(_fixture(tmp_path, [*cases, invalid]))
    stats = report["categories"][cases[0]["category"]]

    assert stats["total"] == 2
    assert stats["errors"] == 1
    assert stats["expected_negative"] == 1
    assert stats["expected_positive"] == 0
    assert stats["false_pass_rate"] == 1.0
    assert stats["false_fail_rate"] is None


def test_false_fail_counts_are_distinct_from_errors(tmp_path):
    case = copy.deepcopy(next(case for case in _cases() if case["id"] == "failed-history"))
    case["expected_satisfied"] = True
    report = challenges.run_challenges(_fixture(tmp_path, [case]))

    assert report["outcomes"][0]["outcome"] == "false_fail"
    assert report["summary"]["false_fail"] == 1
    assert report["summary"]["false_fail_rate"] == 1.0
    assert report["summary"]["false_pass_rate"] is None
    assert report["summary"]["errors"] == 0


def test_execution_error_is_reported_as_ungraded(tmp_path):
    case = copy.deepcopy(_cases()[0])
    case["trajectory"]["error"] = "Interrupted synthetic rollout"
    report = challenges.run_challenges(_fixture(tmp_path, [case]))

    assert report["outcomes"][0]["actual"] is None
    assert "Execution incomplete" in report["outcomes"][0]["error"]
    assert report["summary"]["errors"] == 1
    assert report["summary"]["evaluated"] == 0


def test_fixture_uses_advertised_call_parameters_and_no_saved_labels():
    tools = json.loads((REPO_ROOT / "configs/mcp-tools.json").read_text())["tools"]
    schemas = {tool["name"]: tool["parameters"] for tool in tools}
    for case in _cases():
        assert "criteria_results" not in case["trajectory"]
        for turn in case["trajectory"]["turns"]:
            for call in turn.get("tool_calls", []):
                jsonschema.validate(call["arguments"], schemas[call["name"]])


def test_source_hashes_and_report_are_reproducible():
    first = challenges.run_challenges(rubric_channel="v10")
    assert first == challenges.run_challenges(rubric_channel="v10")
    hashes = first["source_hashes"]
    for relative in (
        "configs/tasks/information_retrieval/task_001_allergy_check.yaml",
        "configs/rubrics/v9_deterministic_overlay.yaml",
        "configs/rubrics/v10_deterministic_overlay.yaml",
        "src/healthcraft/tasks/evaluator.py",
        "src/healthcraft/tasks/challenges.py",
        "configs/em_vocab.yaml",
    ):
        assert hashes[relative] == hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()
    assert (
        first["fixture_sha256"]
        == hashlib.sha256(challenges.DEFAULT_CHALLENGES.read_bytes()).hexdigest()
    )
    assert first["rubric_channel"] == "v10"


def test_runner_never_writes_shadow_results_and_restores_environment(tmp_path, monkeypatch):
    shadow_path = tmp_path / "must-not-be-created.jsonl"
    monkeypatch.setenv("HEALTHCRAFT_POC_VALIDATOR_SHADOW", "1")
    monkeypatch.setenv("HEALTHCRAFT_POC_VALIDATOR_LOG", str(shadow_path))
    challenges.run_challenges()

    assert not shadow_path.exists()
    assert os.environ["HEALTHCRAFT_POC_VALIDATOR_SHADOW"] == "1"


def test_cli_fails_for_mismatches_and_can_explicitly_report_only(tmp_path):
    command = [sys.executable, str(REPO_ROOT / "scripts/grade_challenges.py")]
    failed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)
    assert failed.returncode == 1, failed.stderr
    assert json.loads(failed.stdout)["summary"]["false_pass"] == 3

    output = tmp_path / "report.json"
    completed = subprocess.run(
        [*command, "--report-only", "--output", str(output)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text())["summary"]["false_pass"] == 3


def test_report_only_does_not_suppress_harness_errors(tmp_path):
    fixture = _fixture(tmp_path, [{}])
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/grade_challenges.py"),
            "--fixture",
            str(fixture),
            "--report-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["summary"]["errors"] == 1


def test_cli_never_overwrites_existing_artifacts(tmp_path):
    output = tmp_path / "existing.json"
    output.write_text("immutable artifact\n")
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/grade_challenges.py"),
            "--report-only",
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 2
    assert output.read_text() == "immutable artifact\n"
