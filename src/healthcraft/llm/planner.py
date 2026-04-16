"""Evaluation planner for HEALTHCRAFT (Harness Pattern).

The Planner is the first stage of the Planner -> Generator -> Evaluator
pipeline. It takes task definitions and expands them into evaluation specs
with sprint contracts.

The Planner:
1. Loads task definitions from configs/tasks/
2. Generates sprint contracts for each task
3. Selects system prompt components based on task requirements
4. Determines trial strategy based on historical pass rates
5. Writes evaluation plan to disk for the Generator and Evaluator

The Planner can optionally use a local model (e.g., cascade8b via Ollama)
to reduce API cost, since planning does not require frontier model quality.

Usage:
    python -m healthcraft.llm.planner \
        --tasks all --agent-model claude-opus-4-6 --trials 5

    # Plan for specific tasks:
    python -m healthcraft.llm.planner \
        --tasks CR-001,CR-002 --agent-model gpt-5.4
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from healthcraft.llm.judge import select_judge_model
from healthcraft.llm.sprint_contract import SprintContract
from healthcraft.tasks.loader import Task, load_task, load_tasks

logger = logging.getLogger("healthcraft.planner")

_TASKS_DIR = Path(__file__).parents[3] / "configs" / "tasks"
_RESULTS_DIR = Path(__file__).parents[3] / "results"
_SYSTEM_PROMPT_DIR = Path(__file__).parents[3] / "system-prompts"


@dataclass
class TaskPlan:
    """Evaluation plan for a single task."""

    task_id: str
    category: str
    title: str
    description: str
    system_prompt_components: list[str]
    contract: SprintContract
    trials: int
    seed: int


@dataclass
class EvaluationPlan:
    """Complete evaluation plan spanning multiple tasks."""

    agent_model: str
    judge_model: str
    skepticism: str
    total_tasks: int
    total_trials: int
    task_plans: list[TaskPlan]
    seed: int = 42
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return path


def _select_system_prompt_components(task: Task) -> list[str]:
    """Select which system prompt components to include for a task.

    Returns a list of filenames from system-prompts/ that should be
    concatenated for this task's system prompt.
    """
    if task.system_prompt_override:
        return [task.system_prompt_override]

    # Default component set
    components = ["base.txt", "mercy_point.txt", "policies.txt", "tool_reference.txt"]

    # Verify components exist
    existing = []
    for filename in components:
        if (_SYSTEM_PROMPT_DIR / filename).exists():
            existing.append(filename)

    return existing if existing else ["base.txt"]


def _load_historical_pass_rates(results_dir: Path) -> dict[str, float]:
    """Load historical pass rates from experiments.jsonl.

    Returns:
        Dict mapping task_id to historical pass rate [0.0, 1.0].
    """
    exp_path = results_dir / "experiments.jsonl"
    if not exp_path.exists():
        return {}

    task_results: dict[str, list[bool]] = {}
    for line in exp_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            tid = entry.get("task_id", "")
            passed = entry.get("passed", False)
            if tid:
                task_results.setdefault(tid, []).append(passed)
        except json.JSONDecodeError:
            continue

    return {tid: sum(results) / len(results) for tid, results in task_results.items() if results}


def plan_evaluation(
    agent_model: str,
    task_filter: str = "all",
    trials: int = 5,
    seed: int = 42,
    skepticism: str = "default",
    tasks_dir: Path | None = None,
    results_dir: Path | None = None,
    max_tasks: int | None = None,
) -> EvaluationPlan:
    """Generate an evaluation plan.

    Args:
        agent_model: Model identifier for the agent.
        task_filter: "all" or comma-separated task IDs.
        trials: Number of trials per task.
        seed: Base random seed.
        skepticism: Judge skepticism level.
        tasks_dir: Where to load tasks from.
        results_dir: Where to find historical results.
        max_tasks: Maximum number of tasks to plan.

    Returns:
        An EvaluationPlan with sprint contracts for each task.
    """
    tasks_dir = tasks_dir or _TASKS_DIR
    results_dir = results_dir or _RESULTS_DIR

    # Select judge model (cross-vendor)
    judge_model = select_judge_model(agent_model)

    # Load tasks
    if task_filter == "all":
        tasks = load_tasks(tasks_dir)
    else:
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

    if max_tasks:
        tasks = tasks[:max_tasks]

    if not tasks:
        logger.error("No tasks found for filter: %s", task_filter)
        return EvaluationPlan(
            agent_model=agent_model,
            judge_model=judge_model,
            skepticism=skepticism,
            total_tasks=0,
            total_trials=0,
            task_plans=[],
            seed=seed,
        )

    # Historical pass rates available for future adaptive trial strategy
    _load_historical_pass_rates(results_dir)

    # Generate plans
    task_plans: list[TaskPlan] = []
    for task in tasks:
        # Generate sprint contract
        contract = SprintContract.from_task(
            task,
            agent_model=agent_model,
            judge_model=judge_model,
            skepticism=skepticism,
            seed=seed,
        )

        # Select system prompt components
        prompt_components = _select_system_prompt_components(task)

        task_plans.append(
            TaskPlan(
                task_id=task.id,
                category=task.category,
                title=task.title,
                description=task.description[:500],  # Truncate for plan readability
                system_prompt_components=prompt_components,
                contract=contract,
                trials=trials,
                seed=seed,
            )
        )

    total_trials = sum(tp.trials for tp in task_plans)

    plan = EvaluationPlan(
        agent_model=agent_model,
        judge_model=judge_model,
        skepticism=skepticism,
        total_tasks=len(task_plans),
        total_trials=total_trials,
        task_plans=task_plans,
        seed=seed,
    )

    logger.info(
        "Plan: %d tasks x %d trials = %d total, agent=%s, judge=%s (skepticism=%s)",
        len(task_plans),
        trials,
        total_trials,
        agent_model,
        judge_model,
        skepticism,
    )

    return plan


def main() -> None:
    """CLI entry point for evaluation planning."""
    parser = argparse.ArgumentParser(description="HEALTHCRAFT Evaluation Planner")
    parser.add_argument("--agent-model", required=True, help="Agent model ID")
    parser.add_argument("--tasks", default="all", help="Task filter")
    parser.add_argument("--trials", type=int, default=5, help="Trials per task")
    parser.add_argument("--seed", type=int, default=42, help="Base seed")
    parser.add_argument("--max-tasks", type=int, default=None, help="Limit tasks")
    parser.add_argument(
        "--skepticism",
        choices=["default", "moderate", "high"],
        default="default",
        help="Judge skepticism level",
    )
    parser.add_argument("--output", default=None, help="Output path for plan JSON")
    parser.add_argument("--log-level", default="INFO", help="Log level")

    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level, logging.INFO))

    plan = plan_evaluation(
        agent_model=args.agent_model,
        task_filter=args.tasks,
        trials=args.trials,
        seed=args.seed,
        skepticism=args.skepticism,
        max_tasks=args.max_tasks,
    )

    # Save plan
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = _RESULTS_DIR / "evaluation_plan.json"

    plan.save(output_path)
    logger.info("Plan saved to %s", output_path)

    # Print summary
    print(f"\nEvaluation Plan: {plan.total_tasks} tasks, {plan.total_trials} total trials")
    print(f"Agent: {plan.agent_model}, Judge: {plan.judge_model} (skepticism={plan.skepticism})")
    for tp in plan.task_plans[:5]:
        print(f"\n{tp.contract.summary()}")
    if plan.total_tasks > 5:
        print(f"\n  ... and {plan.total_tasks - 5} more tasks")


if __name__ == "__main__":
    main()
