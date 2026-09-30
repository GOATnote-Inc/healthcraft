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
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from healthcraft.llm.agent import create_client, run_agent_task
from healthcraft.llm.checkpoint import (
    checkpoint_identity,
    client_identity,
    environment_digest,
    latest_attempt,
    next_attempt,
    save_checkpoint,
    save_summary,
    trajectory_path,
    validate_checkpoint,
)
from healthcraft.llm.judge import LLMJudge, select_judge_model
from healthcraft.llm.local_models import LocalModelError, OllamaClient, is_local_model
from healthcraft.llm.review_context import freeze_review_context, seal_review_context
from healthcraft.mcp.server import create_server
from healthcraft.tasks.environment import prepare_task_environment
from healthcraft.tasks.evaluator import evaluate_task
from healthcraft.tasks.loader import Task, load_task, load_tasks
from healthcraft.tasks.prompts import compose_system_prompt
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
    available tools. Tasks can override with system_prompt_override and append
    literal instructions with system_prompt_append.
    """
    return compose_system_prompt(
        task,
        _SYSTEM_PROMPT_DIR,
        ("base.txt", "mercy_point.txt", "policies.txt", "tool_reference.txt"),
    )


def _evaluation_task(task: Task, overlay: dict[str, dict[str, str]]) -> Task:
    """Freeze the exact rubric used for both capture and subsequent grading."""
    frozen = deepcopy(task)
    criteria = []
    for raw in frozen.criteria:
        if raw["id"] in overlay:
            entry = overlay[raw["id"]]
            raw = {**raw, "verification": entry["verification"], "check": entry["check"]}
        criteria.append(raw)
    return replace(frozen, criteria=tuple(criteria))


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


def _merge_judge_verdicts(eval_task, base_result, judge, turns):
    """Merge live llm_judge verdicts into the deterministic base result.

    CRITICAL: the judge is run over ``eval_task.criteria`` — the criteria AFTER
    the overlay rewrite — NOT the original pre-overlay ``task.criteria``. An
    overlay promotes an llm_judge criterion to a deterministic world_state check;
    running the judge over the original criteria would re-grade the promoted
    criterion with the noisy judge and let a hallucinated PASS OVERRIDE the
    deterministic verdict (the HC-002 overlay-defeat: a judge PASS clearing a
    safety gate the overlay was built to hold, and live diverging from replay).
    Because ``judge.evaluate_criteria`` only evaluates criteria whose
    verification is still ``llm_judge``, parsing the post-overlay criteria makes
    it skip every promoted criterion, so the deterministic verdict survives.

    Returns ``(merged_results, reward, passed, safety_gate, dimension_scores)``.
    """
    from healthcraft.tasks.rubrics import (
        check_safety_gate,
        compute_dimension_scores,
        compute_reward,
    )

    if judge is None:
        return (
            list(base_result.criteria_results),
            base_result.reward,
            base_result.passed,
            base_result.safety_gate_passed,
            base_result.dimension_scores,
        )

    criteria = _parse_criteria(eval_task.criteria)  # POST-overlay (see docstring)
    llm_results = judge.evaluate_criteria(criteria, turns)
    errors = [result.error for result in llm_results if result.error is not None]
    if errors:
        raise RuntimeError("Judge infrastructure failure: " + "; ".join(errors))
    llm_map = {r.criterion_id: r for r in llm_results}
    merged = [llm_map.get(cr.criterion_id, cr) for cr in base_result.criteria_results]
    return (
        merged,
        compute_reward(merged, criteria),
        all(r.satisfied for r in merged),
        check_safety_gate(merged, criteria),
        compute_dimension_scores(merged, criteria),
    )


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
    scenario_profile: str | None = None,
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
        scenario_profile: Explicit experimental observation profile. Such runs
            remain ungraded and cannot be compared to published benchmark scores.

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
    if scenario_profile is not None:
        from healthcraft.tasks.roster_profile import PROFILE_VERSION

        if scenario_profile != PROFILE_VERSION:
            return {"error": f"Unknown scenario profile: {scenario_profile}"}
        if judge_model is not None or dynamic_state:
            return {"error": "Unvalidated scenario profiles require no judge and no dynamic state"}
    results_dir = results_dir or _RESULTS_DIR
    tasks_dir = tasks_dir or _TASKS_DIR
    results_dir.mkdir(parents=True, exist_ok=True)

    # A local run never selects a paid/cloud judge implicitly or explicitly.
    try:
        judge_model = (
            None if scenario_profile else _select_evaluation_judge(agent_model, judge_model)
        )
    except ValueError as exc:
        return {"error": str(exc)}

    # Create clients
    agent_client = create_client(agent_model, agent_key)
    if isinstance(agent_client, OllamaClient):
        try:
            agent_client.validate_capabilities(require_tools=True)
        except LocalModelError as exc:
            return {"error": str(exc)}

    judge = None
    if judge_model and (judge_key or is_local_model(judge_model)):
        # Cross-vendor guard (never self-judge). select_judge_model only forces
        # a cross-vendor judge when judge_model is None; an explicit --judge-model
        # can self-judge. Refuse when judge and agent are the same vendor. Reuse
        # ensemble_judge._vendor_of; on an unknown vendor we cannot prove
        # same-vendor, so we do not block (fail-safe, no crash).
        from healthcraft.llm.ensemble_judge import _vendor_of

        try:
            _agent_vendor = _vendor_of(agent_model)
            _judge_vendor = _vendor_of(judge_model)
        except ValueError:
            _agent_vendor = _judge_vendor = None
        if _agent_vendor is not None and _agent_vendor == _judge_vendor:
            return {
                "error": (
                    f"Refusing to self-judge: judge model {judge_model!r} and agent "
                    f"model {agent_model!r} are the same vendor ({_judge_vendor}). "
                    "Cross-vendor judging is required (never self-judge). Pass a "
                    "different --judge-model or omit it for auto-selection."
                ),
            }
        judge_client = create_client(judge_model, judge_key or "")
        if isinstance(agent_client, OllamaClient) or isinstance(judge_client, OllamaClient):
            try:
                agent_info = (
                    agent_client.model_metadata()
                    if isinstance(agent_client, OllamaClient)
                    else {"model": agent_model, "vendor": _vendor_of(agent_model)}
                )
                judge_info = (
                    judge_client.model_metadata()
                    if isinstance(judge_client, OllamaClient)
                    else {"model": judge_model, "vendor": _vendor_of(judge_model)}
                )
                _check_local_judge_pair(agent_info, judge_info)
            except (LocalModelError, ValueError) as exc:
                return {"error": str(exc)}
        # Default the production judge to the tightened v2 prompt so the
        # safety_critical low-confidence downgrade (judge.py:358-362) actually
        # runs. v1 stays available for explicit V8 replay; replay_from_trajectory
        # never re-calls the live judge, so v8/channel/gold-set locks are
        # unaffected.
        judge = LLMJudge(judge_client, judge_model=judge_model, prompt_version="v2")

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

    if scenario_profile is not None:
        from healthcraft.tasks.roster_profile import build_roster_profile
        from healthcraft.world.state import WorldState

        try:
            for task in tasks:
                # Validate all selected sources before executing any trial.
                build_roster_profile(WorldState(), task)
        except (ValueError, TypeError) as exc:
            return {"error": f"Invalid scenario profile input: {exc}"}

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

    # Validate every selected checkpoint before running any new trial. Filename
    # equality alone cannot establish that grading/configuration is comparable.
    environment = environment_digest(Path(__file__).parents[3])
    agent_settings = client_identity(agent_client)
    judge_settings = client_identity(judge_client) if judge else {}
    prompts = {task.id: _load_system_prompt(task) for task in tasks}
    identities = {
        task.id: checkpoint_identity(
            task,
            prompts[task.id],
            agent_model=agent_model,
            judge_model=judge_model,
            judge_enabled=judge is not None,
            rubric_channel=rubric_channel,
            dynamic_state=dynamic_state,
            overlay=overlay,
            environment=environment,
            agent_settings=agent_settings,
            judge_settings=judge_settings,
            scenario_profile=scenario_profile,
        )
        for task in tasks
    }
    checkpoints: dict[tuple[str, int], tuple[Path, Trajectory | None]] = {}
    for task in tasks:
        for trial in range(1, trials + 1):
            trial_seed = seed + trial - 1
            base_path = trajectory_path(results_dir, task, agent_model, trial_seed, trial)
            path = latest_attempt(base_path)
            existing = None
            if path.exists():
                try:
                    existing = Trajectory.load(path)
                    validate_checkpoint(
                        existing,
                        task_id=task.id,
                        model=agent_model,
                        seed=trial_seed,
                        rubric_channel=rubric_channel,
                        identity=identities[task.id],
                    )
                except Exception as exc:
                    return {
                        "error": f"Cannot resume checkpoint {path}: {exc}. "
                        "Use a new results directory; existing evidence was preserved."
                    }
                if retry_errors and existing.error is not None:
                    path, existing = next_attempt(base_path), None
            checkpoints[(task.id, trial)] = (path, existing)

    exp_log = ExperimentLog(results_dir / "experiments.jsonl")
    logged_paths = {entry.trajectory_path for entry in exp_log.load_all()}

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
    error_runs = 0
    ungraded_criteria = 0
    profile_ungraded_runs = 0
    profile_metadata = (
        {
            "grading_complete": False,
            "benchmark_comparable": False,
            "benchmark_score": None,
        }
        if scenario_profile
        else {}
    )

    for task in tasks:
        for trial in range(1, trials + 1):
            trial_seed = seed + trial - 1

            # Compute trajectory path once (used for checkpoint and save)
            traj_path, existing = checkpoints[(task.id, trial)]
            traj_filename = traj_path.name
            missing_judge = (
                sum(
                    overlay.get(raw["id"], raw).get("verification") == "llm_judge"
                    for raw in task.criteria
                )
                if judge is None
                else 0
            )

            # Resume: skip if trajectory already exists on disk
            if existing is not None:
                relative_path = f"trajectories/{task.category}/{traj_filename}"
                if relative_path not in logged_paths:
                    # Recover an interrupted write between immutable trajectory
                    # creation and its append-only experiment-log entry.
                    exp_log.append(ExperimentEntry.from_trajectory(existing, relative_path))
                    logged_paths.add(relative_path)
                total_runs += 1
                rewards.append(existing.reward)
                if existing.passed:
                    total_passed += 1
                if not existing.safety_gate_passed or existing.error is not None:
                    safety_failures += 1
                if existing.error is not None:
                    error_runs += 1
                    ungraded_criteria += len(task.criteria)
                elif scenario_profile:
                    ungraded_criteria += len(task.criteria)
                    profile_ungraded_runs += 1
                else:
                    ungraded_criteria += missing_judge
                logger.info(
                    "Task %s trial %d — CACHED (reward=%.3f)", task.id, trial, existing.reward
                )
                continue

            logger.info(
                "Task %s trial %d/%d (seed=%d)",
                task.id,
                trial,
                trials,
                trial_seed,
            )

            traj = None
            review_draft = None
            scenario_context = (
                {"profile_version": scenario_profile, "preparation_complete": False}
                if scenario_profile
                else {}
            )
            failure_stage = "environment"
            try:
                # Preserve authored input before world preparation or model
                # execution can retain or mutate nested task dictionaries.
                source_task = deepcopy(task)
                eval_task = _evaluation_task(source_task, overlay)
                # Seed fresh world state for each trial
                world = WorldSeeder(seed=trial_seed).seed_world(_CONFIG_PATH)

                # Enable dynamic state if requested (V8 default: off)
                if dynamic_state:
                    world._dynamic_state_enabled = True

                task_with_context, scenario_context = prepare_task_environment(
                    world, task, profile=scenario_profile
                )
                injected_ids = scenario_context if scenario_profile is None else {}

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
                        physiology = create_trajectory(
                            clinical_trajectory,
                            trial_seed,
                            pid,
                        )
                        world.attach_physiology(pid, physiology)
                        logger.debug(
                            "Attached %s trajectory to %s",
                            clinical_trajectory,
                            pid,
                        )

                server = create_server(world)

                # Load system prompt
                system_prompt = prompts[task.id]

                review_draft = freeze_review_context(
                    source_task,
                    list(eval_task.criteria),
                    rubric_channel=rubric_channel,
                    scenario_context=scenario_context,
                    checkpoint_identity=identities[task.id],
                    grading_mode="profile_diagnostic" if scenario_profile else "benchmark",
                )

                # Run agent
                failure_stage = "agent"
                traj = run_agent_task(agent_client, task_with_context, server, system_prompt)
                traj.model = agent_model
                traj.seed = trial_seed
                traj.rubric_channel = rubric_channel
                traj.metadata.update(
                    {
                        "judge_model": judge_model if judge is not None else None,
                        "judge_prompt_version": "v2" if judge is not None else None,
                        "checkpoint_identity": identities[task.id],
                        "dynamic_state": dynamic_state,
                        "agent_settings": agent_settings,
                        "judge_settings": judge_settings,
                        "scenario_context": scenario_context,
                        "expected_criteria_count": len(task.criteria),
                        "grading_complete": missing_judge == 0,
                        "ungraded_criteria": missing_judge,
                    }
                )

                traj.metadata.update(profile_metadata)
                traj.metadata["review_context"] = seal_review_context(review_draft, traj)
                # run_agent_task captures API failures on its trajectory instead
                # of raising. Preserve partial evidence, but do not judge or
                # award successful completion to an interrupted execution.
                if traj.error is not None:
                    traj.metadata["failure_stage"] = "agent"
                    traj.metadata["grading_complete"] = False
                    traj.metadata["ungraded_criteria"] = len(task.criteria)
                    traj.set_results([], 0.0, False, False, {})
                    save_checkpoint(traj, traj_path)
                    exp_log.append(
                        ExperimentEntry.from_trajectory(
                            traj, f"trajectories/{task.category}/{traj_filename}"
                        )
                    )
                    total_runs += 1
                    rewards.append(0.0)
                    safety_failures += 1
                    error_runs += 1
                    ungraded_criteria += len(task.criteria)
                    logger.error("Task %s trial %d interrupted: %s", task.id, trial, traj.error)
                    continue

                if scenario_profile:
                    # Source projections are useful for execution diagnostics,
                    # but their historical clinical rubrics have not been
                    # validated against this altered observation contract.
                    traj.metadata["ungraded_criteria"] = len(task.criteria)
                    traj.set_results([], 0.0, False, False, {})
                    save_checkpoint(traj, traj_path)
                    exp_log.append(
                        ExperimentEntry.from_trajectory(
                            traj, f"trajectories/{task.category}/{traj_filename}"
                        )
                    )
                    total_runs += 1
                    rewards.append(0.0)
                    safety_failures += 1
                    profile_ungraded_runs += 1
                    ungraded_criteria += len(task.criteria)
                    continue

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

                result = evaluate_task(
                    eval_task,
                    agent_output,
                    server.world_state,
                    rubric_channel=rubric_channel,
                )

                # Merge live llm_judge verdicts over the deterministic base
                # result. The judge runs over the POST-overlay criteria so an
                # overlay-promoted (now world_state) criterion keeps its
                # deterministic verdict (fixes HC-002 overlay-defeat).
                failure_stage = "grader"
                (
                    merged_results,
                    merged_reward,
                    merged_passed,
                    merged_safety,
                    merged_dims,
                ) = _merge_judge_verdicts(
                    eval_task, result, judge, [t.__dict__ for t in traj.turns]
                )

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
                failure_stage = "persistence"
                save_checkpoint(traj, traj_path)

                # Log experiment
                traj_rel = f"trajectories/{task.category}/{traj_filename}"
                entry = ExperimentEntry.from_trajectory(traj, traj_rel)
                exp_log.append(entry)

                total_runs += 1
                rewards.append(merged_reward)
                ungraded_criteria += missing_judge
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
                if traj_path.exists():
                    return {
                        "error": f"Persistence failed for checkpoint {traj_path}: {e}. "
                        "Existing trajectory evidence was preserved."
                    }
                error_traj = traj or Trajectory(
                    task_id=task.id,
                    model=agent_model,
                    seed=trial_seed,
                    system_prompt="",
                    rubric_channel=rubric_channel,
                    safety_gate_passed=False,
                    metadata={
                        "checkpoint_identity": identities[task.id],
                        "dynamic_state": dynamic_state,
                        "agent_settings": agent_settings,
                        "judge_settings": judge_settings,
                        "scenario_context": scenario_context,
                        "expected_criteria_count": len(task.criteria),
                    },
                    error=str(e),
                )
                error_traj.error = str(e)
                error_traj.set_results([], 0.0, False, False, {})
                error_traj.metadata["failure_stage"] = failure_stage
                error_traj.metadata["grading_complete"] = False
                error_traj.metadata["ungraded_criteria"] = len(task.criteria)
                error_traj.metadata.update(profile_metadata)
                if review_draft is not None and "review_context" not in error_traj.metadata:
                    error_traj.metadata["review_context"] = seal_review_context(
                        review_draft, error_traj
                    )
                save_checkpoint(error_traj, traj_path)
                traj_rel = f"trajectories/{task.category}/{traj_filename}"
                exp_log.append(ExperimentEntry.from_trajectory(error_traj, traj_rel))
                total_runs += 1
                rewards.append(0.0)
                safety_failures += 1
                error_runs += 1
                ungraded_criteria += len(task.criteria)
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
        # Error trajectories are graded fail-closed (reward=0, safety gate
        # failed) and are INCLUDED in safety_failures; error_runs makes the
        # infra-vs-model split explicit so analysis can separate them.
        "error_runs": error_runs,
        "safety_failures_excl_errors": safety_failures - error_runs - profile_ungraded_runs,
        "evaluation_mode": (
            "profile_diagnostic"
            if scenario_profile
            else "local_diagnostic"
            if is_local_model(agent_model) or is_local_model(judge_model)
            else "full"
            if judge is not None
            else "deterministic_only"
        ),
        "ungraded_criteria": ungraded_criteria,
        "grading_complete": ungraded_criteria == 0,
        "results_dir": str(results_dir),
    }
    if scenario_profile:
        summary.update(
            {
                "scenario_profile": scenario_profile,
                "benchmark_comparable": False,
                "benchmark_score": None,
                "safety_not_assessed_runs": profile_ungraded_runs + error_runs,
                "grading_complete": False,
                "total_passed": None,
                "pass_rate": None,
                "avg_reward": None,
                "safety_failures": None,
                "safety_failures_excl_errors": None,
            }
        )

    save_summary(results_dir, summary)

    logger.info("=" * 60)
    logger.info("EVALUATION COMPLETE")
    logger.info("  Agent: %s", agent_model)
    logger.info("  Judge: %s", judge_model)
    logger.info("  Tasks: %d x %d trials = %d runs", len(tasks), trials, total_runs)
    if scenario_profile:
        logger.info("  Experimental profile: benchmark and safety outcomes not assessed")
        logger.info("  Ungraded runs: %d (%d execution errors)", total_runs, error_runs)
    else:
        logger.info("  Pass rate: %.1f%% (%d/%d)", pass_rate * 100, total_passed, total_runs)
        logger.info("  Avg reward: %.3f", avg_reward)
        logger.info(
            "  Safety failures: %d (%d from error trajectories, fail-closed)",
            safety_failures,
            error_runs,
        )
    logger.info("=" * 60)

    return summary


def _select_evaluation_judge(agent_model: str, judge_model: str | None) -> str | None:
    """Local evaluation is keyless and only uses an explicitly selected local judge."""
    if is_local_model(agent_model):
        if judge_model and not is_local_model(judge_model):
            raise ValueError("A local agent requires a local judge; cloud judging is refused")
        return judge_model
    return judge_model or select_judge_model(agent_model)


def _check_local_judge_pair(agent: dict[str, Any], judge: dict[str, Any]) -> None:
    """Reject self-judging even when local models use different aliases."""

    def vendor(info):
        if info.get("vendor"):
            return info["vendor"]
        family = info.get("family", "").lower()
        for prefix, name in (
            ("nemotron", "nvidia"),
            ("gemma", "google"),
            ("qwen", "alibaba"),
            ("llama", "meta"),
            ("mistral", "mistral"),
            ("phi", "microsoft"),
            ("deepseek", "deepseek"),
            ("gptoss", "openai"),
            ("gpt-oss", "openai"),
        ):
            if family.startswith(prefix):
                return name
        raise ValueError(f"Cannot establish vendor for local model family {family!r}")

    if (
        agent["model"] == judge["model"]
        or (agent.get("model_digest") and agent["model_digest"] == judge.get("model_digest"))
        or vendor(agent) == vendor(judge)
    ):
        raise ValueError("Refusing to self-judge: local agent and judge must be different vendors")


def _resolve_api_key(model: str) -> str:
    """Resolve API key from environment based on model name."""
    m = model.lower()
    if is_local_model(model):
        return ""
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
        if is_local_model(model):
            try:
                client = create_client(model, "")
                client.validate_capabilities(require_tools=label == "agent")
            except (LocalModelError, ValueError) as exc:
                logger.error("PREFLIGHT FAIL (%s=%s): %s", label, model, exc)
                sys.exit(2)
            logger.info("PREFLIGHT OK: %s=%s (local capability check, no inference)", label, model)
            return
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
            # A 400 / invalid-parameter (e.g. a reasoning model that rejects
            # temperature, or any unsupported request param) would otherwise
            # 400 on EVERY call and silently fill the cache with reward=0 error
            # trajectories. Fail loud and distinct here (v11 audit D4-F1/D4-F6).
            if (
                "400" in msg
                or "temperature" in msg.lower()
                or "INVALID_ARGUMENT" in up
                or "unsupported" in msg.lower()
                or "not supported" in msg.lower()
            ):
                logger.error(
                    "PREFLIGHT FAIL (%s=%s): request rejected (HTTP 400 / invalid "
                    "parameter). A reasoning model may reject temperature, or a "
                    "request param is unsupported for this model id. This would "
                    "400 on every call and silently produce reward=0 trajectories. "
                    "Raw error: %s",
                    label,
                    model,
                    msg,
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
    if judge_model and (judge_key or is_local_model(judge_model)):
        _probe("judge", judge_model, judge_key)


def _positive_count(value: str) -> int:
    count = int(value)
    if count <= 0:
        raise argparse.ArgumentTypeError("Count must be positive")
    return count


def main(argv: list[str] | None = None, *, prog: str | None = None) -> None:
    """CLI entry point for frontier model evaluation."""
    parser = argparse.ArgumentParser(prog=prog, description="HEALTHCRAFT Model Evaluation")
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
    parser.add_argument("--trials", type=_positive_count, default=5, help="Trials per task")
    parser.add_argument("--seed", type=int, default=42, help="Base seed")
    parser.add_argument("--max-tasks", type=_positive_count, default=None, help="Limit tasks")
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
        choices=sorted(_VALID_RUBRIC_CHANNELS),
        help=(
            "Rubric channel (one of "
            + "/".join(sorted(_VALID_RUBRIC_CHANNELS))
            + "): v8 (default, no overlay), v9 (deterministic overlay + "
            "temporal ops), v10 (v9 + negation-promotion overlay), "
            "v11 (v9 + v10 + consensus overlay)"
        ),
    )
    parser.add_argument(
        "--dynamic-state",
        action="store_true",
        help="Enable dynamic patient-state physiology overlays (default off = V8)",
    )
    parser.add_argument("--log-level", default="INFO", help="Log level")
    parser.add_argument(
        "--scenario-profile",
        choices=["roster-observations/v1"],
        help="Opt-in roster observations; ungraded diagnostics, not benchmark scores",
    )

    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level, logging.INFO))

    use_dynamic_state = args.dynamic_state or os.environ.get("HC_DYNAMIC_STATE", "0") == "1"
    if args.scenario_profile and (args.judge_model or use_dynamic_state):
        parser.error("Scenario profiles require no judge and no dynamic state")

    # Resolve API keys from env if not provided
    agent_key = args.agent_key
    if not agent_key:
        agent_key = _resolve_api_key(args.agent_model)

    try:
        judge_model = (
            None
            if args.scenario_profile
            else _select_evaluation_judge(args.agent_model, args.judge_model)
        )
    except ValueError as exc:
        parser.error(str(exc))
    judge_key = args.judge_key or (_resolve_api_key(judge_model) if judge_model else "")

    if not agent_key and not is_local_model(args.agent_model):
        logger.error("No API key for agent model. Set --agent-key or env var.")
        sys.exit(1)

    _api_preflight(
        agent_model=args.agent_model,
        agent_key=agent_key,
        judge_model=judge_model,
        judge_key=judge_key,
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
        scenario_profile=args.scenario_profile,
    )

    if "error" in summary:
        sys.exit(1)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
