"""Post-submission excellence audit tests — TDD red phase.

These tests encode the findings from the rigorous evaluation conducted
2026-05-11 after Devpost submission. Each test name maps to a finding
ID (F1, F2, F3, F4, F6, F7, F8) in the audit report. The tests are
deliberately written to FAIL against v0.1.0 so the implementation
gap is auditable; v0.1.1 fixes make them pass.

This file is the public auditable record of every quality bar we hold
ourselves to beyond MCP spec compliance.
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


def _post(url: str, payload: Any, path: str = "/mcp") -> tuple[Any, int]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url + path,
        data=body,
        method="POST",
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return json.loads(body), e.code
        except json.JSONDecodeError:
            return body, e.code


def _get(url: str, path: str) -> tuple[Any, int, dict[str, str]]:
    req = urllib.request.Request(url + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status, dict(resp.headers)
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8")), e.code, dict(e.headers)
        except (json.JSONDecodeError, AttributeError):
            return None, e.code, dict(getattr(e, "headers", {}) or {})


# ---------------------------------------------------------------------------
# F2: Fuzzy rule-name lookup — single highest agent-UX impact
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user_input,expected_match",
    [
        ("HEART", "HEART Score"),
        ("heart score", "HEART Score"),
        ("Wells PE", "Wells Criteria for PE"),
        ("Wells DVT", "Wells Criteria for DVT"),
        ("HASBLED", "HAS-BLED Score"),
        ("CURB65", "CURB-65"),
        ("qsofa", "qSOFA"),
        ("Glasgow Coma", "Glasgow Coma Scale"),
        ("CHA2DS2", "CHA2DS2-VASc"),
    ],
)
def test_f2_fuzzy_rule_name_resolution(
    server_url: str, user_input: str, expected_match: str
) -> None:
    """Real-world agents and clinicians type rule names loosely — exact-match
    silently 404s. The server must accept common abbreviations, casing
    variants, and punctuation drops, then resolve to the canonical name."""
    body, _ = _post(
        server_url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "applyDecisionRule",
                "arguments": {"ruleName": user_input, "variables": {}},
            },
        },
    )
    structured = body["result"]["structuredContent"]
    rule = structured.get("data", {}).get("rule") or structured.get("rule")
    assert rule == expected_match, (
        f"input {user_input!r} must resolve to {expected_match!r}, got {rule!r}"
    )


def test_f2_unknown_rule_returns_three_suggestions(server_url: str) -> None:
    """When no fuzzy match crosses the threshold, the error payload must
    include the three closest canonical names so the agent can self-correct."""
    body, _ = _post(
        server_url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "applyDecisionRule",
                "arguments": {"ruleName": "ZZZ_UnknownRule_QQQ", "variables": {}},
            },
        },
    )
    err = body["result"]["structuredContent"].get("data", {}).get("error") or {}
    suggestions = err.get("suggestions") or err.get("closest") or []
    assert isinstance(suggestions, list) and len(suggestions) >= 3, (
        f"rule_not_found error must include at least 3 closest-match suggestions, got: {err}"
    )


# ---------------------------------------------------------------------------
# F1: Glasgow Coma Scale must NOT silently score impossible values
# ---------------------------------------------------------------------------


def test_f1_gcs_with_no_variables_returns_missing_variables_status(server_url: str) -> None:
    """GCS minimum is 3 (eye=1 + verbal=1 + motor=1). A score of 0 is
    clinically impossible. Missing variables must surface as an explicit
    error status, not silently produce 0/15."""
    body, _ = _post(
        server_url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "applyDecisionRule",
                "arguments": {"ruleName": "Glasgow Coma Scale", "variables": {}},
            },
        },
    )
    data = body["result"]["structuredContent"].get("data", {})
    # Either the status is non-"ok" or the result must be flagged as invalid.
    if data.get("status") == "ok":
        result = data.get("result", {})
        rl = result.get("risk_level", "")
        assert rl not in ("low", "moderate", "high"), (
            f"GCS with no variables must not return a clinical risk tier; got risk_level={rl!r}"
        )
        # Score 0 is impossible. The server must reject it OR flag it.
        assert result.get("score") != 0 or "invalid" in rl.lower() or "missing" in rl.lower(), (
            f"GCS with score=0 must flag as invalid_input/missing, got: {result}"
        )


def test_f1_gcs_with_valid_inputs_scores_correctly(server_url: str) -> None:
    """GCS=15 (fully alert: eye=4, verbal=5, motor=6) must score correctly."""
    body, _ = _post(
        server_url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "applyDecisionRule",
                "arguments": {
                    "ruleName": "Glasgow Coma Scale",
                    "variables": {"eye": 4, "verbal": 5, "motor": 6},
                },
            },
        },
    )
    data = body["result"]["structuredContent"]["data"]
    assert data["status"] == "ok"
    # Score must be in valid GCS range [3, 15]
    score = data["result"]["score"]
    assert 3 <= score <= 15, f"GCS score must be in [3,15], got {score}"


# ---------------------------------------------------------------------------
# F3: HEART evidence-grade annotations on borderline scores
# ---------------------------------------------------------------------------


def test_f3_heart_borderline_includes_evidence_note(server_url: str) -> None:
    """HEART score 3 sits at the discharge/admit boundary. 2025 single-center
    validation (Cureus PMC12151265) found 4.4% MACE at HEART<=3, exceeding the
    ACEP 2% safe-discharge threshold. The response must surface this evidence
    note at score boundary (1-3) so clinicians know the recommendation is
    being actively contested in current literature."""
    body, _ = _post(
        server_url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "applyDecisionRule",
                "arguments": {
                    "ruleName": "HEART Score",
                    "variables": {"history": 1, "ecg": 1, "age": 1, "risk_factors": 0, "troponin": 0},
                },
            },
        },
    )
    data = body["result"]["structuredContent"]["data"]
    result = data["result"]
    assert result["score"] == 3
    # Evidence note must be present in either the result or the data envelope.
    evidence = result.get("evidence_note") or data.get("evidence_note") or result.get("evidence")
    assert evidence is not None, (
        "HEART score in borderline tier (1-3) must include an evidence_note "
        "referencing current literature (e.g. PMC12151265)"
    )
    blob = str(evidence).lower()
    assert "mace" in blob or "2025" in blob or "validation" in blob, (
        f"evidence_note must reference MACE/2025 validation context, got: {evidence!r}"
    )


# ---------------------------------------------------------------------------
# F4: Request body size cap
# ---------------------------------------------------------------------------


def test_f4_oversized_body_rejected_with_413(server_url: str) -> None:
    """Server must refuse oversized requests at the Content-Length check
    before consuming function memory. Use a raw socket so urllib doesn't
    raise BrokenPipe when the server closes the connection mid-upload."""
    import socket
    import urllib.parse

    parsed = urllib.parse.urlparse(server_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect((host, port))
    # Advertise a 6 MB body but only send a tiny stub; server should refuse
    # after reading Content-Length without consuming the body.
    req = (
        b"POST /mcp HTTP/1.1\r\n"
        b"Host: " + host.encode() + b"\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: 6291457\r\n"
        b"Connection: close\r\n\r\n"
        b"{}"
    )
    s.sendall(req)
    resp = b""
    try:
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
            if len(resp) > 8192:
                break
    except (TimeoutError, socket.timeout):
        pass
    finally:
        s.close()
    status_line = resp.split(b"\r\n", 1)[0].decode("latin1", errors="replace")
    assert " 413 " in status_line, f"expected 413, got: {status_line!r}"


# ---------------------------------------------------------------------------
# F6: .well-known/oauth-protected-resource discovery
# ---------------------------------------------------------------------------


def test_f6_well_known_oauth_protected_resource_served(server_url: str) -> None:
    """Per MCP June 2025 spec, servers should expose RFC 9728's
    ``.well-known/oauth-protected-resource`` so clients can discover auth
    requirements. Even for open-access servers, returning a document with
    ``authorization_servers: []`` signals spec awareness and gives smart
    clients a definitive 'no auth required' confirmation."""
    body, status, _ = _get(server_url, "/.well-known/oauth-protected-resource")
    assert status == 200, f"discovery endpoint must return 200, got {status}"
    assert isinstance(body, dict), "body must be a JSON object"
    assert "resource" in body, "must include 'resource' URI"
    assert "authorization_servers" in body, (
        "must include 'authorization_servers' (empty array signals open-access)"
    )


# ---------------------------------------------------------------------------
# F7: Hardening headers — content-type sniff prevention + frame deny
# ---------------------------------------------------------------------------


def test_f7_response_includes_hardening_headers(server_url: str) -> None:
    """All responses must include the OWASP-recommended hardening headers:
    ``X-Content-Type-Options: nosniff`` to prevent MIME sniffing,
    ``X-Frame-Options: DENY`` to prevent clickjacking via iframe embed.
    HSTS is set by Vercel at the platform edge."""
    body, status, headers = _get(server_url, "/healthz")
    assert status == 200
    # Header names are case-insensitive
    norm = {k.lower(): v for k, v in headers.items()}
    assert norm.get("x-content-type-options", "").lower() == "nosniff", (
        f"missing X-Content-Type-Options: nosniff, headers: {list(norm.keys())}"
    )
    assert norm.get("x-frame-options", "").upper() in {"DENY", "SAMEORIGIN"}, (
        f"missing X-Frame-Options: DENY, headers: {list(norm.keys())}"
    )


# ---------------------------------------------------------------------------
# F8: getRuleSchema tool — per-rule input discoverability
# ---------------------------------------------------------------------------


def test_f8_get_rule_schema_tool_exposed(server_url: str) -> None:
    """The agent UX gap is that ``applyDecisionRule.inputSchema.variables``
    is typed-but-generic (``object``). A per-rule schema tool lets the agent
    introspect the canonical variable names + integer encodings + natural-
    language synonyms before calling applyDecisionRule."""
    body, _ = _post(
        server_url,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    tools = body["result"]["tools"]
    names = {t["name"] for t in tools}
    assert "getRuleSchema" in names, (
        f"expected getRuleSchema tool exposed, got: {sorted(names)}"
    )


def test_f8_get_rule_schema_returns_heart_encoding(server_url: str) -> None:
    """getRuleSchema('HEART Score') must return each variable's encoding
    so an LLM agent can self-orient without trial-and-error."""
    body, _ = _post(
        server_url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "getRuleSchema", "arguments": {"ruleName": "HEART Score"}},
        },
    )
    schema = body["result"]["structuredContent"]
    assert schema.get("rule") == "HEART Score" or schema.get("ruleName") == "HEART Score"
    variables = schema.get("variables") or schema.get("inputs") or []
    var_names = {v.get("name", "").lower() for v in variables if isinstance(v, dict)}
    expected = {"history", "ecg", "age", "risk factors", "troponin"}
    assert expected <= var_names, (
        f"HEART schema must enumerate canonical variables {expected}, got {var_names}"
    )


# ---------------------------------------------------------------------------
# Cross-cutting: existing tests still pass (sanity)
# ---------------------------------------------------------------------------


def test_audit_anchor_existing_tools_list_still_returns_minimum_5(server_url: str) -> None:
    """When we add getRuleSchema in F8, the previously-pinned 5 tools must
    remain present. This test prevents accidental drop during the rename/add."""
    body, _ = _post(
        server_url,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    names = {t["name"] for t in body["result"]["tools"]}
    assert {
        "applyDecisionRule",
        "listRules",
        "getCoverageForComplaint",
        "getProtocolDetails",
        "getReferenceArticle",
    } <= names
