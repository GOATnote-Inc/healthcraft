"""A native model worker must preserve failure rather than return false completion."""

from __future__ import annotations

import hashlib
import importlib
import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest

from healthcraft.reconciliation.controller import (
    PUBLIC_TOOLS,
    CommandController,
    PilotSettings,
    RecordingOllamaClient,
    canonical_json,
    command_format_identity,
)

ROOT = Path(__file__).resolve().parents[2]


def api():
    return importlib.import_module("healthcraft.reconciliation.model_worker")


def configuration(**settings):
    tools = [
        row
        for row in json.loads((ROOT / "configs/mcp-tools.json").read_text())["tools"]
        if row["name"] in PUBLIC_TOOLS
    ]
    options = PilotSettings(**settings)
    instruction = "Read the exact synthetic target records; write and read back the requested note."
    control = CommandController(
        instruction, tools, settings=options, command_format=command_format_identity()
    )
    return {
        "model": "test:latest",
        "expected_digest": "a" * 64,
        "expected_runtime": "0.34.4",
        "settings": asdict(options),
        "instruction": instruction,
        "tools": tools,
        "initial_messages_sha256": hashlib.sha256(
            canonical_json(control.snapshot()["messages"]).encode()
        ).hexdigest(),
        "command_format": command_format_identity(),
    }


def envelope(content='{"action":"finish"}', **changes):
    return {
        "model": "test:latest",
        "done": True,
        "done_reason": "stop",
        "message": {"role": "assistant", "content": content},
        "eval_count": 8,
        "prompt_eval_count": 32,
        **changes,
    }


def call_command(name="getPatientHistory", params=None):
    return canonical_json(
        {"action": "call", "name": name, "params": params or {"patient_id": "PAT-AAAAAAAA"}}
    )


class Pipe:
    def __init__(self, replies=(), *, fail_finished=False):
        self.replies = iter(replies)
        self.sent = []
        self.fail_finished = fail_finished

    def send(self, message):
        if message["event"] == "finished" and self.fail_finished:
            raise BrokenPipeError("parent closed during final receipt")
        self.sent.append(deepcopy(message))

    def recv(self):
        reply = next(self.replies)
        if isinstance(reply, BaseException):
            raise reply
        if callable(reply):
            return reply(self.sent[-1])
        return deepcopy(reply)


def client_factory(envelopes, output, *, postflight_error=None, preflight_error=None):
    queue, clients = iter(envelopes), []

    class ScriptedNative(RecordingOllamaClient):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.dispatches = []
            clients.append(self)

        def _transport_request(self, path, payload=None):
            if path == "/api/tags":
                if preflight_error:
                    raise preflight_error
                return {"models": [{"name": "test:latest", "digest": "a" * 64}]}
            if path == "/api/show":
                return {"capabilities": ["completion"], "details": {}}
            if path == "/api/version":
                return {"version": "0.34.4"}
            assert path == "/api/chat"
            # The exact configured native request is durable BEFORE transport.
            last = json.loads((output / "model.jsonl").read_text().splitlines()[-1])
            assert last["event"] == "model_dispatched"
            assert last["exchange"]["request"] == payload
            self.dispatches.append(deepcopy(payload))
            response = next(queue)
            if isinstance(response, BaseException):
                raise response
            return deepcopy(response)

        def postflight(self):
            if postflight_error:
                raise postflight_error
            return super().postflight()

    return ScriptedNative, clients


def invoke(tmp_path, envelopes, replies=(), *, config=None, **factory_options):
    output = tmp_path / "worker"
    output.mkdir()
    pipe = Pipe(replies)
    factory, clients = client_factory(envelopes, output, **factory_options)
    result = api().run_worker(pipe, config or configuration(), output, client_factory=factory)
    return result, pipe, clients, output


def test_real_controller_success_has_exact_format_bound_prompt_and_durable_receipts(tmp_path):
    result, pipe, clients, output = invoke(
        tmp_path,
        [envelope(call_command()), envelope()],
        [{"id": 1, "response": {"status": "ok", "data": {"id": "PAT-AAAAAAAA"}}}],
    )
    assert result["status"] == "terminated"
    assert result["controller"]["completion"] == {"status": "terminated", "reason": "model_finish"}
    assert result["postflight_status"] == "matched"
    assert result["model_calls"] == len(result["model_exchanges"]) == 2
    assert result["model_invocation_accounting"] == "recorded_native_request_attempts"
    assert len(clients[0].dispatches) == 2
    assert pipe.sent[0] == {
        "event": "call",
        "id": 1,
        "name": "getPatientHistory",
        "params": {"patient_id": "PAT-AAAAAAAA"},
    }
    assert pipe.sent[-1] == {"event": "finished", "receipt": result}
    assert result == json.loads((output / "worker-receipt.json").read_text())
    prompt = json.loads((output / "initial-prompt.json").read_text())
    assert (
        prompt["expected_sha256"]
        == prompt["actual_sha256"]
        == configuration()["initial_messages_sha256"]
    )
    assert result["identity_before"] == json.loads((output / "identity-before.json").read_text())
    assert result["identity_after"] == json.loads((output / "identity-after.json").read_text())
    assert result["benchmark_score"] is None
    assert result["grading_complete"] is result["benchmark_comparable"] is False
    for request in clients[0].dispatches:
        assert "tools" not in request
        assert "format" in request


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "missing",
        "settings_missing",
        "bool_count",
        "bad_digest",
        "bad_prompt",
        "bad_format",
        "none_format",
        "tools_missing",
        "instruction_empty",
    ],
)
def test_invalid_config_or_prompt_identity_fails_before_client_access(tmp_path, mutation):
    config = configuration()
    if mutation == "extra":
        config["scenario"] = {"private": "must not enter child"}
    elif mutation == "missing":
        del config["model"]
    elif mutation == "settings_missing":
        del config["settings"]["seed"]
    elif mutation == "bool_count":
        config["settings"]["max_model_responses"] = True
    elif mutation == "bad_digest":
        config["expected_digest"] = "wrong"
    elif mutation == "bad_prompt":
        config["initial_messages_sha256"] = "0" * 64
    elif mutation == "bad_format":
        config["command_format"]["sha256"] = "0" * 64
    elif mutation == "none_format":
        config["command_format"] = None
    elif mutation == "tools_missing":
        config["tools"].pop()
    else:
        config["instruction"] = " "
    result, pipe, clients, output = invoke(tmp_path, [], config=config)
    assert result["status"] == "failed"
    assert result["error"]["type"] == "ValueError"
    assert result["model_calls"] == 0 and clients == []
    assert all(item["event"] != "call" for item in pipe.sent)
    assert result == json.loads((output / "worker-receipt.json").read_text())


@pytest.mark.parametrize(
    "response",
    [
        envelope("```json\n{}\n```"),
        envelope(done_reason="length"),
        envelope(done_reason=None),
        envelope(
            message={"role": "assistant", "content": '{"action":"finish"}', "refusal": "blocked"}
        ),
    ],
)
def test_raw_response_failure_retains_exact_envelope_and_never_dispatches(tmp_path, response):
    result, pipe, clients, output = invoke(tmp_path, [response])
    assert result["status"] == "failed"
    assert result["model_exchanges"][0]["response"] == response
    assert result["controller"]["completion"]["status"] == "failed"
    assert result["model_calls"] == 1 and len(clients[0].dispatches) == 1
    assert [m["event"] for m in pipe.sent] == ["finished"]


@pytest.mark.parametrize(
    "error,status",
    [
        (TimeoutError("native socket timeout"), "failed"),
        (KeyboardInterrupt("interrupted request"), "interrupted"),
    ],
)
def test_transport_error_and_interruption_keep_original_errors(tmp_path, error, status):
    result, pipe, _, _ = invoke(tmp_path, [error])
    assert result["status"] == status
    assert result["error"] == {"type": type(error).__name__, "message": str(error)}
    assert result["model_exchanges"][0]["error"] == result["error"]
    assert pipe.sent[-1]["receipt"]["status"] == status


def test_response_limit_is_failed_after_preserving_completed_tool_roundtrip(tmp_path):
    config = configuration(max_model_responses=1)
    result, pipe, clients, _ = invoke(
        tmp_path,
        [envelope(call_command())],
        [{"id": 1, "response": {"status": "ok", "data": {}}}],
        config=config,
    )
    assert result["status"] == "failed"
    assert result["controller"]["completion"]["reason"] == "model_response_limit"
    assert result["controller"]["calls"][0]["response"]["status"] == "ok"
    assert result["model_calls"] == len(clients[0].dispatches) == 1
    assert len(pipe.sent) == 2


@pytest.mark.parametrize(
    "reply",
    [
        {"id": 2, "response": {"status": "ok"}},
        {"id": True, "response": {"status": "ok"}},
        {"id": 1, "response": []},
        {"id": 1, "response": {"status": "ok"}, "extra": True},
        {"response": {"status": "ok"}},
        EOFError("parent unavailable"),
    ],
)
def test_malformed_or_missing_parent_reply_cannot_finish_or_retry(tmp_path, reply):
    result, pipe, clients, _ = invoke(tmp_path, [envelope(call_command())], [reply])
    assert result["status"] == "failed" and result["failure_stage"] == "tool_response"
    assert result["model_calls"] == len(clients[0].dispatches) == 1
    assert result["controller"]["calls"][0]["response"] is None
    assert pipe.sent[-1]["receipt"]["status"] == "failed"


def test_actual_invalid_parameter_response_retains_native_audit_and_stops(tmp_path):
    from healthcraft.mcp.server import create_server
    from healthcraft.reconciliation.casebook import load_cases
    from healthcraft.reconciliation.execution import ReconciliationRecorder
    from healthcraft.reconciliation.fixture_v2 import build_world

    world = build_world(load_cases()[0]["scenario"])
    recorder = ReconciliationRecorder(create_server(world), world)

    def reply(request):
        assert request == {
            "event": "call",
            "id": 1,
            "name": "getEncounterDetails",
            "params": {"encounter_id": "wrong"},
        }
        return {"id": request["id"], "response": recorder.call(request["name"], request["params"])}

    result, _, clients, _ = invoke(
        tmp_path,
        [envelope(call_command("getEncounterDetails", {"encounter_id": "wrong"}))],
        [reply],
    )
    assert result["status"] == "failed"
    assert result["controller"]["calls"][0]["response"]["status"] == "error"
    assert len(world.audit_log) == len(recorder.calls) == len(clients[0].dispatches) == 1


def test_postflight_failure_cannot_upgrade_model_finish_to_success(tmp_path):
    result, pipe, _, _ = invoke(
        tmp_path, [envelope()], postflight_error=RuntimeError("identity changed")
    )
    assert result["status"] == "failed" and result["postflight_status"] == "failed"
    assert result["postflight_error"] == {"type": "RuntimeError", "message": "identity changed"}
    assert result["controller"]["completion"] == {"status": "terminated", "reason": "model_finish"}
    assert pipe.sent[-1]["receipt"]["status"] == "failed"


def test_original_failure_survives_secondary_postflight_error(tmp_path):
    result, _, _, _ = invoke(
        tmp_path, [TimeoutError("first error")], postflight_error=RuntimeError("second error")
    )
    assert result["error"]["message"] == "first error"
    assert result["postflight_error"]["message"] == "second error"


def test_preflight_error_preserved_without_inference(tmp_path):
    result, _, clients, _ = invoke(tmp_path, [], preflight_error=RuntimeError("missing model"))
    assert result["status"] == "failed" and result["failure_stage"] == "preflight"
    assert result["error"]["message"] == "missing model"
    assert result["model_calls"] == 0 and clients[0].dispatches == []


def test_existing_output_files_not_overwritten_or_mixed(tmp_path):
    output = tmp_path / "worker"
    output.mkdir()
    (output / "model.jsonl").write_bytes(b"prior")
    pipe = Pipe()
    accessed = []
    with pytest.raises(FileExistsError):
        api().run_worker(
            pipe, configuration(), output, client_factory=lambda **kwargs: accessed.append(kwargs)
        )
    assert (output / "model.jsonl").read_bytes() == b"prior" and accessed == [] and pipe.sent == []
    assert list(output.iterdir()) == [output / "model.jsonl"]


def test_final_pipe_failure_preserves_local_receipt_and_separate_delivery_error(tmp_path):
    output = tmp_path / "worker"
    output.mkdir()
    pipe = Pipe(fail_finished=True)
    factory, _ = client_factory([envelope()], output)
    with pytest.raises(BrokenPipeError):
        api().run_worker(pipe, configuration(), output, client_factory=factory)
    assert json.loads((output / "worker-receipt.json").read_text())["status"] == "terminated"
    assert json.loads((output / "delivery-error.json").read_text())["type"] == "BrokenPipeError"


def test_late_native_response_retained_but_not_dispatched_after_attempt_deadline(
    tmp_path, monkeypatch
):
    module = api()
    clock = [0.0]
    original_controller = module.CommandController

    def controller(*args, **kwargs):
        return original_controller(*args, **kwargs, clock=lambda: clock[0])

    monkeypatch.setattr(module, "CommandController", controller)
    output = tmp_path / "worker"
    output.mkdir()
    factory, clients = client_factory([envelope(call_command())], output)
    original_transport = factory._transport_request

    def delayed(self, path, payload=None):
        response = original_transport(self, path, payload)
        if path == "/api/chat":
            clock[0] = 2.0
        return response

    monkeypatch.setattr(factory, "_transport_request", delayed)
    pipe = Pipe()
    result = module.run_worker(
        pipe, configuration(attempt_timeout_seconds=1), output, client_factory=factory
    )
    assert result["status"] == "failed"
    assert result["error"]["type"] == "TimeoutError"
    assert result["controller"]["completion"]["reason"] == "attempt_deadline"
    assert result["model_exchanges"][0]["response"] == envelope(call_command())
    assert [row["event"] for row in pipe.sent] == ["finished"]
    assert len(clients[0].dispatches) == 1


def test_model_journal_failure_before_transport_is_not_counted_as_confirmed_inference(
    tmp_path, monkeypatch
):
    module = api()
    append = module._append

    def fail_dispatch(stream, event):
        if event["event"] == "model_dispatched":
            raise OSError("durable model journal unavailable")
        append(stream, event)

    monkeypatch.setattr(module, "_append", fail_dispatch)
    result, pipe, clients, output = invoke(tmp_path, [envelope()])
    assert result["status"] == "failed" and result["error"]["type"] == "OSError"
    assert result["model_calls"] == 1  # Captured request intent, not proof of inference.
    assert result["model_invocation_accounting"] == "recorded_native_request_attempts"
    assert clients[0].dispatches == [] and (output / "model.jsonl").read_bytes() == b""
    assert pipe.sent[-1]["receipt"]["status"] == "failed"


def test_two_native_tool_requests_are_uniquely_sequenced_and_returned_data_is_detached(tmp_path):
    config = configuration()
    original = deepcopy(config)
    responses = [
        {"id": 1, "response": {"status": "ok", "data": {"records": [1]}}},
        {"id": 2, "response": {"status": "ok", "data": {"records": [2]}}},
    ]
    result, pipe, clients, output = invoke(
        tmp_path,
        [envelope(call_command()), envelope(call_command()), envelope()],
        responses,
        config=config,
    )
    assert result["status"] == "terminated"
    assert [row["id"] for row in pipe.sent if row["event"] == "call"] == [1, 2]
    assert config == original
    stored = (output / "worker-receipt.json").read_bytes()
    result["config"]["tools"].clear()
    result["controller"]["calls"][0]["response"]["data"]["records"].clear()
    assert config == original and responses[0]["response"]["data"]["records"] == [1]
    assert clients[0].dispatches[0]["messages"]
    assert (output / "worker-receipt.json").read_bytes() == stored


def test_parent_pipe_interruption_keeps_successful_request_and_interrupted_status(tmp_path):
    result, pipe, clients, _ = invoke(
        tmp_path, [envelope(call_command())], [KeyboardInterrupt("interrupted while awaiting tool")]
    )
    assert result["status"] == "interrupted"
    assert result["failure_stage"] == "tool_response"
    assert result["pipe_exchanges"][0]["request"]["id"] == 1
    assert result["pipe_exchanges"][0]["error"]["type"] == "KeyboardInterrupt"
    assert result["controller"]["calls"][0]["response"] is None
    assert len(clients[0].dispatches) == 1 and len(pipe.sent) == 2
