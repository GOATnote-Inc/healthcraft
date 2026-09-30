#!/usr/bin/env python3
"""Run a pinned, free local-model source-reconciliation development cohort."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from healthcraft.reconciliation.model_cohort import run_model_cohort  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--casebook", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = run_model_cohort(
            args.plan,
            args.output_dir,
            expected_sha256=args.expected_sha256,
            casebook_path=args.casebook,
        )
    except (ValueError, OSError) as exc:
        print(
            json.dumps(
                {"status": "preflight_or_io_error", "type": type(exc).__name__, "message": str(exc)}
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                key: manifest[key]
                for key in ("status", "counts", "sources_unchanged", "benchmark_score")
            },
            indent=2,
        )
    )
    return 0 if manifest["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
