"""FastMCP server for the HEALTHCRAFT simulation.

Exposes 24 tools for interacting with the Mercy Point ED simulation
via the Model Context Protocol.
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
from healthcraft.mcp.validation import ValidationError, validate_encounter_id, validate_patient_id
from healthcraft.world.state import WorldState

# --- Tool definitions ---

TOOL_DEFINITIONS: list[dict[str, str]] = [
    # Patient management
    {"name": "get_patient", "description": "Retrieve patient demographics and history"},
    {"name": "search_patients", "description": "Search patients by name, MRN, or chief complaint"},
    {"name": "update_patient", "description": "Update patient information"},
    # Encounter management
    {"name": "get_encounter", "description": "Retrieve encounter details"},
    {"name": "create_encounter", "description": "Create a new ED encounter"},
    {"name": "update_encounter", "description": "Update encounter status or disposition"},
    # Clinical assessment
    {"name": "record_vitals", "description": "Record a set of vital signs"},
    {"name": "get_vitals_history", "description": "Retrieve vital signs history for an encounter"},
    {"name": "perform_assessment", "description": "Document clinical assessment findings"},
    # Orders
    {"name": "order_lab", "description": "Place a laboratory order"},
    {"name": "order_imaging", "description": "Place an imaging study order"},
    {"name": "order_medication", "description": "Place a medication order"},
    {"name": "get_lab_results", "description": "Retrieve laboratory results"},
    {"name": "get_imaging_results", "description": "Retrieve imaging study results"},
    # Procedures
    {"name": "perform_procedure", "description": "Document a procedure performed"},
    {"name": "administer_medication", "description": "Record medication administration"},
    # Documentation
    {"name": "write_note", "description": "Write a clinical note"},
    {"name": "get_notes", "description": "Retrieve clinical notes for an encounter"},
    # Disposition
    {"name": "set_disposition", "description": "Set encounter disposition"},
    {"name": "request_consult", "description": "Request a specialist consultation"},
    # ED Operations
    {"name": "get_bed_board", "description": "View current ED bed status"},
    {"name": "assign_bed", "description": "Assign a patient to a bed"},
    {"name": "get_department_census", "description": "Get current ED census and metrics"},
    # Clinical decision support
    {"name": "lookup_clinical_knowledge", "description": "Query clinical knowledge base"},
]


def _make_error_response(message: str) -> dict[str, Any]:
    """Create a structured error response.

    Args:
        message: Error description.

    Returns:
        Dict with error details.
    """
    return {"status": "error", "error": message}


def _make_success_response(data: Any) -> dict[str, Any]:
    """Create a structured success response.

    Args:
        data: Response payload.

    Returns:
        Dict with success status and data.
    """
    return {"status": "ok", "data": data}


class HealthcraftServer:
    """HEALTHCRAFT MCP server wrapping the world state.

    Provides tool dispatch, input validation, and audit logging
    as middleware around the world state.
    """

    def __init__(self, world_state: WorldState) -> None:
        self._world = world_state
        self._audit = AuditLogger()
        self._handlers: dict[str, Any] = {
            "get_patient": self._handle_get_patient,
            "search_patients": self._handle_search_patients,
            "get_encounter": self._handle_get_encounter,
            "get_vitals_history": self._handle_get_vitals_history,
            "get_bed_board": self._handle_get_bed_board,
            "get_department_census": self._handle_get_department_census,
            "lookup_clinical_knowledge": self._handle_lookup_clinical_knowledge,
        }

    def call_tool(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a tool call with validation and audit logging.

        Args:
            tool_name: Name of the tool to invoke.
            params: Tool parameters.

        Returns:
            Structured response dict.
        """
        handler = self._handlers.get(tool_name)
        if handler is None:
            result = _make_error_response(f"Unknown tool: {tool_name}")
            self._audit.log_tool_call(tool_name, params, result, self._world.timestamp)
            return result

        try:
            result = handler(params)
            self._audit.log_tool_call(tool_name, params, result, self._world.timestamp)
            self._world.record_audit(
                tool_name=tool_name,
                params=params,
                result_summary=result.get("status", "unknown"),
            )
            return result
        except ValidationError as e:
            result = _make_error_response(f"Validation error: {e}")
            self._audit.log_tool_call(tool_name, params, result, self._world.timestamp)
            return result
        except Exception as e:
            result = _make_error_response(f"Internal error: {e}")
            self._audit.log_tool_call(tool_name, params, result, self._world.timestamp)
            return result

    @property
    def audit_logger(self) -> AuditLogger:
        """The server's audit logger."""
        return self._audit

    # --- Tool handlers ---

    def _handle_get_patient(self, params: dict[str, Any]) -> dict[str, Any]:
        patient_id = params.get("patient_id", "")
        if not validate_patient_id(patient_id):
            raise ValidationError(f"Invalid patient_id: {patient_id}")
        patient = self._world.get_entity("patient", patient_id)
        if patient is None:
            return _make_error_response(f"Patient not found: {patient_id}")
        # Return patient as dict (works for both dataclass and dict entities)
        if hasattr(patient, "__dataclass_fields__"):
            from dataclasses import asdict

            return _make_success_response(asdict(patient))
        return _make_success_response(patient)

    def _handle_search_patients(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query", "").lower()
        patients = self._world.list_entities("patient")
        results = []
        for pid, patient in patients.items():
            # Search by name or MRN
            searchable = ""
            if hasattr(patient, "first_name"):
                searchable = f"{patient.first_name} {patient.last_name} {patient.mrn}".lower()
            elif isinstance(patient, dict):
                searchable = (
                    f"{patient.get('first_name', '')} "
                    f"{patient.get('last_name', '')} "
                    f"{patient.get('mrn', '')}"
                ).lower()
            if query in searchable:
                results.append({"id": pid})
        return _make_success_response(results)

    def _handle_get_encounter(self, params: dict[str, Any]) -> dict[str, Any]:
        encounter_id = params.get("encounter_id", "")
        if not validate_encounter_id(encounter_id):
            raise ValidationError(f"Invalid encounter_id: {encounter_id}")
        encounter = self._world.get_entity("encounter", encounter_id)
        if encounter is None:
            return _make_error_response(f"Encounter not found: {encounter_id}")
        if hasattr(encounter, "__dataclass_fields__"):
            from dataclasses import asdict

            return _make_success_response(asdict(encounter))
        return _make_success_response(encounter)

    def _handle_get_vitals_history(self, params: dict[str, Any]) -> dict[str, Any]:
        encounter_id = params.get("encounter_id", "")
        if not validate_encounter_id(encounter_id):
            raise ValidationError(f"Invalid encounter_id: {encounter_id}")
        encounter = self._world.get_entity("encounter", encounter_id)
        if encounter is None:
            return _make_error_response(f"Encounter not found: {encounter_id}")
        vitals = getattr(encounter, "vitals", ())
        if hasattr(vitals, "__iter__"):
            from dataclasses import asdict

            vitals_list = [asdict(v) if hasattr(v, "__dataclass_fields__") else v for v in vitals]
        else:
            vitals_list = []
        return _make_success_response(vitals_list)

    def _handle_get_bed_board(self, params: dict[str, Any]) -> dict[str, Any]:
        locations = self._world.list_entities("location")
        return _make_success_response(list(locations.values()))

    def _handle_get_department_census(self, params: dict[str, Any]) -> dict[str, Any]:
        patients = self._world.list_entities("patient")
        encounters = self._world.list_entities("encounter")
        locations = self._world.list_entities("location")
        return _make_success_response(
            {
                "total_patients": len(patients),
                "active_encounters": len(encounters),
                "total_beds": len(locations),
                "timestamp": self._world.timestamp.isoformat(),
            }
        )

    def _handle_lookup_clinical_knowledge(self, params: dict[str, Any]) -> dict[str, Any]:
        condition_id = params.get("condition_id", "")
        knowledge = self._world.get_entity("clinical_knowledge", f"CK-{condition_id}")
        if knowledge is None:
            # Try without prefix
            knowledge = self._world.get_entity("clinical_knowledge", condition_id)
        if knowledge is None:
            return _make_error_response(f"Condition not found: {condition_id}")
        if hasattr(knowledge, "__dataclass_fields__"):
            from dataclasses import asdict

            return _make_success_response(asdict(knowledge))
        return _make_success_response(knowledge)


def create_server(world_state: WorldState) -> HealthcraftServer:
    """Factory function to create a HEALTHCRAFT MCP server.

    Args:
        world_state: The WorldState instance to expose via tools.

    Returns:
        A configured HealthcraftServer.
    """
    return HealthcraftServer(world_state)
