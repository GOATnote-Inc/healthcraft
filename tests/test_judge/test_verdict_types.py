"""Only JSON booleans can certify criterion satisfaction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from healthcraft.llm import ensemble_judge as ensemble_module
from healthcraft.llm.ensemble_judge import EnsembleJudge
from healthcraft.llm.judge import LLMJudge, _parse_judge_response
from healthcraft.tasks.rubrics import Criterion, VerificationMethod


class _Client:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls = 0

    def chat(self, **_kwargs: object) -> dict:
        self.calls += 1
        if isinstance(self.payload, Exception):
            raise self.payload
        return {"content": json.dumps(self.payload), "tool_calls": []}


def _criterion() -> Criterion:
    return Criterion(
        id="TYPE-001-C01",
        assertion="The required safety action was completed",
        dimension="safety",
        verification=VerificationMethod.LLM_JUDGE,
        safety_critical=True,
    )


@pytest.mark.parametrize("value", ["false", "true", 1, -1, [True], {"satisfied": True}])
@pytest.mark.parametrize("version", ["v1", "v2"])
def test_non_boolean_judge_verdict_cannot_certify_safety(value: object, version: str) -> None:
    judge = LLMJudge(
        _Client({"satisfied": value, "confidence": "high", "evidence": "Synthetic response"}),
        judge_model="gpt-5.4",
        prompt_version=version,
    )

    result = judge.evaluate_criterion(_criterion(), [])

    assert result.satisfied is False
    assert "satisfied must be a boolean" in result.evidence
    assert result.error is not None


@pytest.mark.parametrize("payload", [[], ["satisfied"], True, 1, "satisfied", {}])
def test_valid_json_with_wrong_schema_returns_diagnostic_failure(payload: object) -> None:
    parsed = _parse_judge_response(json.dumps(payload))

    assert parsed["satisfied"] is False
    assert parsed["_parse_failure"] is True
    assert parsed["confidence"] == "low"


@pytest.mark.parametrize("cached_verdict", ["false", "true", 1, [True], None])
def test_non_boolean_ensemble_cache_is_rejudged(
    cached_verdict: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clients: list[_Client] = []

    def factory(*_args: object, **_kwargs: object) -> _Client:
        client = _Client({"satisfied": False, "confidence": "high", "evidence": "Fresh verdict"})
        clients.append(client)
        return client

    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-only")
    monkeypatch.setattr(ensemble_module, "create_client", factory)
    ensemble = EnsembleJudge(
        agent_model="claude-opus-4-7",
        judge_pool=["gpt-5.4", "gemini-3.1-pro-preview"],
        cache_dir=tmp_path,
    )
    criterion = _criterion()
    for model in ensemble.judge_models:
        path = ensemble._cache_path(model, "synthetic-trajectory", criterion.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"prompt_version": "v2", "satisfied": cached_verdict}), encoding="utf-8"
        )

    result = ensemble.evaluate_criterion(criterion, [], "synthetic-trajectory")

    assert result.satisfied is False
    assert result.per_judge == dict.fromkeys(ensemble.judge_models, False)
    assert [client.calls for client in clients] == [1, 1]


def test_judge_runtime_failure_has_typed_error() -> None:
    judge = LLMJudge(_Client(RuntimeError("out of memory")), judge_model="synthetic")

    result = judge.evaluate_criterion(_criterion(), [])

    assert result.satisfied is False
    assert result.error == "RuntimeError: out of memory"
    assert result.evidence.startswith("Judge error:")


@pytest.mark.parametrize("satisfied", [True, False])
def test_valid_judge_verdict_has_no_error(satisfied: bool) -> None:
    judge = LLMJudge(
        _Client({"satisfied": satisfied, "confidence": "high"}), judge_model="synthetic"
    )

    result = judge.evaluate_criterion(_criterion(), [])

    assert result.satisfied is satisfied
    assert result.error is None


@pytest.mark.parametrize("safety_critical", [True, False])
def test_unparseable_affirmation_is_an_error_even_outside_safety(safety_critical: bool) -> None:
    from dataclasses import replace

    class RawClient:
        def chat(self, **_kwargs: object) -> dict:
            return {"content": "The criterion is satisfied."}

    judge = LLMJudge(RawClient(), judge_model="synthetic", prompt_version="v1")

    result = judge.evaluate_criterion(replace(_criterion(), safety_critical=safety_critical), [])

    assert result.error is not None
    assert "parse" in result.error.lower()
    assert result.evidence.startswith("Judge error:")


def test_ensemble_abstains_on_parse_failure_and_retries_without_caching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clients: list[_Client] = []

    def factory(*_args: object, **_kwargs: object) -> _Client:
        client = _Client({"satisfied": "false", "confidence": "high"})
        clients.append(client)
        return client

    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-only")
    monkeypatch.setattr(ensemble_module, "create_client", factory)
    ensemble = EnsembleJudge(
        agent_model="claude-opus-4-7",
        judge_pool=["gpt-5.4", "gemini-3.1-pro-preview"],
        cache_dir=tmp_path,
    )

    failed = ensemble.evaluate_criterion(_criterion(), [], "parse-failure")

    assert failed.n_judges_used == 0
    assert failed.ambiguous is True
    assert not list(tmp_path.rglob("*.json"))

    for client in clients:
        client.payload = {"satisfied": False, "confidence": "high"}
    recovered = ensemble.evaluate_criterion(_criterion(), [], "parse-failure")

    assert recovered.n_judges_used == 2
    assert recovered.satisfied is False
    assert recovered.ambiguous is False
    assert [client.calls for client in clients] == [2, 2]
    assert len(list(tmp_path.rglob("*.json"))) == 2


@pytest.mark.parametrize("cached_verdict", [True, False])
def test_historical_parse_failure_cache_cannot_be_reused(
    cached_verdict: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clients: list[_Client] = []

    def factory(*_args: object, **_kwargs: object) -> _Client:
        client = _Client({"satisfied": False, "confidence": "high"})
        clients.append(client)
        return client

    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-only")
    monkeypatch.setattr(ensemble_module, "create_client", factory)
    ensemble = EnsembleJudge(
        agent_model="claude-opus-4-7",
        judge_pool=["gpt-5.4", "gemini-3.1-pro-preview"],
        cache_dir=tmp_path,
    )
    criterion = _criterion()
    for model in ensemble.judge_models:
        path = ensemble._cache_path(model, "legacy-parse-failure", criterion.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "prompt_version": "v2",
                    "satisfied": cached_verdict,
                    "evidence": f"[{model}/v2] PARSE FAILURE (fail-closed): invalid JSON",
                }
            ),
            encoding="utf-8",
        )

    result = ensemble.evaluate_criterion(criterion, [], "legacy-parse-failure")

    assert result.satisfied is False
    assert result.n_judges_used == 2
    assert [client.calls for client in clients] == [1, 1]
