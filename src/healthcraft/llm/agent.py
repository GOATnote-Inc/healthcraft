"""LLM agent interface for HEALTHCRAFT evaluation.

Provides a model-agnostic agent that interacts with the MCP server
to solve clinical tasks. Supports Claude, GPT, and Gemini models.

Usage:
    agent = create_agent("claude-opus-4-6", api_key="...")
    trajectory = agent.run_task(task, server)
"""

from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
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
                raise ImportError("anthropic package required: pip install anthropic")

    def _convert_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Convert generic messages to Anthropic format.

        Anthropic requires:
        - System message as separate 'system' parameter
        - Assistant tool calls as content blocks (not 'tool_calls' field)
        - Tool results as role='user' with tool_result content blocks
        """
        system_msg = None
        converted = []

        for msg in messages:
            role = msg["role"]

            if role == "system":
                system_msg = msg["content"]
                continue

            if role == "assistant":
                content_blocks: list[dict[str, Any]] = []
                if msg.get("content"):
                    content_blocks.append({"type": "text", "text": msg["content"]})
                for tc in msg.get("tool_calls", []):
                    content_blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["name"],
                            "input": tc.get("arguments", {}),
                        }
                    )
                converted.append(
                    {
                        "role": "assistant",
                        "content": content_blocks if content_blocks else msg.get("content", ""),
                    }
                )

            elif role == "tool":
                # Anthropic: tool results go in role=user with tool_result blocks
                # Merge consecutive tool results into one user message
                tool_block = {
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": msg.get("content", ""),
                }
                if converted and converted[-1].get("_tool_results"):
                    converted[-1]["content"].append(tool_block)
                else:
                    converted.append(
                        {
                            "role": "user",
                            "content": [tool_block],
                            "_tool_results": True,
                        }
                    )

            else:
                converted.append({"role": role, "content": msg.get("content", "")})

        # Strip internal markers
        for msg in converted:
            msg.pop("_tool_results", None)

        return system_msg, converted

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = MAX_RESPONSE_TOKENS,
    ) -> dict[str, Any]:
        self._ensure_client()

        system_msg, converted_messages = self._convert_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": converted_messages,
            "max_tokens": max_tokens,
        }
        # Claude Opus 4.7+ deprecated `temperature` (API returns 400).
        # Older Claude models still accept it.
        if "4-7" not in self._model:
            kwargs["temperature"] = temperature

        if system_msg:
            kwargs["system"] = system_msg

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
                tool_calls.append(
                    {
                        "id": block.id,
                        "name": block.name,
                        "arguments": block.input,
                    }
                )

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
                raise ImportError("openai package required: pip install openai")

    def _convert_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert generic messages to OpenAI format.

        OpenAI requires:
        - Assistant tool_calls with type='function' and function wrapper
        - Tool call arguments as JSON strings (not dicts)
        - Tool results as role='tool' with tool_call_id
        """
        converted = []
        for msg in messages:
            role = msg["role"]

            if role == "assistant" and msg.get("tool_calls"):
                oai_tool_calls = []
                for tc in msg["tool_calls"]:
                    args = tc.get("arguments", {})
                    if isinstance(args, dict):
                        args = json.dumps(args)
                    oai_tool_calls.append(
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": args,
                            },
                        }
                    )
                converted.append(
                    {
                        "role": "assistant",
                        "content": msg.get("content") or None,
                        "tool_calls": oai_tool_calls,
                    }
                )
            elif role == "tool":
                converted.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.get("tool_call_id", ""),
                        "content": msg.get("content", ""),
                    }
                )
            else:
                converted.append(msg)

        return converted

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = MAX_RESPONSE_TOKENS,
    ) -> dict[str, Any]:
        self._ensure_client()

        converted_messages = self._convert_messages(messages)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": converted_messages,
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
                tool_calls.append(
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": json.loads(tc.function.arguments),
                    }
                )

        return {
            "content": message.content or "",
            "tool_calls": tool_calls,
            "stop_reason": choice.finish_reason,
        }


class GrokClient(OpenAIClient):
    """Client for Grok models via the xAI API (OpenAI-compatible)."""

    def __init__(self, api_key: str, model: str = "grok-4") -> None:
        super().__init__(api_key=api_key, model=model)

    def _ensure_client(self) -> None:
        if self._client is None:
            try:
                import openai

                self._client = openai.OpenAI(
                    api_key=self._api_key,
                    base_url="https://api.x.ai/v1",
                )
            except ImportError:
                raise ImportError("openai package required: pip install openai")


class GeminiClient:
    """Client for Gemini models via the Google Generative AI API."""

    def __init__(self, api_key: str, model: str = "gemini-3.1-pro") -> None:
        self._api_key = api_key
        self._model = model
        self._client: Any = None

    def _ensure_client(self) -> None:
        if self._client is None:
            try:
                from google import genai

                self._client = genai.Client(api_key=self._api_key)
            except ImportError:
                raise ImportError("google-genai package required: pip install google-genai")

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = MAX_RESPONSE_TOKENS,
    ) -> dict[str, Any]:
        self._ensure_client()
        from google.genai import types

        # Extract system instruction
        system_text = None
        contents = []
        for msg in messages:
            role = msg["role"]
            if role == "system":
                system_text = msg["content"]
                continue

            # Map roles: assistant -> model, tool -> function response
            if role == "assistant":
                parts = []
                if msg.get("content"):
                    parts.append(types.Part.from_text(text=msg["content"]))
                for tc in msg.get("tool_calls", []):
                    ts = tc.get("thought_signature")
                    if ts:
                        fc = types.FunctionCall(
                            name=tc["name"],
                            args=tc.get("arguments", {}),
                        )
                        parts.append(
                            types.Part(
                                function_call=fc,
                                thought_signature=base64.b64decode(ts),
                            )
                        )
                    else:
                        parts.append(
                            types.Part.from_function_call(
                                name=tc["name"],
                                args=tc.get("arguments", {}),
                            )
                        )
                contents.append(types.Content(role="model", parts=parts))
            elif role == "tool":
                tc_id = msg.get("tool_call_id", "")
                result_str = msg.get("content", "{}")
                try:
                    result_data = json.loads(result_str)
                except (json.JSONDecodeError, TypeError):
                    result_data = {"result": result_str}
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=tc_id,
                                response=result_data,
                            )
                        ],
                    )
                )
            else:
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=msg.get("content", ""))],
                    )
                )

        # Build tool declarations
        tool_declarations = None
        if tools:
            func_decls = []
            for t in tools:
                func_decls.append(
                    types.FunctionDeclaration(
                        name=t["name"],
                        description=t.get("description", ""),
                        parameters=t.get("parameters", {"type": "object", "properties": {}}),
                    )
                )
            tool_declarations = [types.Tool(function_declarations=func_decls)]

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system_text,
            tools=tool_declarations,
        )

        response = self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=config,
        )

        # Parse response
        content = ""
        tool_calls = []
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if part.text:
                    content += part.text
                elif part.function_call:
                    tc_entry = {
                        "id": f"call_{part.function_call.name}_{len(tool_calls)}",
                        "name": part.function_call.name,
                        "arguments": (
                            dict(part.function_call.args) if part.function_call.args else {}
                        ),
                    }
                    if getattr(part, "thought_signature", None):
                        tc_entry["thought_signature"] = base64.b64encode(
                            part.thought_signature
                        ).decode("ascii")
                    tool_calls.append(tc_entry)

        stop_reason = "stop"
        if tool_calls:
            stop_reason = "tool_calls"

        return {
            "content": content,
            "tool_calls": tool_calls,
            "stop_reason": stop_reason,
        }


def create_client(model: str, api_key: str) -> ModelClient:
    """Create a model client based on model name.

    Args:
        model: Model identifier (e.g., "claude-opus-4-6", "gpt-5.4",
               "gemini-3.1-pro", "grok-4").
        api_key: API key for the model provider.

    Returns:
        A ModelClient instance.
    """
    m = model.lower()
    if "claude" in m or "opus" in m or "sonnet" in m or "haiku" in m:
        return AnthropicClient(api_key=api_key, model=model)
    elif "gpt" in m or "o1" in m or "o3" in m:
        return OpenAIClient(api_key=api_key, model=model)
    elif "gemini" in m:
        return GeminiClient(api_key=api_key, model=model)
    elif "grok" in m:
        return GrokClient(api_key=api_key, model=model)
    else:
        raise ValueError(f"Unknown model provider for: {model}")


def _build_tool_definitions(server: HealthcraftServer) -> list[dict[str, Any]]:
    """Build tool definitions from mcp-tools.json for LLM function calling.

    Loads full JSON Schema parameter definitions so models know what
    arguments each tool accepts. Falls back to sparse definitions if
    the config file is missing.
    """
    tools_config = Path(__file__).parents[3] / "configs" / "mcp-tools.json"
    schema_map: dict[str, dict[str, Any]] = {}
    if tools_config.exists():
        with open(tools_config) as f:
            config = json.load(f)
        schema_map = {t["name"]: t for t in config.get("tools", [])}

    tools = []
    for camel_name in server.available_tools:
        if camel_name in schema_map:
            t = schema_map[camel_name]
            tools.append(
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                }
            )
        else:
            tools.append(
                {
                    "name": camel_name,
                    "description": f"HEALTHCRAFT MCP tool: {camel_name}",
                    "parameters": {"type": "object", "properties": {}},
                }
            )
    return tools


def _build_setting_context(setting: dict[str, Any]) -> str:
    """Format task setting data as contextual information for the agent.

    Includes facility status, resource availability, specialist availability,
    and other environmental details that the agent would know as the
    attending physician. Excludes keys already in the system prompt
    (facility, department) and technical keys (world_seed).
    """
    if not setting:
        return ""

    # Keys handled elsewhere (system prompt or inject)
    skip = {"world_seed", "time", "bed"}
    parts: list[str] = []

    for key, value in setting.items():
        if key in skip:
            continue
        label = key.replace("_", " ").title()
        if isinstance(value, dict):
            sub_parts = []
            for k, v in value.items():
                sub_parts.append(f"  {k.replace('_', ' ').title()}: {v}")
            parts.append(f"{label}:\n" + "\n".join(sub_parts))
        elif isinstance(value, list):
            items = "\n".join(f"  - {item}" for item in value)
            parts.append(f"{label}:\n{items}")
        else:
            parts.append(f"{label}: {value}")

    if not parts:
        return ""

    return "\n\n--- Current Department Status ---\n" + "\n".join(parts)


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

    # Build user message: task description + setting context
    user_content = task.description
    setting_context = _build_setting_context(task.initial_state)
    if setting_context:
        user_content = user_content.rstrip() + "\n" + setting_context

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    traj.add_turn("system", system_prompt)
    traj.add_turn("user", user_content)

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
                {"name": tc["name"], "arguments": tc.get("arguments", {})} for tc in tool_calls
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

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": result_str,
                }
            )

    traj.duration_seconds = time.monotonic() - start_time
    return traj
