"""Pre-flight validation for HEALTHCRAFT evaluations.

Runs three checks in <30 seconds:
  1. Schema-Handler Contract Tests — every tool in mcp-tools.json dispatches ok
  2. Evaluator Smoke Test — success/failure distinction in world_state verification
  3. Criteria-Tool Existence Check — world_state check targets exist in tool registry

Usage:
    python scripts/preflight.py
    make preflight
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve project root so imports work from any directory.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

TOOLS_JSON = PROJECT_ROOT / "configs" / "mcp-tools.json"
WORLD_CONFIG = PROJECT_ROOT / "configs" / "world" / "mercy_point_v1.yaml"
TASK_DIR = PROJECT_ROOT / "configs" / "tasks"


def _load_tool_names() -> set[str]:
    """Load camelCase tool names from mcp-tools.json."""
    with open(TOOLS_JSON) as f:
        data = json.load(f)
    return {tool["name"] for tool in data["tools"]}


# ---------------------------------------------------------------------------
# Check 1: Schema-Handler Contract Tests
# ---------------------------------------------------------------------------

# Minimal valid inputs that satisfy each handler's _require() checks.
# Only required params are provided — we just need status != "internal_error".
_MINIMAL_INPUTS: dict[str, dict] = {
    "searchEncounters": {},
    "searchPatients": {},
    "searchClinicalKnowledge": {"query": "chest pain"},
    "searchReferenceMaterials": {"query": "aspirin"},
    "searchAvailableResources": {"resource_type": "bed"},
    "getEncounterDetails": {"encounter_id": "ENC-00000000"},
    "getConditionDetails": {},
    "getPatientHistory": {"patient_id": "PAT-00000000"},
    "getProtocolDetails": {},
    "getTransferStatus": {},
    "getInsuranceCoverage": {"patient_id": "PAT-00000000"},
    "getReferenceArticle": {},
    "checkResourceAvailability": {"resource_type": "bed"},
    "calculateTransferTime": {"destination_facility": "General Hospital"},
    "runDecisionRule": {"rule_name": "qSOFA", "variables": {"sbp": 90}},
    "validateTreatmentPlan": {"patient_id": "PAT-00000000"},
    "createClinicalOrder": {
        "encounter_id": "ENC-00000000",
        "order_type": "lab",
        "details": {"test": "CBC"},
    },
    "updateTaskStatus": {"task_id": "TSK-00000000", "status": "pending"},
    "updateEncounter": {"encounter_id": "ENC-00000000", "notes": "test"},
    "updatePatientRecord": {"patient_id": "PAT-00000000", "allergies": ["test"]},
    "registerPatient": {"first_name": "Test", "last_name": "Patient"},
    "applyProtocol": {"encounter_id": "ENC-00000000", "protocol_name": "sepsis_bundle"},
    "processDischarge": {"encounter_id": "ENC-00000000", "diagnosis": "test"},
    "processTransfer": {
        "encounter_id": "ENC-00000000",
        "destination_facility": "General Hospital",
        "reason": "test",
    },
}


def check_schema_handler_contracts() -> list[str]:
    """For each tool in mcp-tools.json, call the handler and verify no crash."""
    from healthcraft.mcp.server import TOOL_NAME_MAP, create_server
    from healthcraft.world.seed import WorldSeeder

    failures: list[str] = []
    schema_tools = _load_tool_names()
    handler_tools = set(TOOL_NAME_MAP.keys())

    # Check coverage: every schema tool has a handler
    for tool in sorted(schema_tools - handler_tools):
        failures.append(f"Schema tool '{tool}' has no handler in TOOL_NAME_MAP")

    for tool in sorted(handler_tools - schema_tools):
        failures.append(f"Handler tool '{tool}' missing from mcp-tools.json schema")

    # Seed a world and try dispatching each tool
    seeder = WorldSeeder(seed=42)
    world = seeder.seed_world(WORLD_CONFIG)
    server = create_server(world)

    for tool_name in sorted(schema_tools & handler_tools):
        params = _MINIMAL_INPUTS.get(tool_name, {})
        try:
            result = server.call_tool(tool_name, params)
        except Exception as e:
            failures.append(f"Tool '{tool_name}' raised exception: {e}")
            continue

        status = result.get("status")
        if status not in ("ok", "error"):
            failures.append(f"Tool '{tool_name}' returned unexpected status: {status}")
        # "error" is acceptable (e.g. entity not found) — we just need no crash.
        # "internal_error" means the handler itself broke.
        if result.get("code") == "internal_error":
            failures.append(f"Tool '{tool_name}' internal error: {result.get('message', '')}")

    return failures


# ---------------------------------------------------------------------------
# Check 2: Evaluator Smoke Test
# ---------------------------------------------------------------------------


def check_evaluator_smoke() -> list[str]:
    """Verify that the evaluator correctly distinguishes success from failure."""
    from healthcraft.tasks.evaluator import _verify_world_state
    from healthcraft.tasks.rubrics import Criterion, VerificationMethod
    from healthcraft.world.state import WorldState

    failures: list[str] = []
    ws = WorldState(start_time=datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc))

    # Add one successful and one failed call
    ws.record_audit(tool_name="getPatientHistory", params={}, result_summary="ok")
    ws.record_audit(tool_name="createClinicalOrder", params={}, result_summary="error")

    positive_ok = Criterion(
        id="SMOKE-P1",
        assertion="test",
        dimension="clinical_completeness",
        verification=VerificationMethod.WORLD_STATE,
        check="audit_log contains call to getPatientHistory",
    )
    positive_fail = Criterion(
        id="SMOKE-P2",
        assertion="test",
        dimension="clinical_completeness",
        verification=VerificationMethod.WORLD_STATE,
        check="audit_log contains call to createClinicalOrder",
    )

    r1 = _verify_world_state(positive_ok, (), ws)
    if not r1.satisfied:
        failures.append("Successful call should satisfy positive criterion")

    r2 = _verify_world_state(positive_fail, (), ws)
    if r2.satisfied:
        failures.append("Failed call should NOT satisfy positive criterion")

    return failures


# ---------------------------------------------------------------------------
# Check 3: Criteria-Tool Existence Check
# ---------------------------------------------------------------------------


def check_criteria_tool_existence() -> list[str]:
    """Verify that every world_state criterion references an existing tool."""
    import re

    from healthcraft.mcp.server import TOOL_NAME_MAP
    from healthcraft.tasks.loader import load_tasks

    failures: list[str] = []
    valid_tools = {name.lower() for name in TOOL_NAME_MAP}
    tasks = load_tasks(TASK_DIR)

    for task in tasks:
        for raw_criterion in task.criteria:
            if raw_criterion.get("verification") != "world_state":
                continue
            check = raw_criterion.get("check", "")
            if not check:
                continue

            # Extract tool name from check string
            check_lower = check.lower()
            # Match "contains call to <tool>" or "not contain call to <tool>"
            # Require "call to" — bare "contains" without "call to" is ambiguous
            match = re.search(
                r"(?:contains\s+call\s+to|not\s+contain\s+call\s+to)\s+(\S+)",
                check_lower,
            )
            if match:
                tool_ref = match.group(1)
                if tool_ref not in valid_tools:
                    failures.append(
                        f"{task.id}/{raw_criterion['id']}: "
                        f"check references tool '{tool_ref}' not in TOOL_NAME_MAP"
                    )

    return failures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    checks = [
        ("Schema-Handler Contracts", check_schema_handler_contracts),
        ("Evaluator Smoke", check_evaluator_smoke),
        ("Criteria-Tool Existence", check_criteria_tool_existence),
    ]

    total_failures = 0
    for name, check_fn in checks:
        print(f"\n{'=' * 60}")
        print(f"  {name}")
        print(f"{'=' * 60}")
        failures = check_fn()
        if failures:
            for f in failures:
                print(f"  FAIL: {f}")
            total_failures += len(failures)
        else:
            print("  PASS")

    print(f"\n{'=' * 60}")
    if total_failures:
        print(f"  PREFLIGHT FAILED: {total_failures} issue(s)")
        return 1
    else:
        print("  PREFLIGHT PASSED: all checks green")
        return 0


if __name__ == "__main__":
    sys.exit(main())
