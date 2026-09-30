"""Private reconciliation state with an authenticated public tool surface.

Only the coordinator can finalize the in-memory session. The public surface
does not serve world snapshots, oracle labels, audit logs or completion controls.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import threading
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from healthcraft.mcp.server import TOOL_NAME_MAP, create_server
from healthcraft.reconciliation.execution import ReconciliationRecorder, scenario_digest
from healthcraft.reconciliation.fixture import build_world, load_scenario, snapshot_world
from healthcraft.tasks.history_execution import _json_snapshot

PUBLIC_TOOLS = frozenset(
    {
        "searchPatients",
        "searchEncounters",
        "getPatientHistory",
        "getEncounterDetails",
        "updateEncounter",
    }
)
MAX_BODY_BYTES = 1_048_576
BODY_PREFIX_BYTES = 4096


def strict_json(data: bytes | str):
    """Parse finite JSON without silently collapsing duplicate object keys."""

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate object key")
            result[key] = value
        return result

    def number(value):
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("Non-finite JSON number")
        return value

    return json.loads(data, object_pairs_hook=pairs, parse_constant=number, parse_float=number)


def _error(code: str) -> dict:
    return {"status": "error", "code": code}


class ReconciliationSession:
    """Serialize actual tool dispatch, source snapshots and durable evidence.

    A malformed or refused transport request is retained separately from MCP
    calls. It cannot fabricate an audit entry, disappear from the attempt, or
    establish a clean completion. These are local consistency records, not
    third-party attestations or a general multi-tenant clinical service.
    """

    def __init__(
        self, *, scenario: dict | None = None, token: str, journal_dir: Path | None = None
    ) -> None:
        if type(token) is not str or not token or any(char.isspace() for char in token):
            raise ValueError("A nonempty session token without whitespace is required")
        self._authorization = ("Bearer " + token).encode("utf-8")
        self._scenario = deepcopy(scenario) if scenario is not None else load_scenario()
        self._world = build_world(self._scenario)
        self._before = snapshot_world(self._world)
        self._server = create_server(self._world)
        # Keep actual middleware and handlers, including rejected-attempt audit.
        allowed = {TOOL_NAME_MAP[name] for name in PUBLIC_TOOLS}
        self._server._handlers = {
            name: handler for name, handler in self._server._handlers.items() if name in allowed
        }
        tool_path = Path(__file__).resolve().parents[3] / "configs/mcp-tools.json"
        self._tools = [
            tool
            for tool in strict_json(tool_path.read_bytes())["tools"]
            if tool["name"] in PUBLIC_TOOLS
        ]
        if {tool["name"] for tool in self._tools} != PUBLIC_TOOLS:
            raise ValueError("Public tool schemas are incomplete")
        if journal_dir is not None:
            journal_dir.mkdir(parents=True, exist_ok=False)
        self._recorder = ReconciliationRecorder(
            self._server,
            self._world,
            journal_path=journal_dir / "calls.jsonl" if journal_dir is not None else None,
        )
        self._transport_stream = (
            (journal_dir / "transport.jsonl").open("x", encoding="utf-8")
            if journal_dir is not None
            else None
        )
        self._transport: list[dict] = []
        self._lock = threading.RLock()
        self._closed = False

    def _journal(self, phase: str, event: dict) -> None:
        if self._transport_stream is not None:
            self._transport_stream.write(json.dumps({"event": phase, "transport": event}) + "\n")
            self._transport_stream.flush()
            os.fsync(self._transport_stream.fileno())

    def handle(
        self, method: str, path: str, body: bytes = b"", authorization: str = ""
    ) -> tuple[int, dict]:
        with self._lock:
            if self._closed:
                return 409, _error("session_closed")
            if type(body) is not bytes or type(method) is not str or type(path) is not str:
                raise ValueError("Transport method/path/body types are invalid")
            event = {
                "id": f"transport-{len(self._transport) + 1:04d}",
                "method": method,
                "path": path,
                "raw_body_b64": base64.b64encode(body[:BODY_PREFIX_BYTES]).decode("ascii"),
                "body_length": len(body),
                "body_truncated": len(body) > BODY_PREFIX_BYTES,
                "body_sha256": hashlib.sha256(body).hexdigest(),
                "status": None,
            }
            self._transport.append(event)
            self._journal("requested", event)
            status, response = 500, _error("transport_execution_error")
            try:
                authorized = type(authorization) is str and hmac.compare_digest(
                    authorization.encode("utf-8"), self._authorization
                )
                if not authorized:
                    status, response = 401, _error("unauthorized")
                elif len(body) > MAX_BODY_BYTES:
                    status, response = 413, _error("body_too_large")
                elif (method, path) == ("GET", "/health"):
                    status, response = 200, {"status": "ok"}
                elif (method, path) == ("GET", "/tools"):
                    status, response = 200, {"tools": deepcopy(self._tools)}
                elif (method, path) == ("POST", "/call"):
                    try:
                        request = strict_json(body.decode("utf-8"))
                        if (
                            type(request) is not dict
                            or set(request) != {"name", "params"}
                            or type(request["name"]) is not str
                            or not request["name"]
                            or type(request["params"]) is not dict
                        ):
                            raise ValueError("Malformed call request")
                    except (ValueError, UnicodeError, RecursionError):
                        status, response = 400, _error("invalid_request")
                    else:
                        status = 200
                        response = self._recorder.call(request["name"], request["params"])
                else:
                    status, response = 404, _error("unknown_route")
            except (Exception, KeyboardInterrupt) as exc:
                status, response = 500, _error("transport_execution_error")
                event["error_type"] = type(exc).__name__
                if isinstance(exc, KeyboardInterrupt):
                    raise
            finally:
                event["status"] = status
                event["response"] = deepcopy(response)
                self._journal("returned", event)
            return status, deepcopy(response)

    def finalize(self, status: str, *, error: dict | None = None) -> dict:
        if status not in ("completed", "interrupted", "failed"):
            raise ValueError("Unsupported completion status")
        if error is not None and type(error) is not dict:
            raise ValueError("Completion error must be an object")
        detached_error = strict_json(json.dumps(error, allow_nan=False)) if error else None
        with self._lock:
            if self._closed:
                raise ValueError("Session is already closed")
            completion = {"status": status}
            if detached_error:
                completion["error"] = detached_error
            transport_failures = sum(event["status"] != 200 for event in self._transport)
            if transport_failures and status == "completed":
                completion = {
                    "status": "failed",
                    "error": {"type": "TransportFailure", "count": transport_failures},
                }
                if detached_error:
                    completion["controller_error"] = detached_error
            evidence = {
                "schema_version": "healthcraft-reconciliation-execution/v1",
                "execution_kind": "private_tool_session",
                "scenario_sha256": scenario_digest(self._scenario),
                "before": deepcopy(self._before),
                "after": snapshot_world(self._world),
                "calls": self._recorder.calls,
                "audit": _json_snapshot([asdict(entry) for entry in self._world.audit_log]),
                "completion": completion,
                "transport_events": deepcopy(self._transport),
            }
            self.close()
            return evidence

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._recorder.close()
            if self._transport_stream is not None:
                self._transport_stream.close()
                self._transport_stream = None
