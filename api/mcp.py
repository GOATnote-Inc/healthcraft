"""Vercel Function entrypoint for the Streamable-HTTP MCP server.

Vercel's Python runtime detects a top-level class derived from
``BaseHTTPRequestHandler`` and routes the matching path to it. The function
is mounted at ``/api/mcp`` (Vercel's file-based convention) and a
``vercel.json`` rewrite advertises the cleaner ``/mcp`` / ``/healthz``
public paths.

We:

1. Add ``src/`` to ``sys.path`` so the bundled function imports the
   in-repo ``healthcraft`` package without an editable install.
2. Load the 100-rule world + Superpower + coverage matrix **once at import
   time** so warm Fluid Compute instances reuse them across requests.
3. Subclass ``_Handler`` to make path matching permissive — the underlying
   handler enforces ``self.path == "/mcp"``, but Vercel's URL surface at the
   function level is ``/api/mcp``. We accept either by normalizing.
"""

from __future__ import annotations

import pathlib
import sys
from http import HTTPStatus
from typing import Any

# Ensure the in-repo ``src/`` is importable without an editable install. The
# Vercel build bundles the whole repo by default; we keep the package layout
# unchanged so tests and Docker keep working.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from healthcraft.agents_assemble.coverage import CoverageMatrix  # noqa: E402
from healthcraft.agents_assemble.streamable_http_server import (  # noqa: E402
    PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    _Handler,
    _build_world,
    _jsonrpc_error,
    handle_jsonrpc,
)
from healthcraft.agents_assemble.superpower_decision_rules.server import (  # noqa: E402
    create_superpower,
)

# Module-level singletons. Class attributes survive across requests in the
# same warm container; Vercel's runtime reuses the imported module.
_world = _build_world()
_superpower = create_superpower(_world)
_coverage = CoverageMatrix.load(
    _REPO_ROOT / "configs" / "agents_assemble" / "coverage_matrix.yaml"
)


class handler(_Handler):  # noqa: N801 — Vercel naming convention
    """Path-permissive Vercel adapter over the stdlib MCP handler."""

    # Attach the preloaded state at class scope so all instances share it.
    world = _world
    superpower = _superpower
    coverage = _coverage

    def do_GET(self) -> None:  # noqa: N802
        if self._is_health_path():
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "server": SERVER_NAME,
                    "version": SERVER_VERSION,
                    "protocolVersion": PROTOCOL_VERSION,
                    "endpoint": "/mcp",
                    "rulesLoaded": len(self.world.list_entities("decision_rule")),
                },
            )
            return
        if self._is_mcp_path():
            # MCP Streamable HTTP allows GET-as-SSE; we don't push events.
            self._send_json(
                HTTPStatus.METHOD_NOT_ALLOWED,
                {"error": "sse_not_supported", "hint": "POST JSON-RPC to /mcp"},
            )
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found", "path": self.path})

    def do_POST(self) -> None:  # noqa: N802
        if not self._is_mcp_path():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found", "path": self.path})
            return

        body = self._read_json_body()
        if body is None:
            self._send_json(HTTPStatus.BAD_REQUEST, _jsonrpc_error(None, -32700, "Parse error"))
            return

        if isinstance(body, list):
            responses: list[Any] = []
            for msg in body:
                if not isinstance(msg, dict):
                    continue
                resp = handle_jsonrpc(
                    msg,
                    superpower=self.superpower,
                    coverage=self.coverage,
                    world=self.world,
                )
                if resp is not None:
                    responses.append(resp)
            if not responses:
                self._send_empty(HTTPStatus.ACCEPTED)
                return
            self._send_json(HTTPStatus.OK, responses)
            return

        if not isinstance(body, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, _jsonrpc_error(None, -32600, "Invalid Request"))
            return

        response = handle_jsonrpc(
            body,
            superpower=self.superpower,
            coverage=self.coverage,
            world=self.world,
        )
        if response is None:
            self._send_empty(HTTPStatus.ACCEPTED)
            return
        self._send_json(HTTPStatus.OK, response)

    # ------------------------------------------------------------------
    # Path normalization
    # ------------------------------------------------------------------

    def _normalized_path(self) -> str:
        path = (self.path or "/").split("?", 1)[0].rstrip("/") or "/"
        # Strip Vercel's function-mount prefix so ``/api/mcp`` and ``/mcp``
        # both reach the same dispatch branch.
        if path.startswith("/api/mcp"):
            path = path[len("/api") :] or "/mcp"
        return path

    def _is_mcp_path(self) -> bool:
        return self._normalized_path() in ("/mcp", "/")

    def _is_health_path(self) -> bool:
        return self._normalized_path() in ("/healthz", "/health")
