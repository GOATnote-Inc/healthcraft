#!/usr/bin/env python3
"""Export six reviewed source rosters without claiming clinical/FHIR validation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from healthcraft.tasks.loader import load_task
from healthcraft.tasks.roster_execution import TASK_PATHS
from healthcraft.tasks.roster_profile import build_roster_profile
from healthcraft.world.fhir_projection import REPRESENTATION_VERSION, export_roster_sources
from healthcraft.world.state import WorldState

ROOT = Path(__file__).resolve().parents[1]


def _source_hashes() -> dict[str, str]:
    paths = list((ROOT / "src/healthcraft").rglob("*.py"))
    paths += [ROOT / "configs/tasks" / path for path in TASK_PATHS.values()]
    paths += [Path(__file__).resolve(), ROOT / "configs/mcp-tools.json"]
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        parser.error("Choose a new output directory; existing exports are never overwritten")
    before = _source_hashes()
    exports, files = [], {}
    for task_id, relative in TASK_PATHS.items():
        task = load_task(ROOT / "configs/tasks" / relative)
        world = WorldState()
        context = build_roster_profile(world, task)
        report = export_roster_sources(task, context, world)
        filename = f"{task_id}.bundle.json"
        files[filename] = report.pop("bundle")
        exports.append({**report, "bundle_file": filename})
    if _source_hashes() != before:
        parser.error("Source changed during export; no artifacts written")
    files["manifest.json"] = {
        "representation_version": REPRESENTATION_VERSION,
        "source_hashes": before,
        "exports": exports,
    }
    # All records validate before any artifact is created. Manifest is last:
    # a failed write cannot leave a manifest claiming a complete export.
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for name, value in files.items():
        with (args.output_dir / name).open("x", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")
    print(f"Exported 33 source records as 99 resources to {args.output_dir}")
    print("Official FHIR validation not run; clinical and safety criteria unassessed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
