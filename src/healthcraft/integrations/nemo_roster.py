"""Dependency-free session logic for an opt-in mechanical Gym resource server."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from healthcraft.mcp.server import create_server
from healthcraft.tasks.history_execution import ExecutionRecorder
from healthcraft.tasks.loader import Task, load_task
from healthcraft.tasks.roster_certificate import verify_roster_retrieval
from healthcraft.tasks.roster_profile import PROFILE_VERSION, build_roster_profile
from healthcraft.trajectory import trajectory_completion
from healthcraft.world.state import WorldState

FIXTURE_KEY = "cc022-roster-source-retrieval/v1"
MECHANICAL_PROMPT = (
    "Retrieve the full encounter details for every encounter in this episode using the "
    "available tools. Discover the records through search. Finish with a short completion "
    "message. This is a source-retrieval exercise, not a clinical decision task."
)
TOOL_NAMES = ("searchEncounters", "getEncounterDetails", "getPatientHistory")
ROOT = Path(__file__).resolve().parents[3]
TASK_PATH = ROOT / "configs/tasks/clinical_communication/task_022_nurse_delegation.yaml"


def tool_definitions() -> list[dict]:
    """Return the unchanged source-of-truth schemas for both comparison arms."""
    tools = json.loads((ROOT / "configs/mcp-tools.json").read_text())["tools"]
    return [
        {key: deepcopy(tool[key]) for key in ("name", "description", "parameters")}
        for tool in tools
        if tool["name"] in TOOL_NAMES
    ]


def response_completion(response: dict) -> tuple[str, str]:
    """Check Gym's final episode response separately from resource retrieval.

    The response is controller-supplied completion evidence, never an expected
    answer or a substitute for server-held tool captures. This is not an
    authenticated transcript-verification protocol.
    """
    if response.get("error") is not None or response.get("status") in {
        "failed",
        "incomplete",
        "cancelled",
        "in_progress",
        "queued",
    }:
        return "incomplete", "Gym response did not complete normally"
    if response.get("status") != "completed":
        return "unknown", "Explicit completed Gym response status is missing"
    if response.get("incomplete_details") is not None:
        return "unknown", "Completed status conflicts with incomplete details"
    output = response.get("output")
    if not isinstance(output, list):
        return "unknown", "Missing response output"
    turns = []
    for item in output:
        if not isinstance(item, dict):
            return "unknown", "Malformed response output"
        if item.get("status") in {"incomplete", "in_progress"}:
            return "incomplete", "An output item remains incomplete"
        kind = item.get("type")
        if kind == "reasoning":
            continue
        if kind == "function_call":
            turns.append(
                {"role": "assistant", "content": "", "tool_calls": [{"id": item.get("call_id")}]}
            )
        elif kind == "function_call_output":
            turns.append(
                {"role": "tool", "content": item.get("output"), "tool_call_id": item.get("call_id")}
            )
        elif kind == "message":
            content = item.get("content")
            if not isinstance(content, list):
                return "unknown", "Malformed assistant content"
            if any(isinstance(part, dict) and part.get("type") == "refusal" for part in content):
                return "incomplete", "Provider refused the task"
            if any(
                not isinstance(part, dict)
                or part.get("type") != "output_text"
                or not isinstance(part.get("text"), str)
                for part in content
            ):
                return "unknown", "Unsupported assistant content"
            turns.append(
                {"role": item.get("role"), "content": "".join(part["text"] for part in content)}
            )
        else:
            return "unknown", "Unsupported response output item"
    return trajectory_completion(turns, {"stop_reason": "stop"}, None)


class SessionError(ValueError):
    """Explicit lifecycle or unsupported-route failure."""


@dataclass
class _Session:
    episode_id: str
    world: WorldState
    task: Task
    context: dict
    recorder: ExecutionRecorder
    fixture_sha256: str


class RosterSessions:
    """Fresh worlds and immutable captures keyed by Gym's cookie session ID."""

    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._closed: dict[str, str] = {}

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    def _session(self, session_id: str) -> _Session:
        if session_id in self._closed:
            raise SessionError("Resources session is closed; use a fresh cookie session")
        if session_id not in self._sessions:
            raise SessionError("Resources session was not seeded")
        return self._sessions[session_id]

    def seed(self, session_id: str, fixture_key: str, episode_id: str) -> dict:
        if fixture_key != FIXTURE_KEY:
            raise SessionError("Unknown mechanical fixture")
        if not isinstance(session_id, str) or not session_id.strip():
            raise SessionError("A cookie session identity is required")
        if not isinstance(episode_id, str) or not episode_id.strip():
            raise SessionError("A nonempty episode identity is required")
        if session_id in self._closed:
            raise SessionError("Resources session is closed; use a fresh cookie session")
        if session_id in self._sessions:
            if self._sessions[session_id].episode_id != episode_id:
                raise SessionError("Conflicting episode identity for existing resources session")
        else:
            task = load_task(TASK_PATH)
            world = WorldState(start_time=datetime(2026, 1, 15, 3, tzinfo=timezone.utc))
            context = build_roster_profile(world, task)
            fixture = {
                "fixture_key": FIXTURE_KEY,
                "context": context,
                "tools": tool_definitions(),
                "clock": world.timestamp.isoformat(),
                "world_preparation": "minimal_roster_only",
            }
            digest = hashlib.sha256(json.dumps(fixture, sort_keys=True).encode()).hexdigest()
            self._sessions[session_id] = _Session(
                episode_id,
                world,
                task,
                context,
                ExecutionRecorder(create_server(world), world),
                digest,
            )
        return {
            "resources_session_id": session_id,
            "episode_id": episode_id,
            "fixture_key": FIXTURE_KEY,
        }

    def call(self, session_id: str, name: str, params: dict) -> dict:
        session = self._session(session_id)
        if name not in TOOL_NAMES:
            raise SessionError("Tool is outside the mechanical fixture allowlist")
        return session.recorder.call(name, params)

    def verify(self, session_id: str, episode_id: str, completion: str) -> dict:
        session = self._session(session_id)
        if episode_id != session.episode_id:
            raise SessionError("Verification episode does not match the resources session")
        if completion not in {"complete", "incomplete", "unknown"}:
            raise ValueError("Invalid execution completion state")
        result = {
            "fixture_key": FIXTURE_KEY,
            "profile_version": PROFILE_VERSION,
            "fixture_sha256": session.fixture_sha256,
            "world_preparation": "minimal_roster_only",
            "reward_scope": "mechanical_retrieval_only",
            "benchmark_comparable": False,
            "benchmark_score": None,
            "grading_complete": False,
            "clinical_validation": "not_assessed",
            "execution_completed": completion == "complete",
            "completion_status": completion,
        }
        try:
            certificate = verify_roster_retrieval(
                session.task, session.context, session.recorder.calls, session.world
            )
        except (ValueError, TypeError) as exc:
            return {
                **result,
                "reward": 0.0,
                "mechanical_passed": False,
                "mask_sample": True,
                "failure_kind": "verifier_error",
                "failure_reason": str(exc),
                "certificate": None,
            }
        passed = completion == "complete" and certificate["mechanical_passed"]
        return {
            **result,
            "reward": float(passed),
            "mechanical_passed": passed,
            "mask_sample": False,
            "failure_kind": "healthcraft:incomplete_execution"
            if completion != "complete"
            else None,
            "failure_reason": "Completion was not established"
            if completion != "complete"
            else None,
            "certificate": certificate,
        }

    def snapshot(self, session_id: str) -> dict:
        """Export trusted controller evidence before close; never an agent tool."""
        session = self._session(session_id)
        return deepcopy(
            {
                "fixture_key": FIXTURE_KEY,
                "episode_id": session.episode_id,
                "fixture_sha256": session.fixture_sha256,
                "world_preparation": "minimal_roster_only",
                "context": session.context,
                "calls": session.recorder.calls,
            }
        )

    def close(self, session_id: str, resources_session_id: str, episode_id: str) -> dict:
        if resources_session_id != session_id:
            raise SessionError("Close identity does not match the cookie session")
        session = self._session(session_id)
        if session.episode_id != episode_id:
            raise SessionError("Close episode does not match the resources session")
        del self._sessions[session_id]
        self._closed[session_id] = episode_id
        return {"resources_session_id": session_id}
