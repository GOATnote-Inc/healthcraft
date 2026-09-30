#!/usr/bin/env python3
"""Run offline exposed reconciliation development controls, without model calls."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Support the documented absolute-script command from outside the repository.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from healthcraft.reconciliation.casebook_runner import run_casebook  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="New exclusive evidence directory"
    )
    parser.add_argument(
        "--casebook", type=Path, help="Explicit casebook, requires --expected-sha256"
    )
    parser.add_argument("--expected-sha256", help="Separately pinned canonical casebook digest")
    parser.add_argument(
        "--case", dest="case_ids", action="append", help="Select a case; repeat for multiple cases"
    )
    parser.add_argument("--mode", choices=("reference", "designated", "both"), default="both")
    args = parser.parse_args(argv)
    try:
        manifest = run_casebook(
            args.output_dir,
            casebook_path=args.casebook,
            expected_sha256=args.expected_sha256,
            case_ids=args.case_ids,
            mode=args.mode,
        )
    except (ValueError, OSError) as exc:
        print(
            json.dumps(
                {
                    "status": "preflight_or_io_error",
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                },
                allow_nan=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir.resolve()),
                **{
                    key: manifest[key]
                    for key in (
                        "status",
                        "counts",
                        "development_controls_matched",
                        "sources_unchanged",
                        "model_calls",
                        "benchmark_score",
                        "clinical_validated",
                    )
                },
            },
            indent=2,
            allow_nan=False,
        )
    )
    if any(outcome["status"] == "io_error" for outcome in manifest["outcomes"]):
        return 2
    return 0 if manifest["development_controls_matched"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
