"""Publication bundles include current dependencies and fail on broken builds."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def packager():
    spec = importlib.util.spec_from_file_location(
        "arxiv_packager", ROOT / "scripts/build_arxiv_submission.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def paper(tmp_path):
    root = tmp_path / "paper"
    for name, content in {
        "build_named.tex": r"\input{metadata}\input{content}\input{appendix}",
        "metadata.tex": "Named author",
        "content.tex": r"\includegraphics[width=1cm]{figures/current.pdf}",
        "appendix.tex": "Appendix",
        "references.bib": "@article{current,title={Current}}",
        "sty/neurips_2024.sty": "Required style",
        "figures/current.pdf": "%PDF-1.4 current figure",
        "figures/stale.pdf": "%PDF-1.4 obsolete figure",
        "output/build_named.bbl": r"\begin{thebibliography}{1}Current\end{thebibliography}",
        "arxiv_submission/stale.tex": "Must never ship",
        ".env": "PRIVATE_FIXTURE_NOT_A_SECRET",
    }.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return root


def test_current_minimal_bundle_includes_matching_bibliography(packager, paper, tmp_path):
    out = tmp_path / "bundle"
    result = packager.build_bundle(paper, out)
    with tarfile.open(out / "healthcraft-arxiv-source.tar.gz") as archive:
        names = set(archive.getnames())
        assert names == {
            "ms.tex",
            "ms.bbl",
            "content.tex",
            "appendix.tex",
            "metadata.tex",
            "references.bib",
            "sty/neurips_2024.sty",
            "figures/current.pdf",
        }
        assert (
            archive.extractfile("ms.bbl").read() == (paper / "output/build_named.bbl").read_bytes()
        )
        assert archive.extractfile("ms.tex").read() == (paper / "build_named.tex").read_bytes()
    assert result == json.loads((out / "source-manifest.json").read_text())
    assert set(result["files"]) == names


def test_bundle_is_reproducible_and_never_reuses_old_directory(packager, paper, tmp_path):
    packager.build_bundle(paper, tmp_path / "one")
    packager.build_bundle(paper, tmp_path / "two")
    assert (tmp_path / "one/healthcraft-arxiv-source.tar.gz").read_bytes() == (
        tmp_path / "two/healthcraft-arxiv-source.tar.gz"
    ).read_bytes()
    with pytest.raises((ValueError, FileExistsError)):
        packager.build_bundle(paper, tmp_path / "one")


@pytest.mark.parametrize("source", ["content.tex", "appendix.tex", "sty/neurips_2024.sty"])
@pytest.mark.parametrize("command", ["input", "include"])
def test_unshipped_tex_dependency_rejected_before_output(
    packager, paper, tmp_path, source, command
):
    extra = paper / "sections/new-results.tex"
    extra.parent.mkdir()
    extra.write_text("Required results source")
    (paper / source).write_text(f"\\{command}{{sections/new-results}}")
    out = tmp_path / "missing-dependency"
    with pytest.raises(ValueError, match="dependency"):
        packager.build_bundle(paper, out)
    assert not out.exists()


@pytest.mark.parametrize(
    "directive",
    [r"\input content", r"\input{\dynamicfile}", r"\include{../private}", r"\input{build_named}"],
)
def test_unsupported_dependency_form_is_not_silently_ignored(packager, paper, tmp_path, directive):
    (paper / "appendix.tex").write_text(directive)
    out = tmp_path / "unsupported-dependency"
    with pytest.raises(ValueError, match="dependency"):
        packager.build_bundle(paper, out)
    assert not out.exists()


def test_comments_and_packaged_literal_inputs_remain_supported(packager, paper, tmp_path):
    (paper / "build_named.tex").write_text(
        "% \\input{obsolete}\n"
        "\\input % source comment\n{metadata.tex}"
        "\\input{content}\\include{appendix}"
    )
    (paper / "content.tex").write_text("Text % \\citep{obsolete}\n")
    packager.build_bundle(paper, tmp_path / "valid-comments")


@pytest.mark.parametrize(
    "citation",
    [
        r"\cite{current}",
        r"\citep[see][p.~2]{current, other}",
        r"\citet*{current}",
        r"\Citep{current}",
        r"\citeauthor{current}",
        r"\citeyearpar{current}",
        r"\nocite{current}",
    ],
)
def test_citation_keys_must_exist_in_shipped_bibliography(packager, paper, tmp_path, citation):
    (paper / "appendix.tex").write_text(citation)
    bibliography = paper / "output/build_named.bbl"
    bibliography.write_text(r"\begin{thebibliography}{1}\bibitem{old}Old\end{thebibliography}")
    out = tmp_path / "stale-bibliography"
    with pytest.raises(ValueError, match="bibliography.*current"):
        packager.build_bundle(paper, out)
    assert not out.exists()
    bibliography.write_text(
        "\\begin{thebibliography}{2}\n"
        "\\bibitem[Author et~al.(2026)\nAuthor and {Other}]{current}Current\n"
        "\\bibitem{other}Other\\end{thebibliography}"
    )
    packager.build_bundle(paper, out)


@pytest.mark.parametrize("prefix", [r"Literal \% ", "Line break \\\\ % ignored\n"])
def test_tex_comment_handling_does_not_hide_active_citations(packager, paper, tmp_path, prefix):
    (paper / "content.tex").write_text(prefix + r"\citep{missing}")
    with pytest.raises(ValueError, match="bibliography.*missing"):
        packager.build_bundle(paper, tmp_path / "bad-citation")


@pytest.mark.parametrize("citation", [r"\citep{\keymacro}", r"\nocite{*}"])
def test_dynamic_or_wildcard_citations_require_explicit_supported_keys(
    packager, paper, tmp_path, citation
):
    (paper / "content.tex").write_text(citation)
    with pytest.raises(ValueError, match="citation"):
        packager.build_bundle(paper, tmp_path / "dynamic-citation")


@pytest.mark.parametrize("change", ["missing_bbl", "empty_bbl", "outside_figure", "symlink"])
def test_invalid_inputs_fail_before_output_creation(packager, paper, tmp_path, change):
    if change == "missing_bbl":
        (paper / "output/build_named.bbl").unlink()
    elif change == "empty_bbl":
        (paper / "output/build_named.bbl").write_text("")
    elif change == "outside_figure":
        (paper / "content.tex").write_text(r"\includegraphics{../private.pdf}")
        (paper.parent / "private.pdf").write_text("do not include")
    else:
        (paper / "figures/current.pdf").unlink()
        (paper / "figures/current.pdf").symlink_to(paper / ".env")
    out = tmp_path / "invalid"
    with pytest.raises((ValueError, OSError)):
        packager.build_bundle(paper, out)
    assert not out.exists()


@pytest.mark.parametrize("target", ["named", "anonymous"])
def test_make_does_not_suppress_bibtex_failure(tmp_path, target):
    shutil.copyfile(ROOT / "docs/whitepaper/Makefile", tmp_path / "Makefile")
    latex = tmp_path / "fake_latex"
    latex.write_text(
        f"#!{sys.executable}\n"
        "import pathlib,sys\n"
        "out=pathlib.Path('output');out.mkdir(exist_ok=True)\n"
        "name=pathlib.Path(sys.argv[-1]).stem\n"
        "(out/(name+'.pdf')).write_bytes(b'%PDF-1.4 fixture')\n"
    )
    latex.chmod(0o755)
    bibtex = tmp_path / "failed_bibtex"
    bibtex.write_text("#!/bin/sh\nexit 7\n")
    bibtex.chmod(0o755)
    (tmp_path / "references.bib").write_text("unused fixture")
    completed = subprocess.run(
        ["make", target, f"PDFLATEX={latex}", f"BIBTEX={bibtex}"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert completed.returncode != 0, "A failed bibliography build was reported successful"
    assert not (tmp_path / f"output/whitepaper_{target}.pdf").exists()


@pytest.mark.parametrize("verifier_exit", [0, 17])
def test_make_verify_propagates_canonical_audit_failure(tmp_path, verifier_exit):
    paper = tmp_path / "docs/whitepaper"
    paper.mkdir(parents=True)
    shutil.copyfile(ROOT / "docs/whitepaper/Makefile", paper / "Makefile")
    (paper / "output").mkdir()
    for label in ("named", "anonymous"):
        (paper / f"output/whitepaper_{label}.pdf").write_bytes(b"%PDF-" + b"x" * 100001)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "verify_canonical_numbers.py").write_text(f"raise SystemExit({verifier_exit})\n")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    pdf_text = binaries / "pdftotext"
    pdf_text.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "if sys.argv[1].endswith('whitepaper_named.pdf'): print('b@thegoatnote.com')\n"
    )
    pdf_text.chmod(0o755)
    env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ["PATH"])
    result = subprocess.run(
        ["make", "verify", f"PYTHON={sys.executable}"],
        cwd=paper,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if verifier_exit:
        assert result.returncode != 0, result.stdout
        assert "FAIL: canonical numbers mismatch" in result.stdout
        assert "PASS: Canonical numbers audit" not in result.stdout
        assert "PASS: All verification checks passed" not in result.stdout
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "PASS: Canonical numbers audit" in result.stdout
