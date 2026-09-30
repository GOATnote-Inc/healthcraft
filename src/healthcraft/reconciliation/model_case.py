"""One public-only spawned model worker with a parent-owned native case world.

The worker receives no scenario or expectation documents. This is a process
and input boundary, not a hostile-code filesystem sandbox. Killing the worker
bounds its lifetime, not an already dispatched Ollama daemon request.
"""

from __future__ import annotations

import base64
import multiprocessing
import os
import pickle
import queue
import re
import threading
import time
from copy import deepcopy
from dataclasses import asdict, fields
from pathlib import Path

from healthcraft.reconciliation.controller import (
    PUBLIC_TOOLS,
    PilotSettings,
    canonical_json,
    validate_command_format,
)
from healthcraft.reconciliation.execution_v2 import _validated_case, run_case
from healthcraft.reconciliation.fixture import _json_copy
from healthcraft.reconciliation.terminal import _json_object


class WorkerProtocolError(RuntimeError):
    """The child did not establish a consistent completed worker attempt."""


def validate_model_config(config: dict) -> dict:
    """Validate exact public model/settings fields without I/O or model access."""
    value = _json_copy(config)
    required = {"model", "expected_digest", "expected_runtime", "settings", "command_format"}
    if type(value) is not dict or set(value) != required:
        raise ValueError("Model configuration requires exactly five public fields")
    for field in ("model", "expected_runtime"):
        text = value[field]
        if type(text) is not str or not text.strip() or text != text.strip():
            raise ValueError(f"Invalid {field}")
    if "cloud" in value["model"].lower():
        raise ValueError("Cloud model aliases are not allowed")
    if type(value["expected_digest"]) is not str or not re.fullmatch(
        r"[a-f0-9]{64}", value["expected_digest"]
    ):
        raise ValueError("Expected model digest must be lowercase SHA-256")
    if type(value["settings"]) is not dict or set(value["settings"]) != {
        f.name for f in fields(PilotSettings)
    }:
        raise ValueError("Every PilotSettings field must be explicitly supplied")
    value["settings"] = asdict(PilotSettings(**value["settings"]))
    value["command_format"] = validate_command_format(value["command_format"])
    return value


def _write(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical_json(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _append(path: Path, value: object) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(canonical_json(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _error(exc: BaseException) -> dict:
    return {"type": type(exc).__name__, "message": str(exc)}


def _receive_frames(connection, messages: queue.Queue) -> None:
    """Receive only; this thread never dispatches actions or changes evidence."""
    while True:
        try:
            raw = connection.recv_bytes(maxlength=64 * 1024 * 1024)
        except (EOFError, OSError) as exc:
            messages.put((False, exc))
            return
        messages.put((True, raw))


def _send_reply(connection, reply: dict, result: queue.Queue) -> None:
    """IPC only; a stalled child must not block the supervising thread."""
    try:
        connection.send(reply)
    except (EOFError, OSError) as exc:
        result.put(exc)
    else:
        result.put(None)


def _decode_frame(raw: bytes, journal: Path) -> object:
    # Connection.send already uses pickle for the trusted local worker. Retain
    # the actual frame before decoding, including malformed/non-JSON payloads.
    _append(journal, {"event": "worker_frame", "body_b64": base64.b64encode(raw).decode("ascii")})
    value = pickle.loads(raw)
    return _json_copy(value)


def _check_receipt(receipt: dict, public: dict, exitcode: int | None) -> None:
    if (
        type(receipt) is not dict
        or receipt.get("schema_version") != "healthcraft-reconciliation-model-worker/v1"
    ):
        raise WorkerProtocolError("Worker receipt schema is invalid")
    if receipt.get("status") == "interrupted":
        raise KeyboardInterrupt("Worker reported an interruption; see original worker receipt")
    if receipt.get("status") != "terminated" or exitcode != 0:
        raise WorkerProtocolError("Worker did not terminate normally")
    if receipt.get("error") is not None or receipt.get("postflight_error") is not None:
        raise WorkerProtocolError("Worker retained an execution or postflight error")
    if receipt.get("postflight_status") != "matched":
        raise WorkerProtocolError("Worker did not establish fresh matching postflight identity")
    if canonical_json(receipt.get("config")) != canonical_json(public):
        raise WorkerProtocolError("Worker public configuration differs from the frozen request")
    for field in ("identity_before", "identity_after"):
        identity = receipt.get(field)
        if type(identity) is not dict or (
            identity.get("model_digest"),
            identity.get("runtime_version"),
            identity.get("model"),
        ) != (public["expected_digest"], public["expected_runtime"], public["model"]):
            raise WorkerProtocolError("Worker model/runtime identity mismatch")
    for field in ("initial_messages_sha256_expected", "initial_messages_sha256_actual"):
        if receipt.get(field) != public["initial_messages_sha256"]:
            raise WorkerProtocolError("Worker initial prompt identity mismatch")
    controller = receipt.get("controller")
    if type(controller) is not dict or controller.get("completion") != {
        "status": "terminated",
        "reason": "model_finish",
    }:
        raise WorkerProtocolError("Worker controller has no explicit model finish")
    count = receipt.get("model_calls")
    exchanges = receipt.get("model_exchanges")
    if (
        type(count) is not int
        or not 1 <= count <= public["settings"]["max_model_responses"]
        or type(exchanges) is not list
        or len(exchanges) != count
        or type(controller.get("model_requests")) is not int
        or controller["model_requests"] != count
    ):
        raise WorkerProtocolError("Worker request accounting is inconsistent")


def _cleanup(process) -> dict:
    terminated = killed = False
    if process.pid is not None:
        if process.is_alive():
            terminated = True
            process.terminate()
        process.join(timeout=2)
        if process.is_alive():
            killed = True
            process.kill()
            process.join(timeout=2)
    return {
        "terminated": terminated,
        "killed": killed,
        "alive": process.is_alive(),
        "exitcode": process.exitcode,
    }


def _model_accounting(worker_receipt: dict | None, worker_dir: Path) -> tuple[int | None, str]:
    # The count is recorded native request attempts, never guaranteed inferences.
    path = worker_dir / "model.jsonl"
    if not path.is_file():
        return None, "unknown_missing_journal"
    try:
        events = [_json_object(line) for line in path.read_text(encoding="utf-8").splitlines()]
        count = sum(event.get("event") == "model_dispatched" for event in events)
    except (OSError, UnicodeError, ValueError):
        return None, "unknown_incomplete_journal"
    if worker_receipt is not None:
        declared = worker_receipt.get("model_calls")
        if type(declared) is not int or declared != count:
            return count, "recorded_dispatches_receipt_disagrees"
    return count, "recorded_native_request_attempts"


def run_model_case(
    case: dict,
    model_config: dict,
    output_dir: Path,
    *,
    worker_target=None,
) -> dict:
    """Supervise one spawned worker; preserve native writes on every failure.

    The hard deadline covers child startup, metadata, inference and IPC. Native
    handler execution remains synchronous in the parent; deadlines are checked
    before dispatch and again before responding. The parent never retries.
    """
    data = _validated_case(case)
    config = validate_model_config(model_config)
    from healthcraft.reconciliation.model_worker import worker_main
    from healthcraft.reconciliation.public_case import public_case_context

    context = public_case_context(data["scenario"]["target"])
    public = {
        **deepcopy(config),
        **{
            key: deepcopy(context[key])
            for key in ("instruction", "tools", "initial_messages_sha256")
        },
    }
    settings = PilotSettings(**config["settings"])
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    worker_dir = output / "worker"
    worker_dir.mkdir()
    _write(output / "case.json", data)
    _write(output / "model-config.json", config)
    _write(output / "public-context.json", context)
    journal = output / "parent.jsonl"
    journal.touch(exist_ok=False)
    state = {"worker_receipt": None, "worker_exitcode": None, "worker_cleanup": None, "error": None}

    def controller(recorder, *, target):
        process_context = multiprocessing.get_context("spawn")
        parent, child = process_context.Pipe(duplex=True)
        process = process_context.Process(
            target=worker_target or worker_main, args=(child, public, worker_dir)
        )
        deadline = time.monotonic() + settings.attempt_timeout_seconds
        messages = queue.Queue()
        reader = None
        senders = []
        next_id = 1
        finished = False
        try:
            _append(
                journal,
                {
                    "event": "worker_starting",
                    "start_method": "spawn",
                    "deadline_seconds": settings.attempt_timeout_seconds,
                },
            )
            process.start()
            child.close()
            reader = threading.Thread(target=_receive_frames, args=(parent, messages), daemon=True)
            reader.start()
            _append(journal, {"event": "worker_started", "pid": process.pid})
            while not finished:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Model worker exceeded the hard attempt deadline")
                try:
                    complete_frame, frame = messages.get(timeout=min(1.0, remaining))
                except queue.Empty:
                    if not process.is_alive():
                        raise WorkerProtocolError("Worker exited without a finished receipt")
                    continue
                if not complete_frame:
                    raise frame
                message = _decode_frame(frame, journal)
                if type(message) is not dict:
                    raise WorkerProtocolError("Worker message must be an object")
                if message.get("event") == "call":
                    if (
                        set(message) != {"event", "id", "name", "params"}
                        or type(message["id"]) is not int
                        or message["id"] != next_id
                        or next_id > settings.max_model_responses
                        or type(message["name"]) is not str
                        or message["name"] not in PUBLIC_TOOLS
                        or type(message["params"]) is not dict
                    ):
                        raise WorkerProtocolError(
                            "Malformed or out-of-sequence worker tool request"
                        )
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Deadline reached before native dispatch")
                    response = recorder.call(message["name"], message["params"])
                    reply = {"id": next_id, "response": response}
                    _append(journal, {"event": "native_response", "message": reply})
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            "Deadline reached after native dispatch; response retained"
                        )
                    sent = queue.Queue()
                    sender = threading.Thread(
                        target=_send_reply, args=(parent, reply, sent), daemon=True
                    )
                    senders.append(sender)
                    sender.start()
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError("Worker did not accept native reply before deadline")
                        try:
                            send_error = sent.get(timeout=min(1.0, remaining))
                        except queue.Empty:
                            continue
                        if send_error is not None:
                            raise send_error
                        break
                    next_id += 1
                elif (
                    message.get("event") == "finished"
                    and set(message) == {"event", "receipt"}
                    and type(message["receipt"]) is dict
                ):
                    state["worker_receipt"] = message["receipt"]
                    _write(output / "worker-receipt.json", message["receipt"])
                    finished = True
                else:
                    raise WorkerProtocolError("Unknown or malformed worker event")
            while process.is_alive():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Worker did not exit before the hard deadline")
                process.join(timeout=min(0.1, remaining))
            state["worker_exitcode"] = process.exitcode
            # Reaping the child closes its pipe, so the read-only receiver must
            # also finish. A partial frame cannot block the supervising thread.
            reader.join(timeout=min(1.0, max(0, deadline - time.monotonic())))
            if reader.is_alive():
                raise WorkerProtocolError("Worker pipe receiver did not close")
            while not messages.empty():
                complete_frame, frame = messages.get_nowait()
                if complete_frame:
                    _decode_frame(frame, journal)
                    raise WorkerProtocolError("Worker sent an event after its finished receipt")
                if not isinstance(frame, EOFError):
                    raise frame
            _check_receipt(state["worker_receipt"], public, process.exitcode)
            recorded_count, accounting = _model_accounting(state["worker_receipt"], worker_dir)
            if (
                accounting != "recorded_native_request_attempts"
                or recorded_count != state["worker_receipt"]["model_calls"]
            ):
                raise WorkerProtocolError(
                    "Worker success lacks consistent durable model dispatch evidence"
                )
        except (Exception, KeyboardInterrupt) as exc:
            state["error"] = _error(exc)
            _append(journal, {"event": "supervisor_failed", "error": state["error"]})
            raise
        finally:
            state["worker_cleanup"] = _cleanup(process)
            state["worker_exitcode"] = process.exitcode
            parent.close()
            child.close()
            if reader is not None:
                reader.join(timeout=1)
                state["worker_cleanup"]["receiver_alive"] = reader.is_alive()
            for sender in senders:
                sender.join(timeout=1)
            state["worker_cleanup"]["sender_alive"] = any(s.is_alive() for s in senders)
            _append(journal, {"event": "worker_cleanup", "cleanup": state["worker_cleanup"]})

    evidence = run_case(data, controller=controller, journal_path=output / "native-journal.jsonl")
    _write(output / "execution.json", evidence)
    status = {"completed": "completed", "interrupted": "interrupted"}.get(
        evidence["completion"]["status"], "failed"
    )
    count, accounting = _model_accounting(state["worker_receipt"], worker_dir)
    receipt = {
        "schema_version": "healthcraft-reconciliation-model-attempt/v2",
        "status": status,
        "model_calls": count,
        "model_call_accounting": accounting,
        "execution_path": "execution.json",
        "case_binding": evidence["case_binding"],
        "model_config": config,
        "public_context": {
            key: context[key]
            for key in (
                "initial_messages_sha256",
                "instruction_sha256",
                "tools_sha256",
                "command_format",
            )
        },
        "start_method": "spawn",
        **state,
        "benchmark_score": None,
        "benchmark_comparable": False,
        "grading_complete": False,
        "clinical_assessment": "unassessed",
        "limitations": [
            "Worker completion is not mechanical or clinical success.",
            "Request counts are recorded native dispatch attempts, "
            "not guaranteed server inferences.",
            "The supervised child deadline does not cancel "
            "an already dispatched Ollama daemon request.",
            "The public-only worker configuration is not a hostile-code filesystem sandbox.",
        ],
    }
    if status != "completed" and receipt["error"] is None:
        receipt["error"] = evidence["completion"].get("error")
    _write(output / "receipt.json", receipt)
    return receipt
