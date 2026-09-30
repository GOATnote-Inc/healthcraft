"""Optional host-native Ollama agent for the actual Harbor terminal lifecycle.

This module never selects a model or starts inference on import. The coordinator
must authorize and supervise each separately scheduled attempt. A model finish
is termination only; the independent private-backend oracle remains separate.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import threading
import time
from copy import deepcopy
from dataclasses import asdict, fields
from pathlib import Path

from healthcraft.reconciliation.controller import (
    CommandController,
    PilotSettings,
    RecordingOllamaClient,
    canonical_json,
)
from healthcraft.reconciliation.terminal import _json_text
from scripts.harbor_reconciliation_trial import PublicReferenceAgent, _write_json


def validate_model_config(value: dict) -> dict:
    """Require all frozen settings explicitly, with no provider/default fallback."""
    if type(value) is not dict or set(value) != {
        "model",
        "expected_digest",
        "expected_runtime",
        "settings",
        "initial_messages_sha256",
    }:
        raise ValueError(
            "Expected exactly model, expected_digest, expected_runtime, settings "
            "and initial_messages_sha256"
        )
    if (
        type(value["model"]) is not str
        or not value["model"].strip()
        or value["model"] != value["model"].strip()
        or type(value["expected_runtime"]) is not str
        or not value["expected_runtime"].strip()
        or type(value["expected_digest"]) is not str
        or re.fullmatch(r"[0-9a-f]{64}", value["expected_digest"]) is None
        or type(value["initial_messages_sha256"]) is not str
        or re.fullmatch(r"[0-9a-f]{64}", value["initial_messages_sha256"]) is None
        or type(value["settings"]) is not dict
        or set(value["settings"]) != {field.name for field in fields(PilotSettings)}
    ):
        raise ValueError("Model identities and every PilotSettings field must be explicit")
    settings = PilotSettings(**value["settings"])
    return deepcopy({**value, "settings": asdict(settings)})


class PublicModelAgent(PublicReferenceAgent):
    """Use the shared controller; execute only fixed terminal commands in main."""

    def __init__(self, logs_dir: Path, *, model_config: dict, **kwargs):
        config = validate_model_config(model_config)
        supplied_model = kwargs.pop("model_name", None)
        if supplied_model not in (None, config["model"]):
            raise ValueError("Harbor model name differs from the frozen model configuration")
        self._event_lock = threading.RLock()
        self._cancelled = False
        super().__init__(logs_dir, target=None, mode="noop", model_name=config["model"], **kwargs)
        self.mode = "model"
        self.settings = PilotSettings(**config["settings"])
        self.model_config = config
        self._record.update(
            schema_version="harbor-public-model/v1",
            mode="model",
            model_config=config,
            controller=None,
            model_exchanges=[],
            identity_before=None,
            identity_after=None,
            postflight_status="not_attempted",
        )
        self._model_journal = self.logs_dir / "model-events.jsonl"
        self._model_journal.touch(exist_ok=False)

    @staticmethod
    def name() -> str:
        return "healthcraft-native-ollama-terminal"

    def version(self) -> str:
        return "1"

    def snapshot(self) -> dict:
        with self._event_lock:
            return super().snapshot()

    def _publish(self, event: str, exchange: dict | None = None) -> None:
        with self._event_lock:
            super()._publish(event, exchange)

    def _model_event(self, event: dict) -> None:
        """Synchronous durable sink; late thread events cannot upgrade completion."""
        with self._event_lock:
            event = deepcopy(event)
            event["after_cancellation"] = self._cancelled
            with self._model_journal.open("a", encoding="utf-8") as stream:
                stream.write(_json_text(event) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            if self._cancelled:
                return
            if "controller" in event:
                self._record["controller"] = event["controller"]
            if "exchange" in event:
                row = event["exchange"]
                index = row["index"] - 1
                if index == len(self._record["model_exchanges"]):
                    self._record["model_exchanges"].append(row)
                else:
                    self._record["model_exchanges"][index] = row
                self._record["model_calls"] = len(self._record["model_exchanges"])
            self._publish("model_state_updated")

    async def run(self, instruction, environment, context) -> None:
        self._context = context
        self._record["instruction"] = instruction
        self._record["completion"] = {"status": "running"}
        self._publish("controller_started")
        client = None
        controller = None
        failure = None
        started = time.monotonic()
        try:
            controller = CommandController(
                instruction,
                self._record["tool_definitions"],
                settings=self.settings,
                event_sink=self._model_event,
            )
            messages = controller.snapshot()["messages"]
            actual = hashlib.sha256(canonical_json(messages).encode("utf-8")).hexdigest()
            expected = self.model_config["initial_messages_sha256"]
            prompt = {"expected_sha256": expected, "actual_sha256": actual, "messages": messages}
            self._record["initial_messages_sha256_expected"] = expected
            self._record["initial_messages_sha256_actual"] = actual
            _write_json(self.logs_dir / "initial-prompt.json", prompt)
            self._model_event({"event": "initial_prompt", "initial_prompt": prompt})
            if actual != expected:
                raise ValueError("Actual initial messages differ from the frozen prompt digest")
            client = RecordingOllamaClient(
                model=self.model_config["model"],
                expected_digest=self.model_config["expected_digest"],
                expected_runtime=self.model_config["expected_runtime"],
                settings=self.settings,
                event_sink=self._model_event,
            )
            self._record["identity_before"] = await asyncio.to_thread(client.preflight)
            self._publish("model_identity_before")
            while True:
                command = await asyncio.to_thread(controller.next_command, client)
                # Cancellation of this coroutine never resumes this dispatch.
                if command == {"action": "finish"}:
                    break
                response = await self._exchange(environment, command, allow_tool_error=True)
                controller.accept_result(response)
        except (Exception, asyncio.CancelledError, KeyboardInterrupt) as exc:
            failure = exc
            if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)):
                with self._event_lock:
                    self._cancelled = True
            if controller is not None:
                controller.fail(
                    exc, reason="adapter_interrupted" if self._cancelled else "adapter_error"
                )
                self._record["controller"] = controller.snapshot()
            self._failed(exc)
        finally:
            if client is not None:
                self._record["identity_before"] = deepcopy(client.identity_before)
            remaining = self.settings.attempt_timeout_seconds - (time.monotonic() - started)
            if client is not None and not self._cancelled and remaining > 0:
                try:
                    # Match the direct arm's native socket timeout; the parent
                    # process applies the common hard whole-attempt deadline.
                    self._record["identity_after"] = await asyncio.to_thread(client.postflight)
                    self._record["postflight_status"] = "matched"
                except (Exception, asyncio.CancelledError) as exc:
                    self._record["identity_after"] = deepcopy(client.identity_after)
                    self._record["postflight_status"] = "failed"
                    self._record["postflight_error"] = {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                    if failure is None:
                        failure = exc
                        self._failed(exc)
            else:
                self._record["postflight_status"] = "unavailable_after_interruption_or_deadline"
                if failure is None:
                    failure = TimeoutError("No remaining time for fresh model identity validation")
                    self._failed(failure)
            if failure is None:
                self._record["completion"] = {"status": "completed", "reason": "model_finish"}
                self._publish("controller_completed")
            else:
                self._publish("model_attempt_failed")
        if failure is not None:
            raise failure
