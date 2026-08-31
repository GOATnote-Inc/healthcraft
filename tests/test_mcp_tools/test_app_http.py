"""Tests for the ASGI HTTP surface in ``healthcraft.mcp.app``.

Covers the security hardening:
    - optional bearer auth via HEALTHCRAFT_API_TOKEN (401 on wrong/missing)
    - /health never requires auth
    - /audit is 403 unless a token is configured (and then requires it)
    - request body size cap (413)
    - `python -m healthcraft.mcp.app` binds loopback when no token is set

The app is exercised as a plain ASGI callable — no server, no sockets.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from typing import Any

import pytest

from healthcraft.mcp import app as app_module


def _call(
    method: str,
    path: str,
    body: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> tuple[int, Any]:
    """Drive the ASGI app with one request; return (status, parsed body)."""
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
    }
    messages = [{"type": "http.request", "body": body, "more_body": False}]
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return messages.pop(0)

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(app_module.app(scope, receive, send))

    status = sent[0]["status"]
    raw = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, json.loads(raw)


@pytest.fixture
def no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEALTHCRAFT_API_TOKEN", raising=False)


@pytest.fixture
def with_token(monkeypatch: pytest.MonkeyPatch) -> str:
    token = "test-secret-token"
    monkeypatch.setenv("HEALTHCRAFT_API_TOKEN", token)
    return token


def _bearer(token: str) -> list[tuple[bytes, bytes]]:
    return [(b"authorization", b"Bearer " + token.encode())]


# ---------------------------------------------------------------------------
# Auth off (no token configured)
# ---------------------------------------------------------------------------


def test_health_ok_without_token(no_token: None) -> None:
    status, data = _call("GET", "/health")
    assert status == 200
    assert data["status"] == "ok"
    assert data["tools"] > 0


def test_tools_ok_without_token(no_token: None) -> None:
    status, data = _call("GET", "/tools")
    assert status == 200
    assert len(data["tools"]) > 0


def test_tool_call_without_token(no_token: None) -> None:
    body = json.dumps({"name": "definitely-not-a-tool", "params": {}}).encode()
    status, data = _call("POST", "/tool", body=body)
    assert status == 200
    assert data["status"] == "error"
    assert data["code"] == "unknown_tool"


def test_audit_disabled_without_token(no_token: None) -> None:
    status, data = _call("GET", "/audit")
    assert status == 403
    assert data["code"] == "audit_disabled"


def test_invalid_json_is_400(no_token: None) -> None:
    status, data = _call("POST", "/tool", body=b"{not json")
    assert status == 400
    assert data["code"] == "invalid_json"


def test_unknown_path_is_404(no_token: None) -> None:
    status, data = _call("GET", "/nope")
    assert status == 404


# ---------------------------------------------------------------------------
# Auth on (token configured)
# ---------------------------------------------------------------------------


def test_health_never_requires_auth(with_token: str) -> None:
    status, data = _call("GET", "/health")
    assert status == 200
    assert data["status"] == "ok"


def test_tools_requires_auth(with_token: str) -> None:
    status, data = _call("GET", "/tools")
    assert status == 401
    assert data["code"] == "unauthorized"


def test_tool_post_requires_auth(with_token: str) -> None:
    body = json.dumps({"name": "x", "params": {}}).encode()
    status, data = _call("POST", "/tool", body=body)
    assert status == 401


def test_wrong_token_is_401(with_token: str) -> None:
    status, data = _call("GET", "/tools", headers=_bearer("wrong-token"))
    assert status == 401


def test_correct_token_passes(with_token: str) -> None:
    status, data = _call("GET", "/tools", headers=_bearer(with_token))
    assert status == 200
    assert len(data["tools"]) > 0


def test_audit_with_token_requires_and_accepts_bearer(with_token: str) -> None:
    status, _ = _call("GET", "/audit")
    assert status == 401
    status, data = _call("GET", "/audit", headers=_bearer(with_token))
    assert status == 200
    assert isinstance(data, list)


# ---------------------------------------------------------------------------
# Body size cap
# ---------------------------------------------------------------------------


def test_oversized_body_is_413(no_token: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEALTHCRAFT_MAX_BODY_BYTES", "64")
    status, data = _call("POST", "/tool", body=b"x" * 65)
    assert status == 413
    assert data["code"] == "body_too_large"


def test_body_under_cap_is_processed(no_token: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEALTHCRAFT_MAX_BODY_BYTES", "1024")
    body = json.dumps({"name": "definitely-not-a-tool", "params": {}}).encode()
    status, _ = _call("POST", "/tool", body=body)
    assert status == 200


def test_default_cap_is_1mib(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEALTHCRAFT_MAX_BODY_BYTES", raising=False)
    assert app_module._max_body_bytes() == 1_048_576
    monkeypatch.setenv("HEALTHCRAFT_MAX_BODY_BYTES", "not-a-number")
    assert app_module._max_body_bytes() == 1_048_576


# ---------------------------------------------------------------------------
# Runner bind-host selection (uvicorn stubbed; never actually serves)
# ---------------------------------------------------------------------------


def _run_main(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_run(app_path: str, host: str, port: int) -> None:
        captured.update({"app": app_path, "host": host, "port": port})

    stub = types.ModuleType("uvicorn")
    stub.run = fake_run  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", stub)
    app_module.main()
    return captured


def test_main_binds_loopback_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEALTHCRAFT_API_TOKEN", raising=False)
    monkeypatch.delenv("HEALTHCRAFT_HOST", raising=False)
    captured = _run_main(monkeypatch)
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8000


def test_main_binds_all_interfaces_with_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEALTHCRAFT_API_TOKEN", "secret")
    monkeypatch.delenv("HEALTHCRAFT_HOST", raising=False)
    captured = _run_main(monkeypatch)
    assert captured["host"] == "0.0.0.0"


def test_main_honours_explicit_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEALTHCRAFT_API_TOKEN", raising=False)
    monkeypatch.setenv("HEALTHCRAFT_HOST", "0.0.0.0")
    monkeypatch.setenv("HEALTHCRAFT_PORT", "9999")
    captured = _run_main(monkeypatch)
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9999
