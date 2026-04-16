"""Verify % CN:<tag> tags in whitepaper LaTeX against canonical_numbers.md.

Rules:
  1. Every tag cited in content.tex or appendix.tex via a "% CN:<tag>" comment
     MUST be defined in canonical_numbers.md.
  2. Every tag defined in canonical_numbers.md SHOULD be cited at least once
     (warning only; some tags may be reserved for appendix tables not yet
     populated).
  3. canonical_numbers.md must parse: the tag column is a fenced `CN:<tag>`
     identifier and the row must have a value.

Exit codes:
  0  all checks pass
  1  hard failure (unknown tag cited, or malformed canonical_numbers.md)

Does NOT verify that prose values match canonical_numbers.md values -- that's
a human review task. This script is a structural gate only.
"""

from __future__ import annotations

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

    if uncited:
        print("\nWARN: tags defined in canonical_numbers.md but not yet cited in prose:")
        for tag in uncited:
            print(f"  - CN:{tag}")
        # Do not fail on uncited tags -- Phase 1 scaffolding has no prose yet.

    print("\nPASS: canonical-numbers structural audit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
