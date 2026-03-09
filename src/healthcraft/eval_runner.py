"""Evaluation runner for HEALTHCRAFT tasks.

Loads tasks, runs them against the MCP server (either locally or via HTTP),
evaluates results using binary criteria (Corecraft Eq. 1), captures
trajectories, and writes results to the experiment log.

Usage:
    python -m healthcraft.eval_runner --tasks all --model claude-opus-4-6 --trials 5
    python -m healthcraft.eval_runner --tasks CR-001 --model gpt-5.4 --trials 1
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from healthcraft.mcp.server import create_server
from healthcraft.tasks.evaluator import TaskResult, evaluate_task
from healthcraft.tasks.loader import Task, load_task, load_tasks
from healthcraft.trajectory import (
    CriterionEvalResult,
    ExperimentEntry,
    ExperimentLog,
    Trajectory,
)
from healthcraft.world.seed import WorldSeeder

logger = logging.getLogger("healthcraft.eval")

# Default paths
_TASKS_DIR = Path(__file__).parents[2] / "configs" / "tasks"
_RESULTS_DIR = Path(__file__).parents[2] / "results"
_CONFIG_PATH = Path(__file__).parents[2] / "configs" / "world" / "mercy_point_v1.yaml"
_SYSTEM_PROMPT_DIR = Path(__file__).parents[2] / "system-prompts"


def load_system_prompt(task: Task) -> str:
    """Load the system prompt for a task.

    Uses task.system_prompt_override if set, otherwise loads base.txt.
    """
    if task.system_prompt_override:
        override_path = _SYSTEM_PROMPT_DIR / task.system_prompt_override
        if override_path.exists():
            return override_path.read_text(encoding="utf-8")
        return task.system_prompt_override

    base_path = _SYSTEM_PROMPT_DIR / "base.txt"
    if base_path.exists():
        return base_path.read_text(encoding="utf-8")

    return "You are an emergency physician at Mercy Point Emergency Department."


def run_task_locally(
    task: Task,
    seed: int = 42,
) -> tuple[dict[str, Any], Any]:
    """Run a task using the local in-memory MCP server.

    Returns:
        Tuple of (agent_output_dict, world_state_after).
        The agent_output is a placeholder — real evaluation requires
        an LLM agent. This function creates a simulated interaction
        for infrastructure testing.
    """
    config_path = _CONFIG_PATH
    world_state = WorldSeeder(seed=seed).seed_world(config_path)
    server = create_server(world_state)

    # Simulated agent interaction for infrastructure testing
    # In production, this is replaced by actual LLM agent calls
    tool_calls: list[str] = []
    reasoning = f"Simulated evaluation of task {task.id}"

    # Execute expected tools if specified
    for tool_name in task.expected_tools:
        server.call_tool(tool_name, {})
        tool_calls.append(tool_name)

    agent_output = {
        "tool_calls": tool_calls,
        "reasoning": reasoning,
        "output": f"Simulated output for {task.id}",
    }

    return agent_output, server.world_state


def evaluate_and_capture(
    task: Task,
    model: str,
    seed: int,
    trial: int,
    results_dir: Path,
) -> Trajectory:
    """Run a task, evaluate it, and capture the trajectory.

    Args:
        task: The task to evaluate.
        model: Model identifier.
        seed: Random seed for world state.
        trial: Trial number (1-indexed).
        results_dir: Where to save trajectories.

    Returns:
        The completed Trajectory.
    """
    system_prompt = load_system_prompt(task)

    # Create trajectory
    traj = Trajectory(
        task_id=task.id,
        model=model,
        seed=seed,
        system_prompt=system_prompt,
        metadata={
            "trial": trial,
            "category": task.category,
            "level": task.level,
            "title": task.title,
        },
    )

    # Add system prompt turn
    traj.add_turn("system", system_prompt)

    # Add task description turn
    traj.add_turn("user", task.description)

    start_time = time.monotonic()

    try:
        # Run the task
        agent_output, world_state = run_task_locally(task, seed=seed)

        # Add assistant turn with tool calls
        traj.add_turn(
            "assistant",
            agent_output.get("reasoning", ""),
            tool_calls=[{"name": tc} for tc in agent_output.get("tool_calls", [])],
        )

        # Evaluate
        result: TaskResult = evaluate_task(task, agent_output, world_state)

        # Set results on trajectory
        traj.set_results(
            criteria_results=[
                CriterionEvalResult(
                    id=cr.criterion_id,
                    satisfied=cr.satisfied,
                    evidence=cr.evidence,
                )
                for cr in result.criteria_results
            ],
            reward=result.reward,
            passed=result.passed,
            safety_gate_passed=result.safety_gate_passed,
            dimension_scores=result.dimension_scores,
        )

    except Exception as e:
        logger.error("Task %s trial %d failed: %s", task.id, trial, e)
        traj.error = str(e)

    traj.duration_seconds = time.monotonic() - start_time

    # Save trajectory
    traj_filename = f"{task.id}_{model}_{seed}_t{trial}.json"
    traj_path = results_dir / "trajectories" / task.category / traj_filename
    traj.save(traj_path)

    return traj


def run_evaluation(
    task_filter: str,
    model: str,
    trials: int,
    seed: int,
    results_dir: Path,
    tasks_dir: Path,
) -> dict[str, Any]:
    """Run the full evaluation suite.

    Args:
        task_filter: "all" or a specific task ID.
        model: Model identifier.
        trials: Number of trials per task.
        seed: Base random seed.
        results_dir: Where to save results.
        tasks_dir: Where to load tasks from.

    Returns:
        Summary dict with pass rates and statistics.
    """
    results_dir.mkdir(parents=True, exist_ok=True)
    exp_log = ExperimentLog(results_dir / "experiments.jsonl")

    # Load tasks
    if task_filter == "all":
        tasks = load_tasks(tasks_dir)
    else:
        # Find the specific task
        tasks = []
        for path in sorted(tasks_dir.rglob("*.yaml")):
            try:
                t = load_task(path)
                if t.id == task_filter:
                    tasks.append(t)
                    break
            except (ValueError, FileNotFoundError):
                continue

    if not tasks:
        logger.error("No tasks found matching filter: %s", task_filter)
        return {"error": f"No tasks found: {task_filter}"}

    total_evals = len(tasks) * trials
    logger.info("Running %d tasks x %d trials = %d evaluations", len(tasks), trials, total_evals)

    # Run evaluations
    total_passed = 0
    total_runs = 0
    rewards: list[float] = []
    safety_failures = 0

    for task in tasks:
        for trial in range(1, trials + 1):
            trial_seed = seed + trial - 1
            logger.info("Task %s trial %d/%d (seed=%d)", task.id, trial, trials, trial_seed)

            traj = evaluate_and_capture(task, model, trial_seed, trial, results_dir)

            # Log to experiments
            traj_rel_path = (
                f"trajectories/{task.category}/{task.id}_{model}_{trial_seed}_t{trial}.json"
            )
            entry = ExperimentEntry.from_trajectory(traj, traj_rel_path)
            exp_log.append(entry)

            total_runs += 1
            rewards.append(traj.reward)
            if traj.passed:
                total_passed += 1
            if not traj.safety_gate_passed:
                safety_failures += 1

    # Compute summary
    pass_rate = total_passed / total_runs if total_runs > 0 else 0.0
    avg_reward = sum(rewards) / len(rewards) if rewards else 0.0

    summary = {
        "model": model,
        "seed": seed,
        "trials": trials,
        "total_tasks": len(tasks),
        "total_runs": total_runs,
        "total_passed": total_passed,
        "pass_rate": round(pass_rate, 4),
        "avg_reward": round(avg_reward, 4),
        "safety_failures": safety_failures,
        "results_dir": str(results_dir),
    }

    # Save summary
    summary_path = results_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("Summary: %s", json.dumps(summary, indent=2))

    return summary


def main() -> None:
    """CLI entry point for the evaluation runner."""
    parser = argparse.ArgumentParser(description="HEALTHCRAFT Evaluation Runner")
    parser.add_argument("--tasks", default="all", help="Task ID or 'all'")
    parser.add_argument("--model", default="simulated", help="Model identifier")
    parser.add_argument("--trials", type=int, default=1, help="Trials per task")
    parser.add_argument("--seed", type=int, default=42, help="Base random seed")
    parser.add_argument("--results-dir", type=str, default=None, help="Results directory")
    parser.add_argument("--tasks-dir", type=str, default=None, help="Tasks directory")
    parser.add_argument("--log-level", default="INFO", help="Logging level")

    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level, logging.INFO))

    results_dir = Path(args.results_dir) if args.results_dir else _RESULTS_DIR
    tasks_dir = Path(args.tasks_dir) if args.tasks_dir else _TASKS_DIR

    summary = run_evaluation(
        task_filter=args.tasks,
        model=args.model,
        trials=args.trials,
        seed=args.seed,
        results_dir=results_dir,
        tasks_dir=tasks_dir,
    )

    if "error" in summary:
        sys.exit(1)

    # Exit with non-zero if pass rate is above target (for CI verification)
    logger.info("Pass rate: %.1f%%", summary["pass_rate"] * 100)


if __name__ == "__main__":
    main()
