"""CLI entrypoint: ``python -m healthcraft.agents_assemble.superpower_decision_rules``.

Boots a fresh seeded world, instantiates the Superpower, and either:

- prints the tool catalog (default), or
- runs ``applyDecisionRule`` once on a Bundle read from stdin (``--invoke``)

This entrypoint exists so the hackathon demo video can record a real run
without spinning up Docker. For the production submission the same server
is wrapped behind an MCP transport on the Prompt Opinion platform.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from healthcraft.agents_assemble.superpower_decision_rules.server import create_superpower
from healthcraft.world.seed import WorldSeeder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="superpower_decision_rules")
    parser.add_argument(
        "--world-config",
        default="configs/world/mercy_point_v1.yaml",
        help="Path to a HEALTHCRAFT world seed config (YAML).",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--invoke",
        choices=["applyDecisionRule", "getProtocolDetails", "getReferenceArticle"],
        help="If set, read a JSON SHARP envelope from stdin and run the named tool.",
    )
    args = parser.parse_args(argv)

    world = WorldSeeder(seed=args.seed).seed_world(Path(args.world_config))
    server = create_superpower(world)

    if args.invoke is None:
        catalog = {
            "tools": list(server.available_tools),
            "world": {"seed": args.seed, "config": args.world_config},
        }
        json.dump(catalog, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    raw = sys.stdin.read()
    params = json.loads(raw) if raw.strip() else {}
    result = server.call(args.invoke, params)
    json.dump(result, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
