#!/usr/bin/env python3
"""Run six ungraded mechanical roster references through actual MCP handlers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from healthcraft.tasks.roster_execution import run_roster_references


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, help="Create a new report; never overwrite")
    args = parser.parse_args(argv)
    try:
        if args.output and args.output.exists():
            raise FileExistsError(f"Report already exists: {args.output}")
        report = run_roster_references(seed=args.seed)
        rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(rendered)
        else:
            print(rendered, end="")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Roster reference certificate error: {exc}", file=sys.stderr)
        return 2
    return 0 if report["mechanical_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
