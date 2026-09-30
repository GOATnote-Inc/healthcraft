"""Unassessed scripted smoke runner; this module does not evaluate any model.

Each task's advertised expected tools are attempted with empty parameters to
exercise local handlers. Returned errors are smoke evidence, not clinical
failures. For actual models use ``python -m healthcraft.llm.orchestrator``.

Usage:
    python -m healthcraft.eval_runner --tasks CR-001 --model simulated \
        --results-dir /tmp/new-healthcraft-smoke
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from healthcraft.mcp.server import create_server
from healthcraft.tasks.loader import Task, load_task
from healthcraft.tasks.prompts import compose_system_prompt
from healthcraft.trajectory import ExperimentEntry, ExperimentLog, Trajectory
from healthcraft.world.seed import WorldSeeder

logger = logging.getLogger("healthcraft.simulation")
_TASKS_DIR = Path(__file__).resolve().parents[2] / "configs/tasks"
_RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs/world/mercy_point_v1.yaml"
_SYSTEM_PROMPT_DIR = Path(__file__).resolve().parents[2] / "system-prompts"


def load_system_prompt(task: Task) -> str:
    """Compose the task prompt for provenance; it is not sent to a model."""
    return compose_system_prompt(task, _SYSTEM_PROMPT_DIR, ("base.txt",))


def _validate_options(model: str, seed: int, count: int, name: str) -> None:
    if model != "simulated":
        raise ValueError(
            "Only model='simulated' is supported; use healthcraft.llm.orchestrator for models"
        )
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if type(count) is not int or count <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _validate_task(task: Task) -> None:
    for name in ("id", "category"):
        value = getattr(task, name)
        if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value):
            raise ValueError(f"Task {name} is not a safe output path component")
    if not all(type(name) is str and name.strip() for name in task.expected_tools):
        raise ValueError("Expected tool names must be nonempty strings")


def _unassessed(criteria: int) -> dict[str, Any]:
    return {
        "evaluation_mode": "simulation_diagnostic",
        "grading_complete": False,
        "benchmark_comparable": False,
        "benchmark_score": None,
        "ungraded_criteria": criteria,
        "model_calls": 0,
    }


def run_task_locally(
    task: Task,
    seed: int = 42,
    *,
    trajectory: Trajectory | None = None,
) -> tuple[dict[str, Any], Any]:
    """Attempt the listed tools with empty parameters, preserving actual receipts.

    This does not inject/solve the clinical task or call a model. Incremental
    trajectory capture keeps earlier responses and a pending request when a
    later handler or response serialization fails.
    """
    world = WorldSeeder(seed=seed).seed_world(_CONFIG_PATH)
    server = create_server(world)
    calls: list[str] = []
    responses: list[dict[str, Any]] = []
    for index, name in enumerate(task.expected_tools, 1):
        identifier = f"simulation-call-{index}"
        if trajectory is not None:
            trajectory.metadata["failure_stage"] = "tool_execution"
            trajectory.metadata["tool_outcome"] = "unknown"
            trajectory.add_turn(
                "assistant", tool_calls=[{"id": identifier, "name": name, "params": {}}]
            )
        response = server.call_tool(name, {})
        # Strict serialization retains actual JSON rather than inventing an error response.
        encoded = json.dumps(response, ensure_ascii=False, sort_keys=True, allow_nan=False)
        encoded.encode("utf-8")
        if trajectory is not None:
            trajectory.add_turn("tool", encoded, tool_call_id=identifier)
        calls.append(name)
        responses.append(json.loads(encoded))
        if type(response) is not dict or response.get("status") not in ("ok", "error"):
            raise ValueError(f"Invalid tool response from {name}")
        if trajectory is not None and response["status"] == "error":
            trajectory.metadata["tool_errors"].append(
                {"tool": name, "call_id": identifier, "code": response.get("code")}
            )
    return {"tool_calls": calls, "responses": responses}, server.world_state


def _trajectory_path(task: Task, seed: int, trial: int, results_dir: Path) -> Path:
    return (
        results_dir / "trajectories" / task.category / f"{task.id}_simulated_{seed}_t{trial}.json"
    )


def evaluate_and_capture(
    task: Task,
    model: str,
    seed: int,
    trial: int,
    results_dir: Path,
) -> Trajectory:
    """Capture one exclusive unassessed simulation, never a benchmark verdict."""
    _validate_options(model, seed, trial, "trial")
    _validate_task(task)
    traj = Trajectory(
        task_id=task.id,
        model="simulated",
        seed=seed,
        system_prompt="",
        reward=None,
        passed=None,
        safety_gate_passed=None,
        metadata={
            **_unassessed(len(task.criteria)),
            "trial": trial,
            "category": task.category,
            "level": task.level,
            "title": task.title,
            "simulation_completed": False,
            "tool_errors": [],
            "failure_stage": "prompt_setup",
            "scope": "Scripted empty-parameter tool attempts; no model or clinical assessment",
        },
    )
    path = _trajectory_path(task, seed, trial, results_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Reserve before execution so a collision never repeats side effects.
    with path.open("x", encoding="utf-8") as stream:
        start = time.monotonic()
        try:
            prompt = load_system_prompt(task)
            traj.system_prompt = prompt
            traj.add_turn("system", prompt)
            traj.add_turn("user", task.description)
            traj.metadata["failure_stage"] = "simulation_setup"
            run_task_locally(task, seed=seed, trajectory=traj)
            traj.metadata["simulation_completed"] = True
            traj.metadata.pop("tool_outcome", None)
            if traj.metadata["tool_errors"]:
                traj.error = (
                    f"{len(traj.metadata['tool_errors'])} scripted tool response(s) reported errors"
                )
                traj.metadata["failure_stage"] = "tool_response"
            else:
                traj.metadata.pop("failure_stage", None)
            traj.add_turn("assistant", "Scripted smoke attempts finished; no model was evaluated.")
        except Exception as exc:
            logger.error("Simulation %s trial %d failed: %s", task.id, trial, exc)
            traj.error = f"{type(exc).__name__}: {exc}"
        traj.duration_seconds = time.monotonic() - start
        json.dump(traj.to_dict(), stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return traj


def _select_tasks(task_filter: str, tasks_dir: Path) -> list[Task]:
    if type(task_filter) is not str or not task_filter or task_filter != task_filter.strip():
        raise ValueError("Task selection must be 'all' or one exact task ID")
    if not tasks_dir.is_dir():
        raise ValueError(f"Task directory not found: {tasks_dir}")
    tasks = []
    identifiers: set[str] = set()
    for path in sorted(tasks_dir.rglob("*")):
        if not path.is_file() or path.suffix not in (".yaml", ".yml"):
            continue
        # A malformed authored task cannot disappear from an 'all' denominator.
        try:
            task = load_task(path)
            _validate_task(task)
        except Exception as exc:
            raise ValueError(f"Invalid task file {path}: {exc}") from exc
        if task.id in identifiers:
            raise ValueError(f"Duplicate task ID: {task.id}")
        identifiers.add(task.id)
        if task_filter == "all" or task.id == task_filter:
            tasks.append(task)
    if not tasks:
        raise ValueError(f"No tasks found: {task_filter}")
    return sorted(tasks, key=lambda task: task.id)


def run_evaluation(
    task_filter: str,
    model: str,
    trials: int,
    seed: int,
    results_dir: Path,
    tasks_dir: Path,
) -> dict[str, Any]:
    """Run a declared simulation cohort in a new directory, retaining failures."""
    _validate_options(model, seed, trials, "trials")
    tasks = _select_tasks(task_filter, tasks_dir)
    results_dir.mkdir(parents=True, exist_ok=False)
    exp_log = ExperimentLog(results_dir / "experiments.jsonl")
    total_runs = execution_errors = tool_error_runs = 0
    for task in tasks:
        for trial in range(1, trials + 1):
            trial_seed = seed + trial - 1
            traj = evaluate_and_capture(task, "simulated", trial_seed, trial, results_dir)
            relative = str(
                _trajectory_path(task, trial_seed, trial, results_dir).relative_to(results_dir)
            )
            exp_log.append(ExperimentEntry.from_trajectory(traj, relative))
            total_runs += 1
            execution_errors += not traj.metadata["simulation_completed"]
            tool_error_runs += bool(traj.metadata["tool_errors"])
    summary = {
        **_unassessed(sum(len(task.criteria) for task in tasks) * trials),
        "model": "simulated",
        "seed": seed,
        "trials": trials,
        "total_tasks": len(tasks),
        "scheduled_runs": len(tasks) * trials,
        "total_runs": total_runs,
        "execution_error_runs": execution_errors,
        "tool_error_runs": tool_error_runs,
        "reward": None,
        "passed": None,
        "safety_gate_passed": None,
        "total_passed": None,
        "pass_rate": None,
        "avg_reward": None,
        "safety_failures": None,
        "results_dir": str(results_dir),
    }
    with (results_dir / "summary.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return summary


def main(argv: list[str] | None = None) -> int:
    """Run unassessed scripted smoke diagnostics; actual models use orchestrator."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", default="all", help="Task ID or 'all'")
    parser.add_argument("--model", choices=("simulated",), default="simulated")
    parser.add_argument("--trials", type=int, default=1, help="Positive smoke trials per task")
    parser.add_argument("--seed", type=int, default=42, help="Integer world seed")
    parser.add_argument(
        "--results-dir", type=Path, help="New output directory; default: a fresh simulations run"
    )
    parser.add_argument("--tasks-dir", type=Path, default=_TASKS_DIR)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level, logging.INFO))
    try:
        summary = run_evaluation(
            args.tasks,
            args.model,
            args.trials,
            args.seed,
            args.results_dir or _RESULTS_DIR / "simulations" / f"run-{uuid4().hex}",
            args.tasks_dir,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(summary, sort_keys=True, allow_nan=False))
    return 1 if summary["execution_error_runs"] or summary["tool_error_runs"] else 0


if __name__ == "__main__":
    sys.exit(main())
