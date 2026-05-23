"""Tests for healthcraft.rl.config.RewardConfig."""

from __future__ import annotations

import pytest

from healthcraft.rl.config import RewardConfig


def test_defaults_are_verifiable_dominant():
    cfg = RewardConfig()
    assert cfg.w_verifiable == 0.8
    assert cfg.w_judge == 0.2
    assert cfg.w_process == 0.0
    assert cfg.require_verifiable_safety is True
    assert cfg.restraint_prevalence_threshold == 0.9


def test_validation_rejects_out_of_range_weights():
    with pytest.raises(ValueError, match="w_verifiable"):
        RewardConfig(w_verifiable=1.5)
    with pytest.raises(ValueError, match="w_judge"):
        RewardConfig(w_judge=-0.1)


def test_validation_rejects_inverted_clip_range():
    with pytest.raises(ValueError, match="clip_hi"):
        RewardConfig(clip_lo=0.7, clip_hi=0.3)


def test_load_from_yaml(tmp_path):
    p = tmp_path / "reward.yaml"
    p.write_text("w_verifiable: 0.6\nw_judge: 0.4\nw_process: 0.0\n")
    cfg = RewardConfig.load(p)
    assert cfg.w_verifiable == 0.6
    assert cfg.w_judge == 0.4
    # Unset keys keep defaults.
    assert cfg.process_bonus_cap == 0.1


def test_load_unknown_keys_ignored(tmp_path):
    p = tmp_path / "reward.yaml"
    p.write_text("w_verifiable: 0.5\nfuture_field: 42\n")
    cfg = RewardConfig.load(p)
    assert cfg.w_verifiable == 0.5


def test_load_none_returns_defaults():
    cfg = RewardConfig.load(None)
    assert cfg == RewardConfig()


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        RewardConfig.load(tmp_path / "does_not_exist.yaml")
