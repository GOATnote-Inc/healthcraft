"""Experimental observation runs must not become benchmark failures in log readers."""

import importlib.util
import json
from pathlib import Path

import pytest

from healthcraft import trajectory as capture


@pytest.fixture
def analysis():
    path = Path(__file__).parents[2] / "scripts/analyze_results.py"
    spec = importlib.util.spec_from_file_location("unassessed_analysis", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _trajectory(*, error=None, profile=True):
    result = capture.Trajectory("CC-022", "fixture", 42, "Synthetic", error=error)
    result.add_turn("assistant", "Observation review complete.")
    result.metadata["stop_reason"] = "stop" if error is None else "client_error"
    if profile:
        result.metadata["scenario_context"] = {"profile_version": "roster-observations/v1"}
    if error is not None:
        result.metadata["failure_stage"] = "environment"
    result.set_results([], 0.0, False, False, {})
    return result


def _entry(*, error=None, profile=True):
    return json.loads(
        capture.ExperimentEntry.from_trajectory(
            _trajectory(error=error, profile=profile),
            "trajectories/clinical_communication/CC-022_fixture_42_t1.json",
        ).to_jsonl()
    )


@pytest.mark.parametrize("error", [None, "Synthetic seed failure"])
def test_experiment_log_roundtrip_preserves_unassessed_profile(tmp_path, error):
    row = _entry(error=error)
    assert row["scenario_profile"] == "roster-observations/v1"
    assert row["grading_complete"] is False
    assert row["benchmark_comparable"] is False
    assert row["execution_completed"] is (error is None)
    assert row["failure_stage"] == ("environment" if error else None)
    path = tmp_path / "experiments.jsonl"
    log = capture.ExperimentLog(path)
    log.append(capture.ExperimentEntry(**row))
    assert json.loads(log.load_all()[0].to_jsonl()) == row


@pytest.mark.parametrize(
    "row",
    [
        {"scenario_profile": "roster-observations/v1"},
        {"evaluation_mode": "profile_diagnostic"},
        {"benchmark_comparable": False},
        {"benchmark_score": None},
        {"grading_complete": False},
        {"ungraded_criteria": 3},
        {"metadata": {"scenario_context": {"profile_version": "roster-observations/v1"}}},
        {"metadata": {"scenario_profile": "roster-observations/v1"}},
        {"metadata": {"grading_complete": False}},
        {"metadata": {"benchmark_comparable": False}},
    ],
)
def test_shared_marker_reader_accepts_log_trajectory_and_summary_shapes(row):
    assert capture.is_unassessed_experiment(row)


def test_legacy_log_defaults_do_not_change_benchmark_semantics(analysis, tmp_path):
    row = _entry(profile=False)
    for field in (
        "scenario_profile",
        "grading_complete",
        "benchmark_comparable",
        "execution_completed",
        "failure_stage",
    ):
        row.pop(field, None)
    path = tmp_path / "experiments.jsonl"
    path.write_text(json.dumps(row) + "\n")
    loaded = capture.ExperimentLog(path).load_all()[0]
    assert loaded.scenario_profile is None
    assert not capture.is_unassessed_experiment(json.loads(loaded.to_jsonl()))
    result = analysis.analyze_model(analysis.load_experiments(tmp_path), "fixture")
    assert result["pass_rate"] == 0.0
    assert result["safety_failures"] == 1
    assert result["unknown_completion_runs"] == 1


def test_profile_failures_keep_full_execution_denominators_and_null_scores(analysis):
    result = analysis.analyze_model(
        [_entry(), _entry(error="Synthetic seed failure")], "fixture", scheduled_runs=5
    )
    assert result["scheduled_runs"] == 5
    assert result["attempted_runs"] == result["unassessed_runs"] == 2
    assert result["completed_runs"] == 1
    assert result["error_runs"] == 1
    assert result["unknown_completion_runs"] == 0
    assert result["total_trials"] == 2
    assert result["benchmark_comparable"] is False
    for key in (
        "total_passed",
        "pass_rate",
        "pass_at_1",
        "pass_at_3",
        "pass_5",
        "avg_reward",
        "safety_failures",
        "safety_failure_rate",
        "safety_failures_excl_errors",
        "safety_failure_rate_excl_errors",
    ):
        assert result[key] is None
    assert result["per_task"] == result["per_category"] == []
    report = analysis.generate_report([result])
    assert "Not assessed" in report
    assert "100.0%" not in report
    assert "Corecraft Table 1 Comparison" not in report


def test_mixed_cohort_does_not_silently_drop_unassessed_trial(analysis):
    graded = _entry(profile=False)
    graded.update(reward=1.0, passed=True, safety_gate_passed=True)
    result = analysis.analyze_model([graded, _entry()], "fixture")
    assert result["total_trials"] == result["attempted_runs"] == 2
    assert result["unassessed_runs"] == 1
    assert result["pass_rate"] is None
    assert result["scheduled_runs"] is None


def test_cli_reports_planned_count_without_treating_unstarted_trials_as_failures(
    analysis, tmp_path, monkeypatch, capsys
):
    (tmp_path / "experiments.jsonl").write_text(json.dumps(_entry()) + "\n")
    (tmp_path / "summary.json").write_text(
        json.dumps({"agent_model": "fixture", "total_tasks": 2, "trials": 3})
    )
    monkeypatch.setattr("sys.argv", ["analyze_results.py", str(tmp_path)])
    analysis.main()
    report = capsys.readouterr().out
    assert "| Scheduled trials | 6 |" in report
    assert "| Attempted trials | 1 |" in report
    assert "| Pass Rate | Not assessed |" in report


def test_incomplete_terminal_generation_is_not_counted_complete():
    trajectory = _trajectory()
    trajectory.metadata["stop_reason"] = "length"
    row = capture.ExperimentEntry.from_trajectory(trajectory, "trajectory.json")
    assert row.execution_completed is False


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"stop_reason": None},
        {"stop_reason": "mystery"},
        {"stop_reason": "stop", "termination_kind": "provider_refusal"},
        {"stop_reason": "stop", "provider_refusal": "Cannot comply"},
    ],
)
def test_missing_or_contradictory_completion_provenance_stays_unknown(metadata):
    trajectory = _trajectory()
    trajectory.metadata = metadata
    row = capture.ExperimentEntry.from_trajectory(trajectory, "trajectory.json")
    assert row.execution_completed is None


@pytest.mark.parametrize("answered", [False, True])
def test_completion_requires_linked_responses_for_all_tool_calls(answered):
    trajectory = _trajectory()
    trajectory.turns = []
    trajectory.add_turn(
        "assistant", "", tool_calls=[{"id": "call-1", "name": "getEncounterDetails"}]
    )
    if answered:
        trajectory.add_turn("tool", '{"status":"ok"}', tool_call_id="call-1")
    trajectory.add_turn("assistant", "Finished.")
    row = capture.ExperimentEntry.from_trajectory(trajectory, "trajectory.json")
    assert row.execution_completed is answered


def test_unlinkable_tool_response_does_not_establish_completion():
    trajectory = _trajectory()
    trajectory.turns = []
    trajectory.add_turn("tool", '{"status":"ok"}', tool_call_id="missing-call")
    trajectory.add_turn("assistant", "Finished.")
    row = capture.ExperimentEntry.from_trajectory(trajectory, "trajectory.json")
    assert row.execution_completed is None
