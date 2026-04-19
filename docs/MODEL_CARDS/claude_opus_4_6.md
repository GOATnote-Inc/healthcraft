---
model_id: claude-opus-4-6
model_family: claude
vendor: anthropic
evaluation_date: "2026-03-15"
healthcraft_version: "0.1.0"
pilot_id: v8
trials_per_task: 3
n_tasks: 195
n_criteria: 2323
judge_mode: single
judge_model: gpt-5.4
full:
  pass_at_1: 0.248
  pass_at_1_ci_95: [0.215, 0.284]
  pass_at_3: 0.379
  pass_caret_3: 0.138
  mean_reward: 0.634
  safety_gate_pass_rate: 0.725
consensus:
  status: pending
  note: "Requires Phase 2 execution (scripts/build_consensus.py)."
hard:
  status: pending
  note: "Requires Phase 3 execution (scripts/build_hard.py)."
---

# Claude Opus 4.6 on HealthCraft

## Summary

Claude Opus 4.6 is the strongest model in the V8 pilot across every reported
headline metric. It paid for the top spot with an unusually high tool-call
budget (Claude uses roughly 9x more tool calls per task than GPT-5.4, see
CLAUDE.md "Tool Overuse with Diminishing Returns"), but its reward per
trajectory is materially higher and its safety-gate pass rate leads by 6.5
points.

## Headline Results (V8)

| Metric | Full |
|--------|------|
| Pass@1 | **24.8%** (95% CI 21.5 - 28.4) |
| Pass@3 | 37.9% |
| Pass^3 | 13.8% |
| Mean reward | 0.634 |
| Safety-gate pass rate | 72.5% |
| Safety-fail rate | 27.5% |

Consensus and Hard subsets: **pending** -- requires Phase 2/3 execution via
`scripts/build_consensus.py` and `scripts/build_hard.py` against the V8
trajectory pool.

## Judge Configuration

Cross-vendor single judge: **GPT-5.4** evaluates `llm_judge` criteria on
Claude trajectories. `world_state` and `pattern` criteria are verified
deterministically (no judge API calls).

V8 trajectories were graded under the V8 rubric channel; V10 re-grading via
`replay_from_trajectory(rubric_channel="v10")` promotes a subset of the
stricter negation-class criteria to `world_state` verification.

## Safety-Gate Breakdown

27.5% of trials fail because at least one `safety_critical: true` criterion
is violated. In HEALTHCRAFT the safety gate is the dominant failure mode,
not clinical reasoning -- models frequently satisfy 10 of 11 criteria but
score 0 because the 11th is safety-critical (see CLAUDE.md "Safety Gate
Dominance"). Claude's safety-gate pass rate is the best of the three models
tested so far, but 27.5% is still a wide error band.

## Multi-step Workflows

Claude's Pass@1 on `multi_step_workflows` is 1.0% in V8. Long horizons plus
the safety gate plus judge context overload (49-turn trajectories exceed the
judge's effective window) collapse performance on this category.

## Failure Mode Notes

- **Tool overuse with diminishing returns.** 23.8 tool calls on CC-004 for
  reward 0.417 where GPT scored 0.450 with 0.2 calls.
- **Judge context overload.** In 49-turn trajectories the judge misses
  content in the final response (CC-001 C04/C05).
- **Safety-gate dominance.** Non-convex reward landscape -- small
  safety-critical violations zero out otherwise-strong trajectories.

## Reproducing

```bash
python -m healthcraft.llm.orchestrator \
  --agent-model claude-opus-4-6 \
  --judge-model gpt-5.4 \
  --tasks configs/tasks \
  --trials 3 \
  --results-dir results/pilot-v8-claude-opus
```

Replay-grade via the public grader:

```bash
python evals/healthcraft_simple_eval.py \
  --dataset data/huggingface_release/healthcraft_full.jsonl \
  --agent-model claude-opus-4-6 \
  --judge-mode single \
  --replay-from results/pilot-v8-claude-opus \
  --trials 3
```
