"""LLM agent interface for HEALTHCRAFT evaluation.

Provides a model-agnostic agent that interacts with the MCP server
to solve clinical tasks. Supports Claude, GPT, and Gemini models.

Usage:
    agent = create_agent("claude-opus-4-6", api_key="...")
    trajectory = agent.run_task(task, server)
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Protocol

from healthcraft.mcp.server import HealthcraftServer
from healthcraft.tasks.loader import Task
from healthcraft.trajectory import Trajectory

logger = logging.getLogger("healthcraft.llm.agent")

# Maximum tool call rounds per task (prevent infinite loops)
MAX_TOOL_ROUNDS = 25

# Maximum tokens for agent response
MAX_RESPONSE_TOKENS = 4096


class ModelClient(Protocol):
    """Protocol for model API clients."""

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = MAX_RESPONSE_TOKENS,
    ) -> dict[str, Any]:
        """Send a chat completion request.

        Returns:
            Dict with 'content' (str), 'tool_calls' (list[dict]), 'stop_reason' (str).
        """
        ...


class AnthropicClient:
    """Client for Claude models via the Anthropic API."""

    def __init__(self, api_key: str, model: str = "claude-opus-4-6") -> None:
        self._api_key = api_key
        self._model = model
        self._client: Any = None

    def _ensure_client(self) -> None:
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self._api_key)
            except ImportError:
                raise ImportError(
                    "anthropic package required: pip install anthropic"
                )

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = MAX_RESPONSE_TOKENS,
    ) -> dict[str, Any]:
        self._ensure_client()

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # Extract system message
        system_msg = None
        filtered_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                filtered_messages.append(msg)
        if system_msg:
            kwargs["system"] = system_msg
            kwargs["messages"] = filtered_messages

        if tools:
            kwargs["tools"] = [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "input_schema": t.get("parameters", {"type": "object"}),
                }
                for t in tools
            ]

        response = self._client.messages.create(**kwargs)

        content = ""
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "arguments": block.input,
                })

        return {
            "content": content,
            "tool_calls": tool_calls,
            "stop_reason": response.stop_reason,
        }


class OpenAIClient:
    """Client for GPT models via the OpenAI API."""

    def __init__(self, api_key: str, model: str = "gpt-5.4") -> None:
        self._api_key = api_key
        self._model = model
        self._client: Any = None

    def _ensure_client(self) -> None:
        if self._client is None:
            try:
                import openai
                self._client = openai.OpenAI(api_key=self._api_key)
            except ImportError:
                raise ImportError(
                    "openai package required: pip install openai"
                )

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = MAX_RESPONSE_TOKENS,
    ) -> dict[str, Any]:
        self._ensure_client()

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }

        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {"type": "object"}),
                    },
                }
                for t in tools
            ]

        response = self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        message = choice.message

        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments),
                })

        return {
            "content": message.content or "",
            "tool_calls": tool_calls,
            "stop_reason": choice.finish_reason,
        }


def create_client(model: str, api_key: str) -> ModelClient:
    """Create a model client based on model name.

    Args:
        model: Model identifier (e.g., "claude-opus-4-6", "gpt-5.4").
        api_key: API key for the model provider.

    Returns:
        A ModelClient instance.
    """
    if "claude" in model.lower() or "opus" in model.lower() or "sonnet" in model.lower():
        return AnthropicClient(api_key=api_key, model=model)
    elif "gpt" in model.lower() or "o1" in model.lower() or "o3" in model.lower():
        return OpenAIClient(api_key=api_key, model=model)
    else:
        raise ValueError(f"Unknown model provider for: {model}")


def _build_tool_definitions(server: HealthcraftServer) -> list[dict[str, Any]]:
    """Build tool definitions from the MCP server for LLM function calling."""
    tools = []
    for camel_name in server.available_tools:
        tools.append({
            "name": camel_name,
            "description": f"HEALTHCRAFT MCP tool: {camel_name}",
            "parameters": {"type": "object", "properties": {}},
        })
    return tools


def run_agent_task(
    client: ModelClient,
    task: Task,
    server: HealthcraftServer,
    system_prompt: str,
) -> Trajectory:
    """Run an LLM agent on a task, capturing the full trajectory.

    The agent interacts with the MCP server via tool calls until it
    either stops calling tools or hits the MAX_TOOL_ROUNDS limit.

    Args:
        client: The model client to use.
        task: The task definition.
        server: The MCP server for tool dispatch.
        system_prompt: The system prompt for the agent.

    Returns:
        A Trajectory capturing the full interaction.
    """
    traj = Trajectory(
        task_id=task.id,
        model="unknown",
        seed=42,
        system_prompt=system_prompt,
        metadata={
            "category": task.category,
            "level": task.level,
            "title": task.title,
        },
    )

    tools = _build_tool_definitions(server)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task.description},
    ]

    traj.add_turn("system", system_prompt)
    traj.add_turn("user", task.description)

    start_time = time.monotonic()

    for round_num in range(MAX_TOOL_ROUNDS):
        try:
            response = client.chat(messages, tools=tools)
        except Exception as e:
            logger.error("API call failed on round %d: %s", round_num + 1, e)
            traj.error = f"API error on round {round_num + 1}: {e}"
            break

        content = response["content"]
        tool_calls = response["tool_calls"]

        # Record assistant turn
        traj.add_turn(
            "assistant",
            content,
            tool_calls=[
                {"name": tc["name"], "arguments": tc.get("arguments", {})}
                for tc in tool_calls
            ],
        )

        # Add assistant message to conversation
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        # If no tool calls, the agent is done
        if not tool_calls:
            break

        # Execute tool calls and add results
        for tc in tool_calls:
            tool_name = tc["name"]
            tool_args = tc.get("arguments", {})
            tool_result = server.call_tool(tool_name, tool_args)

            result_str = json.dumps(tool_result, default=str)

            # Record tool result turn
            traj.add_turn(
                "tool",
                result_str,
                tool_call_id=tc.get("id", ""),
            )

            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": result_str,
            })

    traj.duration_seconds = time.monotonic() - start_time
    return traj
