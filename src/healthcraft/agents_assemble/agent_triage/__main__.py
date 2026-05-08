"""CLI entrypoint: ``python -m healthcraft.agents_assemble.agent_triage``.

Reads a FHIR Bundle (or SHARP envelope) from stdin and emits a
``TriagePlan`` JSON to stdout. Used by the demo video and by integration
tests that pipe Bundles through end-to-end.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from healthcraft.agents_assemble.agent_triage.agent import create_triage_agent
from healthcraft.world.seed import WorldSeeder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent_triage")
    parser.add_argument(
        "--world-config",
        default="configs/world/mercy_point_v1.yaml",
        help="Path to a HEALTHCRAFT world seed config (YAML).",
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    world = WorldSeeder(seed=args.seed).seed_world(Path(args.world_config))
    agent = create_triage_agent(world)

    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {}
    bundle = payload.get("bundle") or payload
    sharp = payload.get("sharp")
    plan = agent.run(bundle, sharp=sharp)
    json.dump(asdict(plan), sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
