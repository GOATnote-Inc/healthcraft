"""LLM judge for evaluating criteria against agent trajectories.

Implements cross-vendor judging: the judge model must be different from
the agent model (never self-judge). Evaluates llm_judge criteria by
sending the criterion assertion and the agent's trajectory to the judge.

Usage:
    judge = LLMJudge(client, judge_model="claude-opus-4-6")
    result = judge.evaluate_criterion(criterion, trajectory)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from healthcraft.tasks.rubrics import Criterion, CriterionResult

logger = logging.getLogger("healthcraft.llm.judge")


JUDGE_SYSTEM_PROMPT = """You are a clinical evaluation judge for an emergency medicine \
simulation. Your task is to evaluate whether an AI agent's actions satisfy a specific \
criterion.

You will be given:
1. A criterion assertion (what the agent should have done)
2. The agent's full interaction trajectory (system prompt, messages, tool calls, results)

You must determine if the criterion is SATISFIED or NOT SATISFIED based solely on the \
evidence in the trajectory.

Respond with a JSON object:
{
    "satisfied": true/false,
    "evidence": "Brief explanation of why the criterion is/isn't satisfied",
    "confidence": "high/medium/low"
}

Rules:
- Base your judgment ONLY on what is in the trajectory
- If the criterion mentions a specific action, verify it appears in tool calls
- If the criterion mentions reasoning or diagnosis, verify it appears in agent text
- If insufficient evidence exists, mark as NOT SATISFIED
- Be strict: partial or ambiguous satisfaction counts as NOT SATISFIED
"""


def _format_trajectory_for_judge(trajectory_turns: list[dict[str, Any]]) -> str:
    """Format trajectory turns into a readable string for the judge."""
    lines = []
    for turn in trajectory_turns:
        role = turn.get("role", "unknown")
        content = turn.get("content", "")
        tool_calls = turn.get("tool_calls", [])

        if role == "system":
            lines.append(f"[SYSTEM PROMPT]\n{content[:500]}")
        elif role == "user":
            lines.append(f"[USER/TASK]\n{content[:1000]}")
        elif role == "assistant":
            lines.append(f"[AGENT RESPONSE]\n{content[:1000]}")
            if tool_calls:
                for tc in tool_calls:
                    name = tc.get("name", "unknown")
                    args = tc.get("arguments", {})
                    lines.append(f"  -> Tool call: {name}({json.dumps(args, default=str)[:200]})")
        elif role == "tool":
            lines.append(f"[TOOL RESULT]\n{content[:500]}")

    return "\n\n".join(lines)


class LLMJudge:
    """LLM-based criterion evaluator.

    Uses a cross-vendor LLM to evaluate whether criteria are satisfied
    based on the agent's trajectory.
    """

    def __init__(self, client: Any, judge_model: str = "") -> None:
        """Initialize the judge.

        Args:
            client: A ModelClient instance for the judge model.
            judge_model: Model identifier for logging/tracking.
        """
        self._client = client
        self._judge_model = judge_model

    def evaluate_criterion(
        self,
        criterion: Criterion,
        trajectory_turns: list[dict[str, Any]],
    ) -> CriterionResult:
        """Evaluate a single criterion against a trajectory.

        Args:
            criterion: The criterion to evaluate.
            trajectory_turns: List of trajectory turn dicts.

        Returns:
            CriterionResult with satisfied/evidence.
        """
        traj_text = _format_trajectory_for_judge(trajectory_turns)

        user_prompt = f"""Evaluate this criterion against the agent's trajectory:

CRITERION ID: {criterion.id}
ASSERTION: {criterion.assertion}
DIMENSION: {criterion.dimension}
SAFETY-CRITICAL: {criterion.safety_critical}

--- AGENT TRAJECTORY ---
{traj_text}
--- END TRAJECTORY ---

Respond with JSON: {{"satisfied": true/false, "evidence": "...", "confidence": "..."}}"""

        try:
            response = self._client.chat(
                messages=[
                    {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=500,
            )

            content = response.get("content", "")
            result = _parse_judge_response(content)

            return CriterionResult(
                criterion_id=criterion.id,
                satisfied=result.get("satisfied", False),
                evidence=f"[{self._judge_model}] {result.get('evidence', 'No evidence')}",
            )

        except Exception as e:
            logger.error(
                "Judge evaluation failed for %s: %s", criterion.id, e
            )
            return CriterionResult(
                criterion_id=criterion.id,
                satisfied=False,
                evidence=f"Judge error: {e}",
            )

    def evaluate_criteria(
        self,
        criteria: list[Criterion],
        trajectory_turns: list[dict[str, Any]],
    ) -> list[CriterionResult]:
        """Evaluate multiple criteria against a trajectory.

        Only evaluates criteria with verification=llm_judge.

        Args:
            criteria: List of criteria to evaluate.
            trajectory_turns: List of trajectory turn dicts.

        Returns:
            List of CriterionResult for llm_judge criteria.
        """
        results = []
        for criterion in criteria:
            if criterion.verification.value == "llm_judge":
                result = self.evaluate_criterion(criterion, trajectory_turns)
                results.append(result)
        return results


def _parse_judge_response(content: str) -> dict[str, Any]:
    """Parse the judge's JSON response.

    Handles both clean JSON and JSON embedded in text/markdown.
    """
    content = content.strip()

    # Try direct JSON parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try extracting JSON from markdown code blocks
    for marker in ("```json", "```"):
        if marker in content:
            start = content.index(marker) + len(marker)
            end = content.index("```", start) if "```" in content[start:] else len(content)
            try:
                return json.loads(content[start:end].strip())
            except (json.JSONDecodeError, ValueError):
                pass

    # Try finding JSON object in text
    brace_start = content.find("{")
    brace_end = content.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        try:
            return json.loads(content[brace_start:brace_end + 1])
        except json.JSONDecodeError:
            pass

    # Fallback: look for keywords
    satisfied = any(
        kw in content.lower()
        for kw in ["satisfied", '"satisfied": true', "criterion is satisfied"]
    )
    return {
        "satisfied": satisfied,
        "evidence": f"Parsed from unstructured response: {content[:200]}",
        "confidence": "low",
    }


def select_judge_model(agent_model: str) -> str:
    """Select a cross-vendor judge model.

    The judge must be a different vendor than the agent to prevent
    self-judging bias.

    Args:
        agent_model: The model used by the agent.

    Returns:
        Model identifier for the judge.
    """
    if "claude" in agent_model.lower() or "opus" in agent_model.lower():
        return "gpt-5.2"
    elif "gpt" in agent_model.lower():
        return "claude-opus-4-6"
    elif "gemini" in agent_model.lower():
        return "claude-opus-4-6"
    else:
        return "claude-opus-4-6"
