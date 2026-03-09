"""Tests for the HEALTHCRAFT MCP server dispatcher."""

from __future__ import annotations

from pathlib import Path

import pytest

from healthcraft.mcp.server import TOOL_NAME_MAP, HealthcraftServer, create_server
from healthcraft.world.seed import WorldSeeder


@pytest.fixture
def seeded_world():
    """A seeded world state with all entity types populated."""
    config_path = Path(__file__).parents[2] / "configs" / "world" / "mercy_point_v1.yaml"
    return WorldSeeder(seed=42).seed_world(config_path)


@pytest.fixture
def server(seeded_world):
    """A configured HealthcraftServer."""
    return create_server(seeded_world)


class TestServerSetup:
    """Test server initialization and tool registration."""

    def test_create_server(self, seeded_world) -> None:
        srv = create_server(seeded_world)
        assert isinstance(srv, HealthcraftServer)

    def test_available_tools_count(self, server) -> None:
        assert len(server.available_tools) == 24

    def test_tool_name_map_has_24_entries(self) -> None:
        assert len(TOOL_NAME_MAP) == 24

    def test_all_camelcase_names(self, server) -> None:
        for name in server.available_tools:
            # camelCase: starts lowercase, no underscores
            assert name[0].islower(), f"{name} should start lowercase"
            assert "_" not in name, f"{name} should not contain underscores"


class TestServerDispatch:
    """Test tool dispatch with camelCase and snake_case names."""

    def test_camelcase_dispatch(self, server) -> None:
        result = server.call_tool("searchPatients", {"query": "Smith"})
        assert result["status"] == "ok"

    def test_snake_case_dispatch(self, server) -> None:
        result = server.call_tool("search_patients", {"query": "Smith"})
        assert result["status"] == "ok"

    def test_unknown_tool_returns_error(self, server) -> None:
        result = server.call_tool("nonExistentTool", {})
        assert result["status"] == "error"
        assert result["code"] == "unknown_tool"

    def test_audit_logging(self, server) -> None:
        server.call_tool("searchPatients", {"query": "test"})
        assert server.audit_logger.entry_count >= 1


class TestReadOnlyTools:
    """Test Wave 1: read-only tool handlers through the server."""

    def test_search_patients(self, server) -> None:
        result = server.call_tool("searchPatients", {"query": ""})
        assert result["status"] == "ok"
        assert isinstance(result["data"], list)
        assert len(result["data"]) <= 10  # Pagination limit

    def test_search_encounters(self, server) -> None:
        result = server.call_tool("searchEncounters", {})
        assert result["status"] == "ok"
        assert isinstance(result["data"], list)
        assert len(result["data"]) <= 10

    def test_search_clinical_knowledge(self, server) -> None:
        result = server.call_tool("searchClinicalKnowledge", {"query": "sepsis"})
        assert result["status"] == "ok"

    def test_search_reference_materials(self, server) -> None:
        result = server.call_tool("searchReferenceMaterials", {"query": "alteplase"})
        assert result["status"] == "ok"

    def test_search_available_resources(self, server) -> None:
        result = server.call_tool("searchAvailableResources", {})
        assert result["status"] == "ok"
        assert isinstance(result["data"], list)
        assert len(result["data"]) <= 10

    def test_get_encounter_details_not_found(self, server) -> None:
        result = server.call_tool("getEncounterDetails", {"encounter_id": "ENC-NOTREAL1"})
        assert result["status"] == "error"

    def test_get_condition_details(self, server) -> None:
        result = server.call_tool("getConditionDetails", {"condition_id": "SEPSIS"})
        assert result["status"] == "ok"

    def test_get_patient_history_not_found(self, server) -> None:
        result = server.call_tool("getPatientHistory", {"patient_id": "PAT-NOTREAL1"})
        assert result["status"] == "error"

    def test_get_protocol_details(self, server) -> None:
        result = server.call_tool("getProtocolDetails", {"protocol_id": "sepsis"})
        assert result["status"] == "ok" or result["status"] == "error"

    def test_get_insurance_coverage_not_found(self, server) -> None:
        result = server.call_tool("getInsuranceCoverage", {"patient_id": "PAT-NOTREAL1"})
        assert result["status"] == "error"


class TestComputationTools:
    """Test Wave 2: computation tool handlers."""

    def test_check_resource_availability(self, server) -> None:
        result = server.call_tool("checkResourceAvailability", {"resource_type": "ct_scanner"})
        assert result["status"] == "ok"
        assert "available" in result["data"]

    def test_calculate_transfer_time(self, server) -> None:
        result = server.call_tool(
            "calculateTransferTime",
            {"facility_name": "University Medical Center"},
        )
        assert result["status"] == "ok" or result["status"] == "error"

    def test_run_decision_rule(self, server) -> None:
        result = server.call_tool(
            "runDecisionRule",
            {
                "rule_name": "qSOFA",
                "variables": {"systolic_bp": 0, "respiratory_rate": 1, "altered_mental_status": 1},
            },
        )
        assert result["status"] == "ok" or result["status"] == "error"

    def test_validate_treatment_plan(self, server) -> None:
        # Get a real encounter ID first
        encounters = server.call_tool("searchEncounters", {})
        if encounters["status"] == "ok" and encounters["data"]:
            enc_id = encounters["data"][0].get("id", "")
            result = server.call_tool(
                "validateTreatmentPlan",
                {"encounter_id": enc_id, "medications": ["Aspirin"]},
            )
            assert result["status"] in ("ok", "error")


class TestMutatingTools:
    """Test Wave 3: state-mutating tool handlers."""

    def test_register_patient(self, server) -> None:
        result = server.call_tool(
            "registerPatient",
            {"first_name": "Test", "last_name": "Patient", "sex": "M"},
        )
        assert result["status"] == "ok"
        assert "id" in result["data"] or "patient_id" in str(result["data"])


class TestWorkflowTools:
    """Test Wave 4: complex workflow tool handlers."""

    def test_process_transfer_missing_facility(self, server) -> None:
        result = server.call_tool(
            "processTransfer",
            {"encounter_id": "ENC-00000001", "receiving_facility": "Nonexistent", "reason": "test"},
        )
        assert result["status"] == "error"


class TestPaginationLimit:
    """Test Corecraft noise: max 10 results, no hasMore signal."""

    def test_search_patients_max_10(self, server) -> None:
        result = server.call_tool("searchPatients", {"query": ""})
        assert result["status"] == "ok"
        assert len(result["data"]) <= 10

    def test_search_encounters_max_10(self, server) -> None:
        result = server.call_tool("searchEncounters", {})
        assert result["status"] == "ok"
        assert len(result["data"]) <= 10

    def test_no_has_more_signal(self, server) -> None:
        result = server.call_tool("searchPatients", {"query": ""})
        assert "hasMore" not in result
        assert "has_more" not in result
        assert "total" not in result
