"""Schema <-> handler contract tests.

Guards three invariants between configs/mcp-tools.json and the Python handler
layer:

  1. Coverage:  every tool in the MCP schema has a TOOL_NAME_MAP entry, and
                every TOOL_NAME_MAP entry appears in the schema. Either-direction
                drift would let agents call tools that the evaluator can never
                grade against, or hide tools from agents.

  2. Required-key alignment (bidirectional):  for each tool, the union of
                schema.required is identical to the handler's set of `_require()`
                arguments. A handler that demands a key the schema does not
                advertise will always 422; a schema that lists a key the
                handler ignores hides preconditions from the agent.

  3. Enum dispatch:  every value declared in a schema-side enum is accepted by
                its handler (no `internal_error` on a documented input). This
                is the same property as preflight Check 5 but enforced as a
                test so a regression breaks CI immediately.

Why the contract matters: the V7 -> V8 transition unearthed bugs where the
handler quietly diverged from the schema (e.g. an enum value the handler
rejected with KeyError -> 500). Pilots cost real money to surface this; the
test surfaces it in seconds.
"""

from __future__ import annotations

import ast
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from healthcraft.mcp.server import TOOL_NAME_MAP, create_server
from healthcraft.mcp.tools import mutate_tools, workflow_tools
from healthcraft.world.state import WorldState

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_JSON = REPO_ROOT / "configs" / "mcp-tools.json"

# Minimal valid params per camelCase tool name. Mirrors scripts/preflight.py
# but kept independent so a divergence in either is caught here too.
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


@pytest.fixture(scope="module")
def schema() -> dict:
    """Parsed configs/mcp-tools.json."""
    return json.loads(TOOLS_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schema_tool_names(schema: dict) -> set[str]:
    """All camelCase tool names declared in the MCP schema."""
    return {tool["name"] for tool in schema["tools"]}


# ---------------------------------------------------------------------------
# Invariant 1: Coverage (bidirectional)
# ---------------------------------------------------------------------------


def test_every_schema_tool_has_handler(schema_tool_names: set[str]) -> None:
    """A schema tool with no handler is dead surface area for the agent."""
    handler_tools = set(TOOL_NAME_MAP.keys())
    missing = sorted(schema_tool_names - handler_tools)
    assert not missing, (
        f"Schema declares {len(missing)} tool(s) with no handler: {missing}. "
        f"Either add a handler in mcp/tools/ + register it in TOOL_NAME_MAP, "
        f"or remove from configs/mcp-tools.json."
    )


def test_every_handler_appears_in_schema(schema_tool_names: set[str]) -> None:
    """A handler not in the schema is invisible to MCP clients."""
    handler_tools = set(TOOL_NAME_MAP.keys())
    extra = sorted(handler_tools - schema_tool_names)
    assert not extra, (
        f"TOOL_NAME_MAP has {len(extra)} entry(ies) absent from schema: "
        f"{extra}. Add them to configs/mcp-tools.json or drop the handler."
    )


def test_minimal_inputs_cover_schema(schema_tool_names: set[str]) -> None:
    """Self-test: every schema tool has a probe input in this module."""
    missing = sorted(schema_tool_names - set(_MINIMAL_INPUTS.keys()))
    assert not missing, (
        f"_MINIMAL_INPUTS is missing probes for: {missing}. "
        f"Add a minimal valid params dict for each new tool."
    )


# ---------------------------------------------------------------------------
# Invariant 2: Required-key alignment (bidirectional)
# ---------------------------------------------------------------------------


# Map from camelCase tool name -> handler module + function name.
# Only tools that go through `_require()` need an entry. Read-only tools that
# treat all params as optional are exempt.
_HANDLER_REQUIRE_SOURCES: dict[str, tuple[object, str]] = {
    "createClinicalOrder": (mutate_tools, "create_clinical_order"),
    "updateTaskStatus": (mutate_tools, "update_task_status"),
    "updateEncounter": (mutate_tools, "update_encounter"),
    "updatePatientRecord": (mutate_tools, "update_patient_record"),
    "registerPatient": (mutate_tools, "register_patient"),
    "applyProtocol": (mutate_tools, "apply_protocol"),
}


def _extract_require_keys(handler_module: object, function_name: str) -> set[str]:
    """Static-parse the handler source for `_require(params, "a", "b", ...)`.

    Returns the set of required keys. Static parsing keeps the test independent
    of runtime control flow (e.g. branches that call `_require` conditionally).
    """
    source = Path(handler_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != function_name:
            continue
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Name)
                and sub.func.id == "_require"
            ):
                # _require(params, "a", "b", ...) -- skip first positional.
                for arg in sub.args[1:]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        keys.add(arg.value)
        break
    return keys


@pytest.mark.parametrize("tool_name", sorted(_HANDLER_REQUIRE_SOURCES.keys()))
def test_required_keys_match_schema(tool_name: str, schema: dict) -> None:
    """Schema.required must equal handler `_require()` keys.

    Either-direction drift is a contract bug:
      * schema lists a key the handler ignores -> hidden precondition
      * handler demands a key the schema omits -> agent guesses, gets 422
    """
    tool_schema = next(t for t in schema["tools"] if t["name"] == tool_name)
    schema_required = set(tool_schema.get("parameters", {}).get("required", []))

    module, fn_name = _HANDLER_REQUIRE_SOURCES[tool_name]
    handler_required = _extract_require_keys(module, fn_name)

    assert schema_required == handler_required, (
        f"{tool_name}: schema.required={sorted(schema_required)} != "
        f"handler _require keys={sorted(handler_required)}. "
        f"These must match exactly so agents see the same preconditions "
        f"the handler enforces."
    )


# ---------------------------------------------------------------------------
# Invariant 3: Enum dispatch (no internal_error on documented input)
# ---------------------------------------------------------------------------


def _seeded_world() -> WorldState:
    """Fresh empty world. Seeded world is unnecessary -- we accept `error`
    statuses (entity-not-found is fine); we only fail on `internal_error`.
    """
    return WorldState(start_time=datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc))


@pytest.mark.parametrize("tool_name", sorted(_MINIMAL_INPUTS.keys()))
def test_minimal_input_does_not_internal_error(tool_name: str) -> None:
    """Every documented tool dispatches without an unhandled exception."""
    server = create_server(_seeded_world())
    result = server.call_tool(tool_name, _MINIMAL_INPUTS[tool_name])

    assert result.get("status") in ("ok", "error"), (
        f"{tool_name}: unexpected status {result.get('status')!r}"
    )
    assert result.get("code") != "internal_error", (
        f"{tool_name}: handler raised an unhandled exception "
        f"(code=internal_error, message={result.get('message', '')!r}). "
        f"Documented inputs must dispatch cleanly even if they return "
        f"`error` for missing entities."
    )


# ---------------------------------------------------------------------------
# Invariant 3b: Enum values dispatch (subset of preflight Check 5, in test form)
# ---------------------------------------------------------------------------


def test_order_type_enum_matches_handler(schema: dict) -> None:
    """createClinicalOrder.order_type schema enum subset of handler enum."""
    tool_schema = next(t for t in schema["tools"] if t["name"] == "createClinicalOrder")
    schema_enum = set(tool_schema["parameters"]["properties"].get("order_type", {}).get("enum", []))
    handler_enum = set(mutate_tools._VALID_ORDER_TYPES)
    extra = schema_enum - handler_enum
    assert not extra, (
        f"createClinicalOrder.order_type schema enum has values not in handler "
        f"_VALID_ORDER_TYPES: {sorted(extra)}. Documented values that the "
        f"handler rejects will always 422."
    )


def test_task_status_enum_matches_handler(schema: dict) -> None:
    """updateTaskStatus.status schema enum subset of handler enum."""
    tool_schema = next(t for t in schema["tools"] if t["name"] == "updateTaskStatus")
    schema_enum = set(tool_schema["parameters"]["properties"].get("status", {}).get("enum", []))
    handler_enum = set(mutate_tools._VALID_TASK_STATUSES)
    extra = schema_enum - handler_enum
    assert not extra, (
        f"updateTaskStatus.status schema enum has values not in handler "
        f"_VALID_TASK_STATUSES: {sorted(extra)}."
    )


def test_transport_mode_enum_matches_handler(schema: dict) -> None:
    """processTransfer.transport_mode schema enum subset of handler enum.

    Handler treats 'ground' as alias for 'ground_als', so it's accepted.
    """
    tool_schema = next(t for t in schema["tools"] if t["name"] == "processTransfer")
    schema_enum = set(
        tool_schema["parameters"]["properties"].get("transport_mode", {}).get("enum", [])
    )
    handler_enum = set(workflow_tools._VALID_TRANSPORT_MODES) | {"ground"}
    extra = schema_enum - handler_enum
    assert not extra, (
        f"processTransfer.transport_mode schema enum has values not accepted "
        f"by handler: {sorted(extra)}."
    )


# ---------------------------------------------------------------------------
# Self-test: id-pattern probes use the schema-declared formats
# ---------------------------------------------------------------------------


def test_minimal_input_id_patterns_satisfy_schema(schema: dict) -> None:
    """`_MINIMAL_INPUTS` IDs must match the schema's regex patterns.

    Catches drift where the schema tightens an ID format but the test probes
    still use the old form. Patterns we exercise: PAT-, ENC-, MRN-, etc.
    """
    pattern_by_param: dict[tuple[str, str], str] = {}
    for tool in schema["tools"]:
        props = tool.get("parameters", {}).get("properties", {})
        for param_name, prop in props.items():
            pat = prop.get("pattern")
            if pat:
                pattern_by_param[(tool["name"], param_name)] = pat

    failures: list[str] = []
    for tool_name, params in _MINIMAL_INPUTS.items():
        for key, value in params.items():
            pat = pattern_by_param.get((tool_name, key))
            if pat and isinstance(value, str):
                if not re.match(pat, value):
                    failures.append(f"{tool_name}.{key}={value!r} violates {pat}")

    assert not failures, "Probe inputs violate schema patterns:\n  " + "\n  ".join(failures)
