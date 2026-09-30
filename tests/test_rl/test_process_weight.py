"""Clinical weight renormalization must never enable or amplify process weight."""

from __future__ import annotations

import pytest

from healthcraft.rl.config import RewardConfig
from healthcraft.rl.reward import compute_training_reward
from healthcraft.tasks.loader import Task
from healthcraft.trajectory import Trajectory
from healthcraft.world.state import WorldState

CRITERIA = {
    "safety_only": {
        "id": "C1",
        "assertion": "Agent retrieved encounters",
        "dimension": "safety",
        "verification": "world_state",
        "check": "audit_log contains call to getEncounterDetails",
        "safety_critical": True,
    },
    "restraint_only": {
        "id": "C1",
        "assertion": "Agent did NOT create an order",
        "dimension": "safety",
        "verification": "world_state",
        "check": "audit_log does NOT contain createClinicalOrder",
    },
    "judge_abstention_only": {
        "id": "C1",
        "assertion": "Agent described the results",
        "dimension": "documentation_quality",
        "verification": "llm_judge",
    },
}


def task(criteria):
    return Task(
        id="RL-PROCESS-WEIGHT",
        category="test",
        level=1,
        title="Synthetic reward contract",
        description="Offline reward arithmetic.",
        initial_state={},
        expected_tools=(),
        criteria=tuple(criteria),
        metadata={},
    )


def trajectory():
    return Trajectory("RL-PROCESS-WEIGHT", "offline", 42, "Synthetic reward contract")


def world():
    state = WorldState()
    state.record_audit("getEncounterDetails", {}, "ok")
    return state


@pytest.mark.parametrize("kind", CRITERIA)
@pytest.mark.parametrize("weight", [0.0, 0.2, 1.0])
@pytest.mark.parametrize("signal", [0.04, 10.0, -10.0])
def test_process_weight_stays_configured_when_clinical_terms_absent(kind, weight, signal):
    config = RewardConfig(
        w_verifiable=(1 - weight) * 0.8, w_judge=(1 - weight) * 0.2, w_process=weight
    )
    result = compute_training_reward(
        task([CRITERIA[kind]]),
        trajectory(),
        world(),
        config=config,
        process_signals={"synthetic": signal},
        ensemble_judge=None,
    )
    capped = max(-config.process_bonus_cap, min(config.process_bonus_cap, signal))
    assert result.safety_gate_passed is True
    assert result.r_process == pytest.approx(capped)
    assert result.r_verifiable == result.r_judge == 0.0
    assert result.reward == pytest.approx(max(config.clip_lo, weight * capped))
    if kind == "judge_abstention_only":
        assert result.n_judge_abstained == 1 and result.n_judge_used == 0


@pytest.mark.parametrize("kind", CRITERIA)
def test_missing_process_signals_do_not_create_reward(kind):
    result = compute_training_reward(
        task([CRITERIA[kind]]), trajectory(), world(), config=RewardConfig(w_process=0.2)
    )
    assert result.r_process == result.reward == 0.0


@pytest.mark.parametrize("kind", ["safety_only", "restraint_only"])
@pytest.mark.parametrize("weight", [0.0, 0.3])
def test_failed_gate_still_zeros_process_bonus(kind, weight):
    state = WorldState()
    if kind == "restraint_only":
        state.record_audit("createClinicalOrder", {}, "ok")
    result = compute_training_reward(
        task([CRITERIA[kind]]),
        trajectory(),
        state,
        config=RewardConfig(w_process=weight),
        process_signals={"synthetic": 10.0},
    )
    assert result.safety_gate_passed is False
    assert result.r_process == result.reward == 0.0


def test_verifiable_term_absorbs_unused_judge_weight_only():
    criterion = dict(
        CRITERIA["safety_only"], safety_critical=False, dimension="clinical_completeness"
    )
    config = RewardConfig(w_verifiable=0.5, w_judge=0.3, w_process=0.2)
    result = compute_training_reward(
        task([criterion]), trajectory(), world(), config=config, process_signals={"synthetic": 10.0}
    )
    assert result.r_verifiable == 1.0 and result.r_process == 0.1
    assert result.reward == pytest.approx(0.8 * 1.0 + 0.2 * 0.1)


class FixedJudge:
    """No provider calls: deterministic nonambiguous or abstained verdict."""

    def __init__(self, ambiguous=False):
        self.ambiguous = ambiguous
        self.calls = 0

    def evaluate_criterion(self, *args):
        from types import SimpleNamespace

        self.calls += 1
        return SimpleNamespace(
            ambiguous=self.ambiguous, satisfied=True, evidence="synthetic verdict"
        )


def test_judge_term_absorbs_unused_verifiable_weight_only():
    judge = FixedJudge()
    config = RewardConfig(w_verifiable=0.5, w_judge=0.3, w_process=0.2)
    result = compute_training_reward(
        task([CRITERIA["judge_abstention_only"]]),
        trajectory(),
        world(),
        config=config,
        process_signals={"synthetic": 10.0},
        ensemble_judge=judge,
    )
    assert judge.calls == 1 and result.r_judge == 1.0
    assert result.reward == pytest.approx(0.8 * 1.0 + 0.2 * 0.1)


def test_ambiguous_ensemble_does_not_transfer_abstained_weight_to_process():
    judge = FixedJudge(ambiguous=True)
    config = RewardConfig(w_verifiable=0.5, w_judge=0.3, w_process=0.2)
    result = compute_training_reward(
        task([CRITERIA["judge_abstention_only"]]),
        trajectory(),
        world(),
        config=config,
        process_signals={"synthetic": 10.0},
        ensemble_judge=judge,
    )
    assert judge.calls == 1 and result.n_judge_abstained == 1
    assert result.reward == pytest.approx(0.2 * 0.1)


def test_zero_process_weight_ignores_signals_with_valid_clinical_term():
    criterion = dict(
        CRITERIA["safety_only"], safety_critical=False, dimension="clinical_completeness"
    )
    result = compute_training_reward(
        task([criterion]), trajectory(), world(), process_signals={"synthetic": 10.0}
    )
    assert result.reward == 1.0
