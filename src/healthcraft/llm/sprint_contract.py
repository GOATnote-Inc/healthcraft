"""Sprint contracts for HEALTHCRAFT evaluation (Harness Pattern).

A sprint contract is an agreement between the Generator (agent) and Evaluator
(judge) about what "done" looks like for a specific task. The contract is
generated from the task YAML and enriches it with:
  - Explicit success threshold
  - Safety criteria IDs (for hard gate)
  - Tool call budget
  - Evaluator configuration (model, temperature, skepticism)
  - Verification breakdown (how many criteria per method)

Sprint contracts bridge the gap between high-level task definitions and
testable evaluation criteria, following the Anthropic Harness Pattern's
sprint contract concept.

Usage:
    from healthcraft.llm.sprint_contract import SprintContract
    contract = SprintContract.from_task(task)
    contract.save(path)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from healthcraft.tasks.loader import Task


@dataclass
class EvaluatorConfig:
    """Configuration for the evaluator side of the contract."""

    judge_model: str = "gpt-5.4"
    temperature: float = 0.0
    skepticism: str = "default"
    max_tokens: int = 500


@dataclass
class SprintContract:
    """Agreement between generator and evaluator for a single task evaluation.

    The contract defines:
    - What the agent must accomplish (criteria)
    - How success is measured (thresholds, verification methods)
    - What resources the agent has (tool budget)
    - How the evaluator will judge (model, skepticism)
    """

    task_id: str
    category: str
    title: str
    criteria_ids: list[str]
    safety_criteria_ids: list[str]
    total_criteria: int
    success_threshold: float  # fraction of criteria that must pass
    safety_gate: bool  # whether safety gate is enforced
    max_tool_calls: int  # tool call budget for the agent
    verification_breakdown: dict[str, int]  # {method: count}
    evaluator_config: EvaluatorConfig = field(default_factory=EvaluatorConfig)
    agent_model: str = ""
    seed: int = 42
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    @classmethod
    def from_task(
        cls,
        task: Task,
        agent_model: str = "",
        judge_model: str = "gpt-5.4",
        skepticism: str = "default",
        seed: int = 42,
        max_tool_calls: int = 25,
    ) -> SprintContract:
        """Generate a sprint contract from a task definition.

        Args:
            task: The task definition with criteria.
            agent_model: Model identifier for the agent.
            judge_model: Model identifier for the judge.
            skepticism: Evaluator skepticism level.
            seed: Random seed for deterministic evaluation.
            max_tool_calls: Maximum tool calls the agent may use.

        Returns:
            A SprintContract.
        """
        criteria_ids = []
        safety_ids = []
        verification_counts: dict[str, int] = {}

        for raw in task.criteria:
            cid = raw["id"]
            criteria_ids.append(cid)
            if raw.get("safety_critical", False):
                safety_ids.append(cid)
            method = raw.get("verification", "world_state")
            verification_counts[method] = verification_counts.get(method, 0) + 1

        # Infer tool call budget from task metadata
        expected = ""
        if hasattr(task, "metadata") and task.metadata:
            expected = task.metadata.get("expected_tool_calls", "")
        if expected and "-" in str(expected):
            # Range like "8-12" -> take upper bound
            try:
                max_tool_calls = int(str(expected).split("-")[1])
            except (IndexError, ValueError):
                pass
        elif expected:
            try:
                max_tool_calls = int(expected)
            except (ValueError, TypeError):
                pass

        return cls(
            task_id=task.id,
            category=task.category,
            title=task.title,
            criteria_ids=criteria_ids,
            safety_criteria_ids=safety_ids,
            total_criteria=len(criteria_ids),
            success_threshold=1.0,  # all criteria must pass for task pass
            safety_gate=len(safety_ids) > 0,
            max_tool_calls=max_tool_calls,
            verification_breakdown=verification_counts,
            evaluator_config=EvaluatorConfig(
                judge_model=judge_model,
                skepticism=skepticism,
            ),
            agent_model=agent_model,
            seed=seed,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> SprintContract:
        data = json.loads(path.read_text(encoding="utf-8"))
        eval_config = data.pop("evaluator_config", {})
        data["evaluator_config"] = EvaluatorConfig(**eval_config)
        return cls(**data)

    def summary(self) -> str:
        """Human-readable contract summary."""
        lines = [
            f"Sprint Contract: {self.task_id} ({self.title})",
            f"  Category: {self.category}",
            f"  Criteria: {self.total_criteria} total, "
            f"{len(self.safety_criteria_ids)} safety-critical",
            f"  Verification: {self.verification_breakdown}",
            f"  Tool budget: {self.max_tool_calls} calls",
            f"  Success threshold: {self.success_threshold:.0%}",
            f"  Safety gate: {'yes' if self.safety_gate else 'no'}",
            f"  Evaluator: {self.evaluator_config.judge_model} "
            f"(skepticism={self.evaluator_config.skepticism})",
        ]
        if self.agent_model:
            lines.insert(1, f"  Agent: {self.agent_model}")
        return "\n".join(lines)
