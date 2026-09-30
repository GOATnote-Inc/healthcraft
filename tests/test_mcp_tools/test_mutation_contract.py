"""Public mutation contracts execute safely on generated and injected records."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict
from datetime import date
from pathlib import Path

import jsonschema
import pytest

from healthcraft.entities.base import EntityType
from healthcraft.entities.encounters import Encounter
from healthcraft.entities.patients import Patient
from healthcraft.mcp.server import create_server
from healthcraft.tasks.inject import inject_task_patient
from healthcraft.tasks.loader import load_task
from healthcraft.world.state import WorldState

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_SCHEMAS = {
    tool["name"]: tool["parameters"]
    for tool in json.loads((REPO_ROOT / "configs/mcp-tools.json").read_text())["tools"]
}


def _call(world, name, params):
    jsonschema.validate(params, TOOL_SCHEMAS[name])
    return create_server(world).call_tool(name, params)


def _field(entity, name):
    return entity[name] if isinstance(entity, dict) else getattr(entity, name)


@pytest.fixture(autouse=True)
def idempotency_enabled(monkeypatch):
    monkeypatch.delenv("HC_IDEMPOTENT_TOOLS", raising=False)


@pytest.fixture(params=["dataclass", "dict"])
def world(request):
    world = WorldState()
    for suffix in ("A", "B"):
        patient = Patient(
            id=f"PAT-{suffix * 8}",
            entity_type=EntityType.PATIENT,
            created_at=world.timestamp,
            updated_at=world.timestamp,
            first_name=suffix,
            last_name="Synthetic",
            mrn=f"MRN-{suffix}",
            allergies=("Latex", {"name": "Penicillin", "reaction": "Hives"}),
        )
        encounter = Encounter(
            id=f"ENC-{suffix * 8}",
            entity_type=EntityType.ENCOUNTER,
            created_at=world.timestamp,
            updated_at=world.timestamp,
            patient_id=patient.id,
            clinical_notes=(("Triage", f"Original {suffix}"),),
        )
        world.put_entity(
            "patient", patient.id, asdict(patient) if request.param == "dict" else patient
        )
        world.put_entity(
            "encounter", encounter.id, asdict(encounter) if request.param == "dict" else encounter
        )
    return world


def test_registration_at_one_clock_never_replaces_existing_patient():
    world = WorldState()
    first = _call(world, "registerPatient", {"first_name": "Alice", "last_name": "Synthetic"})
    original = deepcopy(world.get_entity("patient", first["data"]["id"]))
    second = _call(world, "registerPatient", {"first_name": "Bob", "last_name": "Synthetic"})

    assert first["status"] == second["status"] == "ok"
    assert first["data"]["id"] != second["data"]["id"]
    assert first["data"]["mrn"] != second["data"]["mrn"]
    assert world.get_entity("patient", first["data"]["id"]) == original
    assert len(world.list_entities("patient")) == 2


def test_registration_honors_canonical_birth_date_and_returns_linked_initial_encounter():
    world = WorldState()
    result = _call(
        world,
        "registerPatient",
        {
            "first_name": "Alice",
            "last_name": "Synthetic",
            "sex": "F",
            "date_of_birth": "1990-01-01",
            "chief_complaint": "Synthetic complaint",
        },
    )

    assert result["status"] == "ok", result
    data = result["data"]
    assert data["dob"] == date(1990, 1, 1)
    assert data["patient_id"] == data["id"]
    encounter = world.get_entity("encounter", data["encounter_id"])
    assert _field(encounter, "patient_id") == data["patient_id"]
    assert _field(encounter, "chief_complaint") == "Synthetic complaint"
    assert _field(encounter, "arrival_time") == world.timestamp
    assert _field(encounter, "triage_time") is None
    assert _field(encounter, "vitals") == ()
    assert (
        _call(world, "getEncounterDetails", {"encounter_id": data["encounter_id"]})["status"]
        == "ok"
    )


def test_registration_sequence_is_reproducible_in_equivalent_worlds():
    worlds = [WorldState(), WorldState()]
    responses = []
    for world in worlds:
        responses.append(
            [
                _call(world, "registerPatient", {"first_name": "Alice", "last_name": "Synthetic"}),
                _call(world, "registerPatient", {"first_name": "Bob", "last_name": "Synthetic"}),
            ]
        )
    assert responses[0] == responses[1]
    assert worlds[0].list_entities("encounter") == worlds[1].list_entities("encounter")


def test_registration_retry_preserves_both_entities_and_return_contract():
    world = WorldState()
    params = {"first_name": "Alice", "last_name": "Synthetic", "idempotency_key": "register-A"}
    first = _call(world, "registerPatient", params)
    retry = _call(world, "registerPatient", params)

    assert retry["data"] == first["data"]
    assert retry["deduplicated"] is True
    assert first["data"]["patient_id"] == first["data"]["id"]
    assert first["data"]["encounter_id"] in world.list_entities("encounter")
    assert len(world.list_entities("patient")) == len(world.list_entities("encounter")) == 1


def test_legacy_registration_birth_date_is_still_supported():
    world = WorldState()
    result = create_server(world).call_tool(
        "registerPatient",
        {
            "first_name": "Alice",
            "last_name": "Synthetic",
            "dob": "1990-01-01",
        },
    )
    assert result["status"] == "ok", result
    assert result["data"]["dob"] == date(1990, 1, 1)


def test_structured_allergy_does_not_crash_unrelated_medication_order(world):
    before = deepcopy(world.list_entities("patient"))
    result = _call(
        world,
        "createClinicalOrder",
        {
            "encounter_id": "ENC-AAAAAAAA",
            "order_type": "medication",
            "details": {"medication": "Doxycycline", "dose": "100 mg"},
        },
    )
    assert result["status"] == "ok", result
    assert result["data"]["encounter_id"] == "ENC-AAAAAAAA"
    assert world.list_entities("patient") == before
    assert all(
        _field(task, "encounter_id") == "ENC-AAAAAAAA"
        for task in world.list_entities("clinical_task").values()
    )


def test_structured_allergy_conflict_is_rejected_without_mutation(world):
    result = _call(
        world,
        "createClinicalOrder",
        {
            "encounter_id": "ENC-AAAAAAAA",
            "order_type": "medication",
            "details": {"medication": "Penicillin"},
        },
    )
    assert result["status"] == "error", result
    assert result["code"] == "allergy_conflict"
    assert not world.list_entities("order")
    assert not world.list_entities("clinical_task")
    assert world.audit_log[-1].error_code == "allergy_conflict"


def test_actual_injected_allergy_supports_order_validation():
    task = load_task(REPO_ROOT / "configs/tasks/information_retrieval/task_001_allergy_check.yaml")
    world = WorldState()
    ids = inject_task_patient(world, task.id, task.patient, task.initial_state)
    result = _call(
        world,
        "createClinicalOrder",
        {
            "encounter_id": ids["encounter_id"],
            "order_type": "medication",
            "details": {"medication": "Penicillin"},
        },
    )
    assert result["code"] == "allergy_conflict", result
    assert not world.list_entities("order")


def test_structured_allergies_append_and_deduplicate_without_losing_history(world):
    unchanged = deepcopy(world.get_entity("patient", "PAT-BBBBBBBB"))
    allergy = {"name": "Sulfa", "reaction": "Rash", "severity": "mild"}
    existing = {"name": "Penicillin", "reaction": "Hives"}
    params = {"patient_id": "PAT-AAAAAAAA", "allergies": [existing, allergy, deepcopy(allergy)]}
    result = _call(world, "updatePatientRecord", params)

    assert result["status"] == "ok", result
    assert tuple(result["data"]["allergies"]) == ("Latex", existing, allergy)
    assert _field(world.get_entity("patient", "PAT-AAAAAAAA"), "allergies") == (
        "Latex",
        existing,
        allergy,
    )
    assert world.get_entity("patient", "PAT-BBBBBBBB") == unchanged
    retry = _call(world, "updatePatientRecord", params)
    assert retry["data"]["allergies"] == result["data"]["allergies"]


def test_structured_allergy_idempotency_and_legacy_duplicate_flag(world, monkeypatch):
    params = {
        "patient_id": "PAT-AAAAAAAA",
        "allergies": [{"name": "Sulfa"}],
        "idempotency_key": "allergy-A",
    }
    first = _call(world, "updatePatientRecord", params)
    second = _call(world, "updatePatientRecord", params)
    assert first["status"] == second["status"] == "ok"
    assert second["deduplicated"] is True
    assert first["data"] == second["data"]
    monkeypatch.setenv("HC_IDEMPOTENT_TOOLS", "0")
    third = _call(world, "updatePatientRecord", params)
    assert list(third["data"]["allergies"]).count({"name": "Sulfa"}) == 2


def test_encounter_notes_persist_and_are_retrievable_only_for_target(world):
    unchanged = deepcopy(world.get_entity("encounter", "ENC-BBBBBBBB"))
    result = _call(
        world, "updateEncounter", {"encounter_id": "ENC-AAAAAAAA", "notes": "Unique follow-up note"}
    )

    assert result["status"] == "ok", result
    retrieved = _call(world, "getEncounterDetails", {"encounter_id": "ENC-AAAAAAAA"})
    notes = retrieved["data"]["clinical_notes"]
    assert notes[0] == ("Triage", "Original A") or notes[0] == ["Triage", "Original A"]
    assert "Unique follow-up note" in str(notes)
    stored = list(world.list_entities("clinical_note").values())
    assert len(stored) == 1
    assert stored[0]["content"] == "Unique follow-up note"
    assert stored[0]["encounter_id"] == "ENC-AAAAAAAA"
    assert stored[0]["patient_id"] == "PAT-AAAAAAAA"
    assert world.get_entity("encounter", "ENC-BBBBBBBB") == unchanged


def test_encounter_note_retry_is_idempotent_but_new_notes_append(world):
    params = {"encounter_id": "ENC-AAAAAAAA", "notes": "First note", "idempotency_key": "note-A"}
    first = _call(world, "updateEncounter", params)
    second = _call(world, "updateEncounter", params)
    assert second["deduplicated"] is True
    assert first["data"] == second["data"]
    assert len(world.list_entities("clinical_note")) == 1
    _call(world, "updateEncounter", {"encounter_id": "ENC-AAAAAAAA", "notes": "Second note"})
    assert len(world.list_entities("clinical_note")) == 2
    notes = _field(world.get_entity("encounter", "ENC-AAAAAAAA"), "clinical_notes")
    assert [item[1] for item in notes] == ["Original A", "First note", "Second note"]


def test_registration_does_not_invent_clinical_history_or_triage():
    world = WorldState()
    result = _call(world, "registerPatient", {"first_name": "Alice", "last_name": "Synthetic"})
    assert result["status"] == "ok", result
    patient = world.get_entity("patient", result["data"]["id"])
    assert patient.dob is None
    assert patient.sex == ""
    assert patient.allergies == patient.medications == patient.pmh == ()
    assert patient.advance_directives == patient.insurance_id == ""
    encounter = world.get_entity("encounter", result["data"]["encounter_id"])
    assert encounter.esi_level is None
    assert encounter.triage_time is None
    assert encounter.vitals == encounter.labs == encounter.imaging == ()


@pytest.mark.parametrize("dedup", [True, False])
def test_structured_allergy_input_is_detached_from_saved_patient(world, monkeypatch, dedup):
    monkeypatch.setenv("HC_IDEMPOTENT_TOOLS", "1" if dedup else "0")
    allergy = {"name": "Aspirin", "reaction": {"symptoms": ["Hives"]}}
    original = deepcopy(allergy)
    result = _call(
        world, "updatePatientRecord", {"patient_id": "PAT-AAAAAAAA", "allergies": [allergy]}
    )
    assert result["status"] == "ok", result
    allergy["name"] = "Unrelated"
    allergy["reaction"]["symptoms"].append("changed after call")

    stored = _field(world.get_entity("patient", "PAT-AAAAAAAA"), "allergies")
    assert stored[-1] == original
    order = _call(
        world,
        "createClinicalOrder",
        {
            "encounter_id": "ENC-AAAAAAAA",
            "order_type": "medication",
            "details": {"medication": "Aspirin"},
        },
    )
    assert order["code"] == "allergy_conflict", order


@pytest.mark.parametrize("response_source", ["update", "retry", "read"])
def test_mutating_returned_allergy_does_not_change_saved_patient(world, response_source):
    params = {
        "patient_id": "PAT-AAAAAAAA",
        "allergies": [{"name": "Aspirin"}],
        "idempotency_key": "detached-allergy",
    }
    response = _call(world, "updatePatientRecord", params)
    if response_source == "retry":
        response = _call(world, "updatePatientRecord", params)
    elif response_source == "read":
        response = _call(world, "getPatientHistory", {"patient_id": "PAT-AAAAAAAA"})
    assert response["status"] == "ok", response
    before = deepcopy(_field(world.get_entity("patient", "PAT-AAAAAAAA"), "allergies"))

    response["data"]["allergies"][-1]["name"] = "Changed after response"

    assert _field(world.get_entity("patient", "PAT-AAAAAAAA"), "allergies") == before


def test_registration_allergies_are_detached_from_caller_data():
    world = WorldState()
    allergy = {"name": "Aspirin", "reaction": {"symptoms": ["Hives"]}}
    original = deepcopy(allergy)
    response = create_server(world).call_tool(
        "registerPatient", {"first_name": "Alice", "last_name": "Synthetic", "allergies": [allergy]}
    )
    assert response["status"] == "ok", response
    allergy["reaction"]["symptoms"].clear()
    response["data"]["allergies"][0]["name"] = "Changed after response"

    assert world.get_entity("patient", response["data"]["patient_id"]).allergies == (original,)


def test_registration_preserves_arrival_mode_and_unverified_insurance():
    world = WorldState()
    insurance = {
        "payer": "Synthetic plan",
        "member_id": "SYNTHETIC-123",
        "custom": {"contact": ["555-0100"]},
    }
    original = deepcopy(insurance)
    response = _call(
        world,
        "registerPatient",
        {
            "first_name": "Alice",
            "last_name": "Synthetic",
            "arrival_mode": "ambulance",
            "insurance": insurance,
        },
    )
    assert response["status"] == "ok", response
    patient_id = response["data"]["patient_id"]
    encounter_id = response["data"]["encounter_id"]
    details = _call(world, "getEncounterDetails", {"encounter_id": encounter_id})
    assert details["data"]["arrival_mode"] == "ambulance"
    coverage = _call(world, "getInsuranceCoverage", {"patient_id": patient_id})
    assert coverage["status"] == "ok", coverage
    assert len(coverage["data"]) == 1
    record = coverage["data"][0]
    assert record["id"] == response["data"]["insurance_id"]
    assert record["insurance_id"] == record["id"]
    assert record["patient_id"] == patient_id
    assert record["verification_status"] == "unverified"
    assert record["submitted_details"] == original
    assert record["payer"] == original["payer"]
    assert record["member_id"] == original["member_id"]
    for fabricated in ("active", "benefits", "covered_medications", "copay_er"):
        assert fabricated not in record

    insurance["custom"]["contact"].clear()
    record["submitted_details"]["custom"]["contact"].clear()
    record["custom"]["contact"].clear()
    saved = world.get_entity("insurance", response["data"]["insurance_id"])
    assert saved["submitted_details"] == original
    assert saved["custom"] == original["custom"]


def test_insurance_payload_cannot_override_trusted_registration_metadata():
    world = WorldState()
    payload = {
        "id": "INS-UNTRUSTED",
        "insurance_id": "INS-OTHER",
        "patient_id": "PAT-FFFFFFFF",
        "entity_type": "patient",
        "created_at": "untrusted",
        "updated_at": "untrusted",
        "verification_status": "verified",
        "submitted_details": {"nested": "original"},
    }
    response = _call(
        world,
        "registerPatient",
        {"first_name": "Alice", "last_name": "Synthetic", "insurance": payload},
    )
    assert response["status"] == "ok", response
    record = world.get_entity("insurance", response["data"]["insurance_id"])
    assert record is not None
    assert record["submitted_details"] == payload
    assert record["patient_id"] == response["data"]["patient_id"]
    assert record["id"] == record["insurance_id"] == response["data"]["insurance_id"]
    assert record["id"] not in (payload["id"], payload["insurance_id"])
    assert record["entity_type"] == EntityType.INSURANCE
    assert record["created_at"] == record["updated_at"] == world.timestamp
    assert record["verification_status"] == "unverified"
    assert _call(world, "getInsuranceCoverage", {"patient_id": "PAT-FFFFFFFF"})["status"] == "error"


def test_insurance_registration_is_deterministic_and_idempotent():
    worlds = [WorldState(), WorldState()]
    params = {
        "first_name": "Alice",
        "last_name": "Synthetic",
        "insurance": {"payer": "Synthetic"},
        "idempotency_key": "insured-registration",
    }
    responses = [_call(world, "registerPatient", params) for world in worlds]
    assert responses[0] == responses[1]
    assert len(worlds[0].list_entities("insurance")) == 1
    assert worlds[0].list_entities("insurance") == worlds[1].list_entities("insurance")
    retried = _call(worlds[0], "registerPatient", params)
    assert retried["deduplicated"] is True
    assert retried["data"] == responses[0]["data"]
    assert len(worlds[0].list_entities("insurance")) == 1


def test_registration_insurance_id_collision_does_not_overwrite_existing_record():
    params = {"first_name": "Alice", "last_name": "Synthetic", "insurance": {"payer": "Synthetic"}}
    probe_world = WorldState()
    probe = _call(probe_world, "registerPatient", params)
    collision_id = probe["data"]["insurance_id"]
    assert collision_id
    world = WorldState()
    existing = {"id": collision_id, "patient_id": "PAT-FFFFFFFF", "payer": "Existing synthetic"}
    world.put_entity("insurance", collision_id, deepcopy(existing))

    response = _call(world, "registerPatient", params)

    assert response["status"] == "ok", response
    assert response["data"]["insurance_id"] != collision_id
    assert world.get_entity("insurance", collision_id) == existing
    assert len(world.list_entities("insurance")) == 2


@pytest.mark.parametrize(
    ("extra", "code"),
    [
        ({"insurance": {}, "insurance_id": "INS-LEGACY"}, "conflicting_params"),
        ({"insurance": []}, "invalid_param"),
        ({"arrival_mode": {}}, "invalid_param"),
    ],
)
def test_bad_registration_insurance_or_arrival_does_not_write_entities(extra, code):
    world = WorldState()
    result = create_server(world).call_tool(
        "registerPatient", {"first_name": "Alice", "last_name": "Synthetic", **extra}
    )
    assert result["status"] == "error", result
    assert result["code"] == code
    assert all(not world.list_entities(kind) for kind in ("patient", "encounter", "insurance"))


def test_registration_keeps_legacy_insurance_link_without_inventing_coverage():
    world = WorldState()
    result = create_server(world).call_tool(
        "registerPatient",
        {"first_name": "Alice", "last_name": "Synthetic", "insurance_id": "INS-LEGACY"},
    )
    assert result["status"] == "ok", result
    assert result["data"]["insurance_id"] == "INS-LEGACY"
    assert world.list_entities("insurance") == {}


@pytest.mark.parametrize("mutation_source", ["input", "response", "retry"])
def test_order_details_are_detached_from_input_and_returned_data(world, mutation_source):
    details = {"medication": "Doxycycline", "dose": "100 mg", "instructions": ["Original"]}
    original = deepcopy(details)
    params = {
        "encounter_id": "ENC-AAAAAAAA",
        "order_type": "medication",
        "details": details,
        "idempotency_key": "detached-order",
    }
    response = _call(world, "createClinicalOrder", params)
    assert response["status"] == "ok", response
    if mutation_source == "retry":
        response = _call(world, "createClinicalOrder", params)
        assert response["deduplicated"] is True
    changing = details if mutation_source == "input" else response["data"]["details"]
    changing["medication"] = "Penicillin"
    changing["instructions"].clear()

    saved = world.get_entity("order", response["data"]["id"])
    assert saved["details"] == original
    assert len(world.list_entities("order")) == 1
