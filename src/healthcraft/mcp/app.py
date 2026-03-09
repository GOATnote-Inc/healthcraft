"""FastMCP application entry point for Docker deployment.

Creates the MCP server with a seeded world state and exposes it
via uvicorn for HTTP-based MCP tool calls.

Usage:
    uvicorn healthcraft.mcp.app:app --host 0.0.0.0 --port 8000

Environment variables:
    HEALTHCRAFT_SEED: Random seed (default: 42)
    HEALTHCRAFT_SEED_CONFIG: Path to world seed config YAML
    HEALTHCRAFT_LOG_LEVEL: Logging level (default: INFO)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from healthcraft.mcp.server import HealthcraftServer, create_server
from healthcraft.world.seed import WorldSeeder

logger = logging.getLogger("healthcraft.mcp")

# --- Configuration from environment ---

_SEED = int(os.environ.get("HEALTHCRAFT_SEED", "42"))
_CONFIG_PATH = os.environ.get(
    "HEALTHCRAFT_SEED_CONFIG",
    str(Path(__file__).parents[3] / "configs" / "world" / "mercy_point_v1.yaml"),
)
_LOG_LEVEL = os.environ.get("HEALTHCRAFT_LOG_LEVEL", "INFO")

logging.basicConfig(level=getattr(logging, _LOG_LEVEL, logging.INFO))


def _create_app() -> HealthcraftServer:
    """Initialize the server with a seeded world state."""
    config_path = Path(_CONFIG_PATH)
    if not config_path.exists():
        raise FileNotFoundError(f"World seed config not found: {config_path}")

    logger.info("Seeding world state (seed=%d, config=%s)", _SEED, config_path)
    world_state = WorldSeeder(seed=_SEED).seed_world(config_path)
    logger.info("World state seeded with %d entity types", len(world_state._stores))

    server = create_server(world_state)
    logger.info("MCP server created with %d tools", len(server.available_tools))
    return server


# Global server instance
_server = _create_app()


async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
    """ASGI application for serving MCP tool calls over HTTP.

    Endpoints:
        POST /tool   — Call a tool: {"name": "...", "params": {...}}
        GET  /tools  — List available tools
        GET  /health — Health check
    """
    if scope["type"] == "lifespan":
        message = await receive()
        if message["type"] == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        message = await receive()
        if message["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
        return

    if scope["type"] != "http":
        return

    method = scope.get("method", "GET")
    path = scope.get("path", "/")

    if path == "/health" and method == "GET":
        await _send_json(send, {"status": "ok", "tools": len(_server.available_tools)})
        return

    if path == "/tools" and method == "GET":
        await _send_json(send, {"tools": _server.available_tools})
        return

    if path == "/tool" and method == "POST":
        body = await _read_body(receive)
        try:
            data = json.loads(body)
            name = data.get("name", "")
            params = data.get("params", {})
            result = _server.call_tool(name, params)
            await _send_json(send, result)
        except json.JSONDecodeError:
            await _send_json(send, {"status": "error", "code": "invalid_json"}, status=400)
        except Exception as e:
            err = {"status": "error", "code": "internal_error", "message": str(e)}
            await _send_json(send, err, status=500)
        return

    if path == "/audit" and method == "GET":
        audit_json = _server.audit_logger.to_json()
        await _send_json(send, json.loads(audit_json), as_list=True)
        return

    await _send_json(send, {"status": "error", "code": "not_found"}, status=404)


async def _read_body(receive: Any) -> bytes:
    """Read the full request body."""
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body", False):
            break
    return body


async def _send_json(
    send: Any,
    data: Any,
    status: int = 200,
    as_list: bool = False,
) -> None:
    """Send a JSON response."""
    body = json.dumps(data, default=str).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                [b"content-type", b"application/json"],
                [b"content-length", str(len(body)).encode()],
            ],
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": body,
        }
    )
