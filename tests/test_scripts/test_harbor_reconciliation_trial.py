"""Optional real-Harbor SDK adapter contracts; no Docker or model calls."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import shlex
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

HAS_HARBOR = importlib.util.find_spec("harbor") is not None


@unittest.skipUnless(HAS_HARBOR, "Optional pinned Harbor 0.8.0 runtime required")
class HarborReferenceContracts(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = importlib.import_module("scripts.harbor_reconciliation_trial")
        self.probe_patch = patch.object(
            self.module.PublicReferenceAgent, "_probe_environment", new=AsyncMock(), create=True
        )
        self.probe_patch.start()
        self.addCleanup(self.probe_patch.stop)
        self.inspect_patch = patch.object(
            self.module.PublicReferenceAgent, "_inspect_container", new=AsyncMock(), create=True
        )
        self.inspect_patch.start()
        self.addCleanup(self.inspect_patch.stop)
        from harbor.models.agent.context import AgentContext

        self.context = AgentContext()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = {"patient_id": "PAT-ABCDEF12", "encounter_id": "ENC-ABCDEF12"}

    def agent(self, **kwargs):
        return self.module.PublicReferenceAgent(logs_dir=self.root, target=self.target, **kwargs)

    @staticmethod
    def result(data, code=0):
        return SimpleNamespace(stdout=json.dumps(data), stderr=None, return_code=code)

    @staticmethod
    def generator(_tools, *, target):
        response = yield {
            "action": "call",
            "name": "getPatientHistory",
            "params": {"patient_id": target["patient_id"]},
        }
        if response != {"status": "ok", "data": {"exact": "returned"}}:
            raise ValueError("Actual response was changed")
        return {"status": "terminated", "reason": "reference_readback_verified"}

    async def test_actual_sdk_agent_preserves_raw_exec_and_uses_public_commands(self):
        from harbor.agents.base import BaseAgent

        agent = self.agent()
        self.assertIsInstance(agent, BaseAgent)
        env = SimpleNamespace(
            exec=AsyncMock(
                side_effect=[
                    self.result({"tools": []}),
                    self.result({"status": "ok", "data": {"exact": "returned"}}),
                ]
            )
        )
        with patch.object(self.module, "reference_commands", self.generator):
            await agent.setup(env)
            await agent.run("Public instruction", env, self.context)
        record = agent.snapshot()
        self.assertEqual(record["completion"]["status"], "completed")
        self.assertEqual(record["model_calls"], 0)
        self.assertEqual(len(record["exchanges"]), 2)
        call = record["exchanges"][1]
        self.assertEqual(call["return_code"], 0)
        self.assertEqual(json.loads(call["stdout"])["data"], {"exact": "returned"})
        argv = shlex.split(env.exec.await_args_list[1].kwargs["command"])
        self.assertEqual(argv[:3], ["python", "/usr/local/bin/hc-ehr.py", "call"])
        self.assertEqual(json.loads(argv[-1]), {"patient_id": self.target["patient_id"]})
        self.assertEqual(self.context.metadata["healthcraft_reconciliation"], record)

    async def test_environment_probe_records_actual_fixed_command_result(self):
        self.probe_patch.stop()
        payload = {
            "hostname": "abcdef012345",
            "backend_tcp": True,
            "public_tcp_connect_ex": 101,
            "private_paths_present": {
                "/app/src/healthcraft": False,
                "/app/configs": False,
                "/run/reconciliation/admin": False,
                "/tests": False,
                "/solution": False,
            },
        }
        agent = self.agent()
        env = SimpleNamespace(exec=AsyncMock(return_value=self.result(payload)))
        await agent._probe_environment(env)
        record = agent.snapshot()["environment_probe"]
        self.assertEqual(record["parsed"], payload)
        self.assertEqual(record["stdout"], json.dumps(payload))
        self.assertEqual(record["return_code"], 0)
        self.assertFalse(record["comprehensive_isolation_assessment"])
        argv = shlex.split(env.exec.await_args.kwargs["command"])
        self.assertEqual(argv[:2], ["python", "-c"])
        self.assertIn("1.1.1.1", argv[2])
        self.assertNotIn("HC_RECONCILIATION_TOKEN", argv[2])

    async def test_environment_probe_fails_closed_without_backend_evidence(self):
        self.probe_patch.stop()
        agent = self.agent()
        env = SimpleNamespace(exec=AsyncMock(return_value=self.result({"backend_tcp": False})))
        with self.assertRaises(ValueError):
            await agent.setup(env)
        self.assertEqual(env.exec.await_count, 1)
        self.assertEqual(agent.snapshot()["environment_probe"]["parsed"], {"backend_tcp": False})

    async def test_host_inspection_reads_only_network_mount_and_image_fields(self):
        self.inspect_patch.stop()
        expected = {"Networks": {"private": {}}, "Mounts": [], "Image": "sha256:" + "a" * 64}
        process = SimpleNamespace(
            communicate=AsyncMock(return_value=(json.dumps(expected).encode(), b"")),
            returncode=0,
        )
        agent = self.agent()
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)) as create:
            await agent._inspect_container("abcdef012345")
        args = create.await_args.args
        self.assertEqual(args[:3], ("docker", "inspect", "--format"))
        self.assertNotIn("Config", args[3])
        self.assertNotIn("Env", args[3])
        self.assertEqual(args[-1], "abcdef012345")
        self.assertEqual(agent.snapshot()["host_container_inspection"]["parsed"], expected)

    async def test_invalid_hostname_never_reaches_host_docker(self):
        self.inspect_patch.stop()
        agent = self.agent()
        with patch("asyncio.create_subprocess_exec", new=AsyncMock()) as create:
            with self.assertRaises(ValueError):
                await agent._inspect_container("--all")
        create.assert_not_awaited()

    async def test_nonzero_exit_never_becomes_completed(self):
        agent = self.agent()
        env = SimpleNamespace(
            exec=AsyncMock(
                side_effect=[self.result({"tools": []}), self.result({"status": "ok"}, 2)]
            )
        )
        with patch.object(self.module, "reference_commands", self.generator):
            await agent.setup(env)
            with self.assertRaises(ValueError):
                await agent.run("Public", env, self.context)
        self.assertEqual(agent.snapshot()["completion"]["status"], "failed")
        self.assertEqual(agent.snapshot()["exchanges"][-1]["return_code"], 2)

    async def test_cancellation_records_unknown_pending_outcome_and_no_next_dispatch(self):
        agent = self.agent()
        env = SimpleNamespace(
            exec=AsyncMock(side_effect=[self.result({"tools": []}), asyncio.CancelledError()])
        )
        with patch.object(self.module, "reference_commands", self.generator):
            await agent.setup(env)
            with self.assertRaises(asyncio.CancelledError):
                await agent.run("Public", env, self.context)
        record = agent.snapshot()
        self.assertEqual(record["completion"]["status"], "interrupted")
        self.assertEqual(record["exchanges"][-1]["outcome"], "unknown")
        self.assertEqual(env.exec.await_count, 2)

    async def test_duplicate_json_response_is_retained_and_rejected(self):
        agent = self.agent()
        raw = '{"tools": [], "tools": []}'
        env = SimpleNamespace(
            exec=AsyncMock(return_value=SimpleNamespace(stdout=raw, stderr=None, return_code=0))
        )
        with self.assertRaises(ValueError):
            await agent.setup(env)
        self.assertEqual(agent.snapshot()["exchanges"][0]["stdout"], raw)
        self.assertEqual(agent.snapshot()["completion"]["status"], "failed")

    async def test_run_reserves_denominator_before_trial_creation_failure(self):
        output = self.root / "attempt"
        with patch("harbor.trial.trial.Trial.create", new=AsyncMock(side_effect=ValueError("bad"))):
            result = await self.module.run_trial(self.root / "task", output, target=self.target)
        self.assertEqual(result["scheduled_trials"], 1)
        self.assertFalse(result["controller_completed"])
        self.assertEqual(result["status"], "failed")
        self.assertTrue((output / "scheduled.json").exists())
        self.assertTrue((output / "receipt.json").exists())

    async def test_existing_even_empty_output_is_rejected(self):
        output = self.root / "existing"
        output.mkdir()
        with self.assertRaises(FileExistsError):
            await self.module.run_trial(self.root / "task", output, target=self.target)
        self.assertEqual(list(output.iterdir()), [])

    async def test_real_public_reference_through_sdk_agent_and_session(self):
        from healthcraft.reconciliation.fixture import load_scenario
        from healthcraft.reconciliation.service import ReconciliationSession

        scenario = load_scenario()
        session = ReconciliationSession(scenario=scenario, token="unit-token")
        self.addCleanup(session.close)

        async def execute(*, command, timeout_sec):
            self.assertEqual(timeout_sec, 30)
            argv = shlex.split(command)
            if argv[2] == "tools":
                code, response = session.handle("GET", "/tools", authorization="Bearer unit-token")
            else:
                request = {"name": argv[3], "params": json.loads(argv[5])}
                code, response = session.handle(
                    "POST", "/call", json.dumps(request).encode(), "Bearer unit-token"
                )
            self.assertEqual(code, 200)
            return self.result(response)

        env = SimpleNamespace(exec=AsyncMock(side_effect=execute))
        agent = self.module.PublicReferenceAgent(logs_dir=self.root, target=scenario["target"])
        await agent.setup(env)
        await agent.run("Original synthetic public source retrieval", env, self.context)
        state = agent.snapshot()
        self.assertEqual(state["completion"]["status"], "completed")
        evidence = session.finalize("completed")
        self.assertEqual(len(evidence["calls"]), 10)
        updates = [row for row in evidence["calls"] if row["name"] == "updateEncounter"]
        self.assertEqual(len(updates), 2)
        self.assertEqual(updates[0]["params"], updates[1]["params"])
        self.assertTrue(updates[1]["response"]["deduplicated"])
        self.assertEqual(evidence["calls"][-1]["name"], "getEncounterDetails")

    async def test_noop_has_completion_but_no_task_success_claim(self):
        agent = self.agent(mode="noop")
        env = SimpleNamespace(exec=AsyncMock(return_value=self.result({"tools": []})))
        await agent.setup(env)
        await agent.run("Public", env, self.context)
        self.assertEqual(agent.snapshot()["completion"], {"status": "completed", "reason": "noop"})
        self.assertEqual(env.exec.await_count, 1)
        self.assertNotIn("reward", agent.snapshot())

    async def test_command_arguments_are_quoted_without_shell_evaluation(self):
        agent = self.agent()
        params = {"notes": "literal 'quoted' $(touch /tmp/forbidden) `echo x`; &"}
        env = SimpleNamespace(
            exec=AsyncMock(return_value=self.result({"status": "ok", "data": {}}))
        )
        await agent._exchange(env, {"action": "call", "name": "updateEncounter", "params": params})
        argv = shlex.split(env.exec.await_args.kwargs["command"])
        self.assertEqual(len(argv), 6)
        self.assertEqual(json.loads(argv[-1]), params)

    async def test_no_unsupported_command_is_dispatched(self):
        agent = self.agent()
        env = SimpleNamespace(exec=AsyncMock())
        with self.assertRaises(ValueError):
            await agent._exchange(env, {"action": "call", "name": "shell", "params": {}})
        env.exec.assert_not_awaited()

    async def test_controller_missing_readback_return_fails(self):
        def empty(_tools, *, target):
            yield from []

        agent = self.agent()
        env = SimpleNamespace(exec=AsyncMock(return_value=self.result({"tools": []})))
        await agent.setup(env)
        with patch.object(self.module, "reference_commands", empty):
            with self.assertRaises(ValueError):
                await agent.run("Public", env, self.context)
        self.assertEqual(agent.snapshot()["completion"]["status"], "failed")

    async def test_harbor_reward_does_not_override_controller_failure(self):
        state = {"completion": {"status": "failed"}, "exchanges": []}
        fake = SimpleNamespace(
            agent=SimpleNamespace(snapshot=lambda: state),
            run=AsyncMock(
                return_value=SimpleNamespace(
                    model_dump=lambda **kwargs: {
                        "exception_info": None,
                        "verifier_result": {"rewards": {"reward": 1}},
                    }
                )
            ),
        )
        create = AsyncMock(return_value=fake)
        with patch("harbor.trial.trial.Trial.create", new=create):
            result = await self.module.run_trial(
                self.root / "task", self.root / "run", target=self.target
            )
        self.assertFalse(result["controller_completed"])
        self.assertEqual(result["verifier_scope"], "terminal_connectivity_only")
        self.assertEqual(result["scheduled_trials"], 1)
        config = create.await_args.args[0]
        self.assertFalse(config.environment.delete)
        self.assertEqual(
            config.agent.import_path, "scripts.harbor_reconciliation_trial:PublicReferenceAgent"
        )


if __name__ == "__main__":
    unittest.main()
