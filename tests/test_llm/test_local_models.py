"""Local evaluation must stay local and preserve native tool-call semantics."""

from __future__ import annotations

from typing import Any

import pytest

from healthcraft.llm.agent import create_client
from healthcraft.llm.local_models import (
    LocalModelError,
    OllamaClient,
    ToolCapabilityError,
)


def _client(monkeypatch, *, capabilities=None, family="nemotron_h_moe", response=None):
    calls = []
    client = OllamaClient("nano:latest", seed=7, num_ctx=16384)

    def request(path, payload=None):
        calls.append((path, payload))
        if path == "/api/version":
            return {"version": "0.test"}
        if path == "/api/tags":
            return {"models": [{"name": "nano:latest", "digest": "sha256:abc"}]}
        if path == "/api/show":
            return {
                "capabilities": capabilities
                if capabilities is not None
                else ["completion", "tools"],
                "details": {"family": family, "quantization_level": "Q5_K_M"},
            }
        return response or {
            "message": {"role": "assistant", "content": "OK"},
            "done": True,
            "done_reason": "stop",
        }

    monkeypatch.setattr(client, "_request", request)
    return client, calls


def test_factory_routes_local_names_before_cloud_substrings(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-use")
    client = create_client("ollama:gpt-oss:20b", "must-not-use")
    assert isinstance(client, OllamaClient)
    assert client._model == "gpt-oss:20b"
    assert not hasattr(client, "_api_key")


@pytest.mark.parametrize("name", ["", " ", "nano:cloud", "nano-cloud:latest"])
def test_invalid_or_cloud_models_fail_before_network(name):
    with pytest.raises(ValueError):
        OllamaClient(name)


@pytest.mark.parametrize(
    "url",
    [
        "https://ollama.com",
        "http://192.168.0.2:11434",
        "http://0.0.0.0:11434",
        "http://user:secret@localhost:11434",
        "http://localhost:11434/proxy",
        "http://localhost:11434?url=https://example.com",
        "file:///tmp/model",
    ],
)
def test_remote_or_ambiguous_endpoints_are_rejected(url):
    with pytest.raises(ValueError, match="loopback"):
        OllamaClient("nano", base_url=url)


def test_localhost_is_normalized_to_loopback_literal():
    assert (
        OllamaClient("nano", base_url="http://localhost:11434/")._base_url
        == "http://127.0.0.1:11434"
    )


def test_text_only_medgemma_remains_usable_as_diagnostic_judge(monkeypatch):
    client, calls = _client(monkeypatch, capabilities=["completion"], family="gemma3")
    assert client.chat([{"role": "user", "content": "Reply OK"}])["content"] == "OK"
    assert calls[-1][0] == "/api/chat"


def test_text_only_model_cannot_silently_skip_tools(monkeypatch):
    client, calls = _client(monkeypatch, capabilities=["completion"])
    with pytest.raises(ToolCapabilityError, match="text-only"):
        client.chat(
            [{"role": "user", "content": "Retrieve encounter"}],
            tools=[{"name": "getEncounterDetails"}],
        )
    assert not any(path == "/api/chat" for path, _ in calls)


def test_missing_model_does_not_pull_or_fall_back(monkeypatch):
    client = OllamaClient("missing")
    calls = []
    monkeypatch.setattr(
        client, "_request", lambda path, payload=None: calls.append(path) or {"models": []}
    )
    with pytest.raises(LocalModelError, match="installed"):
        client.validate_capabilities()
    assert calls == ["/api/tags"]


@pytest.mark.parametrize("source", ["tags", "show"])
def test_alias_to_remote_model_is_rejected(monkeypatch, source):
    client = OllamaClient("alias")

    def request(path, payload=None):
        if path == "/api/tags":
            model = {"name": "alias:latest", "digest": "abc"}
            if source == "tags":
                model["remote_model"] = "large-model"
            return {"models": [model]}
        return {"capabilities": ["completion"], "remote_host": "https://ollama.com"}

    monkeypatch.setattr(client, "_request", request)
    with pytest.raises(LocalModelError, match="remote"):
        client.chat([{"role": "user", "content": "hello"}])


def test_native_tools_and_results_roundtrip_without_losing_names(monkeypatch):
    client, calls = _client(
        monkeypatch,
        response={
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "getEncounterDetails",
                            "arguments": {"encounter_id": "ENC-001"},
                        }
                    },
                ],
            },
            "done": True,
            "done_reason": "stop",
        },
    )
    tools = [{"name": "getEncounterDetails", "parameters": {"type": "object"}}]
    first = client.chat([{"role": "user", "content": "Retrieve it"}], tools=tools, max_tokens=64)
    tool_call = first["tool_calls"][0]
    assert tool_call["id"]
    assert tool_call["arguments"] == {"encounter_id": "ENC-001"}
    assert first["stop_reason"] == "tool_calls"
    client.chat(
        [
            {"role": "assistant", "content": "", "tool_calls": [tool_call]},
            {"role": "tool", "tool_call_id": tool_call["id"], "content": '{"status":"success"}'},
        ],
        tools=tools,
        max_tokens=64,
    )
    payload = calls[-1][1]
    assert payload["stream"] is False
    assert payload["options"] == {
        "temperature": 0.0,
        "seed": 7,
        "num_ctx": 16384,
        "num_predict": 64,
    }
    assert payload["messages"][0]["tool_calls"][0]["function"]["arguments"] == {
        "encounter_id": "ENC-001"
    }
    assert payload["messages"][1]["tool_name"] == "getEncounterDetails"
    assert payload["tools"][0]["function"]["name"] == "getEncounterDetails"
    assert not any(key in payload for key in ("api_key", "Authorization"))


@pytest.mark.parametrize("reason", ["length", "max_tokens", "max_output_tokens"])
def test_truncated_native_tool_call_is_not_executed(monkeypatch, reason):
    from types import SimpleNamespace

    from healthcraft.llm.agent import run_agent_task

    client, _ = _client(
        monkeypatch,
        response={
            "message": {
                "role": "assistant",
                "content": "partial",
                "tool_calls": [
                    {"function": {"name": "searchPatients", "arguments": {}}},
                ],
            },
            "done": True,
            "done_reason": reason,
        },
    )
    dispatched = []
    server = SimpleNamespace(
        available_tools=["searchPatients"],
        call_tool=lambda *args: dispatched.append(args) or {"status": "ok"},
    )
    task = SimpleNamespace(
        id="IR-truncated",
        category="information_retrieval",
        level=1,
        title="test",
        description="retrieve",
        initial_state={},
    )
    trajectory = run_agent_task(client, task, server, "system")
    assert dispatched == []
    assert "truncated" in trajectory.error
    assert trajectory.metadata["stop_reason"] == reason


@pytest.mark.parametrize("termination", [{}, {"done_reason": None}, {"done_reason": "unknown"}])
@pytest.mark.parametrize("with_tools", [False, True])
def test_unknown_native_termination_cannot_complete_or_dispatch(
    monkeypatch, termination, with_tools
):
    from types import SimpleNamespace

    from healthcraft.llm.agent import run_agent_task

    message = {"role": "assistant", "content": "A response is not proof of completed generation."}
    if with_tools:
        message["tool_calls"] = [
            {"function": {"name": "searchPatients", "arguments": {}}},
        ]
    client, requests = _client(
        monkeypatch, response={"message": message, "done": True, **termination}
    )
    dispatched = []
    server = SimpleNamespace(
        available_tools=["searchPatients"],
        call_tool=lambda *args: dispatched.append(args) or {"status": "ok"},
    )
    task = SimpleNamespace(
        id="IR-unknown-termination",
        category="information_retrieval",
        level=1,
        title="test",
        description="retrieve",
        initial_state={},
    )

    trajectory = run_agent_task(client, task, server, "system")

    assert dispatched == []
    assert trajectory.error is not None
    assert trajectory.metadata["termination_kind"] == "incomplete_provider_turn"
    assert trajectory.metadata["stop_reason"] == termination.get("done_reason")
    assert sum(path == "/api/chat" for path, _ in requests) == 1


@pytest.mark.parametrize("arguments", ["broken JSON", "[]", [1], None])
def test_malformed_tool_arguments_fail_before_execution(monkeypatch, arguments):
    client, _ = _client(
        monkeypatch,
        response={
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "getEncounterDetails", "arguments": arguments}},
                ],
            },
            "done": True,
        },
    )
    with pytest.raises(LocalModelError, match="arguments"):
        client.chat([{"role": "user", "content": "go"}], tools=[{"name": "getEncounterDetails"}])


def test_metadata_records_model_digest_and_runtime_parameters(monkeypatch):
    client, _ = _client(monkeypatch)
    info = client.model_metadata()
    assert info["model_digest"] == "sha256:abc"
    assert info["family"] == "nemotron_h_moe"
    assert info["seed"] == 7
    assert info["num_ctx"] == 16384
    assert info["provider"] == "ollama"
    assert info["runtime_version"] == "0.test"


def test_transport_does_not_use_environment_proxy_or_follow_redirects(monkeypatch):
    import healthcraft.llm.local_models as local

    handlers: list[Any] = []
    monkeypatch.setattr(local, "build_opener", lambda *items: handlers.extend(items) or object())
    OllamaClient("nano")
    assert any(getattr(handler, "proxies", None) == {} for handler in handlers)
    redirect_handler = next(
        handler for handler in handlers if isinstance(handler, local.HTTPRedirectHandler)
    )
    with pytest.raises(LocalModelError, match="redirect"):
        redirect_handler.redirect_request(None, None, 302, "moved", {}, "https://ollama.com")


def test_agent_trajectory_keeps_tool_call_ids_for_replay(monkeypatch):
    from types import SimpleNamespace

    from healthcraft.llm.agent import run_agent_task

    replies = iter(
        [
            {
                "content": "",
                "stop_reason": "tool_calls",
                "tool_calls": [{"id": "call-123", "name": "searchPatients", "arguments": {}}],
            },
            {"content": "Done", "tool_calls": [], "stop_reason": "stop"},
        ]
    )
    client = SimpleNamespace(chat=lambda *a, **k: next(replies))
    server = SimpleNamespace(
        available_tools=["searchPatients"], call_tool=lambda *a: {"status": "success"}
    )
    task = SimpleNamespace(
        id="IR-test",
        category="information_retrieval",
        level=1,
        title="test",
        description="retrieve",
        initial_state={},
    )
    trajectory = run_agent_task(client, task, server, "system")
    call = trajectory.turns[2].tool_calls[0]
    assert call["id"] == trajectory.turns[3].tool_call_id == "call-123"


def test_local_cli_never_resolves_cloud_key(monkeypatch):
    from healthcraft.llm.orchestrator import _resolve_api_key

    monkeypatch.setenv("OPENAI_API_KEY", "paid-key")
    assert _resolve_api_key("ollama:gpt-oss:20b") == ""


def test_local_agent_does_not_implicitly_select_cloud_judge():
    from healthcraft.llm.orchestrator import _select_evaluation_judge

    assert _select_evaluation_judge("ollama:nano", None) is None
    assert _select_evaluation_judge("ollama:nano", "ollama:medgemma") == "ollama:medgemma"
    with pytest.raises(ValueError, match="local"):
        _select_evaluation_judge("ollama:nano", "gpt-5.4")


def test_local_preflight_is_keyless_and_checks_agent_tools(monkeypatch):
    import healthcraft.llm.agent as agent
    from healthcraft.llm.orchestrator import _api_preflight

    client, calls = _client(monkeypatch)
    monkeypatch.setattr(agent, "create_client", lambda *args: client)
    _api_preflight("ollama:nano", "", None, "")
    assert not any(path == "/api/chat" for path, _ in calls)


def test_local_preflight_rejects_text_only_agent_before_evaluation(monkeypatch):
    import healthcraft.llm.agent as agent
    from healthcraft.llm.orchestrator import _api_preflight

    client, _ = _client(monkeypatch, capabilities=["completion"])
    monkeypatch.setattr(agent, "create_client", lambda *args: client)
    with pytest.raises(SystemExit) as exc:
        _api_preflight("ollama:medgemma", "", None, "")
    assert exc.value.code == 2


def test_local_preflight_checks_explicit_keyless_judge(monkeypatch):
    import healthcraft.llm.agent as agent
    from healthcraft.llm.orchestrator import _api_preflight

    client, _ = _client(monkeypatch)
    seen = []

    def factory(model, key):
        seen.append((model, key))
        return client

    monkeypatch.setattr(agent, "create_client", factory)
    _api_preflight("ollama:nano", "", "ollama:medgemma", "")
    assert seen == [("ollama:nano", ""), ("ollama:medgemma", "")]


@pytest.mark.parametrize(
    "agent_family,judge_family",
    [
        ("nemotron_h_moe", "nemotron"),
        ("gemma3", "gemma4"),
        ("qwen2", "qwen3"),
    ],
)
def test_local_judges_cannot_bypass_vendor_guard_with_aliases(agent_family, judge_family):
    from healthcraft.llm.orchestrator import _check_local_judge_pair

    with pytest.raises(ValueError, match="self-judge"):
        _check_local_judge_pair(
            {"model": "one", "family": agent_family, "model_digest": "one"},
            {"model": "two", "family": judge_family, "model_digest": "two"},
        )


def test_nemotron_and_medgemma_are_allowed_cross_vendor_diagnostics():
    from healthcraft.llm.orchestrator import _check_local_judge_pair

    _check_local_judge_pair(
        {"model": "nano", "family": "nemotron_h_moe", "model_digest": "one"},
        {"model": "medgemma", "family": "gemma3", "model_digest": "two"},
    )


def test_unknown_local_judge_origin_is_not_treated_as_cross_vendor():
    from healthcraft.llm.orchestrator import _check_local_judge_pair

    with pytest.raises(ValueError, match="Cannot establish vendor"):
        _check_local_judge_pair(
            {"model": "nano", "family": "nemotron_h_moe"},
            {"model": "mystery", "family": ""},
        )


def test_cloud_agent_cannot_self_judge_through_local_vendor_alias(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from healthcraft.llm import orchestrator

    medgemma, _ = _client(monkeypatch, family="gemma3")
    monkeypatch.setattr(
        orchestrator,
        "create_client",
        lambda model, key: medgemma if model.startswith("ollama:") else SimpleNamespace(),
    )
    result = orchestrator.run_frontier_evaluation(
        "gemini-3.1-pro",
        "dummy-key",
        "ollama:medgemma",
        "",
        task_filter="CR-001",
        results_dir=tmp_path / "out",
    )
    assert "self-judge" in result["error"]


@pytest.mark.parametrize("role", ["user", "tool", "system", None, "missing"])
@pytest.mark.parametrize("with_tools", [False, True])
def test_native_response_requires_explicit_assistant_role_before_exposing_output(
    monkeypatch, role, with_tools
):
    message = {"content": "Never expose this as an assistant completion."}
    if role != "missing":
        message["role"] = role
    if with_tools:
        message["tool_calls"] = [
            {"function": {"name": "getEncounterDetails", "arguments": {"encounter_id": "ENC-001"}}}
        ]
    client, requests = _client(
        monkeypatch,
        response={"done": True, "done_reason": "stop", "message": message},
    )
    with pytest.raises(LocalModelError, match="role"):
        client.chat(
            [{"role": "user", "content": "Read"}],
            tools=[{"name": "getEncounterDetails"}] if with_tools else None,
        )
    assert client._call_sequence == 0
    assert sum(path == "/api/chat" for path, _ in requests) == 1
