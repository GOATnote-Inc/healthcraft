"""Trajectory capture for HEALTHCRAFT evaluation runs.

Captures full agent interactions (system prompt, messages, tool calls, results)
in a structured format for replay, RL training, and analysis.

Trajectory format follows Corecraft Section 5.2.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def is_unassessed_experiment(entry: dict) -> bool:
    """Recognize explicit ungraded markers in logs, trajectories, or summaries.

    Missing legacy provenance remains unknown rather than being retroactively
    relabeled. A false marker at either level wins over any optimistic marker.
    """
    metadata = entry.get("metadata", {})
    for data in (entry, metadata):
        if not isinstance(data, dict):
            continue
        scenario = data.get("scenario_context", {})
        if (
            data.get("scenario_profile")
            or (isinstance(scenario, dict) and scenario.get("profile_version"))
            or data.get("evaluation_mode") == "profile_diagnostic"
            or data.get("benchmark_comparable") is False
            or data.get("grading_complete") is False
            or ("benchmark_score" in data and data["benchmark_score"] is None)
        ):
            return True
        ungraded = data.get("ungraded_criteria")
        if type(ungraded) is int and ungraded > 0:
            return True
    return False


def trajectory_completion(turns: Any, metadata: dict, error: Any) -> tuple[str, str]:
    """Check explicit termination and complete tool-response linkage."""
    if error is not None:
        return "incomplete", "Execution interrupted by a recorded error"
    stop = metadata.get("stop_reason")
    if not isinstance(stop, str) or stop not in {"stop", "end_turn", "stop_sequence"}:
        if isinstance(stop, str) and stop in {
            "tool_round_limit",
            "length",
            "max_tokens",
            "max_output_tokens",
            "error",
            "content_filter",
            "refusal",
            "pause_turn",
            "tool_calls",
            "tool_use",
        }:
            return "incomplete", f"Execution did not complete normally: {stop}"
        return (
            "unknown",
            "Completion provenance missing or unknown; recorded scores remain unverified",
        )
    if "termination_kind" in metadata and metadata["termination_kind"] != "complete":
        return "unknown", "Final stop conflicts with termination_kind; completion is unverified"
    if metadata.get("provider_refusal") not in (None, "", False):
        return "unknown", "Final stop conflicts with recorded provider refusal"
    if not isinstance(turns, list) or not turns or any(not isinstance(t, dict) for t in turns):
        return "unknown", "Completion cannot be checked against malformed or missing turns"
    final = turns[-1]
    if (
        final.get("role") != "assistant"
        or final.get("tool_calls")
        or not isinstance(final.get("content"), str)
    ):
        return "incomplete", "No terminal assistant response without tool calls"
    pending = set()
    for turn in turns:
        calls = turn.get("tool_calls", [])
        if not isinstance(calls, list):
            return "unknown", "Malformed tool-call list prevents completion verification"
        for call in calls:
            call_id = call.get("id") if isinstance(call, dict) else None
            if (
                turn.get("role") != "assistant"
                or not isinstance(call_id, str)
                or not call_id
                or call_id in pending
            ):
                return (
                    "unknown",
                    "Missing or ambiguous tool-call identity prevents response linkage",
                )
            pending.add(call_id)
        if turn.get("role") == "tool":
            call_id = turn.get("tool_call_id")
            if not isinstance(call_id, str) or call_id not in pending:
                return "unknown", "Tool response cannot be linked to a preceding unanswered call"
            pending.remove(call_id)
    if pending:
        return "incomplete", "Unanswered tool calls remain in the recorded conversation"
    return "complete", ""


@dataclass
class TrajectoryTurn:
    """A single turn in an agent interaction."""

    role: str  # "user", "assistant", "tool", "system"
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str = ""
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class CriterionEvalResult:
    """Result of evaluating a single criterion in a trajectory."""

    id: str
    satisfied: bool
    evidence: str = ""


@dataclass
class Trajectory:
    """Complete trajectory of an agent evaluation run.

    Captures everything needed for:
    - Replay: exact tool calls and responses
    - RL training: reward signal from criteria
    - Analysis: per-criterion and per-dimension breakdowns
    """

    task_id: str
    model: str
    seed: int
    system_prompt: str
    turns: list[TrajectoryTurn] = field(default_factory=list)
    criteria_results: list[CriterionEvalResult] = field(default_factory=list)
    reward: float = 0.0
    passed: bool = False
    safety_gate_passed: bool = True
    dimension_scores: dict[str, float] = field(default_factory=dict)
    # Grading provenance — which rubric channel produced reward/passed/safety.
    # Without it a trajectory file alone cannot prove it was graded at v10 vs v8
    # (v11 audit finding D4-F4). Default "" keeps older trajectory files loadable.
    rubric_channel: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    duration_seconds: float = 0.0
    total_tool_calls: int = 0
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def add_turn(
        self,
        role: str,
        content: str = "",
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str = "",
    ) -> TrajectoryTurn:
        """Add a turn to the trajectory."""
        turn = TrajectoryTurn(
            role=role,
            content=content,
            tool_calls=tool_calls or [],
            tool_call_id=tool_call_id,
        )
        self.turns.append(turn)
        if tool_calls:
            self.total_tool_calls += len(tool_calls)
        return turn

    def set_results(
        self,
        criteria_results: list[CriterionEvalResult],
        reward: float,
        passed: bool,
        safety_gate_passed: bool,
        dimension_scores: dict[str, float],
    ) -> None:
        """Set evaluation results after the run completes."""
        self.criteria_results = criteria_results
        self.reward = reward
        self.passed = passed
        self.safety_gate_passed = safety_gate_passed
        self.dimension_scores = dimension_scores

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary."""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def save(self, path: Path) -> Path:
        """Save trajectory to a JSON file.

        Creates parent directories if needed.

        Returns:
            The path the trajectory was saved to.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> Trajectory:
        """Load a trajectory from a JSON file."""
        data = json.loads(path.read_text(encoding="utf-8"))
        turns = [TrajectoryTurn(**t) for t in data.pop("turns", [])]
        criteria = [CriterionEvalResult(**c) for c in data.pop("criteria_results", [])]
        traj = cls(**data)
        traj.turns = turns
        traj.criteria_results = criteria
        return traj


@dataclass
class ExperimentEntry:
    """A single entry in the experiments log (results/experiments.jsonl)."""

    task_id: str
    model: str
    seed: int
    reward: float
    passed: bool
    safety_gate_passed: bool
    total_tool_calls: int
    duration_seconds: float
    trajectory_path: str
    timestamp: str = ""
    error: str | None = None
    # None preserves the unknown provenance of legacy experiment rows.
    scenario_profile: str | None = None
    grading_complete: bool | None = None
    benchmark_comparable: bool | None = None
    execution_completed: bool | None = None
    failure_stage: str | None = None

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_jsonl(self) -> str:
        """Serialize to a single JSONL line."""
        return json.dumps(asdict(self), default=str)

    @classmethod
    def from_trajectory(cls, traj: Trajectory, trajectory_path: str) -> ExperimentEntry:
        """Create an experiment entry from a completed trajectory."""
        metadata = traj.metadata
        scenario = metadata.get("scenario_context", {})
        profile = metadata.get("scenario_profile") or (
            scenario.get("profile_version") if isinstance(scenario, dict) else None
        )
        unassessed = is_unassessed_experiment({"metadata": metadata})
        completion, _ = trajectory_completion(
            [asdict(turn) for turn in traj.turns], metadata, traj.error
        )
        completed = None if completion == "unknown" else completion == "complete"
        return cls(
            task_id=traj.task_id,
            model=traj.model,
            seed=traj.seed,
            reward=traj.reward,
            passed=traj.passed,
            safety_gate_passed=traj.safety_gate_passed,
            total_tool_calls=traj.total_tool_calls,
            duration_seconds=traj.duration_seconds,
            trajectory_path=trajectory_path,
            timestamp=traj.timestamp,
            error=traj.error,
            scenario_profile=profile,
            grading_complete=False if unassessed else metadata.get("grading_complete"),
            benchmark_comparable=False if unassessed else metadata.get("benchmark_comparable"),
            execution_completed=completed,
            failure_stage=metadata.get("failure_stage"),
        )


class ExperimentLog:
    """Append-only experiment log (results/experiments.jsonl)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, entry: ExperimentEntry) -> None:
        """Append an experiment entry to the log."""
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(entry.to_jsonl() + "\n")

    def load_all(self) -> list[ExperimentEntry]:
        """Load all entries from the log."""
        if not self._path.exists():
            return []
        entries = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                data = json.loads(line)
                entries.append(ExperimentEntry(**data))
        return entries

    @property
    def path(self) -> Path:
        return self._path
