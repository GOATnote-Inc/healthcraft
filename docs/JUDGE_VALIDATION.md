# Judge Validation

Phase 2 of the v0.2 hardening plan. Characterizes the cross-vendor LLM judge,
locks its behavior with 52 tests, and introduces the v9 deterministic overlay
for migrating defensibly-convertible llm_judge criteria to world_state.

## V8 Baseline: Judge Reliability

Source: `scripts/judge_reliability.py` run on V8 pilot trajectories (100
criterion evaluations, 3 repeats each = 300 API calls).

| Metric | Value |
|--------|-------|
| Overall Cohen's kappa | 0.553 |
| Overall agreement rate | 77.0% |
| Disagreements | 23 / 100 (23%) |

### Stratified by Trajectory Length

| Bucket | n | Agreement | kappa |
|--------|---|-----------|-------|
| Short (< 15 turns) | 5 | 60.0% | 0.444 |
| Medium (15-40 turns) | 70 | 72.9% | 0.542 |
| Long (> 40 turns) | 25 | 92.0% | 0.306 |

The paradoxically low kappa on long trajectories (92% agreement but kappa=0.306)
is a base-rate artifact: most long-trajectory criteria are judged not-satisfied,
so high agreement is expected by chance. kappa corrects for this.

### Interpretation

- kappa=0.553 is "moderate" on the Landis-Koch scale.
- 63.5% of 2,241 criteria depend on llm_judge (1,420 criteria).
- This means the single largest source of evaluation variance is the judge.
- Failure pattern #7 (judge context overload) disproportionately affects
  Claude's longer trajectories.

## Judge Test Suite (52 tests)

All tests in `tests/test_judge/`. No judge tests existed before Phase 2.

### test_judge_parser.py (21 tests)

Locks `_parse_judge_response()` across 4 input formats:
- **Clean JSON**: `{"satisfied": true, "evidence": "..."}` parses correctly.
- **Markdown-fenced**: ` ```json ... ``` ` extracted and parsed.
- **Prose-wrapped**: JSON embedded in explanatory text found by brace-matching.
- **Malformed fallback**: keyword search for "satisfied" in unstructured text.

Critical fix landed during Phase 2: empty JSON `{}` inside markdown fences
previously returned without a `satisfied` key. Refactored parser from
early-return to accumulator pattern with normalization at end.

### test_judge_prompt_stability.py (5 tests)

Snapshot test: `JUDGE_SYSTEM_PROMPT` at `tests/fixtures/judge_prompts/default.txt`
(1,587 bytes). Any prompt change breaks the snapshot, forcing deliberate review.
Also verifies structural elements: FINAL RESPONSE section mentioned, JSON format
specified, "satisfied" key required.

### test_judge_fairness.py (6 tests)

`select_judge_model()` cross-vendor rule: the judge must be a different vendor
than the agent. Parametrized across all model families (Anthropic, OpenAI,
Google, xAI). Claude agent -> GPT judge. GPT agent -> Claude judge. Unknown
model -> Claude judge (safe default). Deterministic: same input always same output.

### test_trajectory_formatter.py (10 tests)

`_format_trajectory_for_judge()` transforms raw turns into structured sections:
TASK CONTEXT, TOOL CALL SUMMARY, AGENT'S FINAL RESPONSE, EARLIER REASONING.

Critical property locked: the agent's final assistant message is preserved in
full (no truncation) even in 50+ turn trajectories. This is where discharge
instructions, consult notes, and clinical content live. Truncating it causes
the judge to miss content-based criteria (failure pattern #7).

Also locks: tool call argument truncation at 150 chars, earlier reasoning
condensed to 500 chars per step, edge cases (empty trajectory, no assistant).

### test_skepticism_presets.py (10 tests)

Three presets: default (empty suffix, V8 behavior), moderate (lean not-satisfied
on ambiguity), high (strict/unambiguous evidence required). Tests lock:
- All three exist and are distinct.
- Default adds nothing (backward-compatible).
- High's suffix is longer than moderate's (more rules).
- Each appends cleanly to `JUDGE_SYSTEM_PROMPT` without corruption.

## v9 Deterministic Overlay

### Design

A second rubric channel (`rubric_channel=v9`) that rewrites convertible
llm_judge criteria to world_state checks. V8 behavior is completely unaffected
(default `rubric_channel=v8`).

Files:
- `configs/rubrics/v9_deterministic_overlay.yaml` -- curated entries (starts empty,
  populated after clinical review)
- `configs/rubrics/v9_migrations_proposed.yaml` -- 265 automated proposals
- `scripts/migrate_criteria.py` -- non-destructive proposal generator

### Orchestrator Integration

`src/healthcraft/llm/orchestrator.py` accepts `--rubric-channel {v8,v9}`.
When v9:
1. Loads overlay from `v9_deterministic_overlay.yaml`.
2. Rewrites matching criteria (verification + check fields) before evaluation.
3. Passes `rubric_channel="v9"` to `evaluate_task()`, enabling BEFORE/AFTER
   temporal operators in `_verify_world_state`.

### BEFORE/AFTER Temporal Operators (v9 only)

Added to `src/healthcraft/tasks/evaluator.py`. Gated on `rubric_channel != "v8"`.

Syntax: `<clause_A> BEFORE <clause_B>` or `<clause_A> AFTER <clause_B>`

Semantics:
- Both clauses must individually match audit log entries.
- `_first_matching_index(clause, audit_log)` finds the first entry matching
  each clause.
- BEFORE: clause_A's first match index < clause_B's first match index.
- AFTER: clause_A's first match index > clause_B's first match index.
- If either clause has no match, the criterion is not satisfied.

### Migration Proposals

`scripts/migrate_criteria.py` applies 4 heuristics to 1,420 llm_judge criteria:

| Heuristic | Pattern | Maps to |
|-----------|---------|---------|
| Retrieval | "retrieved X", "reviewed X" | audit_log contains call to <tool> |
| Ordering | "ordered X", "placed order" | audit_log contains createClinicalOrder for <type> |
| Negation | "did NOT order X", "avoided" | audit_log does NOT contain createClinicalOrder |
| Sequencing | "before", "prior to", "after" | manual rewrite (BEFORE/AFTER ops) |

Results (265 / 1,420 = 18.7%):

| Confidence | Count | Action |
|------------|-------|--------|
| high | 70 | Order verb + specific type keyword |
| medium | 55 | Retrieval verb + tool keyword, negation + type |
| low | 140 | Sequencing language (needs manual rewrite), generic order |

### Unconvertible Set

The remaining 1,155 llm_judge criteria (81.3%) stay as llm_judge because
they require judgment that cannot be reduced to audit-log checks:

| Category | Why unconvertible |
|----------|-------------------|
| Clinical reasoning | Diagnosis quality, differential completeness, treatment appropriateness |
| Clinical communication | Tone, empathy, clarity, patient education quality |
| Safety judgment | Appropriateness of contraindication avoidance (not just "did/didn't order") |
| Documentation quality | Structure, terminology, completeness beyond tool-call checks |
| Complex sequencing | Multi-step reasoning chains where order depends on intermediate results |

These criteria are inherently evaluative and require the LLM judge.

### Validation Gate

Before any entry lands in `v9_deterministic_overlay.yaml`:

1. Run `scripts/migrate_criteria.py --dry-run` to generate proposals.
2. Clinical reviewer signs off on high/medium confidence proposals.
3. Re-grade V8 trajectories with overlay applied.
4. Require kappa >= 0.80 per category between overlay verdicts and original
   llm_judge verdicts. Disagreements get manual review.
5. Only proposals passing this gate are added to the overlay.

### Targeted Shift

If all 70 high-confidence and 55 medium-confidence proposals pass validation:

| Channel | world_state | llm_judge | pattern |
|---------|------------|-----------|---------|
| v8 (current) | 820 (36.6%) | 1,420 (63.3%) | 1 (0.04%) |
| v9 (target) | 945 (42.2%) | 1,295 (57.8%) | 1 (0.04%) |

Modest but defensible shift. Aggressive conversion risks false determinism
(checking tool calls without checking reasoning quality).

## V8 Impact

None. All changes are:
- Tests only (52 new tests).
- Additive: `rubric_channel` parameter defaults to "v8" everywhere.
- Overlay file starts empty (no criteria rewritten until clinical review).
- v9 results are a separate evaluation channel, never reported as V8.

## Files

| File | Purpose |
|------|---------|
| `tests/test_judge/*.py` | 52 judge tests (5 files) |
| `tests/fixtures/judge_prompts/default.txt` | JUDGE_SYSTEM_PROMPT snapshot |
| `configs/rubrics/v9_deterministic_overlay.yaml` | Curated overlay (starts empty) |
| `configs/rubrics/v9_migrations_proposed.yaml` | 265 automated proposals |
| `scripts/migrate_criteria.py` | Non-destructive proposal generator |
| `src/healthcraft/llm/orchestrator.py` | `--rubric-channel` CLI flag |
| `src/healthcraft/tasks/evaluator.py` | BEFORE/AFTER temporal operators |
| `src/healthcraft/llm/judge.py` | Parser fix (empty JSON normalization) |
| `docs/JUDGE_VALIDATION.md` | This document |
