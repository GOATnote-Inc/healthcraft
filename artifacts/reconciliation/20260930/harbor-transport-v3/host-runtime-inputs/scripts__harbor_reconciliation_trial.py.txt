#!/usr/bin/env python3
"""Run one optional Harbor 0.8.0 reference/control trial without model calls.

The coordinator owns the private backend and the hard process deadline. Harbor's
shared verifier reward is connectivity-only; the independent host oracle judges
source retention and persistence after private finalization.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import os
import shlex
import uuid
from copy import deepcopy
from pathlib import Path

from harbor.agents.base import BaseAgent

from healthcraft.reconciliation.terminal import _json_object, _json_text

HARBOR_VERSION = "0.8.0"
HARBOR_COMMIT = "22b83271db78ef4bcbeb2402cdd154979cf87912"
PUBLIC_TOOLS = {
    "searchPatients",
    "searchEncounters",
    "getPatientHistory",
    "getEncounterDetails",
    "updateEncounter",
}


def reference_commands(tools, *, target):
    """Load the shared public-data controller only when execution begins."""
    from healthcraft.reconciliation.controller import reference_commands as controller

    return controller(tools, target=target)


def _write_json(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(_json_text(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


class PublicReferenceAgent(BaseAgent):
    """Actual Harbor external agent; only fixed CLI commands cross the boundary."""

    def __init__(
        self,
        logs_dir: Path,
        *,
        target: dict,
        mode: str = "reference",
        terminal_path: str = "/usr/local/bin/hc-ehr.py",
        command_timeout: int = 30,
        **kwargs,
    ):
        super().__init__(logs_dir=logs_dir, **kwargs)
        if mode not in {"reference", "noop"}:
            raise ValueError("Unsupported scripted control")
        if type(command_timeout) is not int or not 1 <= command_timeout <= 30:
            raise ValueError("Command timeout must be an integer from 1 through 30")
        if type(target) is not dict or set(target) != {"patient_id", "encounter_id"}:
            raise ValueError("Only public patient and encounter target IDs are accepted")
        if any(type(value) is not str or not value for value in target.values()):
            raise ValueError("Public target IDs must be nonempty strings")
        self.target = deepcopy(target)
        self.mode = mode
        self.terminal_path = terminal_path
        self.command_timeout = command_timeout
        self._context = None
        self._record = {
            "schema_version": "harbor-public-reference/v1",
            "mode": mode,
            "model_calls": 0,
            "completion": {"status": "not_started"},
            "exchanges": [],
            "tool_definitions": None,
            "instruction": None,
        }
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._journal = self.logs_dir / "terminal-exchanges.jsonl"
        self._journal.touch(exist_ok=False)

    @staticmethod
    def name() -> str:
        return "healthcraft-public-reference"

    def version(self) -> str:
        return "1"

    def snapshot(self) -> dict:
        return deepcopy(self._record)

    def _publish(self, event: str, exchange: dict | None = None) -> None:
        entry = {"event": event, "completion": self._record["completion"]}
        if exchange is not None:
            entry["exchange"] = exchange
        with self._journal.open("a", encoding="utf-8") as stream:
            stream.write(_json_text(entry) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if self._context is not None:
            self._context.metadata = {"healthcraft_reconciliation": self.snapshot()}

    def _failed(self, exc: BaseException) -> None:
        self._record["completion"] = {
            "status": "interrupted"
            if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt))
            else "failed",
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
        self._publish("controller_failed")

    async def _exchange(self, environment, command: dict | None = None) -> dict:
        argv = ["python", self.terminal_path]
        if command is None:
            argv.append("tools")
        else:
            if (
                type(command) is not dict
                or set(command) != {"action", "name", "params"}
                or command["action"] != "call"
                or command["name"] not in PUBLIC_TOOLS
                or type(command["params"]) is not dict
            ):
                raise ValueError("Unsupported public controller command")
            argv.extend(["call", command["name"], "--params-json", _json_text(command["params"])])
        shell_command = shlex.join(argv)
        exchange = {
            "index": len(self._record["exchanges"]) + 1,
            "command": shell_command,
            "request": deepcopy(command),
            "status": "requested",
            "outcome": "unknown",
            "stdout": None,
            "stderr": None,
            "return_code": None,
        }
        self._record["exchanges"].append(exchange)
        self._publish("requested", exchange)
        try:
            result = await environment.exec(command=shell_command, timeout_sec=self.command_timeout)
            exchange.update(
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.return_code,
                status="returned",
            )
            self._publish("returned", exchange)
            if type(result.return_code) is not int or result.return_code != 0:
                raise ValueError("Terminal command did not exit successfully")
            if type(result.stdout) is not str or result.stderr not in (None, ""):
                raise ValueError("Expected one terminal JSON output stream")
            response = _json_object(result.stdout)
            if command is None:
                if set(response) != {"tools"} or type(response["tools"]) is not list:
                    raise ValueError("Malformed tool discovery response")
            elif response.get("status") != "ok" or "data" not in response:
                raise ValueError("Terminal success exit disagrees with tool response")
            exchange["outcome"] = "returned"
            self._publish("validated", exchange)
            return response
        except BaseException as exc:
            exchange["error"] = {"type": type(exc).__name__, "message": str(exc)}
            self._publish("failed", exchange)
            raise

    async def setup(self, environment) -> None:
        try:
            result = await self._exchange(environment)
            self._record["tool_definitions"] = result["tools"]
        except BaseException as exc:
            self._failed(exc)
            raise

    async def run(self, instruction, environment, context) -> None:
        self._context = context
        self._record["instruction"] = instruction
        self._record["completion"] = {"status": "running"}
        self._publish("controller_started")
        try:
            if self.mode == "reference":
                commands = reference_commands(self._record["tool_definitions"], target=self.target)
                response = None
                for index in range(32):
                    try:
                        command = next(commands) if index == 0 else commands.send(response)
                    except StopIteration as ended:
                        if ended.value != {
                            "status": "terminated",
                            "reason": "reference_readback_verified",
                        }:
                            raise ValueError("Reference ended without verified readback") from None
                        break
                    response = await self._exchange(environment, command)
                else:
                    raise ValueError("Reference command limit reached")
            self._record["completion"] = {
                "status": "completed",
                "reason": "reference_readback_verified" if self.mode == "reference" else "noop",
            }
            self._publish("controller_completed")
        except BaseException as exc:
            self._failed(exc)
            raise


async def run_trial(
    task_dir: Path,
    output_dir: Path,
    *,
    target: dict,
    mode: str = "reference",
    timeout_sec: int = 180,
    terminal_path: str = "/usr/local/bin/hc-ehr.py",
) -> dict:
    """Run the real SDK lifecycle; parent process owns the hard outer deadline.

    asyncio cancellation requests SDK cleanup, which can outlast timeout_sec.
    Fresh output is mandatory, including for preparation failures. Backend
    finalization and authoritative independent oracle evaluation are external.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    trial_name = f"hc-reconcile-{uuid.uuid4().hex[:12]}"
    receipt = {
        "schema_version": "harbor-reconciliation-trial/v1",
        "status": "scheduled",
        "scheduled_trials": 1,
        "recorded_trials": 1,
        "trial_name": trial_name,
        "mode": mode,
        "harbor_version": HARBOR_VERSION,
        "harbor_commit": HARBOR_COMMIT,
        "model_calls": 0,
        "benchmark_score": None,
        "clinical_assessment": "unassessed",
        "verifier_scope": "terminal_connectivity_only",
        "independent_oracle": "pending_private_backend_finalization",
        "controller_completed": False,
        "cleanup_status": "unknown",
    }
    _write_json(output_dir / "scheduled.json", receipt)
    trial = None
    try:
        if importlib.metadata.version("harbor") != HARBOR_VERSION:
            raise ValueError("This integration requires the pinned Harbor 0.8.0 runtime")
        if type(timeout_sec) is not int or not 1 <= timeout_sec <= 600:
            raise ValueError("Trial timeout must be an integer from 1 through 600")
        os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
        os.environ["LITELLM_MODE"] = "PRODUCTION"
        import litellm
        from harbor.models.trial.config import (
            AgentConfig,
            EnvironmentConfig,
            TaskConfig,
            TrialConfig,
        )
        from harbor.trial.trial import Trial

        litellm.telemetry = False
        config = TrialConfig(
            task=TaskConfig(path=Path(task_dir).resolve()),
            trial_name=trial_name,
            trials_dir=output_dir / "trials",
            agent=AgentConfig(
                import_path="scripts.harbor_reconciliation_trial:PublicReferenceAgent",
                override_timeout_sec=timeout_sec,
                kwargs={"target": target, "mode": mode, "terminal_path": terminal_path},
            ),
            environment=EnvironmentConfig(type="docker", delete=False),
        )
        trial = await Trial.create(config)
        result = await asyncio.wait_for(trial.run(), timeout=timeout_sec)
        result_json = result.model_dump(mode="json")
        _write_json(output_dir / "harbor-result.json", result_json)
        receipt["harbor_exception"] = result_json.get("exception_info")
        receipt["status"] = "completed" if receipt["harbor_exception"] is None else "failed"
    except (Exception, asyncio.CancelledError) as exc:
        receipt["status"] = "interrupted" if isinstance(exc, asyncio.CancelledError) else "failed"
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        if trial is not None:
            state = trial.agent.snapshot()
            receipt["agent"] = state
            _write_json(output_dir / "agent-receipt.json", state)
            receipt["controller_completed"] = (
                receipt["status"] == "completed"
                and state["completion"]["status"] == "completed"
                and all(
                    row["status"] == "returned" and row["return_code"] == 0
                    for row in state["exchanges"]
                )
            )
            # Harbor catches some cleanup errors. This means SDK returned, not
            # that independently inspected containers or child processes ended.
            receipt["cleanup_status"] = "sdk_returned_independent_inspection_required"
        _write_json(output_dir / "receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--patient-id", required=True)
    parser.add_argument("--encounter-id", required=True)
    parser.add_argument("--mode", choices=("reference", "noop"), default="reference")
    parser.add_argument("--timeout-sec", type=int, default=180)
    args = parser.parse_args()
    receipt = asyncio.run(
        run_trial(
            args.task_dir,
            args.output_dir,
            target={"patient_id": args.patient_id, "encounter_id": args.encounter_id},
            mode=args.mode,
            timeout_sec=args.timeout_sec,
        )
    )
    print(_json_text(receipt))
    return 0 if receipt["controller_completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
