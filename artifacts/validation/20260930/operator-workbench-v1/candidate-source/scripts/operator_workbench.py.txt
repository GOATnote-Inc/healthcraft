#!/usr/bin/env python3
"""Build or verify a lighter review view without changing its original assignment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from healthcraft.operator_workbench import build_workbench, validate_workbench  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Issue a new offline view of a validated v2 packet")
    build.add_argument("manifest", type=Path, help="Original issuer manifest.json")
    build.add_argument("--output-dir", type=Path, required=True, help="New exclusive directory")
    build.add_argument("--source-manifest-override", type=Path)
    verify = commands.add_parser(
        "verify", help="Check the complete view against its pinned original"
    )
    verify.add_argument("manifest", type=Path, help="Workbench manifest.json")
    verify.add_argument("--issuer-manifest-override", type=Path)
    verify.add_argument("--source-manifest-override", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            manifest = build_workbench(
                args.manifest,
                args.output_dir,
                source_manifest_override=args.source_manifest_override,
            )
            result = {
                "status": "created",
                "output_dir": str(args.output_dir.resolve()),
                "distribute_only": "public/",
            }
        else:
            packet, manifest = validate_workbench(
                args.manifest,
                issuer_manifest_override=args.issuer_manifest_override,
                source_manifest_override=args.source_manifest_override,
            )
            result = {"status": "verified", "assigned_cases": len(packet["cases"])}
        result.update(
            {key: manifest[key] for key in ("issuer_kind", "packet_sha256", "view_version")}
        )
        result["import_responses_with"] = "original_issuer_manifest"
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        print(f"Workbench error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
