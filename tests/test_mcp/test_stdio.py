"""Native MCP transport checks; SDK cases run only when the optional SDK exists."""

from __future__ import annotations

import builtins
import copy
import json
import sys
from pathlib import Path

import pytest

from healthcraft.mcp import stdio
from healthcraft.mcp.server import TOOL_NAME_MAP
from healthcraft.world.seed import WorldSeeder

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/world/mercy_point_v1.yaml"
SCHEMAS = ROOT / "configs/mcp-tools.json"


def sdk():
    return pytest.importorskip("mcp", reason="native MCP SDK is an optional dependency")


def run_async(function):
    import anyio

    return anyio.run(function)


def payload(result):
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    parsed = json.loads(result.content[0].text)
    assert result.structuredContent == parsed
    assert result.isError is (parsed["status"] == "error")
    return parsed


def test_missing_optional_sdk_is_actionable_before_seeding(monkeypatch, capsys):
    original = builtins.__import__

    def missing_mcp(name, *args, **kwargs):
        if name == "mcp" or name.startswith("mcp."):
            raise ModuleNotFoundError("No module named 'mcp'", name="mcp")
        return original(name, *args, **kwargs)

    def unexpected_seed(*args, **kwargs):
        pytest.fail("world must not be seeded without a usable transport")

    monkeypatch.setattr(builtins, "__import__", missing_mcp)
    monkeypatch.setattr(WorldSeeder, "seed_world", unexpected_seed)
    with pytest.raises(RuntimeError, match=r"healthcraft\[mcp\]"):
        stdio.serve_stdio(CONFIG, seed=42)
    assert capsys.readouterr().out == ""


def test_missing_config_fails_before_transport(capsys, tmp_path):
    with pytest.raises(FileNotFoundError, match="World seed config"):
        stdio.create_stdio_server(tmp_path / "missing.yaml", seed=42)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "extra", "invalid_schema"])
def test_discovery_config_mismatch_fails_before_seeding(monkeypatch, tmp_path, mutation):
    doc = json.loads(SCHEMAS.read_text())
    if mutation == "missing":
        doc["tools"].pop()
    elif mutation == "duplicate":
        doc["tools"].append(copy.deepcopy(doc["tools"][0]))
    elif mutation == "extra":
        doc["tools"].append({"name": "extraTool", "description": "extra", "parameters": {}})
    else:
        doc["tools"][0]["parameters"]["type"] = 42
    path = tmp_path / "tools.json"
    path.write_text(json.dumps(doc))
    monkeypatch.setattr(WorldSeeder, "seed_world", lambda *a: pytest.fail("must not seed"))
    with pytest.raises(ValueError, match="tool schema"):
        stdio.create_stdio_server(CONFIG, schema_path=path)


def test_real_sdk_initialize_and_exact_full_discovery():
    sdk()
    from mcp.shared.memory import create_connected_server_and_client_session

    adapter = stdio.create_stdio_server(CONFIG, seed=42)
    expected = {row["name"]: row for row in json.loads(SCHEMAS.read_text())["tools"]}
    assert adapter.dispatcher.world_state.entity_counts["patient"] > 0
    assert adapter.dispatcher.world_state.entity_counts["encounter"] > 0

    async def scenario():
        async with create_connected_server_and_client_session(adapter.server) as session:
            result = await session.list_tools()
            assert len(result.tools) == 24
            assert {tool.name for tool in result.tools} == set(TOOL_NAME_MAP)
            for tool in result.tools:
                assert tool.inputSchema == expected[tool.name]["parameters"]
                assert tool.description == expected[tool.name]["description"]
            return payload(await session.call_tool("searchEncounters", {}))

    result = run_async(scenario)
    assert len(result["data"]) == 10
    audit = adapter.dispatcher.world_state.audit_log
    assert len(audit) == 1 and audit[0].tool_name == "searchEncounters"


def test_real_sdk_mutation_persisted_with_exact_audit_and_readback(capsys):
    sdk()
    from mcp.shared.memory import create_connected_server_and_client_session

    adapter = stdio.create_stdio_server(CONFIG, seed=19)
    world = adapter.dispatcher.world_state
    encounter_id = next(iter(world.list_entities("encounter")))
    params = {
        "encounter_id": encounter_id,
        "order_type": "lab",
        "details": {"test_name": "synthetic transport verification"},
        "priority": "routine",
        "indication": "synthetic interface check",
    }

    async def scenario():
        async with create_connected_server_and_client_session(adapter.server) as session:
            before = payload(
                await session.call_tool("getEncounterDetails", {"encounter_id": encounter_id})
            )
            created = payload(await session.call_tool("createClinicalOrder", params))
            updated = payload(
                await session.call_tool(
                    "updateEncounter",
                    {"encounter_id": encounter_id, "notes": "stdio transport note"},
                )
            )
            after = payload(
                await session.call_tool("getEncounterDetails", {"encounter_id": encounter_id})
            )
            return before, created, updated, after

    before, created, updated, after = run_async(scenario)
    assert created["status"] == updated["status"] == "ok"
    assert before["data"]["id"] == after["data"]["id"] == encounter_id
    assert any(note[1] == "stdio transport note" for note in after["data"]["clinical_notes"])
    stored = world.get_entity("order", created["data"]["order_id"])
    assert stored["encounter_id"] == encounter_id
    assert stored["details"] == params["details"]
    audit = world.audit_log
    assert [row.tool_name for row in audit] == [
        "getEncounterDetails",
        "createClinicalOrder",
        "updateEncounter",
        "getEncounterDetails",
    ]
    assert audit[1].params == params
    assert adapter.dispatcher.audit_logger.entry_count == 4
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "name, params, code",
    [
        (
            "createClinicalOrder",
            {"encounter_id": "ENC-AAAAAAAA", "order_type": "fiction", "details": {}},
            "validation_error",
        ),
        ("getEncounterDetails", {}, "validation_error"),
        ("notARealTool", {"source": "original"}, "unknown_tool"),
        (
            "update_encounter",
            {"encounter_id": "ENC-AAAAAAAA", "notes": "must not write"},
            "unknown_tool",
        ),
        ("getEncounterDetails", {"encounter_id": "ENC-AAAAAAAA"}, "not_found"),
    ],
)
def test_real_sdk_errors_are_structured_audited_without_mutation(name, params, code):
    sdk()
    from mcp.shared.memory import create_connected_server_and_client_session

    adapter = stdio.create_stdio_server(CONFIG)
    world = adapter.dispatcher.world_state
    counts = world.entity_counts.copy()

    async def scenario():
        async with create_connected_server_and_client_session(adapter.server) as session:
            return payload(await session.call_tool(name, params))

    result = run_async(scenario)
    assert result["code"] == code
    assert world.entity_counts == counts
    assert len(world.audit_log) == adapter.dispatcher.audit_logger.entry_count == 1
    assert world.audit_log[0].params == params
    assert world.audit_log[0].error_code == code
    assert world.audit_log[0].result_summary == "error"


def test_handler_prints_cannot_pollute_protocol_stdout(capsys):
    sdk()
    from mcp.shared.memory import create_connected_server_and_client_session

    adapter = stdio.create_stdio_server(CONFIG)

    def noisy_handler(world, params):
        print("handler diagnostic")
        return {"status": "ok", "data": {"synthetic": True}}

    adapter.dispatcher._handlers["search_encounters"] = noisy_handler

    async def scenario():
        async with create_connected_server_and_client_session(adapter.server) as session:
            return payload(await session.call_tool("searchEncounters", {}))

    assert run_async(scenario)["data"] == {"synthetic": True}
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "handler diagnostic" in captured.err


@pytest.mark.parametrize("entrypoint", ["adapter", "public_cli"])
def test_real_sdk_child_stdio_initialize_list_call_and_persisted_readback(entrypoint):
    sdk()
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    command = (
        "from pathlib import Path; "
        "from healthcraft.mcp.stdio import serve_stdio; "
        "serve_stdio(Path('configs/world/mercy_point_v1.yaml'), seed=42)"
    )

    arguments = (
        ["-c", command]
        if entrypoint == "adapter"
        else ["-m", "healthcraft", "serve", "--config", str(CONFIG), "--seed", "42"]
    )

    async def scenario():
        import anyio

        with anyio.fail_after(25):
            async with stdio_client(
                StdioServerParameters(
                    command=sys.executable,
                    args=arguments,
                    cwd=ROOT,
                    env={"PYTHONPATH": str(ROOT / "src")},
                )
            ) as streams:
                async with ClientSession(*streams) as session:
                    initialized = await session.initialize()
                    assert initialized.serverInfo.name == "healthcraft"
                    assert initialized.capabilities.tools is not None
                    assert len((await session.list_tools()).tools) == 24
                    found = payload(await session.call_tool("searchEncounters", {}))
                    encounter_id = found["data"][0]["id"]
                    params = {
                        "encounter_id": encounter_id,
                        "order_type": "lab",
                        "details": {"test_name": "synthetic stdio check"},
                    }
                    created = payload(await session.call_tool("createClinicalOrder", params))
                    assert created["status"] == "ok"
                    assert (
                        payload(
                            await session.call_tool(
                                "updateEncounter",
                                {"encounter_id": encounter_id, "notes": "child stdio persistence"},
                            )
                        )["status"]
                        == "ok"
                    )
                    details = payload(
                        await session.call_tool(
                            "getEncounterDetails", {"encounter_id": encounter_id}
                        )
                    )
                    assert any(
                        note[1] == "child stdio persistence"
                        for note in details["data"]["clinical_notes"]
                    )
                    changed = payload(
                        await session.call_tool(
                            "updateTaskStatus",
                            {"task_id": created["data"]["task_id"], "status": "completed"},
                        )
                    )
                    assert changed["status"] == "ok"
                    assert changed["data"]["status"] == "completed"

    run_async(scenario)


def test_known_entity_values_are_preserved_as_json_not_repr_strings():
    sdk()
    from mcp.shared.memory import create_connected_server_and_client_session

    adapter = stdio.create_stdio_server(CONFIG, seed=7)
    world = adapter.dispatcher.world_state
    encounter_id, encounter = next(iter(world.list_entities("encounter").items()))
    patient = world.get_entity("patient", encounter.patient_id)

    async def scenario():
        async with create_connected_server_and_client_session(adapter.server) as session:
            details = payload(
                await session.call_tool("getEncounterDetails", {"encounter_id": encounter_id})
            )["data"]
            history = payload(
                await session.call_tool("getPatientHistory", {"patient_id": encounter.patient_id})
            )["data"]
            return details, history

    details, history = run_async(scenario)
    assert details["entity_type"] == "encounter"
    assert details["arrival_time"] == encounter.arrival_time.isoformat()
    assert details["created_at"] == encounter.created_at.isoformat()
    assert history["dob"] == patient.dob.isoformat()
    assert details["clinical_notes"] == [list(note) for note in encounter.clinical_notes]
    expected_world = WorldSeeder(seed=7).seed_world(CONFIG)
    assert set(world.list_entities("patient")) == set(expected_world.list_entities("patient"))


def test_rejected_write_to_real_target_is_audited_and_does_not_poison_retry():
    sdk()
    from mcp.shared.memory import create_connected_server_and_client_session

    adapter = stdio.create_stdio_server(CONFIG)
    world = adapter.dispatcher.world_state
    encounter_id, before = next(iter(world.list_entities("encounter").items()))
    bad = {
        "encounter_id": encounter_id,
        "notes": ["not a string"],
        "idempotency_key": "retry-check",
    }
    good = {**bad, "notes": "valid retry"}

    async def scenario():
        async with create_connected_server_and_client_session(adapter.server) as session:
            rejected = payload(await session.call_tool("updateEncounter", bad))
            assert rejected["code"] == "validation_error"
            assert world.get_entity("encounter", encounter_id) == before
            assert not world.list_entities("clinical_note")
            return payload(await session.call_tool("updateEncounter", good))

    result = run_async(scenario)
    assert result["status"] == "ok"
    assert len(world.list_entities("clinical_note")) == 1
    audit = world.audit_log
    assert [entry.attempt_number for entry in audit] == [1, 2]
    assert [entry.idempotency_key for entry in audit] == ["retry-check", "retry-check"]
    assert [entry.result_summary for entry in audit] == ["error", "ok"]
    assert audit[0].params == bad


def test_stdin_eof_exits_cleanly_without_ready_banner_or_stdout_logs():
    sdk()
    import os
    import subprocess

    command = (
        "from pathlib import Path; "
        "from healthcraft.mcp.stdio import serve_stdio; "
        "serve_stdio(Path('configs/world/mercy_point_v1.yaml'))"
    )
    process = subprocess.run(
        [sys.executable, "-c", command],
        input="",
        capture_output=True,
        text=True,
        timeout=15,
        cwd=ROOT,
        env={"PATH": os.defpath, "PYTHONPATH": str(ROOT / "src")},
    )
    assert process.returncode == 0, process.stderr
    assert process.stdout == ""
