# HealthCraft Leaderboard

Auto-generated from `docs/MODEL_CARDS/*.md`. Do not edit directly --
run `scripts/regen_leaderboard.py` after updating any card.

All Pass@1 metrics are the fraction of tasks passed on a single trial. Pass@3 / Pass^3 and CI are listed in the individual model cards. Rows marked **pending** require Phase 2 / Phase 3 execution (Consensus / Hard subsets) or completion of the V9 Gemini pilot.

| Model | Full Pass@1 | Consensus Pass@1 | Hard Pass@1 | Mean Reward (Full) | Safety Gate Pass Rate (Full) | Notes |
|-------|-------------|------------------|-------------|--------------------|------------------------------|-------|
| `claude-opus-4-6` | 24.8% | pending | pending | 0.634 | 72.5% | pilot v8 |
| `gpt-5.4` | 12.6% | pending | pending | 0.546 | 66.0% | pilot v8 |
| `gemini-3.1-pro` | partial (v1.1) | pending | pending | pending | pending | pilot v9; partial coverage -- see card |

## Model cards

- [`claude-opus-4-6`](MODEL_CARDS/claude_opus_4_6.md) -- evaluated 2026-03-15
- [`gpt-5.4`](MODEL_CARDS/gpt_5_4.md) -- evaluated 2026-03-15
- [`gemini-3.1-pro`](MODEL_CARDS/gemini_3_1_pro.md) -- evaluated 2026-04-16
