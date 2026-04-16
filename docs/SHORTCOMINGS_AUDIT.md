# SHORTCOMINGS_AUDIT.md

Status: 2026-04-16. Driver: external review of HealthCraft v0.1.0 against frontier-lab safety-eval standards. Companion to `CHANGELOG.md` v0.2.0 and the v0.2 hardening plan.

This document enumerates seven shortcomings identified in HealthCraft as it stood at arXiv v1 submission. Each section names the current behavior (with file:line anchors), the severity, what breaks if unaddressed, and the planned fix. Plan referenced inline; no fixes are claimed here — this document is the audit, not the deliverable.

The arXiv v1 numbers (Claude Opus 4.6 Pass@1 24.8% / GPT-5.4 Pass@1 12.6%, see `docs/V8_ANALYSIS.md`) are frozen. All v0.2 fixes that could change V8 numbers are gated behind opt-in flags so V8 reproduces bit-for-bit.

---

## 1. LLM-judge reliability is moderate

**Severity:** High — affects 63.5% of all rubric criteria.

**Current behavior:**
- 1,420 of 2,241 rubric criteria use `verification: llm_judge` (820 use `world_state`, 1 uses `pattern`).
- `safety_critical_judgment` category: 84.4% llm_judge.
- `temporal_reasoning`: 81.6% llm_judge.
- `information_retrieval`: 77.5% llm_judge.
- Cohen's κ vs human adjudication: **0.553** overall (moderate), **0.306** on long trajectories (>40 turns) — see `docs/JUDGE_RELIABILITY.md`.
- Cross-vendor judge selection (`src/healthcraft/llm/judge.py:283-305` `select_judge_model`) is correctly implemented (Claude→GPT, GPT→Claude, Gemini→Claude); reliability gap is in the judge LLM itself, not in vendor selection.
- Judge prompt (`src/healthcraft/llm/judge.py:23-57`) is single-shot, no skepticism preset, no rationale capture beyond `evidence` string.
- No dedicated test module for `judge.py` exists in the test suite (22 test files, 317 tests).

**What breaks if unaddressed:** Headline Pass@k numbers carry an irreducible ~25% disagreement floor. Frontier-lab reviewers will not accept benchmark claims at this κ. Long-trajectory bias systematically penalizes Claude (longer trajectories) vs GPT (shorter) — see Pattern 7 in `CLAUDE.md`.

**Planned fix (Phase 2 of v0.2 plan):**
- Add `tests/test_judge/` module with parser, prompt-stability, fairness, formatter, skepticism-preset tests.
- Introduce opt-in `rubric_channel=v9_deterministic` overlay that converts the realistically-convertible llm_judge subset (target: 1420 → ~990-1090 llm_judge; 820 → ~1150-1250 world_state) without modifying V8 rubrics.
- Validation gate: per-category κ ≥ 0.80 between v9 overlay and original llm_judge on V8 trajectories before any task YAML is edited.
- `docs/JUDGE_VALIDATION.md` records κ, conversions, and unconvertible set with rationale.

**V8-comparability impact:** None with default `rubric_channel=v8`. v9 results are reported as a separate channel in the paper, never as V8 replacements.

---

## 2. Patient state is static

**Severity:** High — limits the realism of safety-critical evaluation.

**Current behavior:**
- `WorldState.advance_time(minutes)` exists at `src/healthcraft/world/state.py:104` but is **never called by the orchestrator** (`src/healthcraft/llm/orchestrator.py:93-382`). Confirmed: `_current_time` is set at task start (line 32) and never advances during a trial.
- `Patient` is `@dataclass(frozen=True)` (`src/healthcraft/entities/patients.py:14-32`).
- `Encounter` is also frozen with immutable tuples for `vitals`, `labs`, `imaging` (`src/healthcraft/entities/encounters.py:87-106`).
- No deterioration logic exists for any clinical condition (sepsis, ACS, respiratory failure, etc.).
- No reassessment-trigger module exists.

**What breaks if unaddressed:** The benchmark cannot evaluate time-pressure failure modes that EM uniquely tests — agents that stabilize the wrong diagnosis still receive credit because vitals never change. This was acknowledged in arXiv v1 §6 Limitations but with insufficient sharpness.

**Planned fix (Phase 3 of v0.2 plan):**
- Create `src/healthcraft/world/physiology.py` with `VitalsTrajectory` overlay (frozen dataclass, layered on top of `Patient`/`Encounter` rather than mutating them).
- Pure seeded generators: `sepsis_trajectory`, `acs_trajectory`, `respiratory_failure_trajectory`, `stable_improving_trajectory`. All seeded from `(world_seed, patient_id)` for reproducibility.
- `WorldState.advance_time()` extended to optionally emit `_reassessment_prompt` audit entries when thresholds cross. Gated on `dynamic_state_enabled` constructor arg (default `False`).
- Orchestrator gains `--dynamic-state` CLI flag (default off). When on, calls `advance_time(minutes_per_turn)` between agent turns.
- Additive optional task-schema fields: `initial_state.clinical_trajectory`, `initial_state.time_budget_minutes`. All 195 V8 task YAMLs continue to validate without these fields.

**V8-comparability impact:** None with `dynamic_state_enabled=False`. With flag on, this is a new evaluation mode reported in paper v2 as "Dynamic-State Pilot (v2 Addendum)".

---

## 3. No latency / retry / timeout / concurrency semantics

**Severity:** Medium-High — limits realism for production-deployment claims.

**Current behavior:**
- All MCP tool calls execute synchronously and return immediately. No artificial latency.
- No timeout enforcement on tool calls.
- No retry logic; if a tool call fails, the agent must retry manually and the attempt is recorded as a fresh audit entry with no link to the original.
- `AuditEntry` (`src/healthcraft/mcp/audit.py:15-134`) has no `attempt_number`, `error_code`, or correlation field.
- No concurrency model — assumes single-threaded agent. Real ED systems have multiple concurrent clinicians and resource contention.

**What breaks if unaddressed:** Agents cannot demonstrate retry strategy, timeout-aware planning, or graceful degradation. Production systems need these; the benchmark cannot select for them.

**Planned fix (Phase 4 of v0.2 plan, partial):**
- Audit-log format extended **additively** with `attempt_number` and `error_code` fields (default 1 / `""`). Old V8 audit logs continue to parse.
- `src/healthcraft/mcp/server.py` `call_tool` increments `attempt_number` keyed by `(tool_name, idempotency_key)` and populates `error_code` from `result["code"]` on failure. Gated on `HC_IDEMPOTENT_TOOLS` env (default off).
- Latency simulation, true concurrency, and timeout enforcement remain **out of scope for v0.2** — flagged as open future work in `PAPER_REVISION_NOTES.md` and the v2 §6 Limitations rewrite.

**V8-comparability impact:** None with flag off (additive fields parse with defaults).

---

## 4. No idempotency on mutating tools

**Severity:** High — a real safety bug, not just a realism gap.

**Current behavior:**
- `create_clinical_order` (`src/healthcraft/mcp/tools/mutate_tools.py:110`) mints a fresh `ORD-<uuid>` on every call. If an agent retries the same logical order (e.g., duplicate aspirin order due to a transient error), two distinct orders land in world state and the agent receives credit for "ordered aspirin" twice while the patient is exposed to a real safety risk.
- `update_patient_record` (`src/healthcraft/mcp/tools/mutate_tools.py:306`) appends to the patient's `allergies` and `medications` tuples unconditionally at L335 / L342. Repeated calls produce duplicate entries.
- `update_task_status` (`mutate_tools.py:200`) accepts moves to terminal states (`completed`, `cancelled`) without checking whether the task is already in that state.
- No `idempotency_key` parameter is accepted by any mutating tool.

**What breaks if unaddressed:** Real clinical bugs in synthesized trajectories. Beyond realism, these affect rubric correctness — criteria that count "did the agent order X?" via audit-log presence over-credit duplicates.

**Planned fix (Phase 4 of v0.2 plan):**
- `AuditEntry` extended additively with `idempotency_key: str = ""` and `deduplicated: bool = False`.
- `create_clinical_order`: when `HC_IDEMPOTENT_TOOLS` on AND `params["idempotency_key"]` set, derive Order ID deterministically from `hash((encounter_id, order_type, idempotency_key))`; collisions return the existing order with `deduplicated=True`.
- `update_patient_record`: when flag on, set-append semantics `tuple(dict.fromkeys(existing + new))` — preserves order, drops duplicates.
- `update_task_status`: when flag on AND target status already terminal, return existing entity with `deduplicated=True`.
- `tests/test_mcp_tools/test_idempotency.py` covers each path; `test_audit_entry_backward_compatible_load` asserts V8 audit-log JSON still parses.

**V8-comparability impact:** None with flag off. Flag-on is a new pilot reported separately in paper v2.

---

## 5. Evaluator + infrastructure validation is incomplete

**Severity:** Highest priority (Reviewer's #1 fix).

**Current behavior:**
- 22 test files, 317 tests. **No dedicated `llm_judge` test module exists.**
- `scripts/preflight.py` runs 6 schema/contract checks but does not enforce that `schema.required` ⊆ handler `_require()` keys (one direction only).
- No task-satisfiability check exists. A criterion can reference a `(tool, qualifier)` pair that no handler can produce; this would silently always-fail.
- No audit-log invariants are tested (timestamp monotonicity, `result_summary` enum, append-only, tool-name casing).
- No prompt-composition snapshot test. Edits to `system-prompts/*.txt` can silently change agent behavior.
- No golden-trajectory replay. V7→V8 saw six infrastructure bugs (per `docs/V8_ANALYSIS.md`) that changed Pass rates substantially (Claude −13% rel, GPT +107% rel); a regression suite would have caught most of them.
- `replay_from_trajectory()` does not exist on the evaluator.

**What breaks if unaddressed:** Future infrastructure bugs go undetected until full pilot runs. Pilots cost money and time; bugs that should be caught in seconds at CI take days to surface.

**Planned fix (Phase 1 of v0.2 plan, top priority):**
- New `tests/test_evaluator_integrity/` module with six test files: `test_schema_handler_contract.py`, `test_missing_entity_links.py`, `test_audit_log_invariants.py`, `test_prompt_composition.py`, `test_golden_trajectory_replay.py`, `test_task_satisfiability.py`.
- New `replay_from_trajectory(trajectory, task)` helper on `src/healthcraft/tasks/evaluator.py`. Read-only. For `llm_judge` criteria, accepts saved verdicts as input rather than re-calling the judge (which would be nondeterministic and break replay).
- Extend `scripts/preflight.py` Check 1 to verify schema↔handler bidirectionally; add Check 7 (task satisfiability).
- Generalize `scripts/oracle_cc001.py` to `scripts/oracle_batch.py` with `--tasks A,B,C` CLI.
- New `tests/fixtures/golden_trajectories/index.json` manifest of ~30 stratified V8 trajectories with frozen `(reward, passed, safety_gate, criteria_results_hash)` tuples.
- Manifest does not copy result files — `results/` remains immutable per CLAUDE.md.
- New `docs/EVALUATION_INTEGRITY_HARDENING.md` documents what each test guards and how to extend without breaking the suite.

**V8-comparability impact:** None — tests-only plus one read-only helper. **If the golden-replay test fails on day 1, that is a real V8 nondeterminism bug** and is documented in `PAPER_REVISION_NOTES.md` rather than silently fixed.

---

## 6. Benchmark depth limited

**Severity:** Medium — matters for scaling-law claims, not for v1 baselining.

**Current behavior:**
- 195 tasks across 6 categories.
- Maps to **130 of 370** OpenEM conditions (35% coverage).
- Stratification is uneven: `clinical_reasoning` is 50 tasks (largest), `temporal_reasoning` is 25 (smallest).
- No explicit acuity (ESI 1-5) distribution check vs real ED visit mix.
- Pediatric, geriatric, obstetric, toxicology specialty subsets are not enumerated as a coverage axis.

**What breaks if unaddressed:** A 195-task benchmark is informative but underpowered for scaling-law claims, sub-population analysis, or training-set construction. Reviewers will ask whether per-condition difficulty was sampled or hand-picked.

**Planned fix (Phase 6 of v0.2 plan):**
- `docs/TASKSET_EXPANSION_PLAN.md` — explicit roadmap to 230/370 (+100 tasks, v0.2), 330/370 (+200 tasks, v0.3), 370/370 (+240 tasks, v0.4). Remaining 130 tasks reserved for cross-cutting multi-condition scenarios.
- Stratification axes: acuity (ESI 1-5), workflow (single/multi/disposition/procedural), failure mode (Corecraft patterns 1-3 + HealthCraft patterns 4-7 from CLAUDE.md), specialty (adult/pediatric/geriatric/obstetric/toxicology/trauma).
- New `scripts/coverage_matrix.py` generates conditions × axes matrix from existing task YAMLs and `openem` data.
- Quality gates for new tasks: `make preflight`, `test_task_satisfiability`, `oracle_batch.py`, manual clinical review.
- Authoring target: 65% world_state criteria (driven by Phase 2 v9 channel design, applied at task-author time so future tasks inherit the deterministic-grading bias by default).

**V8-comparability impact:** None. Adding tasks creates a superset; the "195-task set" remains the v1 head-to-head benchmark. The "295-task set" (v0.2) is reported as a separate row.

---

## 7. Whitepaper overclaims in places

**Severity:** Medium — paper is on arXiv as v1; rebuttals will catch this.

**Current behavior:**
- §1 Abstract and §10 Conclusion frame contributions in language that is occasionally more confident than the methods support.
- §6 Limitations enumerates static-state and judge-κ as known issues but does not specifically call out the `createClinicalOrder` duplicate-order bug or the `updatePatientRecord` duplicate-append bug — both present in V8 audit logs.
- The 63.5% llm_judge dependence is stated only in §7 and not flagged as a measurement caveat in §8 Results.
- Long-trajectory judge context overload (Pattern 7 in CLAUDE.md, κ=0.306 vs κ=0.553 overall) is mentioned but not quantified as a model-comparison bias.

**What breaks if unaddressed:** Reviewer rebuttals at NeurIPS, journal review, or independent replication will surface these as either undisclosed limitations or evidence of insufficient methodological self-criticism. The arXiv v2 update is the natural place to address all of them at once.

**Planned fix (Phase 5 of v0.2 plan):**
- `docs/PAPER_REVISION_NOTES.md` with five sections:
  1. v1 measured claims (frozen — do not change).
  2. Sharpened limitations for v2 §6: the 63.5% llm_judge dependence; static patient state; the two mutating-tool bugs; no idempotency/retry; 130/370 OpenEM coverage; long-trajectory judge bias.
  3. Tightened novelty claims relative to τ²-Bench and Corecraft.
  4. v2 additions, each marked `TBD-after-pilot` until backed by `results/`.
  5. Explicit "what has NOT been re-measured" list — rule: if no new pilot ran, no improvement claim.
- Optional `scripts/verify_v2_claims.py` extends `verify_canonical_numbers.py` to flag any v2 number not backed by a `results/pilot-*/summary.json`.
- `docs/whitepaper/canonical_numbers.md` gains a v2 section; v1 numbers are untouched.

**V8-comparability impact:** None. Documentation only.

---

## Cross-cutting commitments

- **No emojis** anywhere in code, docs, commit messages, or output (user hard rule from `~/.claude/projects/-Users-kiteboard/memory/`).
- **No `git add -A`** (HealthCraft convention from CLAUDE.md).
- **`results/` is immutable.** All Phase 0-6 tooling reads only; new pilots write to new directories with explicit names (`results/v9-smoke`, `results/dynamic-smoke`, `results/idempotent-smoke`).
- Every commit leaves the repo in `make test && make preflight` green.
- Phase ordering follows reviewer's prioritization: 1 → 6 in priority order. If time runs out, work below the cut is well-defined for later.

## References

- v0.2 hardening plan: `~/.claude/plans/crystalline-watching-steele.md`
- arXiv v1 whitepaper: `docs/whitepaper/content.tex`
- V8 results: `docs/V8_ANALYSIS.md`, `results/pilot-v8-{claude-opus,gpt54}/`
- Judge reliability: `docs/JUDGE_RELIABILITY.md`
- Evaluation integrity baseline: `docs/EVALUATION_INTEGRITY.md`
- Corecraft attribution: `docs/CORECRAFT_ATTRIBUTION.md`
