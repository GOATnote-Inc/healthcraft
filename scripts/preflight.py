"""Pre-flight validation for HEALTHCRAFT evaluations.

Runs seven checks in <30 seconds:
  1. Schema-Handler Contract Tests — every tool in mcp-tools.json dispatches ok
  2. Evaluator Smoke Test — success/failure distinction in world_state verification
  3. Criteria-Tool Existence Check — world_state check targets exist in tool registry
  4. Parameter Qualifier Coverage — qualifiers in check strings are parseable
  5. Enum Exhaustiveness — schema enums are subsets of handler accepted values
  6. Protocol Name Matching — protocol names from schema match seeded world
  7. Task Satisfiability — every world_state criterion is reachable through the
     same compound-AND/OR split + qualifier parse the runtime uses

Usage:
    python scripts/preflight.py
    make preflight
"""

from __future__ import annotations

import json
import re
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
# Check 4: Parameter Qualifier Coverage
# ---------------------------------------------------------------------------


def check_parameter_qualifier_coverage() -> list[str]:
    """Verify that check strings with qualifiers are parseable by the evaluator."""
    from healthcraft.tasks.evaluator import _extract_tool_and_params
    from healthcraft.tasks.loader import load_tasks

    failures: list[str] = []
    tasks = load_tasks(TASK_DIR)

    for task in tasks:
        for raw_criterion in task.criteria:
            if raw_criterion.get("verification") != "world_state":
                continue
            check = raw_criterion.get("check", "")
            if not check:
                continue

            # Split on AND/OR and check each clause
            clauses = re.split(r"\s+(?:AND|OR)\s+", check, flags=re.IGNORECASE)
            for clause in clauses:
                clause_lower = clause.lower().strip()
                if "contains" not in clause_lower:
                    continue
                keyword = "not contain" if "not contain" in clause_lower else "contains"
                tool_name, params = _extract_tool_and_params(clause_lower, keyword)
                if not tool_name:
                    failures.append(
                        f"{task.id}/{raw_criterion['id']}: "
                        f"cannot extract tool name from clause: '{clause.strip()}'"
                    )

    return failures


# ---------------------------------------------------------------------------
# Check 5: Enum Exhaustiveness
# ---------------------------------------------------------------------------


def check_enum_exhaustiveness() -> list[str]:
    """Verify that schema enum values are accepted by their handlers."""
    failures: list[str] = []

    with open(TOOLS_JSON) as f:
        data = json.load(f)

    # Known handler accepted values for enum parameters
    from healthcraft.mcp.tools.mutate_tools import _VALID_ORDER_TYPES, _VALID_TASK_STATUSES
    from healthcraft.mcp.tools.workflow_tools import _VALID_TRANSPORT_MODES

    handler_enums: dict[str, dict[str, frozenset[str]]] = {
        "createClinicalOrder": {"order_type": _VALID_ORDER_TYPES},
        "updateTaskStatus": {"status": _VALID_TASK_STATUSES},
        "processTransfer": {"transport_mode": _VALID_TRANSPORT_MODES | frozenset({"ground"})},
    }

    for tool_schema in data["tools"]:
        tool_name = tool_schema["name"]
        if tool_name not in handler_enums:
            continue
        properties = tool_schema.get("parameters", {}).get("properties", {})
        for param_name, handler_accepted in handler_enums[tool_name].items():
            prop = properties.get(param_name, {})
            schema_enum = prop.get("enum")
            if not schema_enum:
                continue
            for val in schema_enum:
                # "ground" is mapped to "ground_als" at runtime, so it's accepted
                if val not in handler_accepted and val != "ground":
                    failures.append(
                        f"{tool_name}.{param_name}: schema enum value '{val}' "
                        f"not in handler accepted values {sorted(handler_accepted)}"
                    )

    return failures


# ---------------------------------------------------------------------------
# Check 6: Protocol Name Matching
# ---------------------------------------------------------------------------


def check_protocol_name_matching() -> list[str]:
    """Verify that schema protocol names match protocols in a seeded world."""
    from healthcraft.mcp.tools.mutate_tools import _normalize_protocol_name
    from healthcraft.world.seed import WorldSeeder

    failures: list[str] = []

    # Load protocol names from schema
    with open(TOOLS_JSON) as f:
        data = json.load(f)
    protocol_enums: list[str] = []
    for tool_schema in data["tools"]:
        if tool_schema["name"] == "applyProtocol":
            props = tool_schema.get("parameters", {}).get("properties", {})
            protocol_enums = props.get("protocol_name", {}).get("enum", [])
            break

    if not protocol_enums:
        return ["applyProtocol schema has no protocol_name enum"]

    # Seed a world and get protocol names
    seeder = WorldSeeder(seed=42)
    world = seeder.seed_world(WORLD_CONFIG)
    protocols = world.list_entities("protocol")

    if not protocols:
        failures.append("No protocols in seeded world — cannot verify name matching")
        return failures

    world_protocol_names = []
    for _pid, proto in protocols.items():
        name = proto.name if hasattr(proto, "name") else proto.get("name", "")
        if name:
            world_protocol_names.append(name)

    # For each schema enum value, check if it would match at least one world protocol.
    # Uses the same matching logic as apply_protocol: exact, substring, or
    # all search words present in the protocol name.
    for enum_val in protocol_enums:
        normalized_enum = _normalize_protocol_name(enum_val)
        search_words = set(normalized_enum.split())
        matched = any(
            normalized_enum in _normalize_protocol_name(wname)
            or _normalize_protocol_name(wname) == normalized_enum
            or search_words <= set(_normalize_protocol_name(wname).split())
            for wname in world_protocol_names
        )
        if not matched:
            failures.append(
                f"Schema protocol '{enum_val}' (normalized: '{normalized_enum}') "
                f"does not match any world protocol: {world_protocol_names[:5]}..."
            )

    return failures


# ---------------------------------------------------------------------------
# Check 7: Task Satisfiability (runtime-aligned)
# ---------------------------------------------------------------------------


def check_task_satisfiability() -> list[str]:
    """Every world_state criterion is reachable through the runtime parser.

    Unlike Check 3 (which uses a single regex), this walks each criterion's
    check string through ``_expand_tool_alternatives`` + ``_split_compound``
    exactly like ``_verify_world_state`` does, then validates each clause
    resolves to a real tool AND any enum-bound qualifier matches its
    handler's enum.

    A check like ``contains call to X AND contains call to Y`` would have
    Check 3 only inspect the first clause; Check 7 inspects both.
    """
    from healthcraft.mcp.server import TOOL_NAME_MAP
    from healthcraft.mcp.tools.mutate_tools import (
        _VALID_ORDER_TYPES,
        _VALID_TASK_STATUSES,
    )
    from healthcraft.mcp.tools.workflow_tools import _VALID_TRANSPORT_MODES
    from healthcraft.tasks.evaluator import (
        _expand_tool_alternatives,
        _extract_tool_and_params,
        _parse_criteria,
        _split_compound,
    )
    from healthcraft.tasks.loader import load_tasks
    from healthcraft.tasks.rubrics import VerificationMethod

    valid_tools = {name.lower() for name in TOOL_NAME_MAP}
    qualifier_enums: dict[str, frozenset[str]] = {
        "order_type": frozenset(_VALID_ORDER_TYPES),
        "status": frozenset(_VALID_TASK_STATUSES),
        "transport_mode": frozenset(_VALID_TRANSPORT_MODES) | frozenset({"ground"}),
    }

    failures: list[str] = []
    for task in load_tasks(TASK_DIR):
        for crit in _parse_criteria(task.criteria):
            if crit.verification != VerificationMethod.WORLD_STATE:
                continue
            expanded = _expand_tool_alternatives(crit.check)
            clauses = _split_compound(expanded, "AND")
            if len(clauses) == 1:
                clauses = _split_compound(expanded, "OR")
            for clause in clauses:
                lower = clause.lower()
                if "does not contain" in lower or "not contain" in lower:
                    tool, params = _extract_tool_and_params(lower, "not contain")
                elif "contains" in lower:
                    tool, params = _extract_tool_and_params(lower, "contains")
                else:
                    # Unrecognized clause shape — surface for author review.
                    failures.append(
                        f"{task.id}/{crit.id}: no directive in clause {clause.strip()!r}"
                    )
                    continue
                if not tool:
                    failures.append(
                        f"{task.id}/{crit.id}: tool unparseable in clause {clause.strip()!r}"
                    )
                    continue
                if tool not in valid_tools:
                    failures.append(
                        f"{task.id}/{crit.id}: unknown tool {tool!r} in clause {clause.strip()!r}"
                    )
                    continue
                for key, accepted in qualifier_enums.items():
                    if key in params and params[key] not in accepted:
                        failures.append(
                            f"{task.id}/{crit.id}: qualifier {key}={params[key]!r}"
                            f" not in handler enum {sorted(accepted)}"
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
        ("Parameter Qualifier Coverage", check_parameter_qualifier_coverage),
        ("Enum Exhaustiveness", check_enum_exhaustiveness),
        ("Protocol Name Matching", check_protocol_name_matching),
        ("Task Satisfiability", check_task_satisfiability),
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
