"""Public-context-only model loop for a separately supervised native case.

The parent owns the world, actual tool dispatch and hard process deadline. This
worker receives no scenario or expectations, and does not compute a verdict.
Its request counter counts captured native request attempts, not proof that an
inference ran. A local terminated receipt does not prove delivery to the parent.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict, fields
from pathlib import Path

from healthcraft.reconciliation.controller import (
    CommandController,
    PilotSettings,
    RecordingOllamaClient,
    canonical_json,
    validate_command_format,
)
from healthcraft.reconciliation.terminal import _json_object

_FIELDS = {
    "model",
    "expected_digest",
    "expected_runtime",
    "settings",
    "instruction",
    "tools",
    "initial_messages_sha256",
    "command_format",
}


def _copy(value):
    return _json_object(canonical_json({"value": value}))["value"]


def _error(exc):
    return {"type": type(exc).__name__, "message": str(exc)}


def _write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical_json(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _append(stream, event):
    stream.write(canonical_json(event) + "\n")
    stream.flush()
    os.fsync(stream.fileno())


def _configuration(value):
    value = _copy(value)
    if type(value) is not dict or set(value) != _FIELDS:
        raise ValueError("Worker requires exactly the public model/context configuration fields")
    for key in ("model", "expected_runtime", "instruction"):
        if type(value[key]) is not str or not value[key].strip():
            raise ValueError(f"{key} must be nonempty text")
    if value["model"] != value["model"].strip() or "cloud" in value["model"].lower():
        raise ValueError("Only a named installed local model is supported")
    for key in ("expected_digest", "initial_messages_sha256"):
        if type(value[key]) is not str or re.fullmatch(r"[0-9a-f]{64}", value[key]) is None:
            raise ValueError(f"{key} must be an explicit SHA256 identity")
    if type(value["settings"]) is not dict or set(value["settings"]) != {
        field.name for field in fields(PilotSettings)
    }:
        raise ValueError("Every PilotSettings field must be explicit")
    settings = PilotSettings(**value["settings"])
    value["settings"] = asdict(settings)
    value["command_format"] = validate_command_format(value["command_format"])
    return value, settings


def run_worker(
    connection,
    public_config: dict,
    output_dir: Path,
    *,
    client_factory=RecordingOllamaClient,
) -> dict:
    """Run once and durably report termination, failure or interruption.

    The caller creates an empty output directory. Existing files are refused
    before model access. Failed preparation still emits a receipt. The receipt
    is saved before its terminal pipe message; failed delivery gets a separate
    file and raises, so the parent must also require normal child termination.
    """
    output = Path(output_dir)
    if not output.is_dir() or output.is_symlink():
        raise ValueError("Worker output must be an existing ordinary empty directory")
    if any(output.iterdir()):
        raise FileExistsError("Worker output is not empty; choose a new worker directory")
    receipt = {
        "schema_version": "healthcraft-reconciliation-model-worker/v1",
        "status": "failed",
        "config": None,
        "controller": None,
        "model_exchanges": [],
        "model_calls": 0,
        "model_invocation_accounting": "recorded_native_request_attempts",
        "pipe_exchanges": [],
        "identity_before": None,
        "identity_after": None,
        "postflight_status": "not_attempted",
        "error": None,
        "postflight_error": None,
        "failure_stage": None,
        "initial_messages_sha256_expected": None,
        "initial_messages_sha256_actual": None,
        "benchmark_score": None,
        "benchmark_comparable": False,
        "grading_complete": False,
        "clinical_criteria": 0,
        "safety_criteria": 0,
    }
    client = controller = None
    stage = "configuration"
    with (
        (output / "model.jsonl").open("x", encoding="utf-8") as model_log,
        (output / "controller.jsonl").open("x", encoding="utf-8") as controller_log,
    ):
        try:
            config, settings = _configuration(public_config)
            receipt["config"] = config
            stage = "controller_setup"
            controller = CommandController(
                config["instruction"],
                config["tools"],
                settings=settings,
                command_format=config["command_format"],
                event_sink=lambda event: _append(controller_log, event),
            )
            stage = "prompt_identity"
            messages = controller.snapshot()["messages"]
            actual = hashlib.sha256(canonical_json(messages).encode("utf-8")).hexdigest()
            receipt["initial_messages_sha256_expected"] = config["initial_messages_sha256"]
            receipt["initial_messages_sha256_actual"] = actual
            _write(
                output / "initial-prompt.json",
                {
                    "expected_sha256": config["initial_messages_sha256"],
                    "actual_sha256": actual,
                    "messages": messages,
                },
            )
            if actual != config["initial_messages_sha256"]:
                raise ValueError("Actual initial messages differ from frozen prompt identity")
            stage = "client_setup"
            client = client_factory(
                model=config["model"],
                expected_digest=config["expected_digest"],
                expected_runtime=config["expected_runtime"],
                settings=settings,
                command_format=config["command_format"],
                event_sink=lambda event: _append(model_log, event),
            )
            stage = "preflight"
            try:
                client.preflight()
            finally:
                receipt["identity_before"] = _copy(client.identity_before)
                _write(output / "identity-before.json", receipt["identity_before"])
            sequence = 0
            while True:
                stage = "inference"
                command = controller.next_command(client)
                if command == {"action": "finish"}:
                    if controller.snapshot()["completion"] != {
                        "status": "terminated",
                        "reason": "model_finish",
                    }:
                        raise ValueError("Finish command lacks explicit controller termination")
                    receipt["status"] = "terminated"
                    break
                sequence += 1
                request = {
                    "event": "call",
                    "id": sequence,
                    "name": command["name"],
                    "params": command["params"],
                }
                exchange = {"request": _copy(request), "response": None, "error": None}
                receipt["pipe_exchanges"].append(exchange)
                stage = "tool_dispatch"
                connection.send(_copy(request))
                stage = "tool_response"
                response = _copy(connection.recv())
                exchange["response"] = response
                if (
                    type(response) is not dict
                    or set(response) != {"id", "response"}
                    or type(response["id"]) is not int
                    or response["id"] != sequence
                    or type(response["response"]) is not dict
                ):
                    raise ValueError("Parent tool response does not match the outstanding call")
                controller.accept_result(response["response"])
        except (Exception, KeyboardInterrupt) as exc:
            receipt["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
            receipt["error"] = _error(exc)
            receipt["failure_stage"] = stage
            if receipt["pipe_exchanges"] and stage in {"tool_dispatch", "tool_response"}:
                receipt["pipe_exchanges"][-1]["error"] = _error(exc)
            if (
                controller is not None
                and controller.snapshot()["completion"]["status"] == "running"
            ):
                try:
                    controller.fail(exc, reason=stage)
                except (Exception, KeyboardInterrupt) as capture_error:
                    receipt["controller_capture_error"] = _error(capture_error)
        finally:
            if client is not None:
                try:
                    client.postflight()
                    receipt["postflight_status"] = "matched"
                except (Exception, KeyboardInterrupt) as exc:
                    receipt["postflight_status"] = "failed"
                    receipt["postflight_error"] = _error(exc)
                    if receipt["error"] is None:
                        receipt["error"] = _error(exc)
                        receipt["failure_stage"] = "postflight"
                    if receipt["status"] != "interrupted":
                        receipt["status"] = (
                            "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
                        )
                receipt["identity_before"] = _copy(client.identity_before)
                receipt["identity_after"] = _copy(client.identity_after)
                receipt["model_exchanges"] = _copy(client.exchanges)
                receipt["model_calls"] = len(receipt["model_exchanges"])
            receipt["controller"] = controller.snapshot() if controller is not None else None
            if not (output / "identity-before.json").exists():
                _write(output / "identity-before.json", receipt["identity_before"])
            _write(output / "identity-after.json", receipt["identity_after"])
    _write(output / "worker-receipt.json", receipt)
    try:
        connection.send({"event": "finished", "receipt": _copy(receipt)})
    except (Exception, KeyboardInterrupt) as exc:
        _write(output / "delivery-error.json", _error(exc))
        raise
    return _copy(receipt)


def worker_main(connection, public_config: dict, output_dir: Path) -> None:
    """Spawn-safe production entry; the parent also checks the process exit."""
    run_worker(connection, public_config, output_dir)
