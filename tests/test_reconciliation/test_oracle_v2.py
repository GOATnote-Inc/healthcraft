"""V2 engineering verification uses bound authored labels and actual tool state."""

from __future__ import annotations

import hashlib
import importlib
import json
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pytest

from healthcraft.entities.base import EntityType
from healthcraft.entities.encounters import Encounter
from healthcraft.entities.patients import Patient
from healthcraft.mcp.server import create_server
from healthcraft.reconciliation.execution import ReconciliationRecorder
from healthcraft.reconciliation.fixture import snapshot_world
from healthcraft.tasks.care_projection import project_authored_care
from healthcraft.tasks.imaging_projection import project_imaging
from healthcraft.world.state import WorldState


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def case_data():
    # Separate, explicit engineering source and expectation literals. No renderer
    # or production row selector generates the expected source ledger.
    scenario = {
        "schema_version": "healthcraft-reconciliation-scenario/v2",
        "id": "synthetic-ed-reconciliation/v2/REC2-999",
        "clock": "2026-11-01T12:00:00Z",
        "target": {"patient_id": "PAT-11111111", "encounter_id": "ENC-11111111"},
        "patients": [
            {
                "id": "PAT-11111111",
                "mrn": "TEST-1",
                "first_name": "Avery",
                "last_name": "Synthetic",
                "date_of_birth": None,
                "sex": "",
                "prior_visit_ids": ["ENC-22222222"],
            }
        ],
        "encounters": [
            {
                "id": "ENC-11111111",
                "patient_id": "PAT-11111111",
                "chief_complaint": "Source preservation exercise",
                "arrival_time": None,
                "patient_data": {
                    "current_management": [
                        {
                            "source_id": "SRC-X01",
                            "item": "synthetic observation",
                            "status": None,
                            "time": None,
                        }
                    ]
                },
            },
            {
                "id": "ENC-22222222",
                "patient_id": "PAT-11111111",
                "chief_complaint": "Prior source context",
                "arrival_time": None,
                "patient_data": {
                    "active_orders": [
                        {
                            "source_id": "SRC-X02",
                            "order_id": "ORDER-X01",
                            "item": "prior synthetic order",
                            "status": "planned",
                            "time": None,
                        }
                    ]
                },
            },
        ],
    }
    expected = {
        "schema_version": "healthcraft-reconciliation-expectations/v2",
        "scenario_id": "synthetic-ed-reconciliation/v2/REC2-999",
        "scenario_sha256": digest(scenario),
        "target": {"patient_id": "PAT-11111111", "encounter_id": "ENC-11111111"},
        "sources": [
            {
                "source_id": "SRC-X01",
                "patient_id": "PAT-11111111",
                "encounter_id": "ENC-11111111",
                "source_collection": "current_management",
                "source_path": "/current_management/0",
                "source": {
                    "source_id": "SRC-X01",
                    "item": "synthetic observation",
                    "status": None,
                    "time": None,
                },
            },
            {
                "source_id": "SRC-X02",
                "patient_id": "PAT-11111111",
                "encounter_id": "ENC-22222222",
                "source_collection": "active_orders",
                "source_path": "/active_orders/0",
                "source": {
                    "source_id": "SRC-X02",
                    "order_id": "ORDER-X01",
                    "item": "prior synthetic order",
                    "status": "planned",
                    "time": None,
                },
            },
        ],
        "observation_source_ids": ["SRC-X01"],
        "unresolved_conflicts": [],
        "scope_exclusions": [
            {
                "source_id": "SRC-X02",
                "patient_id": "PAT-11111111",
                "encounter_id": "ENC-22222222",
                "reason": "other_encounter",
            }
        ],
    }
    return {
        "schema_version": "healthcraft-reconciliation-case/v2",
        "case_id": "REC2-999",
        "scenario_family_id": "unknown-current-prior-order",
        "exposure": "development",
        "label_status": "engineering_authored_independent_review_pending",
        "casebook_sha256": "a" * 64,
        "scenario_sha256": digest(scenario),
        "expectations_sha256": digest(expected),
        "scenario": scenario,
        "expectations": expected,
        "designated_control": "omit_observation",
    }


def rebind(case):
    case["scenario_sha256"] = digest(case["scenario"])
    case["expectations"]["scenario_sha256"] = case["scenario_sha256"]
    case["expectations_sha256"] = digest(case["expectations"])


def binding(case):
    return {
        name: case[name]
        for name in (
            "case_id",
            "casebook_sha256",
            "scenario_sha256",
            "expectations_sha256",
            "scenario_family_id",
        )
    }


def run(
    case,
    *,
    change_note=None,
    readback=True,
    duplicate=False,
    retry=False,
    stop="completed",
    omit_read=None,
    ack_only=False,
):
    scenario, expected = case["scenario"], case["expectations"]
    clock = datetime.fromisoformat(scenario["clock"].replace("Z", "+00:00")).astimezone(
        timezone.utc
    )
    world = WorldState(start_time=clock, dynamic_state_enabled=False)
    for row in scenario["patients"]:
        world.put_entity(
            "patient",
            row["id"],
            Patient(
                id=row["id"],
                entity_type=EntityType.PATIENT,
                created_at=clock,
                updated_at=clock,
                mrn=row["mrn"],
                first_name=row["first_name"],
                last_name=row["last_name"],
                dob=None,
                sex=row["sex"],
                prior_visit_ids=tuple(row["prior_visit_ids"]),
            ),
        )
    for row in scenario["encounters"]:
        images = project_imaging(row["patient_data"], task_id=scenario["id"])
        world.put_entity(
            "encounter",
            row["id"],
            Encounter(
                id=row["id"],
                entity_type=EntityType.ENCOUNTER,
                created_at=clock,
                updated_at=clock,
                patient_id=row["patient_id"],
                chief_complaint=row["chief_complaint"],
                arrival_time=row["arrival_time"],
                esi_level=None,
                triage_time=None,
                authored_care=project_authored_care(row["patient_data"]),
                imaging=images.records,
                imaging_projection_notices=images.notices,
            ),
        )
    before = snapshot_world(world)
    server = create_server(world)
    if ack_only:
        server._handlers["update_encounter"] = server._handlers["get_encounter_details"]
    recorder = ReconciliationRecorder(server, world)
    for row in scenario["encounters"]:
        if row["id"] != omit_read:
            recorder.call("getEncounterDetails", {"encounter_id": row["id"]})
    note = {
        "schema_version": "healthcraft-reconciliation-note/v1",
        **expected["target"],
        "observations": [
            deepcopy(row)
            for row in expected["sources"]
            if row["source_id"] in expected["observation_source_ids"]
        ],
        "unresolved_conflicts": deepcopy(expected["unresolved_conflicts"]),
        "scope_exclusions": deepcopy(expected["scope_exclusions"]),
    }
    if change_note:
        change_note(note)
    params = {
        "encounter_id": expected["target"]["encounter_id"],
        "notes": canonical(note),
        "idempotency_key": "test-note",
    }
    recorder.call("updateEncounter", params)
    if duplicate:
        recorder.call("updateEncounter", {**params, "idempotency_key": "second-note"})
    if retry:
        recorder.call("updateEncounter", params)
    if readback:
        recorder.call("getEncounterDetails", {"encounter_id": expected["target"]["encounter_id"]})
    recorder.close()
    return {
        "schema_version": "healthcraft-reconciliation-execution/v2",
        "case_binding": binding(case),
        "scenario_sha256": case["scenario_sha256"],
        "before": before,
        "after": snapshot_world(world),
        "calls": recorder.calls,
        "audit": json.loads(
            json.dumps(
                [asdict(entry) for entry in world.audit_log], default=lambda item: item.isoformat()
            )
        ),
        "completion": {"status": stop},
    }


@pytest.fixture(autouse=True)
def idempotency(monkeypatch):
    monkeypatch.setenv("HC_IDEMPOTENT_TOOLS", "1")


def verify(case, evidence):
    return importlib.import_module("healthcraft.reconciliation.oracle_v2").verify_case(
        case, evidence
    )


def test_variable_source_counts_actual_tools_unknowns_and_no_clinical_score():
    case = case_data()
    evidence = run(case)
    original = canonical([case, evidence])
    result = verify(case, evidence)
    assert result["schema_version"] == "healthcraft-reconciliation-verification/v2"
    assert result["mechanical_passed"] is True
    assert result["coverage"] == {
        "expected_sources": 2,
        "target_observations": 1,
        "clinical_criteria": 0,
        "safety_criteria": 0,
    }
    assert result["benchmark_score"] is None
    assert result["case_binding"] == binding(case)
    assert canonical([case, evidence]) == original


def test_single_source_without_exclusions_is_not_forced_into_v1_denominators():
    case = case_data()
    case["scenario"]["patients"][0]["prior_visit_ids"] = []
    case["scenario"]["encounters"].pop()
    case["expectations"]["sources"].pop()
    case["expectations"]["scope_exclusions"] = []
    rebind(case)
    result = verify(case, run(case))
    assert result["mechanical_passed"] is True
    assert result["coverage"]["expected_sources"] == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "case_id",
        "casebook_sha256",
        "scenario_sha256",
        "expectations_sha256",
        "scenario_family_id",
        "missing",
        "extra",
        "schema",
    ],
)
def test_execution_case_bindings_must_match_exactly(mutation):
    case = case_data()
    evidence = run(case)
    if mutation == "missing":
        del evidence["case_binding"]
    elif mutation == "extra":
        evidence["case_binding"]["extra"] = "claim"
    elif mutation == "schema":
        evidence["schema_version"] = "healthcraft-reconciliation-execution/v1"
    else:
        evidence["case_binding"][mutation] = "changed"
    result = verify(case, evidence)
    assert result["status"] == "provenance_error"
    assert result["mechanical_passed"] is False


@pytest.mark.parametrize(
    "mutation",
    ["scenario", "expectations", "exposure", "label_status", "extra", "case_schema", "hash_type"],
)
def test_invalid_case_cannot_be_self_asserted_with_stale_hashes(mutation):
    case = case_data()
    evidence = run(case)
    if mutation == "scenario":
        case["scenario"]["encounters"][0]["chief_complaint"] = "changed"
    elif mutation == "expectations":
        case["expectations"]["sources"][0]["source"]["status"] = "administered"
    elif mutation == "extra":
        case["independently_validated"] = True
    elif mutation == "case_schema":
        case["schema_version"] = "healthcraft-reconciliation-case/v1"
    elif mutation == "hash_type":
        case["casebook_sha256"] = True
    else:
        case[mutation] = "independently_validated"
    result = verify(case, evidence)
    assert result["status"] == "provenance_error"
    assert result["coverage"]["expected_sources"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        "omitted_source",
        "invented_raw_value",
        "wrong_pointer",
        "negative_index",
        "extra_observation",
        "duplicate_observation",
        "omitted_exclusion",
        "wrong_exclusion_reason",
        "unsupported_conflict",
        "duplicate_source",
    ],
)
def test_rehashed_labels_must_still_match_the_actual_source_contract(mutation):
    case = case_data()
    expected = case["expectations"]
    if mutation == "omitted_source":
        expected["sources"].pop()
    elif mutation == "invented_raw_value":
        expected["sources"][0]["source"]["status"] = "administered"
    elif mutation == "wrong_pointer":
        expected["sources"][0]["source_path"] = "/active_orders/0"
    elif mutation == "negative_index":
        expected["sources"][0]["source_path"] = "/current_management/-1"
    elif mutation == "extra_observation":
        expected["observation_source_ids"].append("SRC-X02")
    elif mutation == "duplicate_observation":
        expected["observation_source_ids"].append("SRC-X01")
    elif mutation == "omitted_exclusion":
        expected["scope_exclusions"] = []
    elif mutation == "wrong_exclusion_reason":
        expected["scope_exclusions"][0]["reason"] = "other_patient"
    elif mutation == "unsupported_conflict":
        expected["unresolved_conflicts"] = [
            {
                "source_ids": ["SRC-X01", "SRC-X02"],
                "event_id": "invented",
                "field": "reported_status",
            }
        ]
    else:
        expected["sources"].append(deepcopy(expected["sources"][0]))
    rebind(case)
    result = verify(case, run(case))
    assert result["status"] == "provenance_error"
    assert result["mechanical_passed"] is False


@pytest.mark.parametrize(
    "control",
    [
        "omission",
        "invented_status",
        "wrong_patient",
        "duplicate_observation",
        "duplicate_writes",
        "missing_readback",
        "ack_only",
        "unretrieved_source",
    ],
)
def test_actual_action_controls_cannot_satisfy_the_contract(control):
    case = case_data()
    kwargs = {}
    if control == "omission":
        kwargs["change_note"] = lambda note: note["observations"].clear()
    elif control == "invented_status":
        kwargs["change_note"] = lambda note: note["observations"][0]["source"].update(
            status="administered"
        )
    elif control == "wrong_patient":
        kwargs["change_note"] = lambda note: note.update(patient_id="PAT-99999999")
    elif control == "duplicate_observation":
        kwargs["change_note"] = lambda note: note["observations"].append(
            deepcopy(note["observations"][0])
        )
    elif control == "duplicate_writes":
        kwargs["duplicate"] = True
    elif control == "missing_readback":
        kwargs["readback"] = False
    elif control == "ack_only":
        kwargs["ack_only"] = True
    else:
        kwargs["omit_read"] = "ENC-22222222"
    result = verify(case, run(case, **kwargs))
    assert result["checks"]["provenance"] is True
    assert result["mechanical_passed"] is False


def test_idempotent_retry_is_not_a_second_note():
    case = case_data()
    assert verify(case, run(case, retry=True))["mechanical_passed"] is True


def test_postwrite_interruption_preserves_actual_storage():
    case = case_data()
    result = verify(case, run(case, stop="interrupted"))
    assert result["checks"]["persisted_action"] is True
    assert result["checks"]["readback"] is True
    assert result["checks"]["execution_complete"] is False


def test_aware_offset_clock_is_matched_to_native_utc_snapshot():
    case = case_data()
    case["scenario"]["clock"] = "2026-11-01T14:00:00.125+02:00"
    rebind(case)
    assert verify(case, run(case))["mechanical_passed"] is True


def catalog_case(case_id):
    directory = Path(__file__).resolve().parents[2] / "configs/evaluation/reconciliation_v2"
    book = json.loads((directory / "casebook.json").read_bytes())
    row = next(row for row in book["cases"] if row["case_id"] == case_id)
    return {
        "schema_version": "healthcraft-reconciliation-case/v2",
        "case_id": row["case_id"],
        "scenario_family_id": row["scenario_family_id"],
        "exposure": book["exposure"],
        "label_status": book["label_status"],
        "casebook_sha256": digest(book),
        "scenario_sha256": row["scenario_sha256"],
        "expectations_sha256": row["expectations_sha256"],
        "scenario": json.loads((directory / row["scenario"]).read_bytes()),
        "expectations": json.loads((directory / row["expectations"]).read_bytes()),
        "designated_control": row["designated_control"],
    }


@pytest.mark.parametrize(
    "case_id,count",
    [(f"REC2-{index:03d}", count) for index, count in enumerate([6, 5, 6, 5, 6, 7, 4, 11], 1)],
)
def test_eight_authored_cases_verify_actual_reference_controller_and_native_tools(case_id, count):
    from healthcraft.reconciliation.execution_v2 import run_case

    case = catalog_case(case_id)
    evidence = run_case(case)
    result = verify(case, evidence)
    assert result["mechanical_passed"] is True, result["errors"]
    assert result["coverage"]["expected_sources"] == count
    assert result["coverage"]["target_observations"] == len(
        case["expectations"]["observation_source_ids"]
    )
    assert len(evidence["after"]["entities"]["clinical_note"]) == 1
    assert len(evidence["audit"]) == len(evidence["calls"])
    assert evidence["calls"][-1]["name"] == "getEncounterDetails"


def test_case_id_must_identify_bound_scenario_even_after_execution_binding_changes():
    case = case_data()
    case["case_id"] = "UNRELATED-CASE"
    result = verify(case, run(case))
    assert result["status"] == "provenance_error"


@pytest.mark.parametrize(
    "case_id,mutation",
    [("REC2-004", "drop_minority"), ("REC2-003", "cross_patient"), ("REC2-005", "merge_events")],
)
def test_conflict_labels_cannot_vote_drop_sources_or_merge_other_events(case_id, mutation):
    case = catalog_case(case_id)
    expected = case["expectations"]
    if mutation == "drop_minority":
        expected["unresolved_conflicts"][0]["source_ids"].pop(0)
    elif mutation == "cross_patient":
        other = next(
            row
            for row in expected["sources"]
            if row["patient_id"] != expected["target"]["patient_id"] and "event_id" in row["source"]
        )
        target = next(
            row
            for row in expected["sources"]
            if row["source_id"] in expected["observation_source_ids"]
            and row["source"].get("event_id") == other["source"]["event_id"]
        )
        expected["unresolved_conflicts"] = [
            {
                "source_ids": [target["source_id"], other["source_id"]],
                "event_id": other["source"]["event_id"],
                "field": "reported_status",
            }
        ]
    else:
        ids = [
            row["source_id"]
            for row in expected["sources"]
            if row["encounter_id"] == expected["target"]["encounter_id"]
            and "event_id" in row["source"]
        ]
        expected["unresolved_conflicts"] = [
            {"source_ids": ids, "event_id": "MERGED-EVENT", "field": "reported_status"}
        ]
    rebind(case)
    result = verify(case, run(case))
    assert result["status"] == "provenance_error"


def test_source_status_null_is_not_a_boolean_or_invented_administration():
    case = case_data()
    result = verify(
        case,
        run(case, change_note=lambda note: note["observations"][0]["source"].update(status=False)),
    )
    assert result["checks"]["provenance"] is True
    assert result["checks"]["source_fidelity"] is False
    assert result["mechanical_passed"] is False


def test_truncated_retrieval_does_not_satisfy_source_fidelity():
    case = case_data()
    evidence = run(case)
    evidence["calls"][0]["response"]["data"]["authored_care"] = []
    result = verify(case, evidence)
    assert result["checks"]["provenance"] is True
    assert result["checks"]["source_fidelity"] is False


def test_missing_call_receipt_is_provenance_failure():
    case = case_data()
    evidence = run(case)
    evidence["calls"].pop(0)
    assert verify(case, evidence)["status"] == "provenance_error"


def test_v1_pin_is_not_removed_by_v2_support():
    from healthcraft.reconciliation.oracle import verify_reconciliation

    case = case_data()
    result = verify_reconciliation(case["scenario"], case["expectations"], run(case))
    assert result["status"] == "provenance_error"


def test_case_id_syntax_matches_registry_and_native_fixture():
    case = case_data()
    case["case_id"] = "../renamed"
    case["scenario"]["id"] = "synthetic-ed-reconciliation/v2/../renamed"
    case["expectations"]["scenario_id"] = case["scenario"]["id"]
    rebind(case)
    assert verify(case, run(case))["status"] == "provenance_error"


def test_conflict_source_order_is_not_a_new_semantic_answer():
    from healthcraft.reconciliation.execution_v2 import run_case

    case = catalog_case("REC2-004")
    case["expectations"]["unresolved_conflicts"][0]["source_ids"].reverse()
    rebind(case)
    result = verify(case, run_case(case))
    assert result["mechanical_passed"] is True, result["errors"]
