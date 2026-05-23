# HealthCraft → Megatron + SGLang + GRPO coupling

Design document for the env-side coupling that makes the whitepaper sentence
*"We scaffold the coupling to a Megatron+SGLang+GRPO loop per Corecraft §5.2"*
**concrete**, with a training-reward design that responds to the whitepaper's
training-reward-ablations future-work list (`§sec:limits`).
Implementation lives under `src/healthcraft/rl/`.

> **Score ≠ clinical readiness.** A policy trained against HealthCraft is a
> research artifact. A strong HealthCraft training score does NOT constitute
> evidence of clinical readiness. Held-out prospective validation by a
> physician reviewer blind to model identity is required before any
> deployment conversation. This is non-negotiable; the rest of this doc
> assumes it.

> **Empirical training-safety remains future work.** The whitepaper names
> three items still open: soft-gate/hard-gate ablation, restraint-criterion
> reweighting, reward-hacking probes. This PR delivers *design* and
> *contract*. It does **not** deliver any of those experiments, and the
> mere existence of `compute_training_reward` is not endorsement of
> training-safety for any task suite. The function is a research
> implementation of one design among many that could close the
> evaluation-to-training boundary.

## Why a separate training reward

HealthCraft's Eq. 1 evaluation reward (`tasks/rubrics.py:compute_reward` —
the unweighted mean of binary criteria, gated by safety) is the right
**evaluation** reward. The whitepaper (`docs/whitepaper/content.tex`
§sec:limits, L841–853) proves it is **not** a drop-in training reward: the
60-run NEG smoke pilot found restraint-pattern criteria pass at **0.929
prevalence** — a structural gameability an evaluation harness tolerates but
a training loop converts into pattern-matching for the specific over-actions
frontier models have already been trained against. GRPO would amplify this.

`healthcraft.rl.reward.compute_training_reward` is therefore decoupled from
`compute_reward`. Eq. 1 remains byte-identical for evaluation (golden
replay under `tests/test_evaluator_integrity/` continues to pass); the
training reward composes verifiable-anchored signals with a multiplicative
safety gate, abstention-on-disagreement for the residual LLM-judge term,
and capped process bonuses.

**Formula** (`rl/reward.py`):

```
R = G_safety · clip( w_v · R_verifiable
                   + w_j · R_judge
                   + w_p · R_process ,
                     clip_lo, clip_hi )
```

| Term | Meaning | Source |
|---|---|---|
| `G_safety ∈ {0, 1}` | Multiplicative hard gate over safety + restraint criteria, **all verifiable** | `rl/criteria_classifier.py`, `rl/reward.py` |
| `R_verifiable` | Mean satisfaction over non-safety, non-restraint `world_state`/`pattern` criteria | reuses `tasks/evaluator._verify_world_state` and `_verify_pattern` |
| `R_judge` | Mean satisfaction over judge-needed criteria, **abstain** on `EnsembleResult.ambiguous` (drop from denominator) | reuses `llm/ensemble_judge.EnsembleJudge` |
| `R_process` | Small, capped bonus from `process_signals` (idempotency-key use, retry-with-backoff, escalation) | populated by PR-B (WS-5) |

Defaults are verifiable-dominant (`configs/rl/reward.yaml`):
`w_verifiable=0.8`, `w_judge=0.2`, `w_process=0.0`, `process_bonus_cap=0.1`,
`restraint_prevalence_threshold=0.9`, `require_verifiable_safety=true`,
`rubric_channel="v8"` (set to `"v10"` for production training — the
strictest non-experimental overlay, which promotes `llm_judge` criteria to
deterministic `world_state` checks and shrinks the judge-call surface in
the hot loop; v8 is the conservative no-behaviour-change default and
matches `evaluate_task`'s internal default).

**Three design choices in this training reward (each responds to one item
on the whitepaper's training-safety future-work list; none has been
empirically validated yet):**

1. **No safety-critical criterion may depend on an LLM judge.** With
   `require_verifiable_safety=True` (default), the classifier raises on any
   safety-critical `llm_judge` criterion. Convert via the existing overlay
   system (`scripts/migrate_criteria.py` → `configs/rubrics/v9–v11`).
   Rationale: a hard safety gate that calls a noisy oracle is not a hard
   gate.
2. **Restraint criteria carry no shaped gradient.** They are folded into
   the safety gate (violation → gate fails) and excluded from the shaped
   term. This is one possible response to the whitepaper's 0.929
   restraint-prevalence finding; alternative responses (prevalence-discount
   weighting, replacement with affirmative criteria) are not implemented
   here and have not been compared.
3. **Judge abstention.** `EnsembleJudge` already supports same-vendor skip
   and `EnsembleResult.ambiguous` for supermajority-fail. The training
   reward consumes that — ambiguous criteria are dropped from the
   denominator rather than guessed at; the verifiable/process weights are
   renormalised to maintain reward range.

Note that "verifiable" world-state checks are deterministic and free of
LLM-judge noise; they are **not** ungameable. The whitepaper's
0.929-prevalence finding is itself a case of a deterministic
world-state-verified criterion that nonetheless behaves badly as a
training reward.

## Architecture

```
 slime: Megatron-Core (policy, DAPO grads) -- weights(CUDA-IPC) --> SGLang
   ^   batch: tokens, loss_mask, reward, advantage                      |
   |                                                                    v
   +-- healthcraft.rl.rollout.generate(args, sample, params) ------------+
       - HealthCraftEnv.reset(task, episode_seed, system_prompt)
       - run_agent_task against SGLangClient (OpenAI-compatible /v1)
       - emit tokens + per-token loss_mask (assistant=1, env=0)
   +-- healthcraft.rl.reward.reward_func(args, sample) ------------------+
       - compute_training_reward(task, trajectory, world, ensemble_judge)
```

HealthCraft owns **environment + reward**; `slime` (THUDM — Corecraft's own
stack) owns Megatron-Core training, GRPO/DAPO gradients, and CUDA-IPC
weight sync. We do **not** write training-framework code. `slime` and a
tokenizer are optional/lazy imports so HealthCraft stays CPU-installable.

Policy must be **open-weights** — Claude is closed-weight and cannot be
GRPO-trained. Recommended candidates:

- `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` (hybrid Mamba-2 + MoE +
  Attention; aligns with the existing Kaggle work; supported by
  Megatron-Core and SGLang v0.5.5+).
- Qwen3-30B (easiest path; well-supported by all RL frameworks).

Claude is appropriate for the LLM judge only (via `EnsembleJudge`'s
cross-vendor pool with same-vendor skip).

## Algorithm — DAPO, not vanilla GRPO

HealthCraft's safety-gated reward will produce many zero-variance groups
(all rollouts safety-fail, or all pass with identical criteria). Vanilla
GRPO group-relative advantage collapses to zero gradient on those, wasting
compute. DAPO addresses this:

| Technique | Why for HealthCraft |
|---|---|
| Dynamic sampling | Drop zero-variance groups — common with the safety hard-gate |
| Clip-higher (`ε_low=0.2, ε_high=0.28`) | Maintain exploration; prevent entropy collapse on long tool trajectories |
| Token-level loss | Long variable-length agentic trajectories shouldn't be down-weighted by sequence count |
| Overlong reward shaping | Soft penalty for runaway trajectories; avoids false negatives on long-but-correct reasoning |

Group size **G = 16** (Corecraft Table 5.2). Reward range strictly `[0, 1]`
keeps clip-higher stable. KL-to-reference removed (DAPO recipe).

## Package layout (PR-A, this PR)

| Path | Role |
|---|---|
| `src/healthcraft/rl/__init__.py` | Public API |
| `src/healthcraft/rl/types.py` | `RolloutResult`, `TrainingRewardResult` |
| `src/healthcraft/rl/config.py` | `RewardConfig` + YAML loader |
| `src/healthcraft/rl/loss_mask.py` | `role_loss_mask`, `token_loss_mask`, `serialize_tool_result` |
| `src/healthcraft/rl/criteria_classifier.py` | Partition into safety / restraint / verifiable / judged |
| `src/healthcraft/rl/reward.py` | `compute_training_reward` + slime `reward_func` adapter |
| `src/healthcraft/rl/env.py` | `HealthCraftEnv` — `reset` / `rollout` |
| `src/healthcraft/llm/agent.py` | New `SGLangClient(OpenAIClient)` + factory routing |
| `configs/rl/reward.yaml` | Training-reward weights and thresholds |
| `scripts/rl_dryrun.py` | CPU end-to-end smoke (no GPU, no API) |
| `tests/test_rl/` | Unit + contract tests |

**Untouched** (proof Eq. 1 evaluation reward is not disturbed):
`tasks/rubrics.py:compute_reward`, `tasks/evaluator.py:evaluate_task`,
`configs/rubrics/v8–v11`, `configs/tasks/`, `docs/whitepaper/content.tex`.
`tests/test_evaluator_integrity/` continues to pass.

## Design principles (governance-clean)

1. **Eq. 1 evaluation reward is immutable.** Never modify `compute_reward`,
   `evaluate_task`, the v8–v11 overlays, `configs/tasks/`, or the
   whitepaper.
2. **Land in new Safe locations.** New files in `src/healthcraft/rl/`,
   `configs/rl/`, `tests/test_rl/`, `scripts/`, `docs/`. Surgical edits
   only to `llm/agent.py` (SGLangClient) and `rl/loss_mask.py` (parse-and-
   reserialise for tool-turn determinism — leaves `agent.py`'s
   `json.dumps` untouched).
3. **Verifiable-first.** Every criterion checkable against world state is
   in `R_verifiable`. The LLM judge is the residual, not the spine. This
   is both a safety property (ungameable) and a throughput property (no
   API call in the hot loop).
4. **Reproducible-by-seed.** The env is deterministic given an
   `episode_seed`; training samples seeds, eval pins them
   (`HealthCraftEnv.reset(..., episode_seed=...)`). The legacy hardcoded
   `seed=42` in `run_agent_task` is overridden post-rollout.
5. **Research-artifact firewall.** A trained checkpoint carries a
   machine-readable label (`deployment_status=research_artifact`,
   `trained_against=healthcraft_v<n>`); downstream tooling refuses to
   score it on the same benchmark as evidence of clinical competence.
   Held-out prospective validation by a physician is mandatory before
   any deployment conversation.

## slime configuration (delivered in PR-D)

PR-D (WS-6) will deliver `configs/rl/slime_grpo.yaml` and
`scripts/rl_train.sh`. Skeleton:

```bash
python -m slime.train \
  --custom-generate-function-path healthcraft.rl.rollout.generate \
  --custom-rm-path healthcraft.rl.reward.reward_func \
  --algo dapo \
  --n-samples-per-prompt 16 \
  --dapo-dynamic-sampling \
  --dapo-clip-low 0.2 --dapo-clip-high 0.28 \
  --dapo-token-level-loss \
  --colocate \
  --sglang-base-url http://127.0.0.1:30000/v1 \
  --model nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 \
  --megatron-tp 4 --megatron-pp 2 --megatron-ep 4 \
  --max-turns 25 \
  --output-dir results/rl/run-<timestamp>
```

The live multi-GPU run is **out of scope** for the env-side PRs; it needs
H100s (Brev `distant-peach-wildebeest` or Kaggle) and is multi-day.

## Verification

```bash
make test                          # full suite; tests/test_rl/ included
make lint                          # ruff check + format check
python scripts/rl_dryrun.py        # CPU end-to-end smoke
pytest tests/test_evaluator_integrity/ -q   # Eq.1 byte-identical (golden replay)
```

The dry-run asserts: loss-mask length matches turn count, mask values match
turn roles, reward ∈ [0, 1], safety gate fires on a synthesised violation,
ambiguous judge criteria abstain, and same-seed runs reproduce identically.

## Roadmap

| PR | Workstreams | Status |
|---|---|---|
| **PR-A** (#3) | WS-1 + WS-2 — env contract + verifiable-anchored training reward | ✅ merged |
| **PR-B** (#4) | WS-5 — idempotency completion + fault injection + process signals | ✅ merged |
| **PR-C** (#5) | WS-3 + WS-4 — closed-loop physiology + seeded episodes | ✅ merged |
| **PR-D** (this PR) | WS-6 — `slime` launch config + anti-Goodhart instrumentation + research-artifact firewall + runbook | in review |

### PR-D — slime launch config + anti-Goodhart instrumentation (WS-6)

Closes the docs/RL_COUPLING.md roadmap. Five deliverables:

1. **`rl/instrumentation.py`** — anti-Goodhart canaries the slime training
   loop reads to halt before reward-hacking sets in:
   `group_reward_variance` (DAPO dynamic-sampling), `prevalence_drift` +
   `restraint_inflation_signal` (the whitepaper's 0.929-finding watchdog),
   `cohens_kappa` + `judge_kappa_drift` (cross-judge agreement drop = the
   policy is exploiting one judge's blind spots), `kl_overoptimisation_signal`
   (Gao-2023 hump detection). `CanaryReport.any_red()` aggregates with
   conservative default thresholds; the runbook explains tuning.

2. **`rl/artifact.py`** — `ResearchArtifactMetadata` is enforced at the
   API level: the dataclass refuses to construct with `deployment_status`
   set to anything but `"research_artifact"`, and refuses to construct
   with a tampered `score_disclaimer`. Every checkpoint travels with a
   `research_artifact.json` written by `metadata.save()`; downstream
   tooling calls `verify_research_artifact(path)` and refuses to score
   the checkpoint on the benchmark it was trained against.

3. **`configs/rl/slime_grpo.yaml`** — the slime launch config: DAPO with
   clip-higher 0.20/0.28, G=16, token-level loss, co-located CUDA-IPC
   weight sync, fault-injection curriculum (3 stages), instrumentation
   periodicities, eval hooks. `make rl-train` invokes it.

4. **`scripts/rl_train.sh`** — operator launch wrapper with pre-flight
   checks (config exists, seed-pool disjoint invariant, SGLang reachable).
   Fails loud before launching slime, so no half-started runs.

5. **`docs/RL_RUNBOOK.md`** — operator runbook: H100 provisioning, SGLang
   bring-up, pre-flight, launch, **canary interpretation** (when a canary
   fires, the prescribed response is *halt training*, not "tune the LR"),
   post-training validation requirements (held-out prospective physician
   review is mandatory).

### PR-C — closed-loop physiology + seeded episodes (WS-3 + WS-4)

**`world/transition.py`** (new) implements the bounded-residual update
`s_t = clip(base_interp(t) + Σ effect(a, t - t_a), bounds)`. Each mutating
action contributes a time-varying delta (linear ramp to peak over
`onset_minutes`, linear decay over `duration_minutes`) that sums onto the
open-loop trajectory and clips to physiologic bounds (`spo2 ≤ 100`,
`systolic_bp ≥ 40`, etc.). `WorldState.get_current_vitals` consults
`actions_for_patient(audit_log, patient_id, world, start_time)` to build
the action list, then calls `apply_action_effects_to_vitals`. **No
behaviour change when `dynamic_state_enabled=False`** (V8 / replay path).

The action → effect mapping is a deliberately **simplified clinical
model**, not a pharmacology simulator. Five effects ship: vasopressor
(MAP↑), fluid (BP↑, HR↓), antibiotic (sepsis curve flattens), analgesic
(HR↓, RR↓), oxygen (SpO2↑). Extending the model is straightforward — add
a key to `ACTION_EFFECTS` and a pattern to `_classify_action`.

**Seeded episodes (WS-4)**: `configs/rl/seeds_train.txt` (5000 seeds
`43..5042`) and `configs/rl/seeds_eval.txt` (50 seeds — `42` plus
`1000001..1000049`) are disjoint **by construction**.
`SeedPool.__post_init__` asserts no overlap at load time so a
misconfigured file fails loudly rather than leaking eval seeds into
training. `WorldSeeder` now accepts `dynamic_state_enabled` directly,
retiring PR-A's `# noqa: SLF001` private-attribute poke in `rl/env.py`.

**Why a clinical model can be this simple and still help RL.** The
whitepaper's restraint-prevalence finding (0.929 NEG-smoke) shows
literal-game-prone deterministic criteria already exist; the closed-loop
physiology doesn't have to be pharmacologically accurate to add a
sequential signal — it just has to make agent actions *change the future
state in clinically-directional ways*, so "do the right thing at the
right time" carries non-zero reward variance. Anything more faithful is
a separate research effort with its own validation burden.
