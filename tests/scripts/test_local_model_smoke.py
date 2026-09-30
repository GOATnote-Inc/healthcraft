"""The local smoke must exercise real seeded entity IDs and the judge parser."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest

from scripts import local_model_smoke


@pytest.fixture
def client_factory(monkeypatch):
    class Client:
        encounter_id = ""

        def __init__(self, model):
            self.model = model

        def validate_capabilities(self, **kwargs):
            return {
                "model": self.model,
                "family": "nemotron_h_moe" if "nano" in self.model else "gemma3",
            }

        def chat(self, messages, tools=None, **kwargs):
            if tools:
                self.encounter_id = re.search(r"ENC-[A-Z0-9]+", messages[-1]["content"])[0]
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "name": "getEncounterDetails",
                            "arguments": {"encounter_id": self.encounter_id},
                        }
                    ],
                }
            if "nano" in self.model:
                return {"content": self.encounter_id, "tool_calls": []}
            return {
                "content": json.dumps(
                    {
                        "satisfied": "The encounter identifier is ENC-001."
                        in messages[-1]["content"],
                        "evidence": "fixture",
                        "confidence": "high",
                    }
                ),
                "tool_calls": [],
            }

    monkeypatch.setattr(local_model_smoke, "create_client", lambda model, key: Client(model))
    return Client


def test_smoke_executes_a_real_seeded_encounter_and_both_judge_labels(client_factory):
    result = local_model_smoke.run_smoke("ollama:nano", "ollama:medgemma")
    assert result["passed"] is True
    assert result["tool_roundtrip_passed"] is True
    assert result["benchmark_score"] is None
    assert [case["satisfied"] for case in result["judge_sanity_cases"]] == [True, False]


def test_negative_judge_infrastructure_failure_does_not_count_as_correct(
    client_factory, monkeypatch
):
    verdicts = iter(
        [
            SimpleNamespace(satisfied=True, evidence="valid", error=None),
            SimpleNamespace(satisfied=False, evidence="Judge error", error="invalid JSON"),
        ]
    )
    monkeypatch.setattr(
        local_model_smoke,
        "LLMJudge",
        lambda *a, **k: SimpleNamespace(evaluate_criterion=lambda *a: next(verdicts)),
    )
    result = local_model_smoke.run_smoke("ollama:nano", "ollama:medgemma")
    assert result["passed"] is False
    assert result["judge_sanity_cases"][1]["error"] == "invalid JSON"


@pytest.mark.parametrize("stage", ["tool", "final"])
@pytest.mark.parametrize("reason", ["length", "max_tokens", "content_filter"])
def test_incomplete_native_smoke_cannot_pass(client_factory, monkeypatch, stage, reason):
    original = client_factory.chat
    servers = []
    server_factory = local_model_smoke.create_server

    def record_server(world):
        server = server_factory(world)
        servers.append(server)
        return server

    def interrupted_chat(client, messages, tools=None, **kwargs):
        response = original(client, messages, tools=tools, **kwargs)
        if "nano" in client.model and ((stage == "tool") == bool(tools)):
            response["stop_reason"] = reason
        return response

    monkeypatch.setattr(client_factory, "chat", interrupted_chat)
    monkeypatch.setattr(local_model_smoke, "create_server", record_server)
    with pytest.raises(RuntimeError, match="incomplete"):
        local_model_smoke.run_smoke("ollama:nano", "ollama:medgemma")
    if stage == "tool":
        assert servers[0].world_state.audit_log == []
