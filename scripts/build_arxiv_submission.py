"""Create a minimal, reproducible arXiv source archive from a built paper."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

PAPER = Path(__file__).resolve().parents[1] / "docs/whitepaper"
FIGURE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\s*\{([^}]+)\}")
DEPENDENCY = re.compile(r"(?<!\\)(?:\\\\)*\\(?:input|include)(?![A-Za-z@])")
CITATION = re.compile(
    r"(?<!\\)(?:\\\\)*\\(?:[Cc]ite(?:[pt]|alt|alp|author|year(?:par)?)?|nocite)"
    r"\*?(?![A-Za-z@])"
)
LITERAL_ARGUMENT = re.compile(r"\s*\{([^{}\\%]+)\}")
CITATION_ARGUMENT = re.compile(r"\s*(?:\[[^\[\]]*\]\s*){0,2}\{([^{}\\%]+)\}")
BIBITEM = re.compile(r"\\bibitem\s*(?:\[[^\]]*\]\s*)?\{([^{}\\%]+)\}")


def _without_comments(text: str) -> str:
    """Remove TeX line comments, retaining escaped percent signs and newlines."""
    lines = []
    for line in text.splitlines(keepends=True):
        for index, character in enumerate(line):
            if character != "%":
                continue
            preceding = index - 1
            while preceding >= 0 and line[preceding] == "\\":
                preceding -= 1
            if (index - preceding - 1) % 2 == 0:
                line = line[:index] + "\n"
                break
        lines.append(line)
    return "".join(lines)


def _validate_tex_sources(payloads: dict[str, bytes]) -> dict[str, str]:
    """Check the fixed paper's literal input closure and natbib citation keys.

    Dynamic/unbraced inputs and wildcard/macro citation keys are unsupported.
    This is deliberately not a TeX interpreter or proof of bibliography content
    freshness; release validation must still compile the isolated archive.
    """
    sources = {
        name: _without_comments(raw.decode("utf-8"))
        for name, raw in payloads.items()
        if Path(name).suffix in {".tex", ".sty", ".bbl"}
    }
    cited: set[str] = set()
    for name, text in sources.items():
        for command in DEPENDENCY.finditer(text):
            argument = LITERAL_ARGUMENT.match(text, command.end())
            if argument is None:
                raise ValueError(f"Use a literal braced TeX dependency in {name}")
            dependency = Path(argument.group(1).strip())
            if not dependency.suffix:
                dependency = dependency.with_suffix(".tex")
            if (
                dependency.is_absolute()
                or ".." in dependency.parts
                or dependency.as_posix() not in sources
            ):
                raise ValueError(f"Unpackaged TeX dependency in {name}: {argument.group(1)}")
        for command in CITATION.finditer(text):
            argument = CITATION_ARGUMENT.match(text, command.end())
            if argument is None:
                raise ValueError(f"Use explicit literal citation keys in {name}")
            keys = [key.strip() for key in argument.group(1).split(",")]
            if any(not re.fullmatch(r"[^\s,{}\\%*]+", key) for key in keys):
                raise ValueError(f"Unsupported citation keys in {name}: {argument.group(1)}")
            cited.update(keys)
    available = {match.group(1).strip() for match in BIBITEM.finditer(sources["ms.bbl"])}
    missing = cited - available
    if missing:
        raise ValueError(
            "Rebuild bibliography; missing citation keys: " + ", ".join(sorted(missing))
        )
    return sources


def build_bundle(paper_dir: Path, output_dir: Path) -> dict:
    """Snapshot required sources, refusing stale destinations or missing inputs."""
    paper = Path(paper_dir).resolve()
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError(f"Use a new output directory: {output}")

    def read_source(name: str) -> bytes:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Source must stay inside the paper directory: {name}")
        path = paper / relative
        if any(p.is_symlink() for p in (path, *path.parents) if p != paper):
            raise ValueError(f"Source symlinks are not supported: {name}")
        value = path.read_bytes()
        if not value.strip():
            raise ValueError(f"Empty required source: {name}")
        return value

    mapping = {
        "ms.tex": "build_named.tex",
        "ms.bbl": "output/build_named.bbl",
        "content.tex": "content.tex",
        "appendix.tex": "appendix.tex",
        "metadata.tex": "metadata.tex",
        "references.bib": "references.bib",
        "sty/neurips_2024.sty": "sty/neurips_2024.sty",
    }
    payloads = {name: read_source(source) for name, source in mapping.items()}
    sources = _validate_tex_sources(payloads)
    for name in ("ms.tex", "content.tex", "appendix.tex", "metadata.tex"):
        for figure in FIGURE.findall(sources[name]):
            if not figure.startswith("figures/") or Path(figure).suffix not in {
                ".pdf",
                ".png",
                ".jpg",
                ".jpeg",
            }:
                raise ValueError(f"Use an explicit supported figure path: {figure}")
            payloads[figure] = read_source(figure)

    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0, filename="") as zipped:
        with tarfile.open(fileobj=zipped, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, raw in sorted(payloads.items()):
                entry = tarfile.TarInfo(name)
                entry.size = len(raw)
                entry.mode = 0o644
                archive.addfile(entry, io.BytesIO(raw))
    archived = buffer.getvalue()
    manifest = {
        "schema_version": "healthcraft-arxiv-source/v1",
        "main_file": "ms.tex",
        "engine": "pdflatex",
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(payloads.items())},
        "archive_sha256": hashlib.sha256(archived).hexdigest(),
    }
    output.mkdir(parents=True, exist_ok=False)
    (output / "healthcraft-arxiv-source.tar.gz").write_bytes(archived)
    (output / "source-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-dir", type=Path, default=PAPER)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build_bundle(args.paper_dir, args.output_dir)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"arXiv packaging failed: {exc}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
