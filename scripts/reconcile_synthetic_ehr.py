#!/usr/bin/env python3
"""Run original synthetic reconciliation controls; no model calls or benchmark score."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from healthcraft.reconciliation.bundle import run_development_suite


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="New exclusive evidence directory"
    )
    parser.add_argument(
        "--upstream", action="store_true", help="Run optional pinned Microsoft CSV verifier"
    )
    args = parser.parse_args()
    bundle = run_development_suite(args.output_dir, upstream=args.upstream)
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir.resolve()),
                "scheduled": len(bundle["roster"]),
                "recorded": len(bundle["trials"]),
                "development_controls_matched": bundle["development_controls_matched"],
                "sources_unchanged": bundle["sources_unchanged"],
                "upstream_requested": bundle["upstream_requested"],
                "upstream_completed_count": bundle["upstream_completed_count"],
                "upstream_all_completed": bundle["upstream_all_completed"],
                "model_calls": 0,
                "benchmark_score": None,
            },
            indent=2,
        )
    )
    complete = bundle["development_controls_matched"] and bundle["sources_unchanged"]
    if args.upstream:
        complete = complete and bundle["upstream_all_completed"]
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
