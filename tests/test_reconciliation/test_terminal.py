"""The copied terminal client preserves real responses and uncertain writes."""

import importlib
import io
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler

import pytest


@pytest.fixture
def terminal():
    return importlib.import_module("healthcraft.reconciliation.terminal")


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("HC_RECONCILIATION_URL", "http://127.0.0.1:18765")
    monkeypatch.setenv("HC_RECONCILIATION_TOKEN", "trial-token-do-not-echo")


def wire(terminal, monkeypatch, body=b'{"status":"ok","data":{}}', error=None):
    calls = []
    handlers = []

    class Response(io.BytesIO):
        def read(self, size=-1):
            assert 0 <= size <= 1024 * 1024 + 1
            return super().read(size)

    class Opener:
        def open(self, request, timeout):
            calls.append((request, timeout))
            if error:
                raise error
            return Response(body)

    def build(*items):
        handlers.extend(items)
        return Opener()

    monkeypatch.setattr(terminal, "build_opener", build)
    return calls, handlers


def receipt(capsys, code, state):
    captured = capsys.readouterr()
    assert captured.out == ""
    value = json.loads(captured.err)
    assert value["status"] == "error"
    assert value["code"] == code
    assert value["dispatch_state"] == state
    assert "trial-token-do-not-echo" not in captured.err
    return value


def test_tools_returns_full_public_json_without_wrapper(terminal, configured, monkeypatch, capsys):
    response = {"tools": [{"name": "getEncounterDetails", "parameters": {"type": "object"}}]}
    calls, handlers = wire(terminal, monkeypatch, json.dumps(response).encode())
    assert terminal.main(["tools"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == response
    assert captured.err == ""
    req, timeout = calls[0]
    assert req.full_url == "http://127.0.0.1:18765/tools"
    assert req.get_method() == "GET"
    assert req.data is None
    assert req.get_header("Authorization") == "Bearer trial-token-do-not-echo"
    assert timeout == 30
    assert next(h for h in handlers if isinstance(h, ProxyHandler)).proxies == {}


def test_call_preserves_nested_note_string_and_raw_tool_error(
    terminal, configured, monkeypatch, capsys
):
    params = {
        "encounter_id": "ENC-AAAAAAAA",
        "notes": '{"assertion": "unknown ☃"}',
        "idempotency_key": "same-call",
    }
    response = {
        "status": "error",
        "code": "idempotency_conflict",
        "message": "different note",
        "data": {"unknown": None},
    }
    calls, _ = wire(terminal, monkeypatch, json.dumps(response).encode())
    assert terminal.main(["call", "updateEncounter", "--params-json", json.dumps(params)]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == response
    assert captured.err == ""
    req, _ = calls[0]
    assert req.full_url.endswith("/call")
    assert req.get_method() == "POST"
    assert json.loads(req.data) == {"name": "updateEncounter", "params": params}
    assert "trial-token-do-not-echo" not in captured.out


def test_params_file_and_json_have_identical_request_semantics(
    terminal, configured, monkeypatch, capsys, tmp_path
):
    params = {"nested": {"no": False, "unknown": None}, "items": [1, "x"]}
    source = tmp_path / "params.json"
    source.write_text(json.dumps(params), encoding="utf-8")
    calls, _ = wire(terminal, monkeypatch)
    assert terminal.main(["call", "updateEncounter", "--params-file", str(source)]) == 0
    capsys.readouterr()
    assert terminal.main(["call", "updateEncounter", "--params-json", json.dumps(params)]) == 0
    assert calls[0][0].data == calls[1][0].data


@pytest.mark.parametrize(
    "raw",
    [
        '{"x":NaN}',
        '{"x":Infinity}',
        '{"x":1e9999}',
        '{"x":1,"x":2}',
        '{"x":{"a":0,"a":1}}',
        "[]",
        "null",
        "false",
        "{} trailing",
        "{",
    ],
)
def test_invalid_params_are_never_dispatched(terminal, configured, monkeypatch, capsys, raw):
    calls, _ = wire(terminal, monkeypatch)
    assert terminal.main(["call", "updateEncounter", "--params-json", raw]) == 2
    receipt(capsys, "invalid_params", "not_dispatched")
    assert calls == []


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["unknown"],
        ["call", "updateEncounter"],
        ["call", "updateEncounter", "--params-json", "{}", "--params-file", "x"],
        ["tools", "--params-json", "{}"],
    ],
)
def test_invalid_cli_is_a_json_receipt_without_argument_echo(
    terminal, configured, monkeypatch, capsys, args
):
    calls, _ = wire(terminal, monkeypatch)
    assert terminal.main(args) == 2
    receipt(capsys, "invalid_arguments", "not_dispatched")
    assert calls == []


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:80",
        "http://example.com:80",
        "http://127.0.0.1",
        "http://localhost:0",
        "http://localhost:65536",
        "http://localhost:80/path",
        "http://localhost:80/?x=1",
        "http://localhost:80/#x",
        "http://secret@localhost:80",
        "http://localhost.evil:80",
        " http://localhost:80",
        "http://localhost:80\n",
        "http://healthcraft-ehr.evil:80",
    ],
)
def test_invalid_service_url_fails_before_network(terminal, configured, monkeypatch, capsys, url):
    monkeypatch.setenv("HC_RECONCILIATION_URL", url)
    calls, _ = wire(terminal, monkeypatch)
    assert terminal.main(["tools"]) == 2
    receipt(capsys, "invalid_configuration", "not_dispatched")
    assert calls == []


@pytest.mark.parametrize(
    "host", ["127.0.0.1", "localhost", "[::1]", "host.docker.internal", "healthcraft-ehr"]
)
def test_exact_local_service_hosts_are_accepted(terminal, monkeypatch, host):
    calls, _ = wire(terminal, monkeypatch)
    result = terminal.request_json("GET", "/tools", url=f"http://{host}:8080/", token="nonce")
    assert result == {"status": "ok", "data": {}}
    assert len(calls) == 1
    assert calls[0][0].full_url == f"http://{host}:8080/tools"


@pytest.mark.parametrize("token", ["", "bad\nheader", "bad\rheader", "has space", "nonascii☃"])
def test_invalid_token_never_leaks_or_dispatches(terminal, configured, monkeypatch, capsys, token):
    monkeypatch.setenv("HC_RECONCILIATION_TOKEN", token)
    calls, _ = wire(terminal, monkeypatch)
    assert terminal.main(["tools"]) == 2
    receipt(capsys, "invalid_configuration", "not_dispatched")
    assert calls == []


@pytest.mark.parametrize("timeout", [0, -1, 31, math.inf, math.nan, True, "30"])
def test_timeout_is_positive_finite_and_capped(terminal, monkeypatch, timeout):
    calls, _ = wire(terminal, monkeypatch)
    with pytest.raises(terminal.TerminalError) as error:
        terminal.request_json(
            "GET", "/tools", url="http://localhost:80", token="nonce", timeout=timeout
        )
    assert error.value.dispatch_state == "not_dispatched"
    assert calls == []


@pytest.mark.parametrize(
    "body",
    [
        b"[]",
        b"null",
        b'{"status":"ok","status":"error"}',
        b'{"x":NaN}',
        b'{"x":1e9999}',
        b'{"x":{"a":0,"a":1}}',
        b"{} garbage",
        b"\xff",
    ],
)
def test_invalid_response_does_not_erase_possible_write(
    terminal, configured, monkeypatch, capsys, body
):
    calls, _ = wire(terminal, monkeypatch, body)
    assert terminal.main(["call", "updateEncounter", "--params-json", "{}"]) == 2
    receipt(capsys, "invalid_response", "outcome_unknown")
    assert len(calls) == 1


def test_response_size_is_bounded_without_retry(terminal, configured, monkeypatch, capsys):
    body = b'{"text":"' + b"x" * (1024 * 1024) + b'"}'
    calls, _ = wire(terminal, monkeypatch, body)
    assert terminal.main(["call", "updateEncounter", "--params-json", "{}"]) == 2
    receipt(capsys, "response_too_large", "outcome_unknown")
    assert len(calls) == 1


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("secret trial-token-do-not-echo"),
        URLError("secret trial-token-do-not-echo"),
        OSError("secret trial-token-do-not-echo"),
    ],
)
def test_transport_failure_is_unknown_and_never_retried(
    terminal, configured, monkeypatch, capsys, error
):
    calls, _ = wire(terminal, monkeypatch, error=error)
    assert terminal.main(["call", "updateEncounter", "--params-json", "{}"]) == 2
    receipt(capsys, "transport_error", "outcome_unknown")
    assert len(calls) == 1


def test_http_failure_does_not_echo_body_token_or_url(terminal, configured, monkeypatch, capsys):
    error = HTTPError(
        "http://secret/", 401, "trial-token-do-not-echo", {}, io.BytesIO(b"trial-token-do-not-echo")
    )
    calls, _ = wire(terminal, monkeypatch, error=error)
    assert terminal.main(["tools"]) == 2
    value = receipt(capsys, "http_error", "outcome_unknown")
    assert value["http_status"] == 401
    assert len(calls) == 1


def test_redirect_handler_refuses_before_followup(terminal, configured, monkeypatch):
    _, handlers = wire(terminal, monkeypatch)
    terminal.request_json("GET", "/tools", url="http://localhost:80", token="nonce")
    redirect = next(h for h in handlers if hasattr(h, "redirect_request"))
    with pytest.raises(terminal.TerminalError) as error:
        redirect.redirect_request(None, None, 302, "found", {}, "http://attacker.example")
    assert error.value.dispatch_state == "outcome_unknown"


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "updateEncounter", "params": {"n": math.nan}},
        {"name": "updateEncounter", "params": {1: "coerced"}},
        {"name": "updateEncounter", "params": {"tuple": (1, 2)}},
        {"name": "updateEncounter", "params": []},
    ],
)
def test_python_api_refuses_non_json_request_without_coercion(terminal, monkeypatch, payload):
    calls, _ = wire(terminal, monkeypatch)
    with pytest.raises(terminal.TerminalError) as error:
        terminal.request_json("POST", "/call", payload, url="http://localhost:80", token="nonce")
    assert error.value.dispatch_state == "not_dispatched"
    assert calls == []


def test_unreadable_params_file_is_not_dispatched(
    terminal, configured, monkeypatch, capsys, tmp_path
):
    calls, _ = wire(terminal, monkeypatch)
    assert (
        terminal.main(["call", "updateEncounter", "--params-file", str(tmp_path / "missing")]) == 2
    )
    receipt(capsys, "invalid_params", "not_dispatched")
    assert calls == []


def test_standalone_copy_has_no_healthcraft_or_external_dependencies(terminal, tmp_path):
    script = tmp_path / "terminal.py"
    shutil.copyfile(Path(terminal.__file__), script)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(script),
            "call",
            "updateEncounter",
            "--params-json",
            '{"x":NaN}',
        ],
        cwd=tmp_path,
        env={
            "PATH": os.defpath,
            "HC_RECONCILIATION_URL": "http://localhost:80",
            "HC_RECONCILIATION_TOKEN": "nonce",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert json.loads(result.stderr)["dispatch_state"] == "not_dispatched"


def test_direct_api_rejects_null_byte_token(terminal, monkeypatch):
    calls, _ = wire(terminal, monkeypatch)
    with pytest.raises(terminal.TerminalError) as error:
        terminal.request_json("GET", "/tools", url="http://localhost:80", token="\x00")
    assert error.value.code == "invalid_configuration"
    assert calls == []


@pytest.mark.parametrize("kind", ["bad_status", "incomplete_body"])
def test_http_protocol_failure_is_controlled_unknown_outcome(
    terminal, configured, monkeypatch, capsys, kind
):
    from http.client import BadStatusLine, IncompleteRead

    error = (
        BadStatusLine("trial-token-do-not-echo")
        if kind == "bad_status"
        else IncompleteRead(b"trial-token-do-not-echo", 50)
    )
    calls, _ = wire(terminal, monkeypatch, error=error)
    assert terminal.main(["call", "updateEncounter", "--params-json", "{}"]) == 2
    receipt(capsys, "transport_error", "outcome_unknown")
    assert len(calls) == 1


def test_extreme_integer_timeout_is_rejected_without_overflow(terminal, monkeypatch):
    calls, _ = wire(terminal, monkeypatch)
    with pytest.raises(terminal.TerminalError) as error:
        terminal.request_json(
            "GET", "/tools", url="http://localhost:80", token="nonce", timeout=10**1000
        )
    assert error.value.code == "invalid_configuration"
    assert calls == []


def test_response_at_exact_limit_is_preserved(terminal, configured, monkeypatch, capsys):
    body = b'{"text":"' + b"x" * (1024 * 1024 - 11) + b'"}'
    assert len(body) == 1024 * 1024
    calls, _ = wire(terminal, monkeypatch, body)
    assert terminal.main(["tools"]) == 0
    assert json.loads(capsys.readouterr().out) == json.loads(body)
    assert len(calls) == 1
