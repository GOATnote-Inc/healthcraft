#!/usr/bin/env python3
"""Report selected offline grader counterexamples; exit 1 on label mismatches."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from healthcraft.tasks.challenges import DEFAULT_CHALLENGES, run_challenges
from healthcraft.tasks.rubrics import VALID_RUBRIC_CHANNELS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_CHALLENGES)
    parser.add_argument("--rubric-channel", choices=sorted(VALID_RUBRIC_CHANNELS), default="v10")
    parser.add_argument("--output", type=Path, help="Create a new JSON report; never overwrite")
    parser.add_argument(
        "--report-only", action="store_true", help="Allow reported label mismatches"
    )
    args = parser.parse_args()
    try:
        report = run_challenges(args.fixture, rubric_channel=args.rubric_channel)
        rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(rendered)
        else:
            print(rendered, end="")
    except (OSError, ValueError) as exc:
        print(f"Challenge report error: {exc}", file=sys.stderr)
        return 2
    summary = report["summary"]
    if summary["errors"]:
        return 2
    if not args.report_only and (summary["false_pass"] or summary["false_fail"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
