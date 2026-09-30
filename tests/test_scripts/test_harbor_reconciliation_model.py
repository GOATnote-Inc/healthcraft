"""Optional SDK model-adapter tests use fake provider bytes, never inference."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import json
import shlex
import tempfile
import threading
import unittest
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

HAS_HARBOR = importlib.util.find_spec("harbor") is not None


@unittest.skipUnless(HAS_HARBOR, "Optional pinned Harbor 0.8.0 runtime required")
class HarborModelContracts(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = importlib.import_module("scripts.harbor_reconciliation_model")
        self.helper = importlib.import_module("scripts.harbor_reconciliation_trial")
        self.api = importlib.import_module("healthcraft.reconciliation.controller")
        from harbor.models.agent.context import AgentContext

        from healthcraft.reconciliation.service import ReconciliationSession

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.context = AgentContext()
        self.service = ReconciliationSession(token="unit-token")
        self.addCleanup(self.service.close)
        self.config = {
            "model": "local-test:latest",
            "expected_digest": "a" * 64,
            "expected_runtime": "0.34.4",
            "settings": asdict(self.api.PilotSettings()),
            "initial_messages_sha256": "0" * 64,
        }
        self.probe = patch.object(
            self.helper.PublicReferenceAgent, "_probe_environment", AsyncMock()
        )
        self.probe.start()
        self.addCleanup(self.probe.stop)

    def agent(self, instruction="Public"):
        tools = self.service.handle("GET", "/tools", authorization="Bearer unit-token")[1]["tools"]
        messages = self.api.CommandController(instruction, tools).snapshot()["messages"]
        self.config["initial_messages_sha256"] = hashlib.sha256(
            self.api.canonical_json(messages).encode("utf-8")
        ).hexdigest()
        return self.module.PublicModelAgent(logs_dir=self.root, model_config=self.config)

    def environment(self):
        async def execute(*, command, timeout_sec):
            argv = shlex.split(command)
            if argv[2] == "tools":
                code, response = self.service.handle(
                    "GET", "/tools", authorization="Bearer unit-token"
                )
            else:
                body = json.dumps({"name": argv[3], "params": json.loads(argv[5])}).encode()
                code, response = self.service.handle("POST", "/call", body, "Bearer unit-token")
            self.assertEqual(code, 200)
            return SimpleNamespace(
                stdout=json.dumps(response),
                stderr=None,
                return_code=1 if response.get("status") == "error" else 0,
            )

        return SimpleNamespace(exec=AsyncMock(side_effect=execute))

    def provider(self, values):
        queue = iter(values)
        self.requests = []
        self.digest = "a" * 64

        def transport(_client, path, payload=None):
            if path == "/api/tags":
                return {"models": [{"name": self.config["model"], "digest": self.digest}]}
            if path == "/api/version":
                return {"version": "0.34.4"}
            if path == "/api/show":
                return {"capabilities": ["completion", "tools", "thinking"], "details": {}}
            self.assertEqual(path, "/api/chat")
            self.requests.append(payload)
            value = next(queue)
            if callable(value):
                value = value()
            if isinstance(value, BaseException):
                raise value
            if isinstance(value, dict):
                return value
            return {
                "model": self.config["model"],
                "done": True,
                "done_reason": "stop",
                "message": {"role": "assistant", "content": value},
            }

        return patch.object(self.api.RecordingOllamaClient, "_transport_request", transport)

    async def test_real_shared_controller_preserves_settings_and_explicit_finish(self):
        command = (
            '{"action":"call","name":"getPatientHistory","params":{"patient_id":"PAT-AAAAAAAA"}}'
        )
        agent, env = self.agent("Public instruction only"), self.environment()
        with self.provider([command, '{"action":"finish"}']):
            await agent.setup(env)
            await agent.run("Public instruction only", env, self.context)
        state = agent.snapshot()
        self.assertEqual(state["completion"], {"status": "completed", "reason": "model_finish"})
        self.assertEqual(state["model_calls"], 2)
        self.assertEqual(state["controller"]["completion"]["status"], "terminated")
        self.assertEqual(state["identity_before"]["model_digest"], "a" * 64)
        self.assertEqual(state["identity_after"]["model_digest"], "a" * 64)
        self.assertNotIn("tools", self.requests[0])
        self.assertNotIn("format", self.requests[0])
        self.assertNotIn("command_format", state["model_config"])
        self.assertIs(self.requests[0]["think"], False)
        self.assertEqual(
            self.requests[0]["options"],
            {"temperature": 0.0, "seed": 42, "num_ctx": 32768, "num_predict": 4096},
        )
        self.assertEqual(self.requests[0]["keep_alive"], 0)
        self.assertEqual(len(self.service._recorder.calls), 1)
        events = [
            json.loads(line) for line in (self.root / "model-events.jsonl").read_text().splitlines()
        ]
        self.assertEqual(sum(e["event"] == "model_dispatched" for e in events), 2)

    async def test_tool_error_response_reaches_common_controller_without_retry(self):
        agent, env = self.agent(), self.environment()
        command = (
            '{"action":"call","name":"getPatientHistory","params":{"patient_id":"PAT-FFFFFFFF"}}'
        )
        with self.provider([command]):
            await agent.setup(env)
            with self.assertRaises(RuntimeError):
                await agent.run("Public", env, self.context)
        state = agent.snapshot()
        self.assertEqual(state["completion"]["status"], "failed")
        self.assertEqual(state["controller"]["calls"][0]["response"]["status"], "error")
        self.assertEqual(state["exchanges"][-1]["return_code"], 1)
        self.assertEqual(len(self.requests), 1)

    async def test_invalid_native_output_is_retained_without_any_tool_dispatch(self):
        agent, env = self.agent(), self.environment()
        raw = '```json\n{"action":"finish"}\n```'
        with self.provider([raw]):
            await agent.setup(env)
            with self.assertRaises(ValueError):
                await agent.run("Public", env, self.context)
        self.assertEqual(len(self.service._recorder.calls), 0)
        self.assertEqual(
            agent.snapshot()["model_exchanges"][0]["response"]["message"]["content"], raw
        )
        self.assertEqual(agent.snapshot()["completion"]["status"], "failed")

    async def test_postflight_drift_prevents_completion(self):
        agent, env = self.agent(), self.environment()

        def finish_with_drift():
            self.digest = "b" * 64
            return '{"action":"finish"}'

        with self.provider([finish_with_drift]):
            await agent.setup(env)
            with self.assertRaises(ValueError):
                await agent.run("Public", env, self.context)
        self.assertEqual(agent.snapshot()["identity_after"]["model_digest"], "b" * 64)
        self.assertEqual(agent.snapshot()["completion"]["status"], "failed")

    async def test_cancelled_model_thread_cannot_dispatch_or_upgrade_late_finish(self):
        agent, env = self.agent(), self.environment()
        started, release, returned = threading.Event(), threading.Event(), threading.Event()

        def blocked():
            started.set()
            release.wait(5)
            returned.set()
            return '{"action":"finish"}'

        with self.provider([blocked]):
            await agent.setup(env)
            task = asyncio.create_task(agent.run("Public", env, self.context))
            self.assertTrue(await asyncio.to_thread(started.wait, 2))
            task.cancel()
            try:
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                release.set()
            self.assertTrue(await asyncio.to_thread(returned.wait, 2))
            await asyncio.sleep(0.05)
        state = agent.snapshot()
        self.assertEqual(state["completion"]["status"], "interrupted")
        self.assertEqual(len(self.service._recorder.calls), 0)
        events = [
            json.loads(line) for line in (self.root / "model-events.jsonl").read_text().splitlines()
        ]
        self.assertTrue(any(row.get("after_cancellation") for row in events))

    def test_config_requires_explicit_frozen_settings(self):
        del self.config["settings"]["seed"]
        with self.assertRaises(ValueError):
            self.agent()

    def test_config_rejects_surrounding_alias_whitespace_before_client_creation(self):
        self.config["model"] = " local-test:latest "
        with self.assertRaises(ValueError):
            self.agent()

    def test_initial_prompt_digest_is_required_in_model_config(self):
        del self.config["initial_messages_sha256"]
        with self.assertRaises(ValueError):
            self.module.validate_model_config(self.config)

    async def test_changed_initial_instruction_fails_before_client_creation(self):
        agent, env = self.agent("Frozen instruction"), self.environment()
        with patch.object(self.module, "RecordingOllamaClient") as client:
            await agent.setup(env)
            with self.assertRaises(ValueError):
                await agent.run("Changed instruction", env, self.context)
        client.assert_not_called()
        state = agent.snapshot()
        self.assertEqual(state["model_calls"], 0)
        self.assertEqual(state["completion"]["status"], "failed")
        self.assertNotEqual(
            state["initial_messages_sha256_expected"], state["initial_messages_sha256_actual"]
        )
        prompt = json.loads((self.root / "initial-prompt.json").read_text())
        self.assertEqual(prompt["expected_sha256"], self.config["initial_messages_sha256"])
        self.assertEqual(
            prompt["actual_sha256"],
            hashlib.sha256(self.api.canonical_json(prompt["messages"]).encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            json.loads(prompt["messages"][1]["content"])["instruction"], "Changed instruction"
        )

    async def test_changed_discovered_schema_fails_before_client_creation(self):
        agent, env = self.agent(), self.environment()
        with patch.object(self.module, "RecordingOllamaClient") as client:
            await agent.setup(env)
            agent._record["tool_definitions"][0]["description"] += " Changed actual schema."
            with self.assertRaises(ValueError):
                await agent.run("Public", env, self.context)
        client.assert_not_called()
        self.assertEqual(agent.snapshot()["model_calls"], 0)

    async def test_structured_config_is_detached_and_reaches_both_shared_components(self):
        self.config["command_format"] = self.api.command_format_identity()
        original = deepcopy(self.config)
        normalized = self.module.validate_model_config(self.config)
        self.assertEqual(normalized, original)
        normalized["command_format"]["sha256"] = "0" * 64
        self.assertEqual(self.config, original)
        agent, env = self.agent(), self.environment()
        with self.provider(['{"action":"finish"}']):
            await agent.setup(env)
            await agent.run("Public", env, self.context)
        state = agent.snapshot()
        identity = self.api.command_format_identity()
        self.assertEqual(state["model_config"]["command_format"], identity)
        self.assertEqual(state["controller"]["command_format"], identity)
        self.assertEqual(state["completion"]["status"], "completed")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0]["format"], self.api.command_format_schema())
        self.assertIs(self.requests[0]["think"], False)
        self.assertNotIn("tools", self.requests[0])
        self.assertEqual(
            self.requests[0]["options"],
            {"temperature": 0.0, "seed": 42, "num_ctx": 32768, "num_predict": 4096},
        )
        events = [
            json.loads(line) for line in (self.root / "model-events.jsonl").read_text().splitlines()
        ]
        dispatched = [row for row in events if row["event"] == "model_dispatched"]
        self.assertEqual(dispatched[0]["exchange"]["request"], self.requests[0])

    def test_reviewed_format_identity_is_accepted_with_five_legacy_fields(self):
        identity = {
            "version": "healthcraft-reconciliation-command/v2",
            "sha256": "40c74bce3587de9fbd7385f81314f8f6d3d23e978b3024bba2d7b7a734b48794",
        }
        self.config["command_format"] = identity
        normalized = self.module.validate_model_config(self.config)
        self.assertEqual(normalized, self.config)
        normalized["command_format"]["sha256"] = "0" * 64
        self.assertEqual(self.config["command_format"], identity)

    async def test_invalid_command_format_blocks_actual_trial_creation(self):
        from harbor.trial.trial import Trial

        valid = self.api.command_format_identity()
        values = [
            None,
            {},
            "json",
            {"version": valid["version"]},
            {"sha256": valid["sha256"]},
            {**valid, "version": "unrecognized"},
            {**valid, "sha256": "0" * 64},
            {**valid, "schema": {}},
        ]
        for index, identity in enumerate(values):
            with self.subTest(identity=identity):
                value = {**self.config, "command_format": identity}
                with patch.object(Trial, "create", AsyncMock()) as create:
                    with patch.object(self.module, "RecordingOllamaClient") as client:
                        result = await self.helper.run_trial(
                            self.root / "unused-task",
                            self.root / f"invalid-{index}",
                            target={},
                            mode="model",
                            model_config=value,
                        )
                create.assert_not_awaited()
                client.assert_not_called()
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["scheduled_trials"], 1)
                self.assertEqual(result["recorded_trials"], 1)
                self.assertEqual(result["model_calls"], 0)
                self.assertEqual(result["error"]["type"], "ValueError")

    async def test_structured_format_does_not_replace_initial_prompt_guard(self):
        self.config["command_format"] = self.api.command_format_identity()
        agent, env = self.agent("Frozen instruction"), self.environment()
        with patch.object(self.module, "RecordingOllamaClient") as client:
            await agent.setup(env)
            with self.assertRaises(ValueError):
                await agent.run("Changed instruction", env, self.context)
        client.assert_not_called()
        self.assertEqual(agent.snapshot()["model_calls"], 0)
        self.assertEqual(agent.snapshot()["completion"]["status"], "failed")

    def test_structured_format_still_requires_initial_prompt_digest(self):
        self.config["command_format"] = self.api.command_format_identity()
        del self.config["initial_messages_sha256"]
        with self.assertRaises(ValueError):
            self.module.validate_model_config(self.config)


if __name__ == "__main__":
    unittest.main()
