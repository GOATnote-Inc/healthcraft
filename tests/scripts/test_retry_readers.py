"""Immutable retries are attempts of one trial, not independent observations."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from healthcraft.llm import checkpoint

_ROOT = Path(__file__).resolve().parents[2]


def _module(relative_path: str):
    name = "_retry_reader_" + Path(relative_path).stem
    spec = importlib.util.spec_from_file_location(name, _ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def run_directory(tmp_path):
    category = tmp_path / "trajectories" / "clinical_reasoning"
    category.mkdir(parents=True)
    base = category / "CR-001_ollama:org%2Fmodel_44_t3.json"
    paths = [
        base,
        base.with_stem(base.stem + "_attempt2"),
        base.with_stem(base.stem + "_attempt10"),
    ]
    other = category / "CR-001_ollama:org%2Fmodel_42_t1.json"
    paths.append(other)
    entries = []
    for i, path in enumerate(paths):
        data = {
            "task_id": "CR-001",
            "model": "ollama:org/model",
            "seed": 42 if path == other else 44,
            "reward": 0.0 if i < 2 else 1.0,
            "passed": i >= 2,
            "safety_gate_passed": i >= 2,
            "error": "provider failed" if i < 2 else None,
            "turns": [],
            "criteria_results": [],
            "total_tool_calls": 1,
            "duration_seconds": 1,
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        entries.append({**data, "trajectory_path": str(path.relative_to(tmp_path))})
    (tmp_path / "experiments.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8"
    )
    return tmp_path, base, paths[2], other, entries


def test_shared_reader_selects_numerically_latest_attempt_without_writing(run_directory):
    root, base, latest, other, _ = run_directory
    before = {p: p.read_bytes() for p in root.rglob("*.json")}
    assert checkpoint.selected_trajectory_paths(root) == [other, latest]
    assert checkpoint.selected_trajectory_paths(root / "trajectories") == [other, latest]
    assert checkpoint.selected_trajectory_paths([latest, other, base, latest]) == [other, latest]
    assert {p: p.read_bytes() for p in root.rglob("*.json")} == before


def test_latest_corrupt_attempt_never_falls_back_to_older_score(run_directory):
    root, _, latest, other, _ = run_directory
    latest.write_text("{interrupted", encoding="utf-8")
    assert checkpoint.selected_trajectory_paths(root) == [other, latest]


def test_attempt_grouping_preserves_trial_and_directory_identity(tmp_path):
    first = tmp_path / "one" / "CR-001_m_42_t1.json"
    second = tmp_path / "two" / first.name
    retried = first.with_stem(first.stem + "_attempt2")
    assert checkpoint.selected_trajectory_paths([first, second, retried]) == [retried, second]
    assert checkpoint.trajectory_attempt(retried) == (first, 2)
    assert checkpoint.trajectory_attempt(tmp_path / "model_attempt2_42_t1.json")[1] == 1


def test_latest_summary_is_numeric_and_invalid_latest_is_visible(tmp_path):
    assert checkpoint.load_latest_summary(tmp_path) is None
    (tmp_path / "summary.json").write_text('{"total_runs":1}', encoding="utf-8")
    assert checkpoint.load_latest_summary(tmp_path) == {"total_runs": 1}
    for attempt in (2, 10):
        (tmp_path / f"summary-{attempt}.json").write_text(
            json.dumps({"total_runs": attempt}), encoding="utf-8"
        )
    (tmp_path / "summary-diagnostics.json").write_text("{}", encoding="utf-8")
    assert checkpoint.load_latest_summary(tmp_path) == {"total_runs": 10}
    (tmp_path / "summary-10.json").write_text("{interrupted", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        checkpoint.load_latest_summary(tmp_path)


def test_log_analysis_counts_successful_retry_once(run_directory):
    root, _, latest, other, _ = run_directory
    module = _module("scripts/analyze_results.py")
    entries = module.load_experiments(root)
    assert {entry["trajectory_path"] for entry in entries} == {
        str(path.relative_to(root)) for path in (latest, other)
    }
    result = module.analyze_model(entries, "ollama:org/model")
    assert result["total_trials"] == 2
    assert result["pass_at_1"] == 1.0
    assert result["n_error"] == 0


def test_log_reader_preserves_historical_order_without_retries(tmp_path):
    module = _module("scripts/analyze_results.py")
    entries = [{"task_id": "CR-002"}, {"task_id": "CR-001"}]
    path = tmp_path / "experiments.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    assert module.load_experiments(tmp_path) == entries


def test_retry_replaces_original_log_slot_without_reordering_other_trials(run_directory):
    root, _, latest, other, entries = run_directory
    module = _module("scripts/analyze_results.py")
    # Real retries are appended after the original run's remaining trials.
    entries = [entries[0], entries[3], entries[1], entries[2]]
    (root / "experiments.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8"
    )
    assert [entry["trajectory_path"] for entry in module.load_experiments(root)] == [
        str(path.relative_to(root)) for path in (latest, other)
    ]


@pytest.mark.parametrize("script", ["build_hard", "build_consensus"])
def test_release_builders_select_one_attempt_per_trial(run_directory, script):
    root, _, latest, other, _ = run_directory
    module = _module(f"scripts/{script}.py")
    assert module._iter_trajectory_files([root]) == [other, latest]


@pytest.mark.parametrize("script", ["agreement_report", "rescore_v10", "propose_overlay_entries"])
def test_regrading_selects_one_attempt_per_trial(run_directory, script):
    root, _, latest, other, _ = run_directory
    module = _module(f"scripts/{script}.py")
    assert [path for path, _ in module._collect_trajectories([root])] == [other, latest]


@pytest.mark.parametrize("script", ["agreement_report", "rescore_v10", "propose_overlay_entries"])
@pytest.mark.parametrize("invalid_latest", ["error", "corrupt"])
def test_regrading_never_resurrects_prior_score(run_directory, script, invalid_latest):
    root, base, latest, other, _ = run_directory
    module = _module(f"scripts/{script}.py")
    # Even if a prior artifact appears valid, the latest attempt controls selection.
    base.write_text(other.read_text(encoding="utf-8"), encoding="utf-8")
    latest.write_text(
        '{"error":"provider failed"}' if invalid_latest == "error" else "{interrupted",
        encoding="utf-8",
    )
    assert [path for path, _ in module._collect_trajectories([root])] == [other]


def test_diagnostic_readers_use_latest_attempt_and_summary(run_directory):
    root, base, latest, other, _ = run_directory
    for path in (base, latest, other):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["safety_gate_passed"] = False
        data["criteria_results"] = [
            {
                "criterion_id": "CR-001-C01",
                "satisfied": False,
                "evidence": "Judge: evidence missing",
                "dimension": "safety",
            }
        ]
        path.write_text(json.dumps(data), encoding="utf-8")
    (root / "summary.json").write_text('{"agent_model":"old"}', encoding="utf-8")
    (root / "summary-2.json").write_text('{"agent_model":"current"}', encoding="utf-8")

    reliability = _module("scripts/judge_reliability.py")
    sample = reliability.select_sample([root], sample_size=100)
    assert {entry["trajectory_path"] for entry in sample} == {str(latest), str(other)}
    assert {entry["model"] for entry in sample} == {"current"}

    taxonomy = _module("scripts/safety_taxonomy.py")
    violations = taxonomy.load_safety_violations(
        [root],
        {
            "CR-001-C01": {
                "task_category": "clinical_reasoning",
                "assertion": "Required action",
                "dimension": "safety",
                "failure_type": "omission",
                "verification": "llm_judge",
            }
        },
    )
    assert len(violations) == 2
    assert {entry["model"] for entry in violations} == {"current"}


def test_simple_eval_discovers_selected_attempt_and_keeps_original_trial(run_directory):
    root, _, latest, other, _ = run_directory
    module = _module("evals/healthcraft_simple_eval.py")
    assert module._iter_trajectory_files(root) == [other, latest]
    assert module._parse_trial_from_path(latest) == 3
    assert module._parse_trial_from_path(other) == 1


def test_planner_history_does_not_count_superseded_attempts(run_directory):
    from healthcraft.llm.planner import _load_historical_pass_rates

    root = run_directory[0]
    assert _load_historical_pass_rates(root) == {"CR-001": 1.0}


def test_analysis_main_uses_latest_summary(run_directory, monkeypatch, capsys):
    root = run_directory[0]
    (root / "summary.json").write_text('{"agent_model":"old"}', encoding="utf-8")
    (root / "summary-2.json").write_text('{"agent_model":"current"}', encoding="utf-8")
    module = _module("scripts/analyze_results.py")
    monkeypatch.setattr(sys, "argv", ["analyze_results.py", str(root)])
    module.main()
    report = capsys.readouterr().out
    assert "current" in report
    assert "### old" not in report


def test_standalone_bulk_evaluator_selects_latest_without_paid_calls(run_directory, monkeypatch):
    from healthcraft.llm import evaluator

    root, _, latest, other, _ = run_directory
    seen = []

    def evaluate(path, *_args, **_kwargs):
        seen.append(path)
        return None

    monkeypatch.setattr(evaluator, "create_skeptical_judge", lambda *_args: object())
    monkeypatch.setattr(evaluator, "evaluate_trajectory_file", evaluate)
    monkeypatch.setattr(
        sys,
        "argv",
        ["evaluator", "--trajectory-dir", str(root / "trajectories"), "--judge-key", "fake"],
    )
    evaluator.main()
    assert seen == [other, latest]


def test_full_replay_counts_latest_trial_once_with_generated_sidecars(tmp_path, monkeypatch):
    from healthcraft.tasks.loader import Task

    module = _module("evals/healthcraft_simple_eval.py")
    task = Task(
        id="REPLAY-001",
        category="clinical_reasoning",
        level=1,
        title="Synthetic replay",
        description="Write completed",
        initial_state={},
        expected_tools=(),
        criteria=(
            {
                "id": "REPLAY-001-C01",
                "assertion": "Said completed",
                "verification": "pattern",
                "dimension": "documentation_quality",
                "check": "completed",
            },
        ),
        metadata={},
    )
    monkeypatch.setattr("healthcraft.tasks.loader.load_tasks", lambda _: [task])
    directory = tmp_path / "trajectories" / task.category
    directory.mkdir(parents=True)
    original = directory / "REPLAY-001_model_42_t1.json"
    latest = original.with_stem(original.stem + "_attempt2")
    original.write_text(
        json.dumps({"task_id": task.id, "turns": [], "criteria_results": []}), encoding="utf-8"
    )
    latest.write_text(
        json.dumps(
            {
                "task_id": task.id,
                "model": "model",
                "turns": [{"role": "assistant", "content": "completed"}],
                "criteria_results": [],
            }
        ),
        encoding="utf-8",
    )
    # Standalone grading writes this task-bearing artifact alongside its input.
    latest.with_stem(latest.stem + "_grading").write_text(
        json.dumps(
            {
                "task_id": task.id,
                "agent_model": "model",
                "criteria_results": [],
                "reward": 1.0,
                "passed": True,
            }
        ),
        encoding="utf-8",
    )
    for name in ("summary.json", "summary-2.json", "summary-10.json", "evaluation_summary.json"):
        (directory / name).write_text('{"total_runs":1}', encoding="utf-8")
    before = {path: path.read_bytes() for path in directory.iterdir()}

    verdicts = module._run_replay(
        [module._DatasetTask(task.id, task.category, task.criteria)],
        tmp_path,
        rubric_channel="v8",
        trials=1,
        limit=None,
    )

    assert [(verdict.trial, verdict.reward, verdict.passed) for verdict in verdicts] == [
        (1, 1.0, True)
    ]
    assert checkpoint.selected_trajectory_paths(tmp_path) == [latest]
    assert checkpoint.selected_trajectory_paths(list(directory.iterdir())) == [latest]
    assert {path: path.read_bytes() for path in directory.iterdir()} == before


def test_sidecar_filter_preserves_legacy_and_similarly_named_trajectories(tmp_path):
    paths = [
        tmp_path / "legacy-unconventional.json",
        tmp_path / "CR-001_summary_model_42_t1.json",
        tmp_path / "CR-001_model_grading_42_t1.json",
        tmp_path / "summary-model.json",
    ]
    assert checkpoint.selected_trajectory_paths(paths) == sorted(paths)


def test_experiment_entry_selection_handles_excluded_sidecars():
    trajectory = {"task_id": "CR-001", "trajectory_path": "CR-001_m_42_t1.json"}
    grading = {"task_id": "CR-001", "trajectory_path": "CR-001_m_42_t1_grading.json"}
    assert checkpoint.selected_experiment_entries([trajectory, grading]) == [trajectory]
