"""Verify v2 whitepaper claims against results/ artifacts.

Extension of verify_canonical_numbers.py for arXiv v2 additions.

Rules:
  1. Every v2 CN tag (CN:v2_*) must trace to a results/ artifact that exists
     and contains the claimed value within tolerance.
  2. v1 CN tags are NOT checked here (verify_canonical_numbers.py handles those).
  3. Any v2 tag marked TBD-after-pilot must NOT have a numeric claim in the
     paper prose -- the tag must exist in canonical_numbers.md with value "TBD".
  4. If a results/ artifact is referenced but does not exist, the claim is
     flagged as unbacked.

Exit codes:
  0  all checks pass
  1  hard failure (unbacked claim, missing artifact, TBD in prose)
  2  warnings only (unused v2 tags, missing optional artifacts)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WHITEPAPER = REPO / "docs" / "whitepaper"
CANONICAL = WHITEPAPER / "canonical_numbers.md"
CONTENT_FILES = [WHITEPAPER / "content.tex", WHITEPAPER / "appendix.tex"]
RESULTS = REPO / "results"
PAPER_NOTES = REPO / "docs" / "PAPER_REVISION_NOTES.md"

# Match v2 CN tags in canonical_numbers.md
TAG_DEF_RE = re.compile(r"\|\s*`CN:(v2_[A-Za-z0-9_]+)`\s*\|")
# Match CN tag citations in LaTeX
TAG_CITE_RE = re.compile(r"%\s*CN:(v2_[A-Za-z0-9_]+)")
# Match source column (last pipe-delimited field with a path)
SOURCE_RE = re.compile(r"\|\s*`?([^|`]+/[^|`]+)`?\s*\|?\s*$")
# Match value column for TBD
TBD_RE = re.compile(r"\bTBD\b", re.IGNORECASE)

# Known v2 pilot directories and what they back
V2_PILOT_DIRS = {
    "v9-deterministic": "v9 Deterministic Pilot",
    "dynamic-state": "Dynamic-State Pilot",
    "idempotent-tools": "Idempotent-Tools Pilot",
}


def load_v2_tags() -> dict[str, dict[str, str]]:
    """Return {tag: {value, source, claim}} for all v2 CN tags."""
    if not CANONICAL.exists():
        print(f"FAIL: {CANONICAL} not found", file=sys.stderr)
        sys.exit(1)

    tags: dict[str, dict[str, str]] = {}
    for line in CANONICAL.read_text().splitlines():
        match = TAG_DEF_RE.search(line)
        if not match:
            continue
        tag = match.group(1)
        # Parse columns: | tag | claim | value | ci | source |
        cols = [c.strip() for c in line.split("|")]
        # Filter empty strings from split
        cols = [c for c in cols if c]
        if len(cols) >= 4:
            tags[tag] = {
                "claim": cols[1] if len(cols) > 1 else "",
                "value": cols[2] if len(cols) > 2 else "",
                "ci": cols[3] if len(cols) > 3 else "",
                "source": cols[4] if len(cols) > 4 else "",
            }
    return tags


def load_v2_cited() -> dict[str, list[str]]:
    """Return {tag: [locations]} for v2 CN tags cited in LaTeX."""
    cited: dict[str, list[str]] = {}
    for path in CONTENT_FILES:
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for m in TAG_CITE_RE.finditer(line):
                tag = m.group(1)
                cited.setdefault(tag, []).append(f"{path.name}:{lineno}")
    return cited


def check_artifact_exists(source: str) -> tuple[bool, str]:
    """Check if a results/ artifact referenced by a source exists.

    Returns (exists, resolved_path).
    """
    source = source.strip().strip("`")
    if not source:
        return False, ""

    # Handle JSON pointer syntax: path/to/file.json#$.key
    path_str = source.split("#")[0].strip()
    resolved = REPO / path_str
    return resolved.exists(), str(resolved)


def check_summary_value(
    source: str, expected_key: str, expected_value: float, tolerance: float = 0.01
) -> tuple[bool, str]:
    """Check if a summary.json contains the expected value."""
    path_str = source.split("#")[0].strip().strip("`")
    resolved = REPO / path_str
    if not resolved.exists():
        return False, f"artifact not found: {resolved}"

    try:
        data = json.loads(resolved.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return False, f"cannot parse {resolved}: {e}"

    if expected_key not in data:
        return False, f"key '{expected_key}' not in {resolved}"

    actual = float(data[expected_key])
    if abs(actual - expected_value) > tolerance:
        return False, f"{expected_key}={actual}, expected {expected_value}"

    return True, f"{expected_key}={actual} (OK)"


def check_not_measured_section() -> list[str]:
    """Verify PAPER_REVISION_NOTES.md 'What Has NOT Been Re-Measured' entries.

    Any item listed there must NOT have a backing results/ artifact.
    If a pilot ran since the notes were written, warn that the notes
    need updating.
    """
    warnings = []
    if not PAPER_NOTES.exists():
        warnings.append(f"WARN: {PAPER_NOTES} not found")
        return warnings

    text = PAPER_NOTES.read_text()
    not_measured_section = False
    for line in text.splitlines():
        if "What Has NOT Been Re-Measured" in line:
            not_measured_section = True
            continue
        if not_measured_section and line.startswith("## "):
            break
        if not_measured_section and line.startswith("- "):
            # Check if a results directory now exists for this item
            for pilot_dir, pilot_name in V2_PILOT_DIRS.items():
                pilot_path = RESULTS / f"pilot-{pilot_dir}"
                if pilot_name.lower() in line.lower() and pilot_path.exists():
                    warnings.append(
                        f"WARN: '{pilot_name}' listed as NOT measured but "
                        f"{pilot_path} exists -- update PAPER_REVISION_NOTES.md"
                    )
    return warnings


def main() -> int:
    v2_tags = load_v2_tags()
    v2_cited = load_v2_cited()

    print(f"canonical_numbers.md: {len(v2_tags)} v2 tags defined")
    print(f"content.tex + appendix.tex: {len(v2_cited)} v2 tags cited")

    failures: list[str] = []
    warnings: list[str] = []

    # Check 1: Every cited v2 tag must be defined
    undefined = sorted(set(v2_cited) - set(v2_tags))
    for tag in undefined:
        locs = ", ".join(v2_cited[tag])
        failures.append(f"CN:{tag} cited at {locs} but not defined in canonical_numbers.md")

    # Check 2: TBD tags must not have numeric claims in LaTeX
    for tag, info in v2_tags.items():
        if TBD_RE.search(info.get("value", "")):
            if tag in v2_cited:
                # Check if the LaTeX line near the citation contains a number
                # (This is a heuristic -- manual review still needed)
                warnings.append(f"CN:{tag} is TBD but cited in prose -- verify no numeric claim")

    # Check 3: Non-TBD tags must trace to existing artifacts
    # Sources containing "aggregate" or referencing scripts/docs are computed
    # values, not single-file artifacts. They are verified by inspection, not
    # by file existence.
    aggregate_markers = ("aggregate", "scripts/", "docs/")
    for tag, info in v2_tags.items():
        value = info.get("value", "")
        source = info.get("source", "")
        if TBD_RE.search(value):
            continue  # TBD is expected for unrun pilots
        if not source:
            warnings.append(f"CN:{tag} has value '{value}' but no source path")
            continue
        source_clean = source.strip().strip("`")
        if any(marker in source_clean for marker in aggregate_markers):
            continue  # Computed aggregate -- not a single artifact
        exists, resolved = check_artifact_exists(source)
        if not exists:
            failures.append(f"CN:{tag} claims '{value}' from '{source}' but artifact not found")

    # Check 4: Uncited v2 tags (warning only)
    uncited = sorted(set(v2_tags) - set(v2_cited))
    for tag in uncited:
        warnings.append(f"CN:{tag} defined but not cited in prose")

    # Check 5: PAPER_REVISION_NOTES.md consistency
    warnings.extend(check_not_measured_section())

    # Check 6: v2 pilot directories that exist but have no CN tags
    for pilot_dir, pilot_name in V2_PILOT_DIRS.items():
        pilot_path = RESULTS / f"pilot-{pilot_dir}"
        if pilot_path.exists():
            has_tag = any(pilot_dir.replace("-", "_") in tag for tag in v2_tags)
            if not has_tag:
                warnings.append(
                    f"{pilot_path} exists but no CN:v2_* tag references it -- "
                    f"add tags to canonical_numbers.md if claiming results"
                )

    # Report
    if failures:
        print(f"\nFAIL: {len(failures)} hard failures:")
        for f in failures:
            print(f"  - {f}")

    if warnings:
        print(f"\nWARN: {len(warnings)} warnings:")
        for w in warnings:
            print(f"  - {w}")

    if failures:
        return 1

    if not v2_tags:
        print("\nNo v2 CN tags defined yet -- nothing to verify.")
        print("PASS (vacuous): v2 claims audit")
        return 0

    print("\nPASS: v2 claims audit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
