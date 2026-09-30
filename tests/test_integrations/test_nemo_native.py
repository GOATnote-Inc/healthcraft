"""Offline native wire parity and fail-closed optional Gym conversion."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from healthcraft.integrations.nemo_native import NativeOllamaBridge
from healthcraft.llm.local_models import LocalModelError, OllamaClient

MODEL = "nano:latest"
DIGEST = "sha256:fixture"
TOOL = {
    "type": "function",
    "name": "getEncounterDetails",
    "description": "Read one encounter",
    "parameters": {
        "type": "object",
        "properties": {"encounter_id": {"type": "string"}},
        "required": ["encounter_id"],
    },
}


@pytest.fixture
def transport(monkeypatch):
    calls = []
    state = {
        "response": {
            "model": MODEL,
            "message": {"role": "assistant", "content": "Read all four."},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 35,
            "eval_count": 6,
        }
    }

    def request(self, path, payload=None):
        calls.append((path, deepcopy(payload)))
        if path == "/api/tags":
            return {"models": [{"name": MODEL, "digest": state.get("digest", DIGEST)}]}
        if path == "/api/show":
            return {"capabilities": ["completion", "tools", "thinking"], "details": {}}
        if path == "/api/version":
            return {"version": "0.34.4"}
        if "error" in state:
            raise LocalModelError(state["error"])
        return deepcopy(state["response"])

    monkeypatch.setattr(OllamaClient, "_request", request)
    return calls, state


def bridge(tmp_path, **kwargs):
    return NativeOllamaBridge(
        model=MODEL, expected_digest=DIGEST, capture_dir=tmp_path, output_budget=512, **kwargs
    )


def test_exact_wire_parity_with_healthcraft_native_client(tmp_path, transport):
    calls, _ = transport
    request = {
        "instructions": "Use the records.",
        "input": [
            {"role": "user", "content": "Read the encounter."},
            {
                "type": "function_call",
                "call_id": "prior",
                "name": "getEncounterDetails",
                "arguments": '{"encounter_id":"ENC-1"}',
            },
            {"type": "function_call_output", "call_id": "prior", "output": '{"status":"ok"}'},
        ],
        "tools": [TOOL],
        "max_output_tokens": 512,
        "temperature": 0,
    }
    response = bridge(tmp_path).responses(request)
    actual = next(payload for path, payload in calls if path == "/api/chat")
    OllamaClient(MODEL, seed=42, num_ctx=32768, think=False).chat(
        [
            {"role": "system", "content": "Use the records."},
            {"role": "user", "content": "Read the encounter."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "prior",
                        "name": "getEncounterDetails",
                        "arguments": {"encounter_id": "ENC-1"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "prior", "content": '{"status":"ok"}'},
        ],
        tools=[{k: v for k, v in TOOL.items() if k != "type"}],
        max_tokens=512,
    )
    assert calls[-1] == ("/api/chat", actual)
    assert actual["options"] == {
        "temperature": 0.0,
        "seed": 42,
        "num_ctx": 32768,
        "num_predict": 512,
    }
    assert actual["think"] is False and actual["stream"] is False
    assert "top_p" not in actual["options"]
    assert response["status"] == "completed"
    assert response["usage"]["total_tokens"] == 41
    assert response["usage"]["output_tokens_details"]["reasoning_tokens"] is None
    files = list(tmp_path.glob("*/transport-*.json"))
    assert len(files) == 4
    event = [
        json.loads(path.read_text())
        for path in files
        if json.loads(path.read_text())["path"] == "/api/chat"
    ][0]
    assert event["request"] == actual
    assert event["response"]["prompt_eval_count"] == 35
    assert "token_ids" not in json.dumps(response)


@pytest.mark.parametrize(
    "option",
    [
        {"top_p": 1.0},
        {"temperature": 0.5},
        {"max_output_tokens": 0},
        {"max_output_tokens": 513},
        {"stream": True},
        {"parallel_tool_calls": False},
        {"tool_choice": "required"},
        {"reasoning": {"effort": "low"}},
        {"previous_response_id": "prior"},
        {"extra_body": {"options": {"num_ctx": 1}}},
        {"metadata": {"extra_body": {"think": True}}},
        {"model": "other"},
    ],
)
def test_unsupported_or_mismatched_options_fail_before_network(tmp_path, transport, option):
    calls, _ = transport
    with pytest.raises(ValueError):
        bridge(tmp_path).responses({"input": "Read records", **option})
    assert not calls


@pytest.mark.parametrize(
    "items",
    [
        [
            {
                "role": "user",
                "content": [{"type": "input_image", "image_url": "https://example.test"}],
            }
        ],
        [{"type": "function_call_output", "call_id": "missing", "output": "result"}],
        [
            {
                "type": "function_call",
                "call_id": "x",
                "name": "getEncounterDetails",
                "arguments": "{}",
            }
        ],
        [{"role": "assistant", "content": "partial", "status": "incomplete"}],
        [{"type": "reasoning", "summary": [{"type": "summary_text", "text": "secret"}]}],
    ],
)
def test_unsupported_or_unanswered_history_is_not_silently_dropped(tmp_path, transport, items):
    calls, _ = transport
    with pytest.raises(ValueError):
        bridge(tmp_path).responses({"input": items})
    assert not calls


def test_native_tool_calls_round_trip_ids_and_preserve_argument_types(tmp_path, transport):
    calls, state = transport
    state["response"]["message"] = {
        "role": "assistant",
        "content": "Opening it.",
        "tool_calls": [
            {
                "function": {
                    "name": "getEncounterDetails",
                    "arguments": {"encounter_id": "ENC-1", "n": 4},
                }
            }
        ],
    }
    client = bridge(tmp_path)
    first = client.responses({"input": "Read", "tools": [TOOL]})
    tool = next(item for item in first["output"] if item["type"] == "function_call")
    assert tool["status"] == "completed"
    second = client.responses(
        {
            "input": [
                {"role": "user", "content": "Read"},
                *first["output"],
                {"type": "function_call_output", "call_id": tool["call_id"], "output": "ok"},
            ],
            "tools": [TOOL],
        }
    )
    native = [payload for path, payload in calls if path == "/api/chat"][-1]
    assert native["messages"][-2] == {
        "role": "assistant",
        "content": "Opening it.",
        "tool_calls": [
            {
                "function": {
                    "name": "getEncounterDetails",
                    "arguments": {"encounter_id": "ENC-1", "n": 4},
                }
            }
        ],
    }
    assert native["messages"][-1]["tool_name"] == "getEncounterDetails"
    assert (
        next(i for i in second["output"] if i["type"] == "function_call")["call_id"]
        != tool["call_id"]
    )


def test_length_retains_partial_calls_but_marks_them_incomplete(tmp_path, transport):
    _, state = transport
    state["response"]["done_reason"] = "length"
    state["response"]["message"]["tool_calls"] = [
        {"function": {"name": TOOL["name"], "arguments": {}}}
    ]
    response = bridge(tmp_path).responses({"input": "Read", "tools": [TOOL]})
    assert response["status"] == "incomplete"
    assert response["incomplete_details"] == {"reason": "max_output_tokens"}
    assert all(item["status"] == "incomplete" for item in response["output"])


@pytest.mark.parametrize(
    "mutation",
    [
        {"done": False},
        {"done_reason": None},
        {"done_reason": "unknown"},
        {"message": {"role": "assistant", "content": "", "refusal": "blocked"}},
        {"message": {"role": "assistant", "content": "", "thinking": "unexpected"}},
        {"prompt_eval_count": -1},
        {"model": "other"},
    ],
)
def test_unknown_completion_and_contradictions_fail_with_preserved_raw(
    tmp_path, transport, mutation
):
    _, state = transport
    state["response"].update(mutation)
    with pytest.raises((ValueError, LocalModelError)):
        bridge(tmp_path).responses({"input": "Read"})
    assert len(list(tmp_path.glob("*/error.json"))) == 1
    assert any(
        json.loads(path.read_text()).get("response") == state["response"]
        for path in tmp_path.glob("*/transport-*.json")
    )


def test_blank_final_is_complete_and_missing_usage_stays_unknown(tmp_path, transport):
    _, state = transport
    state["response"]["message"]["content"] = ""
    state["response"].pop("prompt_eval_count")
    response = bridge(tmp_path).responses({"input": "Read"})
    assert response["status"] == "completed"
    assert response["output"][0]["content"][0]["text"] == ""
    assert response["usage"] is None


def test_digest_change_blocks_generation_and_preserves_failure(tmp_path, transport):
    calls, state = transport
    state["digest"] = "changed"
    with pytest.raises(LocalModelError, match="digest"):
        bridge(tmp_path).responses({"input": "Read"})
    assert not any(path == "/api/chat" for path, _ in calls)
    assert len(list(tmp_path.glob("*/error.json"))) == 1


def test_provider_error_is_recorded_and_each_attempt_gets_exclusive_files(tmp_path, transport):
    _, state = transport
    state["error"] = "local runtime failed"
    client = bridge(tmp_path)
    for _ in range(2):
        with pytest.raises(LocalModelError):
            client.responses({"input": "Read"})
    assert len(list(tmp_path.iterdir())) == 2
    assert len(list(tmp_path.glob("*/request.json"))) == 2
    assert len(list(tmp_path.glob("*/error.json"))) == 2


def test_chat_and_responses_requests_have_identical_native_wire(tmp_path, transport):
    calls, _ = transport
    client = bridge(tmp_path)
    client.responses({"input": "Read", "instructions": "Use tools", "tools": [TOOL]})
    result = client.chat_completions(
        {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "Use tools"},
                {"role": "user", "content": "Read"},
            ],
            "tools": [
                {"type": "function", "function": {k: v for k, v in TOOL.items() if k != "type"}}
            ],
            "seed": 42,
            "reasoning_effort": "none",
            "max_tokens": 512,
        }
    )
    native = [payload for path, payload in calls if path == "/api/chat"]
    assert native[0] == native[1]
    assert result["choices"][0]["finish_reason"] == "stop"


def test_pinned_gym_types_and_component_without_inference(tmp_path, transport):
    pytest.importorskip("nemo_gym")
    from nemo_gym.openai_utils import NeMoGymResponse, NeMoGymResponseCreateParamsNonStreaming
    from nemo_gym.server_utils import ServerClient

    from integrations.nemo_gym.native_ollama import NativeOllamaModel, NativeOllamaModelConfig

    server = NativeOllamaModel(
        config=NativeOllamaModelConfig(
            name="native",
            host="127.0.0.1",
            port=8081,
            entrypoint="",
            model=MODEL,
            expected_digest=DIGEST,
            capture_dir=str(tmp_path),
            output_budget=512,
        ),
        server_client=MagicMock(spec=ServerClient),
    )
    result = asyncio.run(server.responses(NeMoGymResponseCreateParamsNonStreaming(input="Read")))
    assert isinstance(result, NeMoGymResponse)
    assert result.status == "completed"
    assert result.usage.input_tokens == 35
    assert len(list(Path(tmp_path).glob("*/response.json"))) == 1


def test_pending_duplicate_ids_fail_but_answered_id_reuse_is_valid(tmp_path, transport):
    call = {"type": "function_call", "call_id": "same", "name": "read", "arguments": "{}"}
    answer = {"type": "function_call_output", "call_id": "same", "output": "ok"}
    client = bridge(tmp_path)
    with pytest.raises(ValueError, match="Duplicate pending"):
        client.responses({"input": [call, call, answer]})
    assert client.responses({"input": [call, answer, call, answer]})["status"] == "completed"


def test_response_usage_and_partial_calls_validate_against_actual_gym(tmp_path, transport):
    pytest.importorskip("nemo_gym")
    from nemo_gym.openai_utils import NeMoGymChatCompletion, NeMoGymResponse

    _, state = transport
    state["response"]["done_reason"] = "length"
    state["response"]["message"]["tool_calls"] = [
        {"function": {"name": TOOL["name"], "arguments": {}}}
    ]
    client = bridge(tmp_path)
    result = NeMoGymResponse.model_validate(client.responses({"input": "Read", "tools": [TOOL]}))
    assert result.status == "incomplete"
    assert result.incomplete_details.reason == "max_output_tokens"
    assert result.output[-1].status == "incomplete"
    chat = NeMoGymChatCompletion.model_validate(
        client.chat_completions(
            {
                "messages": [{"role": "user", "content": "Read"}],
                "tools": [
                    {"type": "function", "function": {k: v for k, v in TOOL.items() if k != "type"}}
                ],
            }
        )
    )
    assert chat.choices[0].finish_reason == "length"


def test_http_routes_reject_lossy_options_before_gym_normalization(tmp_path, transport):
    pytest.importorskip("nemo_gym")
    from fastapi.testclient import TestClient
    from nemo_gym.server_utils import ServerClient

    from integrations.nemo_gym.native_ollama import NativeOllamaModel, NativeOllamaModelConfig

    config = NativeOllamaModelConfig(
        name="native",
        host="127.0.0.1",
        port=8081,
        entrypoint="",
        model=MODEL,
        expected_digest=DIGEST,
        capture_dir=tmp_path,
        output_budget=512,
    )
    server_client = MagicMock(spec=ServerClient)
    server_client.global_config_dict = {}
    server = NativeOllamaModel(config=config, server_client=server_client)
    with TestClient(server.setup_webserver()) as client:
        assert client.post("/v1/responses", json={"input": "Read"}).status_code == 200
        calls, _ = transport
        initial = len(calls)
        for body in [
            {"input": "Read", "stream": True},
            {"input": "Read", "tools": [{**TOOL, "unsupported_nested_option": True}]},
        ]:
            assert client.post("/v1/responses", json=body).status_code == 422
        assert (
            client.post(
                "/v1/messages", json={"model": MODEL, "messages": [], "max_tokens": 512}
            ).status_code
            == 422
        )
        assert len(calls) == initial


def test_unadvertised_function_is_preserved_but_never_dispatched(tmp_path, transport):
    _, state = transport
    state["response"]["message"]["tool_calls"] = [
        {"function": {"name": "notAdvertised", "arguments": {}}}
    ]
    with pytest.raises(LocalModelError, match="advertised"):
        bridge(tmp_path).responses({"input": "Read", "tools": [TOOL]})
    assert len(list(tmp_path.glob("*/error.json"))) == 1
    assert not list(tmp_path.glob("*/response.json"))
