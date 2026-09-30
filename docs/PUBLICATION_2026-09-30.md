# Automated engineering and whitepaper publication

The [publication release](https://github.com/GOATnote-Inc/healthcraft/releases/tag/healthcraft-2026-09-30)
packages the repository work and revised paper by Brandon Dent, MD. This is
a single physician-engineer project using automated development and evaluation.
The workflow does not require a human-in-the-loop approval stage. Optional
clinical and comparative user studies remain on the research roadmap.

## What is being released

The implementation distinguishes model execution, tool acknowledgement,
physical persistence, literal readback and source-correct content. It adds
strict failure accounting, immutable attempts, source-preserving clinical
views, synthetic comparator adapters, local MedGemma/Nemotron capture and
offline diagnostic interfaces. The paper explains these contracts and the
limits of the evidence supporting them.

The frozen local cohort contains 16 scheduled attempts: 15 completed, 15 notes
stored, 2 literal readbacks and 0 full mechanical passes. A failed tool call
remains in the denominator. Clinical criteria were unassessed. Neither these
development cases nor unrelated competitor scores establish clinical or
product superiority.

## Automated adversarial and publication review

[Frozen receipts](../artifacts/validation/20260930/publication-v1/manifest.json)
record the bounded automated review and test-driven repairs:

- A separate agent ran 317 focused regressions covering malformed execution,
  successful-action evidence, immutable checkpoints, worker failures, cohort
  denominators and draft identity. These are engineering tests, not independent
  clinical observations.
- Source and newly reachable history screening found no credential-pattern
  matches or files over 50 MiB. The scan's scope and limitations are recorded;
  it is not comprehensive security or privacy certification.
- Publication tests reproduced then repaired ignored BibTeX failures, canonical
  verifier failures masked by `make`, ignored `artifacts/` citations, missing
  TeX dependencies, incomplete bibliographies and empty-figure overwrites.
- The final focused publication selection passed 61 tests. The 32 packaging
  tests also passed on Python 3.10 and 3.12. These overlapping runs are not
  additive evidence of independent validation.
- `make lint` passed on the tracked candidate plus explicitly listed new Python
  files in an isolated directory. Unrelated untracked research archives were
  excluded; the original workspace still contains their existing lint findings.
- Named and anonymous paper builds passed. The 21-page named PDF was rendered
  and inspected. The extracted arXiv archive compiled without unresolved
  references or overfull boxes and produced the same extracted text as the
  named PDF. Final test and commit details are in the release's
  `publication-validation.json` and GitHub checks.

## Known limits retained in the release

SCJ-012-C02, IR-001-C03 and IR-002 include documented semantic grader
counterexamples. The historical task files also have 81 declared-schema
violations across 64 of 205 tasks, unchanged from the prior main revision;
loader/preflight success does not imply full schema conformance. Some seeded
entity timestamps and clinical-task due-times remain wall-clock-dependent.
The paper describes these limitations without changing historical results or
claiming clinical validity from passing software tests.

Historical figures are preserved as hash-checked snapshots because their full
original inputs are not all distributed in Git. New local execution and
engineering evidence is separately committed. The repository's research
artifact boundary remains in force.

## arXiv handoff

The release includes the PDF, source archive, per-file manifest, checksums,
copy-ready metadata and [replacement instructions](whitepaper/ARXIV_SUBMISSION.md)
for arXiv:2605.21496. Publishing on GitHub does not itself submit the replacement
through the author's arXiv account.
