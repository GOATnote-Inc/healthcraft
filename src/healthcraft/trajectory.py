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

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_jsonl(self) -> str:
        """Serialize to a single JSONL line."""
        return json.dumps(asdict(self), default=str)

    @classmethod
    def from_trajectory(cls, traj: Trajectory, trajectory_path: str) -> ExperimentEntry:
        """Create an experiment entry from a completed trajectory."""
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
