# HealthCraft Whitepaper

Research preprint by Brandon Dent, MD, a single physician-engineer using
automated development and evaluation tools. The named paper is the public
release; an anonymous build is available for review venues that require it.

The [2026-09-30 publication](https://github.com/GOATnote-Inc/healthcraft/releases/tag/healthcraft-2026-09-30)
provides the paper PDF, arXiv source archive, checksums and submission metadata.
See [arXiv replacement instructions](ARXIV_SUBMISSION.md).

## Build

```bash
cd docs/whitepaper
make all             # both PDFs
make named           # public release (author visible)
make anonymous       # blind review (author redacted)
make verify          # CI gate: size, validity, identity leak, canonical numbers
make ci              # clean + all + verify
make arxiv           # rebuild named PDF and create fresh output/arxiv/
# A repeat package needs a fresh destination:
make arxiv ARXIV_OUT=output/arxiv-next
```

Requirements: Python 3.10+, TeX Live 2023+ with `pdflatex`, `bibtex`, and
Poppler (`pdftotext` for identity checks). Install the repository with
`pip install -c constraints-security.txt -e .` from its root before running
repository scripts. `make verify` reports when Poppler is absent and skips
identity checks; publication validation uses Poppler and does not skip them.

Builds stop on LaTeX or BibTeX failures. Packaging refuses an existing output
directory and includes only required sources, the compiled `ms.bbl`, style
and referenced figures. The source manifest records each archived file's
SHA-256 digest. CI also compiles the extracted archive in an isolated directory.

## File layout

| File | Role |
|------|------|
| `content.tex` | Main body, sections 1-10. Edit here. |
| `appendix.tex` | Supplementary material. Edit here. |
| `metadata.tex` | Title, author, affiliation with `\ifanon` toggle. |
| `build_named.tex` | Named-build wrapper; sets `\anonfalse` and loads `neurips_2024` in preprint mode. |
| `build_anonymous.tex` | Anonymous-build wrapper; sets `\anontrue` and loads `neurips_2024` in review mode. |
| `references.bib` | Bibliography. |
| `canonical_numbers.md` | Single-source-of-truth for every quantitative claim. |
| `sty/neurips_2024.sty` | Official NeurIPS 2024 style (vendored). |
| `figures/` | Generated figure outputs. |

## Canonical numbers

Every number, percentage, or count in `content.tex` / `appendix.tex`
must be tagged with a `% CN:<tag>` comment that maps to a row in
`canonical_numbers.md`. `scripts/verify_canonical_numbers.py` checks
tag definitions and cited source paths on every build. It does not
compare prose values with the table or detect untagged numbers; numerical
agreement still requires review against the cited evidence.

Example:
```latex
Claude Opus 4.6 achieves Pass@1 of 24.8\%  % CN:v8_claude_pass1
95\% Wilson CI [21.5--28.4].               % CN:v8_claude_pass1
```

## Figures

Figures 3, 4 and 5 are tracked historical snapshots generated from pilot
aggregates by `scripts/generate_paper_figures.py`. Their hashes are recorded in
`figures/SHA256SUMS`; CI verifies and compiles these snapshots. The complete
historical aggregate inputs are not distributed in the checkout, so a fresh
clone cannot independently regenerate these historical plots or statistics.
Do not regenerate them from an incomplete results directory. The current
engineering and local-model evidence has separate tracked artifacts cited in
the manuscript. Figures 1 and 2 are authored as TikZ in `content.tex`.

## Attribution

HealthCraft adapts the Corecraft architecture (arXiv:2602.16179v5). See
`docs/CORECRAFT_ATTRIBUTION.md` for the entity / tool / category mapping.
