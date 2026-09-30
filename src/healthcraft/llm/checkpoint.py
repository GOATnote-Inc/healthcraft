"""Content-addressed evaluation identity and append-only checkpoint selection.

Historical trajectories remain replayable, but cannot establish that a new live
experiment uses the same task, grader, environment, prompt, or model settings.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.parse import quote

from healthcraft.tasks.loader import Task
from healthcraft.trajectory import Trajectory


def content_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def environment_digest(root: Path) -> str:
    """Hash executable environment and world/schema inputs, never credentials."""
    files = sorted((root / "src" / "healthcraft").rglob("*.py"))
    files += sorted((root / "configs" / "world").rglob("*.yaml"))
    files += [root / "configs" / "mcp-tools.json"]
    vocabulary = root / "configs" / "em_vocab.yaml"
    if vocabulary.exists():
        files.append(vocabulary)
    from healthcraft.world.seed import WorldSeeder

    packages = {}
    for name in ("pyyaml", "jsonschema", "openem", "openai", "anthropic", "google-genai"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return content_digest(
        {
            "files": {
                str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
            },
            "packages": packages,
            "openem_conditions": WorldSeeder._load_openem_conditions(),
            "idempotent_tools": os.environ.get("HC_IDEMPOTENT_TOOLS", "1") != "0",
        }
    )


def client_identity(client: Any) -> dict:
    """Record effective routing without storing keys or credentials in URLs."""
    identity = getattr(client, "checkpoint_identity", None)
    if callable(identity):
        return identity()
    endpoint = getattr(client, "_base_url", None)
    provider = type(client).__name__
    if provider == "OpenAIClient":
        endpoint = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    elif provider == "AnthropicClient":
        endpoint = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    return {
        "provider": provider,
        "model": getattr(client, "_model", None),
        "endpoint_sha256": content_digest(endpoint),
    }


def checkpoint_identity(
    task: Task,
    system_prompt: str,
    *,
    agent_model: str,
    judge_model: str | None,
    judge_enabled: bool,
    rubric_channel: str,
    dynamic_state: bool,
    overlay: dict,
    environment: str,
    agent_settings: dict,
    judge_settings: dict,
) -> str:
    return content_digest(
        {
            "version": 1,
            "task": asdict(task),
            "system_prompt": system_prompt,
            "agent_model": agent_model,
            "judge_model": judge_model,
            "judge_enabled": judge_enabled,
            "judge_prompt_version": "v2" if judge_enabled else None,
            "rubric_channel": rubric_channel,
            "dynamic_state": dynamic_state,
            "overlay": {c["id"]: overlay[c["id"]] for c in task.criteria if c["id"] in overlay},
            "environment": environment,
            "agent_settings": agent_settings,
            "judge_settings": judge_settings,
        }
    )


def trajectory_path(root: Path, task: Task, model: str, seed: int, trial: int) -> Path:
    # Model registry IDs commonly contain slashes; keep one filename per trial.
    model_name = quote(model, safe="-_.:")
    return root / "trajectories" / task.category / f"{task.id}_{model_name}_{seed}_t{trial}.json"


def latest_attempt(path: Path) -> Path:
    candidates = [(1, path)] if path.exists() else []
    for candidate in path.parent.glob(path.stem + "_attempt*.json"):
        suffix = candidate.stem[len(path.stem + "_attempt") :]
        if suffix.isdigit() and int(suffix) >= 2:
            candidates.append((int(suffix), candidate))
    return max(candidates, default=(1, path))[1]


def next_attempt(path: Path) -> Path:
    latest = latest_attempt(path)
    number = 2 if latest == path else int(latest.stem[len(path.stem + "_attempt") :]) + 1
    return path.with_name(f"{path.stem}_attempt{number}.json")


def validate_checkpoint(
    trajectory: Trajectory,
    *,
    task_id: str,
    model: str,
    seed: int,
    rubric_channel: str,
    identity: str,
) -> None:
    if (
        trajectory.task_id != task_id
        or trajectory.model != model
        or trajectory.seed != seed
        or trajectory.rubric_channel != rubric_channel
        or trajectory.metadata.get("checkpoint_identity") != identity
    ):
        raise ValueError("Checkpoint provenance differs or is absent; use a new results directory.")


def save_checkpoint(trajectory: Trajectory, path: Path) -> None:
    """Exclusive creation prevents retries or racing runs from erasing evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(trajectory.to_json())


def save_summary(root: Path, summary: dict) -> None:
    """Keep previous summaries intact when retrying or extending an experiment."""
    payload = json.dumps(summary, indent=2)
    candidates = _summary_candidates(root)
    if candidates and load_latest_summary(root) == summary:
        return
    number = max((number for number, _ in candidates), default=0) + 1
    path = root / ("summary.json" if number == 1 else f"summary-{number}.json")
    with path.open("x", encoding="utf-8") as stream:
        stream.write(payload)


def trajectory_attempt(path: Path) -> tuple[Path, int]:
    """Return a trial's original path and numeric attempt, without reading it.

    Only the final suffix after ``_t<number>`` denotes a retry; model names
    containing ``_attempt`` remain part of the trial identity.
    """
    stem, separator, suffix = path.stem.rpartition("_attempt")
    trial_separator = stem.rpartition("_t")
    if (
        path.suffix == ".json"
        and separator
        and suffix.isdigit()
        and int(suffix) >= 2
        and trial_separator[1]
        and trial_separator[2].isdigit()
    ):
        return path.with_name(stem + ".json"), int(suffix)
    return path, 1


def selected_trajectory_paths(source: Path | list[Path]) -> list[Path]:
    """Select the newest immutable attempt of each trial in original-path order.

    Accept a run directory, its trajectory directory, or an explicit path list.
    Known generated grading/summary sidecars are excluded by filename; legacy
    trajectory names otherwise remain supported without a filename schema.
    Selection happens before content validation: an invalid newest attempt must
    never silently resurrect an older score. Separate directories remain
    separate experiments, and no files are modified.
    """
    if isinstance(source, Path):
        directory = source / "trajectories"
        if not directory.is_dir():
            directory = source
        paths = list(directory.rglob("*.json"))
    else:
        paths = source
    selected: dict[Path, tuple[int, Path]] = {}
    for path in paths:
        if path.suffix == ".json" and (
            path.stem.endswith("_grading")
            or path.name in {"summary.json", "evaluation_summary.json"}
            or (path.stem.startswith("summary-") and path.stem.removeprefix("summary-").isdigit())
        ):
            continue
        original, number = trajectory_attempt(path)
        if original not in selected or number > selected[original][0]:
            selected[original] = (number, path)
    return [selected[original][1] for original in sorted(selected)]


def _summary_candidates(root: Path) -> list[tuple[int, Path]]:
    original = root / "summary.json"
    candidates = [(1, original)] if original.is_file() else []
    for path in root.glob("summary-*.json"):
        suffix = path.stem.removeprefix("summary-")
        if suffix.isdigit() and int(suffix) >= 2:
            candidates.append((int(suffix), path))
    return candidates


def load_latest_summary(root: Path) -> dict[str, Any] | None:
    """Read the latest numbered summary, preserving legacy ``summary.json``.

    A corrupt latest summary raises instead of falling back to stale metrics.
    Unrelated files such as ``summary-diagnostics.json`` are ignored.
    """
    candidates = _summary_candidates(root)
    if not candidates:
        return None
    summary = json.loads(max(candidates)[1].read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise ValueError("An evaluation summary must be a JSON object")
    return summary


def selected_experiment_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace superseded log attempts in place, preserving original trial order.

    Entries without a trajectory path and historical logs without retries keep
    their prior behavior. The caller may retain ``len(entries)`` as the raw
    attempt count; this view is for trial-level statistics.
    """
    paths = [Path(entry["trajectory_path"]) for entry in entries if entry.get("trajectory_path")]
    selected = {trajectory_attempt(path)[0]: path for path in selected_trajectory_paths(paths)}
    latest_entries = {
        Path(entry["trajectory_path"]): entry for entry in entries if entry.get("trajectory_path")
    }
    active = []
    emitted_retries: set[Path] = set()
    for entry in entries:
        if not entry.get("trajectory_path"):
            active.append(entry)
            continue
        path = Path(entry["trajectory_path"])
        original, _ = trajectory_attempt(path)
        latest = selected.get(original)
        if latest is None:
            continue  # A generated sidecar is not a trajectory observation.
        if latest == original:
            active.append(entry)
        elif original not in emitted_retries:
            active.append(latest_entries[latest])
            emitted_retries.add(original)
    return active
