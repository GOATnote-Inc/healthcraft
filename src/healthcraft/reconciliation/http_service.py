"""Bounded local HTTP transport and private coordinator finalization.

This research harness is intended for loopback or an isolated container network.
The independent oracle runs outside the agent container. HTTP success is not an
assertion of source fidelity, persistence correctness, or clinical validity.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import math
import os
import signal
import threading
import time
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from healthcraft.reconciliation.service import (
    BODY_PREFIX_BYTES,
    MAX_BODY_BYTES,
    ReconciliationSession,
    strict_json,
)

CONTROL_PATH = "/_control/finalize"


def _error(code: str) -> dict:
    return {"status": "error", "code": code}


class ReconciliationHTTPServer(ThreadingHTTPServer):
    """Expose public tools and a separately credentialed, write-once coordinator.

    Protocol records describe bytes actually consumed, not the entire wire
    payload. A refused oversized declaration is not read or hashed as a body.
    Socket/body waits are bounded; an external supervisor bounds a whole trial.
    """

    daemon_threads = False
    allow_reuse_address = False

    def __init__(
        self,
        address: tuple[str, int],
        session: ReconciliationSession,
        *,
        admin_token: str,
        evidence_path: Path,
        socket_timeout: float = 5.0,
    ) -> None:
        if (
            type(admin_token) is not str
            or not admin_token
            or any(not 33 <= ord(char) <= 126 for char in admin_token)
        ):
            raise ValueError("A printable nonempty coordinator credential is required")
        authorization = ("Bearer " + admin_token).encode("utf-8")
        if hmac.compare_digest(authorization, session._authorization):
            raise ValueError("Public and coordinator credentials must differ")
        if (
            type(socket_timeout) not in (int, float)
            or not math.isfinite(socket_timeout)
            or not 0 < socket_timeout <= 30
        ):
            raise ValueError("Socket timeout must be finite and in (0, 30]")
        self.evidence_path = Path(evidence_path)
        if self.evidence_path.exists():
            raise FileExistsError(self.evidence_path)
        self.session = session
        self._admin_authorization = authorization
        self.socket_timeout = socket_timeout
        self._protocol_lock = threading.RLock()
        self._events: list[dict] = []
        self._finalized = False
        self._protocol_stream = None
        # Bind first so a refused listener does not leave a misleading journal.
        super().__init__(address, _Handler)
        try:
            self._protocol_stream = (self.evidence_path.parent / "protocol.jsonl").open(
                "x", encoding="utf-8"
            )
        except BaseException:
            super().server_close()
            raise

    @property
    def protocol_events(self) -> list[dict]:
        with self._protocol_lock:
            return deepcopy(self._events)

    @property
    def finalized(self) -> bool:
        return self._finalized

    def _journal(self, phase: str, event: dict) -> None:
        if self._protocol_stream is not None:
            self._protocol_stream.write(
                json.dumps({"event": phase, "protocol": event}, allow_nan=False) + "\n"
            )
            self._protocol_stream.flush()
            os.fsync(self._protocol_stream.fileno())

    def finalize(self, status: str, *, error: dict | None = None) -> dict:
        """Persist actual state once; return only its content identity to caller."""
        with self._protocol_lock:
            if self._finalized:
                raise ValueError("Session is already finalized")
            failures = sum(
                row["path"] != CONTROL_PATH
                and (row["status"] != 200 or row.get("response_delivery") == "failed")
                for row in self._events
            )
            if failures and status == "completed":
                status = "failed"
                error = {
                    "type": "HTTPProtocolFailure",
                    "count": failures,
                    "controller_error": error,
                }
            # Reserve before closing the session; never overwrite existing data.
            with self.evidence_path.open("xb") as stream:
                evidence = self.session.finalize(status, error=error)
                evidence["protocol_events"] = deepcopy(self._events)
                raw = (
                    json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False) + "\n"
                ).encode()
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            self._finalized = True
            return {"status": "ok", "sha256": hashlib.sha256(raw).hexdigest()}

    def server_close(self) -> None:
        super().server_close()  # Join handlers before closing their shared journal.
        with self._protocol_lock:
            if self._protocol_stream is not None:
                self._protocol_stream.close()
                self._protocol_stream = None


class _Handler(BaseHTTPRequestHandler):
    server: ReconciliationHTTPServer
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(self.server.socket_timeout)

    def log_message(self, format, *args) -> None:
        # Never log Authorization, arbitrary request headers, or supplied paths.
        pass

    def parse_request(self) -> bool:
        try:
            return super().parse_request()
        except (TimeoutError, ConnectionError):
            self.send_error(408)
            return False

    def send_error(self, code, message=None, explain=None) -> None:
        """Retain rejections generated before the application's route handler."""
        self.close_connection = True
        event = {
            "method": getattr(self, "command", None),
            "path": getattr(self, "path", ""),
            "declared_body_length": None,
            "received_body_length": 0,
            "status": code,
            "error": "http_parser_rejection",
        }
        with self.server._protocol_lock:
            event["id"] = f"http-{len(self.server._events) + 1:04d}"
            self.server._events.append(event)
            self.server._journal("parser_rejected", event)
        # Malformed request versions leave stdlib in its HTTP/0.9 mode, which
        # would otherwise suppress status/headers on our JSON error response.
        self.request_version = "HTTP/1.1"
        raw = json.dumps(_error("http_parser_rejection")).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(raw)
            event["response_delivery"] = "written_to_socket"
        except (OSError, TimeoutError):
            event["response_delivery"] = "failed"
        finally:
            with self.server._protocol_lock:
                self.server._journal("parser_response_write", event)

    def _handle(self) -> None:
        self.close_connection = True
        event = {
            "method": self.command,
            "path": self.path,
            "declared_body_length": None,
            "received_body_length": 0,
            "status": None,
        }
        with self.server._protocol_lock:
            event["id"] = f"http-{len(self.server._events) + 1:04d}"
            self.server._events.append(event)
            self.server._journal("received_headers", event)
        content = bytearray()
        status, response = 500, _error("http_execution_error")
        try:
            lengths = self.headers.get_all("Content-Length", [])
            if (
                self.headers.get_all("Transfer-Encoding")
                or len(lengths) > 1
                or (self.command == "POST" and not lengths)
                or (lengths and (not lengths[0].isascii() or not lengths[0].isdigit()))
            ):
                status, response = 400, _error("invalid_framing")
            else:
                length = int(lengths[0]) if lengths else 0
                event["declared_body_length"] = length if lengths else None
                if length > MAX_BODY_BYTES:
                    status, response = 413, _error("body_too_large")
                elif self.command not in {"GET", "POST"}:
                    status, response = 405, _error("method_not_allowed")
                else:
                    deadline = time.monotonic() + self.server.socket_timeout
                    while len(content) < length:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError
                        self.connection.settimeout(remaining)
                        chunk = self.rfile.read1(min(65536, length - len(content)))
                        if not chunk:
                            break
                        content.extend(chunk)
                    if len(content) != length:
                        status, response = 400, _error("incomplete_body")
                    else:
                        status, response = self._dispatch(bytes(content))
        except (TimeoutError, ConnectionError):
            status, response = 408, _error("body_timeout")
        except (Exception, KeyboardInterrupt) as exc:
            event["error_type"] = type(exc).__name__
            status, response = 500, _error("http_execution_error")
        event["received_body_length"] = len(content)
        event["received_body_sha256"] = hashlib.sha256(content).hexdigest()
        event["received_prefix_b64"] = base64.b64encode(content[:BODY_PREFIX_BYTES]).decode()
        event["received_prefix_truncated"] = len(content) > BODY_PREFIX_BYTES
        event["status"] = status
        if status != 200:
            event["error"] = response["code"]
        with self.server._protocol_lock:
            self.server._journal("response_prepared", event)
        try:
            raw = json.dumps(response, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(raw)
            event["response_delivery"] = "written_to_socket"
        except (OSError, TimeoutError):
            # A stored mutation may have happened even if its response was lost.
            event["response_delivery"] = "failed"
        finally:
            with self.server._protocol_lock:
                self.server._journal("response_write", event)

    def _dispatch(self, content: bytes) -> tuple[int, dict]:
        if (self.command, self.path) != ("POST", CONTROL_PATH):
            return self.server.session.handle(
                self.command, self.path, content, self.headers.get("Authorization", "")
            )
        authorization = self.headers.get("Authorization", "").encode("utf-8")
        if not hmac.compare_digest(authorization, self.server._admin_authorization):
            return 401, _error("unauthorized")
        try:
            request = strict_json(content.decode("utf-8"))
            if (
                type(request) is not dict
                or set(request) not in ({"status"}, {"status", "error"})
                or request["status"] not in ("completed", "failed", "interrupted")
                or ("error" in request and type(request["error"]) is not dict)
            ):
                raise ValueError
        except (ValueError, UnicodeError, RecursionError):
            return 400, _error("invalid_request")
        if self.server.finalized:
            return 409, _error("session_closed")
        return 200, self.server.finalize(request["status"], error=request.get("error"))

    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle
    do_DELETE = _handle
    do_PATCH = _handle
    do_HEAD = _handle
    do_OPTIONS = _handle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--public-token-file", type=Path, required=True)
    parser.add_argument("--admin-token-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    session = ReconciliationSession(
        token=args.public_token_file.read_text().strip(), journal_dir=args.output_dir / "journal"
    )
    server = ReconciliationHTTPServer(
        (args.host, args.port),
        session,
        admin_token=args.admin_token_file.read_text().strip(),
        evidence_path=args.output_dir / "evidence.json",
    )

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if not server.finalized:
            server.finalize("interrupted", error={"type": "ServerStoppedBeforeFinalization"})
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
