"""Offline evidence challenges against real task replay, separate from rewards.

Labels describe authored synthetic evidence, not clinical ground truth. Known
rubric defects are report findings; this module never adjusts tasks or scores.
"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from healthcraft.tasks.evaluator import _apply_overlay_to_task, replay_from_trajectory
from healthcraft.tasks.loader import load_task
from healthcraft.tasks.rubrics import validate_rubric_channel

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CHALLENGES = REPO_ROOT / "configs/evaluation/grader_challenges_v1.json"
_SHADOW_ENV = "HEALTHCRAFT_POC_VALIDATOR_SHADOW"


@contextmanager
def _without_shadow_writes() -> Iterator[None]:
    """Keep the synchronous offline runner read-only, restoring caller settings."""
    original = os.environ.get(_SHADOW_ENV)
    os.environ[_SHADOW_ENV] = "0"
    try:
        yield
    finally:
        if original is None:
            os.environ.pop(_SHADOW_ENV, None)
        else:
            os.environ[_SHADOW_ENV] = original


def _text_field(case: dict[str, Any], field: str) -> str:
    value = case.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _source_hashes(task_paths: set[Path], channel: str) -> dict[str, str]:
    files = set((REPO_ROOT / "src/healthcraft/tasks").glob("*.py")) | task_paths
    files.update(
        REPO_ROOT / path
        for path in (
            "src/healthcraft/world/state.py",
            "src/healthcraft/llm/orchestrator.py",
            "scripts/grade_challenges.py",
            "configs/mcp-tools.json",
            "configs/em_vocab.yaml",
        )
    )
    overlay_files = {
        "v9": "v9_deterministic_overlay.yaml",
        "v10": "v10_deterministic_overlay.yaml",
        "v11": "v11_consensus_overlay.yaml",
    }
    for version, filename in overlay_files.items():
        if int(version[1:]) <= int(channel[1:]):
            files.add(REPO_ROOT / "configs/rubrics" / filename)
    return {
        str(path.relative_to(REPO_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(files)
    }


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [row for row in rows if row["error"] is None]
    positive = sum(row["expected"] is True for row in scored)
    negative = sum(row["expected"] is False for row in scored)
    false_pass = sum(row["outcome"] == "false_pass" for row in scored)
    false_fail = sum(row["outcome"] == "false_fail" for row in scored)
    return {
        "total": len(rows),
        "evaluated": len(scored),
        "errors": len(rows) - len(scored),
        "expected_positive": positive,
        "expected_negative": negative,
        "false_pass": false_pass,
        "false_fail": false_fail,
        "false_pass_rate": false_pass / negative if negative else None,
        "false_fail_rate": false_fail / positive if positive else None,
    }


def run_challenges(path: Path | None = None, *, rubric_channel: str = "v10") -> dict[str, Any]:
    """Replay selected criteria and report mismatches without editing artifacts.

    All case failures remain individual error rows, excluded from confusion
    denominators. Invalid suite metadata fails loudly. This synchronous runner
    temporarily disables process-level shadow logging; do not run it alongside
    a live evaluation in another thread of the same process.
    """
    validate_rubric_channel(rubric_channel)
    path = Path(path or DEFAULT_CHALLENGES)
    fixture_bytes = path.read_bytes()
    data = json.loads(fixture_bytes)
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int:
        raise ValueError("Challenge fixture must have an integer schema_version")
    if data["schema_version"] != 1:
        raise ValueError("Unsupported challenge schema_version")
    for field in ("suite_id", "label_basis", "limitations"):
        _text_field(data, field)
    if not isinstance(data.get("cases"), list) or not data["cases"]:
        raise ValueError("Challenge fixture cases must be a nonempty array")

    outcomes: list[dict[str, Any]] = []
    task_paths: set[Path] = set()
    seen: set[str] = set()
    with _without_shadow_writes():
        for index, raw in enumerate(data["cases"]):
            case = raw if isinstance(raw, dict) else {}
            row: dict[str, Any] = {
                "id": case.get("id", f"invalid-row-{index}"),
                "category": case.get("category")
                if isinstance(case.get("category"), str) and case["category"].strip()
                else "invalid_case",
                "task_id": case.get("task_id"),
                "criterion_id": case.get("criterion_id"),
                "safety_critical": None,
                "expected": case.get("expected_satisfied")
                if isinstance(case.get("expected_satisfied"), bool)
                else None,
                "actual": None,
                "outcome": "error",
                "error": None,
                "evidence": "",
                "rationale": case.get("rationale", ""),
            }
            try:
                for field in (
                    "id",
                    "category",
                    "task_path",
                    "task_id",
                    "criterion_id",
                    "assertion",
                    "target_patient_id",
                    "rationale",
                ):
                    _text_field(case, field)
                if case["id"] in seen:
                    raise ValueError(f"Duplicate challenge id: {case['id']}")
                seen.add(case["id"])
                if not isinstance(case.get("expected_satisfied"), bool):
                    raise ValueError("expected_satisfied must be a boolean")
                task_path = (REPO_ROOT / case["task_path"]).resolve()
                if not task_path.is_relative_to(REPO_ROOT / "configs/tasks"):
                    raise ValueError("task_path must resolve inside configs/tasks")
                task = load_task(task_path)
                task_paths.add(task_path)
                if task.id != case["task_id"]:
                    raise ValueError("task_id does not match the task file")
                effective = _apply_overlay_to_task(task, rubric_channel)
                criterion = next(
                    (raw for raw in effective.criteria if raw["id"] == case["criterion_id"]),
                    None,
                )
                if criterion is None:
                    raise ValueError("criterion_id does not exist in the task")
                safety_critical = criterion.get("safety_critical", False)
                if not isinstance(safety_critical, bool):
                    raise ValueError("Task safety_critical metadata must be a boolean")
                row["safety_critical"] = safety_critical
                if criterion["assertion"] != case["assertion"]:
                    raise ValueError("Task assertion changed; independently review the label")
                if criterion["verification"] not in {"world_state", "pattern"}:
                    raise ValueError("Offline challenges require a deterministic criterion")
                row.update(
                    assertion=criterion["assertion"],
                    check=criterion.get("check", ""),
                    verification=criterion["verification"],
                    target_patient_id=case["target_patient_id"],
                )
                trajectory = case.get("trajectory")
                if not isinstance(trajectory, dict) or trajectory.get("task_id") != task.id:
                    raise ValueError("trajectory must be an object with the matching task_id")
                if not isinstance(trajectory.get("turns"), list):
                    raise ValueError("trajectory.turns must be an array")
                if "criteria_results" in trajectory:
                    raise ValueError("Saved verdicts are not permitted in independent challenges")
                result = replay_from_trajectory(trajectory, task, rubric_channel=rubric_channel)
                verdict = next(
                    cr for cr in result.criteria_results if cr.criterion_id == case["criterion_id"]
                )
                row["evidence"] = verdict.evidence
                if verdict.error is not None:
                    raise ValueError(verdict.error)
                if not isinstance(verdict.satisfied, bool):
                    raise ValueError("Evaluator returned a nonboolean verdict")
                row["actual"] = verdict.satisfied
                row["outcome"] = (
                    "match"
                    if verdict.satisfied is row["expected"]
                    else "false_pass"
                    if verdict.satisfied
                    else "false_fail"
                )
            except Exception as exc:  # noqa: BLE001 — every input row must remain visible
                row["error"] = f"{type(exc).__name__}: {exc}"
            outcomes.append(row)

    categories = sorted({row["category"] for row in outcomes})
    scored = [row for row in outcomes if row["error"] is None]
    return {
        "schema_version": "healthcraft-grader-challenges/v1",
        "suite_id": data["suite_id"],
        "label_basis": data["label_basis"],
        "limitations": data["limitations"],
        "replay_only": True,
        "rubric_channel": rubric_channel,
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "source_hashes": _source_hashes(task_paths, rubric_channel),
        "coverage": {
            "cases": len(outcomes),
            "tasks": len({row["task_id"] for row in scored}),
            "criteria": len({(row["task_id"], row["criterion_id"]) for row in scored}),
            "measured_safety_cases": sum(row["safety_critical"] is True for row in scored),
        },
        "summary": _stats(outcomes),
        "categories": {
            category: _stats([row for row in outcomes if row["category"] == category])
            for category in categories
        },
        "safety_groups": {
            label: _stats([row for row in outcomes if row["safety_critical"] is value])
            for label, value in (
                ("safety_critical", True),
                ("non_safety", False),
                ("unknown", None),
            )
        },
        "outcomes": outcomes,
    }
