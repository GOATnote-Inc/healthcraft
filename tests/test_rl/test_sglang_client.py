"""SGLangClient factory and routing tests.

No real network calls — only client construction and factory routing are
exercised (``_ensure_client`` is not invoked, so the ``openai`` package
need not be installed for these tests).
"""

from __future__ import annotations

from healthcraft.llm.agent import (
    AnthropicClient,
    GeminiClient,
    OpenAIClient,
    SGLangClient,
    create_client,
)


def test_routing_via_sglang_prefix():
    client = create_client("sglang:Qwen/Qwen3-30B-A3B", api_key="")
    assert isinstance(client, SGLangClient)
    # Prefix is stripped from the model name.
    assert client._model == "Qwen/Qwen3-30B-A3B"


def test_routing_via_http_url(monkeypatch):
    monkeypatch.setenv("SGLANG_MODEL", "nemotron-h-30b")
    client = create_client("http://localhost:30000/v1", api_key="")
    assert isinstance(client, SGLangClient)
    assert client._model == "nemotron-h-30b"
    assert client._base_url == "http://localhost:30000/v1"


def test_routing_via_https_url(monkeypatch):
    monkeypatch.setenv("SGLANG_MODEL", "test-model")
    client = create_client("https://sglang.internal/v1", api_key="")
    assert isinstance(client, SGLangClient)
    assert client._base_url == "https://sglang.internal/v1"


def test_does_not_misroute_adversarial_sglang_names():
    # Model name contains "claude" and "gpt" — the prefix check must win.
    for adversarial in (
        "sglang:claude-reimplementation-7b",
        "sglang:gpt-rep-13b",
        "sglang:gemini-clone-8b",
    ):
        client = create_client(adversarial, api_key="")
        assert isinstance(client, SGLangClient)


def test_default_base_url_used_when_env_unset(monkeypatch):
    monkeypatch.delenv("SGLANG_BASE_URL", raising=False)
    client = create_client("sglang:test", api_key="")
    assert client._base_url == "http://localhost:30000/v1"


def test_env_override_for_base_url(monkeypatch):
    monkeypatch.setenv("SGLANG_BASE_URL", "http://remote.example.com:8080/v1")
    client = create_client("sglang:test", api_key="")
    assert client._base_url == "http://remote.example.com:8080/v1"


def test_existing_vendor_routes_unaffected():
    # Sanity: PR-A's factory change did not break existing routing.
    assert isinstance(create_client("claude-opus-4-7", api_key="k"), AnthropicClient)
    assert isinstance(create_client("gpt-5.4", api_key="k"), OpenAIClient)
    assert isinstance(create_client("gemini-3.1-pro", api_key="k"), GeminiClient)


def test_empty_api_key_becomes_placeholder():
    # SGLang deployments typically don't enforce auth; the OpenAI SDK still
    # requires a truthy api_key, so an empty string is normalised to "EMPTY".
    client = SGLangClient(api_key="", model="x")
    assert client._api_key == "EMPTY"
