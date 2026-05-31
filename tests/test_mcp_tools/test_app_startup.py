"""Startup/health tests for the Docker MCP ASGI entrypoint.

Regression guard for a class of bug that ``docker compose build`` cannot
catch: ``healthcraft.mcp.app`` builds a live server at import time via the
module-level ``_server = _create_app()``. A bad reference there (e.g. reading
a non-existent ``WorldState`` attribute) crashes uvicorn on startup while the
image still builds cleanly -- invisible to a build-only CI step.

These tests drive the raw ASGI app in-process (no socket bind), so they run
inside the fast ``make test`` gate and are immune to sandbox port-binding
restrictions. Importing this module is itself the first assertion: if
``_create_app()`` raised, the file would fail to collect.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import healthcraft.mcp.app as app_module

EXPECTED_TOOL_COUNT = 24


def _call_asgi(method: str, path: str, body: bytes = b"") -> tuple[int, dict[str, str], Any]:
    """Drive the ASGI app once and return (status, headers, parsed_json)."""
    scope = {"type": "http", "method": method, "path": path, "headers": []}
    sent: list[dict[str, Any]] = []
    request_sent = False

    async def receive() -> dict[str, Any]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(app_module.app(scope, receive, send))

    start = next(m for m in sent if m["type"] == "http.response.start")
    chunks = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    headers = {k.decode(): v.decode() for k, v in start["headers"]}
    parsed = json.loads(chunks) if chunks else None
    return start["status"], headers, parsed


def test_app_module_built_server_at_import() -> None:
    # If _create_app() raised at import, this module never collects. Reaching
    # here proves the seeded-world startup path is intact.
    assert callable(app_module.app)


def test_health_endpoint_returns_ok_with_tool_count() -> None:
    status, headers, payload = _call_asgi("GET", "/health")
    assert status == 200
    assert headers.get("content-type") == "application/json"
    assert payload == {"status": "ok", "tools": EXPECTED_TOOL_COUNT}


def test_tools_endpoint_lists_all_tools() -> None:
    status, _headers, payload = _call_asgi("GET", "/tools")
    assert status == 200
    assert isinstance(payload["tools"], list)
    assert len(payload["tools"]) == EXPECTED_TOOL_COUNT


def test_unknown_path_returns_404() -> None:
    status, _headers, payload = _call_asgi("GET", "/no-such-route")
    assert status == 404
    assert payload["code"] == "not_found"
