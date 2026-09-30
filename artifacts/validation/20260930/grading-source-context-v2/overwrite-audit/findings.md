# Standalone grading output preservation audit

Ordinary bounded correctness audit, not formal red-team or clinical validation.
Only newly created synthetic fixtures under this directory were graded. No
repository files, historical results, models, provider APIs, or network were used
or modified. A stub supplied judge metadata only; the synthetic task has one
saved deterministic criterion and its judge method fails if invoked.

## Confirmed finding: existing grades and summaries are silently replaced

- `src/healthcraft/llm/evaluator.py:121`–123: `GradingResult.save` creates a parent
  directory then uses `Path.write_text`, truncating an existing result.
- `src/healthcraft/llm/evaluator.py:310`–319: `evaluate_trajectory_file` grades first,
  chooses the fixed `<trajectory_stem>_grading.json` filename, then calls that save
  method. The filename does not distinguish judge model, skepticism, or regrade
  attempt. Both the default alongside-input output and explicit `output_dir`
  replace prior grades.
- `src/healthcraft/llm/evaluator.py:495`, 504–515, 547–566: the CLI constructs its
  judge and grades before writing a fixed `evaluation_summary.json` using
  `write_text`. A second invocation with a different stub judge and skepticism
  returns normally while replacing both the grade and summary.

The executable reproduction creates genuine first grading outputs, captures
those bytes, and invokes the actual APIs again with a different offline judge
identity. All five checked outputs changed with no exception: direct save (1),
single-file default and explicit destination (2), CLI grade and summary (2).
Every original trajectory retained its SHA-256. Copies of before/after grading
outputs are retained alongside the temporary fixtures. `reproduction.json`
binds their hashes and the unchanged evaluator source.

This is a preservation defect in derived grading evidence; it is not evidence
that any existing historical result was actually overwritten in this audit.
No concurrency or crash behavior was tested, and there is no clinical claim.

## Existing test coverage and minimal future repair

`tests/test_evaluator_integrity/test_empty_rubric_entrypoints.py` verifies no
writes for invalid rubrics and a fresh-output positive grading case; it does not
exercise valid repeated grading against an existing destination.
`tests/scripts/test_retry_readers.py` covers selecting latest trajectory retries,
not preservation of standalone grading outputs.

A separate TDD patch should reject destination collisions before any judge
construction/call or first grading write, including the CLI summary and every
planned grade path. Direct `GradingResult.save` should use exclusive creation as
the final guard against races. A fresh exclusive run directory is an alternative
for the CLI, with clear guidance to choose a new destination for a new regrade.
Keep original trajectories untouched; do not silently skip or overwrite existing
grades. This audit implements none of those changes.

## Reproduction

From the repository root, with a new empty audit directory (the supplied driver
uses exclusive fixture creation):

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. .venv/bin/python /private/tmp/healthcraft-standalone-output-audit/reproduce.py
```

Historical invocation redirected stdout/stderr to `reproduction.log`. Runtime:
Python 3.14.3. The driver patches provider construction and socket connection
entry points to fail, and supplies only a metadata-only offline judge stub.
