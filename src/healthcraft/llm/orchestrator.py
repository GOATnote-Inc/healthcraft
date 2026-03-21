"""Evaluation orchestrator for HEALTHCRAFT frontier model evaluation.

Manages the full evaluation pipeline:
1. Load tasks and seed world state
2. Run agent on each task (with tool calling via MCP server)
3. Evaluate criteria (world_state + llm_judge + pattern)
4. Capture trajectories and compute rewards (Corecraft Eq. 1)
5. Write results to experiment log

Usage:
    python -m healthcraft.llm.orchestrator \\
        --agent-model claude-opus-4-6 --agent-key $ANTHROPIC_API_KEY \\
        --judge-model gpt-5.4 --judge-key $OPENAI_API_KEY \\
        --tasks all --trials 5 --seed 42
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from healthcraft.llm.agent import create_client, run_agent_task
from healthcraft.llm.judge import LLMJudge, select_judge_model
from healthcraft.mcp.server import create_server
from healthcraft.tasks.evaluator import evaluate_task
from healthcraft.tasks.inject import inject_task_patient
from healthcraft.tasks.loader import Task, load_task, load_tasks
from healthcraft.tasks.rubrics import Criterion, VerificationMethod
from healthcraft.trajectory import (
    CriterionEvalResult,
    ExperimentEntry,
    ExperimentLog,
    Trajectory,
)
from healthcraft.world.seed import WorldSeeder

logger = logging.getLogger("healthcraft.orchestrator")

_TASKS_DIR = Path(__file__).parents[3] / "configs" / "tasks"
_RESULTS_DIR = Path(__file__).parents[3] / "results"
_CONFIG_PATH = Path(__file__).parents[3] / "configs" / "world" / "mercy_point_v1.yaml"
_SYSTEM_PROMPT_DIR = Path(__file__).parents[3] / "system-prompts"


def _load_system_prompt(task: Task) -> str:
    """Load the composite system prompt for a task.

    Concatenates base.txt + mercy_point.txt + policies.txt + tool_reference.txt
    to give the agent full context about its role, facility, policies, and
    available tools. Tasks can override with system_prompt_override.
    """
    if task.system_prompt_override:
        override_path = _SYSTEM_PROMPT_DIR / task.system_prompt_override
        if override_path.exists():
            return override_path.read_text(encoding="utf-8")
        return task.system_prompt_override

    # Concatenate all system prompt components
    components = []
    for filename in ("base.txt", "mercy_point.txt", "policies.txt", "tool_reference.txt"):
        path = _SYSTEM_PROMPT_DIR / filename
        if path.exists():
            components.append(path.read_text(encoding="utf-8"))

    if components:
        return "\n\n".join(components)

    return "You are an emergency physician at Mercy Point Emergency Department."


def _parse_criteria(raw_criteria: tuple[dict[str, Any], ...]) -> list[Criterion]:
    """Parse raw criterion dicts into Criterion objects."""
    criteria = []
    for raw in raw_criteria:
        criteria.append(
            Criterion(
                id=raw["id"],
                assertion=raw["assertion"],
                dimension=raw.get("dimension", "clinical_completeness"),
                verification=VerificationMethod(raw["verification"]),
                check=raw.get("check", ""),
                safety_critical=raw.get("safety_critical", False),
            )
        )
    return criteria


def run_frontier_evaluation(
    agent_model: str,
    agent_key: str,
    judge_model: str | None,
    judge_key: str | None,
    task_filter: str = "all",
    trials: int = 5,
    seed: int = 42,
    results_dir: Path | None = None,
    tasks_dir: Path | None = None,
    max_tasks: int | None = None,
    retry_errors: bool = False,
) -> dict[str, Any]:
    """Run a full frontier model evaluation.

    Args:
        agent_model: Model identifier for the agent.
        agent_key: API key for the agent model.
        judge_model: Model identifier for the judge (auto-selected if None).
        judge_key: API key for the judge model.
        task_filter: "all" or a specific task ID.
        trials: Number of trials per task.
        seed: Base random seed.
        results_dir: Where to save results.
        tasks_dir: Where to load tasks from.
        max_tasks: Maximum number of tasks to evaluate (for testing).
        retry_errors: If True, re-run tasks that have error trajectories.

    Returns:
        Summary dict with pass rates and statistics.
    """
    results_dir = results_dir or _RESULTS_DIR
    tasks_dir = tasks_dir or _TASKS_DIR
    results_dir.mkdir(parents=True, exist_ok=True)

    # Auto-select judge model if not specified
    if judge_model is None:
        judge_model = select_judge_model(agent_model)
        logger.info("Auto-selected judge model: %s", judge_model)

    # Create clients
    agent_client = create_client(agent_model, agent_key)

    judge = None
    if judge_key:
        judge_client = create_client(judge_model, judge_key)
        judge = LLMJudge(judge_client, judge_model=judge_model)

    # Load tasks
    if task_filter == "all":
        tasks = load_tasks(tasks_dir)
    else:
        # Support comma-separated task IDs
        wanted_ids = {tid.strip() for tid in task_filter.split(",")}
        tasks = []
        for path in sorted(tasks_dir.rglob("*.yaml")):
            try:
                t = load_task(path)
                if t.id in wanted_ids:
                    tasks.append(t)
                    if len(tasks) == len(wanted_ids):
                        break
            except (ValueError, FileNotFoundError):
                continue

    if not tasks:
        return {"error": f"No tasks found: {task_filter}"}

    if max_tasks:
        tasks = tasks[:max_tasks]

    exp_log = ExperimentLog(results_dir / "experiments.jsonl")

    logger.info(
        "Evaluation: %d tasks x %d trials, agent=%s, judge=%s",
        len(tasks),
        trials,
        agent_model,
        judge_model,
    )

    # Run evaluations
    total_passed = 0
    total_runs = 0
    rewards: list[float] = []
    safety_failures = 0

    for task in tasks:
        for trial in range(1, trials + 1):
            trial_seed = seed + trial - 1

            # Compute trajectory path once (used for checkpoint and save)
            traj_filename = f"{task.id}_{agent_model}_{trial_seed}_t{trial}.json"
            traj_path = results_dir / "trajectories" / task.category / traj_filename

            # Resume: skip if trajectory already exists on disk
            if traj_path.exists():
                try:
                    existing = Trajectory.load(traj_path)
                    # If --retry-errors, re-run error trajectories
                    if retry_errors and existing.error is not None:
                        logger.info(
                            "Task %s trial %d — retrying previous error",
                            task.id,
                            trial,
                        )
                    else:
                        total_runs += 1
                        rewards.append(existing.reward)
                        if existing.passed:
                            total_passed += 1
                        if not existing.safety_gate_passed:
                            safety_failures += 1
                        logger.info(
                            "Task %s trial %d — CACHED (reward=%.3f)",
                            task.id,
                            trial,
                            existing.reward,
                        )
                        continue
                except Exception as e:
                    logger.warning(
                        "Corrupt checkpoint %s, re-running: %s",
                        traj_path,
                        e,
                    )

            logger.info(
                "Task %s trial %d/%d (seed=%d)",
                task.id,
                trial,
                trials,
                trial_seed,
            )

            try:
                # Seed fresh world state for each trial
                world = WorldSeeder(seed=trial_seed).seed_world(_CONFIG_PATH)

                # Inject task-described patient into world state
                injected_ids: dict[str, str] = {}
                if task.patient:
                    injected_ids = inject_task_patient(
                        world, task.id, task.patient, task.initial_state
                    )

                server = create_server(world)

                # Load system prompt
                system_prompt = _load_system_prompt(task)

                # Append injected patient/encounter IDs to the task so
                # the agent knows which patient to look up (prevents GPT
                # from creating a new patient via registerPatient).
                task_with_context = task
                if injected_ids:
                    pid = injected_ids.get("patient_id", "")
                    eid = injected_ids.get("encounter_id", "")
                    context_hint = f"\n\nRelevant patient ID: {pid}. Active encounter ID: {eid}."
                    # Create a shallow copy of the task with augmented description
                    from dataclasses import replace as dc_replace

                    task_with_context = dc_replace(
                        task, description=task.description.rstrip() + context_hint
                    )

                # Run agent
                traj = run_agent_task(agent_client, task_with_context, server, system_prompt)
                traj.model = agent_model
                traj.seed = trial_seed

                # Evaluate with world_state and pattern criteria
                agent_output = {
                    "tool_calls": [
                        tc.get("name", "")
                        for turn in traj.turns
                        if turn.tool_calls
                        for tc in turn.tool_calls
                    ],
                    "reasoning": " ".join(
                        turn.content for turn in traj.turns if turn.role == "assistant"
                    ),
                    "output": " ".join(
                        turn.content for turn in traj.turns if turn.role == "assistant"
                    ),
                }

                result = evaluate_task(task, agent_output, server.world_state)

                # Evaluate llm_judge criteria
                if judge:
                    criteria = _parse_criteria(task.criteria)
                    llm_results = judge.evaluate_criteria(
                        criteria,
                        [t.__dict__ for t in traj.turns],
                    )
                    # Merge llm_judge results with world_state/pattern results
                    llm_results_map = {r.criterion_id: r for r in llm_results}
                    merged_results = []
                    for cr in result.criteria_results:
                        if cr.criterion_id in llm_results_map:
                            merged_results.append(llm_results_map[cr.criterion_id])
                        else:
                            merged_results.append(cr)
                    # Recompute reward with merged results
                    from healthcraft.tasks.rubrics import (
                        check_safety_gate,
                        compute_dimension_scores,
                        compute_reward,
                    )

                    merged_reward = compute_reward(list(merged_results), criteria)
                    merged_passed = all(r.satisfied for r in merged_results)
                    merged_safety = check_safety_gate(list(merged_results), criteria)
                    merged_dims = compute_dimension_scores(list(merged_results), criteria)
                else:
                    merged_results = list(result.criteria_results)
                    merged_reward = result.reward
                    merged_passed = result.passed
                    merged_safety = result.safety_gate_passed
                    merged_dims = result.dimension_scores

                # Set results on trajectory
                traj.set_results(
                    criteria_results=[
                        CriterionEvalResult(
                            id=cr.criterion_id,
                            satisfied=cr.satisfied,
                            evidence=cr.evidence,
                        )
                        for cr in merged_results
                    ],
                    reward=merged_reward,
                    passed=merged_passed,
                    safety_gate_passed=merged_safety,
                    dimension_scores=merged_dims,
                )

                # Save trajectory
                traj.save(traj_path)

                # Log experiment
                traj_rel = f"trajectories/{task.category}/{traj_filename}"
                entry = ExperimentEntry.from_trajectory(traj, traj_rel)
                exp_log.append(entry)

                total_runs += 1
                rewards.append(merged_reward)
                if merged_passed:
                    total_passed += 1
                if not merged_safety:
                    safety_failures += 1

                logger.info(
                    "  -> reward=%.3f passed=%s safety=%s tools=%d",
                    merged_reward,
                    merged_passed,
                    merged_safety,
                    traj.total_tool_calls,
                )

            except Exception as e:
                logger.error("Task %s trial %d FAILED: %s", task.id, trial, e)
                error_traj = Trajectory(
                    task_id=task.id,
                    model=agent_model,
                    seed=trial_seed,
                    system_prompt="",
                    error=str(e),
                )
                error_traj.save(traj_path)
                traj_rel = f"trajectories/{task.category}/{traj_filename}"
                exp_log.append(
                    ExperimentEntry(
                        task_id=task.id,
                        model=agent_model,
                        seed=trial_seed,
                        reward=0.0,
                        passed=False,
                        safety_gate_passed=False,
                        total_tool_calls=0,
                        duration_seconds=0.0,
                        trajectory_path=traj_rel,
                        error=str(e),
                    )
                )
                total_runs += 1
                rewards.append(0.0)
                safety_failures += 1
                continue

    # Compute summary
    pass_rate = total_passed / total_runs if total_runs > 0 else 0.0
    avg_reward = sum(rewards) / len(rewards) if rewards else 0.0

    summary = {
        "agent_model": agent_model,
        "judge_model": judge_model,
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

    summary_path = results_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    logger.info("=" * 60)
    logger.info("EVALUATION COMPLETE")
    logger.info("  Agent: %s", agent_model)
    logger.info("  Judge: %s", judge_model)
    logger.info("  Tasks: %d x %d trials = %d runs", len(tasks), trials, total_runs)
    logger.info("  Pass rate: %.1f%% (%d/%d)", pass_rate * 100, total_passed, total_runs)
    logger.info("  Avg reward: %.3f", avg_reward)
    logger.info("  Safety failures: %d", safety_failures)
    logger.info("=" * 60)

    return summary


def _resolve_api_key(model: str) -> str:
    """Resolve API key from environment based on model name."""
    m = model.lower()
    if "claude" in m or "opus" in m or "sonnet" in m or "haiku" in m:
        return os.environ.get("ANTHROPIC_API_KEY", "")
    elif "gpt" in m or "o1" in m or "o3" in m:
        return os.environ.get("OPENAI_API_KEY", "")
    elif "gemini" in m:
        return os.environ.get("GOOGLE_API_KEY", "")
    elif "grok" in m:
        return os.environ.get("XAI_API_KEY", "")
    return os.environ.get("OPENAI_API_KEY", "")


def main() -> None:
    """CLI entry point for frontier model evaluation."""
    parser = argparse.ArgumentParser(description="HEALTHCRAFT Frontier Model Evaluation")
    parser.add_argument("--agent-model", required=True, help="Agent model ID")
    parser.add_argument(
        "--agent-key",
        default=None,
        help="Agent API key (or ANTHROPIC_API_KEY / OPENAI_API_KEY env var)",
    )
    parser.add_argument("--judge-model", default=None, help="Judge model ID")
    parser.add_argument(
        "--judge-key",
        default=None,
        help="Judge API key (auto-detected from env if not set)",
    )
    parser.add_argument("--tasks", default="all", help="Task ID or 'all'")
    parser.add_argument("--trials", type=int, default=5, help="Trials per task")
    parser.add_argument("--seed", type=int, default=42, help="Base seed")
    parser.add_argument("--max-tasks", type=int, default=None, help="Limit tasks")
    parser.add_argument("--results-dir", default=None, help="Results directory")
    parser.add_argument("--tasks-dir", default=None, help="Tasks directory")
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Re-run tasks that previously failed with errors (skips successful cached results)",
    )
    parser.add_argument("--log-level", default="INFO", help="Log level")

    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level, logging.INFO))

    # Resolve API keys from env if not provided
    agent_key = args.agent_key
    if not agent_key:
        agent_key = _resolve_api_key(args.agent_model)

    judge_key = args.judge_key
    if not judge_key:
        judge_model = args.judge_model or select_judge_model(args.agent_model)
        judge_key = _resolve_api_key(judge_model)

    if not agent_key:
        logger.error("No API key for agent model. Set --agent-key or env var.")
        sys.exit(1)

    summary = run_frontier_evaluation(
        agent_model=args.agent_model,
        agent_key=agent_key,
        judge_model=args.judge_model,
        judge_key=judge_key,
        task_filter=args.tasks,
        trials=args.trials,
        seed=args.seed,
        results_dir=Path(args.results_dir) if args.results_dir else None,
        tasks_dir=Path(args.tasks_dir) if args.tasks_dir else None,
        max_tasks=args.max_tasks,
        retry_errors=args.retry_errors,
    )

    if "error" in summary:
        sys.exit(1)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
