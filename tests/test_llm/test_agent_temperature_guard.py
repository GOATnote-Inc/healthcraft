"""Anthropic temperature-parameter guard (2026-05-31 v11 audit, finding D4-F1).

Opus 4.7+ deprecated `temperature` (the API returns 400 if it is sent). The
guard used to be a literal ``"4-7" not in model`` substring test, so
claude-opus-4-8 / 4-9 still SENT temperature → 400 → the orchestrator caught the
exception and cached a reward=0 error trajectory for EVERY task, silently grading
the headline model as all-zeros (and resume re-cached it with no retry).

These lock the version-family behaviour:
  * Opus >= 4.7 (4-7/4-8/4-9/4-10/5-x) must OMIT temperature.
  * Opus <= 4.6 and non-Opus Claude (sonnet/haiku) must KEEP sending it —
    omitting it there would fall back to the API-default temperature and break
    deterministic (temperature=0) replay.
The send-path is verified by capturing the kwargs handed to the SDK (no network).
"""

from __future__ import annotations

from typing import Any

import pytest

from healthcraft.llm.agent import AnthropicClient, _claude_omits_temperature


class _CaptureMessages:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs

        class _Block:
            type = "text"
            text = "ok"

        class _Resp:
            content = [_Block()]
            stop_reason = "end_turn"

        return _Resp()


def _sends_temperature(model: str) -> bool:
    client = AnthropicClient(api_key="x", model=model)
    msgs = _CaptureMessages()

    class _Client:
        messages = msgs

    client._client = _Client()  # type: ignore[attr-defined]
    client.chat(messages=[{"role": "user", "content": "hi"}], temperature=0.0)
    return "temperature" in msgs.kwargs


class TestClaudeOmitsTemperatureHelper:
    @pytest.mark.parametrize(
        "model",
        [
            "claude-opus-4-7",
            "claude-opus-4-8",
            "claude-opus-4-9",
            "claude-opus-4-10",
            "claude-opus-5-0",
        ],
    )
    def test_opus_4_7_plus_omits(self, model: str) -> None:
        assert _claude_omits_temperature(model) is True

    @pytest.mark.parametrize(
        "model",
        ["claude-opus-4-6", "claude-opus-4-0", "claude-sonnet-4-7", "claude-haiku-4-5", "gpt-5.5"],
    )
    def test_pre_4_7_and_non_opus_keep(self, model: str) -> None:
        assert _claude_omits_temperature(model) is False

    def test_dated_suffix_still_classified(self) -> None:
        assert _claude_omits_temperature("claude-opus-4-8-20260515") is True
        assert _claude_omits_temperature("claude-opus-4-6-20251101") is False


class TestSendPath:
    @pytest.mark.parametrize("model", ["claude-opus-4-7", "claude-opus-4-8", "claude-opus-4-9"])
    def test_opus_4_7_plus_does_not_send_temperature(self, model: str) -> None:
        # The bug: 4-8/4-9 used to send temperature -> 400 -> all-zeros run.
        assert _sends_temperature(model) is False, f"{model} must NOT send temperature (API 400)"

    @pytest.mark.parametrize("model", ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"])
    def test_accepting_models_still_send_temperature(self, model: str) -> None:
        # Determinism guard: these must keep sending temperature=0.
        assert _sends_temperature(model) is True, (
            f"{model} must keep sending temperature for temp=0 replay"
        )
