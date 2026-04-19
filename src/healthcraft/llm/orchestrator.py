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

import yaml

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
_RUBRICS_DIR = Path(__file__).parents[3] / "configs" / "rubrics"

_VALID_RUBRIC_CHANNELS = {"v8", "v9", "v10", "v11"}

_OVERLAY_FILES: dict[str, tuple[str, ...]] = {
    "v9": ("v9_deterministic_overlay.yaml",),
    # v10 is additive: load v9 first, then v10 (v10 overrides on duplicate criterion_id)
    "v10": ("v9_deterministic_overlay.yaml", "v10_deterministic_overlay.yaml"),
    # v11 is additive: load v9 + v10 + v11 (v11 overrides on duplicate criterion_id)
    "v11": (
        "v9_deterministic_overlay.yaml",
        "v10_deterministic_overlay.yaml",
        "v11_consensus_overlay.yaml",
    ),
}


def _load_overlay_file(path: Path) -> dict[str, dict[str, str]]:
    """Load a single overlay YAML file and return criterion_id -> overlay entry."""
    if not path.exists():
        return {}

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not data or not data.get("overlays"):
        return {}

    overlay_map: dict[str, dict[str, str]] = {}
    missing_attestation: list[str] = []
    for entry in data["overlays"]:
        crit_id = entry.get("criterion_id", "")
        if not crit_id:
            continue
        check = (entry.get("check") or "").lower()
        if "attempt at" in check and not (entry.get("intent_rescue_reason") or "").strip():
            missing_attestation.append(crit_id)
        overlay_map[crit_id] = {
            "verification": entry.get("verification", "world_state"),
            "check": entry.get("check", ""),
        }

    if missing_attestation:
        raise ValueError(
            f"{path.name}: entries using 'contains attempt at' must declare "
            "intent_rescue_reason. Missing on: " + ", ".join(sorted(missing_attestation))
        )

    return overlay_map


def _load_overlay(channel: str) -> dict[str, dict[str, str]]:
    """Load the deterministic overlay(s) for a rubric channel.

    For channel=v9: loads v9_deterministic_overlay.yaml.
    For channel=v10: loads v9 entries first, then v10 entries; v10 entries
    override v9 on duplicate criterion_id (v10 is newer).
    For channel=v11: loads v9 + v10 + v11 entries; later entries override
    earlier on duplicate criterion_id. v8 loads nothing.

    Returns a dict mapping criterion_id -> {verification, check} that
    replaces the original llm_judge criterion during evaluation.
    """
    filenames = _OVERLAY_FILES.get(channel, ())
    merged: dict[str, dict[str, str]] = {}
    for filename in filenames:
        merged.update(_load_overlay_file(_RUBRICS_DIR / filename))
    return merged


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
    rubric_channel: str = "v8",
    dynamic_state: bool = False,
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
        rubric_channel: "v8" (default, V8 behavior), "v9" (enables
            deterministic overlay and BEFORE/AFTER temporal operators),
            or "v10" (v9 entries plus v10 negation-promotion overlays).
        dynamic_state: If True, enable dynamic patient-state physiology
            overlays. Default False (V8 behavior).

    Returns:
        Summary dict with pass rates and statistics.
    """
    if rubric_channel not in _VALID_RUBRIC_CHANNELS:
        return {
            "error": (
                f"Invalid rubric_channel: {rubric_channel!r}. "
                f"Must be one of {_VALID_RUBRIC_CHANNELS}."
            ),
        }
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

    # Load deterministic overlay (no-op for v8; v9 loads v9; v10 loads v9+v10;
    # v11 loads v9+v10+v11).
    overlay: dict[str, dict[str, str]] = {}
    if rubric_channel in ("v9", "v10", "v11"):
        overlay = _load_overlay(rubric_channel)
        logger.info(
            "Rubric channel %s: loaded %d overlay entries",
            rubric_channel,
            len(overlay),
        )

    exp_log = ExperimentLog(results_dir / "experiments.jsonl")

    logger.info(
        "Evaluation: %d tasks x %d trials, agent=%s, judge=%s, channel=%s",
        len(tasks),
        trials,
        agent_model,
        judge_model,
        rubric_channel,
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

                # Enable dynamic state if requested (V8 default: off)
                if dynamic_state:
                    world._dynamic_state_enabled = True

                # Inject task-described patient into world state
                injected_ids: dict[str, str] = {}
                if task.patient:
                    injected_ids = inject_task_patient(
                        world, task.id, task.patient, task.initial_state
                    )

                # Attach physiology after injection (need patient_id)
                if dynamic_state and injected_ids.get("patient_id"):
                    clinical_trajectory = (
                        task.initial_state.get("clinical_trajectory")
                        if task.initial_state
                        else None
                    )
                    if clinical_trajectory:
                        from healthcraft.world.physiology import create_trajectory

                        pid = injected_ids["patient_id"]
                        traj = create_trajectory(
                            clinical_trajectory,
                            trial_seed,
                            pid,
                        )
                        world.attach_physiology(pid, traj)
                        logger.debug(
                            "Attached %s trajectory to %s",
                            clinical_trajectory,
                            pid,
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

                # Apply deterministic overlay (v9 or v10): rewrite matching
                # criteria from llm_judge -> world_state before evaluation.
                eval_task = task
                if overlay:
                    rewritten_criteria = []
                    for raw in task.criteria:
                        crit_id = raw["id"]
                        if crit_id in overlay:
                            overlay_entry = overlay[crit_id]
                            rewritten = dict(raw)
                            rewritten["verification"] = overlay_entry["verification"]
                            rewritten["check"] = overlay_entry["check"]
                            rewritten_criteria.append(rewritten)
                        else:
                            rewritten_criteria.append(raw)
                    from dataclasses import replace as dc_replace

                    eval_task = dc_replace(
                        task,
                        criteria=tuple(rewritten_criteria),
                    )

                result = evaluate_task(
                    eval_task,
                    agent_output,
                    server.world_state,
                    rubric_channel=rubric_channel,
                )

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
        "rubric_channel": rubric_channel,
        "dynamic_state": dynamic_state,
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


def _api_preflight(
    agent_model: str,
    agent_key: str,
    judge_model: str | None,
    judge_key: str,
) -> None:
    """Probe agent and judge APIs before the eval loop to catch
    misconfigured keys (free-tier quota, auth failure, unknown model).
    Without this, a 429-on-every-call key silently fills the trajectory
    cache with reward=0 shells that resume then skips.
    """
    from healthcraft.llm.agent import create_client

    def _probe(label: str, model: str, key: str) -> None:
        if not model or not key:
            logger.error("PREFLIGHT FAIL (%s): missing model or key", label)
            sys.exit(2)
        try:
            create_client(model, key).chat(
                messages=[{"role": "user", "content": "Reply with OK."}],
                tools=None,
                max_tokens=8,
            )
        except Exception as e:
            msg = str(e)
            if "limit: 0" in msg or "free_tier" in msg.lower() or "FreeTier" in msg:
                logger.error(
                    "PREFLIGHT FAIL (%s=%s): free-tier quota (limit 0). "
                    "Enable billing on the project that owns this key.",
                    label,
                    model,
                )
                sys.exit(2)
            up = msg.upper()
            if "401" in msg or "403" in msg or "API_KEY_INVALID" in up:
                logger.error(
                    "PREFLIGHT FAIL (%s=%s): auth failure (key missing, "
                    "revoked, or lacks model access).",
                    label,
                    model,
                )
                sys.exit(2)
            if "404" in msg or "NOT_FOUND" in up:
                logger.error(
                    "PREFLIGHT FAIL (%s=%s): model id not found.",
                    label,
                    model,
                )
                sys.exit(2)
            logger.warning(
                "PREFLIGHT WARN (%s=%s): probe raised %s; continuing "
                "(eval-loop retry logic will handle transients).",
                label,
                model,
                type(e).__name__,
            )
            return
        logger.info("PREFLIGHT OK: %s=%s", label, model)

    _probe("agent", agent_model, agent_key)
    if judge_model and judge_key:
        _probe("judge", judge_model, judge_key)


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
    parser.add_argument(
        "--rubric-channel",
        default="v8",
        choices=["v8", "v9", "v10"],
        help=(
            "Rubric channel: v8 (default), v9 (deterministic overlay + temporal ops), "
            "or v10 (v9 + negation-promotion overlay)"
        ),
    )
    parser.add_argument(
        "--dynamic-state",
        action="store_true",
        help="Enable dynamic patient-state physiology overlays (default off = V8)",
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

    _api_preflight(
        agent_model=args.agent_model,
        agent_key=agent_key,
        judge_model=args.judge_model or select_judge_model(args.agent_model),
        judge_key=judge_key,
    )

    # Also check HC_DYNAMIC_STATE env var as a flag
    use_dynamic_state = (
        args.dynamic_state
        or os.environ.get(
            "HC_DYNAMIC_STATE",
            "0",
        )
        == "1"
    )

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
        rubric_channel=args.rubric_channel,
        dynamic_state=use_dynamic_state,
    )

    if "error" in summary:
        sys.exit(1)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
