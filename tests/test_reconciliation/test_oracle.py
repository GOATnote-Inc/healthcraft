"""Independent reconciliation oracle controls using real handlers and audit entries."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

import pytest

from healthcraft.entities.base import EntityType
from healthcraft.entities.encounters import Encounter
from healthcraft.entities.patients import Patient
from healthcraft.mcp.server import create_server
from healthcraft.reconciliation.oracle import load_expectations, verify_reconciliation
from healthcraft.tasks.care_projection import project_authored_care
from healthcraft.tasks.imaging_projection import project_imaging
from healthcraft.world.state import WorldState

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/evaluation/reconciliation_v1"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def detached(value):
    def default(item):
        if is_dataclass(item):
            return asdict(item)
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, Enum):
            return item.value
        raise TypeError(type(item).__name__)

    return json.loads(json.dumps(value, default=default, allow_nan=False))


def snapshot(world):
    return detached(
        {
            "timestamp": world.timestamp,
            "entities": {kind.value: world.list_entities(kind.value) for kind in EntityType},
        }
    )


def literal_note(expectations):
    # Test author constructs the declared note schema directly, without a controller/renderer.
    return {
        "schema_version": "healthcraft-reconciliation-note/v1",
        "patient_id": "PAT-AAAAAAAA",
        "encounter_id": "ENC-AAAAAAAA",
        "observations": deepcopy(expectations["sources"][:6]),
        "unresolved_conflicts": [
            {
                "source_ids": ["SRC-A04", "SRC-A05"],
                "event_id": "EVENT-A01",
                "field": "reported_status",
            }
        ],
        "scope_exclusions": [
            {
                "source_id": "SRC-A07",
                "patient_id": "PAT-AAAAAAAA",
                "encounter_id": "ENC-CCCCCCCC",
                "reason": "other_encounter",
            },
            {
                "source_id": "SRC-B01",
                "patient_id": "PAT-BBBBBBBB",
                "encounter_id": "ENC-BBBBBBBB",
                "reason": "other_patient",
            },
        ],
    }


def fixture_world(scenario):
    # Standalone test construction, independent of the production fixture builder.
    clock = datetime.fromisoformat(scenario["clock"].replace("Z", "+00:00"))
    world = WorldState(start_time=clock)
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
        imaging = project_imaging(row["patient_data"], task_id=scenario["id"])
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
                imaging=imaging.records,
                imaging_projection_notices=imaging.notices,
            ),
        )
    return world


def run_case(
    *,
    mutate_note=None,
    read_ids=None,
    write_target="ENC-AAAAAAAA",
    duplicate=False,
    retry=False,
    completion="completed",
    raw_note=None,
    world_factory=fixture_world,
):
    scenario = json.loads((CONFIG / "scenario.json").read_text())
    expectations = json.loads((CONFIG / "expectations.json").read_text())
    world = world_factory(scenario)
    server = create_server(world)
    before = snapshot(world)
    calls = []

    def call(name, params):
        start = len(world.audit_log)
        response = server.call_tool(name, deepcopy(params))
        calls.append(
            detached(
                {
                    "id": f"call-{len(calls) + 1}",
                    "name": name,
                    "params": params,
                    "response": response,
                    "audit_start": start,
                    "audit_end": len(world.audit_log),
                }
            )
        )
        return response

    for identifier in (
        read_ids if read_ids is not None else ["ENC-AAAAAAAA", "ENC-CCCCCCCC", "ENC-BBBBBBBB"]
    ):
        assert call("getEncounterDetails", {"encounter_id": identifier})["status"] == "ok"
    note = literal_note(expectations)
    if mutate_note:
        mutate_note(note)
    content = raw_note if raw_note is not None else canonical(note)
    params = {"encounter_id": write_target, "notes": content, "idempotency_key": "reconcile"}
    assert call("updateEncounter", params)["status"] == "ok"
    if duplicate:
        assert call("updateEncounter", {**params, "idempotency_key": "duplicate"})["status"] == "ok"
    if retry:
        assert call("updateEncounter", params)["deduplicated"] is True
    if completion == "completed":
        assert call("getEncounterDetails", {"encounter_id": "ENC-AAAAAAAA"})["status"] == "ok"
    evidence = {
        "schema_version": "healthcraft-reconciliation-execution/v1",
        "scenario_sha256": hashlib.sha256(canonical(scenario).encode()).hexdigest(),
        "before": before,
        "after": snapshot(world),
        "calls": calls,
        "audit": detached(world.audit_log),
        "completion": {"status": completion},
    }
    return scenario, expectations, evidence


@pytest.fixture(autouse=True)
def idempotency(monkeypatch):
    monkeypatch.setenv("HEALTHCRAFT_IDEMPOTENT_TOOLS", "1")


def test_faithful_actual_execution_and_valid_unknowns():
    result = verify_reconciliation(*run_case())
    assert result["mechanical_passed"] is True
    assert all(result["checks"].values())
    assert result["benchmark_score"] is None
    assert result["benchmark_comparable"] is False
    assert result["coverage"]["clinical_criteria"] == result["coverage"]["safety_criteria"] == 0
    assert result["coverage"]["expected_sources"] == 8


def test_faithful_public_fixture_and_real_handlers_match_independent_expectations():
    from healthcraft.reconciliation.fixture import build_world

    assert verify_reconciliation(*run_case(world_factory=build_world))["mechanical_passed"] is True


def test_order_of_note_sets_does_not_change_meaning():
    def reorder(note):
        note["observations"].reverse()
        note["scope_exclusions"].reverse()
        note["unresolved_conflicts"][0]["source_ids"].reverse()

    assert verify_reconciliation(*run_case(mutate_note=reorder))["mechanical_passed"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda n: n.update(patient_id="PAT-BBBBBBBB"),
        lambda n: n["observations"].pop(),
        lambda n: n["observations"].append(deepcopy(n["observations"][0])),
        lambda n: n["observations"][0]["source"].update(status="administered"),
        lambda n: n["observations"][2]["source"].update(time="2026-09-30T14:05:00Z"),
        lambda n: n["observations"][2]["source"].update(status=False),
        lambda n: n["observations"][2]["source"].update(time=0),
        lambda n: n["observations"][5]["source"].update(findings="normal"),
        lambda n: n["observations"][0].update(source_path="/treatments_given/0"),
        lambda n: n["unresolved_conflicts"].clear(),
        lambda n: n["unresolved_conflicts"][0].update(resolved=True),
        lambda n: n["scope_exclusions"][0].update(reason="other_patient"),
        lambda n: n.update(clinical_assessment="safe"),
    ],
)
def test_source_claim_mutants_are_rejected(mutation):
    result = verify_reconciliation(*run_case(mutate_note=mutation))
    assert result["mechanical_passed"] is False
    assert result["checks"]["source_fidelity"] is False


@pytest.mark.parametrize(
    "raw_note",
    [
        "not JSON",
        "[]",
        '{"schema_version":"x","schema_version":"healthcraft-reconciliation-note/v1"}',
        '{"value":NaN}',
        '{"value":1e400}',
    ],
)
def test_malformed_note_fails_closed(raw_note):
    result = verify_reconciliation(*run_case(raw_note=raw_note))
    assert result["checks"]["source_fidelity"] is False
    assert result["mechanical_passed"] is False


def test_wrong_patient_write_is_not_a_persisted_target_action():
    result = verify_reconciliation(*run_case(write_target="ENC-BBBBBBBB"))
    assert result["checks"]["persisted_action"] is False


def test_omitted_retrieval_cannot_be_replaced_by_guessed_source_content():
    result = verify_reconciliation(*run_case(read_ids=["ENC-AAAAAAAA", "ENC-CCCCCCCC"]))
    assert result["checks"]["source_fidelity"] is False


def test_acknowledgement_without_persistence_is_not_action_success():
    scenario, expectations, evidence = run_case()
    evidence["after"] = deepcopy(evidence["before"])
    result = verify_reconciliation(scenario, expectations, evidence)
    assert result["checks"]["persisted_action"] is False
    assert result["mechanical_passed"] is False


def test_duplicate_write_rejected_but_identical_retry_retains_one_action():
    duplicate = verify_reconciliation(*run_case(duplicate=True))
    assert duplicate["checks"]["persisted_action"] is False
    assert verify_reconciliation(*run_case(retry=True))["mechanical_passed"] is True


def test_interruption_preserves_action_axis_without_claiming_complete_execution():
    result = verify_reconciliation(*run_case(completion="interrupted"))
    assert result["checks"]["source_fidelity"] is True
    assert result["checks"]["persisted_action"] is True
    assert result["checks"]["execution_complete"] is False
    assert result["checks"]["readback"] is False
    assert result["mechanical_passed"] is False


@pytest.mark.parametrize(
    "kind",
    [
        "missing_audit",
        "changed_audit",
        "duplicate_call_id",
        "wrong_response_owner",
        "truncated_response",
        "changed_source",
        "changed_other_entity",
        "extra_note",
        "missing_snapshot_collection",
        "nonfinite",
        "wrong_hash",
    ],
)
def test_evidence_mutants_cannot_pass(kind):
    scenario, expectations, evidence = run_case()
    if kind == "missing_audit":
        evidence["audit"].pop()
    elif kind == "changed_audit":
        evidence["audit"][0]["params"]["encounter_id"] = "ENC-BBBBBBBB"
    elif kind == "duplicate_call_id":
        evidence["calls"][1]["id"] = evidence["calls"][0]["id"]
    elif kind == "wrong_response_owner":
        evidence["calls"][0]["response"]["data"]["patient_id"] = "PAT-BBBBBBBB"
    elif kind == "truncated_response":
        evidence["calls"][0]["response"]["data"]["authored_care"] = []
    elif kind == "changed_source":
        evidence["after"]["entities"]["encounter"]["ENC-AAAAAAAA"]["authored_care"][0][
            "source_data"
        ][0]["status"] = "administered"
    elif kind == "changed_other_entity":
        evidence["after"]["entities"]["patient"]["PAT-BBBBBBBB"]["first_name"] = "Changed"
    elif kind == "extra_note":
        notes = evidence["after"]["entities"]["clinical_note"]
        notes["NOTE-FAKE"] = deepcopy(next(iter(notes.values())))
    elif kind == "missing_snapshot_collection":
        del evidence["before"]["entities"]["order"]
    elif kind == "nonfinite":
        evidence["after"]["timestamp"] = float("nan")
    else:
        evidence["scenario_sha256"] = "0" * 64
    assert verify_reconciliation(scenario, expectations, evidence)["mechanical_passed"] is False


def test_corrupt_expectations_are_provenance_error_not_agent_error():
    scenario, expectations, evidence = run_case()
    expectations["sources"][0]["source"]["status"] = "administered"
    result = verify_reconciliation(scenario, expectations, evidence)
    assert result["checks"]["provenance"] is False
    assert result["status"] == "provenance_error"


@pytest.mark.parametrize("argument", [0, 1, 2])
def test_malformed_top_level_inputs_return_diagnostics_without_raising(argument):
    inputs = list(run_case())
    inputs[argument] = None
    result = verify_reconciliation(*inputs)
    assert result["mechanical_passed"] is False
    assert result["status"] == "provenance_error"


def test_load_expectations_returns_detached_pinned_labels_and_failclosed_file_error(tmp_path):
    first = load_expectations()
    first["sources"].clear()
    assert len(load_expectations()["sources"]) == 8
    malformed = tmp_path / "bad.json"
    malformed.write_text('{"source":1,"source":2}')
    scenario, _, evidence = run_case()
    result = verify_reconciliation(scenario, load_expectations(malformed), evidence)
    assert result["status"] == "provenance_error"


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt_number", True),
        ("attempt_number", 0),
        ("idempotency_key", 7),
        ("error_code", []),
        ("result_summary", "unknown"),
    ],
)
def test_malformed_audit_metadata_fails_provenance(field, value):
    scenario, expectations, evidence = run_case()
    evidence["audit"][0][field] = value
    assert verify_reconciliation(scenario, expectations, evidence)["checks"]["provenance"] is False


def test_wrong_write_response_is_not_accepted_as_linked_action():
    scenario, expectations, evidence = run_case()
    evidence["calls"][3]["response"]["data"]["id"] = "ENC-BBBBBBBB"
    assert (
        verify_reconciliation(scenario, expectations, evidence)["checks"]["persisted_action"]
        is False
    )


def test_interrupted_attempt_after_write_retains_action_and_complete_denominator():
    scenario, expectations, evidence = run_case(completion="interrupted")
    index = len(evidence["audit"])
    evidence["calls"].append(
        {
            "id": "failed-readback",
            "name": "getEncounterDetails",
            "params": {"encounter_id": "ENC-AAAAAAAA"},
            "error": "RuntimeError: dispatch interrupted",
            "audit_start": index,
            "audit_end": index,
        }
    )
    result = verify_reconciliation(scenario, expectations, evidence)
    assert result["checks"]["provenance"] is True
    assert result["checks"]["persisted_action"] is True
    assert result["checks"]["execution_complete"] is False
    assert result["checks"]["readback"] is False


def test_missing_response_cannot_be_called_completed():
    scenario, expectations, evidence = run_case()
    del evidence["calls"][-1]["response"]
    result = verify_reconciliation(scenario, expectations, evidence)
    assert result["checks"]["provenance"] is False
    assert result["mechanical_passed"] is False


def test_forged_readback_without_the_note_does_not_count():
    scenario, expectations, evidence = run_case()
    evidence["calls"][-1]["response"]["data"]["clinical_notes"] = []
    result = verify_reconciliation(scenario, expectations, evidence)
    assert result["checks"]["persisted_action"] is True
    assert result["checks"]["readback"] is False


def test_sourced_note_written_before_retrieval_is_not_rehabilitated_by_retry():
    scenario, expectations, evidence = run_case(retry=True)
    # The note source content is valid, but its real successful action precedes
    # the recorded retrievals. Reorder both captured calls and matching audit.
    order = [3, 0, 1, 2, 4, 5]
    evidence["calls"] = [evidence["calls"][i] for i in order]
    evidence["audit"] = [evidence["audit"][i] for i in order]
    for index, call in enumerate(evidence["calls"]):
        call.update(audit_start=index, audit_end=index + 1)
    result = verify_reconciliation(scenario, expectations, evidence)
    assert result["checks"]["source_fidelity"] is False
    assert result["mechanical_passed"] is False


@pytest.mark.parametrize(
    "kind,identifier,field,value",
    [
        ("encounter", "ENC-AAAAAAAA", "chief_complaint", "invented complaint"),
        ("encounter", "ENC-CCCCCCCC", "arrival_time", "2026-09-30T14:30:00Z"),
        ("encounter", "ENC-AAAAAAAA", "arrival_time", "2028-01-01T00:00:00Z"),
        ("encounter", "ENC-CCCCCCCC", "esi_level", 3),
        ("encounter", "ENC-CCCCCCCC", "triage_time", "2026-09-30T14:30:00Z"),
        ("encounter", "ENC-CCCCCCCC", "vitals", [{"heart_rate": 70}]),
        ("encounter", "ENC-CCCCCCCC", "labs", [{"test_name": "invented", "value": 1}]),
        ("patient", "PAT-AAAAAAAA", "created_at", "2028-01-01T00:00:00Z"),
        ("patient", "PAT-BBBBBBBB", "updated_at", "2028-01-01T00:00:00Z"),
        ("encounter", "ENC-CCCCCCCC", "created_at", "2028-01-01T00:00:00Z"),
        ("encounter", "ENC-CCCCCCCC", "updated_at", "2028-01-01T00:00:00Z"),
    ],
)
def test_unaltered_but_wrong_initial_presentation_is_not_source_bound(
    kind, identifier, field, value
):
    scenario, expectations, evidence = run_case()
    # Corrupt the initial/final store and all corresponding actual-response
    # snapshots consistently: before/after comparison alone cannot detect it.
    for stage in ("before", "after"):
        evidence[stage]["entities"][kind][identifier][field] = deepcopy(value)
    for call in evidence["calls"]:
        data = call.get("response", {}).get("data")
        if isinstance(data, dict) and data.get("id") == identifier:
            data[field] = deepcopy(value)
    result = verify_reconciliation(scenario, expectations, evidence)
    assert result["checks"]["provenance"] is False
    assert result["mechanical_passed"] is False


@pytest.mark.parametrize("location", ["audit", "response"])
def test_success_with_contradictory_error_code_is_not_trusted(location):
    scenario, expectations, evidence = run_case()
    if location == "audit":
        evidence["audit"][3]["error_code"] = "permission_denied"
    else:
        evidence["calls"][3]["response"]["code"] = "permission_denied"
    result = verify_reconciliation(scenario, expectations, evidence)
    assert result["checks"]["provenance"] is False
    assert result["mechanical_passed"] is False


@pytest.mark.parametrize("field", ["arrival_time", "esi_level", "triage_time"])
def test_explicit_unknown_baseline_fields_cannot_disappear(field):
    scenario, expectations, evidence = run_case()
    for stage in ("before", "after"):
        del evidence[stage]["entities"]["encounter"]["ENC-CCCCCCCC"][field]
    for call in evidence["calls"]:
        data = call.get("response", {}).get("data", {})
        if data.get("id") == "ENC-CCCCCCCC":
            del data[field]
    assert verify_reconciliation(scenario, expectations, evidence)["checks"]["provenance"] is False
