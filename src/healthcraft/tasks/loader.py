"""Task loading from YAML definitions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Task:
    """Immutable task definition loaded from YAML.

    Each task defines a clinical scenario with binary evaluation criteria
    (Corecraft Eq. 1), expected tools, and initial world state configuration.
    """

    id: str
    category: str
    level: int
    title: str
    description: str
    initial_state: dict[str, Any]
    expected_tools: tuple[str, ...]
    criteria: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]
    patient: dict[str, Any] | None = None
    system_prompt_override: str | None = None
    # Kept for backward compatibility / diagnostic analysis
    rubric: dict[str, Any] | None = None


# --- Schema validation ---

_REQUIRED_FIELDS = {"id", "category", "level", "title", "description"}


def _validate_task_dict(data: dict[str, Any], source: str = "") -> list[str]:
    """Validate a task dict against the expected schema.

    Args:
        data: The parsed task dict.
        source: Source file path for error messages.

    Returns:
        List of validation error strings (empty if valid).
    """
    errors: list[str] = []
    prefix = f"{source}: " if source else ""

    for field_name in _REQUIRED_FIELDS:
        if field_name not in data:
            errors.append(f"{prefix}Missing required field: {field_name}")

    if "level" in data:
        level = data["level"]
        if not isinstance(level, int) or not (1 <= level <= 5):
            errors.append(f"{prefix}level must be an integer 1-5, got: {level}")

    # Validate criteria if present
    if "criteria" in data:
        criteria = data["criteria"]
        if not isinstance(criteria, list):
            errors.append(f"{prefix}criteria must be a list")
        else:
            for i, criterion in enumerate(criteria):
                if not isinstance(criterion, dict):
                    errors.append(f"{prefix}criteria[{i}] must be a dict")
                    continue
                if "id" not in criterion:
                    errors.append(f"{prefix}criteria[{i}] missing 'id'")
                if "assertion" not in criterion:
                    errors.append(f"{prefix}criteria[{i}] missing 'assertion'")
                if "verification" not in criterion:
                    errors.append(f"{prefix}criteria[{i}] missing 'verification'")
                elif criterion["verification"] not in ("world_state", "llm_judge", "pattern"):
                    errors.append(
                        f"{prefix}criteria[{i}] verification must be "
                        f"world_state/llm_judge/pattern, got: {criterion['verification']}"
                    )

    return errors


def load_task(path: Path) -> Task:
    """Load a single task from a YAML file.

    Args:
        path: Path to the task YAML file.

    Returns:
        A frozen Task instance.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the YAML is invalid or fails schema validation.
    """
    if not path.exists():
        raise FileNotFoundError(f"Task file not found: {path}")

    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)

    if not isinstance(data, dict):
        raise ValueError(f"Task file must contain a YAML mapping: {path}")

    errors = _validate_task_dict(data, source=str(path))
    if errors:
        raise ValueError("Task validation failed:\n" + "\n".join(errors))

    # Support both naming conventions for world state context
    initial_state = data.get("initial_state") or data.get("setting", {})

    # Support both naming conventions for expected tools
    expected_tools = data.get("expected_tools") or data.get("tools_required", ())

    # Parse criteria (new binary format)
    raw_criteria = data.get("criteria", [])
    criteria = tuple(raw_criteria)

    return Task(
        id=data["id"],
        category=data["category"],
        level=data["level"],
        title=data["title"],
        description=data["description"],
        initial_state=initial_state,
        expected_tools=tuple(expected_tools),
        criteria=criteria,
        metadata=data.get("metadata", {}),
        patient=data.get("patient"),
        system_prompt_override=data.get("system_prompt_override"),
        rubric=data.get("rubric"),
    )


def load_tasks(directory: Path) -> list[Task]:
    """Load all tasks from a directory (recursively).

    Searches for .yaml and .yml files and loads each as a Task.

    Args:
        directory: Root directory to search.

    Returns:
        List of Task instances, sorted by id.

    Raises:
        FileNotFoundError: If the directory does not exist.
    """
    if not directory.exists():
        raise FileNotFoundError(f"Task directory not found: {directory}")

    tasks: list[Task] = []
    errors: list[str] = []

    for path in sorted(directory.rglob("*.y*ml")):
        if path.suffix not in (".yaml", ".yml"):
            continue
        try:
            task = load_task(path)
            tasks.append(task)
        except (ValueError, FileNotFoundError) as e:
            errors.append(str(e))

    if errors:
        import warnings

        for err in errors:
            warnings.warn(f"Skipped invalid task: {err}", stacklevel=2)

    return sorted(tasks, key=lambda t: t.id)
