"""Dependency-free, text/tool-only native Ollama bridge for an optional Gym adapter.

The provider transport and native payload construction remain HealthCraft's
OllamaClient. This module validates the narrower experimental interoperability
contract, captures provider envelopes, and translates response shapes without
claiming token IDs, clinical validity, or exact cross-runtime reproducibility.
"""

from __future__ import annotations

import json
import math
import time
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from healthcraft.llm.local_models import LocalModelError, OllamaClient

GYM_REVISION = "82e1834ccf2dd578af26a1abc686c15e17569594"


def _write(path: Path, data: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)
        handle.write("\n")


def _fields(value: dict, allowed: set[str], where: str) -> None:
    unexpected = {key for key, item in value.items() if key not in allowed and item is not None}
    if unexpected:
        raise ValueError(f"Unsupported {where} fields: {sorted(unexpected)}")


def _text(value: Any, kinds: set[str]) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        raise ValueError("Only text content is supported")
    parts = []
    for part in value:
        if not isinstance(part, dict) or part.get("type") not in kinds:
            raise ValueError("Unsupported non-text content")
        _fields(part, {"type", "text", "annotations", "logprobs"}, "text content")
        if part.get("annotations") or part.get("logprobs"):
            raise ValueError("Annotated or token-scored input is unsupported")
        if not isinstance(part.get("text"), str):
            raise ValueError("Text content requires a string")
        parts.append(part["text"])
    return "".join(parts)


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _arguments(value: Any) -> dict:
    if isinstance(value, str):

        def unique(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError("Duplicate JSON argument key")
                result[key] = item
            return result

        value = json.loads(value, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("Function arguments must be a JSON object")
    json.dumps(value, allow_nan=False)
    return deepcopy(value)


def _tools(value: Any, dialect: str) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("Tools must be a list")
    result, names = [], set()
    for tool in value:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            raise ValueError("Only function tools are supported")
        if dialect == "chat":
            _fields(tool, {"type", "function"}, "tool")
            tool = tool.get("function")
        if not isinstance(tool, dict):
            raise ValueError("Function tool must be an object")
        _fields(tool, {"type", "name", "description", "parameters", "strict"}, "function")
        name = _nonempty(tool.get("name"), "Function name")
        if name in names:
            raise ValueError("Duplicate function name")
        names.add(name)
        if tool.get("strict") not in (None, False):
            raise ValueError("Strict schema-constrained decoding is unsupported")
        description, parameters = tool.get("description", ""), tool.get("parameters", {})
        if description is None:
            description = ""
        if not isinstance(description, str) or not isinstance(parameters, dict):
            raise ValueError("Function description/schema has the wrong type")
        result.append(
            {"name": name, "description": description, "parameters": deepcopy(parameters)}
        )
    return result


def _messages(items: Any, dialect: str, instructions: Any) -> list[dict]:
    if isinstance(items, str) and dialect == "responses":
        items = [{"role": "user", "content": items}]
    if not isinstance(items, list) or not items:
        raise ValueError("A nonempty conversation is required")
    messages, pending = [], {}
    if instructions is not None:
        if not isinstance(instructions, str):
            raise ValueError("Instructions must be text")
        messages.append({"role": "system", "content": instructions})

    def add_call(call_id, name, arguments):
        call_id = _nonempty(call_id, "Tool call ID")
        name = _nonempty(name, "Tool name")
        if call_id in pending:
            raise ValueError("Duplicate pending tool call ID")
        pending[call_id] = name
        if not messages or messages[-1]["role"] != "assistant":
            messages.append({"role": "assistant", "content": ""})
        messages[-1].setdefault("tool_calls", []).append(
            {"id": call_id, "name": name, "arguments": _arguments(arguments)}
        )

    def add_result(call_id, content):
        if not isinstance(call_id, str) or call_id not in pending:
            raise ValueError("Orphaned or repeated tool result")
        pending.pop(call_id)
        messages.append({"role": "tool", "tool_call_id": call_id, "content": content})

    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Conversation items must be objects")
        kind = item.get("type", "message")
        if item.get("status") not in (None, "completed"):
            raise ValueError("Incomplete history cannot be resumed as completed output")
        if dialect == "responses" and kind == "function_call":
            _fields(item, {"type", "id", "call_id", "name", "arguments", "status"}, "call")
            add_call(item.get("call_id"), item.get("name"), item.get("arguments"))
        elif dialect == "responses" and kind == "function_call_output":
            _fields(item, {"type", "id", "call_id", "output", "status"}, "result")
            add_result(item.get("call_id"), _text(item.get("output"), {"input_text"}))
        elif kind == "message":
            _fields(
                item,
                {"type", "id", "role", "content", "status", "tool_calls", "tool_call_id"},
                "message",
            )
            role = item.get("role")
            text = _text(
                item.get("content"),
                {"text"} if dialect == "chat" else {"input_text", "output_text"},
            )
            if role == "tool" and dialect == "chat":
                add_result(item.get("tool_call_id"), text)
                continue
            if role not in {"system", "developer", "user", "assistant"}:
                raise ValueError("Unsupported message role")
            if pending:
                raise ValueError("Assistant tool calls must be answered before the next message")
            if item.get("tool_calls") and (dialect != "chat" or role != "assistant"):
                raise ValueError("Only chat assistant messages may contain tool_calls")
            messages.append({"role": role, "content": text})
            for call in item.get("tool_calls") or []:
                if not isinstance(call, dict) or call.get("type") != "function":
                    raise ValueError("Only function tool calls are supported")
                _fields(call, {"id", "type", "function"}, "chat call")
                function = call.get("function")
                if not isinstance(function, dict):
                    raise ValueError("Function call must be an object")
                _fields(function, {"name", "arguments"}, "chat function")
                add_call(call.get("id"), function.get("name"), function.get("arguments"))
        else:
            raise ValueError(f"Unsupported conversation item: {kind}")
    if pending:
        raise ValueError("Unanswered tool calls cannot be sent for further generation")
    return messages


class _RecordingClient(OllamaClient):
    def __init__(self, *, directory: Path, **kwargs):
        super().__init__(**kwargs)
        self.directory = directory
        self.events: list[dict] = []

    def _request(self, path, payload=None):
        if path not in {"/api/tags", "/api/show", "/api/version", "/api/chat"}:
            raise LocalModelError("Unsupported local runtime endpoint")
        event = {"path": path, "request": deepcopy(payload)}
        self.events.append(event)
        try:
            result = super()._request(path, payload)
            event["response"] = deepcopy(result)
            return result
        except Exception as exc:
            event["error"] = {"type": type(exc).__name__, "message": str(exc)}
            raise
        finally:
            _write(self.directory / f"transport-{len(self.events):03d}.json", event)


class NativeOllamaBridge:
    """Fixed-setting native calls with a new exclusive capture directory per attempt."""

    def __init__(
        self,
        *,
        model: str,
        expected_digest: str,
        capture_dir: str | Path,
        output_budget: int,
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 300,
        expected_runtime: str = "0.34.4",
    ) -> None:
        if type(output_budget) is not int or output_budget <= 0:
            raise ValueError("output_budget must be a positive integer")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        self.expected_digest = _nonempty(expected_digest, "Expected model digest")
        self.expected_runtime = _nonempty(expected_runtime, "Expected Ollama runtime")
        self.capture_dir = Path(capture_dir)
        if not self.capture_dir.is_dir():
            raise ValueError("capture_dir must already exist")
        self.client_options = dict(
            model=model, base_url=base_url, seed=42, num_ctx=32768, think=False, timeout=timeout
        )
        # Reuse the native constructor's URL/model validation before any request.
        OllamaClient(**self.client_options)
        self.output_budget = output_budget

    def _normalize(self, body: dict, dialect: str) -> tuple[list[dict], list[dict]]:
        common = {"model", "tools", "temperature", "stream", "tool_choice", "parallel_tool_calls"}
        specific = (
            {"input", "instructions", "max_output_tokens", "reasoning", "store"}
            if dialect == "responses"
            else {"messages", "max_tokens", "seed", "reasoning_effort", "n"}
        )
        _fields(body, common | specific, "request")
        if body.get("model") not in (None, self.client_options["model"]):
            raise ValueError("Request model differs from configured installed alias")
        for field, expected in (("temperature", 0), ("seed", 42), ("n", 1)):
            if body.get(field) is not None and (
                type(body[field]) not in (int, float) or body[field] != expected
            ):
                raise ValueError(f"{field} must equal the configured setting {expected}")
        for field, expected in (("stream", False), ("store", False), ("parallel_tool_calls", True)):
            if body.get(field) is not None and body[field] is not expected:
                raise ValueError(f"Unsupported {field} setting")
        if body.get("tool_choice") not in (None, "auto"):
            raise ValueError("Only automatic tool choice is supported")
        reasoning = body.get("reasoning")
        if reasoning is not None and reasoning != {"effort": "none"}:
            raise ValueError("Only reasoning effort none is supported")
        if body.get("reasoning_effort") not in (None, "none"):
            raise ValueError("Only reasoning effort none is supported")
        budget = body.get("max_output_tokens" if dialect == "responses" else "max_tokens")
        if budget is not None and (type(budget) is not int or budget != self.output_budget):
            raise ValueError("Request output budget must equal the configured positive budget")
        messages = _messages(
            body.get("input" if dialect == "responses" else "messages"),
            dialect,
            body.get("instructions"),
        )
        return messages, _tools(body.get("tools", []), dialect)

    def responses(self, body: dict) -> dict:
        return self._run(body, "responses")

    def chat_completions(self, body: dict) -> dict:
        return self._run(body, "chat")

    def validate_request(self, body: dict, dialect: str) -> None:
        """Check raw input before an optional SDK can discard unsupported fields."""
        if not isinstance(body, dict) or dialect not in {"responses", "chat"}:
            raise ValueError("Unsupported request shape or dialect")
        json.dumps(body, allow_nan=False)
        self._normalize(body, dialect)

    def _run(self, body: dict, dialect: str) -> dict:
        if not isinstance(body, dict):
            raise ValueError("Request must be an object")
        capture_id = uuid4().hex
        directory = self.capture_dir / capture_id
        directory.mkdir()
        _write(directory / "request.json", {"dialect": dialect, "body": body})
        try:
            messages, tools = self._normalize(body, dialect)
            client = _RecordingClient(directory=directory, **self.client_options)
            info = client.validate_capabilities(require_tools=bool(tools))
            if info["model_digest"] != self.expected_digest:
                raise LocalModelError("Installed model digest differs from configured digest")
            if info["runtime_version"] != self.expected_runtime:
                raise LocalModelError("Installed Ollama runtime differs from configured version")
            if "thinking" not in info["capabilities"]:
                raise LocalModelError("This matched profile requires declared thinking capability")
            _write(directory / "provenance.json", {"gym_revision": GYM_REVISION, **info})
            client.chat(messages, tools=tools, temperature=0.0, max_tokens=self.output_budget)
            raw = client.events[-1]["response"]
            result = _response(raw, capture_id, self.client_options["model"], tools, dialect)
            _write(directory / "response.json", result)
            return result
        except Exception as exc:
            _write(directory / "error.json", {"type": type(exc).__name__, "message": str(exc)})
            raise


def _response(raw: dict, capture_id: str, model: str, tools: list[dict], dialect: str) -> dict:
    message = raw.get("message")
    reason = raw.get("done_reason")
    if raw.get("done") is not True or reason not in {"stop", "length", "content_filter"}:
        raise LocalModelError("Missing or unsupported native completion provenance")
    if raw.get("model") != model:
        raise LocalModelError("Native response model differs from the requested installed alias")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise LocalModelError("Native response requires an assistant message")
    if message.get("refusal") or message.get("thinking"):
        raise LocalModelError("Native response contradicts the text/tool-only no-thinking profile")
    content = message.get("content")
    if not isinstance(content, str):
        raise LocalModelError("Native assistant content must be a string")
    status = "completed" if reason == "stop" else "incomplete"
    calls = []
    allowed_names = {tool["name"] for tool in tools}
    for index, call in enumerate(message.get("tool_calls") or []):
        function = call["function"]
        if function.get("name") not in allowed_names:
            raise LocalModelError(
                "Native response called a function not advertised in this request"
            )
        calls.append(
            {
                "id": f"fc_{capture_id}_{index}",
                "call_id": f"call_{capture_id}_{index}",
                "type": "function_call",
                "status": status,
                "name": _nonempty(function.get("name"), "Native function name"),
                "arguments": json.dumps(
                    _arguments(function.get("arguments")), ensure_ascii=False, allow_nan=False
                ),
            }
        )
    counts = [raw.get("prompt_eval_count"), raw.get("eval_count")]
    for count in counts:
        if count is not None and (type(count) is not int or count < 0):
            raise LocalModelError("Native usage must contain nonnegative integer counts")
    usage = None
    if all(count is not None for count in counts):
        usage = {
            "input_tokens": counts[0],
            "output_tokens": counts[1],
            "total_tokens": sum(counts),
            "input_tokens_details": {"cached_tokens": None},
            "output_tokens_details": {"reasoning_tokens": None},
        }
    metadata = {
        "hc_native_done_reason": reason,
        "hc_capture_id": capture_id,
        "hc_execution_kind": ("tool_calls" if calls else "completed")
        if status == "completed"
        else ("max_output_tokens" if reason == "length" else "content_filter"),
    }
    if dialect == "chat":
        chat_message = {"role": "assistant", "content": content}
        if calls:
            chat_message["tool_calls"] = [
                {
                    "id": call["call_id"],
                    "type": "function",
                    "function": {"name": call["name"], "arguments": call["arguments"]},
                }
                for call in calls
            ]
        return {
            "id": f"chatcmpl_{capture_id}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": chat_message,
                    "finish_reason": "tool_calls" if calls and reason == "stop" else reason,
                }
            ],
            "usage": None
            if usage is None
            else {
                "prompt_tokens": counts[0],
                "completion_tokens": counts[1],
                "total_tokens": sum(counts),
            },
            "metadata": metadata,
        }
    output = [
        {
            "id": f"msg_{capture_id}",
            "type": "message",
            "role": "assistant",
            "status": status,
            "content": [{"type": "output_text", "text": content, "annotations": []}],
        }
    ]
    output.extend(calls)
    return {
        "id": f"resp_{capture_id}",
        "object": "response",
        "created_at": time.time(),
        "model": model,
        "status": status,
        "output": output,
        "usage": usage,
        "metadata": metadata,
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "tools": [{"type": "function", **tool, "strict": False} for tool in tools],
        "error": None,
        "incomplete_details": None
        if status == "completed"
        else {"reason": "max_output_tokens" if reason == "length" else "content_filter"},
    }
