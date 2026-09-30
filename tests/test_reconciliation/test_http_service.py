"""Actual loopback HTTP behavior for the private reconciliation coordinator.

No models, remote services, upstream datasets, or clinical scores are used.
Raw-socket cases exercise bounded HTTP framing before any tool can dispatch.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
import threading
import time
from contextlib import contextmanager
from copy import deepcopy

import pytest

from healthcraft.reconciliation.execution import execute_reference
from healthcraft.reconciliation.fixture import load_scenario
from healthcraft.reconciliation.oracle import load_expectations, verify_reconciliation
from healthcraft.reconciliation.service import MAX_BODY_BYTES, ReconciliationSession

PUBLIC_TOKEN = "http-test-agent-secret"
ADMIN_TOKEN = "http-test-coordinator-secret"
PUBLIC_AUTH = f"Bearer {PUBLIC_TOKEN}"
ADMIN_AUTH = f"Bearer {ADMIN_TOKEN}"


def server_class():
    from healthcraft.reconciliation.http_service import ReconciliationHTTPServer

    return ReconciliationHTTPServer


def body(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")


@contextmanager
def running_server(tmp_path, *, socket_timeout=0.1):
    session = ReconciliationSession(token=PUBLIC_TOKEN)
    evidence_path = tmp_path / "evidence.json"
    server = server_class()(
        ("127.0.0.1", 0),
        session,
        admin_token=ADMIN_TOKEN,
        evidence_path=evidence_path,
        socket_timeout=socket_timeout,
    )
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield server, evidence_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        session.close()
        assert not thread.is_alive(), "HTTP coordinator did not shut down within the test bound"


def http_request(server, method, path, payload=None, authorization=PUBLIC_AUTH):
    connection = http.client.HTTPConnection(*server.server_address, timeout=2)
    headers = {"Connection": "close"}
    if authorization is not None:
        headers["Authorization"] = authorization
    try:
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        assert response.getheader("Content-Type", "").startswith("application/json")
        return response.status, json.loads(raw)
    finally:
        connection.close()


def raw_request(server, headers, payload=b"", *, method="POST", path="/call", eof=False):
    request = (
        f"{method} {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\nAuthorization: {PUBLIC_AUTH}\r\n{headers}\r\n".encode()
        + payload
    )
    started = time.monotonic()
    with socket.create_connection(server.server_address, timeout=2) as connection:
        connection.settimeout(2)
        connection.sendall(request)
        if eof:
            connection.shutdown(socket.SHUT_WR)
        chunks = []
        while chunk := connection.recv(65536):
            chunks.append(chunk)
    raw = b"".join(chunks)
    head, response_body = raw.split(b"\r\n\r\n", 1)
    status = int(head.split(b" ", 2)[1])
    return status, json.loads(response_body), time.monotonic() - started


def finalize(server, *, status="completed", error=None):
    request = {"status": status}
    if error is not None:
        request["error"] = error
    return http_request(server, "POST", "/_control/finalize", body(request), ADMIN_AUTH)


class HTTPRecorder:
    def __init__(self, server):
        self.server = server

    def call(self, name, params):
        status, response = http_request(
            self.server, "POST", "/call", body({"name": name, "params": params})
        )
        assert status == 200
        return response


@pytest.fixture(autouse=True)
def idempotency(monkeypatch):
    monkeypatch.setenv("HC_IDEMPOTENT_TOOLS", "1")


def test_actual_http_reference_persists_note_and_private_finalize_returns_only_digest(
    tmp_path, monkeypatch
):
    synced = []
    original_fsync = os.fsync

    def fsync(descriptor):
        synced.append(descriptor)
        return original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fsync)
    with running_server(tmp_path) as (server, path):
        assert http_request(server, "GET", "/health") == (200, {"status": "ok"})
        status, schemas = http_request(server, "GET", "/tools")
        assert status == 200 and len(schemas["tools"]) == 5
        execute_reference(HTTPRecorder(server), target=deepcopy(load_scenario()["target"]))
        assert not path.exists()
        status, receipt = finalize(server)
        assert status == 200 and set(receipt) == {"status", "sha256"}
        assert receipt["status"] == "ok"
        raw = path.read_bytes()
        assert receipt["sha256"] == hashlib.sha256(raw).hexdigest()
        assert synced, "Coordinator evidence must be flushed to the filesystem"
        evidence = json.loads(raw)
        result = verify_reconciliation(load_scenario(), load_expectations(), evidence)
        assert result["mechanical_passed"] is True
        assert len(evidence["after"]["entities"]["clinical_note"]) == 1
        assert len(evidence["calls"]) == len(evidence["audit"]) == 10
        assert PUBLIC_TOKEN not in raw.decode() and ADMIN_TOKEN not in raw.decode()
        assert "protocol_events" in evidence


@pytest.mark.parametrize("route", ["/tools", "/health"])
def test_public_http_routes_require_public_bearer_token(tmp_path, route):
    with running_server(tmp_path) as (server, path):
        assert http_request(server, "GET", route, authorization=None)[0] == 401
        assert http_request(server, "GET", route, authorization=ADMIN_AUTH)[0] == 401
        assert finalize(server)[0] == 200
        evidence = json.loads(path.read_text())
        assert evidence["calls"] == evidence["audit"] == []
        assert evidence["completion"]["status"] == "failed"


def test_private_token_is_required_to_finalize_and_wrong_admin_does_not_poison_public_work(
    tmp_path,
):
    with running_server(tmp_path) as (server, path):
        status, response = http_request(
            server, "POST", "/_control/finalize", body({"status": "completed"}), PUBLIC_AUTH
        )
        assert status == 401 and response.get("status") == "error"
        assert not path.exists()
        assert http_request(server, "GET", "/health")[0] == 200
        execute_reference(HTTPRecorder(server), target=load_scenario()["target"])
        assert finalize(server)[0] == 200
        evidence = json.loads(path.read_text())
        assert evidence["completion"]["status"] == "completed"
        assert (
            verify_reconciliation(load_scenario(), load_expectations(), evidence)[
                "mechanical_passed"
            ]
            is True
        )
        assert any(
            event["path"] == "/_control/finalize" and event["status"] == 401
            for event in evidence["protocol_events"]
        )


@pytest.mark.parametrize("path", ["/evidence", "/snapshot", "/world", "/finalize"])
def test_public_network_never_exposes_coordinator_snapshots(tmp_path, path):
    with running_server(tmp_path) as (server, evidence_path):
        status, response = http_request(server, "GET", path)
        assert status == 404
        assert response.get("status") == "error"
        assert "entities" not in json.dumps(response) and "source_id" not in json.dumps(response)
        assert finalize(server)[0] == 200
        assert json.loads(evidence_path.read_text())["calls"] == []


@pytest.mark.parametrize(
    "headers",
    [
        "",
        "Content-Length: -1\r\n",
        "Content-Length: invalid\r\n",
        "Content-Length: 1.0\r\n",
        "Content-Length: 0\r\nContent-Length: 0\r\n",
        "Transfer-Encoding: chunked\r\n",
        "Content-Length: 0\r\nTransfer-Encoding: chunked\r\n",
    ],
)
def test_invalid_framing_rejected_before_dispatch_and_poisons_only_public_completion(
    tmp_path, headers
):
    with running_server(tmp_path) as (server, path):
        status, response, elapsed = raw_request(server, headers)
        assert status == 400 and response.get("status") == "error"
        assert elapsed < 2
        assert finalize(server)[0] == 200
        evidence = json.loads(path.read_text())
        assert evidence["calls"] == evidence["audit"] == []
        assert evidence["completion"]["status"] == "failed"
        events = [event for event in evidence["protocol_events"] if event["path"] == "/call"]
        assert len(events) == 1 and events[0]["status"] == 400
        assert events[0]["received_body_length"] == 0
        assert "declared_body_length" in events[0] and events[0].get("error")
        assert PUBLIC_TOKEN not in json.dumps(events)


def test_declared_oversized_body_rejected_without_waiting_for_or_reading_body(tmp_path):
    with running_server(tmp_path) as (server, path):
        declared = MAX_BODY_BYTES + 1
        status, response, elapsed = raw_request(server, f"Content-Length: {declared}\r\n")
        assert status == 413 and response.get("status") == "error"
        assert elapsed < 2
        assert finalize(server)[0] == 200
        evidence = json.loads(path.read_text())
        assert evidence["calls"] == evidence["audit"] == []
        assert evidence["completion"]["status"] == "failed"
        event = next(row for row in evidence["protocol_events"] if row["status"] == 413)
        assert event["declared_body_length"] == declared
        assert event["received_body_length"] == 0


def test_partial_body_wait_is_bounded_and_actual_received_byte_count_is_retained(tmp_path):
    partial = b'{"name":'
    with running_server(tmp_path, socket_timeout=0.1) as (server, path):
        status, response, elapsed = raw_request(server, "Content-Length: 100\r\n", partial)
        assert status == 408 and response.get("status") == "error"
        assert elapsed < 2
        assert finalize(server)[0] == 200
        evidence = json.loads(path.read_text())
        assert evidence["calls"] == evidence["audit"] == []
        assert evidence["completion"]["status"] == "failed"
        event = next(row for row in evidence["protocol_events"] if row["status"] == 408)
        assert event["declared_body_length"] == 100
        assert event["received_body_length"] == len(partial)


def test_early_eof_is_not_a_complete_request(tmp_path):
    partial = b'{"name":'
    with running_server(tmp_path) as (server, path):
        status, response, _ = raw_request(server, "Content-Length: 100\r\n", partial, eof=True)
        assert status == 400 and response.get("status") == "error"
        assert finalize(server)[0] == 200
        evidence = json.loads(path.read_text())
        assert evidence["calls"] == evidence["audit"] == []
        assert evidence["completion"]["status"] == "failed"
        event = next(row for row in evidence["protocol_events"] if row["status"] == 400)
        assert event["received_body_length"] == len(partial)


@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
def test_unsupported_http_methods_have_controlled_recorded_405(tmp_path, method):
    with running_server(tmp_path) as (server, path):
        status, response = http_request(server, method, "/call", b"")
        assert status == 405 and response.get("status") == "error"
        assert finalize(server)[0] == 200
        evidence = json.loads(path.read_text())
        assert evidence["calls"] == evidence["audit"] == []
        assert evidence["completion"]["status"] == "failed"
        assert any(
            event["method"] == method and event["status"] == 405
            for event in evidence["protocol_events"]
        )


@pytest.mark.parametrize(
    "payload",
    [
        b'{"status":"completed","status":"failed"}',
        b'{"status":"done"}',
        b'{"status":"completed","extra":true}',
        b'{"status":"failed","error":[]}',
        b'{"status":"failed","error":{"value":NaN}}',
        b"[]",
    ],
)
def test_private_finalize_requires_strict_schema_without_closing_or_poisoning_session(
    tmp_path, payload
):
    with running_server(tmp_path) as (server, path):
        status, response = http_request(server, "POST", "/_control/finalize", payload, ADMIN_AUTH)
        assert status == 400 and response.get("status") == "error"
        assert not path.exists()
        assert http_request(server, "GET", "/health")[0] == 200
        assert finalize(server)[0] == 200
        evidence = json.loads(path.read_text())
        assert evidence["completion"]["status"] == "completed"
        assert any(
            event["path"] == "/_control/finalize" and event["status"] == 400
            for event in evidence["protocol_events"]
        )


def test_finalization_cannot_be_repeated_and_closed_session_does_not_write_again(tmp_path):
    with running_server(tmp_path) as (server, path):
        execute_reference(HTTPRecorder(server), target=load_scenario()["target"])
        assert finalize(server)[0] == 200
        saved = path.read_bytes()
        status, response = http_request(
            server,
            "POST",
            "/call",
            body(
                {
                    "name": "updateEncounter",
                    "params": {"encounter_id": "ENC-AAAAAAAA", "notes": "must not persist"},
                }
            ),
        )
        assert status == 409 and response.get("status") == "error"
        assert finalize(server)[0] == 409
        assert path.read_bytes() == saved
        assert len(json.loads(saved)["after"]["entities"]["clinical_note"]) == 1


def test_existing_evidence_path_is_rejected_before_server_can_overwrite(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text("prior evidence\n")
    session = ReconciliationSession(token=PUBLIC_TOKEN)
    try:
        with pytest.raises(FileExistsError):
            server_class()(("127.0.0.1", 0), session, admin_token=ADMIN_TOKEN, evidence_path=path)
        assert path.read_text() == "prior evidence\n"
    finally:
        session.close()


def test_public_and_private_credentials_must_differ(tmp_path):
    session = ReconciliationSession(token=PUBLIC_TOKEN)
    try:
        with pytest.raises(ValueError):
            server_class()(
                ("127.0.0.1", 0),
                session,
                admin_token=PUBLIC_TOKEN,
                evidence_path=tmp_path / "evidence.json",
            )
    finally:
        session.close()


@pytest.mark.parametrize("timeout", [0, -0.1, 30.1, float("inf"), float("-inf"), float("nan")])
def test_socket_wait_must_be_positive_finite_and_at_most_thirty_seconds(tmp_path, timeout):
    session = ReconciliationSession(token=PUBLIC_TOKEN)
    try:
        with pytest.raises(ValueError):
            server_class()(
                ("127.0.0.1", 0),
                session,
                admin_token=ADMIN_TOKEN,
                evidence_path=tmp_path / "evidence.json",
                socket_timeout=timeout,
            )
    finally:
        session.close()


def wire_bytes(server, request_bytes):
    """Send one complete raw request without normalizing malformed framing."""
    with socket.create_connection(server.server_address, timeout=2) as connection:
        connection.settimeout(2)
        connection.sendall(request_bytes)
        chunks = []
        while chunk := connection.recv(65536):
            chunks.append(chunk)
    return b"".join(chunks)


@pytest.mark.parametrize(
    "request_bytes,expected_status",
    [
        (b"TRACE /call HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n", 501),
        (b"GET /health HTTP/not-a-version\r\nHost: localhost\r\n\r\n", 400),
        (b"GET /health HTTP/1.1\r\nHost: localhost\r\nX-Long: " + b"x" * 66_000 + b"\r\n\r\n", 431),
        (b"GET /" + b"x" * 66_000 + b" HTTP/1.1\r\nHost: localhost\r\n\r\n", 414),
    ],
    ids=["unknown-method", "malformed-version", "long-header", "long-target"],
)
def test_stdlib_rejections_are_controlled_json_and_cannot_leave_clean_completion(
    tmp_path, request_bytes, expected_status
):
    with running_server(tmp_path) as (server, path):
        raw = wire_bytes(server, request_bytes)
        assert finalize(server)[0] == 200
        evidence = json.loads(path.read_text())
        assert evidence["calls"] == evidence["audit"] == []
        assert evidence["completion"]["status"] == "failed"
        events = [
            event for event in evidence["protocol_events"] if event["path"] != "/_control/finalize"
        ]
        assert len(events) == 1
        event = events[0]
        assert event["status"] == expected_status and event.get("error")
        assert event["received_body_length"] == 0
        assert PUBLIC_TOKEN not in json.dumps(event) and ADMIN_TOKEN not in json.dumps(event)
        headers, response_bytes = raw.split(b"\r\n\r\n", 1)
        assert int(headers.split(b" ", 2)[1]) == expected_status
        assert b"application/json" in headers.lower()
        assert json.loads(response_bytes)["status"] == "error"


def test_timeout_while_parsing_headers_is_retained_before_tool_dispatch(tmp_path):
    # The request line exists, but the header block never completes. This
    # timeout occurs inside BaseHTTPRequestHandler.parse_request, before _handle.
    with running_server(tmp_path, socket_timeout=0.1) as (server, path):
        raw = wire_bytes(server, b"GET /health HTTP/1.1\r\nHost: localhost")
        assert finalize(server)[0] == 200
        evidence = json.loads(path.read_text())
        assert evidence["calls"] == evidence["audit"] == []
        assert evidence["completion"]["status"] == "failed"
        events = [
            event for event in evidence["protocol_events"] if event["path"] != "/_control/finalize"
        ]
        assert len(events) == 1
        assert events[0]["status"] == 408 and events[0].get("error")
        assert events[0]["received_body_length"] == 0
        headers, response_bytes = raw.split(b"\r\n\r\n", 1)
        assert int(headers.split(b" ", 2)[1]) == 408
        assert json.loads(response_bytes)["status"] == "error"
