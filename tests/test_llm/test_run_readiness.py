"""Run-readiness locks for the gpt-5.5 / claude-opus-4-8 accounting
(2026-05-31 v11 audit, findings D4-F4 + D4-F6).

Two silent-corruption guards for a multi-hour frontier run:
  * The grading channel must be provable from a trajectory file alone — so
    rubric_channel is now a first-class Trajectory field (D4-F4). Old files
    without it must still load (default "").
  * A 400 / invalid-parameter (e.g. a reasoning model that rejects
    temperature=0) would 400 on EVERY call and silently fill the cache with
    reward=0 error trajectories. Preflight must FAIL LOUD on it, distinctly from
    auth/404, before the run starts (D4-F6 / D4-F1 defense-in-depth).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import healthcraft.llm.agent as agent_mod
from healthcraft.llm.orchestrator import _api_preflight
from healthcraft.trajectory import Trajectory


class TestRubricChannelProvenance:
    def test_rubric_channel_round_trips(self, tmp_path: Path) -> None:
        t = Trajectory(task_id="CR-001", model="claude-opus-4-8", seed=42, system_prompt="x")
        t.rubric_channel = "v10"
        p = t.save(tmp_path / "t.json")
        loaded = Trajectory.load(p)
        assert loaded.rubric_channel == "v10"

    def test_default_is_empty(self) -> None:
        t = Trajectory(task_id="CR-001", model="gpt-5.5", seed=42, system_prompt="x")
        assert t.rubric_channel == ""

    def test_old_trajectory_without_field_still_loads(self, tmp_path: Path) -> None:
        # A pre-existing trajectory JSON has no rubric_channel key — must default,
        # not raise (backward-compatible field addition).
        import json

        p = tmp_path / "old.json"
        p.write_text(
            json.dumps(
                {
                    "task_id": "CR-001",
                    "model": "claude-opus-4-6",
                    "seed": 42,
                    "system_prompt": "x",
                    "turns": [],
                    "criteria_results": [],
                }
            ),
            encoding="utf-8",
        )
        loaded = Trajectory.load(p)
        assert loaded.rubric_channel == ""


class _ChatRaises:
    def __init__(self, message: str) -> None:
        self._message = message

    def chat(self, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError(self._message)


def _patch_client(monkeypatch: pytest.MonkeyPatch, message: str) -> None:
    monkeypatch.setattr(agent_mod, "create_client", lambda *a, **k: _ChatRaises(message))


class TestPreflightFailsLoudOn400:
    @pytest.mark.parametrize(
        "message",
        [
            "Error code: 400 - unsupported parameter: 'temperature'",
            "BadRequest: temperature is not supported for this model",
            "INVALID_ARGUMENT: temperature must be 1 for reasoning models",
        ],
    )
    def test_temperature_or_400_is_hard_fail(
        self, monkeypatch: pytest.MonkeyPatch, message: str
    ) -> None:
        _patch_client(monkeypatch, message)
        with pytest.raises(SystemExit) as exc:
            _api_preflight("gpt-5.5", "k", None, "")
        assert exc.value.code == 2

    def test_transient_still_warns_not_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A generic transient (e.g. a 503) must NOT hard-fail preflight — the
        # eval loop's retry handles it. Guards against over-broad 400 matching.
        _patch_client(monkeypatch, "ServiceUnavailable: 503 upstream connect error")
        _api_preflight("gpt-5.5", "k", None, "")  # returns without SystemExit
