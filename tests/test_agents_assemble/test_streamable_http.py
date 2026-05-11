"""HTTP integration tests for the Streamable-HTTP MCP server.

Boots the in-process ThreadingHTTPServer on an ephemeral port and exercises
the MCP wire protocol (initialize / tools/list / tools/call). Loopback-only;
each test runs in <2s. No real EHR or FHIR backend is required — tests
exercise the deterministic decision-rule path.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any

import pytest

from healthcraft.agents_assemble.streamable_http_server import (
    PROTOCOL_VERSION,
    SERVER_NAME,
    serve,
)

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def server_url():
    server = serve(port=0, host="127.0.0.1")
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _post_jsonrpc(url: str, payload: Any) -> Any:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url + "/mcp",
        data=body,
        method="POST",
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8")), resp.status


def _get(url: str, path: str) -> tuple[Any, int]:
    req = urllib.request.Request(url + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8")), e.code


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_healthz_returns_server_info(server_url: str) -> None:
    body, status = _get(server_url, "/healthz")
    assert status == 200
    assert body["server"] == SERVER_NAME
    assert body["protocolVersion"] == PROTOCOL_VERSION
    assert body["endpoint"] == "/mcp"


def test_initialize_returns_protocol_version(server_url: str) -> None:
    body, status = _post_jsonrpc(
        server_url,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert status == 200
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    result = body["result"]
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == SERVER_NAME
    assert "tools" in result["capabilities"]


def test_initialize_advertises_sharp_fhir_context_capability(server_url: str) -> None:
    """Prompt Opinion / SHARP-aware hosts schema-validate the initialize result
    and require ``capabilities.experimental.fhir_context_required = true`` so
    they know to forward FHIR context headers (X-FHIR-Server-URL,
    X-FHIR-Access-Token, X-Patient-ID) on subsequent calls. Without this flag,
    the host's MCP-server registration endpoint returns 422 Unprocessable
    Entity during the connectivity test.
    """
    body, _ = _post_jsonrpc(
        server_url,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    caps = body["result"]["capabilities"]
    assert "experimental" in caps, "SHARP capability flag is required"
    # Per MCP spec, each experimental capability is an OBJECT (not a primitive).
    fhir_cap = caps["experimental"].get("fhir_context_required")
    assert isinstance(fhir_cap, dict), (
        "experimental capabilities must be objects (MCP spec / Inspector validation)"
    )
    assert fhir_cap.get("required") is True, (
        "Hosts use this flag to opt into forwarding SHARP FHIR-context headers"
    )


def test_initialize_uses_widely_supported_mcp_protocol_version(server_url: str) -> None:
    """Pin to ``2025-03-26`` — the version Prompt Opinion's and most other
    production MCP host SDKs ship today. The MCP spec lets clients negotiate
    down to an older version, but many host validators reject handshakes that
    advertise a newer version than they recognize. Conservative wins."""
    body, _ = _post_jsonrpc(
        server_url,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    version = body["result"]["protocolVersion"]
    assert version == "2025-03-26", f"expected 2025-03-26, got {version}"


def test_get_root_returns_healthz_not_405(server_url: str) -> None:
    """A bare GET to ``/`` must return 200 with server info — many MCP host
    validators ping the base URL before posting the initialize, and a 405
    there gets misclassified as 'endpoint unreachable'."""
    body, status = _get(server_url, "/")
    assert status == 200
    assert body.get("server") == SERVER_NAME, body


def test_tools_list_includes_decision_rule_tools(server_url: str) -> None:
    body, status = _post_jsonrpc(
        server_url,
        {"jsonrpc": "2.0", "id": "list-1", "method": "tools/list"},
    )
    assert status == 200
    names = {tool["name"] for tool in body["result"]["tools"]}
    assert {
        "applyDecisionRule",
        "listRules",
        "getCoverageForComplaint",
        "getProtocolDetails",
        "getReferenceArticle",
    } <= names
    # Every tool must declare an input schema (MCP requirement).
    for tool in body["result"]["tools"]:
        assert "inputSchema" in tool
        assert tool["inputSchema"]["type"] == "object"


def test_list_rules_returns_bundled_library(server_url: str) -> None:
    body, _ = _post_jsonrpc(
        server_url,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "listRules", "arguments": {}},
        },
    )
    payload = body["result"]["structuredContent"]
    assert isinstance(payload["rules"], list)
    # PR #2 ships 100 decision rules. Allow some headroom but assert non-empty
    # and that well-known rule names are present so a future rename surfaces.
    assert payload["count"] >= 30
    name_blob = " ".join(payload["rules"]).upper()
    assert "HEART" in name_blob
    assert body["result"]["isError"] is False


def test_get_coverage_for_complaint_returns_ranked_rules(server_url: str) -> None:
    body, _ = _post_jsonrpc(
        server_url,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "getCoverageForComplaint",
                "arguments": {"complaint": "chest pain"},
            },
        },
    )
    payload = body["result"]["structuredContent"]
    assert payload["complaint"] == "chest pain"
    assert isinstance(payload["rules"], list)
    assert payload["count"] >= 1
    assert body["result"]["isError"] is False


def test_apply_decision_rule_with_supplied_variables(server_url: str) -> None:
    # HEART score with all-zero inputs should produce a low-risk result via the
    # deterministic additive scorer. We don't pin the exact numeric output (the
    # rule library evolves) — just that the dispatch succeeds and a result
    # block is returned.
    body, _ = _post_jsonrpc(
        server_url,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "applyDecisionRule",
                "arguments": {
                    "ruleName": "HEART",
                    "variables": {
                        "history": 0,
                        "ecg": 0,
                        "age": 0,
                        "risk_factors": 0,
                        "troponin": 0,
                    },
                },
            },
        },
    )
    structured = body["result"]["structuredContent"]
    # The Superpower returns a SHARP-reply envelope; the payload is nested
    # under the same shape ``SuperpowerServer.call`` produces.
    assert "rule" in structured or "result" in structured or "sharp" in structured
    # Best-effort: scan the JSON-string content for the rule name.
    text_blob = body["result"]["content"][0]["text"]
    assert "HEART" in text_blob


def test_unknown_tool_returns_jsonrpc_error(server_url: str) -> None:
    body, _ = _post_jsonrpc(
        server_url,
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "nonexistentTool", "arguments": {}},
        },
    )
    assert "error" in body
    assert body["error"]["code"] == -32602


def test_notification_returns_no_body(server_url: str) -> None:
    body = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode("utf-8")
    req = urllib.request.Request(
        server_url + "/mcp",
        data=body,
        method="POST",
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 202
        assert resp.read() == b""
