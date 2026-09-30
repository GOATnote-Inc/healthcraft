# Empty-rubric assessment boundary audit

Ordinary, read-only development review at local checkpoint `b8e8e050b78f53b61e1a29444c1139bf3d3c42be`. No model, judge, provider, or network calls. Both `criteria: []` and omitted `criteria` were tested through real loaders and assessment functions using new synthetic files under this directory. The original synthetic trajectories were unchanged. Source hashes before/after are identical in `reproduction.json`.

The current canonical catalog has **205 tasks and zero empty rubrics**. The strict orchestrator now rejects these inputs. The remaining gap is in public assessment APIs and custom/legacy authored inputs; this audit does not show corrupted existing benchmark results.

| Entry point | Reproduced outcome with zero criteria | Relevant implementation |
|---|---|---|
| `tasks.evaluator.evaluate_task` | `reward=0.0`, `passed=True`, `safety_gate_passed=True`, no criterion results | `src/healthcraft/tasks/evaluator.py:107–124`: empty parse, then `all([])` |
| `tasks.evaluator.replay_from_trajectory` | Same assessed pass and safety pass for a trajectory without execution error | `src/healthcraft/tasks/evaluator.py:941–975`: calls evaluator then merges an empty set |
| `llm.evaluator.evaluate_trajectory_file` → `evaluate_trajectory` | Writes a new `_grading.json` with `passed=True`, safety true, reward zero; zero judge calls | `src/healthcraft/llm/evaluator.py:182–223`, file wrapper `:247–307` |
| `evals/healthcraft_simple_eval.py` replay/report | `pass_at_1=1.0`, safety pass rate 1.0, mean reward zero | `_run_replay:203–239`, `_build_report:269–293` |
| `rl.reward.compute_training_reward` | Default reward zero, `safety_gate_passed=True`, all criterion counts zero | `src/healthcraft/rl/reward.py:220–239,361–373` |
| Same training API with a supplied positive process signal 0.1 | Reward **0.1**, despite no task criteria and default `w_process=0`; safety true | Empty-partition renormalization `src/healthcraft/rl/reward.py:332–359` |
| `rl.reward.reward_func` (slime-compatible API) | Returns scalar **0.1** and records the zero-criterion decomposition in sample metadata | `src/healthcraft/rl/reward.py:394–414` |

The simple-evals reproduction points its module root at a temporary synthetic catalog. Its dataset `criteria` field is not the scored rubric: it loads authored YAML through the legacy loader. An empty dataset criterion list **alone** therefore does not reproduce this when the corresponding canonical task still has criteria. The standalone file API directly accepts a custom `tasks_dir`; no patched judge behavior was needed beyond an object that raises if any judge call occurs.

An interrupted zero-rubric replay currently returns false/false instead of true/true because of its separate execution-error branch. That does not establish an assessed rubric and should not become a special allowance for invalid assessment configuration.

Recommended next TDD slice:

1. Treat **zero total task criteria as invalid assessment configuration**, raising a clear `ValueError` (or a narrow subclass), rather than emitting a clinical failure or unassessed-looking numeric score. `TaskResult`/`TrainingRewardResult` are assessed result types with bool/float fields; a null/unassessed redesign is larger and unnecessary for a malformed rubric.
2. The smallest shared scoring boundary is `tasks.evaluator._parse_criteria`: reject an empty raw rubric there. It is already called by direct evaluation, both replay branches, and training reward. Have standalone evaluation reuse this guarded parser rather than its duplicate parser. Keep the strict loader's early rejection so ordinary orchestrator runs fail before provider/output access. CLI wrappers should report this as a configuration error/nonzero, never silently skip it or emit a success aggregate.
3. Preserve `Task` construction, ordinary `load_task`/legacy `load_tasks`, and non-scoring `HealthCraftEnv.reset/rollout` use for prompt/transport fixtures. These are not themselves assessment. Do not ban rubricless synthetic generation fixtures globally.
4. Keep **Eq. 1 and valid nonempty task outcomes unchanged**. Retain low-level `compute_reward([], []) == 0.0` compatibility and the legitimate safety-gate pass for a nonempty rubric containing no safety criteria. Do not confuse zero total criteria with an empty safety/verifiable/judged partition, or with missing saved criterion results on a nonempty task.
5. Do not edit or rewrite historical trajectories/results. Historical records may remain loadable/viewable as recorded evidence. A new attempt to re-grade an empty task must fail explicitly; ordinary nonempty golden replay must stay identical.

Existing contracts and targeted regression plan:

- `tests/test_tasks/test_rubrics.py:182` locks the low-level empty reward fallback; `:188` onward permits a nonempty rubric with no safety criteria. Preserve both.
- `tests/test_rl/test_env.py:34–46` deliberately uses a rubricless task for environment/rollout tests; no assessment is performed there. Preserve those fixtures.
- `tests/test_rl/test_reward.py:329` permits zero when **sample metadata is absent**. This is distinct from a supplied invalid empty task and should not silently absorb the new configuration error.
- `tests/scripts/test_retry_readers.py:251` exercises full simple-evals replay for a nonempty rubric; `tests/test_release/test_huggingface_release.py:361` only checks simple-evals help. Add missing/empty authored-task cases to the actual replay/report path, including a valid row before the invalid one, and require a clear failure rather than a reduced or all-pass aggregate.
- `tests/test_evaluator_integrity/test_replay_contract.py:299` protects interrupted nonempty trajectories; add empty-task rejection with and without a trajectory error. Do not reject merely because saved `criteria_results` is empty.
- Add direct/standalone/training/slime adapter empty-rubric regressions, with a forbidden judge spy and positive process signal control. Check no grading file or scalar success is produced and original input bytes remain unchanged.
- Re-run `test_golden_trajectory_replay.py` and channel goldens unchanged; their 30 historical golden trajectories reference tasks in the nonempty canonical catalog.

Reproduction: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. .venv/bin/python /private/tmp/healthcraft-empty-rubric-audit/reproduce.py`. Results: `reproduction.json` and `reproduction.log`. Existing relevant contract tests: **82 passed** on Python 3.14.3 (`existing-contract-tests.log`). No repository files changed.
