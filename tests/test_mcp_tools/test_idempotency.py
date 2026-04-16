"""Idempotency tests for mutating tools.

Tests the HC_IDEMPOTENT_TOOLS flag-gated behavior:

1. create_clinical_order: duplicate idempotency_key returns existing order.
2. update_patient_record: deduplicates allergies and medications.
3. update_task_status: terminal status guard (completed/cancelled).
4. Flag off preserves V8 behavior (fresh UUID, duplicate appends).
5. AuditEntry backward compatibility: V8 JSON loads with new fields defaulting.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from healthcraft.mcp.tools.mutate_tools import (
    create_clinical_order,
    update_patient_record,
    update_task_status,
)
from healthcraft.world.state import AuditEntry, WorldState


@pytest.fixture()
def world() -> WorldState:
    """Create a world state with a patient and encounter for testing."""
    w = WorldState(start_time=datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc))

    # Add a patient
    from healthcraft.entities.base import EntityType
    from healthcraft.entities.patients import Patient

    patient = Patient(
        id="PAT-TEST",
        entity_type=EntityType.PATIENT,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        mrn="MRN-999999",
        first_name="Test",
        last_name="Patient",
        sex="M",
        allergies=("Penicillin",),
        medications=("Lisinopril 10mg",),
    )
    w.put_entity("patient", "PAT-TEST", patient)

    # Add an encounter
    from healthcraft.entities.encounters import Encounter, ESILevel

    encounter = Encounter(
        id="ENC-TEST",
        entity_type=EntityType.ENCOUNTER,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        patient_id="PAT-TEST",
        chief_complaint="Chest pain",
        esi_level=ESILevel.EMERGENT,
    )
    w.put_entity("encounter", "ENC-TEST", encounter)
    return w


@pytest.fixture(autouse=True)
def _clean_env():
    """Ensure HC_IDEMPOTENT_TOOLS is unset before/after each test."""
    old = os.environ.pop("HC_IDEMPOTENT_TOOLS", None)
    yield
    if old is not None:
        os.environ["HC_IDEMPOTENT_TOOLS"] = old
    else:
        os.environ.pop("HC_IDEMPOTENT_TOOLS", None)


# ---------------------------------------------------------------------------
# create_clinical_order idempotency
# ---------------------------------------------------------------------------


class TestCreateOrderIdempotency:
    """Duplicate idempotency_key returns existing order when flag on."""

    def test_duplicate_key_returns_existing(self, world: WorldState) -> None:
        os.environ["HC_IDEMPOTENT_TOOLS"] = "1"
        params = {
            "encounter_id": "ENC-TEST",
            "order_type": "lab",
            "details": {"test": "CBC"},
            "idempotency_key": "idem-001",
        }
        r1 = create_clinical_order(world, params)
        r2 = create_clinical_order(world, params)
        assert r1["status"] == "ok"
        assert r2["status"] == "ok"
        assert r2.get("deduplicated") is True
        assert r1["data"]["id"] == r2["data"]["id"]

    def test_different_key_creates_new(self, world: WorldState) -> None:
        os.environ["HC_IDEMPOTENT_TOOLS"] = "1"
        params_a = {
            "encounter_id": "ENC-TEST",
            "order_type": "lab",
            "details": {"test": "CBC"},
            "idempotency_key": "idem-A",
        }
        params_b = {
            "encounter_id": "ENC-TEST",
            "order_type": "lab",
            "details": {"test": "BMP"},
            "idempotency_key": "idem-B",
        }
        r_a = create_clinical_order(world, params_a)
        r_b = create_clinical_order(world, params_b)
        assert r_a["data"]["id"] != r_b["data"]["id"]

    def test_flag_off_creates_fresh_uuid(self, world: WorldState) -> None:
        # Flag off = V8 behavior: fresh UUID even with same idempotency_key
        params = {
            "encounter_id": "ENC-TEST",
            "order_type": "lab",
            "details": {"test": "CBC"},
            "idempotency_key": "idem-001",
        }
        r1 = create_clinical_order(world, params)
        r2 = create_clinical_order(world, params)
        assert r1["data"]["id"] != r2["data"]["id"]

    def test_no_key_creates_fresh_uuid_even_with_flag(self, world: WorldState) -> None:
        os.environ["HC_IDEMPOTENT_TOOLS"] = "1"
        params = {
            "encounter_id": "ENC-TEST",
            "order_type": "lab",
            "details": {"test": "CBC"},
        }
        r1 = create_clinical_order(world, params)
        r2 = create_clinical_order(world, params)
        assert r1["data"]["id"] != r2["data"]["id"]


# ---------------------------------------------------------------------------
# update_patient_record dedup
# ---------------------------------------------------------------------------


class TestUpdatePatientRecordDedup:
    """Dedup allergies and medications when flag on."""

    def test_dedup_allergies(self, world: WorldState) -> None:
        os.environ["HC_IDEMPOTENT_TOOLS"] = "1"
        params = {"patient_id": "PAT-TEST", "allergies": ["Penicillin", "Sulfa"]}
        r = update_patient_record(world, params)
        assert r["status"] == "ok"
        allergies = r["data"]["allergies"]
        # "Penicillin" was already in the patient; should not be duplicated
        assert allergies.count("Penicillin") == 1
        assert "Sulfa" in allergies

    def test_dedup_medications(self, world: WorldState) -> None:
        os.environ["HC_IDEMPOTENT_TOOLS"] = "1"
        params = {"patient_id": "PAT-TEST", "medications": ["Lisinopril 10mg", "Metformin 500mg"]}
        r = update_patient_record(world, params)
        assert r["status"] == "ok"
        meds = r["data"]["medications"]
        assert meds.count("Lisinopril 10mg") == 1
        assert "Metformin 500mg" in meds

    def test_flag_off_allows_duplicates(self, world: WorldState) -> None:
        # V8 behavior: duplicates are appended
        params = {"patient_id": "PAT-TEST", "allergies": ["Penicillin"]}
        r = update_patient_record(world, params)
        assert r["status"] == "ok"
        allergies = r["data"]["allergies"]
        assert allergies.count("Penicillin") == 2

    def test_dedup_preserves_order(self, world: WorldState) -> None:
        os.environ["HC_IDEMPOTENT_TOOLS"] = "1"
        params = {"patient_id": "PAT-TEST", "allergies": ["Sulfa", "Penicillin", "Latex"]}
        r = update_patient_record(world, params)
        allergies = r["data"]["allergies"]
        # Original "Penicillin" comes first, then Sulfa, Latex
        assert allergies == ("Penicillin", "Sulfa", "Latex")


# ---------------------------------------------------------------------------
# update_task_status terminal guard
# ---------------------------------------------------------------------------


class TestUpdateTaskStatusTerminalGuard:
    """Terminal status guard when flag on."""

    def _create_task(self, world: WorldState, status: str = "pending") -> str:
        """Helper to create a clinical task."""
        from healthcraft.entities.base import EntityType
        from healthcraft.entities.clinical_tasks import ClinicalTask

        task = ClinicalTask(
            id="TSK-TEST",
            entity_type=EntityType.CLINICAL_TASK,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            encounter_id="ENC-TEST",
            task_type="lab_draw",
            status=status,
            priority="routine",
        )
        world.put_entity("clinical_task", "TSK-TEST", task)
        return "TSK-TEST"

    def test_terminal_guard_returns_existing(self, world: WorldState) -> None:
        os.environ["HC_IDEMPOTENT_TOOLS"] = "1"
        self._create_task(world, status="completed")
        r = update_task_status(world, {"task_id": "TSK-TEST", "status": "in_progress"})
        assert r["status"] == "ok"
        assert r.get("deduplicated") is True

    def test_terminal_guard_cancelled(self, world: WorldState) -> None:
        os.environ["HC_IDEMPOTENT_TOOLS"] = "1"
        self._create_task(world, status="cancelled")
        r = update_task_status(world, {"task_id": "TSK-TEST", "status": "pending"})
        assert r.get("deduplicated") is True

    def test_flag_off_allows_status_change_from_terminal(self, world: WorldState) -> None:
        # V8 behavior: no guard
        self._create_task(world, status="completed")
        r = update_task_status(world, {"task_id": "TSK-TEST", "status": "in_progress"})
        assert r["status"] == "ok"
        assert r.get("deduplicated") is None


# ---------------------------------------------------------------------------
# AuditEntry backward compatibility
# ---------------------------------------------------------------------------


class TestAuditEntryBackwardCompat:
    """V8 audit entries load with new fields defaulting."""

    def test_v8_fields_only(self) -> None:
        entry = AuditEntry(
            tool_name="createClinicalOrder",
            timestamp=datetime.now(timezone.utc),
            params={"encounter_id": "ENC-001"},
            result_summary="ok",
        )
        assert entry.idempotency_key == ""
        assert entry.attempt_number == 1
        assert entry.error_code == ""
        assert entry.deduplicated is False

    def test_new_fields_can_be_set(self) -> None:
        entry = AuditEntry(
            tool_name="createClinicalOrder",
            timestamp=datetime.now(timezone.utc),
            params={},
            result_summary="ok",
            idempotency_key="idem-001",
            attempt_number=2,
            error_code="timeout",
            deduplicated=True,
        )
        assert entry.idempotency_key == "idem-001"
        assert entry.attempt_number == 2
        assert entry.error_code == "timeout"
        assert entry.deduplicated is True
