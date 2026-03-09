"""CLI entry point for HEALTHCRAFT.

Provides subcommands for world generation, MCP server startup,
task evaluation, and YAML validation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _cmd_seed(args: argparse.Namespace) -> int:
    """Generate a deterministic world state from a seed config."""
    from healthcraft.world.seed import WorldSeeder

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        return 1

    seeder = WorldSeeder(seed=args.seed)
    world = seeder.seed_world(config_path)
    print(f"World seeded: {world}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    """Start the MCP server."""
    from healthcraft.mcp.server import create_server
    from healthcraft.world.state import WorldState

    world = WorldState()
    server = create_server(world)
    print(f"HEALTHCRAFT MCP server ready: {server}")
    print(f"World state: {world}")

    if args.port:
        print(f"Listening on port {args.port} (MCP transport not yet implemented)")

    return 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    """Run task evaluation."""
    from healthcraft.tasks.loader import load_task, load_tasks

    task_path = Path(args.tasks)
    if not task_path.exists():
        print(f"Error: Task path not found: {task_path}", file=sys.stderr)
        return 1

    if task_path.is_file():
        tasks = [load_task(task_path)]
    else:
        tasks = load_tasks(task_path)

    print(f"Loaded {len(tasks)} task(s)")
    for task in tasks:
        print(f"  [{task.id}] {task.title} (level={task.level}, category={task.category})")

    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    """Validate task and entity YAML files."""
    from healthcraft.tasks.loader import load_task

    target = Path(args.path)
    if not target.exists():
        print(f"Error: Path not found: {target}", file=sys.stderr)
        return 1

    files = [target] if target.is_file() else sorted(target.rglob("*.y*ml"))
    errors = 0
    for path in files:
        if path.suffix not in (".yaml", ".yml"):
            continue
        try:
            load_task(path)
            print(f"  OK: {path}")
        except Exception as e:
            print(f"  FAIL: {path}: {e}", file=sys.stderr)
            errors += 1

    if errors:
        print(f"\n{errors} file(s) failed validation", file=sys.stderr)
        return 1

    print(f"\nAll {len(files)} file(s) valid")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code (0 = success).
    """
    parser = argparse.ArgumentParser(
        prog="healthcraft",
        description="HEALTHCRAFT: Emergency Medicine RL Training Environment",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.1.0",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # seed
    seed_parser = subparsers.add_parser("seed", help="Generate a deterministic world state")
    seed_parser.add_argument(
        "--config",
        "-c",
        required=True,
        help="Path to world seed configuration file (JSON or YAML)",
    )
    seed_parser.add_argument(
        "--seed",
        "-s",
        type=int,
        default=42,
        help="Random seed (default: 42)",
    )

    # serve
    serve_parser = subparsers.add_parser("serve", help="Start the MCP server")
    serve_parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=None,
        help="Port to listen on (default: stdio transport)",
    )

    # evaluate
    eval_parser = subparsers.add_parser("evaluate", help="Run task evaluation")
    eval_parser.add_argument(
        "--tasks",
        "-t",
        required=True,
        help="Path to task YAML file or directory",
    )

    # validate
    val_parser = subparsers.add_parser("validate", help="Validate YAML files")
    val_parser.add_argument(
        "path",
        help="Path to YAML file or directory to validate",
    )

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    handlers = {
        "seed": _cmd_seed,
        "serve": _cmd_serve,
        "evaluate": _cmd_evaluate,
        "validate": _cmd_validate,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    try:
        return handler(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
