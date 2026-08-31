# RL training operator runbook

Pre-flight + launch + monitoring for the HealthCraft → Megatron + SGLang +
GRPO/DAPO training run.

> **Score ≠ clinical readiness.** The model trained by this runbook is a
> **research artifact**. The `research_artifact.json` metadata that ships
> alongside every checkpoint enforces this at the API level
> (`healthcraft.rl.artifact.ResearchArtifactMetadata` refuses to construct
> with `deployment_status` set to anything else). Held-out prospective
> physician-blind validation is required before any deployment
> conversation. See [`docs/RL_COUPLING.md`](RL_COUPLING.md).

## 1. Compute provisioning

| Option | Spec | Notes |
|---|---|---|
| Cloud H100 pod | 1× H100 (96 GB) | Direct SSH; use for small / Qwen3 runs |
| Kaggle | 1× RTX Pro 6000 96 GB | Free; max 12 h wall-clock per session |
| Self-hosted 8× H100 | Required for full Nemotron-3-Nano-30B-A3B run | Provision via your cloud's H100 SKU |

For Nemotron-3-Nano-30B-A3B (the recommended hybrid Mamba-2 + MoE policy),
8× H100 is the floor. Qwen3-30B trains on 4× H100. Both work with the
default `configs/rl/slime_grpo.yaml`.

## 2. Software install

```bash
# slime (THUDM/Tsinghua) — the Megatron + SGLang + DAPO orchestrator
git clone --depth 1 https://github.com/THUDM/slime.git
cd slime && pip install -e .

# SGLang ≥ 0.5.6 — the rollout engine
pip install 'sglang[all]>=0.5.6'

# Megatron-LM — provides the policy training backend
git clone --depth 1 https://github.com/NVIDIA/Megatron-LM.git
# (slime picks it up via PYTHONPATH; follow slime's README for the exact glue)

# HealthCraft itself (editable for the env-side adapters)
pip install -e /path/to/healthcraft
```

## 3. Bring up SGLang

```bash
# Set the policy model + base URL; the rl_train.sh wrapper checks both.
export SGLANG_BASE_URL=http://127.0.0.1:30000/v1
export SGLANG_MODEL=nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16

# Launch SGLang with deterministic inference + memory saver
# (required for co-located weight sync).
python -m sglang.launch_server \
    --model-path "$SGLANG_MODEL" \
    --port 30000 \
    --tp 4 \
    --enable-memory-saver \
    --enable-deterministic-inference \
    --max-running-requests 64

# Verify reachable.
curl -fsS "$SGLANG_BASE_URL/models" | jq .
```

## 4. Pre-flight (run on the launch node)

```bash
# Sanity check the env-side surface; no GPU required.
make rl-test        # tests/test_rl/ — 200+ unit + contract tests
make rl-dryrun      # CPU end-to-end smoke (no GPU, no API)
make integrity      # golden replay — Eq.1 evaluation reward byte-identical
make test           # full suite

# The rl_train.sh wrapper additionally:
#   - validates the seed-pool disjoint invariant
#   - verifies SGLang is reachable
#   - aborts on any pre-flight failure (no half-launched run)
```

## 5. Launch

```bash
make rl-train
# or equivalently:
scripts/rl_train.sh configs/rl/slime_grpo.yaml
```

The wrapper writes results under `results/rl/run-<timestamp>/` including:

- `slime.log` — the training trace
- `checkpoints/step-<N>/` — periodic policy snapshots
- `checkpoints/step-<N>/research_artifact.json` — the firewall metadata
- `canaries.jsonl` — anti-Goodhart canary report per logging step

## 6. Canary interpretation

`healthcraft.rl.instrumentation.CanaryReport.any_red()` returns True iff
**any** of these crosses its threshold. Defaults are conservative starting
points; tune for your task suite after the warmup epoch.

| Canary | What it detects | Default threshold |
|---|---|---|
| `degenerate_group_fraction` | DAPO dynamic-sampling rejecting too many groups (signal-starved training) | > 0.5 sustained |
| `restraint_inflation` | Mean drift of high-prevalence (restraint) criteria — Goodhart in progress | > +0.05 vs baseline |
| `kappa_drift` | Cohen's κ between two judges falling — policy exploiting one judge's blind spots | < −0.10 vs baseline |
| `overoptimising` | Proxy reward still rising but held-out eval flat/falling — reward-model peak past (Gao 2023) | True for ≥ 2 consecutive eval steps |

**When a canary fires:**

1. **Halt training.** Do NOT just lower the learning rate and continue —
   the canaries detect *structural* failure modes, not noise.
2. **Audit the latest checkpoint.** Run the eval seed pool through
   `evaluate_task(..., rubric_channel="v10")` and compare against the V8
   baseline. If gold-reward eval has dropped, roll back to the last
   green-canaries checkpoint.
3. **Diagnose.** Restraint inflation → likely a reward-config issue
   (raise `restraint_prevalence_threshold` or add prevalence-discount).
   Kappa drop → judge ensemble disagreement; add a third judge to
   `EnsembleJudge`. Overoptimisation → reduce `epochs` or raise KL clip
   tightness (lower `clip_high`).
4. **Document in `docs/RL_RUN_NOTES.md`** (create if missing). Every
   training run should leave a written triage trail.

## 7. Post-training validation (REQUIRED before any deployment talk)

The whitepaper's score-≠-clinical-readiness firewall is enforced in
`research_artifact.json` but the post-training human work cannot be
automated. Minimum bar:

- **Held-out prospective evaluation.** A physician reviewer scores the
  trained model on tasks **never** included in `seeds_train.txt`. The
  reviewer is blind to model identity (vs Claude / GPT baselines).
- **Reward-hacking audit.** Manually inspect a sample of high-reward
  rollouts. If any are surface-pattern-matching restraint criteria
  without underlying clinical reasoning, the run is invalid.
- **Generalisation check.** Score the trained model on at least one
  out-of-distribution clinical-AI benchmark (Tau2-Bench Retail,
  τ-Bench Medical, BFCL Parallel) — if HealthCraft scores rose but
  OOD scores fell or held flat, the policy did not learn a
  generalisable skill.

A run that does not pass all three is a successful training experiment
producing an artifact suitable only for research analysis — **not** a
deployable model.

## 8. Failure-mode quick reference

| Symptom | Likely cause | Fix |
|---|---|---|
| `SGLang server not reachable at …` (pre-flight) | Server not started, or `SGLANG_BASE_URL` wrong | Re-run §3 |
| `SeedPool failed invariant` (pre-flight) | `seeds_train.txt` and `seeds_eval.txt` overlap | Inspect both files; never let an eval seed leak into train |
| CUDA OOM during rollout | Co-located memory pressure; SGLang not releasing | Set `enable-memory-saver` (slime config) + lower `max_running_requests` |
| Training stalls (>5 min no progress) | Rollout long tail (high `max_turns` × variable latency) | Enable slime's APRIL partial-rollout option |
| `make integrity` fails on a green branch | Eq.1 evaluation reward was disturbed (unintended change) | Bisect; the regression is in the most recent PR — Eq.1 byte-identical is a hard invariant |
| Canaries fire on warmup epoch | Thresholds too tight for the policy's starting distribution | OK to relax thresholds for the warmup; reset to defaults at epoch 1 |
