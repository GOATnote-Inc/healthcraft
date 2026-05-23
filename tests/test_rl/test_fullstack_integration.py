"""Full-stack integration tests — PR-A through PR-D wired together (PR-E).

Each prior PR ships its own unit + contract tests. This file is the
**cross-PR** test: one rollout that exercises every layer at once.

What the integration drives end-to-end:

- PR-A: env contract + verifiable-anchored training reward.
- PR-B: idempotent retried mutation + fault injection + process signals.
- PR-C: closed-loop physiology (`world/transition.py`) reflecting agent
  actions in `get_current_vitals`.
- PR-D: research-artifact firewall + canary report aggregation.

A regression here means the env-side stack the slime training loop will
call has lost an integration contract — the trainer's first rollout
would have failed too.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from healthcraft.entities.base import EntityType
from healthcraft.entities.encounters import Encounter, ESILevel
from healthcraft.entities.patients import Patient
from healthcraft.mcp.faults import FaultProfile
from healthcraft.rl.artifact import (
    ResearchArtifactMetadata,
    verify_research_artifact,
)
from healthcraft.rl.env import HealthCraftEnv
from healthcraft.rl.instrumentation import (
    CanaryReport,
    degenerate_group_fraction,
    group_reward_variance,
)
from healthcraft.rl.process_signals import process_signals_from_audit_log
from healthcraft.rl.reward import compute_training_reward
from healthcraft.tasks.loader import Task
from healthcraft.world.physiology import stable_improving_trajectory

# ---------------------------------------------------------------------------
# Stub policy + fixture helpers
# ---------------------------------------------------------------------------


class StubPolicyClient:
    """Deterministic ModelClient stub emitting a programmed script."""

    def __init__(self, script: list[dict[str, Any]], model: str = "stub-fullstack") -> None:
        self._script = list(script)
        self._idx = 0
        self._model = model

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        if self._idx >= len(self._script):
            return {"content": "", "tool_calls": [], "stop_reason": "stop"}
        r = self._script[self._idx]
        self._idx += 1
        return r


def _populate_septic_patient(world, patient_id: str, encounter_id: str) -> None:
    """Attach a patient + encounter + stable-improving physiology trajectory.

    Uses ``stable_improving_trajectory`` so the base BP curve is slowly
    *rising* — that means any observed BP delta we attribute to the
    vasopressor cannot be inflated by background deterioration.
    """
    now = datetime.now(timezone.utc)
    patient = Patient(
        id=patient_id,
        entity_type=EntityType.PATIENT,
        created_at=now,
        updated_at=now,
        mrn="MRN-FULLSTACK",
        first_name="Test",
        last_name="Fullstack",
        sex="M",
        allergies=(),
        medications=(),
    )
    world.put_entity("patient", patient_id, patient)

    enc = Encounter(
        id=encounter_id,
        entity_type=EntityType.ENCOUNTER,
        created_at=now,
        updated_at=now,
        patient_id=patient_id,
        chief_complaint="septic shock; persistent hypotension despite fluids",
        esi_level=ESILevel.EMERGENT,
    )
    world.put_entity("encounter", encounter_id, enc)

    trajectory = stable_improving_trajectory(world_seed=42, patient_id=patient_id)
    world.attach_physiology(patient_id, trajectory)


def _task_for_septic_order(encounter_id: str) -> Task:
    """A task whose verifiable criterion is satisfied by a vasopressor order
    for the given encounter (no safety violations, no judge criteria)."""
    return Task(
        id="INTEG-001",
        category="multi_step_workflows",
        level=4,
        title="Integration: vasopressor for septic shock",
        description="Persistent hypotension despite fluids — escalate.",
        initial_state={},
        expected_tools=(),
        criteria=(
            {
                "id": "INTEG-001-C1",
                "assertion": "Agent ordered a vasopressor",
                "dimension": "clinical_correctness",
                "verification": "world_state",
                "check": "audit_log contains call to createClinicalOrder for medication",
            },
            {
                "id": "INTEG-001-C2",
                "assertion": "Agent did NOT order any blood product transfusion without a documented indication",
                "dimension": "safety",
                "verification": "world_state",
                "check": "audit_log does NOT contain createClinicalOrder for blood_product",
                "safety_critical": True,
            },
        ),
        metadata={"purpose": "fullstack_integration"},
    )


def _vasopressor_script(encounter_id: str) -> list[dict[str, Any]]:
    """Order norepinephrine with an idempotency_key, then *retry* the
    same order (same key) — the env should dedup the second."""
    args = {
        "encounter_id": encounter_id,
        "order_type": "medication",
        "details": {"medication": "norepinephrine 8 mcg/min"},
        "idempotency_key": "fullstack-vaso-1",
    }
    return [
        {
            "content": "",
            "tool_calls": [{"id": "c1", "name": "createClinicalOrder", "arguments": args}],
            "stop_reason": "tool_calls",
        },
        # Logical retry under the same idempotency_key.
        {
            "content": "",
            "tool_calls": [{"id": "c2", "name": "createClinicalOrder", "arguments": args}],
            "stop_reason": "tool_calls",
        },
        {"content": "Vasopressor initiated.", "tool_calls": [], "stop_reason": "stop"},
    ]


# ---------------------------------------------------------------------------
# Cross-PR contracts
# ---------------------------------------------------------------------------


def test_fullstack_vasopressor_drives_closed_loop_via_env_rollout():
    """The headline integration: a vasopressor order placed through
    env.rollout (with idempotency, faults configured, closed-loop physiology
    on) raises the patient's BP, dedups the retry, and yields a non-zero
    training reward with the safety gate passing.

    This is the single test that proves PR-A, PR-B, PR-C wire together;
    if it regresses, the slime training loop's first rollout would also
    have failed.
    """
    task = _task_for_septic_order("ENC-T")
    profile = FaultProfile(
        seed=42,
        latency_mean_minutes=2.0,  # advances sim clock — gives action effects time to ramp
        transient_failure_rate=0.0,
        retry_budget=5,
    )
    env = HealthCraftEnv(
        world_config_path=None,
        dynamic_state_enabled=True,
        fault_profile=profile,
    )
    env.reset(task=task, episode_seed=42, system_prompt="You are an attending.")
    assert env.world is not None
    _populate_septic_patient(env.world, "PAT-T", "ENC-T")

    # Baseline BP BEFORE any action has been recorded (audit log empty
    # except for any setup — none here).
    baseline = env.world.get_current_vitals("PAT-T")
    assert baseline is not None
    baseline_sbp = baseline.systolic_bp

    # Drive the rollout.
    result = env.rollout(StubPolicyClient(_vasopressor_script("ENC-T")))
    assert result.error is None
    assert result.task_id == "INTEG-001"

    # PR-C contract: closed-loop physiology applied the vasopressor delta.
    post = env.world.get_current_vitals("PAT-T")
    assert post is not None
    assert post.systolic_bp > baseline_sbp, (
        f"closed-loop physiology should have raised BP — baseline={baseline_sbp}, "
        f"post-vasopressor={post.systolic_bp}"
    )

    # PR-B contract: the audit log records BOTH attempts under the same
    # idempotency_key, and the second carries deduplicated=True.
    vaso_entries = [e for e in env.world.audit_log if e.idempotency_key == "fullstack-vaso-1"]
    assert len(vaso_entries) == 2
    assert [e.attempt_number for e in vaso_entries] == [1, 2]
    assert vaso_entries[1].deduplicated is True

    # PR-B contract: process signals from the audit log surface the safe-retry
    # pattern (idempotency_key bonus + deduplicated_replay bonus).
    signals = process_signals_from_audit_log(env.world.audit_log)
    assert signals.get("idempotency_key_on_retry", 0.0) > 0.0
    assert signals.get("deduplicated_replay", 0.0) > 0.0
    assert "missing_idempotency_key_on_retry" not in signals

    # PR-A contract: compute_training_reward consumes the trajectory, world,
    # and process signals and returns a clipped scalar with safety gate
    # passing (no blood product was ordered).
    reward = compute_training_reward(
        task,
        result.trajectory,
        env.world,
        process_signals=signals,
    )
    assert reward.safety_gate_passed is True
    assert 0.0 <= reward.reward <= 1.0
    assert reward.reward > 0.0  # the verifiable criterion is satisfied


def test_fullstack_fault_injector_installed_and_advances_clock():
    """The FaultInjector must be wrapped onto server.call_tool and must
    move the simulated clock (no real sleep)."""
    profile = FaultProfile(seed=7, latency_mean_minutes=3.0)
    env = HealthCraftEnv(
        world_config_path=None,
        dynamic_state_enabled=True,
        fault_profile=profile,
    )
    env.reset(
        task=_task_for_septic_order("ENC-T"),
        episode_seed=7,
        system_prompt="x",
    )
    assert env.fault_injector is not None  # PR-B / PR-E wiring
    _populate_septic_patient(env.world, "PAT-T", "ENC-T")
    t_before = env.world.timestamp

    # One simple tool call. The injector should advance the sim clock by
    # ~3 minutes (mean latency).
    stub = StubPolicyClient(
        [
            {
                "content": "",
                "tool_calls": [{"id": "c1", "name": "searchPatients", "arguments": {}}],
                "stop_reason": "tool_calls",
            },
            {"content": "done.", "tool_calls": [], "stop_reason": "stop"},
        ]
    )
    env.rollout(stub)

    elapsed_minutes = (env.world.timestamp - t_before).total_seconds() / 60.0
    assert elapsed_minutes >= 2.0  # at least one ~3-min latency injection fired


def test_fullstack_canary_report_clean_on_synthetic_batch():
    """A 4-rollout batch with mixed rewards produces a CanaryReport
    that does NOT fire any threshold (the normal-state case)."""
    group = [
        group_reward_variance([0.8, 0.5, 0.7, 0.6]),
        group_reward_variance([0.5, 0.9, 0.4, 0.7]),
        group_reward_variance([0.6, 0.6, 0.8, 0.5]),
        group_reward_variance([0.3, 0.7, 0.5, 0.6]),
    ]
    report = CanaryReport(
        step=1,
        degenerate_group_fraction=degenerate_group_fraction(group),
        restraint_inflation=0.01,  # well below the 0.05 threshold
        kappa_drift=-0.02,  # well above the -0.10 threshold
        overoptimising=False,
    )
    assert report.any_red() is False


def test_fullstack_research_artifact_firewall(tmp_path: Path):
    """A trained-checkpoint metadata file save/load round-trips, and
    a tampered copy fails verification — the API-level firewall holds
    in an end-to-end checkpoint scenario."""
    ckpt_dir = tmp_path / "step-1000"
    ckpt_dir.mkdir()

    md = ResearchArtifactMetadata(
        base_model="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16",
        trained_against="healthcraft_v8",
        training_run_id="run-fullstack-1",
        reward_config="configs/rl/reward.yaml",
        seed_pool_train=tuple(range(43, 53)),
        seed_pool_eval=(42, 1000001, 1000002),
    )
    md.save(ckpt_dir)
    assert verify_research_artifact(ckpt_dir) is True

    # Tamper: flip deployment_status on disk to "production".
    import json as _json

    target = ckpt_dir / "research_artifact.json"
    data = _json.loads(target.read_text(encoding="utf-8"))
    data["deployment_status"] = "production"
    target.write_text(_json.dumps(data), encoding="utf-8")
    assert verify_research_artifact(ckpt_dir) is False
