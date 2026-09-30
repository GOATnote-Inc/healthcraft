"""Shared text-command pilot engine; execution arms supply only public responses.

The proposed pilot defaults require an external process supervisor for a hard
wall-clock cap. Socket waits and cooperative checks are not cancellation of a
blocked host thread. Neither model finish nor this scripted reference constitutes
clinical assessment or an independent persistence verdict.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import time
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, Callable

from healthcraft.llm.local_models import OllamaClient
from healthcraft.reconciliation.terminal import _json_object, _json_text

PUBLIC_TOOLS = frozenset(
    {
        "searchPatients",
        "searchEncounters",
        "getPatientHistory",
        "getEncounterDetails",
        "updateEncounter",
    }
)
SYSTEM_PROMPT = (
    "You are performing a synthetic source-record reconciliation exercise. Use only the "
    "public instruction and returned records. Do not provide medical advice. Each response "
    "must be exactly one finite JSON object, without Markdown or surrounding prose: "
    '{"action":"call","name":"<advertised tool>","params":{...}} or '
    '{"action":"finish"}. Issue one command per response. Preserve source values and '
    "unknowns exactly. Finish only after the requested write and readback. A finish marker "
    "ends the interaction; independent verification determines whether the stored result "
    "satisfies the exercise."
)


def canonical_json(value: Any) -> str:
    """Encode one shared model-visible representation without lossy coercion."""
    _json_text(value)
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )


def _copy(value: Any) -> Any:
    return json.loads(canonical_json(value))


def command_format_schema() -> dict:
    """Return the detached v2 syntax-only native decoding schema.

    Parameters remain open: this envelope does not encode source facts, valid
    clinical actions or the independent reconciliation success conditions.
    """
    return {
        "anyOf": [
            {
                "type": "object",
                "properties": {
                    "action": {"const": "call"},
                    "name": {"enum": sorted(PUBLIC_TOOLS)},
                    "params": {"type": "object", "additionalProperties": True},
                },
                "required": ["action", "name", "params"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {"action": {"const": "finish"}},
                "required": ["action"],
                "additionalProperties": False,
            },
        ]
    }


def command_format_identity() -> dict[str, str]:
    """Identify the schema separately from the unchanged initial messages."""
    return {
        "version": "healthcraft-reconciliation-command/v2",
        "sha256": hashlib.sha256(
            canonical_json(command_format_schema()).encode("utf-8")
        ).hexdigest(),
    }


def validate_command_format(value: Any) -> dict[str, str]:
    """Reject unknown/malformed opt-ins without silently changing decoding."""
    if type(value) is not dict or value != command_format_identity():
        raise ValueError("Unsupported or mismatched command format identity")
    return _copy(value)


def _tools_snapshot(tools: list[dict]) -> list[dict]:
    if type(tools) is not list or len(tools) != len(PUBLIC_TOOLS):
        raise ValueError("Exactly five public schemas are required")
    if (
        any(
            type(tool) is not dict
            or type(tool.get("name")) is not str
            or type(tool.get("parameters")) is not dict
            for tool in tools
        )
        or {tool["name"] for tool in tools} != PUBLIC_TOOLS
    ):
        raise ValueError("Public tool discovery is malformed or incomplete")
    return sorted(_copy(tools), key=lambda tool: tool["name"])


@dataclass(frozen=True)
class PilotSettings:
    """Proposed, explicitly recorded limits; freeze before any live pilot."""

    max_model_responses: int = 16
    max_output_tokens: int = 4096
    num_ctx: int = 32768
    seed: int = 42
    temperature: float = 0.0
    think: bool = False
    request_timeout_seconds: float = 240
    attempt_timeout_seconds: float = 900
    keep_alive: int = 0

    def __post_init__(self):
        for field in ("max_model_responses", "max_output_tokens", "num_ctx"):
            if type(getattr(self, field)) is not int or getattr(self, field) <= 0:
                raise ValueError(f"{field} must be a positive integer")
        if type(self.seed) is not int or type(self.think) is not bool:
            raise ValueError("Seed and thinking flag must have exact types")
        for field in ("request_timeout_seconds", "attempt_timeout_seconds", "temperature"):
            value = getattr(self, field)
            if type(value) not in {float, int} or not math.isfinite(value):
                raise ValueError(f"{field} must be finite numeric")
        if min(self.request_timeout_seconds, self.attempt_timeout_seconds) <= 0:
            raise ValueError("Timeouts must be positive")
        if self.temperature < 0 or type(self.keep_alive) is not int or self.keep_alive != 0:
            raise ValueError("Temperature must be nonnegative and keep_alive must be zero")
        if self.think:
            raise ValueError("This common text-command pilot disables thinking")


class RecordingOllamaClient(OllamaClient):
    """Native local transport with immediate evidence events and fresh identities.

    A supplied event sink must durably persist events synchronously to survive a
    hard process kill. The in-memory copies alone are not durable capture.
    """

    def __init__(
        self,
        *,
        model: str,
        expected_digest: str,
        expected_runtime: str,
        settings: PilotSettings | None = None,
        event_sink: Callable[[dict], None] | None = None,
        base_url: str = "http://127.0.0.1:11434",
        command_format: dict | None = None,
    ):
        self.settings = settings or PilotSettings()
        self._command_format = (
            validate_command_format(command_format) if command_format is not None else None
        )
        if not expected_digest or not expected_runtime:
            raise ValueError("An expected model digest and runtime version are required")
        self.expected_digest = expected_digest
        self.expected_runtime = expected_runtime
        self.event_sink = event_sink or (lambda event: None)
        self._exchanges: list[dict] = []
        self.identity_before: dict | None = None
        self.identity_after: dict | None = None
        super().__init__(
            model,
            base_url=base_url,
            seed=self.settings.seed,
            num_ctx=self.settings.num_ctx,
            timeout=self.settings.request_timeout_seconds,
            think=self.settings.think,
        )

    @property
    def exchanges(self) -> list[dict]:
        return deepcopy(self._exchanges)

    @property
    def command_format(self) -> dict[str, str] | None:
        return deepcopy(self._command_format)

    def _transport_request(self, path, payload=None):
        return super()._request(path, payload)

    def _response_received(self, path: str, body: bytes) -> None:
        if path == "/api/chat":
            exchange = self._exchanges[-1]
            exchange["response_body_b64"] = base64.b64encode(body).decode("ascii")
            exchange["response_body_sha256"] = hashlib.sha256(body).hexdigest()
            self.event_sink({"event": "model_response_received", "exchange": deepcopy(exchange)})

    def _request(self, path, payload=None):
        if path != "/api/chat":
            return self._transport_request(path, payload)
        if len(self._exchanges) >= self.settings.max_model_responses:
            raise RuntimeError("Model response limit reached")
        payload = {**_copy(payload), "keep_alive": self.settings.keep_alive}
        if self._command_format is not None:
            payload["format"] = command_format_schema()
        exchange = {
            "index": len(self._exchanges) + 1,
            "request": payload,
            "response": None,
            "error": None,
        }
        self._exchanges.append(exchange)
        self.event_sink({"event": "model_dispatched", "exchange": deepcopy(exchange)})
        try:
            response = self._transport_request(path, deepcopy(payload))
            exchange["response"] = deepcopy(response)
            self.event_sink({"event": "model_returned", "exchange": deepcopy(exchange)})
            return response
        except (Exception, KeyboardInterrupt) as exc:
            exchange["error"] = {"type": type(exc).__name__, "message": str(exc)}
            self.event_sink({"event": "model_failed", "exchange": deepcopy(exchange)})
            raise

    def _check_identity(self, info):
        if (info.get("model_digest"), info.get("runtime_version")) != (
            self.expected_digest,
            self.expected_runtime,
        ):
            raise ValueError("Installed model digest or runtime differs from frozen identity")

    def preflight(self) -> dict:
        info = self.model_metadata()
        self.identity_before = deepcopy(info)
        self._check_identity(info)
        return deepcopy(info)

    def postflight(self) -> dict:
        # Clear the native cache: reading a cached identity cannot establish no drift.
        self._info = None
        info = self.model_metadata()
        self.identity_after = deepcopy(info)
        self._check_identity(info)
        return deepcopy(info)

    def chat(self, messages, tools=None, temperature=0.0, max_tokens=4096):
        if (
            tools is not None
            or temperature != self.settings.temperature
            or max_tokens != self.settings.max_output_tokens
        ):
            raise ValueError("Only the frozen text-command request settings are supported")
        if self.identity_before is None:
            self.preflight()
        self._check_identity(self.model_metadata())
        result = super().chat(messages, tools=None, temperature=temperature, max_tokens=max_tokens)
        raw = self._exchanges[-1]["response"]
        message = raw.get("message") if type(raw) is dict else None
        if (
            raw.get("done") is not True
            or raw.get("done_reason") != "stop"
            or raw.get("model") != self._model
            or type(message) is not dict
            or message.get("role") != "assistant"
            or type(message.get("content")) is not str
            or message.get("tool_calls")
            or message.get("refusal")
            or message.get("thinking")
            or result.get("stop_reason") != "stop"
        ):
            raise ValueError(
                "Native response did not explicitly complete one assistant text command"
            )
        for field in ("prompt_eval_count", "eval_count"):
            if field in raw and (type(raw[field]) is not int or raw[field] < 0):
                raise ValueError("Native token counter is invalid")
        return result


class CommandController:
    """Arm-independent single-attempt state machine; no automatic repair/retry."""

    def __init__(
        self,
        instruction: str,
        tools: list[dict],
        *,
        settings: PilotSettings | None = None,
        event_sink: Callable[[dict], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        command_format: dict | None = None,
    ):
        if type(instruction) is not str or not instruction.strip():
            raise ValueError("A public instruction is required")
        self._command_format = (
            validate_command_format(command_format) if command_format is not None else None
        )
        self.settings = settings or PilotSettings()
        self._sink = event_sink or (lambda event: None)
        self._clock = clock
        self._started = clock()
        self._messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": canonical_json(
                    {"instruction": instruction, "tools": _tools_snapshot(tools)}
                ),
            },
        ]
        self._requests = 0
        self._calls: list[dict] = []
        self._pending: dict | None = None
        self._completion = {"status": "running"}
        self._emit("controller_started")

    def _emit(self, event):
        self._sink({"event": event, "controller": self.snapshot()})

    def snapshot(self) -> dict:
        value = {
            "schema_version": (
                "healthcraft-reconciliation-controller/v2"
                if self._command_format is not None
                else "healthcraft-reconciliation-controller/v1"
            ),
            "settings": asdict(self.settings),
            "messages": self._messages,
            "model_requests": self._requests,
            "calls": self._calls,
            "completion": self._completion,
            "benchmark_score": None,
            "benchmark_comparable": False,
            "grading_complete": False,
            "clinical_criteria": 0,
            "safety_criteria": 0,
        }
        if self._command_format is not None:
            value["command_format"] = self._command_format
        return _copy(value)

    def fail(self, exc: BaseException, *, reason="controller_error") -> None:
        self._completion = {
            "status": "failed",
            "reason": reason,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
        self._emit("controller_failed")

    def _deadline(self):
        if self._clock() - self._started >= self.settings.attempt_timeout_seconds:
            exc = TimeoutError("Attempt deadline reached; no subsequent work permitted")
            self.fail(exc, reason="attempt_deadline")
            raise exc

    def next_command(self, client: RecordingOllamaClient) -> dict:
        if self._completion["status"] != "running" or self._pending is not None:
            raise RuntimeError("Controller has terminated or requires the pending response")
        self._deadline()
        if self._requests >= self.settings.max_model_responses:
            exc = RuntimeError("Model response limit reached before finish")
            self.fail(exc, reason="model_response_limit")
            raise exc
        if client.settings != self.settings:
            exc = ValueError("Controller and model settings disagree")
            self.fail(exc, reason="settings_mismatch")
            raise exc
        if getattr(client, "command_format", None) != self._command_format:
            exc = ValueError("Controller and model command format disagree")
            self.fail(exc, reason="command_format_mismatch")
            raise exc
        self._requests += 1
        self._emit("model_requested")
        try:
            response = client.chat(
                _copy(self._messages),
                tools=None,
                temperature=self.settings.temperature,
                max_tokens=self.settings.max_output_tokens,
            )
            content = response["content"]
            self._messages.append({"role": "assistant", "content": content})
            self._deadline()
            command = _json_object(content)
            if command == {"action": "finish"}:
                self._completion = {"status": "terminated", "reason": "model_finish"}
                self._emit("controller_terminated")
            elif (
                set(command) == {"action", "name", "params"}
                and command["action"] == "call"
                and type(command["name"]) is str
                and command["name"] in PUBLIC_TOOLS
                and type(command["params"]) is dict
            ):
                self._pending = {"command": _copy(command), "response": None}
                self._calls.append(self._pending)
                self._emit("tool_requested")
            else:
                raise ValueError("Expected exactly one advertised call or finish command")
            return _copy(command)
        except (Exception, KeyboardInterrupt) as exc:
            if self._completion["status"] != "failed":
                self.fail(exc, reason="model_error")
            raise

    def accept_result(self, response: dict) -> None:
        if self._pending is None or self._completion["status"] != "running":
            raise RuntimeError("No pending command accepts a response")
        # Preserve a response that arrived after the deadline before refusing further work.
        try:
            value = _copy(response)
            self._pending["response"] = value
            if type(value) is not dict or value.get("status") not in {"ok", "error"}:
                raise ValueError("Tool response status is missing or unsupported")
            self._messages.append(
                {
                    "role": "user",
                    "content": canonical_json(
                        {
                            "type": "command_result",
                            "name": self._pending["command"]["name"],
                            "response": value,
                        }
                    ),
                }
            )
            self._pending = None
            self._emit("tool_returned")
            self._deadline()
            if value["status"] == "error":
                raise RuntimeError("Tool returned an error; this attempt will not retry")
        except (Exception, KeyboardInterrupt) as exc:
            if self._completion["status"] != "failed":
                self.fail(exc, reason="tool_error")
            raise


def _reference_call(name: str, params: dict):
    response = yield {"action": "call", "name": name, "params": _copy(params)}
    if type(response) is not dict or response.get("status") != "ok" or "data" not in response:
        raise ValueError("Reference tool call failed or returned malformed data")
    return _copy(response["data"])


def _source_records(encounter: dict) -> list[dict]:
    """Read raw authored rows from returned projections, never typed guesses."""
    rows = []

    def collect(value: Any, *, collection: str, path: str) -> None:
        if isinstance(value, dict) and "source_id" in value:
            rows.append(
                {
                    "source_id": value["source_id"],
                    "patient_id": encounter["patient_id"],
                    "encounter_id": encounter["id"],
                    "source_collection": collection,
                    "source_path": path,
                    "source": deepcopy(value),
                }
            )
        elif isinstance(value, dict):
            for key, child in value.items():
                escaped = key.replace("~", "~0").replace("/", "~1")
                collect(child, collection=collection, path=f"{path}/{escaped}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                collect(child, collection=collection, path=f"{path}/{index}")

    for projection in (*encounter["authored_care"], *encounter["imaging"]):
        path = projection["source_path"]
        if not path.startswith("/patient/"):
            raise ValueError("Unexpected source pointer namespace")
        collect(
            projection["source_data"],
            collection=projection["source_collection"],
            path=path[len("/patient") :],
        )
    return rows


def reference_commands(tools, *, target: dict):
    """Reconcile the closed synthetic same-name cohort and persist/read back.

    This narrow reference does not solve arbitrary clinical contradictions.
    It retains opposing literal reported-status assertions for the same event.
    Saturated searches are rejected because these handlers expose no offset.
    """
    _tools_snapshot(tools)
    patient_id, encounter_id = (target["patient_id"], target["encounter_id"])
    history = yield from _reference_call("getPatientHistory", {"patient_id": patient_id})
    if history.get("id") != patient_id:
        raise ValueError("Patient history identity mismatch")
    name = f"{history['first_name']} {history['last_name']}"
    patients = yield from _reference_call("searchPatients", {"name": name})
    if len(patients) >= 10:
        raise ValueError("Patient search saturated; completeness cannot be established")
    if patient_id not in {row["id"] for row in patients}:
        raise ValueError("Target absent from same-name cohort")
    records = []
    seen_encounters = set()
    for patient in sorted(patients, key=lambda row: row["id"]):
        encounters = yield from _reference_call("searchEncounters", {"patient_id": patient["id"]})
        if len(encounters) >= 10:
            raise ValueError("Encounter search saturated; completeness cannot be established")
        for row in sorted(encounters, key=lambda row: row["id"]):
            if row["patient_id"] != patient["id"] or row["id"] in seen_encounters:
                raise ValueError("Encounter search identity mismatch or duplicate")
            seen_encounters.add(row["id"])
            details = yield from _reference_call("getEncounterDetails", {"encounter_id": row["id"]})
            if details.get("id") != row["id"] or details.get("patient_id") != patient["id"]:
                raise ValueError("Encounter details identity mismatch")
            records.extend(_source_records(details))
    if encounter_id not in seen_encounters:
        raise ValueError("Target encounter was not retrieved")
    ids = [row["source_id"] for row in records]
    if len(set(ids)) != len(ids):
        raise ValueError("Ambiguous duplicate source identifiers")
    included, excluded = ([], [])
    for row in sorted(records, key=lambda row: row["source_id"]):
        if row["patient_id"] == patient_id and row["encounter_id"] == encounter_id:
            included.append(row)
        else:
            excluded.append(
                {key: row[key] for key in ("source_id", "patient_id", "encounter_id")}
                | {
                    "reason": "other_patient"
                    if row["patient_id"] != patient_id
                    else "other_encounter"
                }
            )
    if not included:
        raise ValueError("No current-encounter source records")
    events: dict[str, list[dict]] = defaultdict(list)
    for row in included:
        if row["source"].get("event_id"):
            events[row["source"]["event_id"]].append(row)
    conflicts = []
    for event_id, rows in sorted(events.items()):
        statuses = {row["source"].get("reported_status") for row in rows}
        if {"administered", "not_administered"} <= statuses:
            conflicts.append(
                {
                    "source_ids": sorted((row["source_id"] for row in rows)),
                    "event_id": event_id,
                    "field": "reported_status",
                }
            )
    note = {
        "schema_version": "healthcraft-reconciliation-note/v1",
        "patient_id": patient_id,
        "encounter_id": encounter_id,
        "observations": included,
        "unresolved_conflicts": conflicts,
        "scope_exclusions": excluded,
    }
    params = {
        "encounter_id": encounter_id,
        "notes": json.dumps(note, sort_keys=True, ensure_ascii=False, allow_nan=False),
        "idempotency_key": "synthetic-reconciliation-note-v1",
    }
    yield from _reference_call("updateEncounter", params)
    yield from _reference_call("updateEncounter", params)
    readback = yield from _reference_call("getEncounterDetails", {"encounter_id": encounter_id})
    if (
        readback.get("id") != encounter_id
        or readback.get("patient_id") != patient_id
        or readback.get("clinical_notes") != [["Progress Note", params["notes"]]]
    ):
        raise ValueError("Reference persisted note readback is missing, ambiguous or changed")
    return {"status": "terminated", "reason": "reference_readback_verified"}
