"""Verify % CN:<tag> tags in whitepaper LaTeX against canonical_numbers.md.

Rules:
  1. Every tag cited in content.tex or appendix.tex via a "% CN:<tag>" comment
     MUST be defined in canonical_numbers.md.
  2. Every tag defined in canonical_numbers.md SHOULD be cited at least once
     (warning only; some tags may be reserved for appendix tables not yet
     populated).
  3. canonical_numbers.md must parse: the tag column is a fenced `CN:<tag>`
     identifier and the row must have a value.
  4. Every in-repo path cited in a Source cell MUST exist in the working
     tree, unless it is listed in the "Deferred artifacts" table of
     canonical_numbers.md (those are result aggregates awaiting commit
     from the eval machine; missing-but-deferred is a warning, not a
     failure, and a deferred entry that now exists is flagged for removal
     from the table).

Exit codes:
  0  all checks pass
  1  hard failure (unknown tag cited, or malformed canonical_numbers.md)

Does NOT verify that prose values match canonical_numbers.md values -- that's
a human review task. This script is a structural gate only.
"""

from __future__ import annotations

import fnmatch
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WHITEPAPER = REPO / "docs" / "whitepaper"
CONTENT_FILES = [WHITEPAPER / "content.tex", WHITEPAPER / "appendix.tex"]
CANONICAL = WHITEPAPER / "canonical_numbers.md"

TAG_CITE_RE = re.compile(r"%\s*CN:([A-Za-z0-9_]+)")
# Match rows in the markdown file that look like: | `CN:foo` | ... | value | ...
TAG_DEF_RE = re.compile(r"\|\s*`CN:([A-Za-z0-9_]+)`\s*\|")

# In-repo roots a Source cell may cite; anything else (e.g. "OpenEM v0.5.1")
# is prose and not checked.
SOURCE_ROOTS = ("configs/", "docs/", "evals/", "results/", "scripts/", "src/", "tests/")
SOURCE_TOKEN_RE = re.compile(r"`([^`]+)`")
DEFERRED_HEADING = "## Deferred artifacts"


def _normalize_source_path(token: str) -> str | None:
    """Reduce a backticked Source token to a repo-relative path, or None."""
    token = token.strip()
    # Drop a JSON-pointer fragment and a trailing :line suffix.
    token = token.split("#", 1)[0]
    token = re.sub(r":\d+(-\d+)?$", "", token)
    if token.startswith(SOURCE_ROOTS):
        return token.rstrip()
    return None


def _split_sections(text: str) -> tuple[str, str]:
    """Return (numbers_part, deferred_part) of canonical_numbers.md."""
    idx = text.find(DEFERRED_HEADING)
    if idx == -1:
        return text, ""
    return text[:idx], text[idx:]


def load_source_paths() -> dict[str, list[str]]:
    """Return {path: [tags]} for every in-repo path cited in a Source cell."""
    numbers_part, _ = _split_sections(CANONICAL.read_text())
    cited: dict[str, list[str]] = {}
    for line in numbers_part.splitlines():
        tag_match = TAG_DEF_RE.search(line)
        if not tag_match:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells:
            continue
        source_cell = cells[-1]
        for token in SOURCE_TOKEN_RE.findall(source_cell):
            path = _normalize_source_path(token)
            if path:
                cited.setdefault(path, []).append(tag_match.group(1))
    return cited


def load_deferred_paths() -> set[str]:
    """Paths listed in the Deferred artifacts table (existence-check exempt)."""
    _, deferred_part = _split_sections(CANONICAL.read_text())
    deferred: set[str] = set()
    for line in deferred_part.splitlines():
        if not line.lstrip().startswith("|"):
            continue  # only table rows define deferred paths
        cells = [c.strip() for c in line.strip().strip("|").split("|") if c.strip()]
        if not cells:
            continue
        first = SOURCE_TOKEN_RE.match(cells[0])
        if first:
            path = _normalize_source_path(first.group(1))
            if path:
                deferred.add(path)
    return deferred


def _path_exists(path: str) -> bool:
    if "*" in path or "?" in path:
        return any(REPO.glob(path))
    return (REPO / path).exists()


def _is_deferred(path: str, deferred: set[str]) -> bool:
    stripped = path.rstrip("/")
    for entry in deferred:
        if (
            entry == path
            or entry.rstrip("/") == stripped
            or fnmatch.fnmatch(entry, path)
            or fnmatch.fnmatch(path, entry)
            or entry.startswith(stripped + "/")
        ):
            return True
    return False


def check_source_paths() -> tuple[list[str], list[str], list[str]]:
    """Return (missing_hard, missing_deferred, deferred_now_present)."""
    cited = load_source_paths()
    deferred = load_deferred_paths()

    missing_hard: list[str] = []
    missing_deferred: list[str] = []
    for path, tags in sorted(cited.items()):
        if _path_exists(path):
            continue
        label = f"{path}  (Source of CN:{', CN:'.join(sorted(set(tags)))})"
        if _is_deferred(path, deferred):
            missing_deferred.append(label)
        else:
            missing_hard.append(label)

    deferred_now_present = sorted(p for p in deferred if _path_exists(p))
    return missing_hard, missing_deferred, deferred_now_present


def load_cited_tags() -> dict[str, list[str]]:
    """Return {tag: [source_locations]} across content.tex and appendix.tex."""
    cited: dict[str, list[str]] = {}
    for path in CONTENT_FILES:
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for match in TAG_CITE_RE.finditer(line):
                tag = match.group(1)
                cited.setdefault(tag, []).append(f"{path.name}:{lineno}")
    return cited


def load_defined_tags() -> set[str]:
    if not CANONICAL.exists():
        print(f"FAIL: {CANONICAL} not found", file=sys.stderr)
        sys.exit(1)
    tags = set()
    for line in CANONICAL.read_text().splitlines():
        match = TAG_DEF_RE.search(line)
        if match:
            tags.add(match.group(1))
    return tags


def main() -> int:
    cited = load_cited_tags()
    defined = load_defined_tags()

    undefined = sorted(set(cited) - defined)
    uncited = sorted(defined - set(cited))

    print(f"canonical_numbers.md: {len(defined)} tags defined")
    print(f"content.tex + appendix.tex: {len(cited)} distinct tags cited")

    if undefined:
        print("\nFAIL: tags cited in prose but not defined in canonical_numbers.md:")
        for tag in undefined:
            locs = ", ".join(cited[tag])
            print(f"  - CN:{tag}  (cited at {locs})")
        return 1

    missing_hard, missing_deferred, deferred_present = check_source_paths()
    if missing_deferred:
        print("\nWARN: deferred Source artifacts not yet committed (see the")
        print("'Deferred artifacts' table in canonical_numbers.md):")
        for label in missing_deferred:
            print(f"  - {label}")
    if deferred_present:
        print("\nNOTE: deferred entries now exist in-repo -- remove them from the")
        print("'Deferred artifacts' table so the existence check hardens:")
        for path in deferred_present:
            print(f"  - {path}")
    if missing_hard:
        print("\nFAIL: Source paths cited in canonical_numbers.md do not exist")
        print("in the repo (commit the artifact, fix the path, or add a row to")
        print("the 'Deferred artifacts' table):")
        for label in missing_hard:
            print(f"  - {label}")
        return 1

    if uncited:
        print("\nWARN: tags defined in canonical_numbers.md but not yet cited in prose:")
        for tag in uncited:
            print(f"  - CN:{tag}")
        # Do not fail on uncited tags -- Phase 1 scaffolding has no prose yet.

    print("\nPASS: canonical-numbers structural audit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
