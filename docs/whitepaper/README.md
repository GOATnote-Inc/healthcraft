# HealthCraft Whitepaper

NeurIPS 2026 Datasets & Benchmarks Track submission, dual build
(named public release + anonymous blind review).

## Build

```bash
cd docs/whitepaper
make all             # both PDFs
make named           # public release (author visible)
make anonymous       # blind review (author redacted)
make verify          # CI gate: size, validity, identity leak, canonical numbers
make ci              # clean + all + verify
make arxiv           # package for arXiv upload
```

Requirements: TeX Live 2023+ with `pdflatex`, `bibtex`. Optional:
`pdftotext` (poppler-utils) for content checks during `verify`.

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
`canonical_numbers.md`. `scripts/verify_canonical_numbers.py` enforces
correspondence on every build.

Example:
```latex
Claude Opus 4.6 achieves Pass@1 of 24.8\%  % CN:v8_claude_pass1
95\% Wilson CI [21.5--28.4].               % CN:v8_claude_pass1
```

## Figures

Figures 3, 4, 5 are auto-generated from pilot `summary.json` files via
`scripts/generate_paper_figures.py`. Figures 1 and 2 are authored in-tree
as TikZ inside `content.tex`.

## Attribution

HealthCraft adapts the Corecraft architecture (arXiv:2602.16179v5). See
`docs/CORECRAFT_ATTRIBUTION.md` for the entity / tool / category mapping.
