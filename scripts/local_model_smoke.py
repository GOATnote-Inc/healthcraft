"""Exercise local native tool use and a text-only diagnostic judge, without API keys.

This is an integration check, not a benchmark score or clinical validation.
The output is append-only: an existing report path is never overwritten.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from healthcraft.llm.agent import _build_tool_definitions, create_client  # noqa: E402
from healthcraft.llm.judge import LLMJudge  # noqa: E402
from healthcraft.llm.local_models import is_local_model  # noqa: E402
from healthcraft.llm.orchestrator import _check_local_judge_pair  # noqa: E402
from healthcraft.mcp.server import create_server  # noqa: E402
from healthcraft.tasks.rubrics import Criterion, VerificationMethod  # noqa: E402
from healthcraft.world.seed import WorldSeeder  # noqa: E402


def run_smoke(agent_model: str, judge_model: str) -> dict:
    if not is_local_model(agent_model) or not is_local_model(judge_model):
        raise ValueError("Smoke test requires two explicit ollama: model identifiers")
    agent = create_client(agent_model, "")
    judge_client = create_client(judge_model, "")
    agent_info = agent.validate_capabilities(require_tools=True)
    judge_info = judge_client.validate_capabilities()
    _check_local_judge_pair(agent_info, judge_info)
    world = WorldSeeder(seed=42).seed_world(PROJECT_ROOT / "configs/world/mercy_point_v1.yaml")
    server = create_server(world)
    encounter_id = sorted(world.list_entities("encounter"))[0]
    tools = [t for t in _build_tool_definitions(server) if t["name"] == "getEncounterDetails"]
    messages = [
        {"role": "system", "content": "Test the synthetic HEALTHCRAFT tool interface."},
        {"role": "user", "content": f"Call getEncounterDetails for {encounter_id}. Use the tool."},
    ]
    started = time.monotonic()
    response = agent.chat(messages, tools=tools, max_tokens=256)
    if response.get("stop_reason", "tool_calls") not in ("tool_calls", "tool_use"):
        raise RuntimeError(f"Agent tool response incomplete: {response.get('stop_reason')}")
    calls = response["tool_calls"]
    if len(calls) != 1 or calls[0]["name"] != "getEncounterDetails":
        raise RuntimeError(f"Agent did not issue the required native tool call: {response}")
    call = calls[0]
    if call["arguments"] != {"encounter_id": encounter_id}:
        raise RuntimeError(f"Agent supplied incorrect synthetic encounter arguments: {call}")
    result = server.call_tool(call["name"], call["arguments"])
    if result.get("status") != "ok":
        raise RuntimeError(f"HEALTHCRAFT tool failed: {result}")
    messages.extend(
        [
            {"role": "assistant", "content": response["content"], "tool_calls": calls},
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": json.dumps(result, default=str),
            },
            {
                "role": "user",
                "content": "State the encounter_id you just retrieved in one sentence.",
            },
        ]
    )
    final = agent.chat(messages, max_tokens=128)
    if final.get("stop_reason", "stop") not in ("stop", "end_turn", "stop_sequence") or final.get(
        "tool_calls"
    ):
        raise RuntimeError(f"Agent final response incomplete: {final.get('stop_reason')}")
    if encounter_id not in final["content"]:
        raise RuntimeError(f"Agent did not use the tool response: {final}")
    agent_seconds = time.monotonic() - started

    # Known positive/negative labels check parsing and discrimination only.
    criterion = Criterion(
        id="LOCAL-SMOKE-C01",
        assertion="Agent explicitly stated the identifier ENC-001.",
        dimension="documentation_quality",
        verification=VerificationMethod.LLM_JUDGE,
    )
    judge = LLMJudge(judge_client, judge_model=judge_model, prompt_version="v2")
    judged = []
    for content, expected in [
        ("The encounter identifier is ENC-001.", True),
        ("I do not know the identifier.", False),
    ]:
        verdict = judge.evaluate_criterion(criterion, [{"role": "assistant", "content": content}])
        judged.append(
            {
                "expected": expected,
                "satisfied": verdict.satisfied,
                "evidence": verdict.evidence,
                "error": verdict.error,
            }
        )
    return {
        "kind": "local_integration_smoke",
        "benchmark_score": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "agent": agent_info,
        "judge": judge_info,
        "tool_roundtrip_passed": True,
        "tool_call": call,
        "agent_final": final["content"],
        "agent_seconds": round(agent_seconds, 3),
        "judge_sanity_cases": judged,
        "passed": all(
            case["error"] is None and case["satisfied"] == case["expected"] for case in judged
        ),
        "duration_seconds": round(time.monotonic() - started, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-model", required=True)
    parser.add_argument("--judge-model", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("Output already exists; use a new path to preserve prior evidence")
    report = run_smoke(args.agent_model, args.judge_model)
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    print(encoded, end="")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
