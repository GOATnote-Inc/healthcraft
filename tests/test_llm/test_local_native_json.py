"""Ambiguous native responses cannot become an accepted model finish."""

import base64
import hashlib
import io
import json

import pytest

from healthcraft.llm.local_models import LocalModelError, OllamaClient
from healthcraft.reconciliation.controller import RecordingOllamaClient


class BodyOpener:
    def __init__(self, body):
        self.body = body
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        return io.BytesIO(self.body)


@pytest.mark.parametrize(
    "body",
    [
        b'{"done_reason":"length","done_reason":"stop"}',
        b'{"message":{"role":"user","role":"assistant","content":"{}"}}',
        b'{"models":[{"name":"local","digest":"a","digest":"b"}]}',
        b'{"done":false,"done":true}',
        b'{"eval_count":NaN}',
        b'{"duration":Infinity}',
        b'{"duration":-Infinity}',
        b'{"eval_count":1e999}',
        b'{"value":-1e999}',
        '{"value":1}'.encode("utf-16"),
    ],
)
def test_ambiguous_or_nonfinite_native_json_is_rejected_before_use(body):
    client = OllamaClient("local")
    client._opener = BodyOpener(body)
    with pytest.raises(LocalModelError, match="invalid JSON"):
        client._request("/api/chat", {})


def test_exact_valid_values_survive_native_decoding():
    value = {"done": True, "number": 1.25, "nested": {"unknown": None, "literal": "é"}}
    client = OllamaClient("local")
    client._opener = BodyOpener(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    assert client._request("/api/chat", {}) == value


@pytest.mark.parametrize("valid", [True, False])
def test_recording_client_preserves_exact_body_before_json_validation(valid):
    events = []
    body = (
        b'{"model":"local", "done":true,"done_reason":"stop",'
        b'"message":{"role":"assistant","content":"{\\"action\\":\\"finish\\"}"}}'
    )
    if not valid:
        body = body.replace(b'"done_reason":"stop"', b'"done_reason":"length","done_reason":"stop"')
    client = RecordingOllamaClient(
        model="local", expected_digest="a" * 64, expected_runtime="test", event_sink=events.append
    )
    client._opener = BodyOpener(body)
    if valid:
        assert client._request("/api/chat", {"model": "local"})["done_reason"] == "stop"
    else:
        with pytest.raises(LocalModelError):
            client._request("/api/chat", {"model": "local"})
    exchange = client.exchanges[0]
    assert base64.b64decode(exchange["response_body_b64"]) == body
    assert exchange["response_body_sha256"] == hashlib.sha256(body).hexdigest()
    received = next(e for e in events if e["event"] == "model_response_received")
    assert received["exchange"]["response"] is None
    assert base64.b64decode(received["exchange"]["response_body_b64"]) == body
    assert events[-1]["event"] == ("model_returned" if valid else "model_failed")
    if not valid:
        assert exchange["response"] is None
        assert exchange["error"]["type"] == "LocalModelError"


def test_capture_sink_failure_is_not_misreported_as_invalid_native_json():
    def sink(event):
        if event["event"] == "model_response_received":
            raise OSError("evidence disk unavailable")

    client = RecordingOllamaClient(
        model="local", expected_digest="a" * 64, expected_runtime="test", event_sink=sink
    )
    client._opener = BodyOpener(b'{"done":true}')
    with pytest.raises(OSError, match="evidence disk"):
        client._request("/api/chat", {})
    assert client.exchanges[0]["response"] is None
    assert client.exchanges[0]["error"]["type"] == "OSError"


@pytest.mark.parametrize(
    "arguments",
    [
        '{"encounter_id":"ENC-AAAAAAAA","encounter_id":"ENC-BBBBBBBB"}',
        '{"nested":{"value":1,"value":2}}',
        '{"value":NaN}',
        '{"value":1e999}',
    ],
)
def test_string_encoded_native_tool_arguments_cannot_bypass_strict_json(arguments):
    client = OllamaClient("local")
    client._info = {"capabilities": ["completion", "tools"]}
    client._opener = BodyOpener(
        json.dumps(
            {
                "done": True,
                "done_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "getEncounterDetails",
                                "arguments": arguments,
                            }
                        }
                    ],
                },
            }
        ).encode()
    )
    with pytest.raises(LocalModelError, match="tool arguments"):
        client.chat(
            [{"role": "user", "content": "lookup"}],
            tools=[{"name": "getEncounterDetails", "parameters": {"type": "object"}}],
        )
