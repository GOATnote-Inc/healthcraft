"""Contract tests for ``scripts/build_hard.py``.

No API calls, no real trajectories touched. Synthetic trajectories are
written into ``tmp_path``; the script walks them, computes per-task mean
reward, and selects the bottom ``--quantile`` subset.

Covers:

1. Bottom-quantile selection by ascending mean_reward.
2. Min-trials gate: a task with too few non-error trials lands in
   ``dropped_tasks`` with reason ``insufficient_trials``.
3. Error trajectories (``error`` field set) are excluded from the mean.
4. Deterministic tiebreak: equal mean_reward -> pass_rate asc -> task_id lex.
5. Manifest schema: ``version`` / ``stats`` / ``dropped_tasks`` keys.
6. Hardness gate exit code: all-fail HARD -> exit 0, mid-pass HARD -> exit 1.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "build_hard.py"


def _load_build_hard():
    """Import ``scripts/build_hard.py`` as a module."""
    sys.path.insert(0, str(_REPO / "src"))
    spec = importlib.util.spec_from_file_location("_build_hard", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register BEFORE exec so dataclass decorators resolve (Python 3.14).
    sys.modules["_build_hard"] = module
    spec.loader.exec_module(module)
    return module


bh = _load_build_hard()


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


_DEFAULT_MODELS = ("claude-opus-4-6", "gpt-5.4", "gemini-3.1-pro")


def _write_task_yaml(tasks_dir: Path, task_id: str, n_criteria: int = 3) -> None:
    """Emit a minimal task YAML. Category derived from task_id prefix."""
    prefix = task_id.split("-", 1)[0]
    category_map = {
        "CR": "clinical_reasoning",
        "MW": "multi_step_workflows",
        "IR": "information_retrieval",
        "CC": "clinical_communication",
        "SJ": "safety_critical_judgment",
        "TR": "temporal_reasoning",
    }
    category = category_map.get(prefix, "clinical_reasoning")
    criteria = []
    for i in range(n_criteria):
        criteria.append(
            {
                "id": f"{task_id}-C{i + 1:02d}",
                "assertion": f"criterion {i + 1}",
                "dimension": "clinical_correctness",
                "verification": "world_state",
                "safety_critical": i == 0,
            }
        )
    payload = {
        "id": task_id,
        "category": category,
        "level": 3,
        "title": f"Fixture task {task_id}",
        "description": "Fixture task for hard contract test.",
        "criteria": criteria,
    }
    tasks_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / f"{task_id}.yaml").write_text(yaml.safe_dump(payload))


def _write_trajectory(
    results_dir: Path,
    *,
    task_id: str,
    model: str,
    trial: int,
    reward: float,
    passed: bool | None = None,
    safety_gate_passed: bool = True,
    error: str | None = None,
) -> Path:
    """Write one synthetic trajectory JSON file and return its path."""
    tdir = results_dir / "trajectories" / "fixture"
    tdir.mkdir(parents=True, exist_ok=True)
    path = tdir / f"{task_id}_{model}_42_t{trial}.json"
    # Default passed := reward >= 1.0 (mimicking Eq. 1 + safety gate).
    if passed is None:
        passed = reward >= 1.0 and safety_gate_passed
    payload: dict = {
        "task_id": task_id,
        "model": model,
        "seed": 42,
        "turns": [],
        "criteria_results": [],
        "reward": reward,
        "passed": passed,
        "safety_gate_passed": safety_gate_passed,
    }
    if error is not None:
        payload["error"] = error
    path.write_text(json.dumps(payload))
    return path


def _build_fixture(
    tmp_path: Path,
    *,
    task_rewards: dict[str, list[tuple[str, float, bool]]],
    n_criteria: int = 3,
) -> tuple[Path, Path]:
    """Materialise tasks + trajectories.

    Args:
        tmp_path: Fixture root.
        task_rewards: ``{task_id: [(model, reward, passed), ...]}``. Each tuple
            becomes one trajectory; trial numbers are auto-assigned per-model.

    Returns:
        ``(tasks_dir, results_dir)``.
    """
    tasks_dir = tmp_path / "tasks"
    results_dir = tmp_path / "pilot"
    trial_counters: dict[tuple[str, str], int] = {}
    for task_id, trials in task_rewards.items():
        _write_task_yaml(tasks_dir, task_id, n_criteria=n_criteria)
        for model, reward, passed in trials:
            key = (task_id, model)
            trial_counters[key] = trial_counters.get(key, 0) + 1
            _write_trajectory(
                results_dir,
                task_id=task_id,
                model=model,
                trial=trial_counters[key],
                reward=reward,
                passed=passed,
            )
    return tasks_dir, results_dir


def _run(
    tasks_dir: Path,
    results_dir: Path,
    *,
    output: Path,
    manifest: Path,
    quantile: float = 0.20,
    min_trials: int = 6,
) -> int:
    """Invoke the CLI with standard flags and return the exit code."""
    return bh.main(
        [
            "--results",
            str(results_dir),
            "--quantile",
            str(quantile),
            "--min-trials-per-task",
            str(min_trials),
            "--output",
            str(output),
            "--manifest",
            str(manifest),
            "--tasks-dir",
            str(tasks_dir),
        ]
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBottomQuantileSelection:
    def test_bottom_quantile_selection(self, tmp_path: Path) -> None:
        """10 tasks, quantile=0.20 -> 2 HARD tasks, hardest first."""
        task_rewards: dict[str, list[tuple[str, float, bool]]] = {}
        # Task CR-010 is hardest (reward 0.0), CR-001 is easiest (reward 0.9).
        # Means distributed 0.9, 0.8, ..., 0.0 across 10 tasks.
        for i in range(1, 11):
            task_id = f"CR-{i:03d}"
            r = (10 - i) / 10.0  # 0.9, 0.8, ..., 0.0
            trials = [(m, r, r >= 1.0) for m in _DEFAULT_MODELS for _ in range(3)]
            task_rewards[task_id] = trials

        tasks_dir, results_dir = _build_fixture(tmp_path, task_rewards=task_rewards)
        output = tmp_path / "out" / "hard.jsonl"
        manifest = tmp_path / "out" / "hard.yaml"
        exit_code = _run(tasks_dir, results_dir, output=output, manifest=manifest)

        assert exit_code == 0  # all HARD tasks fail -> under 35% pass -> gate passes
        lines = [json.loads(line) for line in output.read_text().splitlines() if line.strip()]
        assert len(lines) == 2
        assert lines[0]["task_id"] == "CR-010"
        assert lines[0]["rank"] == 1
        assert lines[1]["task_id"] == "CR-009"
        assert lines[1]["rank"] == 2
        assert lines[0]["mean_reward"] == pytest.approx(0.0)
        assert lines[1]["mean_reward"] == pytest.approx(0.1)


class TestMinTrialsDropsTask:
    def test_min_trials_drops_task(self, tmp_path: Path) -> None:
        """Task with 3 trials (< 6) is dropped with reason insufficient_trials."""
        task_rewards: dict[str, list[tuple[str, float, bool]]] = {}
        # 5 well-covered tasks (9 trials each)
        for i in range(1, 6):
            task_id = f"CR-{i:03d}"
            trials = [(m, 0.5, False) for m in _DEFAULT_MODELS for _ in range(3)]
            task_rewards[task_id] = trials
        # One under-covered task (3 trials, one model)
        task_rewards["CR-099"] = [(_DEFAULT_MODELS[0], 0.0, False)] * 3

        tasks_dir, results_dir = _build_fixture(tmp_path, task_rewards=task_rewards)
        output = tmp_path / "out" / "hard.jsonl"
        manifest = tmp_path / "out" / "hard.yaml"
        _run(tasks_dir, results_dir, output=output, manifest=manifest, quantile=0.20)

        manifest_data = yaml.safe_load(manifest.read_text())
        dropped = {d["task_id"]: d for d in manifest_data["dropped_tasks"]}
        assert "CR-099" in dropped
        assert dropped["CR-099"]["reason"] == "insufficient_trials"
        assert dropped["CR-099"]["n_trials"] == 3

        # And CR-099 must NOT appear in the JSONL subset.
        lines = [json.loads(line) for line in output.read_text().splitlines() if line.strip()]
        assert not any(entry["task_id"] == "CR-099" for entry in lines)


class TestErrorTrajectoriesExcluded:
    def test_error_trajectories_excluded(self, tmp_path: Path) -> None:
        """A trajectory with an error field is not counted in mean_reward."""
        tasks_dir = tmp_path / "tasks"
        results_dir = tmp_path / "pilot"
        # CR-001 is the hardest task: 6 good trials at reward 0.2 + 1 error
        # trajectory (reward 0). Mean without error = 0.2 exactly; if the
        # error were counted, the mean would drop to ~0.171.
        _write_task_yaml(tasks_dir, "CR-001")
        for trial, model in enumerate(
            [m for m in _DEFAULT_MODELS for _ in range(2)],
            start=1,
        ):
            _write_trajectory(
                results_dir,
                task_id="CR-001",
                model=model,
                trial=trial,
                reward=0.2,
                passed=False,
            )
        _write_trajectory(
            results_dir,
            task_id="CR-001",
            model="claude-opus-4-6",
            trial=99,
            reward=0.0,
            passed=False,
            error="APITimeout",
        )
        # A second eligible (easier) task so CR-001 lands in the bottom
        # quantile rather than trivially-all.
        _write_task_yaml(tasks_dir, "CR-002")
        for trial, model in enumerate(
            [m for m in _DEFAULT_MODELS for _ in range(2)],
            start=1,
        ):
            _write_trajectory(
                results_dir,
                task_id="CR-002",
                model=model,
                trial=trial,
                reward=0.8,
                passed=False,
            )

        output = tmp_path / "out" / "hard.jsonl"
        manifest = tmp_path / "out" / "hard.yaml"
        _run(tasks_dir, results_dir, output=output, manifest=manifest, quantile=0.5)

        manifest_data = yaml.safe_load(manifest.read_text())
        assert manifest_data["stats"]["trajectories_error"] == 1

        lines = [json.loads(line) for line in output.read_text().splitlines() if line.strip()]
        entries = {entry["task_id"]: entry for entry in lines}
        # CR-001 is the hardest; mean_reward should be 0.2 exactly on 6 non-error trials.
        assert "CR-001" in entries
        assert entries["CR-001"]["n_trials"] == 6
        assert entries["CR-001"]["mean_reward"] == pytest.approx(0.2)


class TestTiebreakDeterministic:
    def test_tiebreak_deterministic(self, tmp_path: Path) -> None:
        """Two tasks with identical mean_reward: tiebreak by pass_rate asc, then task_id lex."""
        task_rewards: dict[str, list[tuple[str, float, bool]]] = {}
        # Two tied-reward tasks (mean 0.0) at the bottom.
        # CR-001: 6 trials, all reward=0.0, passed=False -> pass_rate=0.0
        # CR-002: 6 trials, all reward=0.0, passed=False -> pass_rate=0.0
        # Same everything -> fall through to task_id asc -> CR-001 first.
        for tid in ("CR-002", "CR-001"):  # intentionally reversed
            task_rewards[tid] = [(m, 0.0, False) for m in _DEFAULT_MODELS for _ in range(2)]
        # Two stronger tasks so quantile selection still only grabs ~bottom 2.
        for tid in ("CR-003", "CR-004"):
            task_rewards[tid] = [(m, 0.8, False) for m in _DEFAULT_MODELS for _ in range(2)]

        tasks_dir, results_dir = _build_fixture(tmp_path, task_rewards=task_rewards)
        output = tmp_path / "out" / "hard.jsonl"
        manifest = tmp_path / "out" / "hard.yaml"
        _run(tasks_dir, results_dir, output=output, manifest=manifest, quantile=0.50)

        lines = [json.loads(line) for line in output.read_text().splitlines() if line.strip()]
        assert len(lines) == 2
        # Both have identical mean_reward AND pass_rate; tiebreak is task_id asc.
        assert lines[0]["task_id"] == "CR-001"
        assert lines[1]["task_id"] == "CR-002"

    def test_tiebreak_pass_rate(self, tmp_path: Path) -> None:
        """Two tasks with identical mean_reward but different pass_rate: lower pass_rate wins."""
        task_rewards: dict[str, list[tuple[str, float, bool]]] = {}
        # CR-A: 6 trials, reward=0.5; half-pass, half-fail -> pass_rate=0.5.
        task_rewards["CR-A"] = [
            (_DEFAULT_MODELS[0], 0.5, True),
            (_DEFAULT_MODELS[0], 0.5, True),
            (_DEFAULT_MODELS[0], 0.5, True),
            (_DEFAULT_MODELS[1], 0.5, False),
            (_DEFAULT_MODELS[1], 0.5, False),
            (_DEFAULT_MODELS[1], 0.5, False),
        ]
        # CR-B: 6 trials, reward=0.5, all failing -> pass_rate=0.0.
        task_rewards["CR-B"] = [(m, 0.5, False) for m in _DEFAULT_MODELS for _ in range(2)]
        # Filler tasks to move selection window.
        task_rewards["CR-C"] = [(m, 0.9, False) for m in _DEFAULT_MODELS for _ in range(2)]
        task_rewards["CR-D"] = [(m, 0.9, False) for m in _DEFAULT_MODELS for _ in range(2)]

        tasks_dir, results_dir = _build_fixture(tmp_path, task_rewards=task_rewards)
        output = tmp_path / "out" / "hard.jsonl"
        manifest = tmp_path / "out" / "hard.yaml"
        _run(tasks_dir, results_dir, output=output, manifest=manifest, quantile=0.50)

        lines = [json.loads(line) for line in output.read_text().splitlines() if line.strip()]
        assert len(lines) == 2
        # CR-B (pass_rate 0.0) should come before CR-A (pass_rate 0.5).
        assert lines[0]["task_id"] == "CR-B"
        assert lines[1]["task_id"] == "CR-A"


class TestManifestSchema:
    def test_manifest_schema(self, tmp_path: Path) -> None:
        """Manifest exposes version, stats, dropped_tasks."""
        task_rewards: dict[str, list[tuple[str, float, bool]]] = {}
        for i in range(1, 6):
            tid = f"CR-{i:03d}"
            task_rewards[tid] = [(m, 0.5, False) for m in _DEFAULT_MODELS for _ in range(2)]

        tasks_dir, results_dir = _build_fixture(tmp_path, task_rewards=task_rewards)
        output = tmp_path / "out" / "hard.jsonl"
        manifest = tmp_path / "out" / "hard.yaml"
        _run(tasks_dir, results_dir, output=output, manifest=manifest)

        manifest_data = yaml.safe_load(manifest.read_text())
        assert manifest_data["version"] == 1
        assert "generated_at" in manifest_data
        assert "stats" in manifest_data
        assert "dropped_tasks" in manifest_data
        stats = manifest_data["stats"]
        assert "n_tasks_total" in stats
        assert "n_eligible" in stats
        assert "n_hard" in stats
        assert "threshold_mean_reward" in stats
        assert "overall_frontier_pass_rate_on_hard" in stats
        assert "by_category" in stats
        inputs = manifest_data["inputs"]
        assert inputs["quantile"] == 0.20
        assert inputs["min_trials_per_task"] == 6
        assert "results_dirs" in inputs


class TestHardnessGateExitCode:
    def test_hardness_gate_all_fail_exits_zero(self, tmp_path: Path) -> None:
        """All frontier pass rate = 0.0 on HARD -> script exits 0."""
        task_rewards: dict[str, list[tuple[str, float, bool]]] = {}
        for i in range(1, 6):
            tid = f"CR-{i:03d}"
            task_rewards[tid] = [(m, 0.0, False) for m in _DEFAULT_MODELS for _ in range(2)]

        tasks_dir, results_dir = _build_fixture(tmp_path, task_rewards=task_rewards)
        output = tmp_path / "out" / "hard.jsonl"
        manifest = tmp_path / "out" / "hard.yaml"
        exit_code = _run(tasks_dir, results_dir, output=output, manifest=manifest)
        assert exit_code == 0
        manifest_data = yaml.safe_load(manifest.read_text())
        assert manifest_data["stats"]["overall_frontier_pass_rate_on_hard"] == pytest.approx(0.0)

    def test_hardness_gate_passes_exits_one(self, tmp_path: Path) -> None:
        """Mean pass rate = 0.50 on HARD -> script exits 1 (too easy)."""
        task_rewards: dict[str, list[tuple[str, float, bool]]] = {}
        # Even the "hard" tail has 50% pass rate -> gate fails.
        for i in range(1, 6):
            tid = f"CR-{i:03d}"
            trials: list[tuple[str, float, bool]] = []
            # 3 passing, 3 failing per task across models.
            for m in _DEFAULT_MODELS:
                trials.append((m, 1.0, True))
                trials.append((m, 0.0, False))
            task_rewards[tid] = trials

        tasks_dir, results_dir = _build_fixture(tmp_path, task_rewards=task_rewards)
        output = tmp_path / "out" / "hard.jsonl"
        manifest = tmp_path / "out" / "hard.yaml"
        exit_code = _run(tasks_dir, results_dir, output=output, manifest=manifest)
        assert exit_code == 1
        manifest_data = yaml.safe_load(manifest.read_text())
        assert manifest_data["stats"]["overall_frontier_pass_rate_on_hard"] == pytest.approx(0.5)
