"""FastMCP server for the HEALTHCRAFT simulation.

Exposes 24 tools for interacting with the Mercy Point ED simulation
via the Model Context Protocol. Tool names are camelCase per Corecraft
convention; Python handlers use snake_case internally.
"""

from __future__ import annotations

from typing import Any

try:
    from mcp.server import Server  # noqa: F401
    from mcp.types import Tool  # noqa: F401

    HAS_MCP = True
except ImportError:
    HAS_MCP = False

from healthcraft.mcp.audit import AuditLogger
from healthcraft.mcp.validation import ValidationError
from healthcraft.world.state import WorldState

# --- camelCase -> snake_case handler mapping ---
# This is the single source of truth for tool name translation.
# MCP clients see camelCase names; Python handlers use snake_case.

TOOL_NAME_MAP: dict[str, str] = {
    # Wave 1: Read-only tools
    "searchEncounters": "search_encounters",
    "searchPatients": "search_patients",
    "searchClinicalKnowledge": "search_clinical_knowledge",
    "searchReferenceMaterials": "search_reference_materials",
    "searchAvailableResources": "search_available_resources",
    "getEncounterDetails": "get_encounter_details",
    "getConditionDetails": "get_condition_details",
    "getPatientHistory": "get_patient_history",
    "getProtocolDetails": "get_protocol_details",
    "getTransferStatus": "get_transfer_status",
    "getInsuranceCoverage": "get_insurance_coverage",
    "getReferenceArticle": "get_reference_article",
    # Wave 2: Computation tools
    "checkResourceAvailability": "check_resource_availability",
    "calculateTransferTime": "calculate_transfer_time",
    "runDecisionRule": "run_decision_rule",
    "validateTreatmentPlan": "validate_treatment_plan",
    # Wave 3: State-mutating tools
    "createClinicalOrder": "create_clinical_order",
    "updateTaskStatus": "update_task_status",
    "updateEncounter": "update_encounter",
    "updatePatientRecord": "update_patient_record",
    "registerPatient": "register_patient",
    "applyProtocol": "apply_protocol",
    # Wave 4: Complex workflow tools
    "processDischarge": "process_discharge",
    "processTransfer": "process_transfer",
}

# Reverse map for lookup
_SNAKE_TO_CAMEL: dict[str, str] = {v: k for k, v in TOOL_NAME_MAP.items()}


def _make_error(code: str, message: str) -> dict[str, Any]:
    """Create a structured error response."""
    return {"status": "error", "code": code, "message": message}


def _make_success(data: Any) -> dict[str, Any]:
    """Create a structured success response."""
    return {"status": "ok", "data": data}


class HealthcraftServer:
    """HEALTHCRAFT MCP server wrapping the world state.

    Provides tool dispatch, input validation, and audit logging
    as middleware around the world state. Accepts both camelCase
    and snake_case tool names.
    """

    def __init__(self, world_state: WorldState) -> None:
        self._world = world_state
        self._audit = AuditLogger()
        self._handlers: dict[str, Any] = {}
        self._register_tools()

    def _register_tools(self) -> None:
        """Register all tool handlers from the tool modules."""
        # Wave 1: Read-only
        from healthcraft.mcp.tools.read_tools import (
            get_condition_details,
            get_encounter_details,
            get_insurance_coverage,
            get_patient_history,
            get_protocol_details,
            get_reference_article,
            get_transfer_status,
            search_available_resources,
            search_clinical_knowledge,
            search_encounters,
            search_patients,
            search_reference_materials,
        )

        self._handlers["search_encounters"] = search_encounters
        self._handlers["search_patients"] = search_patients
        self._handlers["search_clinical_knowledge"] = search_clinical_knowledge
        self._handlers["search_reference_materials"] = search_reference_materials
        self._handlers["search_available_resources"] = search_available_resources
        self._handlers["get_encounter_details"] = get_encounter_details
        self._handlers["get_condition_details"] = get_condition_details
        self._handlers["get_patient_history"] = get_patient_history
        self._handlers["get_protocol_details"] = get_protocol_details
        self._handlers["get_transfer_status"] = get_transfer_status
        self._handlers["get_insurance_coverage"] = get_insurance_coverage
        self._handlers["get_reference_article"] = get_reference_article

        # Wave 2: Computation
        from healthcraft.mcp.tools.compute_tools import (
            calculate_transfer_time,
            check_resource_availability,
            run_decision_rule,
            validate_treatment_plan,
        )

        self._handlers["check_resource_availability"] = check_resource_availability
        self._handlers["calculate_transfer_time"] = calculate_transfer_time
        self._handlers["run_decision_rule"] = run_decision_rule
        self._handlers["validate_treatment_plan"] = validate_treatment_plan

        # Wave 3: State-mutating
        from healthcraft.mcp.tools.mutate_tools import (
            apply_protocol,
            create_clinical_order,
            register_patient,
            update_encounter,
            update_patient_record,
            update_task_status,
        )

        self._handlers["create_clinical_order"] = create_clinical_order
        self._handlers["update_task_status"] = update_task_status
        self._handlers["update_encounter"] = update_encounter
        self._handlers["update_patient_record"] = update_patient_record
        self._handlers["register_patient"] = register_patient
        self._handlers["apply_protocol"] = apply_protocol

        # Wave 4: Complex workflows
        from healthcraft.mcp.tools.workflow_tools import (
            process_discharge,
            process_transfer,
        )

        self._handlers["process_discharge"] = process_discharge
        self._handlers["process_transfer"] = process_transfer

    def _resolve_tool_name(self, tool_name: str) -> str | None:
        """Resolve a tool name to its snake_case handler key.

        Accepts both camelCase and snake_case names.
        """
        # Direct snake_case match
        if tool_name in self._handlers:
            return tool_name
        # camelCase -> snake_case via map
        snake = TOOL_NAME_MAP.get(tool_name)
        if snake and snake in self._handlers:
            return snake
        return None

    def call_tool(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a tool call with validation and audit logging.

        Accepts both camelCase (MCP standard) and snake_case tool names.
        """
        handler_key = self._resolve_tool_name(tool_name)
        if handler_key is None:
            result = _make_error("unknown_tool", f"Unknown tool: {tool_name}")
            self._audit.log_tool_call(tool_name, params, result, self._world.timestamp)
            return result

        try:
            result = self._handlers[handler_key](self._world, params)
            self._audit.log_tool_call(tool_name, params, result, self._world.timestamp)
            self._world.record_audit(
                tool_name=tool_name,
                params=params,
                result_summary=result.get("status", "unknown"),
            )
            return result
        except ValidationError as e:
            result = _make_error("validation_error", str(e))
            self._audit.log_tool_call(tool_name, params, result, self._world.timestamp)
            return result
        except Exception as e:
            result = _make_error("internal_error", str(e))
            self._audit.log_tool_call(tool_name, params, result, self._world.timestamp)
            return result

    @property
    def audit_logger(self) -> AuditLogger:
        """The server's audit logger."""
        return self._audit

    @property
    def world_state(self) -> WorldState:
        """The underlying world state."""
        return self._world

    @property
    def available_tools(self) -> list[str]:
        """List of available camelCase tool names."""
        return list(TOOL_NAME_MAP.keys())


def create_server(world_state: WorldState) -> HealthcraftServer:
    """Factory function to create a HEALTHCRAFT MCP server."""
    return HealthcraftServer(world_state)
