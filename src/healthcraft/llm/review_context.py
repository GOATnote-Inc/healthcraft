"""Execution-time evidence for later review; hashes detect drift, not authenticity.

The private snapshot is a normalized loaded Task, not original YAML syntax.
Dates use ISO 8601; tuples become arrays. No arbitrary object stringification.
Only an explicit allowlist may be exported to a masked reviewer packet.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from datetime import date, datetime
from typing import Any

from healthcraft.tasks.loader import Task
from healthcraft.trajectory import Trajectory

SCHEMA_VERSION = "clinical-review-context/v1"


def _normalize(value: Any) -> Any:
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, dict) and all(type(key) is str for key in value):
        return {key: _normalize(item) for key, item in value.items()}
    raise ValueError("Review context requires finite JSON values and string keys")


def context_digest(value: Any) -> str:
    """Hash canonical, strictly normalized JSON."""
    return hashlib.sha256(
        json.dumps(
            _normalize(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def freeze_review_context(
    task: Task,
    effective_criteria: list[dict[str, Any]],
    *,
    rubric_channel: str,
    scenario_context: dict[str, Any],
    checkpoint_identity: str,
    grading_mode: str,
) -> dict[str, Any]:
    """Detach authored sources and the actual effective rubric before execution."""
    if grading_mode not in ("benchmark", "profile_diagnostic"):
        raise ValueError("Unknown review grading mode")
    return _normalize(
        {
            "task": asdict(task),
            "effective_criteria": effective_criteria,
            "rubric_channel": rubric_channel,
            "scenario_context": scenario_context,
            "checkpoint_identity": checkpoint_identity,
            "grading_mode": grading_mode,
        }
    )


def seal_review_context(draft: dict[str, Any], trajectory: Trajectory) -> dict[str, Any]:
    """Bind a frozen source snapshot to the actual captured model interface.

    An incomplete setup can be recorded, but cannot be exported for review.
    Capture completeness is separate from agent completion or grading success.
    """
    payload = _normalize(draft)
    turns = trajectory.to_dict()["turns"]
    user = next((t.get("content") for t in turns if t.get("role") == "user"), None)
    tools = trajectory.metadata.get("agent_tool_definitions")
    payload.update(
        {
            "presented_system": trajectory.system_prompt,
            "presented_user": user,
            "tool_definitions": _normalize(tools),
            "turns_sha256": context_digest(turns),
            "capture_status": "complete"
            if isinstance(user, str) and isinstance(tools, list)
            else "incomplete",
        }
    )
    return {"schema_version": SCHEMA_VERSION, "payload": payload, "sha256": context_digest(payload)}


def validate_review_context(trajectory: dict[str, Any]) -> dict[str, Any]:
    """Return a detached snapshot only if all execution bindings still agree."""
    try:
        metadata = trajectory["metadata"]
        envelope = metadata["review_context"]
        payload = envelope["payload"]
        if envelope["schema_version"] != SCHEMA_VERSION or envelope["sha256"] != context_digest(
            payload
        ):
            raise ValueError("Review context hash or schema mismatch")
        if payload["capture_status"] != "complete":
            raise ValueError("Review context capture is incomplete")
        required_types = {
            "task": dict,
            "effective_criteria": list,
            "scenario_context": dict,
            "rubric_channel": str,
            "checkpoint_identity": str,
            "presented_system": str,
            "presented_user": str,
            "tool_definitions": list,
            "turns_sha256": str,
        }
        if any(type(payload[key]) is not kind for key, kind in required_types.items()):
            raise ValueError("Malformed review context fields")
        if payload["grading_mode"] not in ("benchmark", "profile_diagnostic"):
            raise ValueError("Unknown review grading mode")
        authored_ids = [c["id"] for c in payload["task"]["criteria"]]
        effective_ids = [c["id"] for c in payload["effective_criteria"]]
        if (
            not authored_ids
            or any(not isinstance(cid, str) or not cid for cid in authored_ids + effective_ids)
            or len(set(authored_ids)) != len(authored_ids)
            or len(set(effective_ids)) != len(effective_ids)
            or set(authored_ids) != set(effective_ids)
        ):
            raise ValueError("Effective rubric must preserve every unique authored criterion")
        turns = trajectory["turns"]
        if not isinstance(turns, list) or any(not isinstance(t, dict) for t in turns):
            raise ValueError("Malformed captured turns")
        user = next((t.get("content") for t in turns if t.get("role") == "user"), None)
        bindings = (
            payload["task"]["id"] == trajectory["task_id"],
            payload["rubric_channel"] == trajectory["rubric_channel"],
            payload["checkpoint_identity"] == metadata["checkpoint_identity"],
            payload["presented_system"] == trajectory["system_prompt"],
            payload["presented_user"] == user,
            payload["turns_sha256"] == context_digest(turns),
            all(
                t.get("content") == payload["presented_system"]
                for t in turns
                if t.get("role") == "system"
            ),
            "agent_tool_definitions" not in metadata
            or payload["tool_definitions"] == metadata["agent_tool_definitions"],
            "scenario_context" not in metadata
            or payload["scenario_context"] == metadata["scenario_context"],
        )
        if not all(bindings):
            raise ValueError("Review context does not match captured execution evidence")
        return _normalize(payload)
    except (KeyError, TypeError, AttributeError, StopIteration) as exc:
        raise ValueError("Missing or malformed review context") from exc
