"""Populate configs/rubrics/v9_deterministic_overlay.yaml from high-confidence
proposals in v9_migrations_proposed.yaml.

Filters: confidence == 'high' AND proposed_check != ''.
Transforms proposed schema -> overlay schema.
Flags subordinate-clause / conditional patterns for clinician review.

The header comment block of the overlay file is preserved verbatim; only the
`overlays:` list is regenerated.

Usage:
    python scripts/populate_v9_overlay.py
    python scripts/populate_v9_overlay.py --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROPOSALS_PATH = PROJECT_ROOT / "configs" / "rubrics" / "v9_migrations_proposed.yaml"
OVERLAY_PATH = PROJECT_ROOT / "configs" / "rubrics" / "v9_deterministic_overlay.yaml"

# Patterns suggesting the order verb is in a conditional/subordinate clause
# (i.e., the assertion describes a contingency, not a definite action by the
# agent). These entries still go into the overlay, but flagged for review.
_CONDITIONAL_PATTERNS = [
    re.compile(r"\bif\b.{0,80}\b(ordered|order|prescribed)\b", re.IGNORECASE),
    re.compile(r"\bwhen\b.{0,80}\b(ordered|order|prescribed)\b", re.IGNORECASE),
    re.compile(r"\b(only if|unless)\b", re.IGNORECASE),
    re.compile(
        r"\b(addressed|ensured|verified|confirmed|documented)\b.{0,120}\bordered\b", re.IGNORECASE
    ),
]


def _is_conditional(assertion: str) -> str | None:
    for pat in _CONDITIONAL_PATTERNS:
        m = pat.search(assertion)
        if m:
            return m.group(0)
    return None


def transform(proposal: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "criterion_id": proposal["criterion_id"],
        "verification": proposal["proposed_verification"],
        "check": proposal["proposed_check"],
        "original_assertion": proposal["original_assertion"],
        "migration_confidence": proposal["confidence"],
        "migration_reason": proposal["reason"],
    }
    flag = _is_conditional(proposal["original_assertion"])
    if flag:
        entry["migration_review_needed"] = True
        entry["migration_review_note"] = (
            f"Conditional/subordinate clause detected ({flag!r}); verify the "
            "order verb describes an agent action rather than a hypothetical."
        )
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Print summary only")
    args = parser.parse_args()

    proposals_data = yaml.safe_load(PROPOSALS_PATH.read_text(encoding="utf-8"))
    proposals = proposals_data["proposals"]

    kept = [p for p in proposals if p["confidence"] == "high" and p["proposed_check"].strip()]
    entries = [transform(p) for p in kept]
    flagged = [e for e in entries if e.get("migration_review_needed")]

    print(f"High-confidence proposals: {len(kept)}")
    print(f"  -> overlay entries:      {len(entries)}")
    print(f"  -> flagged for review:   {len(flagged)}")
    if flagged:
        print("\nFlagged entries (conditional/subordinate clause):")
        for e in flagged:
            print(f"  - {e['criterion_id']}: {e['original_assertion'][:100]}")

    if args.dry_run:
        return 0

    # Preserve header, replace trailing `overlays: []` block with populated list
    original_text = OVERLAY_PATH.read_text(encoding="utf-8")

    # Serialize entries under `overlays:` key
    overlay_payload = yaml.safe_dump(
        {"overlays": entries}, sort_keys=False, default_flow_style=False, width=120
    )

    # Split original: keep everything up to and including the `overlays:` line,
    # but replace the value with the populated list.
    # Marker: the existing file has "overlays: []" as the last populated line.
    marker = "overlays: []"
    idx = original_text.rfind(marker)
    if idx < 0:
        # Fallback: find `overlays:` at start of a line
        match = re.search(r"^overlays:.*$", original_text, flags=re.MULTILINE)
        if not match:
            print("ERROR: could not locate `overlays:` in existing overlay file", file=sys.stderr)
            return 1
        idx = match.start()

    header = original_text[:idx].rstrip() + "\n\n"
    new_text = header + overlay_payload

    OVERLAY_PATH.write_text(new_text, encoding="utf-8")
    print(f"\nWrote {len(entries)} entries to {OVERLAY_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
