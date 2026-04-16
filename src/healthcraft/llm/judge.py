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
2. The agent's trajectory, organized into sections:
   - TASK CONTEXT: The system prompt and task description
   - TOOL CALL SUMMARY: A condensed list of all tool calls the agent made
   - AGENT'S FINAL RESPONSE: The agent's complete final output (most important for \
content-based criteria)
   - AGENT'S EARLIER REASONING: Excerpts from intermediate steps

IMPORTANT: For criteria about what the agent communicated, documented, or included \
in its output, focus primarily on the AGENT'S FINAL RESPONSE section. This is where \
discharge instructions, consult notes, handoff documentation, and other clinical \
content appears. The tool call summary shows what information the agent gathered.

Respond with a JSON object:
{
    "satisfied": true/false,
    "evidence": "Brief explanation citing specific text from the trajectory",
    "confidence": "high/medium/low"
}

Rules:
- Base your judgment ONLY on what is in the trajectory
- For tool-use criteria: check the TOOL CALL SUMMARY section
- For content/documentation criteria: check the AGENT'S FINAL RESPONSE section
- For reasoning criteria: check both FINAL RESPONSE and EARLIER REASONING
- If the content exists in the final response, it IS satisfied even if earlier steps \
were incomplete
- Be strict on factual accuracy but fair on format — the agent may use different \
wording than the criterion
"""


def _format_trajectory_for_judge(trajectory_turns: list[dict[str, Any]]) -> str:
    """Format trajectory into structured sections for the judge.

    Long trajectories (30-60 turns) cause judge context overload when
    presented as a flat wall of text. This formatter separates the trajectory
    into clearly labeled sections so the judge can find the final clinical
    response — where most llm_judge criteria are evaluated.

    Structure:
      1. TASK CONTEXT — system prompt excerpt + task description
      2. TOOL CALL SUMMARY — condensed list of all tool calls with key results
      3. AGENT'S FINAL RESPONSE — full text, no truncation
      4. AGENT'S REASONING — key excerpts from intermediate assistant messages
    """
    # Collect sections
    system_text = ""
    task_text = ""
    tool_calls_summary: list[str] = []
    assistant_messages: list[str] = []
    tool_call_count = 0

    for turn in trajectory_turns:
        role = turn.get("role", "unknown")
        content = turn.get("content", "")
        tool_calls = turn.get("tool_calls", [])

        if role == "system":
            system_text = content
        elif role == "user" and not task_text:
            task_text = content
        elif role == "assistant":
            if content and content.strip():
                assistant_messages.append(content)
            for tc in tool_calls:
                tool_call_count += 1
                name = tc.get("name", "unknown")
                args = tc.get("arguments", {})
                args_str = json.dumps(args, default=str)
                if len(args_str) > 150:
                    args_str = args_str[:150] + "..."
                tool_calls_summary.append(f"{tool_call_count}. {name}({args_str})")
        elif role == "tool":
            # Append abbreviated tool result to the most recent tool call
            if tool_calls_summary:
                result_preview = content[:200].replace("\n", " ")
                if len(content) > 200:
                    result_preview += "..."
                tool_calls_summary[-1] += f"\n     → {result_preview}"

    # Build output sections
    sections = []

    # Section 1: Task context
    sections.append("=== TASK CONTEXT ===")
    if system_text:
        sections.append(f"[System prompt excerpt]\n{system_text[:1500]}")
    if task_text:
        sections.append(f"[Task description]\n{task_text[:2000]}")

    # Section 2: Tool call summary
    if tool_calls_summary:
        sections.append(f"=== TOOL CALL SUMMARY ({tool_call_count} calls) ===")
        sections.append("\n".join(tool_calls_summary))

    # Section 3: Final response (MOST IMPORTANT — no truncation)
    if assistant_messages:
        final_response = assistant_messages[-1]
        sections.append("=== AGENT'S FINAL RESPONSE (evaluate criteria against this) ===")
        sections.append(final_response)

        # Section 4: Earlier reasoning (condensed)
        if len(assistant_messages) > 1:
            sections.append("=== AGENT'S EARLIER REASONING (excerpts) ===")
            for i, msg in enumerate(assistant_messages[:-1]):
                # Keep reasoning excerpts brief — focus on clinical decisions
                excerpt = msg[:500]
                if len(msg) > 500:
                    excerpt += "..."
                sections.append(f"[Step {i + 1}]\n{excerpt}")

    return "\n\n".join(sections)


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
            logger.error("Judge evaluation failed for %s: %s", criterion.id, e)
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

    Return contract: the returned dict ALWAYS contains ``"satisfied"``
    (bool). Callers depend on this — ``LLMJudge.evaluate_criterion``
    reads ``result.get("satisfied", False)`` and any code path that
    returns a dict missing the key would default to False silently,
    hiding a parse failure from the audit trail.
    """
    content = content.strip()
    parsed: dict[str, Any] | None = None

    # Try direct JSON parse
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try extracting JSON from markdown code blocks
    if parsed is None:
        for marker in ("```json", "```"):
            if marker in content:
                start = content.index(marker) + len(marker)
                end = content.index("```", start) if "```" in content[start:] else len(content)
                try:
                    parsed = json.loads(content[start:end].strip())
                    break
                except (json.JSONDecodeError, ValueError):
                    pass

    # Try finding JSON object in text
    if parsed is None:
        brace_start = content.find("{")
        brace_end = content.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            try:
                parsed = json.loads(content[brace_start : brace_end + 1])
            except json.JSONDecodeError:
                pass

    # Keyword fallback
    if parsed is None:
        satisfied = any(
            kw in content.lower()
            for kw in ["satisfied", '"satisfied": true', "criterion is satisfied"]
        )
        return {
            "satisfied": satisfied,
            "evidence": f"Parsed from unstructured response: {content[:200]}",
            "confidence": "low",
        }

    # Normalize: guarantee "satisfied" key exists and is bool.
    if "satisfied" not in parsed:
        parsed["satisfied"] = False
    else:
        parsed["satisfied"] = bool(parsed["satisfied"])
    return parsed


def select_judge_model(agent_model: str) -> str:
    """Select a cross-vendor judge model.

    The judge must be a different vendor than the agent to prevent
    self-judging bias.

    Args:
        agent_model: The model used by the agent.

    Returns:
        Model identifier for the judge.
    """
    m = agent_model.lower()
    if "claude" in m or "opus" in m or "sonnet" in m or "haiku" in m:
        return "gpt-5.4"
    elif "gpt" in m:
        return "claude-opus-4-6"
    elif "gemini" in m:
        return "claude-opus-4-6"
    elif "grok" in m:
        return "claude-opus-4-6"
    else:
        return "claude-opus-4-6"
