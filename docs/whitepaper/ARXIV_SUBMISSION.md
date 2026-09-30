# arXiv replacement package

This package updates **arXiv:2605.21496**, *HealthCraft: A Reinforcement
Learning Safety Environment for Emergency Medicine*, by **Brandon Dent**.
The [existing arXiv record](https://arxiv.org/abs/2605.21496) identifies the
primary category as **cs.LG**, with **cs.AI** and **cs.CL** cross-lists. Its
linked paper license is CC BY 4.0. Preserve these existing metadata choices
for this replacement. The software remains Apache 2.0.

## Files

Download the [GitHub publication release](https://github.com/GOATnote-Inc/healthcraft/releases/tag/healthcraft-2026-09-30).

| File | Purpose |
| --- | --- |
| `healthcraft-paper.pdf` | Named manuscript, including appendices |
| `healthcraft-arxiv-source.tar.gz` | Upload this source archive to arXiv |
| `source-manifest.json` | Hashes of archived sources and source archive |
| `submission-metadata.txt` | Copy-ready title, author, abstract and change comment |
| `SHA256SUMS` | Checksums of the release assets |
| `publication-validation.json` | Build, test and publication validation receipt |

The top-level TeX file is **`ms.tex`** and the engine is **pdfLaTeX**. The
archive includes `ms.bbl`, `references.bib`, the local style and only the
referenced figure PDFs. The final paper PDF and these instructions are
separate release assets; do not add them to the source archive.
[arXiv's TeX instructions](https://info.arxiv.org/help/submit_tex.html)
describe supported processors and source-file requirements.

## Replace the existing article

1. Sign in to the author account and choose **Replace** for `2605.21496`.
2. Upload `healthcraft-arxiv-source.tar.gz`. Select `ms.tex` and pdfLaTeX
   if the submission interface asks for them.
3. Copy the title, author, revised abstract and replacement comment from
   `submission-metadata.txt`. Retain useful existing comments. Keep journal
   reference and external DOI fields unchanged unless independently warranted.
4. View arXiv's generated PDF and check the title, author, equations, tables,
   figures, references and appendices against `healthcraft-paper.pdf`.
5. Complete the author's submission attestations and submit the replacement.

This follows the [official replacement procedure](https://info.arxiv.org/help/replace.html).
GitHub publication does not itself update arXiv; the release prepares the
replacement materials. The author-account upload is the remaining submission
step, not a human-review gate on the software or paper release.

## Rebuild locally

From the repository root, with TeX Live and Poppler installed:

```bash
python -m pip install -c constraints-security.txt -e .
make -C docs/whitepaper all verify
make -C docs/whitepaper arxiv ARXIV_OUT=output/arxiv-new
mkdir /tmp/healthcraft-arxiv-check
tar -xzf docs/whitepaper/output/arxiv-new/healthcraft-arxiv-source.tar.gz \
  -C /tmp/healthcraft-arxiv-check
cd /tmp/healthcraft-arxiv-check
pdflatex -interaction=nonstopmode -halt-on-error -no-shell-escape ms.tex
bibtex ms
pdflatex -interaction=nonstopmode -halt-on-error -no-shell-escape ms.tex
pdflatex -interaction=nonstopmode -halt-on-error -no-shell-escape ms.tex
```

Use fresh output and extraction directories. Packaging refuses to overwrite
an existing directory. Compilation reproduces the paper from the supplied
sources and frozen figures; it does not rerun historical model evaluations.

## Scope of this revision

The revision adds automated engineering methods, reproducible local-model
execution evidence, retained failure accounting and explicit limits on clinical
interpretation. It distinguishes historical, superseded benchmark scores from
the new unassessed development cohort. The work is authored by one physician
engineer using automated tools. Independent clinical studies and comparative
operator studies remain research directions, not publication prerequisites.
