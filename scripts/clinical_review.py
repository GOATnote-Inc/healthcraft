#!/usr/bin/env python3
"""Build offline masked review packets or import unvalidated human submissions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from healthcraft.clinical_review import (  # noqa: E402
    _read,
    build_review_packet,
    import_review_response,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Create a new assignment with blank responses")
    build.add_argument(
        "sources", nargs="+", type=Path, help="Trajectory files or one results directory"
    )
    build.add_argument("--protocol", required=True, type=Path, help="Predeclared protocol JSON")
    build.add_argument(
        "--assignment", required=True, type=Path, help="Private reviewer assignment JSON"
    )
    build.add_argument(
        "--output-dir", required=True, type=Path, help="New directory; never overwrite"
    )
    submit = commands.add_parser("import", help="Validate and retain a reviewer submission")
    submit.add_argument("manifest", type=Path, help="Private coordinator/manifest.json")
    submit.add_argument("response", type=Path, help="Completed response JSON")
    submit.add_argument("--output-dir", required=True, type=Path, help="New receipt directory")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            sources = args.sources
            if len(sources) == 1 and sources[0].is_dir():
                sources = sources[0]
            result = build_review_packet(
                sources,
                args.output_dir,
                protocol=_read(args.protocol)[0],
                reviewer_assignment=_read(args.assignment)[0],
            )
            print(
                f"Created {len(result['items'])} assigned opportunities; clinical review pending. "
                f"Share ONLY {args.output_dir / 'reviewer'}. Keep coordinator files private."
            )
        else:
            result = import_review_response(args.manifest, args.response, args.output_dir)
            counts = result["counts"]
            print(
                f"Recorded unvalidated submission: {counts['assigned']} assigned, "
                f"{counts['assessed']} assessed, {counts['unassessed']} unassessed, "
                f"{counts['pending']} pending. Clinical validation is not established."
            )
    except (OSError, ValueError) as exc:
        print(f"Clinical review error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
