"""CLI entry point for HEALTHCRAFT.

Provides subcommands for world generation, MCP server startup,
task evaluation, and YAML validation.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
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
    """Run a real transport; stdio is reserved exclusively for MCP messages."""
    config = Path(args.config).resolve()
    if not config.is_file():
        raise ValueError(f"Config file not found: {config}")
    if args.transport == "http":
        if importlib.util.find_spec("uvicorn") is None:
            raise RuntimeError("Install healthcraft[mcp] to serve the HTTP tool API")
        environment = {
            **os.environ,
            "HEALTHCRAFT_HOST": "127.0.0.1",
            "HEALTHCRAFT_PORT": str(args.port or 8000),
            "HEALTHCRAFT_SEED": str(args.seed),
            "HEALTHCRAFT_SEED_CONFIG": str(config),
        }
        # The child owns its seeded app state and logs. Its exit code, including
        # bind/import failure, is the command's result; no parent readiness claim.
        completed = subprocess.run(
            [sys.executable, "-m", "healthcraft.mcp.app"], env=environment, check=False
        )
        return completed.returncode
    if args.port is not None:
        raise ValueError("--port requires --transport http (the HTTP tool API)")
    from healthcraft.mcp.stdio import serve_stdio

    serve_stdio(config_path=config, seed=args.seed)
    return 0


def _cmd_list_tasks(args: argparse.Namespace) -> int:
    """List task definitions without claiming to have evaluated them."""
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


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("Port must be between 1 and 65535")
    return port


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
    arguments = list(sys.argv[1:] if argv is None else argv)
    # Each runner owns its full option parser. Forward verbatim, including help,
    # so this public entry point cannot drift into a different evaluation path.
    if arguments and arguments[0] in {"evaluate", "simulate"}:
        try:
            if arguments[0] == "evaluate":
                from healthcraft.llm.orchestrator import main as evaluate

                evaluate(arguments[1:], prog="healthcraft evaluate")
                return 0
            from healthcraft.eval_runner import main as simulate

            return simulate(arguments[1:])
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

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
    serve_parser = subparsers.add_parser("serve", help="Serve the seeded world over MCP stdio")
    serve_parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="stdio: native MCP; http: loopback HTTP tool API (not MCP JSON-RPC)",
    )
    serve_parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "configs/world/mercy_point_v1.yaml",
        help="World seed configuration file",
    )
    serve_parser.add_argument("--seed", type=int, default=42)
    serve_parser.add_argument(
        "--port",
        "-p",
        type=_port,
        default=None,
        help="HTTP tool API port; requires --transport http (default: 8000)",
    )

    subparsers.add_parser(
        "evaluate", help="Run actual model evaluation; evaluate --help for options"
    )
    subparsers.add_parser("simulate", help="Run ungraded scripted smoke checks; simulate --help")
    inventory_parser = subparsers.add_parser("list-tasks", help="List task definitions")
    inventory_parser.add_argument(
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

    args = parser.parse_args(arguments)

    if args.command is None:
        parser.print_help()
        return 0

    handlers = {
        "seed": _cmd_seed,
        "serve": _cmd_serve,
        "list-tasks": _cmd_list_tasks,
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
