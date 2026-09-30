"""Incomplete rollouts must preserve evidence without masquerading as completion."""

from types import SimpleNamespace

import pytest

from healthcraft.llm import agent


def _task():
    return SimpleNamespace(
        id="IR-limit",
        category="information_retrieval",
        level=1,
        title="completion budget",
        description="Retrieve details",
        initial_state={},
    )


def _server():
    return SimpleNamespace(
        available_tools=["searchPatients"],
        call_tool=lambda *args: {"status": "ok", "data": []},
    )


def test_tool_round_exhaustion_is_explicit_and_preserves_last_tool_result(monkeypatch):
    monkeypatch.setattr(agent, "MAX_TOOL_ROUNDS", 2)
    client = SimpleNamespace(
        chat=lambda *args, **kwargs: {
            "content": "Searching",
            "stop_reason": "tool_calls",
            "tool_calls": [{"id": "call", "name": "searchPatients", "arguments": {}}],
        }
    )
    trajectory = agent.run_agent_task(client, _task(), _server(), "system")
    assert trajectory.error and "tool round limit" in trajectory.error
    assert trajectory.metadata["stop_reason"] == "tool_round_limit"
    assert trajectory.metadata["max_tool_rounds"] == 2
    assert len(trajectory.turns) == 6
    assert trajectory.turns[-1].role == "tool"


@pytest.mark.parametrize("reason", ["length", "max_tokens", "max_output_tokens"])
def test_token_truncation_preserves_partial_text_as_incomplete(reason):
    client = SimpleNamespace(
        chat=lambda *args, **kwargs: {
            "content": "The incomplete answer is",
            "tool_calls": [],
            "stop_reason": reason,
        }
    )
    trajectory = agent.run_agent_task(client, _task(), _server(), "system")
    assert trajectory.error and "truncated" in trajectory.error
    assert trajectory.turns[-1].content == "The incomplete answer is"
    assert trajectory.metadata["stop_reason"] == reason


def test_final_answer_in_last_available_round_is_complete(monkeypatch):
    monkeypatch.setattr(agent, "MAX_TOOL_ROUNDS", 1)
    client = SimpleNamespace(
        chat=lambda *args, **kwargs: {
            "content": "Complete",
            "tool_calls": [],
            "stop_reason": "stop",
        }
    )
    trajectory = agent.run_agent_task(client, _task(), _server(), "system")
    assert trajectory.error is None
    assert trajectory.metadata["stop_reason"] == "stop"


def _gemini_client(reason, *, with_tool=False, empty_parts=False):
    """Use the official SDK's response shape; stub only the network method."""
    types = pytest.importorskip("google.genai.types")
    parts = [types.Part.from_text(text="Partial answer")]
    if with_tool:
        parts.append(types.Part.from_function_call(name="searchPatients", args={}))
    response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=None if empty_parts else parts),
                finish_reason=reason,
            )
        ]
    )
    client = agent.GeminiClient(api_key="unused", model="gemini-fixture")
    client._client = SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **kwargs: response)
    )
    return client


@pytest.mark.parametrize("with_tool", [False, True])
def test_gemini_max_tokens_retains_evidence_and_never_dispatches_tools(with_tool):
    client = _gemini_client("MAX_TOKENS", with_tool=with_tool)
    server = _server()
    dispatched = []
    server.call_tool = lambda *args: dispatched.append(args)
    trajectory = agent.run_agent_task(client, _task(), server, "system")
    assert trajectory.error and "truncated (max_tokens)" in trajectory.error
    assert trajectory.metadata["stop_reason"] == "max_tokens"
    assert trajectory.turns[-1].content == "Partial answer"
    assert dispatched == []


def test_gemini_empty_parts_at_token_limit_is_still_truncation():
    client = _gemini_client("MAX_TOKENS", empty_parts=True)
    response = client.chat([{"role": "user", "content": "test"}])
    assert response["stop_reason"] == "max_tokens"
    assert response["content"] == ""


@pytest.mark.parametrize("with_tool,expected", [(False, "stop"), (True, "tool_calls")])
def test_gemini_natural_completion_preserves_tools(with_tool, expected):
    response = _gemini_client("STOP", with_tool=with_tool).chat(
        [{"role": "user", "content": "test"}]
    )
    assert response["stop_reason"] == expected
    assert bool(response["tool_calls"]) is with_tool


@pytest.mark.parametrize(
    "reason",
    [
        "SAFETY",
        "RECITATION",
        "MALFORMED_FUNCTION_CALL",
        "OTHER",
        "FINISH_REASON_UNSPECIFIED",
        None,
    ],
)
def test_gemini_non_success_termination_cannot_appear_completed(reason):
    client = _gemini_client(reason, with_tool=True)
    with pytest.raises(RuntimeError, match="Gemini completion") as exc:
        client.chat([{"role": "user", "content": "test"}])
    assert (reason or "missing") in str(exc.value)


def test_gemini_prompt_block_has_explicit_reason():
    types = pytest.importorskip("google.genai.types")
    response = types.GenerateContentResponse(
        candidates=[],
        prompt_feedback=types.GenerateContentResponsePromptFeedback(block_reason="SAFETY"),
    )
    client = agent.GeminiClient(api_key="unused", model="gemini-fixture")
    client._client = SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **kwargs: response)
    )
    with pytest.raises(RuntimeError, match="SAFETY"):
        client.chat([{"role": "user", "content": "test"}])


@pytest.mark.parametrize("reason", ["content_filter", "refusal", "pause_turn", "unknown", None, ""])
@pytest.mark.parametrize("with_tool", [False, True])
def test_non_completion_termination_preserves_evidence_without_dispatch(reason, with_tool):
    response = {"content": "Partial provider output", "stop_reason": reason, "tool_calls": []}
    if with_tool:
        response["tool_calls"] = [{"id": "call", "name": "searchPatients", "arguments": {}}]
    client = SimpleNamespace(chat=lambda *args, **kwargs: response)
    server = _server()
    dispatched = []
    server.call_tool = lambda *args: dispatched.append(args)
    trajectory = agent.run_agent_task(client, _task(), server, "system")
    assert trajectory.error is not None
    assert trajectory.metadata["stop_reason"] == reason
    assert trajectory.turns[-1].role == "assistant"
    assert trajectory.turns[-1].content == "Partial provider output"
    assert dispatched == []
    if reason in {"content_filter", "refusal"}:
        assert "provider" in trajectory.error.lower()
        assert trajectory.metadata["termination_kind"] == (
            "provider_filter" if reason == "content_filter" else "provider_refusal"
        )


@pytest.mark.parametrize("reason", ["tool_calls", "tool_use"])
def test_tool_continuation_without_tool_calls_is_incomplete(reason):
    client = SimpleNamespace(
        chat=lambda *args, **kwargs: {
            "content": "I intend to retrieve the record",
            "tool_calls": [],
            "stop_reason": reason,
        }
    )
    trajectory = agent.run_agent_task(client, _task(), _server(), "system")
    assert trajectory.error and "tool" in trajectory.error.lower()
    assert trajectory.metadata["stop_reason"] == reason


@pytest.mark.parametrize("reason", ["stop", "end_turn", "stop_sequence"])
def test_recognized_final_completion_is_accepted_without_tools(reason):
    client = SimpleNamespace(
        chat=lambda *args, **kwargs: {
            "content": "Completed response",
            "tool_calls": [],
            "stop_reason": reason,
        }
    )
    trajectory = agent.run_agent_task(client, _task(), _server(), "system")
    assert trajectory.error is None
    assert trajectory.metadata["stop_reason"] == reason


@pytest.mark.parametrize("reason", ["stop", "end_turn", "stop_sequence"])
def test_final_completion_reason_cannot_authorize_pending_tools(reason):
    client = SimpleNamespace(
        chat=lambda *args, **kwargs: {
            "content": "Inconsistent response",
            "stop_reason": reason,
            "tool_calls": [{"id": "call", "name": "searchPatients", "arguments": {}}],
        }
    )
    server = _server()
    dispatched = []
    server.call_tool = lambda *args: dispatched.append(args)
    trajectory = agent.run_agent_task(client, _task(), server, "system")
    assert trajectory.error is not None
    assert dispatched == []


@pytest.mark.parametrize("reason", ["tool_calls", "tool_use"])
def test_recognized_tool_continuation_executes_then_requires_completion(reason):
    responses = iter(
        [
            {
                "content": "Retrieving",
                "stop_reason": reason,
                "tool_calls": [{"id": "call", "name": "searchPatients", "arguments": {}}],
            },
            {"content": "Complete", "stop_reason": "end_turn", "tool_calls": []},
        ]
    )
    client = SimpleNamespace(chat=lambda *args, **kwargs: next(responses))
    trajectory = agent.run_agent_task(client, _task(), _server(), "system")
    assert trajectory.error is None
    assert [turn.role for turn in trajectory.turns] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
    ]


@pytest.mark.parametrize("reason", ["stop", "end_turn", "stop_sequence"])
def test_action_only_completion_can_have_blank_final_narrative(reason):
    responses = iter(
        [
            {
                "content": "",
                "stop_reason": "tool_calls",
                "tool_calls": [{"id": "call", "name": "searchPatients", "arguments": {}}],
            },
            {"content": "", "stop_reason": reason, "tool_calls": []},
        ]
    )
    client = SimpleNamespace(chat=lambda *args, **kwargs: next(responses))
    trajectory = agent.run_agent_task(client, _task(), _server(), "system")
    assert trajectory.error is None
    assert trajectory.metadata["termination_kind"] == "complete"
    assert trajectory.turns[-1].content == ""


def test_missing_finish_reason_is_not_inferred_to_be_completion():
    client = SimpleNamespace(chat=lambda *args, **kwargs: {"content": "Partial", "tool_calls": []})
    trajectory = agent.run_agent_task(client, _task(), _server(), "system")
    assert trajectory.error is not None
    assert trajectory.metadata["stop_reason"] is None


def test_explicit_refusal_metadata_overrides_normal_stop():
    client = SimpleNamespace(
        chat=lambda *args, **kwargs: {
            "content": "Partial",
            "tool_calls": [],
            "stop_reason": "stop",
            "refusal": "Provider declined this request.",
        }
    )
    trajectory = agent.run_agent_task(client, _task(), _server(), "system")
    assert trajectory.error and "provider refusal" in trajectory.error.lower()
    assert trajectory.metadata["termination_kind"] == "provider_refusal"
    assert trajectory.metadata["provider_refusal"] == "Provider declined this request."
    assert trajectory.turns[-1].content == "Partial"


def test_openai_refusal_metadata_is_not_discarded_by_adapter():
    client = agent.OpenAIClient(api_key="unused", model="gpt-fixture")
    message = SimpleNamespace(content=None, tool_calls=None, refusal="Provider refusal text")
    response = SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])
    client._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: response,
            )
        )
    )
    result = client.chat([{"role": "user", "content": "test"}])
    assert result.get("refusal") == "Provider refusal text"
