# Authored observation checkpoint validation

Local frozen-candidate validation on 2026-09-30, based on `7d9e54b` plus the
named staged repairs. No remote update, manuscript change, formal red-team
review, paid API, model inference, or clinical adjudication occurred in this
checkpoint. The local Nemotron/MedGemma evidence from earlier checkpoints is
not a new test of these changes.

| Check | Outcome |
|---|---|
| Actual `make test` on the exported candidate, Python 3.14.3 | 2540 passed, seven skipped, 248.50 seconds |
| Changed-contract suite, Python 3.10.18 | 271 passed |
| Changed-contract suite, Python 3.12.8 | 271 passed |
| Actual `make lint` on tracked candidate export | Ruff check and format passed; 320 Python files |
| `make smoke` | 48 checks passed, no failures or warnings |
| `make preflight` | Structural checks passed; clinical validity/solvability unassessed |
| `make grader-goldset` | 55 existing synthetic cases, zero errors or verdict mismatches |
| Actual source-concordance CLI | Passed; 205 tasks accounted for, 196 patient retrievals, nine no-patient tasks unassessed |

The certificate preserves 208/208 direct vital records and 991/991 recognized
lab entries through real injection and `getEncounterDetails` calls. It checks
raw source trees, identity, source paths, timing keys and exact timestamps.
It does not certify typed clinical projections; those have separate regression
tests. Vital timing: 30 explicit, 173 missing, three clock-only, two unresolved.
Lab timing: one explicit, 990 missing. No clinical/safety criterion or model
performance is graded. All 347 source/config certificate hashes stayed stable.

The full test command used the repository Python runtime with the candidate's
`src` and root on `PYTHONPATH`, and local loopback socket permission for HTTP
tests. The lint export excludes unrelated untracked research/deliverable trees.
Earlier in-progress failures and sandbox socket errors are preserved in
`artifacts/evaluation-integrity/20260930/authored-observations-v1/`.

Reproduce on this candidate:

```sh
make test
make lint
make smoke
make preflight
make grader-goldset
python scripts/certify_observation_fidelity.py --output /tmp/new-observation-certificate.json
```

The certificate refuses to overwrite an existing output. Its artifact contains
actual tool requests/responses and source/runtime identities. Hashes establish
content identity, not third-party authentication or prospective registration.
`manifest.json` also binds the tested source/config/test/launch files and logs.
The final workspace source hashes were checked against the exported candidate.
See `docs/AUTHORED_OBSERVATIONS.md` and `docs/RELEASE_EVIDENCE_PLAN.md` for remaining
scope and release requirements. The superiority gate remains unmet.
