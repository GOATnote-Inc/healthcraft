"""One free local instruction-following probe; no clinical or benchmark assessment.

Only createClinicalOrder is advertised. This is a deliberately restricted
integration check, not an unrestricted agent evaluation. Existing output paths
are refused before runtime inspection or inference. No retries or downloads.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import signal
import sys
import time
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from healthcraft.llm.agent import run_agent_task  # noqa: E402
from healthcraft.llm.local_models import OllamaClient, is_local_model  # noqa: E402
from healthcraft.llm.review_context import (  # noqa: E402
    context_digest,
    freeze_review_context,
    seal_review_context,
)
from healthcraft.mcp.server import create_server  # noqa: E402
from healthcraft.tasks.history_execution import ExecutionRecorder  # noqa: E402
from healthcraft.tasks.loader import Task  # noqa: E402
from healthcraft.trajectory import Trajectory, trajectory_completion  # noqa: E402
from healthcraft.world.state import WorldState  # noqa: E402

ORDER_REQUEST = {
    "encounter_id": "ENC-FEED0001",
    "order_type": "lab",
    "priority": "urgent",
    "indication": "Synthetic software transport check only; no clinical interpretation.",
    "details": {
        "test_name": "SYNTHETIC-TRANSPORT-CHECK",
        "specimen": "synthetic-only",
        "instructions": ["Preserve literal values", "Do not infer a clinical action"],
        "probe": {"version": 1, "clinical_use": False},
    },
}
SYSTEM_PROMPT = (
    "You are testing a synthetic software interface. Execute only the explicitly requested "
    "order exactly once. Do not infer clinical facts, change fields, or perform other actions. "
    "After the tool response, briefly acknowledge its actual status."
)


def _json(value):
    def default(item):
        if is_dataclass(item):
            return asdict(item)
        if isinstance(item, (datetime, date)):
            return item.isoformat()
        if isinstance(item, Enum):
            return item.value
        raise TypeError(f"Unsupported evidence type: {type(item).__name__}")

    return json.loads(json.dumps(value, default=default, allow_nan=False))


def source_hashes():
    """Bind source/config/request code, excluding generated output artifacts."""
    paths = set((ROOT / "src/healthcraft").rglob("*.py"))
    for directory in ("configs", "system-prompts"):
        paths.update(p for p in (ROOT / directory).rglob("*") if p.is_file())
    paths.update({Path(__file__).resolve(), ROOT / "pyproject.toml"})
    paths.update(ROOT.glob("requirements*.txt"))
    return {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)
    }


def runtime_identity():
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": sorted(
            {(d.metadata["Name"], d.version) for d in importlib.metadata.distributions()}
        ),
        "flags": {
            key: os.environ.get(key)
            for key in (
                "HC_IDEMPOTENT_TOOLS",
                "HC_ENABLE_FAULT_INJECTION",
                "HC_DYNAMIC_STATE",
            )
        },
    }


@contextmanager
def _request_deadline(seconds):
    """Hard wall-clock limit for this single-threaded POSIX diagnostic CLI."""

    def expired(signum, frame):
        raise TimeoutError("Local probe request exceeded its wall-clock deadline")

    old_handler = signal.getsignal(signal.SIGALRM)
    if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
        raise RuntimeError("Probe cannot replace an active process alarm")
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)


class _BudgetClient:
    def __init__(self, client, max_responses, max_output_tokens, timeout):
        self.client = client
        self.limit = max_responses
        self.tokens = max_output_tokens
        self.timeout = timeout
        self.deadline = time.monotonic() + max_responses * timeout
        self.exchanges = []
        self.budget_exhausted = False

    def chat(self, messages, *, tools):
        if len(self.exchanges) >= self.limit or time.monotonic() >= self.deadline:
            self.budget_exhausted = True
            raise RuntimeError("Local probe response/time budget exhausted; no additional request")
        exchange = {"messages": deepcopy(messages), "response": None, "error": None}
        self.exchanges.append(exchange)
        try:
            with _request_deadline(min(self.timeout, self.deadline - time.monotonic())):
                result = self.client.chat(
                    messages, tools=tools, temperature=0, max_tokens=self.tokens
                )
            exchange["response"] = deepcopy(result)
            return result
        except Exception as exc:
            exchange["error"] = f"{type(exc).__name__}: {exc}"
            raise


class _RecordedServer:
    available_tools = ("createClinicalOrder",)

    def __init__(self, world):
        self.recorder = ExecutionRecorder(create_server(world), world)

    def call_tool(self, name, params):
        # The actual server still records unexpected attempted tool calls. They
        # cannot satisfy the exact-one-action verifier below.
        return self.recorder.call(name, params)


def verify_action(world, calls):
    """Inspect actual stored work independently of model assertions."""
    errors = []
    orders = world.list_entities("order")
    tasks = world.list_entities("clinical_task")
    if len(orders) != 1 or len(tasks) != 1:
        errors.append("Expected exactly one persisted order and one linked clinical task")
    if len(calls) != 1 or len(world.audit_log) != 1:
        errors.append("Expected exactly one actual tool invocation and matching audit entry")
    if len(orders) == len(tasks) == len(calls) == len(world.audit_log) == 1:
        order = next(iter(orders.values()))
        task = _json(next(iter(tasks.values())))
        call, audit = calls[0], world.audit_log[0]
        for field, expected in ORDER_REQUEST.items():
            if order.get(field) != expected:
                errors.append(f"Stored order {field} differs from the explicit request")
        if not (
            call["name"] == audit.tool_name == "createClinicalOrder"
            and call["params"] == audit.params == ORDER_REQUEST
            and call["audit_index"] == 0
            and audit.result_summary == call["response"].get("status") == "ok"
            and call["response"].get("data") == order
            and call["response"].get("deduplicated") is not True
        ):
            errors.append("Actual request, audit, response and persisted order do not agree")
        if (
            order.get("ordered_at") != world.timestamp.isoformat()
            or audit.timestamp != world.timestamp
        ):
            errors.append("Order, audit and world timestamps do not agree")
        expected_task = {
            "id": order.get("task_id"),
            "task_id": order.get("task_id"),
            "encounter_id": ORDER_REQUEST["encounter_id"],
            "task_type": "lab_draw",
            "priority": ORDER_REQUEST["priority"],
            "notes": ORDER_REQUEST["indication"],
            "assigned_to": "",
            "due_time": None,
            "completed_time": None,
            "created_at": world.timestamp.isoformat(),
            "updated_at": world.timestamp.isoformat(),
        }
        for field, expected in expected_task.items():
            if task.get(field) != expected:
                errors.append(f"Linked clinical task {field} differs from requested work")
        try:
            if json.loads(task["description"]) != {
                "order_type": ORDER_REQUEST["order_type"],
                "details": ORDER_REQUEST["details"],
            }:
                errors.append("Linked clinical task action details differ from requested work")
        except (KeyError, TypeError, ValueError):
            errors.append("Linked clinical task action description is missing or malformed")
    return {"passed": not errors, "errors": errors}


def run_probe(
    agent_model, *, max_responses=4, max_output_tokens=256, timeout=45, client_factory=OllamaClient
):
    """Run one attempt; injected clients are for offline tests only."""
    if not is_local_model(agent_model) or "cloud" in agent_model.lower():
        raise ValueError("An explicit installed ollama: model identifier is required")
    if not (
        type(max_responses) is int
        and 1 <= max_responses <= 4
        and type(max_output_tokens) is int
        and 1 <= max_output_tokens <= 512
        and 0 < timeout <= 60
    ):
        raise ValueError("Probe limits require 1-4 responses, 1-512 output tokens, timeout <=60s")
    started = time.monotonic()
    before, runtime_before = source_hashes(), runtime_identity()
    task = Task(
        id="LOCAL-ORDER-PROBE-V1",
        category="integration_diagnostic",
        level=1,
        title="Synthetic order transport",
        description="Create exactly one order using these exact arguments:\n"
        + json.dumps(ORDER_REQUEST),
        initial_state={},
        expected_tools=("createClinicalOrder",),
        metadata={},
        criteria=(
            {
                "id": "LOCAL-ORDER-PROBE-C01",
                "assertion": "Exact authored action is persisted",
                "verification": "world_state",
                "dimension": "documentation_quality",
            },
        ),
    )
    context = {"profile_version": "local-order-probe/v1", "clinical_assessment": False}
    settings = {
        "max_responses": max_responses,
        "max_output_tokens": max_output_tokens,
        "request_timeout_seconds": timeout,
        "temperature": 0,
        "num_ctx": 8192,
        "seed": 42,
        "think": False,
        "automatic_retries": 0,
        "hard_request_timeout_seconds": timeout,
        "inference_deadline_seconds": max_responses * timeout,
    }
    identity = context_digest({"sources": before, "task": asdict(task), "settings": settings})
    draft = freeze_review_context(
        task,
        list(task.criteria),
        rubric_channel="v8",
        scenario_context=context,
        checkpoint_identity=identity,
        grading_mode="profile_diagnostic",
    )
    world = WorldState()
    world.put_entity("patient", "PAT-FEED0001", {"id": "PAT-FEED0001", "allergies": []})
    world.put_entity(
        "encounter",
        ORDER_REQUEST["encounter_id"],
        {"id": ORDER_REQUEST["encounter_id"], "patient_id": "PAT-FEED0001", "clinical_notes": []},
    )
    server = _RecordedServer(world)
    trajectory = Trajectory(
        task_id=task.id, model=agent_model, seed=42, system_prompt=SYSTEM_PROMPT
    )
    errors, info_before, info_after, bounded = [], None, None, None
    stage = "model_setup"
    client_args = {
        "model": agent_model.removeprefix("ollama:"),
        "seed": 42,
        "num_ctx": 8192,
        "think": False,
        "timeout": timeout,
    }
    try:
        client = client_factory(**client_args)
        with _request_deadline(timeout):
            info_before = client.validate_capabilities(require_tools=True)
        identity = context_digest(
            {
                "sources": before,
                "task": asdict(task),
                "settings": settings,
                "agent_model": agent_model,
                "model": info_before,
            }
        )
        draft = freeze_review_context(
            task,
            list(task.criteria),
            rubric_channel="v8",
            scenario_context=context,
            checkpoint_identity=identity,
            grading_mode="profile_diagnostic",
        )
        bounded = _BudgetClient(client, max_responses, max_output_tokens, timeout)
        stage = "agent_execution"
        trajectory = run_agent_task(bounded, task, server, SYSTEM_PROMPT)
    except Exception as exc:
        errors.append({"stage": stage, "error": f"{type(exc).__name__}: {exc}"})
        trajectory.error = f"{stage}: {type(exc).__name__}: {exc}"
    try:
        with _request_deadline(timeout):
            info_after = client_factory(**client_args).validate_capabilities(require_tools=True)
    except Exception as exc:
        errors.append({"stage": "model_after", "error": f"{type(exc).__name__}: {exc}"})
    after, runtime_after = source_hashes(), runtime_identity()
    trajectory.model, trajectory.rubric_channel = agent_model, "v8"
    trajectory.metadata.update(
        {
            "evaluation_mode": "profile_diagnostic",
            "scenario_context": context,
            "checkpoint_identity": identity,
            "grading_enabled": False,
            "grading_complete": False,
            "benchmark_comparable": False,
            "benchmark_score": None,
            "ungraded_criteria": 1,
        }
    )
    trajectory.metadata["review_context"] = seal_review_context(draft, trajectory)
    captured = trajectory.to_dict()
    # These dataclass defaults were never assessed. Do not export them as scores.
    captured.update(reward=None, passed=None, safety_gate_passed=None)
    completion, reason = trajectory_completion(
        captured["turns"], captured["metadata"], captured["error"]
    )
    fidelity = verify_action(world, server.recorder.calls)
    stable = (
        before == after
        and runtime_before == runtime_after
        and info_before == info_after
        and info_before is not None
    )
    return _json(
        {
            "kind": "restricted_local_order_integration",
            "created_at": datetime.now(timezone.utc),
            "grading_enabled": False,
            "benchmark_score": None,
            "coverage": {"clinical": 0, "safety": 0},
            "integration_passed": fidelity["passed"]
            and completion == "complete"
            and stable
            and not errors,
            "action_fidelity": fidelity,
            "completion": {"status": completion, "reason": reason},
            "trajectory": captured,
            "actual_calls": server.recorder.calls,
            "audit_log": world.audit_log,
            "errors": errors,
            "request": ORDER_REQUEST,
            "model_before": info_before,
            "model_after": info_after,
            "settings": settings,
            "model_call_count": len(bounded.exchanges) if bounded else 0,
            "budget_exhausted": bounded.budget_exhausted if bounded else False,
            "exchanges": bounded.exchanges if bounded else [],
            "final_state": {
                kind: world.list_entities(kind)
                for kind in ("patient", "encounter", "order", "clinical_task")
            },
            "source_hashes_before": before,
            "source_hashes_after": after,
            "runtime_before": runtime_before,
            "runtime_after": runtime_after,
            "provenance_stable": stable,
            "duration_seconds": round(time.monotonic() - started, 3),
            "limitations": "One synthetic, one-tool instruction-following attempt. No clinical judgment, human review, benchmark performance or readiness evidence.",
        }
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-responses", type=int, default=4)
    parser.add_argument("--max-output-tokens", type=int, default=256)
    parser.add_argument("--timeout", type=float, default=45)
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(
            {
                "kind": "restricted_local_order_integration",
                "status": "started",
                "benchmark_score": None,
                "grading_enabled": False,
            },
            handle,
        )
        handle.flush()
        try:
            report = run_probe(
                args.agent_model,
                max_responses=args.max_responses,
                max_output_tokens=args.max_output_tokens,
                timeout=args.timeout,
            )
        except Exception as exc:
            report = {
                "kind": "restricted_local_order_integration",
                "integration_passed": False,
                "grading_enabled": False,
                "benchmark_score": None,
                "errors": [{"stage": "harness", "error": f"{type(exc).__name__}: {exc}"}],
            }
        handle.seek(0)
        handle.truncate()
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "integration_passed": report["integration_passed"],
            }
        )
    )
    return 0 if report["integration_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
