#!/usr/bin/env python3
"""Issue source-bound incident forms and separate human validity declarations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from healthcraft.operator_adjudication import (  # noqa: E402
    build_adjudication_packet,
    import_adjudication_response,
    summarize_adjudications,
)
from healthcraft.operator_incidents import (  # noqa: E402
    build_incident_packet,
    import_incident_response,
)
from healthcraft.operator_review import _keys, _parse  # noqa: E402


def _config(path, fields):
    value = _parse(path.read_text(encoding="utf-8"))
    _keys(value, fields, "command configuration")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "import", "adjudication-build", "adjudication-import", "summary"):
        command = commands.add_parser(name)
        command.add_argument("manifest", type=Path)
        command.add_argument(
            "--output-dir", type=Path, required=True, help="New exclusive directory"
        )
        if name in ("import", "adjudication-build", "adjudication-import"):
            command.add_argument("response", type=Path)
        if name in ("build", "adjudication-build"):
            command.add_argument("--config", type=Path, required=True)
        if name in ("build", "import", "adjudication-build") and name != "build":
            command.add_argument("--source-manifest-override", type=Path)
        if name == "summary":
            command.add_argument(
                "--records",
                type=Path,
                required=True,
                help="JSON reviewer ID to import manifest path or null; paths relative to cwd",
            )
            command.add_argument("--resolver-record", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = build_incident_packet(
                args.manifest,
                args.output_dir,
                **_config(
                    args.config,
                    {"expected_sha256", "selections", "protocol", "assignment"},
                ),
            )
        elif args.command == "import":
            result = import_incident_response(
                args.manifest,
                args.response,
                args.output_dir,
                source_manifest_override=args.source_manifest_override,
            )
        elif args.command == "adjudication-build":
            config = _config(args.config, {"assignment", "prior_records"})
            result = build_adjudication_packet(
                args.manifest,
                args.response,
                args.output_dir,
                source_manifest_override=args.source_manifest_override,
                **config,
            )
        elif args.command == "adjudication-import":
            result = import_adjudication_response(args.manifest, args.response, args.output_dir)
        else:
            records = _parse(args.records.read_text(encoding="utf-8"))
            result = summarize_adjudications(
                args.manifest, records, args.output_dir, resolver_record=args.resolver_record
            )
        summary = {
            "status": result.get("status", "created"),
            "output_dir": str(args.output_dir.resolve()),
            "clinical_validation": "not_established",
        }
        if args.command in ("build", "adjudication-build"):
            summary.update(
                packet_id=result["packet_id"],
                assigned_cases=len(result["cases"]),
                distribute_only="public/",
            )
        else:
            summary["counts"] = result["counts"]
            if args.command == "summary":
                summary["assigned_opportunities"] = result["assigned_opportunities"]
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        print(f"Incident workflow error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True, allow_nan=False))
    return 1 if summary["status"] == "invalid_submission" else 0


if __name__ == "__main__":
    raise SystemExit(main())
