#!/usr/bin/env python3
"""Create a standalone offline review of saved HealthCraft evidence; no regrading."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from healthcraft.reporting import write_evidence_report  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Local results or diagnostic artifact directory")
    parser.add_argument("--output", type=Path, required=True, help="New HTML path; never overwrite")
    args = parser.parse_args(argv)
    try:
        report = write_evidence_report(args.source, args.output)
    except (OSError, ValueError) as exc:
        print(f"Evidence report error: {exc}", file=sys.stderr)
        return 2
    counts = report["counts"]
    print(
        f"Created {args.output}: {counts['selected_trials']} selected trials, "
        f"{counts['invalid']} malformed artifacts. Report creation is not an evaluation pass."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
