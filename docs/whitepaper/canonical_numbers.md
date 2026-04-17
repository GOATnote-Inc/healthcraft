# Canonical Numbers

Every quantitative claim in `content.tex` and `appendix.tex` MUST be tagged
with a `% CN:<tag>` LaTeX comment that maps to a row in this file.
`scripts/verify_canonical_numbers.py` enforces correspondence on every
build. A bare number in the prose without a corresponding `% CN` tag is
a CI failure.

## Schema

| Column | Meaning |
|---|---|
| Tag | `CN:<snake_case_identifier>` used in `% CN:` comments |
| Claim | Human-readable description |
| Value | Exact value rendered in the paper |
| 95% CI | Wilson score bounds (if applicable) |
| Source | `path/to/file:line` or `path/to/artifact.json#$.json.pointer` |

## Numbers

### Environment

| Tag | Claim | Value | 95% CI | Source |
|---|---|---|---|---|
| `CN:entity_types` | FHIR entity types in world state | 14 | n/a | `docs/ENTITY_MAPPING.md` |
| `CN:entities_seeded` | Entities at seed=42 | 3,987 | n/a | `src/healthcraft/world/seed.py` |
| `CN:n_tools` | MCP tools exposed | 24 | n/a | `configs/mcp-tools.json` |
| `CN:tool_waves` | Tool waves (read/compute/mutate/workflow) | 4 | n/a | `docs/TOOL_MAPPING.md` |
| `CN:openem_conditions` | OpenEM conditions covered | 370 | n/a | OpenEM v0.5.1 `openem-corpus` |

### Tasks

| Tag | Claim | Value | 95% CI | Source |
|---|---|---|---|---|
| `CN:n_tasks` | Total evaluation tasks | 195 | n/a | `configs/tasks/` aggregate |
| `CN:n_criteria` | Total binary criteria | 2,255 | n/a | `configs/tasks/` aggregate |
| `CN:n_safety_critical` | Safety-critical criteria | 515 | n/a | `configs/tasks/` aggregate |
| `CN:n_categories` | Task categories | 6 | n/a | `docs/TASK_DESIGN.md` |
| `CN:n_confusion_pairs` | OpenEM confusion pairs used | 152 | n/a | OpenEM v0.5.1 |
| `CN:n_decision_rules` | Decision rules used | 45 | n/a | `configs/tasks/` |
| `CN:n_eval_properties` | Evaluation properties used | 44 | n/a | `configs/tasks/` |

### V8 Main Results

| Tag | Claim | Value | 95% CI | Source |
|---|---|---|---|---|
| `CN:v8_claude_pass1` | Claude Opus 4.6 Pass@1 | 24.8% | [21.5, 28.4] | `results/pilot-v8-claude-opus/summary.json` |
| `CN:v8_claude_pass3` | Claude Opus 4.6 Pass@3 | 37.9% | TBD | `docs/V8_ANALYSIS.md` |
| `CN:v8_claude_passk3` | Claude Opus 4.6 Pass^3 | 13.8% | TBD | `docs/V8_ANALYSIS.md` |
| `CN:v8_claude_reward` | Claude Opus 4.6 avg reward | 0.634 | n/a | `results/pilot-v8-claude-opus/summary.json` |
| `CN:v8_claude_safety_fail` | Claude Opus 4.6 safety failures | 27.5% | [24.1, 31.3] | `docs/V8_ANALYSIS.md` |
| `CN:v8_gpt_pass1` | GPT-5.4 Pass@1 | 12.6% | [10.2, 15.6] | `results/pilot-v8-gpt54/summary.json` |
| `CN:v8_gpt_pass3` | GPT-5.4 Pass@3 | 24.6% | TBD | `docs/V8_ANALYSIS.md` |
| `CN:v8_gpt_passk3` | GPT-5.4 Pass^3 | 3.1% | TBD | `docs/V8_ANALYSIS.md` |
| `CN:v8_gpt_reward` | GPT-5.4 avg reward | 0.546 | n/a | `results/pilot-v8-gpt54/summary.json` |
| `CN:v8_gpt_safety_fail` | GPT-5.4 safety failures | 34.0% | [30.3, 37.9] | `docs/V8_ANALYSIS.md` |
| `CN:v8_total_tasks` | Tasks evaluated | 195 | n/a | `results/pilot-v8-claude-opus/summary.json` |
| `CN:v8_total_runs` | Total runs (tasks x trials) | 585 | n/a | `results/pilot-v8-*/summary.json` |
| `CN:v8_trials` | Trials per task | 3 | n/a | `results/pilot-v8-*/summary.json` |

### Multi-Step Workflows Collapse

| Tag | Claim | Value | 95% CI | Source |
|---|---|---|---|---|
| `CN:v8_claude_msw_pass1` | Claude multi\_step\_workflows Pass@1 | 1.0% | TBD | `docs/V8_ANALYSIS.md` |
| `CN:v8_gpt_msw_pass1` | GPT multi\_step\_workflows Pass@1 | 0.0% | TBD | `docs/V8_ANALYSIS.md` |

### Judge Reliability

| Tag | Claim | Value | 95% CI | Source |
|---|---|---|---|---|
| `CN:judge_kappa` | Cross-vendor judge Cohen's kappa | 0.553 | n/a | `docs/JUDGE_RELIABILITY.md` |
| `CN:judge_cc001_oracle` | CC-001 oracle world\_state agreement | 5/5 | n/a | `docs/ORACLE_VALIDATION.md` |

### Pilot Progression (V7 -> V8 delta, infrastructure-fidelity insight)

| Tag | Claim | Value | 95% CI | Source |
|---|---|---|---|---|
| `CN:v7_to_v8_claude_delta` | Claude avg-reward delta v7 -> v8 (0.730 -> 0.634) | -13% rel | n/a | `results/pilot-v7-claude-opus/summary.json`, `results/pilot-v8-claude-opus/summary.json` |
| `CN:v7_to_v8_gpt_delta` | GPT avg-reward delta v7 -> v8 (0.264 -> 0.546) | +107% rel | n/a | `results/pilot-v7-gpt54/summary.json`, `results/pilot-v8-gpt54/summary.json` |
| `CN:infra_bugs_fixed` | Infrastructure bugs fixed v2 -> v8 | 6 | n/a | `docs/V6_AUDIT_FINDINGS.md`, `docs/EVALUATION_INTEGRITY.md` |

### Determinism

| Tag | Claim | Value | 95% CI | Source |
|---|---|---|---|---|
| `CN:seed` | Fixed seed | 42 | n/a | `src/healthcraft/tasks/rubrics.py` |
| `CN:temperature` | Sampling temperature | 0 | n/a | `src/healthcraft/llm/orchestrator.py` |

---

## v2 Additions (arXiv v2 revision)

v2 tags are prefixed `CN:v2_`. These are NOT used in v1 prose. Each requires
a completed pilot in `results/` before it can carry a numeric value. Until
then, the value is `TBD`. `scripts/verify_v2_claims.py` enforces this.

**Rule:** If no new pilot ran, no improvement claim. Every v2 number must
trace to a `results/` artifact.

### Limitations (sharpened for v2 Section 6)

| Tag | Claim | Value | 95% CI | Source |
|---|---|---|---|---|
| `CN:v2_llm_judge_pct` | Criteria using llm\_judge verification | 63.5% | n/a | `configs/tasks/` aggregate (1420/2241) |
| `CN:v2_llm_judge_count` | llm\_judge criteria count | 1,420 | n/a | `configs/tasks/` aggregate |
| `CN:v2_total_criteria_counted` | Total criteria in judge analysis | 2,241 | n/a | `configs/tasks/` aggregate |
| `CN:v2_long_traj_kappa` | Long-trajectory judge kappa | 0.306 | n/a | `docs/JUDGE_RELIABILITY.md` |
| `CN:v2_openem_coverage` | OpenEM conditions covered by tasks | 130/370 | n/a | `scripts/coverage_matrix.py` |
| `CN:v2_openem_coverage_pct` | Coverage as percentage | 35% | n/a | `scripts/coverage_matrix.py` |

### v9 Deterministic Channel

| Tag | Claim | Value | 95% CI | Source |
|---|---|---|---|---|
| `CN:v2_v9_claude_pass1` | Claude Pass@1 (v9 channel) | TBD | TBD | `results/pilot-v9-deterministic/summary.json` |
| `CN:v2_v9_gpt_pass1` | GPT Pass@1 (v9 channel) | TBD | TBD | `results/pilot-v9-deterministic/summary.json` |
| `CN:v2_v9_ws_criteria` | world\_state criteria after overlay | 44 | n/a | `configs/rubrics/v9_deterministic_overlay.yaml` |

### V9 Overlay Audit (judge reliability, 2026-04-17)

Numbers derived from `docs/V9_OVERLAY_AUDIT.json`, reproduced by
`scripts/kappa_validation.py` with no API calls. Source trajectories
are the cached V8 runs in `results/pilot-v8-{claude-opus,gpt54}/`.

| Tag | Claim | Value | 95% CI | Source |
|---|---|---|---|---|
| `CN:v9_overlay_criteria` | Overlay entries audited | 44 | n/a | `configs/rubrics/v9_deterministic_overlay.yaml` |
| `CN:v9_n_observations` | (criterion x trial) observations | 264 | n/a | `docs/V9_OVERLAY_AUDIT.json#$.summary.n_observations` |
| `CN:v9_agreement` | Overall raw agreement v9 vs v8 judge | 76.1% | n/a | `docs/V9_OVERLAY_AUDIT.json#$.summary.overall_agreement` |
| `CN:v9_kappa_overall` | Overall Cohen's kappa | 0.402 | n/a | `docs/V9_OVERLAY_AUDIT.json#$.summary.overall_kappa` |
| `CN:v9_safety_inversions` | Safety-critical verdict inversions | 6 | n/a | `docs/V9_OVERLAY_AUDIT.json#$.summary.n_safety_inversions` |
| `CN:v9_v8_prev_overall` | V8 PASS prevalence on audited subset | 79.5% | n/a | `docs/V9_OVERLAY_AUDIT.json#$.by_category[*].prevalence_v8` (weighted) |
| `CN:v9_judge_halluc_count` | Disagreements labeled judge\_hallucination | 46 | n/a | `docs/V9_OVERLAY_AUDIT.json#$.disagreement_labels.counts.judge_hallucination` |
| `CN:v9_judge_halluc_pct` | judge\_hallucination share of disagreements | 73% | n/a | 46 / 63 |
| `CN:v9_infra_err_count` | Disagreements labeled infrastructure\_error | 5 | n/a | `docs/V9_OVERLAY_AUDIT.json#$.disagreement_labels.counts.infrastructure_error` |
| `CN:v9_tier1_count` | Overlay entries in Tier 1 (reward-safe) | 10 | n/a | `docs/V9_OVERLAY_AUDIT.json#$.tier_counts.tier_1_reward_safe` |
| `CN:v9_tier2_count` | Overlay entries in Tier 2 (research-only) | 26 | n/a | `docs/V9_OVERLAY_AUDIT.json#$.tier_counts.tier_2_research_only` |
| `CN:v9_tier3_count` | Overlay entries in Tier 3 (keep llm\_judge) | 8 | n/a | `docs/V9_OVERLAY_AUDIT.json#$.tier_counts.tier_3_keep_llm_judge` |

### Dynamic-State Pilot

| Tag | Claim | Value | 95% CI | Source |
|---|---|---|---|---|
| `CN:v2_dyn_claude_pass1` | Claude Pass@1 (dynamic state) | TBD | TBD | `results/pilot-dynamic-state/summary.json` |
| `CN:v2_dyn_gpt_pass1` | GPT Pass@1 (dynamic state) | TBD | TBD | `results/pilot-dynamic-state/summary.json` |

### Idempotent-Tools Pilot

| Tag | Claim | Value | 95% CI | Source |
|---|---|---|---|---|
| `CN:v2_idem_claude_pass1` | Claude Pass@1 (idempotent tools) | TBD | TBD | `results/pilot-idempotent-tools/summary.json` |
| `CN:v2_idem_gpt_pass1` | GPT Pass@1 (idempotent tools) | TBD | TBD | `results/pilot-idempotent-tools/summary.json` |
