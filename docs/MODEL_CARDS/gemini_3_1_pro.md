---
model_id: gemini-3.1-pro
model_family: gemini
vendor: google
evaluation_date: "2026-04-16"
healthcraft_version: "0.1.0"
pilot_id: v9
trials_per_task: 3
n_tasks: 195
n_criteria: 2323
judge_mode: single
judge_model: claude-opus-4-6
coverage: partial
coverage_percent: 43
full:
  status: partial
  note: "V9 Gemini run at ~43% coverage (250/585 runs) as of 2026-04-16. Final numbers published at HealthCraft v1.1."
consensus:
  status: pending
  note: "Requires V9 completion + Phase 2 execution (scripts/build_consensus.py)."
hard:
  status: pending
  note: "Requires V9 completion + Phase 3 execution (scripts/build_hard.py)."
---

# Gemini 3.1 Pro on HealthCraft

## Summary

**Status: partial coverage at release time.** The V9 Gemini 3.1 Pro pilot
was approximately 43% complete (250 of 585 trajectories) as of
2026-04-16. This card is published so the leaderboard surface is
ready; headline numbers are withheld until the remaining 335 runs
complete. Follow-up numbers will ship with HealthCraft v1.1.

## Headline Results (V9 partial)

| Metric | Full |
|--------|------|
| Pass@1 | pending -- V9 still running (~43% coverage) |
| Pass@3 | pending |
| Pass^3 | pending |
| Mean reward | pending |
| Safety-gate pass rate | pending |

## Judge Configuration

Cross-vendor single judge: **Claude Opus 4.6** evaluates `llm_judge`
criteria on Gemini trajectories. `world_state` and `pattern` criteria are
verified deterministically (no judge API calls).

The V10 overlay (workstream D from `project_healthcraft_v10_overlay.md`)
promotes 40 negation-class criteria from `llm_judge` to `world_state`,
tightening the binding judge-side bottleneck before Gemini numbers are
published.

## Reproducing

```bash
python -m healthcraft.llm.orchestrator \
  --agent-model gemini-3.1-pro \
  --judge-model claude-opus-4-6 \
  --tasks configs/tasks \
  --trials 3 \
  --results-dir results/pilot-v9-gemini-pro
```

Replay-grade via the public grader (once V9 completes):

```bash
python evals/healthcraft_simple_eval.py \
  --dataset data/huggingface_release/healthcraft_full.jsonl \
  --agent-model gemini-3.1-pro \
  --judge-mode single \
  --replay-from results/pilot-v9-gemini-pro \
  --trials 3
```

## Notes

- Two-model V8 leaderboard (Claude Opus 4.6, GPT-5.4) is the authoritative
  baseline published in the whitepaper. Gemini is deferred to a follow-up
  release per `docs/whitepaper/`.
- Partial-coverage reporting avoids the bias from computing Pass@1 on a
  non-random 43% of tasks.
