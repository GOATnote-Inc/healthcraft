# Care and imaging checkpoint validation

Local engineering validation on 2026-09-30, based on `aa21717` plus the staged
care/imaging and local-provider repairs. These checks do not establish clinical
validity, healthcare benefit or superiority. No formal red-team review, remote
write, manuscript change, paid API or clinical adjudication occurred.

| Check | Outcome |
|---|---|
| Final actual `make test`, Python 3.14.3 | 2,723 passed, seven skipped, 268.19 seconds |
| Changed-path compatibility, Python 3.10.18 | 416 passed, three optional SDK skips |
| Changed-path compatibility, Python 3.12.8 | 416 passed, three optional SDK skips |
| Final actual `make lint` on tracked candidate | Ruff check and format passed; 329 Python files |
| Actual pinned NeMo Gym SDK, Python 3.13.14 | 44 passed; two dependency deprecation warnings |
| `make smoke` | 48 checks passed; no failures or warnings |
| `make preflight` | Structural checks passed; clinical validity/solvability unassessed |
| `make grader-goldset` | 55 existing synthetic fixtures; zero errors or verdict mismatches |
| Care/imaging source certificate | All 205 tasks accounted for; mechanical concordance |
| Existing observation source certificate | All 205 tasks accounted for; mechanical concordance |

The care/imaging witness executed 196 actual `getEncounterDetails` calls and
retained nine no-index-patient tasks as unassessed. It preserved all 32 reviewed
care groups across 29 tasks and 115 public imaging records across 76 tasks.
Eight reviewed conditional guidance fields remained withheld with three
collection-level notices. Imaging timestamps: one explicit, 114 missing.
All 354 source/config hashes remained unchanged. Clinical and safety criteria
assessed: zero.

The existing observation witness still preserved 208 vital records and 991 lab
entries through 196 actual calls. Its 349 source/config hashes remained stable.
It checks raw source and timing; typed lab/vital projections have separate
regression tests. Neither certificate adjudicates authored clinical content.

The first full run (`full-tests.log`) had 2,721 passes, seven skips and one
expected prompt-snapshot mismatch. The tool reference had intentionally changed,
but the composition test still compared it to V8. The original V8 fixture was
preserved byte-for-byte; a separate development fixture and historical-hash
regression were added. The final green run is in `final-tests/`. The initial
failure is retained rather than overwritten or represented as a pass.

The initial export was `/private/tmp/healthcraft-care-final-9cnyg_3v`; the final
export was `/private/tmp/healthcraft-care-final-ydju6d2l`. Between them only the
prompt-composition test and its new fixture changed among tested implementation
inputs. The earlier compatibility, SDK, smoke, preflight, grader and certificate
checks therefore retain identical applicable production inputs. Every source
hash recorded by both certificates was checked against the final candidate.
The final manifest also binds all 582 source/config/test/launch inputs.

Each process receipt records its exact command, candidate path, clean environment,
wall time and exit status. `run-checks.py.txt` preserves the launcher. Local socket
permission enabled actual HTTP tests. Lint used the tracked export, excluding
unrelated untracked research/deliverable trees. NeMo Gym was pinned to
`82e1834ccf2dd578af26a1abc686c15e17569594`; its dedicated Python 3.13 environment
loaded the repository's pure-Python pytest package without installing new dependencies.

The separate [two local model attempts](../../../local-care-probe/20260930/source-reading-v1/README.md)
used the final candidate: both completed, Nemotron met the strict four-field
copy contract, and MedGemma's Markdown-fenced response remained format-invalid.
That diagnostic assesses no clinical or safety outcome and supplies no ranking.

Reproduce with new certificate output paths:

```sh
make test
make lint
make smoke
make preflight
make grader-goldset
python scripts/certify_care_imaging.py --output /tmp/new-care-imaging-certificate.json
python scripts/certify_observation_fidelity.py --output /tmp/new-observation-certificate.json
```

Hashes establish content identity, not independent authentication or prospective
registration. See `docs/CARE_IMAGING_FIDELITY.md`, `docs/TASK_VALIDITY_FINDINGS.md`
and `docs/RELEASE_EVIDENCE_PLAN.md` for the remaining validity and release work.
