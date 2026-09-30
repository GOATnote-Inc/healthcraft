"""Resume must never silently relabel a previous experiment as a new one."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from healthcraft.llm import orchestrator as orch
from healthcraft.tasks.loader import Task
from healthcraft.trajectory import Trajectory
from healthcraft.world.state import WorldState


@pytest.fixture
def harness(monkeypatch, tmp_path):
    task = Task(
        id="TEST-001",
        category="clinical_reasoning",
        level=1,
        title="Synthetic",
        description="Retrieve the encounter",
        initial_state={},
        expected_tools=(),
        criteria=(
            {
                "id": "C1",
                "assertion": "Retrieved encounter",
                "verification": "world_state",
                "dimension": "clinical_completeness",
                "check": "audit_log contains call to getEncounterDetails",
            },
        ),
        metadata={},
    )
    state = {"task": task, "prompt": "Synthetic test only", "calls": 0, "error": False}
    monkeypatch.setattr(orch, "load_tasks", lambda _, **kwargs: [state["task"]])
    state["endpoint"] = "http://localhost:30000/v1"
    monkeypatch.setattr(
        orch,
        "create_client",
        lambda *a, **k: SimpleNamespace(
            _model="served-model",
            _base_url=state["endpoint"],
        ),
    )
    monkeypatch.setattr(orch, "_load_system_prompt", lambda _: state["prompt"])
    monkeypatch.setattr(orch, "_load_overlay", lambda _: {})
    monkeypatch.setattr(orch, "environment_digest", lambda _: "fixed-environment-for-unit-tests")
    monkeypatch.setattr(orch.WorldSeeder, "seed_world", lambda *a: WorldState())

    def run_agent(*args, **kwargs):
        state["calls"] += 1
        if state["error"] == "returned":
            trajectory = Trajectory(
                task_id=state["task"].id,
                model="test",
                seed=42,
                system_prompt=state["prompt"],
                error="late API error",
            )
            trajectory.add_turn("assistant", "completed")
            return trajectory
        if state["error"]:
            raise RuntimeError("synthetic runtime failure")
        return Trajectory(
            task_id=state["task"].id, model="test", seed=42, system_prompt=state["prompt"]
        )

    monkeypatch.setattr(orch, "run_agent_task", run_agent)

    def run(**changes):
        opts = dict(
            agent_model="gpt-test",
            agent_key="unused",
            judge_model="claude-test",
            judge_key=None,
            trials=1,
            rubric_channel="v10",
            results_dir=tmp_path,
        )
        opts.update(changes)
        return orch.run_frontier_evaluation(**opts)

    return state, run, tmp_path


def snapshot(root: Path):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_identical_resume_is_read_only(harness):
    state, run, root = harness
    first = run()
    before = snapshot(root)
    second = run()
    assert second == first
    assert state["calls"] == 1
    assert snapshot(root) == before


@pytest.mark.parametrize(
    "change", ["channel", "dynamic", "judge", "task", "prompt", "legacy", "endpoint"]
)
def test_incompatible_checkpoint_refused_without_overwrite(harness, change):
    state, run, root = harness
    run()
    kwargs = {}
    if change == "channel":
        kwargs["rubric_channel"] = "v8"
    elif change == "dynamic":
        kwargs["dynamic_state"] = True
    elif change == "judge":
        kwargs["judge_key"] = "stub-judge"
    elif change == "task":
        state["task"] = replace(state["task"], description="Different task")
    elif change == "prompt":
        state["prompt"] = "Changed prompt"
    elif change == "endpoint":
        state["endpoint"] = "http://localhost:30001/v1"
    elif change == "legacy":
        path = next(root.rglob("TEST-001*.json"))
        trajectory = Trajectory.load(path)
        trajectory.metadata.clear()
        trajectory.save(path)
    before = snapshot(root)
    result = run(**kwargs)
    assert "error" in result, "incompatible scores must not be reported as current results"
    assert "checkpoint" in result["error"].lower()
    assert state["calls"] == 1
    assert snapshot(root) == before


def test_corrupt_checkpoint_preserved_for_diagnosis(harness):
    state, run, root = harness
    run()
    next(root.rglob("TEST-001*.json")).write_text("{interrupted")
    before = snapshot(root)
    result = run()
    assert "error" in result
    assert state["calls"] == 1
    assert snapshot(root) == before


def test_error_resume_preserves_fail_closed_accounting(harness):
    state, run, root = harness
    state["error"] = True
    first = run()
    second = run()
    assert first == second
    assert second["error_runs"] == 1
    assert second["safety_failures"] == 1
    assert second["safety_failures_excl_errors"] == 0
    assert not Trajectory.load(next(root.rglob("TEST-001*.json"))).safety_gate_passed


def test_partial_agent_error_is_not_scored_as_success_and_trace_survives(harness):
    state, run, root = harness
    state["error"] = "returned"
    state["task"] = replace(
        state["task"],
        criteria=(
            {
                "id": "C1",
                "assertion": "Said completed",
                "verification": "pattern",
                "dimension": "documentation_quality",
                "check": "completed",
            },
        ),
    )
    result = run()
    assert result["error_runs"] == 1
    assert result["total_passed"] == 0
    assert result["avg_reward"] == 0
    trajectory = Trajectory.load(next(root.rglob("TEST-001*.json")))
    assert trajectory.error == "late API error"
    assert trajectory.turns[0].content == "completed"
    assert run() == result


def test_retry_errors_appends_new_attempt_without_replacing_original(harness):
    state, run, root = harness
    state["error"] = True
    run()
    before = snapshot(root)
    state["error"] = False
    result = run(retry_errors=True)
    assert "error" not in result
    assert result["error_runs"] == 0
    assert state["calls"] == 2
    after = snapshot(root)
    for path, contents in before.items():
        if path != "experiments.jsonl":
            assert after[path] == contents
    assert after["experiments.jsonl"].startswith(before["experiments.jsonl"])
    assert len(list(root.rglob("TEST-001*.json"))) == 2
    assert run() == result
    assert state["calls"] == 2


def test_logging_failure_does_not_replace_saved_trajectory(harness, monkeypatch):
    state, run, root = harness

    def fail_append(*args):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(orch.ExperimentLog, "append", fail_append)
    result = run()
    assert "error" in result
    trajectory = Trajectory.load(next(root.rglob("TEST-001*.json")))
    assert trajectory.error is None
    assert trajectory.system_prompt == state["prompt"]


def test_resume_repairs_missing_experiment_log_from_saved_trajectory(harness):
    state, run, root = harness
    result = run()
    (root / "experiments.jsonl").unlink()
    assert run() == result
    assert state["calls"] == 1
    assert len((root / "experiments.jsonl").read_text().splitlines()) == 1


def test_retry_attempt_numbers_increase_even_when_an_older_attempt_is_missing(tmp_path):
    from healthcraft.llm.checkpoint import next_attempt

    path = tmp_path / "trial.json"
    path.write_text("original")
    (tmp_path / "trial_attempt3.json").write_text("latest")
    assert next_attempt(path).name == "trial_attempt4.json"


def test_exclusive_checkpoint_write_cannot_replace_evidence(tmp_path):
    from healthcraft.llm.checkpoint import save_checkpoint

    path = tmp_path / "existing.json"
    path.write_text("immutable evidence")
    with pytest.raises(FileExistsError):
        save_checkpoint(Trajectory(task_id="T", model="M", seed=42, system_prompt=""), path)
    assert path.read_text() == "immutable evidence"


def test_no_judge_reports_missing_grading_coverage(harness):
    state, run, root = harness
    state["task"] = replace(
        state["task"],
        criteria=(
            {
                "id": "C1",
                "assertion": "Reasoned correctly",
                "verification": "llm_judge",
                "dimension": "clinical_correctness",
            },
        ),
    )
    result = run()
    assert result["evaluation_mode"] == "deterministic_only"
    assert result["ungraded_criteria"] == 1
    assert result["grading_complete"] is False
    trajectory = Trajectory.load(next(root.rglob("TEST-001*.json")))
    assert trajectory.metadata["grading_complete"] is False
    assert trajectory.metadata["ungraded_criteria"] == 1


def test_dynamic_setup_failure_preserves_error_checkpoint_not_physiology(harness, monkeypatch):
    state, run, root = harness
    state["task"] = replace(state["task"], initial_state={"clinical_trajectory": "sepsis"})
    state["error"] = True
    monkeypatch.setattr(
        orch,
        "prepare_task_environment",
        lambda world, task, **kwargs: (task, {"patient_id": "PAT-SYNTHETIC"}),
    )
    result = run(dynamic_state=True)
    assert result["error_runs"] == 1
    trajectory = Trajectory.load(next(root.rglob("TEST-001*.json")))
    assert "synthetic runtime failure" in trajectory.error
    assert trajectory.metadata["failure_stage"] == "agent"
    assert trajectory.metadata["grading_complete"] is False
    assert trajectory.metadata["ungraded_criteria"] == 1
    assert trajectory.metadata["review_context"]["payload"]["capture_status"] == "incomplete"


def test_judge_error_preserves_rollout_and_counts_as_infrastructure_failure(harness, monkeypatch):
    from healthcraft.tasks.rubrics import CriterionResult

    state, run, root = harness
    state["task"] = replace(
        state["task"],
        criteria=(
            {
                "id": "C1",
                "assertion": "Reasoned correctly",
                "verification": "llm_judge",
                "dimension": "clinical_correctness",
            },
        ),
    )
    monkeypatch.setattr(
        orch.LLMJudge,
        "evaluate_criteria",
        lambda *a: [
            CriterionResult(
                criterion_id="C1",
                satisfied=False,
                evidence="Judge error: unavailable",
                error="unavailable",
            ),
        ],
    )
    result = run(judge_key="stub-judge")
    assert result["error_runs"] == 1
    assert result["safety_failures_excl_errors"] == 0
    trajectory = Trajectory.load(next(root.rglob("TEST-001*.json")))
    assert trajectory.error and "unavailable" in trajectory.error
    assert trajectory.system_prompt == state["prompt"]
    assert trajectory.metadata["failure_stage"] == "grader"


def test_environment_identity_changes_with_grading_vocabulary(tmp_path, monkeypatch):
    from healthcraft.llm.checkpoint import environment_digest

    monkeypatch.setattr(orch.WorldSeeder, "_load_openem_conditions", lambda: None)
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs/mcp-tools.json").write_text("{}")
    vocabulary = tmp_path / "configs/em_vocab.yaml"
    vocabulary.write_text("drug: heparin")
    before = environment_digest(tmp_path)
    vocabulary.write_text("drug: warfarin")
    assert environment_digest(tmp_path) != before


def test_summary_can_return_to_an_earlier_value_without_stale_latest(tmp_path):
    from healthcraft.llm.checkpoint import load_latest_summary, save_summary

    save_summary(tmp_path, {"reward": 0})
    save_summary(tmp_path, {"reward": 1})
    save_summary(tmp_path, {"reward": 0})
    assert load_latest_summary(tmp_path) == {"reward": 0}
    assert len(list(tmp_path.glob("summary*.json"))) == 3


def test_summary_numbering_never_reuses_gap(tmp_path):
    from healthcraft.llm.checkpoint import load_latest_summary, save_summary

    (tmp_path / "summary-3.json").write_text('{"reward": 1}')
    save_summary(tmp_path, {"reward": 0})
    assert (tmp_path / "summary-4.json").exists()
    assert load_latest_summary(tmp_path) == {"reward": 0}


def test_environment_identity_includes_effective_idempotency_flag(tmp_path, monkeypatch):
    from healthcraft.llm.checkpoint import environment_digest

    monkeypatch.setattr(orch.WorldSeeder, "_load_openem_conditions", lambda: None)
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs/mcp-tools.json").write_text("{}")
    monkeypatch.setenv("HC_IDEMPOTENT_TOOLS", "1")
    enabled = environment_digest(tmp_path)
    monkeypatch.setenv("HC_IDEMPOTENT_TOOLS", "0")
    assert environment_digest(tmp_path) != enabled
