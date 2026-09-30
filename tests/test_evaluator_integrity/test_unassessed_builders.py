"""Release builders must reject explicitly unassessed experimental inputs."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_BUILDERS = ("build_hard", "build_consensus", "propose_overlay_entries")
_MARKERS = (
    {"metadata": {"scenario_profile": "task-roster-source-v1"}},
    {"evaluation_mode": "profile_diagnostic"},
    {"metadata": {"grading_complete": False}},
)


def _module(name):
    module_name = f"_unassessed_{name}"
    spec = importlib.util.spec_from_file_location(module_name, _ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _write(root, trial=1, **overrides):
    path = root / "trajectories" / f"IR-001_test-model_42_t{trial}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "task_id": "IR-001",
        "model": "test-model",
        "seed": 42,
        "reward": 0.0,
        "passed": False,
        "safety_gate_passed": False,
        "turns": [],
        "criteria_results": [],
        **overrides,
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, data


def _load(module, name, root, path):
    if name == "build_hard":
        return module._load_trajectory(path, exclude_error=True)
    if name == "build_consensus":
        return module._load_trajectory(path)
    return module._collect_trajectories([root])


def _task():
    return SimpleNamespace(
        id="IR-001",
        category="information_retrieval",
        criteria=(
            {
                "id": "IR-001-C01",
                "assertion": "Retrieved the intended source facts",
                "verification": "llm_judge",
                "dimension": "clinical_completeness",
            },
        ),
    )


def _fake_ensemble(module, monkeypatch):
    evaluate = Mock(
        return_value=SimpleNamespace(
            per_judge={"judge-a": False, "judge-b": False, "judge-c": False},
            agreement_score=1.0,
            satisfied=False,
        )
    )
    construct = Mock(
        return_value=SimpleNamespace(
            judge_models=["judge-a", "judge-b", "judge-c"], evaluate_criterion=evaluate
        )
    )
    monkeypatch.setattr(module, "EnsembleJudge", construct)
    return construct, evaluate


@pytest.mark.parametrize("name", _BUILDERS)
@pytest.mark.parametrize("marker", _MARKERS)
@pytest.mark.parametrize("error", [None, "provider interrupted"])
def test_loaders_reject_unassessed_before_error_or_zero_reward_filtering(
    tmp_path, name, marker, error
):
    module = _module(name)
    path, _ = _write(tmp_path, **marker, error=error)
    with pytest.raises(ValueError, match="(?i)unassessed") as exc:
        _load(module, name, tmp_path, path)
    assert str(path) in str(exc.value)


@pytest.mark.parametrize("name", _BUILDERS)
def test_unflagged_legacy_zero_reward_is_still_accepted(tmp_path, name):
    module = _module(name)
    path, data = _write(tmp_path)
    result = _load(module, name, tmp_path, path)
    if name == "build_hard":
        assert result == (data, "ok")
    elif name == "build_consensus":
        assert result == data
    else:
        assert result == [(path, data)]


@pytest.mark.parametrize("limit", [None, 1])
def test_consensus_preflights_all_selected_inputs_before_any_judge(tmp_path, monkeypatch, limit):
    module = _module("build_consensus")
    valid, _ = _write(tmp_path)
    unassessed, _ = _write(tmp_path, trial=2, **_MARKERS[0])
    construct, evaluate = _fake_ensemble(module, monkeypatch)
    with pytest.raises(ValueError, match="(?i)unassessed"):
        module._collect_verdicts(
            [valid, unassessed], {_task().id: _task()}, tmp_path / "cache", False, limit
        )
    construct.assert_not_called()
    evaluate.assert_not_called()
    assert not (tmp_path / "cache").exists()


@pytest.mark.parametrize("name", _BUILDERS)
def test_cli_returns_two_before_writing_outputs(tmp_path, monkeypatch, capsys, name):
    module = _module(name)
    _write(tmp_path)
    unassessed, _ = _write(tmp_path, trial=2, **_MARKERS[0])
    monkeypatch.setattr(module, "load_tasks", lambda _: [_task()])
    output = tmp_path / "output.jsonl"
    output.write_text("existing output remains unchanged", encoding="utf-8")
    argv = ["--results", str(tmp_path), "--output", str(output)]
    if name == "propose_overlay_entries":
        monkeypatch.setattr(module, "_load_candidate_ids", lambda *_: [("IR-001-C01", "generic")])
        emit = Mock()
        monkeypatch.setattr(module, "_emit_v11_overlay", emit)
        argv.append("--dry-run")
    else:
        emit = Mock()
        monkeypatch.setattr(module, "_emit_jsonl", emit)
        monkeypatch.setattr(module, "_emit_manifest", Mock())
        if name == "build_consensus":
            construct, evaluate = _fake_ensemble(module, monkeypatch)
    assert module.main(argv) == 2
    stderr = capsys.readouterr().err
    assert "unassessed" in stderr.lower()
    assert str(unassessed) in stderr
    emit.assert_not_called()
    assert output.read_text(encoding="utf-8") == "existing output remains unchanged"
    if name == "build_consensus":
        construct.assert_not_called()
        evaluate.assert_not_called()


def test_overlay_empty_candidate_shortcut_still_rejects_flagged_inputs(tmp_path, monkeypatch):
    module = _module("propose_overlay_entries")
    _write(tmp_path, **_MARKERS[0])
    monkeypatch.setattr(module, "_load_candidate_ids", lambda *_: [])
    emit = Mock()
    monkeypatch.setattr(module, "_emit_v11_overlay", emit)
    assert module.main(["--results", str(tmp_path), "--dry-run"]) == 2
    emit.assert_not_called()
