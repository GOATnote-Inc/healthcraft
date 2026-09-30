"""Shared pilot semantics must not depend on the execution arm or native tools."""

import importlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from healthcraft.reconciliation.fixture import load_scenario
from healthcraft.reconciliation.oracle import load_expectations, verify_reconciliation
from healthcraft.reconciliation.service import ReconciliationSession


@pytest.fixture
def api():
    return importlib.import_module("healthcraft.reconciliation.controller")


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setenv("HEALTHCRAFT_IDEMPOTENT_TOOLS", "1")
    session = ReconciliationSession(token="controller-test")
    yield session
    session.close()


def discovery(service):
    return service.handle("GET", "/tools", authorization="Bearer controller-test")[1]["tools"]


def dispatch(service, command):
    status, response = service.handle(
        "POST",
        "/call",
        json.dumps({"name": command["name"], "params": command["params"]}).encode(),
        "Bearer controller-test",
    )
    assert status == 200
    return response


def native(content='{"action":"finish"}', **changes):
    response = {
        "model": "local-test:latest",
        "done": True,
        "done_reason": "stop",
        "message": {"role": "assistant", "content": content},
        "prompt_eval_count": 15,
        "eval_count": 4,
    }
    response.update(changes)
    return response


def local_client(api, monkeypatch, envelopes, *, capabilities=None, events=None, settings=None):
    queue = iter(envelopes)
    requests = []
    metadata = {"digest": "sha256-fixture", "version": "0.34.4"}
    emitted = events if events is not None else []

    def transport(self, path, payload=None):
        if path == "/api/tags":
            return {"models": [{"name": "local-test:latest", "digest": metadata["digest"]}]}
        if path == "/api/show":
            return {
                "capabilities": capabilities or ["completion"],
                "details": {"family": "gemma3", "quantization_level": "Q5_K_M"},
            }
        if path == "/api/version":
            return {"version": metadata["version"]}
        assert path == "/api/chat"
        assert emitted[-1]["event"] == "model_dispatched"
        assert emitted[-1]["exchange"]["request"] == payload
        requests.append(deepcopy(payload))
        response = next(queue)
        if isinstance(response, BaseException):
            raise response
        return response

    monkeypatch.setattr(api.RecordingOllamaClient, "_transport_request", transport)
    client = api.RecordingOllamaClient(
        model="local-test:latest",
        expected_digest="sha256-fixture",
        expected_runtime="0.34.4",
        settings=settings or api.PilotSettings(),
        event_sink=emitted.append,
    )
    return client, requests, emitted, metadata


def test_defaults_are_explicit_bounded_and_not_benchmark_metrics(api):
    settings = api.PilotSettings()
    assert (settings.max_model_responses, settings.max_output_tokens, settings.num_ctx) == (
        16,
        4096,
        32768,
    )
    assert (settings.seed, settings.temperature, settings.think, settings.keep_alive) == (
        42,
        0,
        False,
        0,
    )
    assert (settings.request_timeout_seconds, settings.attempt_timeout_seconds) == (240, 900)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_model_responses", 0),
        ("max_output_tokens", -1),
        ("num_ctx", True),
        ("request_timeout_seconds", float("inf")),
        ("attempt_timeout_seconds", 0),
        ("temperature", float("nan")),
        ("think", 1),
        ("keep_alive", -1),
    ],
)
def test_invalid_settings_fail_before_any_request(api, field, value):
    with pytest.raises(ValueError):
        api.PilotSettings(**{field: value})


def test_same_initial_messages_and_feedback_across_arms(api, service, monkeypatch):
    tools = discovery(service)
    prompt = "Same public target instruction"
    command = '{"action":"call","name":"getPatientHistory","params":{"patient_id":"PAT-AAAAAAAA"}}'
    left, lr, _, _ = local_client(api, monkeypatch, [native(command), native()])
    a = api.CommandController(prompt, tools)
    first = a.next_command(left)
    result = dispatch(service, first)
    a.accept_result(result)
    assert a.next_command(left) == {"action": "finish"}
    # Second arm receives the same actual JSON values, with different wire spacing/order.
    right, rr, _, _ = local_client(api, monkeypatch, [native(command), native()])
    b = api.CommandController(prompt, list(reversed(tools)))
    b.next_command(right)
    b.accept_result(json.loads(json.dumps(result, indent=3)))
    b.next_command(right)
    assert lr == rr
    assert all("tools" not in request for request in lr)
    assert all("think" not in request for request in lr)  # MedGemma-like completion-only support.
    assert lr[0]["options"] == {"temperature": 0, "seed": 42, "num_ctx": 32768, "num_predict": 4096}
    assert lr[0]["keep_alive"] == 0
    snapshot = a.snapshot()
    assert snapshot["completion"] == {"status": "terminated", "reason": "model_finish"}
    assert snapshot["benchmark_score"] is None
    assert snapshot["benchmark_comparable"] is snapshot["grading_complete"] is False
    assert snapshot["clinical_criteria"] == snapshot["safety_criteria"] == 0
    assert len(snapshot["calls"]) == 1


def test_nano_thinking_is_explicitly_off_with_no_native_tools(api, service, monkeypatch):
    client, requests, _, _ = local_client(
        api, monkeypatch, [native()], capabilities=["completion", "tools", "thinking"]
    )
    api.CommandController("public", discovery(service)).next_command(client)
    assert requests[0]["think"] is False
    assert "tools" not in requests[0]


@pytest.mark.parametrize(
    "content",
    [
        '```json\n{"action":"finish"}\n```',
        '{"action":"finish"} trailing',
        '{"action":"finish","extra":1}',
        '{"action":"finish","action":"call"}',
        '{"action":"call","name":"updateEncounter","params":{"x":1e999}}',
        '{"action":"call","name":"createClinicalOrder","params":{}}',
        '{"action":"call","name":"getEncounterDetails","params":[]}',
        "[]",
    ],
)
def test_invalid_model_command_keeps_raw_and_never_dispatches_or_repairs(
    api, service, monkeypatch, content
):
    client, requests, events, _ = local_client(api, monkeypatch, [native(content)])
    controller = api.CommandController("public", discovery(service))
    with pytest.raises(ValueError):
        controller.next_command(client)
    assert len(requests) == 1
    assert controller.snapshot()["completion"]["status"] == "failed"
    assert controller.snapshot()["calls"] == []
    assert client.exchanges[0]["response"]["message"]["content"] == content
    assert events[-1]["event"] == "model_returned"
    with pytest.raises(RuntimeError):
        controller.next_command(client)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "patch",
    [
        {"done": False},
        {"done_reason": None},
        {"done_reason": "length"},
        {"done_reason": "content_filter"},
        {"model": "other:latest"},
        {"message": {"role": "user", "content": '{"action":"finish"}'}},
        {"message": {"role": "assistant", "content": '{"action":"finish"}', "thinking": "hidden"}},
        {"message": {"role": "assistant", "content": '{"action":"finish"}', "refusal": "blocked"}},
        {
            "message": {
                "role": "assistant",
                "content": '{"action":"finish"}',
                "tool_calls": [{"function": {"name": "getPatientHistory", "arguments": {}}}],
            }
        },
        {"eval_count": -1},
    ],
)
def test_raw_native_completion_faults_fail_before_command_extraction(
    api, service, monkeypatch, patch
):
    envelope = native(**patch)
    client, requests, _, _ = local_client(api, monkeypatch, [envelope])
    controller = api.CommandController("public", discovery(service))
    with pytest.raises((ValueError, RuntimeError)):
        controller.next_command(client)
    assert controller.snapshot()["completion"]["status"] == "failed"
    assert controller.snapshot()["calls"] == []
    assert client.exchanges[0]["response"] == envelope
    assert len(requests) == 1


def test_provider_exception_retains_dispatched_partial_exchange(api, service, monkeypatch):
    client, requests, events, _ = local_client(api, monkeypatch, [TimeoutError("bounded")])
    controller = api.CommandController("public", discovery(service))
    with pytest.raises(TimeoutError):
        controller.next_command(client)
    assert len(requests) == 1
    assert events[-1]["event"] == "model_failed"
    assert client.exchanges[0]["response"] is None
    assert controller.snapshot()["completion"]["status"] == "failed"


def test_model_identity_mismatch_blocks_inference_and_fresh_postflight_detects_drift(
    api, service, monkeypatch
):
    client, requests, _, identity = local_client(api, monkeypatch, [native()])
    client.preflight()
    identity["digest"] = "changed"
    with pytest.raises(ValueError):
        client.postflight()
    assert client.identity_after["model_digest"] == "changed"
    assert not requests
    client2, requests2, _, identity2 = local_client(api, monkeypatch, [native()])
    identity2["version"] = "different"
    with pytest.raises(ValueError):
        api.CommandController("public", discovery(service)).next_command(client2)
    assert not requests2


def test_pending_tool_result_and_turn_budget_are_enforced(api, service, monkeypatch):
    settings = replace(api.PilotSettings(), max_model_responses=1)
    command = '{"action":"call","name":"getPatientHistory","params":{"patient_id":"PAT-AAAAAAAA"}}'
    client, requests, _, _ = local_client(api, monkeypatch, [native(command)], settings=settings)
    controller = api.CommandController("public", discovery(service), settings=settings)
    call = controller.next_command(client)
    with pytest.raises(RuntimeError):
        controller.next_command(client)
    assert len(requests) == 1
    controller.accept_result(dispatch(service, call))
    with pytest.raises(RuntimeError):
        controller.next_command(client)
    assert controller.snapshot()["completion"]["reason"] == "model_response_limit"
    assert len(requests) == 1


def test_deadline_prevents_model_and_tool_work_after_expiry(api, service, monkeypatch):
    time = [0.0]
    client, requests, _, _ = local_client(api, monkeypatch, [native()])
    controller = api.CommandController("public", discovery(service), clock=lambda: time[0])
    time[0] = 901
    with pytest.raises(TimeoutError):
        controller.next_command(client)
    assert not requests
    assert controller.snapshot()["completion"]["reason"] == "attempt_deadline"


def test_snapshots_and_sink_events_cannot_rewrite_state(api, service, monkeypatch):
    tools = discovery(service)
    client, _, events, _ = local_client(api, monkeypatch, [native()])
    controller = api.CommandController("public", tools)
    tools[0]["name"] = "mutated"
    controller.next_command(client)
    snapshot = controller.snapshot()
    snapshot["messages"][0]["content"] = "mutated"
    events[0]["exchange"]["request"]["messages"][0]["content"] = "mutated"
    assert controller.snapshot()["messages"][0]["content"] != "mutated"
    assert client.exchanges[0]["request"]["messages"][0]["content"] != "mutated"


def test_reference_controller_uses_public_records_and_real_retry_readback(api, service):
    commands = api.reference_commands(discovery(service), target=load_scenario()["target"])
    command = next(commands)
    requests = []
    while True:
        requests.append(deepcopy(command))
        response = dispatch(service, command)
        try:
            command = commands.send(response)
        except StopIteration as final:
            assert final.value == {"status": "terminated", "reason": "reference_readback_verified"}
            break
    evidence = service.finalize("completed")
    assert verify_reconciliation(load_scenario(), load_expectations(), evidence)[
        "mechanical_passed"
    ]
    assert len(requests) == 10
    assert requests[-3] == requests[-2]
    assert requests[-1]["name"] == "getEncounterDetails"


def test_reference_derived_note_follows_changed_public_source_not_hidden_expectations(
    api, monkeypatch
):
    monkeypatch.setenv("HEALTHCRAFT_IDEMPOTENT_TOOLS", "1")
    scenario = load_scenario()
    scenario["encounters"][0]["patient_data"]["active_orders"][0]["item"] = "new-source-token"
    service = ReconciliationSession(scenario=scenario, token="controller-test")
    generator = api.reference_commands(discovery(service), target=scenario["target"])
    command = next(generator)
    while True:
        result = dispatch(service, command)
        try:
            command = generator.send(result)
        except StopIteration:
            break
    evidence = service.finalize("completed")
    note = json.loads(
        next(iter(evidence["after"]["entities"]["clinical_note"].values()))["content"]
    )
    assert note["observations"][0]["source"]["item"] == "new-source-token"


@pytest.mark.parametrize(
    "mutation", ["missing_note", "changed_note", "extra_note", "wrong_patient"]
)
def test_reference_requires_exact_single_note_readback(api, service, mutation):
    generator = api.reference_commands(discovery(service), target=load_scenario()["target"])
    command = next(generator)
    for index in range(10):
        result = dispatch(service, command)
        if index == 9:
            if mutation == "missing_note":
                result["data"]["clinical_notes"] = []
            elif mutation == "changed_note":
                result["data"]["clinical_notes"][0][1] = "wrong"
            elif mutation == "extra_note":
                result["data"]["clinical_notes"].append(["Progress Note", "extra"])
            else:
                result["data"]["patient_id"] = "PAT-BBBBBBBB"
            with pytest.raises(ValueError):
                generator.send(result)
        else:
            command = generator.send(result)


def test_reference_module_has_no_private_data_or_oracle_import(api):
    source = Path(api.__file__).read_text()
    assert "reconciliation.fixture" not in source
    assert "reconciliation.oracle" not in source
    assert "reconciliation.execution" not in source
    assert "SRC-A0" not in source
    assert "PAT-AAAAAAAA" not in source


def test_failed_identity_check_cannot_be_bypassed_by_reusing_client(api, monkeypatch):
    client, requests, _, metadata = local_client(api, monkeypatch, [native()])
    metadata["digest"] = "wrong"
    for _ in range(2):
        with pytest.raises(ValueError):
            client.chat([{"role": "user", "content": "public"}], tools=None)
    assert requests == []


def test_settings_mismatch_is_retained_as_failed_without_inference(api, service, monkeypatch):
    client, requests, _, _ = local_client(api, monkeypatch, [native()])
    controller = api.CommandController(
        "public", discovery(service), settings=replace(api.PilotSettings(), max_output_tokens=2048)
    )
    with pytest.raises(ValueError):
        controller.next_command(client)
    assert controller.snapshot()["completion"]["status"] == "failed"
    assert controller.snapshot()["completion"]["reason"] == "settings_mismatch"
    assert requests == []


def test_late_model_return_is_retained_but_command_never_dispatchable(api, service, monkeypatch):
    now = [0.0]
    client, requests, _, _ = local_client(
        api, monkeypatch, [native('{"action":"call","name":"getPatientHistory","params":{}}')]
    )
    original = client._transport_request

    def delayed(path, payload=None):
        response = original(path, payload)
        if path == "/api/chat":
            now[0] = 901
        return response

    monkeypatch.setattr(client, "_transport_request", delayed)
    controller = api.CommandController("public", discovery(service), clock=lambda: now[0])
    with pytest.raises(TimeoutError):
        controller.next_command(client)
    assert len(requests) == 1
    assert controller.snapshot()["calls"] == []
    assert client.exchanges[0]["response"]["done"] is True
    assert controller.snapshot()["completion"]["reason"] == "attempt_deadline"


def test_late_actual_tool_response_is_preserved_and_stops_followup(api, service, monkeypatch):
    now = [0.0]
    client, requests, _, _ = local_client(
        api,
        monkeypatch,
        [
            native(
                '{"action":"call","name":"getPatientHistory","params":{"patient_id":"PAT-AAAAAAAA"}}'
            )
        ],
    )
    controller = api.CommandController("public", discovery(service), clock=lambda: now[0])
    command = controller.next_command(client)
    response = dispatch(service, command)
    now[0] = 901
    with pytest.raises(TimeoutError):
        controller.accept_result(response)
    assert controller.snapshot()["calls"][0]["response"] == response
    assert controller.snapshot()["completion"]["reason"] == "attempt_deadline"
    assert len(requests) == 1


def test_tool_error_stops_without_repair_or_retry_and_preserves_receipt(api, service, monkeypatch):
    client, requests, _, _ = local_client(
        api,
        monkeypatch,
        [
            native(
                '{"action":"call","name":"getPatientHistory","params":{"patient_id":"PAT-AAAAAAAA"}}'
            )
        ],
    )
    controller = api.CommandController("public", discovery(service))
    controller.next_command(client)
    response = {"status": "error", "code": "test_failure", "data": {"unknown": None}}
    with pytest.raises(RuntimeError):
        controller.accept_result(response)
    assert controller.snapshot()["calls"][0]["response"] == response
    assert controller.snapshot()["completion"]["reason"] == "tool_error"
    with pytest.raises(RuntimeError):
        controller.next_command(client)
    assert len(requests) == 1


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "wrong_name", "wrong_schema"])
def test_public_tool_discovery_must_be_complete_and_unambiguous(api, service, mutation):
    tools = discovery(service)
    if mutation == "missing":
        tools.pop()
    elif mutation == "duplicate":
        tools[1] = deepcopy(tools[0])
    elif mutation == "wrong_name":
        tools[0]["name"] = "hiddenTool"
    else:
        tools[0]["parameters"] = []
    with pytest.raises(ValueError):
        api.CommandController("public", tools)
    with pytest.raises(ValueError):
        next(api.reference_commands(tools, target=load_scenario()["target"]))
