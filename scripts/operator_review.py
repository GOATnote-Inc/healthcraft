#!/usr/bin/env python3
"""Build offline operator tutorials and preserve unadjudicated review responses."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from healthcraft.operator_review import (  # noqa: E402
    build_operator_packet,
    import_operator_response,
)
from healthcraft.reconciliation.terminal import _json_object  # noqa: E402


def _case_roster(entries: list[str]) -> dict[str, Path]:
    roster: dict[str, Path] = {}
    folded: set[str] = set()
    for entry in entries:
        case_id, separator, location = entry.partition("=")
        if not separator or not case_id or not location:
            raise ValueError("Each --case must contain CASE_ID=BUNDLE_DIR with both values")
        if case_id.casefold() in folded:
            raise ValueError(f"Duplicate case identifier: {case_id}")
        folded.add(case_id.casefold())
        roster[case_id] = Path(location)
    return roster


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Create a new tutorial packet with blank answers")
    build.add_argument(
        "--case",
        action="append",
        required=True,
        metavar="CASE_ID=BUNDLE_DIR",
        help="Explicit case identifier and source explanation bundle; repeat in presentation order",
    )
    build.add_argument("--protocol", type=Path, required=True)
    build.add_argument("--assignment", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True, help="New directory")
    submit = commands.add_parser(
        "import", help="Preserve a response without adjudicating its answers"
    )
    submit.add_argument("manifest", type=Path, help="Packet manifest.json")
    submit.add_argument("response", type=Path, help="Exported or edited response JSON")
    submit.add_argument("--output-dir", type=Path, required=True, help="New receipt directory")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            cases = _case_roster(args.case)
            result = build_operator_packet(
                cases,
                args.output_dir,
                protocol=_json_object(args.protocol.read_bytes()),
                assignment=_json_object(args.assignment.read_bytes()),
            )
            summary = {
                "status": "created",
                "packet_id": result["packet_id"],
                "assigned_cases": len(result["cases"]),
                "assigned_axes": len(result["cases"]) * 6,
                "output_dir": str(args.output_dir.resolve()),
                "clinical_validation": "not_established",
            }
        else:
            result = import_operator_response(args.manifest, args.response, args.output_dir)
            summary = {
                "status": result["status"],
                "counts": result["counts"],
                "output_dir": str(args.output_dir.resolve()),
                "adjudication": "not_performed",
                "clinical_validation": "not_established",
            }
    except (OSError, ValueError) as exc:
        print(f"Operator review error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True, allow_nan=False))
    return 1 if summary["status"] == "invalid_submission" else 0


if __name__ == "__main__":
    raise SystemExit(main())
