"""Vercel ASGI entrypoint for the Streamable-HTTP MCP server.

We swapped from a stdlib ``BaseHTTPRequestHandler`` subclass to FastAPI
because Vercel's Python serverless runtime does NOT deliver chunked
request bodies via ``self.rfile`` to BaseHTTPRequestHandler — and Prompt
Opinion's backend uses ``Transfer-Encoding: chunked`` on every POST to
the MCP endpoint. FastAPI / Starlette's ASGI pipeline reads the body
through the runtime's native receive() machinery, which handles chunked
transparently.

The underlying MCP dispatch (initialize / tools/list / tools/call) is
unchanged — we still call ``handle_jsonrpc`` from
``healthcraft.agents_assemble.streamable_http_server``.
"""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Make the in-repo ``src/`` importable without an editable install.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from healthcraft.agents_assemble.coverage import CoverageMatrix  # noqa: E402
from healthcraft.agents_assemble.streamable_http_server import (  # noqa: E402
    PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    _build_world,
    _jsonrpc_error,
    handle_jsonrpc,
)
from healthcraft.agents_assemble.superpower_decision_rules.server import (  # noqa: E402
    create_superpower,
)

# Module-level singletons — survive across requests in the same warm container.
_world = _build_world()
_superpower = create_superpower(_world)
_coverage = CoverageMatrix.load(
    _REPO_ROOT / "configs" / "agents_assemble" / "coverage_matrix.yaml"
)

app = FastAPI(
    title="Agents Assemble — ED Decision Rules MCP",
    version=SERVER_VERSION,
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=[
        "content-type",
        "accept",
        "mcp-session-id",
        "mcp-protocol-version",
        "authorization",
        "x-fhir-server-url",
        "x-fhir-access-token",
        "x-patient-id",
    ],
)


# F7: OWASP-recommended hardening headers on every response. HSTS is set
# by Vercel at the edge; we add the rest at the application layer.
@app.middleware("http")
async def _hardening_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    return response


# F4: Refuse bodies larger than 5 MB at the edge — pre-empts the function
# memory budget. JSON-RPC MCP traffic is small; even a maximal FHIR Bundle
# for ED scoring sits comfortably under 1 MB.
MAX_BODY_BYTES = 5 * 1024 * 1024


@app.middleware("http")
async def _enforce_body_size_cap(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl:
        try:
            if int(cl) > MAX_BODY_BYTES:
                return JSONResponse(
                    {"error": "payload_too_large", "limit_bytes": MAX_BODY_BYTES},
                    status_code=413,
                )
        except (ValueError, TypeError):
            pass
    return await call_next(request)


# F6: ``.well-known/oauth-protected-resource`` per RFC 9728 / MCP June 2025
# spec. Even open-access servers expose this discovery document so clients
# can determine auth requirements deterministically.
@app.get("/.well-known/oauth-protected-resource")
def well_known_oauth_protected_resource() -> dict[str, Any]:
    return {
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
        "resource_documentation": "https://github.com/GOATnote-Inc/healthcraft",
        "resource_policy_uri": "https://github.com/GOATnote-Inc/healthcraft/blob/main/SECURITY.md",
        "auth_required": False,
        "notes": (
            "Open access for the v0.1 hackathon submission. OAuth 2.1 + PKCE + "
            "RFC 8707 Resource Indicators targeted for v0.2 per MCP June 2025 spec."
        ),
    }


def _healthz_payload() -> dict[str, Any]:
    return {
        "status": "ok",
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "protocolVersion": PROTOCOL_VERSION,
        "endpoint": "/mcp",
        "rulesLoaded": len(_world.list_entities("decision_rule")),
    }


@app.get("/")
@app.get("/healthz")
@app.get("/health")
def healthz() -> dict[str, Any]:
    return _healthz_payload()


@app.get("/mcp")
def mcp_get() -> Response:
    # MCP Streamable HTTP allows GET-as-SSE; we don't push events.
    return JSONResponse(
        {"error": "sse_not_supported", "hint": "POST JSON-RPC to /mcp"},
        status_code=405,
    )


async def _dispatch_mcp_post(request: Request) -> Response:
    raw = await request.body()
    # Observability — log ONLY non-PHI metadata: method, byte count,
    # User-Agent. Request bodies frequently carry FHIR Bundles with patient
    # names, DOB, MRN, and other PHI; logging body content (even truncated)
    # would persist those values in Vercel function logs, which is a
    # privacy violation regardless of audit value. The rule version hash
    # and bundle SHA-256 are surfaced in the response payload — that's the
    # audit trail. The wire is not for raw payload logging.
    try:
        method_preview = "?"
        if raw:
            try:
                parsed_preview = json.loads(raw)
                if isinstance(parsed_preview, dict):
                    method_preview = str(parsed_preview.get("method", "?"))[:40]
                elif isinstance(parsed_preview, list) and parsed_preview:
                    method_preview = f"batch[{len(parsed_preview)}]"
            except Exception:
                method_preview = "<unparseable>"
        ua = request.headers.get("user-agent", "?")[:80]
        print(
            f"[MCP-IN] method={method_preview} bytes={len(raw)} ua={ua}",
            file=sys.stderr,
            flush=True,
        )
    except Exception:
        pass

    if not raw:
        # Empty-body probe — return an initialize result so connectivity
        # validators populate their tool catalogs.
        init = handle_jsonrpc(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            superpower=_superpower,
            coverage=_coverage,
            world=_world,
        )
        return JSONResponse(init)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return JSONResponse(_jsonrpc_error(None, -32700, "Parse error"), status_code=400)

    if isinstance(payload, list):
        responses: list[Any] = []
        for msg in payload:
            if not isinstance(msg, dict):
                continue
            resp = handle_jsonrpc(
                msg,
                superpower=_superpower,
                coverage=_coverage,
                world=_world,
            )
            if resp is not None:
                responses.append(resp)
        if not responses:
            return Response(status_code=202)
        return JSONResponse(responses)

    if not isinstance(payload, dict):
        return JSONResponse(_jsonrpc_error(None, -32600, "Invalid Request"), status_code=400)

    response = handle_jsonrpc(
        payload,
        superpower=_superpower,
        coverage=_coverage,
        world=_world,
    )
    if response is None:
        return Response(status_code=202)
    return JSONResponse(response)


@app.post("/mcp")
@app.post("/")
async def mcp_post(request: Request) -> Response:
    return await _dispatch_mcp_post(request)
