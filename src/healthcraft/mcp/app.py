"""FastMCP application entry point for Docker deployment.

Creates the MCP server with a seeded world state and exposes it
via uvicorn for HTTP-based MCP tool calls.

Usage:
    python -m healthcraft.mcp.app            # picks a safe bind host (see below)
    uvicorn healthcraft.mcp.app:app --host 127.0.0.1 --port 8000

Security model (research tool, not a production service):
    - If HEALTHCRAFT_API_TOKEN is set, every endpoint except GET /health
      requires "Authorization: Bearer <token>"; a missing or wrong token
      gets 401.
    - If HEALTHCRAFT_API_TOKEN is unset, auth is off, and the module
      runner binds 127.0.0.1 (loopback) instead of 0.0.0.0, logging a
      warning. Set HEALTHCRAFT_HOST=0.0.0.0 explicitly to expose an
      unauthenticated server (docker-compose does this inside the
      container network; the audit endpoint stays disabled).
    - GET /audit (full audit-log dump, every caller's calls) is only
      served when a token is configured and presented; otherwise 403.
    - Request bodies are capped at HEALTHCRAFT_MAX_BODY_BYTES
      (default 1 MiB); larger requests get 413.

Environment variables:
    HEALTHCRAFT_SEED: Random seed (default: 42)
    HEALTHCRAFT_SEED_CONFIG: Path to world seed config YAML
    HEALTHCRAFT_LOG_LEVEL: Logging level (default: INFO)
    HEALTHCRAFT_API_TOKEN: Optional bearer token enabling auth + /audit
    HEALTHCRAFT_HOST: Bind host for `python -m healthcraft.mcp.app`
    HEALTHCRAFT_PORT: Bind port for `python -m healthcraft.mcp.app` (default: 8000)
    HEALTHCRAFT_MAX_BODY_BYTES: Request body cap in bytes (default: 1048576)
"""

from __future__ import annotations

import hmac
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

_DEFAULT_MAX_BODY_BYTES = 1_048_576  # 1 MiB

logging.basicConfig(level=getattr(logging, _LOG_LEVEL, logging.INFO))


def _api_token() -> str:
    """Configured bearer token, or empty string when auth is off.

    Read per-request (not at import) so tests and long-lived processes
    see the current environment.
    """
    return os.environ.get("HEALTHCRAFT_API_TOKEN", "")


def _max_body_bytes() -> int:
    """Request body size cap in bytes."""
    try:
        return int(os.environ.get("HEALTHCRAFT_MAX_BODY_BYTES", str(_DEFAULT_MAX_BODY_BYTES)))
    except ValueError:
        return _DEFAULT_MAX_BODY_BYTES


def _authorized(scope: dict[str, Any]) -> bool:
    """Check the Authorization header against HEALTHCRAFT_API_TOKEN.

    Returns True when auth is off (no token configured) or the caller
    presented the right bearer token. Constant-time comparison.
    """
    token = _api_token()
    if not token:
        return True
    presented = b""
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            presented = value
            break
    expected = b"Bearer " + token.encode("utf-8")
    return hmac.compare_digest(presented, expected)


def _create_app() -> HealthcraftServer:
    """Initialize the server with a seeded world state."""
    config_path = Path(_CONFIG_PATH)
    if not config_path.exists():
        raise FileNotFoundError(f"World seed config not found: {config_path}")

    logger.info("Seeding world state (seed=%d, config=%s)", _SEED, config_path)
    world_state = WorldSeeder(seed=_SEED).seed_world(config_path)
    counts = world_state.entity_counts
    logger.info(
        "World state seeded: %d populated entity types, %d entities",
        len(counts),
        sum(counts.values()),
    )

    server = create_server(world_state)
    logger.info("MCP server created with %d tools", len(server.available_tools))
    return server


# Global server instance
_server = _create_app()


class _BodyTooLarge(Exception):
    """Request body exceeded the configured cap."""


async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
    """ASGI application for serving MCP tool calls over HTTP.

    Endpoints:
        POST /tool   — Call a tool: {"name": "...", "params": {...}}
        GET  /tools  — List available tools
        GET  /health — Health check (never requires auth)
        GET  /audit  — Audit-log dump; requires HEALTHCRAFT_API_TOKEN
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

    if not _authorized(scope):
        await _send_json(
            send,
            {"status": "error", "code": "unauthorized"},
            status=401,
            extra_headers=[[b"www-authenticate", b"Bearer"]],
        )
        return

    if path == "/tools" and method == "GET":
        await _send_json(send, {"tools": _server.available_tools})
        return

    if path == "/tool" and method == "POST":
        try:
            body = await _read_body(receive)
        except _BodyTooLarge:
            await _send_json(send, {"status": "error", "code": "body_too_large"}, status=413)
            return
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
        if not _api_token():
            # Never expose the full audit trail (every caller's calls) on
            # an unauthenticated server.
            await _send_json(
                send,
                {
                    "status": "error",
                    "code": "audit_disabled",
                    "message": "Set HEALTHCRAFT_API_TOKEN to enable the audit endpoint.",
                },
                status=403,
            )
            return
        audit_json = _server.audit_logger.to_json()
        await _send_json(send, json.loads(audit_json), as_list=True)
        return

    await _send_json(send, {"status": "error", "code": "not_found"}, status=404)


async def _read_body(receive: Any) -> bytes:
    """Read the full request body, enforcing the size cap.

    Raises:
        _BodyTooLarge: When the body exceeds HEALTHCRAFT_MAX_BODY_BYTES.
    """
    cap = _max_body_bytes()
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if len(body) > cap:
            raise _BodyTooLarge
        if not message.get("more_body", False):
            break
    return body


async def _send_json(
    send: Any,
    data: Any,
    status: int = 200,
    as_list: bool = False,
    extra_headers: list[list[bytes]] | None = None,
) -> None:
    """Send a JSON response."""
    body = json.dumps(data, default=str).encode("utf-8")
    headers = [
        [b"content-type", b"application/json"],
        [b"content-length", str(len(body)).encode()],
    ]
    if extra_headers:
        headers.extend(extra_headers)
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": headers,
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": body,
        }
    )


def main() -> None:
    """Run the server with a safe default bind host.

    With HEALTHCRAFT_API_TOKEN set (or HEALTHCRAFT_HOST given explicitly)
    the server binds the requested host (default 0.0.0.0 when a token is
    set). Without either, it binds loopback and logs a warning.
    """
    import uvicorn

    port = int(os.environ.get("HEALTHCRAFT_PORT", "8000"))
    host = os.environ.get("HEALTHCRAFT_HOST", "")
    if not host:
        if _api_token():
            host = "0.0.0.0"  # noqa: S104 — auth is enabled
        else:
            host = "127.0.0.1"
    if not _api_token() and host != "127.0.0.1":
        logger.warning(
            "HEALTHCRAFT_API_TOKEN is not set and host is %s: the MCP HTTP "
            "surface (24 tools incl. mutations) is exposed without auth. "
            "Set HEALTHCRAFT_API_TOKEN, or leave HEALTHCRAFT_HOST unset to "
            "bind loopback only.",
            host,
        )
    elif not _api_token():
        logger.warning(
            "HEALTHCRAFT_API_TOKEN is not set; binding %s (loopback only). "
            "Set HEALTHCRAFT_HOST=0.0.0.0 to expose the unauthenticated "
            "server anyway.",
            host,
        )
    uvicorn.run("healthcraft.mcp.app:app", host=host, port=port)


if __name__ == "__main__":
    main()
