"""Streamable-HTTP MCP transport for the ED Decision Rules Superpower.

Wraps :class:`SuperpowerServer` behind a JSON-RPC 2.0 endpoint at ``/mcp`` so
Prompt Opinion (and any other MCP host that supports the Streamable HTTP
transport) can attach by URL. The transport speaks the subset of the MCP wire
protocol that hosts actually exercise today:

- ``initialize`` — handshake; returns protocol version + server info.
- ``tools/list`` — catalog with JSON Schema input definitions.
- ``tools/call`` — dispatch to the underlying Superpower / coverage matrix.
- Notifications (``notifications/initialized`` and friends) — accepted and ack'd.

Five tools are exposed:

- ``applyDecisionRule`` — score one of the 100 bundled rules against a FHIR
  Bundle (and/or pre-supplied variables).
- ``listRules`` — enumerate the bundled rule names.
- ``getCoverageForComplaint`` — query the coverage matrix.
- ``getProtocolDetails`` — pass-through to the HEALTHCRAFT protocol tool.
- ``getReferenceArticle`` — pass-through to the HEALTHCRAFT reference tool.

Run from the repo root::

    python -m healthcraft.agents_assemble.streamable_http_server --port 8080

The server is intentionally stdlib-only (``http.server``) — same trade-off the
CDS Hooks server made: no new deps, single-threaded ThreadingHTTPServer is
plenty for a hackathon demo and a low-volume MCP host.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from healthcraft.agents_assemble.coverage import CoverageMatrix
from healthcraft.agents_assemble.superpower_decision_rules.server import (
    SuperpowerServer,
    create_superpower,
)
from healthcraft.entities.decision_rules import load_decision_rules
from healthcraft.world.state import WorldState

logger = logging.getLogger("agents_assemble.streamable_http")


PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "agents-assemble/ed-decision-rules"
SERVER_VERSION = "0.1.0"

# SHARP (Standardised Healthcare Agent Remote Protocol) capability flag.
# Advertising this on every ``initialize`` response tells SHARP-aware MCP
# hosts (Prompt Opinion / Darena Health) to forward FHIR context headers
# (X-FHIR-Server-URL, X-FHIR-Access-Token, X-Patient-ID) on subsequent
# tool calls so the server can resolve patient context without owning the
# OAuth dance itself.
SERVER_CAPABILITIES: dict[str, Any] = {
    "tools": {"listChanged": False},
    # Prompt Opinion's documented FHIR-context extension. The exact key
    # ``ai.promptopinion/fhir-context`` is required for PO to forward
    # SMART-on-FHIR headers (X-FHIR-Server-URL / X-FHIR-Access-Token /
    # X-Patient-ID) on tool calls. Scope grammar follows SMART v2:
    # ``patient/<Resource>.<perm>`` where perm is ``r``, ``s``, or ``rs``.
    # All scopes are optional — the user can grant any subset; our tools
    # accept variables directly when FHIR context is absent.
    "extensions": {
        "ai.promptopinion/fhir-context": {
            "scopes": [
                {"name": "patient/Patient.rs"},
                {"name": "patient/Observation.rs"},
                {"name": "patient/Condition.rs"},
                {"name": "patient/Encounter.rs"},
                {"name": "patient/MedicationRequest.rs"},
            ],
        },
    },
    # Generic SHARP signal (non-PO MCP hosts may read this; kept for
    # interop with other hackathon platforms).
    "experimental": {
        "sharp": {
            "version": "1.0",
            "fhir_context_required": True,
            "supported_headers": [
                "X-FHIR-Server-URL",
                "X-FHIR-Access-Token",
                "X-Patient-ID",
            ],
        },
    },
}


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------


def _tool_catalog() -> list[dict[str, Any]]:
    """JSON Schema definitions for every tool exposed over MCP."""
    return [
        {
            "name": "applyDecisionRule",
            "description": (
                "Score one of the 100 bundled ED decision rules against a FHIR "
                "Bundle. Returns score, risk tier, recommended disposition, "
                "extraction rationale, and a SHA-256 of the input bundle for "
                "audit. Either supply ``bundle`` (a FHIR R4 Bundle) or "
                "``variables`` (rule inputs as a dict) — or both; supplied "
                "variables override anything the extractor finds.\n\n"
                "VARIABLE ENCODING — pass integers OR natural-language phrases. "
                "Example for HEART Score: {history: 2 OR 'highly suspicious', "
                "ecg: 1 OR 'non-specific ST-T changes', age: 2 OR '>=65', "
                "risk_factors: 2 OR 'coronary artery disease', "
                "troponin: 1 OR '1-3x ULN'}. Each variable maps to 0/1/2 per "
                "the rule's canonical encoding; the server coerces text to "
                "integers via per-rule synonym tables."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ruleName": {
                        "type": "string",
                        "description": "Bundled rule name (e.g. 'HEART', 'Wells PE', 'CURB-65').",
                    },
                    "bundle": {
                        "type": "object",
                        "description": "FHIR R4 Bundle from the EHR.",
                    },
                    "variables": {
                        "type": "object",
                        "description": "Optional rule-input overrides (variable name -> value).",
                    },
                    "contextId": {
                        "type": "string",
                        "description": "Optional SHARP context id propagated back in response.",
                    },
                },
                "required": ["ruleName"],
            },
        },
        {
            "name": "listRules",
            "description": (
                "Return the names of the 100 bundled ED decision rules so the "
                "agent can pick one before calling applyDecisionRule."
            ),
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "getRuleSchema",
            "description": (
                "Return the canonical variable names, ranges, and score "
                "thresholds for a specific bundled rule. Use this BEFORE "
                "applyDecisionRule to learn the exact variable encoding the "
                "rule expects so you can supply integers natively rather than "
                "relying on the natural-language coercion fallback."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ruleName": {
                        "type": "string",
                        "description": "Canonical rule name (e.g. 'HEART Score').",
                    },
                },
                "required": ["ruleName"],
            },
        },
        {
            "name": "getCoverageForComplaint",
            "description": (
                "Look up the ranked rule list for a chief complaint (e.g. "
                "'chest pain', 'shortness of breath'), optionally narrowed by "
                "a qualifier branch. Reads from the coverage matrix (26 "
                "complaints x 9 organ systems x 3 age bands)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "complaint": {
                        "type": "string",
                        "description": "Chief complaint slug or free text.",
                    },
                    "qualifier": {
                        "type": ["string", "null"],
                        "description": "Optional qualifier branch (e.g. 'pleuritic_or_dyspnea').",
                    },
                },
                "required": ["complaint"],
            },
        },
        {
            "name": "getProtocolDetails",
            "description": (
                "Fetch a HEALTHCRAFT clinical protocol by id. Pass-through to "
                "the world-state protocol tool."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "protocol_id": {"type": "string"},
                    "protocolId": {"type": "string"},
                },
            },
        },
        {
            "name": "getReferenceArticle",
            "description": (
                "Fetch a clinical reference article (textbook / guideline) by "
                "id from HEALTHCRAFT's reference materials."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "article_id": {"type": "string"},
                    "articleId": {"type": "string"},
                },
            },
        },
    ]


_TOOL_NAMES = {tool["name"] for tool in _tool_catalog()}


# ---------------------------------------------------------------------------
# World bootstrap
# ---------------------------------------------------------------------------


def _build_world() -> WorldState:
    """Construct a singleton world preloaded with the 100-rule library."""
    world = WorldState()
    for rid, rule in load_decision_rules().items():
        world.put_entity("decision_rule", rid, rule)
    return world


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


def _dispatch_tool(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    superpower: SuperpowerServer,
    coverage: CoverageMatrix,
    world: WorldState,
) -> dict[str, Any]:
    """Run a tool by name. Returns the structured payload."""
    if tool_name == "listRules":
        rules = world.list_entities("decision_rule")
        names = sorted(
            {
                getattr(r, "name", None) or (r.get("name") if isinstance(r, dict) else "")
                for r in rules.values()
            }
            - {""}
        )
        return {"rules": names, "count": len(names)}

    if tool_name == "getCoverageForComplaint":
        complaint = str(arguments.get("complaint") or "").strip()
        qualifier = arguments.get("qualifier") or None
        if not complaint:
            return {"status": "error", "code": "missing_param", "message": "complaint is required"}
        ranked = coverage.rules_for_complaint(complaint, qualifier=qualifier)
        return {
            "complaint": complaint,
            "qualifier": qualifier,
            "rules": ranked,
            "count": len(ranked),
        }

    if tool_name == "getRuleSchema":
        from healthcraft.agents_assemble.superpower_decision_rules.server import (
            _lookup_rule,
            list_rule_schemas,
        )

        target = str(arguments.get("ruleName") or arguments.get("rule_name") or "").strip()
        if not target:
            return {"status": "error", "code": "missing_param", "message": "ruleName is required"}
        rule = _lookup_rule(world, target)
        if rule is None:
            return {
                "status": "error",
                "code": "rule_not_found",
                "message": f"Decision rule '{target}' not found.",
            }
        all_schemas = list_rule_schemas(world)
        # Find canonical name we resolved to.
        canon = getattr(rule, "name", None) or (rule.get("name") if isinstance(rule, dict) else target)
        schema = all_schemas.get(canon)
        if schema is None:
            return {
                "status": "error",
                "code": "schema_unavailable",
                "message": f"No schema for rule '{canon}'.",
            }
        # Add inline natural-language synonym hints for the common rules so
        # the LLM agent has everything it needs in one response.
        synonyms = _RULE_NL_SYNONYMS.get(canon)
        if synonyms:
            for v in schema["variables"]:
                vname = v.get("name", "")
                if vname.lower() in synonyms:
                    v["acceptedValues"] = synonyms[vname.lower()]
        return {"ruleName": canon, **schema}

    if tool_name in {"applyDecisionRule", "getProtocolDetails", "getReferenceArticle"}:
        return superpower.call(tool_name, dict(arguments))

    return {"status": "error", "code": "unknown_tool", "message": f"Unknown tool: {tool_name}"}


# Natural-language synonym tables exposed to MCP agents via getRuleSchema.
# Mirrors the server-side coercion map so an agent that calls getRuleSchema
# first can supply correctly-encoded values without server-side fallback.
_RULE_NL_SYNONYMS: dict[str, dict[str, dict[str, int]]] = {
    "HEART Score": {
        "history": {
            "highly suspicious": 2, "moderately suspicious": 1, "slightly suspicious": 0,
        },
        "ecg": {
            "significant ST depression": 2, "non-specific ST-T changes": 1, "normal": 0,
        },
        "age": {">=65": 2, "45-64": 1, "<45": 0},
        "risk factors": {
            ">=3 risk factors or history of atherosclerotic disease": 2,
            "1-2 risk factors": 1,
            "no risk factors": 0,
        },
        "troponin": {
            ">3x normal limit": 2, "1-3x normal limit": 1, "normal": 0,
        },
    },
}


# ---------------------------------------------------------------------------
# JSON-RPC layer
# ---------------------------------------------------------------------------


def _jsonrpc_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": err}


def handle_jsonrpc(
    message: dict[str, Any],
    *,
    superpower: SuperpowerServer,
    coverage: CoverageMatrix,
    world: WorldState,
) -> dict[str, Any] | None:
    """Handle a single JSON-RPC request. Returns ``None`` for notifications."""
    method = message.get("method")
    params = message.get("params") or {}
    request_id = message.get("id")
    is_notification = request_id is None

    if method == "initialize":
        return _jsonrpc_result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": SERVER_CAPABILITIES,
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )

    if method == "tools/list":
        return _jsonrpc_result(request_id, {"tools": _tool_catalog()})

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        if tool_name not in _TOOL_NAMES:
            return _jsonrpc_error(request_id, -32602, f"Unknown tool: {tool_name}")
        try:
            payload = _dispatch_tool(
                tool_name,
                arguments,
                superpower=superpower,
                coverage=coverage,
                world=world,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("tools/call %s failed", tool_name)
            return _jsonrpc_error(request_id, -32603, f"Tool error: {exc}")
        text = json.dumps(payload, default=str)
        return _jsonrpc_result(
            request_id,
            {
                "content": [{"type": "text", "text": text}],
                "structuredContent": payload,
                "isError": _looks_like_error(payload),
            },
        )

    if method == "ping":
        return _jsonrpc_result(request_id, {})

    if is_notification:
        # Notifications (e.g. notifications/initialized) require no response.
        return None

    return _jsonrpc_error(request_id, -32601, f"Method not found: {method}")


def _looks_like_error(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("status") == "error":
        return True
    if isinstance(payload.get("result"), dict) and payload["result"].get("status") == "error":
        return True
    return False


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    server_version = f"{SERVER_NAME}/{SERVER_VERSION}"

    # Lazily attached by ``serve``.
    superpower: SuperpowerServer | None = None
    coverage: CoverageMatrix | None = None
    world: WorldState | None = None

    # F4: Body size cap — refuse oversized payloads at the edge.
    MAX_BODY_BYTES: int = 5 * 1024 * 1024

    def _send_hardening(self) -> None:
        """F7: OWASP-recommended hardening headers on every response."""
        self.send_header("x-content-type-options", "nosniff")
        self.send_header("x-frame-options", "DENY")
        self.send_header("referrer-policy", "no-referrer")
        self.send_header(
            "content-security-policy", "default-src 'none'; frame-ancestors 'none'"
        )

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
        self.send_header(
            "access-control-allow-headers",
            "content-type, mcp-session-id, mcp-protocol-version",
        )
        self._send_hardening()
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status: int) -> None:
        self.send_response(status)
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
        self.send_header(
            "access-control-allow-headers",
            "content-type, mcp-session-id, mcp-protocol-version",
        )
        self._send_hardening()
        self.send_header("content-length", "0")
        self.end_headers()

    def _read_json_body(self) -> Any:
        length = int(self.headers.get("content-length") or 0)
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_empty(HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/")
        if path in ("", "/healthz"):
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "server": SERVER_NAME,
                    "version": SERVER_VERSION,
                    "protocolVersion": PROTOCOL_VERSION,
                    "endpoint": "/mcp",
                },
            )
            return
        if path == "/.well-known/oauth-protected-resource":
            # F6: RFC 9728 / MCP June 2025 discovery document. Even for the
            # open-access v0.1 release, exposing this signals spec awareness
            # and lets smart clients deterministically detect "no auth needed".
            self._send_json(
                HTTPStatus.OK,
                {
                    "resource": "https://mcp.thegoatnote.com/mcp",
                    "authorization_servers": [],
                    "scopes_supported": [
                        "patient/Patient.rs",
                        "patient/Observation.rs",
                        "patient/Condition.rs",
                        "patient/Encounter.rs",
                        "patient/MedicationRequest.rs",
                    ],
                    "bearer_methods_supported": [],
                    "resource_documentation": (
                        "https://github.com/GOATnote-Inc/healthcraft"
                    ),
                    "auth_required": False,
                    "notes": (
                        "Open access for v0.1 hackathon submission. OAuth 2.1 "
                        "+ PKCE + RFC 8707 Resource Indicators targeted for "
                        "v0.2 per MCP June 2025 spec."
                    ),
                },
            )
            return
        if path == "/mcp":
            # MCP Streamable HTTP allows a GET to open a server-initiated SSE
            # stream. We don't push server-to-client events, so return 405 as
            # the spec permits.
            self._send_json(
                HTTPStatus.METHOD_NOT_ALLOWED,
                {"error": "sse_not_supported", "hint": "POST JSON-RPC to /mcp"},
            )
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found", "path": self.path})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/")
        if path != "/mcp":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found", "path": self.path})
            return

        # F4: refuse oversized payloads at the edge.
        try:
            cl = int(self.headers.get("content-length") or 0)
        except (ValueError, TypeError):
            cl = 0
        if cl > self.MAX_BODY_BYTES:
            self._send_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"error": "payload_too_large", "limit_bytes": self.MAX_BODY_BYTES},
            )
            return

        body = self._read_json_body()
        if body is None:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                _jsonrpc_error(None, -32700, "Parse error"),
            )
            return

        if isinstance(body, list):
            responses = [
                handle_jsonrpc(
                    msg,
                    superpower=self.superpower,
                    coverage=self.coverage,
                    world=self.world,
                )
                for msg in body
                if isinstance(msg, dict)
            ]
            responses = [r for r in responses if r is not None]
            if not responses:
                self._send_empty(HTTPStatus.ACCEPTED)
                return
            self._send_json(HTTPStatus.OK, responses)
            return

        if not isinstance(body, dict):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                _jsonrpc_error(None, -32600, "Invalid Request"),
            )
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

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        logger.debug("%s - %s", self.address_string(), format % args)


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------


def serve(port: int = 8080, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    """Start the Streamable-HTTP MCP server. Returns it for the caller to close."""
    world = _build_world()
    superpower = create_superpower(world)
    coverage = CoverageMatrix.load()

    handler = _Handler
    handler.world = world
    handler.superpower = superpower
    handler.coverage = coverage

    server = ThreadingHTTPServer((host, port), handler)
    logger.info(
        "MCP Streamable HTTP server listening on %s:%d/mcp (%d rules loaded)",
        host,
        port,
        len(world.list_entities("decision_rule")),
    )
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "8080")),
        help="Port to bind (default: $PORT or 8080).",
    )
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    server = serve(port=args.port, host=args.host)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
