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
# Security review v0.1.1 — pinned non-regression tests
# ---------------------------------------------------------------------------


def test_security_no_phi_in_observability_log_line() -> None:
    """The [MCP-IN] log line in app.py must not contain the raw request body.
    A previous version logged the first 400 chars of body content to stderr,
    which Vercel persists in function logs — that is a PHI leak vector when
    callers POST FHIR Bundles containing patient names / DOB / MRN."""
    import pathlib

    app_py = (
        pathlib.Path(__file__).resolve().parents[2] / "app.py"
    ).read_text(encoding="utf-8")
    # Find the MCP-IN log line. It must not include the variable ``preview``
    # (which used to contain raw body content) — only ``method_preview`` (the
    # JSON-RPC method name) is acceptable.
    log_lines = [
        line for line in app_py.splitlines() if "[MCP-IN]" in line and "f\"" in line
    ]
    assert log_lines, "expected an [MCP-IN] log statement in app.py"
    for line in log_lines:
        # Forbid the raw-body interpolation pattern that existed pre-v0.1.1.
        assert "body={preview}" not in line, (
            f"[MCP-IN] must NOT log raw body content (PHI leak). Found: {line!r}"
        )


def test_security_tools_call_exception_handler_returns_generic_message() -> None:
    """Source-level invariant: the catch-all exception handler in
    streamable_http_server.py's tools/call dispatch must NOT return
    ``f"Tool error: {exc}"`` to the caller. ``{exc}`` interpolation can
    leak internal file paths, library names, or framework details via
    Python's repr() of the exception."""
    import pathlib

    server_py = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src"
        / "healthcraft"
        / "agents_assemble"
        / "streamable_http_server.py"
    ).read_text(encoding="utf-8")
    # The leaky pattern that existed pre-v0.1.1.
    assert 'f"Tool error: {exc}"' not in server_py, (
        "tools/call exception handler must not embed {exc} in the response — "
        "it leaks internal paths and module names. Use a generic message and "
        "log the full traceback server-side only."
    )
    # The generic-message pattern must be present.
    assert "Internal error executing tool" in server_py, (
        "tools/call exception handler must use the generic-message pattern"
    )


def test_compliance_documents_present_and_link_to_each_other() -> None:
    """Compliance posture is documented in three artifacts that must all be
    present and cross-reference each other. Missing any of them means a
    reviewer can't verify the claims this repo makes about HIPAA Security
    Rule and SOC 2 Trust Service Criteria alignment."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    for name in (
        "docs/COMPLIANCE.md",
        "docs/PRE_DEPLOYMENT_CHECKLIST.md",
        "docs/SECURITY_REVIEW_v0.1.1.md",
        "SECURITY.md",
    ):
        assert (root / name).exists(), f"required compliance doc missing: {name}"

    compliance = (root / "docs/COMPLIANCE.md").read_text(encoding="utf-8")
    # COMPLIANCE.md must reference both HIPAA and SOC2 anchors so an auditor
    # finds the relevant control mappings.
    assert "45 CFR" in compliance, "COMPLIANCE.md must cite HIPAA Security Rule (45 CFR)"
    assert "164.312" in compliance, "COMPLIANCE.md must cite §164.312 Technical Safeguards"
    assert "Trust Service" in compliance, "COMPLIANCE.md must cover SOC 2 TSC"
    assert "BAA" in compliance, "COMPLIANCE.md must address the BAA requirement"

    checklist = (root / "docs/PRE_DEPLOYMENT_CHECKLIST.md").read_text(encoding="utf-8")
    # The checklist must enumerate signing parties and BAA requirements.
    assert "Security Officer" in checklist
    assert "BAA" in checklist
    assert "Risk Analysis" in checklist

    security = (root / "SECURITY.md").read_text(encoding="utf-8")
    # The security policy must reference the compliance + audit docs.
    assert "docs/COMPLIANCE.md" in security
    assert "docs/SECURITY_REVIEW_v0.1.1.md" in security


def test_compliance_does_not_overclaim_certification() -> None:
    """Hard invariant: this software is not HIPAA-certified or SOC 2-attested,
    and the compliance docs must not say it is. A reviewer who sees a
    'HIPAA compliant' claim with no BAA and no risk analysis will rightly
    distrust the rest of the documentation. We claim controls, not
    certifications."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    forbidden_patterns = [
        r"\bHIPAA\s*-?\s*compliant\b",
        r"\bSOC\s*2\s*-?\s*compliant\b",
        r"\bSOC\s*2\s*certified\b",
        r"\bHIPAA\s*certified\b",
        r"\bfully\s*compliant\s*with\s*HIPAA\b",
        r"\bcomplete[d]?\s*SOC\s*2\s*audit\b",
    ]
    for doc in ("docs/COMPLIANCE.md", "docs/PRE_DEPLOYMENT_CHECKLIST.md", "SECURITY.md", "README.md"):
        p = root / doc
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            assert not re.search(pattern, text, flags=re.IGNORECASE), (
                f"{doc} contains an overclaim matching /{pattern}/i — "
                f"this software is not certified; revise the language."
            )


def test_security_vercelignore_excludes_env_files() -> None:
    """Defense-in-depth: .vercelignore must explicitly exclude env files
    even though .gitignore already does. A future .gitignore change must
    not silently expose secrets to the function bundle."""
    import pathlib

    vercel_ignore = (
        pathlib.Path(__file__).resolve().parents[2] / ".vercelignore"
    ).read_text(encoding="utf-8")
    assert ".env" in vercel_ignore, ".vercelignore must list .env"
    assert "*.pem" in vercel_ignore or "*.key" in vercel_ignore, (
        ".vercelignore should exclude private-key file patterns"
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
