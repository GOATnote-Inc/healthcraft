# Reading immutable evaluation retries

The orchestrator preserves each attempt. The first artifact ends in
`_tN.json`; retries add `_attempt2.json`, `_attempt3.json`, and so on.
Attempt numbers are numeric: attempt 10 supersedes attempt 2. A retry is
another attempt of the same trial, not an additional independent trial.
Original results remain unchanged.

Shared adapters in `healthcraft.llm.checkpoint` provide the current view:

- `selected_trajectory_paths(directory_or_paths)` selects the highest
  numbered attempt per original path, preserving distinct directories.
- `trajectory_attempt(path)` returns the original trial path and attempt
  number. Parse `_tN` from that original path when filtering trials.
- `selected_experiment_entries(entries)` selects the latest logged attempt
  in the original trial's position. This keeps first-k trial ordering stable
  after retries are appended. Entries without paths retain legacy behavior.
- `load_latest_summary(run_directory)` reads the highest numbered
  `summary-N.json`, or historical `summary.json` when no numbered file exists.

Selection happens before parsing or filtering trajectory content. A corrupt
or errored newest attempt never causes fallback to an earlier score. Each
consumer retains its existing policy for errors and invalid input; selection
does not make those policies equivalent across consumers. A malformed latest
summary raises an error instead of returning stale metrics.

Experiment logs remain append-only. `len(raw_entries)` is the logged attempt
count; `len(selected_experiment_entries(raw_entries))` is the selected trial
count. The log reader selects among logged entries, so a trajectory absent
from the log is not synthesized as an observation. Reconcile a failed log
write before interpreting log-based aggregate metrics.

## Updated entrypoints

Analysis, simple-evals replay, hard/consensus subset construction, agreement
reports, v10 rescoring, overlay proposal, judge reliability, safety taxonomy,
standalone bulk grading, and planner history use the selected view. An
explicit single-trajectory path still identifies exactly that artifact.

Historical scripts such as `analyze_v7.py`, `compare_pilots.py`,
`generate_paper_figures.py`, `kappa_validation.py`, and golden-fixture freeze
scripts retain their original snapshot semantics. Use them only with their
documented historical inputs; they are not retry-aware general readers.
Their existing frozen results and manifests have not been rewritten.

Regression coverage lives in `tests/scripts/test_retry_readers.py`, including
numeric attempt ordering, original trial parsing, unchanged source bytes,
stable log order, summary selection, and invalid-latest behavior. All tests
run locally without model requests.
