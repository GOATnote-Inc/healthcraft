"""Tests for healthcraft.rl.artifact — research-artifact firewall (PR-D / WS-6)."""

from __future__ import annotations

import json

import pytest

from healthcraft.rl.artifact import (
    ResearchArtifactMetadata,
    verify_research_artifact,
)


def _valid_kwargs():
    return {
        "base_model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16",
        "trained_against": "healthcraft_v8",
        "training_run_id": "run-20260523-094500",
    }


# ---------------------------------------------------------------------------
# Firewall enforcement at construction time
# ---------------------------------------------------------------------------


def test_default_deployment_status_is_research_artifact():
    m = ResearchArtifactMetadata(**_valid_kwargs())
    assert m.deployment_status == "research_artifact"


def test_refuses_to_construct_with_alternate_deployment_status():
    """The firewall is the whole point — refuse any other value."""
    with pytest.raises(ValueError, match="research_artifact"):
        ResearchArtifactMetadata(
            **_valid_kwargs(),
            deployment_status="production",
        )
    with pytest.raises(ValueError, match="research_artifact"):
        ResearchArtifactMetadata(
            **_valid_kwargs(),
            deployment_status="",
        )


def test_requires_base_model():
    kwargs = _valid_kwargs()
    kwargs["base_model"] = ""
    with pytest.raises(ValueError, match="base_model"):
        ResearchArtifactMetadata(**kwargs)


def test_requires_trained_against():
    kwargs = _valid_kwargs()
    kwargs["trained_against"] = ""
    with pytest.raises(ValueError, match="trained_against"):
        ResearchArtifactMetadata(**kwargs)


def test_requires_training_run_id():
    kwargs = _valid_kwargs()
    kwargs["training_run_id"] = ""
    with pytest.raises(ValueError, match="training_run_id"):
        ResearchArtifactMetadata(**kwargs)


def test_refuses_tampered_score_disclaimer():
    """The canonical firewall text cannot be quietly weakened."""
    with pytest.raises(ValueError, match="score_disclaimer"):
        ResearchArtifactMetadata(
            **_valid_kwargs(),
            score_disclaimer="HealthCraft scores are great evidence!",
        )


# ---------------------------------------------------------------------------
# Save / load round-trip
# ---------------------------------------------------------------------------


def test_save_and_load_roundtrip(tmp_path):
    original = ResearchArtifactMetadata(
        **_valid_kwargs(),
        reward_config="configs/rl/reward.yaml",
        seed_pool_train=(43, 44, 45),
        seed_pool_eval=(42, 1000001),
        notes="smoke",
    )
    target = tmp_path / "research_artifact.json"
    original.save(target)
    loaded = ResearchArtifactMetadata.load(target)
    assert loaded.base_model == original.base_model
    assert loaded.trained_against == original.trained_against
    assert loaded.training_run_id == original.training_run_id
    assert loaded.seed_pool_train == (43, 44, 45)
    assert loaded.seed_pool_eval == (42, 1000001)


def test_save_to_directory_creates_file(tmp_path):
    m = ResearchArtifactMetadata(**_valid_kwargs())
    target_dir = tmp_path / "ckpt-step-1000"
    target_dir.mkdir()
    saved = m.save(target_dir)
    assert saved == target_dir / "research_artifact.json"
    assert saved.exists()


def test_load_from_directory(tmp_path):
    m = ResearchArtifactMetadata(**_valid_kwargs())
    target_dir = tmp_path / "ckpt"
    target_dir.mkdir()
    m.save(target_dir)
    loaded = ResearchArtifactMetadata.load(target_dir)
    assert loaded.deployment_status == "research_artifact"


# ---------------------------------------------------------------------------
# verify_research_artifact — silent-on-failure semantics
# ---------------------------------------------------------------------------


def test_verify_returns_true_on_valid_checkpoint(tmp_path):
    m = ResearchArtifactMetadata(**_valid_kwargs())
    m.save(tmp_path / "research_artifact.json")
    assert verify_research_artifact(tmp_path / "research_artifact.json") is True


def test_verify_returns_false_on_missing_file(tmp_path):
    assert verify_research_artifact(tmp_path / "does-not-exist.json") is False


def test_verify_returns_false_on_tampered_status(tmp_path):
    """If someone hand-edits the JSON to flip deployment_status,
    verify_research_artifact returns False (downstream tooling refuses)."""
    valid = ResearchArtifactMetadata(**_valid_kwargs())
    path = tmp_path / "research_artifact.json"
    valid.save(path)
    # Hand-edit to flip the status.
    data = json.loads(path.read_text(encoding="utf-8"))
    data["deployment_status"] = "production"
    path.write_text(json.dumps(data), encoding="utf-8")
    # Load should raise; verify_research_artifact catches and returns False.
    assert verify_research_artifact(path) is False


def test_verify_returns_false_on_corrupt_json(tmp_path):
    path = tmp_path / "research_artifact.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert verify_research_artifact(path) is False
