# Frontier Accounting — claude-opus-4-8 vs gpt-5.5

**Status:** pilot complete (2026-06-01); full 205-task run in progress.
**Channel:** v10 (strictest populated + regression-locked). **Seed:** 42. **Trials:** 3.

This card reports an accounting of two frontier models on HEALTHCRAFT whose
outcomes are intended to **reproduce, trace, and verify**. It supersedes nothing —
the published V8 benchmark (README) remains the headline result; this is a
separate, in-progress evaluation of two newer models. Read the caveats before
citing any number.

## Why this run exists / what the v11 audit changed

A 43-agent audit of the v11 consensus channel + the model-run path (workflow
`waz7dce3y`, see `GRADER_FIDELITY_AUDIT_2026-05-31.md`) found and fixed three
run-path defects that would have **silently corrupted** a frontier run:

- **D4-F1** — the Anthropic temperature guard was a literal `"4-7" not in model`
  substring, so `claude-opus-4-8` sent `temperature=0` → API 400 → every task
  cached as a `reward=0` error trajectory. Fixed (`_claude_omits_temperature`,
  Opus ≥ 4.7 omits the param).
- **D4-F6** — confirmed live: **`gpt-5.5` rejects `temperature=0`** ("only the
  default (1) is supported"). `OpenAIClient` now self-heals (drops temperature,
  retries, remembers the model); preflight hard-fails distinctly on any residual
  400 so it can't masquerade as a silent `reward=0`.
- **D4-F4** — `rubric_channel` (+ `judge_model`, `judge_prompt_version`) is now
  persisted on every trajectory, so the graded channel is provable from the file.

## Determinism caveat (this is central to "reproduce")

**Neither frontier model runs at `temperature=0`** — Opus 4.7+ deprecated the
parameter and gpt-5.5 mandates the default (1). HEALTHCRAFT's nominal
`temperature=0` reproducibility assumption does **not** hold for these two models.
Reproducibility therefore rests on **`seed=42` + multi-trial Pass@k with CIs**, and
gpt-5.5 in particular samples non-deterministically (per-trial variance is
expected; e.g. pilot CC-001 swung reward 0.889 → 0.000 across trials). Pass^3
(all-3-pass) is the reliability floor and should be read as such.

## Judge design — and the "judge-swap"

The **pilot** used asymmetric *frontier-cross* judging (opus-4.8 judged by gpt-5.5;
gpt-5.5 judged by opus-4.8) — the only cross-vendor option between the two, but a
confound: each agent faced a *different* judge, conflating agent skill with judge
leniency.

The **full run swaps to a common neutral third-vendor judge: `grok-4` (xAI)** —
cross-vendor to both agents, so both are graded by the *same* judge and the
comparison is apples-to-apples. (gemini-3.1-pro-preview was the intended neutral
judge but the available `GOOGLE_API_KEY` is quota-exhausted — 429 — and the bare
`gemini-3.1-pro` id 404s; grok-4 is the working neutral judge.) This is *more*
rigorous than V8, whose cross-vendor judging was itself asymmetric.

## Pilot results — 20 tasks × 3 trials @ v10 (frontier-cross judging)

> **The pilot is a single category.** `--max-tasks 20` took the first 20 tasks in
> load order — all `clinical_communication` (CC-001–020). These rates describe CC
> tasks only and are **not** comparable to V8's cross-category figures. The pilot's
> purpose was to validate the fixed pipeline end-to-end (it did: 120/120 trials,
> 0 errors, fully traceable).

| Metric | claude-opus-4-8 (judge gpt-5.5) | gpt-5.5 (judge claude-opus-4-8) |
|---|---|---|
| Pass@1 | 23.3% — 95% CI [14.4, 35.4] | 43.3% — [31.6, 55.9] |
| Pass@3 (any of 3) | 35.0% | 50.0% |
| Pass^3 (all 3) | 15.0% — [5.2, 36.0] | 35.0% — [18.1, 56.7] |
| Avg reward | 0.685 | 0.787 |
| Safety-fail (per trial) | 20.0% (12/60) — [11.8, 31.8] | 15.0% (9/60) — [8.1, 26.1] |

Pass@1 gap +20pp (two-proportion p = 0.020, nominal). **Do not over-read it:**
(1) single category; (2) judge asymmetry; (3) non-determinism; (4) n = 20 with
overlapping CIs. The reversal vs V8 (where Claude > GPT) is most plausibly **category
skew** — CC is exactly where the documented GPT pattern (strong text generation,
lighter tool/world-state verification) flatters it. The full run + common judge
exist to remove confounds (1) and (2).

## Full run (in progress)

All 205 tasks (spanning all 6 categories) × 3 trials × 2 agents, v10, **common
neutral grok-4 judge**, seed 42. Two concurrent jobs (per-results-dir
`experiments.jsonl`, no shared-write race). Estimated ~24 h wall-clock concurrent
(~2.2 min/trial; gpt-5.5 reasoning is slow). Idempotent resume on interruption.

```bash
set -a && source /Users/kiteboard/lostbench/.env && set +a   # canonical keys (repo .env is stale/401)

python -m healthcraft.llm.orchestrator \
  --agent-model claude-opus-4-8 --judge-model grok-4 \
  --rubric-channel v10 --tasks all --trials 3 --seed 42 \
  --results-dir results/acct-full-opus48-grok-v10

python -m healthcraft.llm.orchestrator \
  --agent-model gpt-5.5 --judge-model grok-4 \
  --rubric-channel v10 --tasks all --trials 3 --seed 42 \
  --results-dir results/acct-full-gpt55-grok-v10
```

Re-running the same command **resumes** (completed trajectories are cached and
skipped). Analyze with `python scripts/analyze_results.py <results-dir>`.

## Reproduce / trace / verify — status

- **Reproduce:** seed=42, deterministic per-(task, model, seed, trial) cache keys
  (include the agent model, so new-model runs never collide with V8), idempotent
  resume, 0 errors. *Caveat:* temp=0 unavailable for both models → seed + trials,
  not bit-exact.
- **Trace:** every trajectory records model, seed, `rubric_channel=v10`,
  `judge_model`, `judge_prompt_version=v2`, full turns, criteria, reward,
  safety_gate, timestamp — provable from the file alone.
- **Verify:** graded on the locked v10 channel via a single cross-vendor judge at
  prompt v2; the v8 golden + channel verdict-locks are intact; the gold-set FP/FN
  harness is green. The grading path is the audited one.

## Follow-ups

- Frontier-cross re-grade ablation (opus-4.8 trajectories judged by gpt-5.5 and
  vice-versa) to quantify the judge-effect delta vs the grok-4 common judge —
  requires a v10-aware re-grade driver (`evaluator.py` grades base criteria only).
- Per-model model cards + leaderboard refresh once the full run completes.
- Gemini as a second neutral judge once a billing-enabled `GOOGLE_API_KEY` is
  available (id is now correct: `gemini-3.1-pro-preview`).
