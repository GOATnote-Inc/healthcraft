---
model_id: gpt-5.4
model_family: gpt
vendor: openai
evaluation_date: "2026-03-15"
healthcraft_version: "0.1.0"
pilot_id: v8
trials_per_task: 3
n_tasks: 195
n_criteria: 2323
judge_mode: single
judge_model: claude-opus-4-6
full:
  pass_at_1: 0.126
  pass_at_1_ci_95: [0.102, 0.156]
  pass_at_3: 0.246
  pass_caret_3: 0.031
  mean_reward: 0.546
  safety_gate_pass_rate: 0.660
consensus:
  status: pending
  note: "Requires Phase 2 execution (scripts/build_consensus.py)."
hard:
  status: pending
  note: "Requires Phase 3 execution (scripts/build_hard.py)."
---

# GPT-5.4 on HealthCraft

## Summary

GPT-5.4 sits behind Claude Opus 4.6 on every headline metric in V8. It is
notably more conservative with tools (roughly 9x fewer tool calls than
Claude) and more aggressive on the safety gate (34.0% safety-fail vs
Claude's 27.5%). GPT's V7 -> V8 shift was large (+107% relative
avg-reward), driven by the six infrastructure bug fixes documented in
CLAUDE.md / V8_ANALYSIS.md.

## Headline Results (V8)

| Metric | Full |
|--------|------|
| Pass@1 | **12.6%** (95% CI 10.2 - 15.6) |
| Pass@3 | 24.6% |
| Pass^3 | 3.1% |
| Mean reward | 0.546 |
| Safety-gate pass rate | 66.0% |
| Safety-fail rate | 34.0% |

Consensus and Hard subsets: **pending** -- requires Phase 2/3 execution via
`scripts/build_consensus.py` and `scripts/build_hard.py` against the V8
trajectory pool.

## Judge Configuration

Cross-vendor single judge: **Claude Opus 4.6** evaluates `llm_judge`
criteria on GPT trajectories. `world_state` and `pattern` criteria are
verified deterministically (no judge API calls).

## Safety-Gate Breakdown

34.0% of trials fail the safety gate -- the highest rate among the three
models benchmarked so far. The gap to Claude (27.5%) is consistent with
GPT's tendency to *selectively avoid tools* on tasks where the description
provides enough context for text generation (see CLAUDE.md "Selective Tool
Avoidance"), which reduces the opportunity to log safety-relevant
`createClinicalOrder` calls and therefore increases the rate at which
safety-critical `world_state` criteria go unsatisfied.

## Multi-step Workflows

GPT's Pass@1 on `multi_step_workflows` is 0.0% in V8. The category that
requires sustained tool-use is where GPT's short-horizon strategy fails
hardest.

## Failure Mode Notes

- **Selective tool avoidance.** Bimodal tool-use: 45% zero-tool, 55%
  heavy-tool. Rational but evaluation-inflating for `world_state` criteria.
- **Infrastructure-sensitive.** V7->V8 shift was +107% relative avg-reward
  after six infrastructure bug fixes; V8 is the authoritative baseline.
- **Low Pass^3 (3.1%).** Reliability is the binding constraint, not
  best-of-3 performance.

## Reproducing

```bash
python -m healthcraft.llm.orchestrator \
  --agent-model gpt-5.4 \
  --judge-model claude-opus-4-6 \
  --tasks configs/tasks \
  --trials 3 \
  --results-dir results/pilot-v8-gpt54
```

Replay-grade via the public grader:

```bash
python evals/healthcraft_simple_eval.py \
  --dataset data/huggingface_release/healthcraft_full.jsonl \
  --agent-model gpt-5.4 \
  --judge-mode single \
  --replay-from results/pilot-v8-gpt54 \
  --trials 3
```
