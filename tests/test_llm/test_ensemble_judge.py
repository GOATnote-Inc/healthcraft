"""Tests for the multi-judge ensemble.

All tests use stub clients via monkeypatch — no real API calls. Coverage:

- Same-vendor filter (agent-vendor judge skipped, not instantiated)
- Supermajority voting (2-of-3 True, 2-of-3 False, unanimous)
- Ambiguity when only 2 judges remain and they split 1-1
- Refusal when the filtered pool is smaller than ``min_agreement``
- Per-judge caching (cache hit skips API)
- Missing-API-key loud failure
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from healthcraft.llm import ensemble_judge as ej_module
from healthcraft.llm.ensemble_judge import EnsembleJudge
from healthcraft.tasks.rubrics import Criterion, VerificationMethod

# ---------------------------------------------------------------------------
# Stub infrastructure
# ---------------------------------------------------------------------------


class FakeClient:
    """Minimal ModelClient stub.

    Returns a deterministic planned verdict each time ``chat`` is called,
    and counts invocations so tests can assert cache-hit behavior.
    """

    def __init__(self, planned_verdict: bool, model: str) -> None:
        self.planned_verdict = planned_verdict
        self.model = model
        self.call_count = 0

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        self.call_count += 1
        payload = {
            "satisfied": self.planned_verdict,
            "evidence": f"stub-evidence-{self.model}",
            "confidence": "high",
        }
        return {
            "content": json.dumps(payload),
            "tool_calls": [],
            "stop_reason": "stop",
        }


def _install_fake_clients(
    monkeypatch: pytest.MonkeyPatch,
    verdicts: dict[str, bool],
) -> dict[str, FakeClient]:
    """Patch ``create_client`` in the ensemble module.

    ``verdicts`` maps model id -> planned verdict. Returns the dict of
    created fakes so tests can assert ``call_count`` per judge model.
    """
    created: dict[str, FakeClient] = {}

    def _factory(model: str, api_key: str) -> FakeClient:  # noqa: ARG001
        if model not in verdicts:
            raise AssertionError(
                f"FakeClient was asked to instantiate an unexpected model: {model!r}. "
                f"Configured models: {list(verdicts)}."
            )
        client = FakeClient(planned_verdict=verdicts[model], model=model)
        created[model] = client
        return client

    monkeypatch.setattr(ej_module, "create_client", _factory)
    return created


def _set_all_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-anthropic")
    monkeypatch.setenv("GOOGLE_API_KEY", "sk-fake-google")
    monkeypatch.setenv("XAI_API_KEY", "sk-fake-xai")


def _criterion(
    crit_id: str = "CR-TEST-C01",
    assertion: str = "Agent did the thing",
    safety_critical: bool = False,
) -> Criterion:
    return Criterion(
        id=crit_id,
        assertion=assertion,
        dimension="clinical_completeness",
        verification=VerificationMethod.LLM_JUDGE,
        check="",
        safety_critical=safety_critical,
    )


def _trajectory() -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "I did the thing.", "tool_calls": []},
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_skips_same_vendor_judge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Agent claude -> claude-opus-4-7 judge is filtered, never instantiated."""
    _set_all_keys(monkeypatch)
    fakes = _install_fake_clients(
        monkeypatch,
        {"gpt-5.4": True, "gemini-3.1-pro": True},
    )

    ensemble = EnsembleJudge(
        agent_model="claude-opus-4-7",
        cache_dir=tmp_path,
    )

    assert ensemble.judge_models == ["gpt-5.4", "gemini-3.1-pro"]
    # claude-opus-4-7 must NOT have been instantiated (pre-check)
    assert "claude-opus-4-7" not in fakes

    result = ensemble.evaluate_criterion(_criterion(), _trajectory(), trajectory_id="traj-001")
    assert result.n_judges_used == 2
    assert set(result.per_judge) == {"gpt-5.4", "gemini-3.1-pro"}


def test_supermajority_true_2_of_3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """[True, True, False] -> satisfied=True, agreement ~= 0.667."""
    _set_all_keys(monkeypatch)
    _install_fake_clients(
        monkeypatch,
        {"gpt-5.4": True, "claude-opus-4-7": True, "gemini-3.1-pro": False},
    )

    ensemble = EnsembleJudge(agent_model="grok-4", cache_dir=tmp_path)
    result = ensemble.evaluate_criterion(_criterion(), _trajectory(), trajectory_id="traj-001")

    assert result.satisfied is True
    assert result.n_judges_used == 3
    assert result.agreement_score == pytest.approx(2 / 3, rel=1e-6)
    assert result.ambiguous is False


def test_supermajority_false_2_of_3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """[False, False, True] -> satisfied=False, agreement ~= 0.667."""
    _set_all_keys(monkeypatch)
    _install_fake_clients(
        monkeypatch,
        {"gpt-5.4": False, "claude-opus-4-7": False, "gemini-3.1-pro": True},
    )

    ensemble = EnsembleJudge(agent_model="grok-4", cache_dir=tmp_path)
    result = ensemble.evaluate_criterion(_criterion(), _trajectory(), trajectory_id="traj-001")

    assert result.satisfied is False
    assert result.agreement_score == pytest.approx(2 / 3, rel=1e-6)
    assert result.ambiguous is False


def test_unanimous_true(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """[True, True, True] -> agreement_score == 1.0."""
    _set_all_keys(monkeypatch)
    _install_fake_clients(
        monkeypatch,
        {"gpt-5.4": True, "claude-opus-4-7": True, "gemini-3.1-pro": True},
    )

    ensemble = EnsembleJudge(agent_model="grok-4", cache_dir=tmp_path)
    result = ensemble.evaluate_criterion(_criterion(), _trajectory(), trajectory_id="traj-001")

    assert result.satisfied is True
    assert result.agreement_score == 1.0
    assert result.ambiguous is False


def test_ambiguous_with_2_judges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Agent claude; gpt=True, gemini=False -> 1-1 split, ambiguous=True."""
    _set_all_keys(monkeypatch)
    _install_fake_clients(
        monkeypatch,
        {"gpt-5.4": True, "gemini-3.1-pro": False},
    )

    ensemble = EnsembleJudge(
        agent_model="claude-opus-4-7",
        cache_dir=tmp_path,
    )
    result = ensemble.evaluate_criterion(_criterion(), _trajectory(), trajectory_id="traj-001")

    assert result.n_judges_used == 2
    # 1 True, 1 False: falls below min_agreement=2 either way
    assert result.satisfied is False
    assert result.agreement_score == pytest.approx(0.5, rel=1e-6)
    assert result.ambiguous is True


def test_raises_if_too_few_judges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pool = [gpt-5.4] with agent gpt-5.4 -> zero judges -> ValueError."""
    _set_all_keys(monkeypatch)
    # No _install_fake_clients here — constructor should raise before any
    # client would be created.

    with pytest.raises(ValueError, match="min_agreement"):
        EnsembleJudge(
            agent_model="gpt-5.4",
            judge_pool=["gpt-5.4"],
            cache_dir=tmp_path,
        )


def test_cache_hit_skips_api_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Second evaluate_criterion call reuses cached per-judge verdicts."""
    _set_all_keys(monkeypatch)
    fakes = _install_fake_clients(
        monkeypatch,
        {"gpt-5.4": True, "claude-opus-4-7": True, "gemini-3.1-pro": False},
    )

    ensemble = EnsembleJudge(agent_model="grok-4", cache_dir=tmp_path)

    crit = _criterion()
    r1 = ensemble.evaluate_criterion(crit, _trajectory(), trajectory_id="traj-X")
    # After first call, each fake client was invoked exactly once.
    for model, client in fakes.items():
        assert client.call_count == 1, f"{model} should have been called once"

    # Second call with identical (trajectory_id, criterion_id) — cache HIT.
    r2 = ensemble.evaluate_criterion(crit, _trajectory(), trajectory_id="traj-X")

    for model, client in fakes.items():
        assert client.call_count == 1, (
            f"{model} should NOT have been called again (got {client.call_count})"
        )

    # Verdicts must be identical across calls.
    assert r1.satisfied == r2.satisfied
    assert r1.per_judge == r2.per_judge
    assert r1.agreement_score == r2.agreement_score


def test_missing_api_key_raises_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dropping OPENAI_API_KEY -> RuntimeError mentioning OPENAI_API_KEY."""
    # Set the other keys but REMOVE openai.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-anthropic")
    monkeypatch.setenv("GOOGLE_API_KEY", "sk-fake-google")
    monkeypatch.setenv("XAI_API_KEY", "sk-fake-xai")

    # Patch create_client so that if we DID get past the key check, we'd
    # fail loudly instead of making real API calls.
    _install_fake_clients(
        monkeypatch,
        {"gpt-5.4": True, "claude-opus-4-7": True, "gemini-3.1-pro": True},
    )

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        EnsembleJudge(agent_model="grok-4", cache_dir=tmp_path)
