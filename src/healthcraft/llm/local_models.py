"""Keyless local inference through Ollama's native API.

Local model identifiers are explicit: ``ollama:<installed-model-name>``. The
client never pulls weights, uses API keys, follows redirects, or switches to a
cloud provider. Native tool support is checked before agent execution; text-only
models such as MedGemma can still serve as diagnostic judges.
"""

from __future__ import annotations

import ipaddress
import json
import math
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class LocalModelError(RuntimeError):
    """The local runtime or model cannot fulfill the requested evaluation."""


class ToolCapabilityError(LocalModelError):
    """A model without native tools was requested as a tool-using agent."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise LocalModelError("Local inference refused an HTTP redirect")


def _native_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate native JSON object key")
        result[key] = value
    return result


def _native_number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Nonfinite native JSON number")
    return number


def is_local_model(model: str | None) -> bool:
    """Whether the identifier explicitly selects the isolated local provider."""
    return bool(model and model.lower().startswith("ollama:"))


def _loopback_url(url: str) -> str:
    """Validate the endpoint and avoid DNS lookup for the localhost alias."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if host == "localhost":
            host = "127.0.0.1"
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or not ipaddress.ip_address(host).is_loopback
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        port = parsed.port
    except ValueError:
        raise ValueError("Ollama endpoint must be a loopback HTTP(S) origin without credentials")
    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority += f":{port}"
    return f"{parsed.scheme}://{authority}"


class OllamaClient:
    """A local-only ``ModelClient`` with native tool capability validation.

    ``HC_OLLAMA_BASE_URL`` defaults to ``http://127.0.0.1:11434``; only
    loopback endpoints are accepted. ``HC_OLLAMA_NUM_CTX`` defaults to 32768.
    ``HC_OLLAMA_SEED`` defaults to 42. Thinking defaults off for inexpensive
    diagnostics and can be enabled with ``HC_OLLAMA_THINK=1``. Seeded decoding
    improves repeatability but does not promise identical cross-runtime output.
    """

    def __init__(
        self,
        model: str,
        *,
        base_url: str | None = None,
        seed: int | None = None,
        num_ctx: int | None = None,
        timeout: float = 300,
        think: bool | None = None,
    ) -> None:
        if not model.strip() or model != model.strip() or "cloud" in model.lower():
            raise ValueError("An installed local model name is required; cloud models are refused")
        self._model = model
        self._base_url = _loopback_url(
            base_url or os.environ.get("HC_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        )
        self._seed = int(os.environ.get("HC_OLLAMA_SEED", "42")) if seed is None else seed
        self._num_ctx = (
            int(os.environ.get("HC_OLLAMA_NUM_CTX", "32768")) if num_ctx is None else num_ctx
        )
        self._think = os.environ.get("HC_OLLAMA_THINK", "0") == "1" if think is None else think
        if self._num_ctx <= 0 or timeout <= 0:
            raise ValueError("num_ctx and timeout must be positive")
        self._timeout = timeout
        # Proxy environment variables and redirects must not reroute local data.
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())
        self._info: dict[str, Any] | None = None
        self._call_sequence = 0

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        request = Request(
            self._base_url + path,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={"Content-Type": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                body = response.read()
        except HTTPError as exc:
            # No retry or fallback: propagate infrastructure failure to the runner.
            detail = exc.read(4096).decode("utf-8", errors="replace")
            raise LocalModelError(f"Ollama HTTP {exc.code} for {path}: {detail}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise LocalModelError(
                f"Local Ollama unavailable at {self._base_url}; start Ollama. No cloud fallback."
            ) from exc
        # Evidence capture precedes decoding. Sink failures retain their own
        # exception identity rather than being mislabeled as a network error.
        self._response_received(path, body)
        try:
            result = json.loads(
                body.decode("utf-8"),
                object_pairs_hook=_native_pairs,
                parse_constant=_native_number,
                parse_float=_native_number,
            )
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise LocalModelError("Ollama returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise LocalModelError("Ollama returned a non-object response")
        if result.get("error"):
            raise LocalModelError(f"Ollama: {result['error']}")
        return result

    def _response_received(self, path: str, body: bytes) -> None:
        """Optional evidence hook for the exact successful HTTP response body."""

    def validate_capabilities(self, *, require_tools: bool = False) -> dict[str, Any]:
        """Check installed identity, reject remote aliases, and require native tools."""
        if self._info is None:
            inventory = self._request("/api/tags").get("models", [])
            names = {self._model}
            if ":" not in self._model.rsplit("/", 1)[-1]:
                names.add(self._model + ":latest")
            entry = next((m for m in inventory if m.get("name", m.get("model")) in names), None)
            if entry is None:
                raise LocalModelError(
                    f"Model {self._model!r} is not installed in local Ollama. "
                    "Install weights explicitly; evaluation never downloads or falls back."
                )
            if entry.get("remote_model") or entry.get("remote_host"):
                raise LocalModelError(
                    "Ollama remote model aliases are refused for local evaluation"
                )
            shown = self._request("/api/show", {"model": self._model})
            if shown.get("remote_model") or shown.get("remote_host"):
                raise LocalModelError(
                    "Ollama remote model aliases are refused for local evaluation"
                )
            details = shown.get("details", {})
            self._info = {
                "provider": "ollama",
                "runtime_version": self._request("/api/version").get("version", ""),
                "base_url": self._base_url,
                "model": entry.get("name", self._model),
                "model_digest": entry.get("digest", ""),
                "family": details.get("family", ""),
                "quantization": details.get("quantization_level", ""),
                "capabilities": shown.get("capabilities", []),
                "seed": self._seed,
                "num_ctx": self._num_ctx,
                "think": self._think,
            }
        if "completion" not in self._info["capabilities"]:
            raise LocalModelError(f"Model {self._model!r} does not declare completion capability")
        if require_tools and "tools" not in self._info["capabilities"]:
            raise ToolCapabilityError(
                f"Model {self._model!r} is text-only in this runtime; native tools are not "
                "supported. Use it as a diagnostic judge, or select a tool-capable agent."
            )
        return dict(self._info)

    def model_metadata(self) -> dict[str, Any]:
        """Return the installed digest and explicit runtime settings for provenance."""
        return self.validate_capabilities()

    def checkpoint_identity(self) -> dict[str, Any]:
        """Resolve weight identity without running inference before a cache check."""
        return self.model_metadata()

    @staticmethod
    def _convert_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted = []
        tool_names = {}
        for message in messages:
            item = {"role": message["role"], "content": message.get("content") or ""}
            if message.get("tool_calls"):
                item["tool_calls"] = []
                for call in message["tool_calls"]:
                    tool_names[call["id"]] = call["name"]
                    item["tool_calls"].append(
                        {"function": {"name": call["name"], "arguments": call["arguments"]}}
                    )
            if message["role"] == "tool":
                call_id = message.get("tool_call_id", "")
                if call_id not in tool_names:
                    raise LocalModelError(
                        f"Tool result has no matching assistant call: {call_id!r}"
                    )
                item["tool_name"] = tool_names[call_id]
            converted.append(item)
        return converted

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        info = self.validate_capabilities(require_tools=bool(tools))
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": self._convert_messages(messages),
            "stream": False,
            "options": {
                "temperature": temperature,
                "seed": self._seed,
                "num_ctx": self._num_ctx,
                "num_predict": max_tokens,
            },
        }
        if "thinking" in info["capabilities"]:
            payload["think"] = self._think
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {"type": "object"}),
                    },
                }
                for tool in tools
            ]
        response = self._request("/api/chat", payload)
        message = response.get("message")
        if not isinstance(message, dict) or response.get("done") is not True:
            raise LocalModelError("Ollama returned an incomplete chat response")
        if message.get("role") != "assistant":
            raise LocalModelError("Ollama response message role must be assistant")
        self._call_sequence += 1
        calls = []
        for index, call in enumerate(message.get("tool_calls") or []):
            function = call.get("function", {})
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(
                        arguments,
                        object_pairs_hook=_native_pairs,
                        parse_constant=_native_number,
                        parse_float=_native_number,
                    )
                except (ValueError, RecursionError) as exc:
                    raise LocalModelError("Ollama tool arguments are not valid JSON") from exc
            if not isinstance(arguments, dict):
                raise LocalModelError("Ollama tool arguments must be a JSON object")
            if not isinstance(function.get("name"), str) or not function["name"]:
                raise LocalModelError("Ollama tool call is missing a function name")
            calls.append(
                {
                    "id": f"ollama-{self._call_sequence}-{index}",
                    "name": function["name"],
                    "arguments": arguments,
                }
            )
        # ``done`` closes the response envelope; it does not establish why
        # generation ended. Missing termination provenance remains unknown.
        reason = response.get("done_reason")
        return {
            "content": message.get("content") or "",
            "tool_calls": calls,
            # A parsed tool call does not prove generation completed. Preserve
            # length/other non-normal termination so the runner never executes
            # a truncated response as though it were a completed tool request.
            "stop_reason": "tool_calls" if calls and reason == "stop" else reason,
        }
