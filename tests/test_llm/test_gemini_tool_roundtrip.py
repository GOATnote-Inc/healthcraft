"""Exercise native Google SDK request types while replacing only network I/O."""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from healthcraft.llm.agent import GeminiClient

types = pytest.importorskip("google.genai.types")


def _response(parts):
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(content=types.Content(role="model", parts=parts), finish_reason="STOP")
        ]
    )


def _client(*responses):
    generate = Mock(side_effect=responses or [_response([types.Part.from_text(text="Done")])])
    client = GeminiClient(api_key="unused", model="gemini-fixture")
    client._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    return client, generate


def _assistant(call_id="call_getPatientHistory_0", name="getPatientHistory", **extra):
    return {
        "role": "assistant",
        "tool_calls": [{"id": call_id, "name": name, "arguments": {}, **extra}],
    }


def _tool(call_id="call_getPatientHistory_0", **response):
    return {"role": "tool", "tool_call_id": call_id, "content": json.dumps(response)}


def _parts(generate):
    return [part for content in generate.call_args.kwargs["contents"] for part in content.parts]


@pytest.mark.parametrize("native_id", [None, "provider-call-42"])
@pytest.mark.parametrize("signature", [None, b"opaque-provider-signature\x00\xff"])
def test_sdk_tool_roundtrip_links_response_to_function_and_preserves_signature(
    native_id, signature
):
    first_response = _response(
        [
            types.Part(
                function_call=types.FunctionCall(
                    id=native_id, name="getPatientHistory", args={"patient_id": "PAT-1"}
                ),
                thought_signature=signature,
            )
        ]
    )
    client, generate = _client(first_response, _response([types.Part.from_text(text="Done")]))
    messages = [{"role": "user", "content": "Retrieve PAT-1 history"}]
    reply = client.chat(messages)
    assert reply["stop_reason"] == "tool_calls"
    call = reply["tool_calls"][0]
    if signature:
        assert base64.b64decode(call["thought_signature"]) == signature
    else:
        assert "thought_signature" not in call
    messages += [
        {"role": "assistant", "tool_calls": reply["tool_calls"]},
        _tool(call["id"], status="ok", data={"id": "PAT-1"}),
    ]
    assert client.chat(messages)["stop_reason"] == "stop"
    parts = _parts(generate)
    returned_call = next(p for p in parts if p.function_call)
    returned_result = next(p.function_response for p in parts if p.function_response)
    assert returned_result.name == returned_call.function_call.name == "getPatientHistory"
    assert returned_call.function_call.args == {"patient_id": "PAT-1"}
    assert returned_call.thought_signature == signature
    assert returned_call.function_call.id == returned_result.id == native_id
    assert returned_result.response == {"status": "ok", "data": {"id": "PAT-1"}}


def test_sequential_reused_ids_are_linked_to_each_preceding_call():
    client, generate = _client()
    client.chat(
        [
            _assistant("reused", "getPatientHistory"),
            _tool("reused", patient="first"),
            _assistant("reused", "getEncounterDetails"),
            _tool("reused", encounter="second"),
        ]
    )
    results = [p.function_response for p in _parts(generate) if p.function_response]
    assert [(r.name, r.response) for r in results] == [
        ("getPatientHistory", {"patient": "first"}),
        ("getEncounterDetails", {"encounter": "second"}),
    ]


def test_parallel_calls_keep_names_and_payloads_linked():
    client, generate = _client()
    first, second = _assistant("first"), _assistant("second", "getEncounterDetails")
    first["tool_calls"] += second["tool_calls"]
    client.chat([first, _tool("first", patient="PAT-1"), _tool("second", encounter="ENC-2")])
    results = [p.function_response for p in _parts(generate) if p.function_response]
    assert [(r.name, r.response) for r in results] == [
        ("getPatientHistory", {"patient": "PAT-1"}),
        ("getEncounterDetails", {"encounter": "ENC-2"}),
    ]
    response_contents = [c for c in generate.call_args.kwargs["contents"] if c.role == "user"]
    assert len(response_contents) == 1
    assert len(response_contents[0].parts) == 2


def test_user_text_stays_separate_between_completed_roundtrips():
    client, generate = _client()
    client.chat(
        [
            {"role": "user", "content": "First request"},
            _assistant(),
            _tool(sequence=1),
            {"role": "user", "content": "Second request"},
            _assistant(),
            _tool(sequence=2),
        ]
    )
    contents = generate.call_args.kwargs["contents"]
    assert [c.role for c in contents] == ["user", "model", "user", "user", "model", "user"]
    assert contents[0].parts[0].text == "First request"
    assert contents[3].parts[0].text == "Second request"
    assert contents[2].parts[0].function_response.response == {"sequence": 1}
    assert contents[5].parts[0].function_response.response == {"sequence": 2}


@pytest.mark.parametrize(
    "messages",
    [
        [_tool("orphan")],
        [_assistant(), _tool("wrong")],
        [_assistant(), {"role": "tool", "content": "{}"}],
        [_assistant(), _tool(), _tool()],
        [_assistant()],
        [_assistant(call_id=""), _tool("")],
        [
            {
                "role": "assistant",
                "tool_calls": _assistant()["tool_calls"] * 2,
            },
            _tool(),
        ],
        [_assistant(), _assistant(), _tool()],
    ],
)
def test_ambiguous_or_incomplete_linkage_fails_before_network_request(messages):
    client, generate = _client()
    with pytest.raises(ValueError, match="Gemini.*(tool|function).*(call|response)"):
        client.chat(messages)
    generate.assert_not_called()
