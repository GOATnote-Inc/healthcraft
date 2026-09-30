"""Native MCP stdio transport over the actual seeded HEALTHCRAFT dispatcher.

Tool names and complete input schemas come from ``TOOL_NAME_MAP`` and
``configs/mcp-tools.json``. Results retain the actual status/data/error envelope
in both structuredContent and JSON text. We intentionally do not advertise an
outputSchema: the authored ``returns`` descriptions do not currently describe
that envelope, and this adapter does not claim return-schema conformance.

The optional MCP SDK is imported only when constructing the transport. No HTTP
service, model provider, or credential is involved.
"""

from __future__ import annotations

import copy
import json
import logging
import sys
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from jsonschema import FormatChecker, SchemaError, ValidationError
from jsonschema.validators import validator_for

from healthcraft.mcp.server import TOOL_NAME_MAP, HealthcraftServer, create_server
from healthcraft.world.seed import WorldSeeder

_DEFAULT_SCHEMAS = Path(__file__).resolve().parents[3] / "configs" / "mcp-tools.json"


@dataclass(frozen=True)
class StdioAdapter:
    """SDK server and its persistent, auditable simulation dispatcher."""

    server: Any
    dispatcher: HealthcraftServer


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate key: {key}")
        result[key] = value
    return result


def _load_schemas(path: Path) -> dict[str, dict[str, Any]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        json.dumps(document, allow_nan=False)
        rows = document["tools"]
        if not isinstance(rows, list):
            raise ValueError("tools must be a list")
        definitions = {}
        for row in rows:
            name = row["name"]
            if name in definitions:
                raise ValueError(f"Duplicate tool: {name}")
            if not isinstance(row["description"], str) or not isinstance(row["parameters"], dict):
                raise ValueError(f"Invalid description or parameters: {name}")
            validator_for(row["parameters"]).check_schema(row["parameters"])
            definitions[name] = row
        if set(definitions) != set(TOOL_NAME_MAP):
            raise ValueError("names must exactly match TOOL_NAME_MAP")
        return definitions
    except (OSError, ValueError, TypeError, KeyError, SchemaError) as exc:
        raise ValueError(f"Invalid HEALTHCRAFT tool schema file {path}: {exc}") from exc


def _json_default(value: Any) -> Any:
    """Preserve typed entity values using their explicit JSON representation."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"Unsupported tool result value: {type(value).__name__}")


def _load_sdk() -> tuple[Any, Any, Any, Any, Any]:
    try:
        import anyio
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import CallToolResult, TextContent, Tool
    except ImportError as exc:
        raise RuntimeError(
            "Native MCP stdio requires the optional MCP SDK. "
            "Install it with: pip install -e '.[mcp]' (healthcraft[mcp])."
        ) from exc
    if "structuredContent" not in getattr(CallToolResult, "model_fields", {}):
        raise RuntimeError(
            "The installed MCP SDK lacks structured tool results. "
            "Upgrade healthcraft[mcp]; this adapter is tested with mcp==1.29.0."
        )
    return Server, Tool, CallToolResult, TextContent, (anyio, stdio_server)


def _record_rejection(
    dispatcher: HealthcraftServer, name: str, params: dict[str, Any], code: str, message: str
) -> dict[str, Any]:
    """Record transport validation without executing a state-mutating handler."""
    result = {"status": "error", "code": code, "message": message}
    world = dispatcher.world_state
    key = params.get("idempotency_key", "")
    key = key if isinstance(key, str) else ""
    attempt = 1 + sum(entry.idempotency_key == key for entry in world.audit_log) if key else 1
    dispatcher.audit_logger.log_tool_call(name, params, result, world.timestamp)
    world.record_audit(
        tool_name=name,
        params=params,
        result_summary="error",
        error_code=code,
        idempotency_key=key,
        attempt_number=attempt,
    )
    return result


def create_stdio_server(
    config_path: Path, seed: int = 42, *, schema_path: Path | None = None
) -> StdioAdapter:
    """Prepare a seeded MCP server without opening any transport.

    Configuration, tool inventory and optional SDK are checked before seeding.
    SDK input validation is replaced with equivalent schema validation here so
    rejected tool requests also reach both audit logs. Protocol-level malformed
    JSON-RPC requests are handled by the SDK and are not tool invocations.
    """
    config_path = Path(config_path)
    if not config_path.is_file():
        raise FileNotFoundError(f"World seed config not found: {config_path}; use --config PATH")
    definitions = _load_schemas(schema_path or _DEFAULT_SCHEMAS)
    Server, Tool, CallToolResult, TextContent, _ = _load_sdk()
    server = Server("healthcraft")
    try:
        register_call = server.call_tool(validate_input=False)
    except TypeError as exc:
        raise RuntimeError(
            "Upgrade healthcraft[mcp]; this adapter is tested with mcp==1.29.0"
        ) from exc
    validators = {
        name: validator_for(row["parameters"])(row["parameters"], format_checker=FormatChecker())
        for name, row in definitions.items()
    }
    # A seed extension or handler diagnostic must never corrupt JSON-RPC stdout.
    with redirect_stdout(sys.stderr):
        world = WorldSeeder(seed=seed).seed_world(config_path)
        dispatcher = create_server(world)

    @server.list_tools()
    async def list_tools() -> list[Any]:
        return [
            Tool(
                name=name,
                description=definitions[name]["description"],
                inputSchema=copy.deepcopy(definitions[name]["parameters"]),
            )
            for name in TOOL_NAME_MAP
        ]

    @register_call
    async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
        with redirect_stdout(sys.stderr):
            if name not in definitions:
                if name in TOOL_NAME_MAP.values():
                    result = _record_rejection(
                        dispatcher, name, arguments, "unknown_tool", f"Unknown MCP tool: {name}"
                    )
                else:
                    result = dispatcher.call_tool(name, arguments)
            else:
                try:
                    json.dumps(arguments, allow_nan=False)
                    validators[name].validate(arguments)
                except (ValidationError, ValueError, TypeError) as exc:
                    message = exc.message if isinstance(exc, ValidationError) else str(exc)
                    result = _record_rejection(
                        dispatcher, name, arguments, "validation_error", message
                    )
                else:
                    result = dispatcher.call_tool(name, arguments)
        encoded = json.dumps(result, default=_json_default, allow_nan=False)
        return CallToolResult(
            content=[TextContent(type="text", text=encoded)],
            structuredContent=json.loads(encoded),
            isError=result.get("status") == "error",
        )

    return StdioAdapter(server=server, dispatcher=dispatcher)


def serve_stdio(config_path: Path, seed: int = 42) -> None:
    """Serve native MCP on stdin/stdout until the client closes the stream.

    Startup errors propagate to the CLI, which can report them on stderr and
    exit nonzero. No ready banner or other non-protocol text is emitted.
    """
    adapter = create_stdio_server(config_path, seed=seed)
    *_, (anyio, stdio_server) = _load_sdk()
    logging.basicConfig(stream=sys.stderr, force=True)

    async def run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await adapter.server.run(
                read_stream, write_stream, adapter.server.create_initialization_options()
            )

    anyio.run(run)
