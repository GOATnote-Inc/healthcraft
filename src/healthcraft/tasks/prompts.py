"""Task-aware prompt composition shared by live and simulated evaluation."""

from __future__ import annotations

import errno
from pathlib import Path

from healthcraft.tasks.loader import Task

_FALLBACK = "You are an emergency physician at Mercy Point Emergency Department."


def compose_system_prompt(task: Task, directory: Path, components: tuple[str, ...]) -> str:
    """Preserve the caller's base/override selection, then append literal text.

    Override values retain their existing file-or-literal behavior. Append
    values are always literal task instructions, including strings that happen
    to name files. Absent/null/empty append values leave prompt bytes unchanged.
    Downstream agent and RL APIs accept this completed prompt unchanged.
    """
    append = task.system_prompt_append
    if append is not None and not isinstance(append, str):
        raise ValueError("system_prompt_append must be a string or null")

    if task.system_prompt_override:
        override_path = directory / task.system_prompt_override
        try:
            override_exists = override_path.exists()
        except OSError as exc:
            if exc.errno != errno.ENAMETOOLONG:
                raise
            # A literal prompt can exceed filename limits on Python 3.10/3.12.
            override_exists = False
        prompt = (
            override_path.read_text(encoding="utf-8")
            if override_exists
            else task.system_prompt_override
        )
    else:
        parts = [
            (directory / filename).read_text(encoding="utf-8")
            for filename in components
            if (directory / filename).exists()
        ]
        prompt = "\n\n".join(parts) if parts else _FALLBACK

    return prompt + "\n\n" + append if append else prompt
