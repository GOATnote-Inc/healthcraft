"""Source-preserving FHIR export, distinct from clinical or retrieval grading."""

from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from healthcraft.tasks.loader import load_task
from healthcraft.tasks.roster_execution import TASK_PATHS
from healthcraft.tasks.roster_profile import build_roster_profile, roster_contract
from healthcraft.world.state import WorldState

ROOT = Path(__file__).resolve().parents[2]


def scenario(task_id="CC-022"):
    task = load_task(ROOT / "configs/tasks" / TASK_PATHS[task_id])
    world = WorldState()
    return task, build_roster_profile(world, task), world


def export(args):
    from healthcraft.world.fhir_projection import export_roster_sources

    return export_roster_sources(*args)


def documents(report):
    return [
        entry["resource"]
        for entry in report["bundle"]["entry"]
        if entry["resource"]["resourceType"] == "DocumentReference"
    ]


@pytest.mark.parametrize("task_id,count", zip(TASK_PATHS, [4, 3, 7, 7, 7, 5], strict=True))
def test_all_33_source_records_preserve_exact_selected_facts_and_patient_ownership(task_id, count):
    task, context, world = args = scenario(task_id)
    report = export(args)
    bundle = report["bundle"]
    assert bundle["resourceType"] == "Bundle" and bundle["type"] == "collection"
    assert len(bundle["entry"]) == count * 3
    by_url = {entry["fullUrl"]: entry["resource"] for entry in bundle["entry"]}
    assert len(by_url) == count * 3
    for document, member in zip(documents(report), context["roster"], strict=True):
        patient = by_url[document["subject"]["reference"]]
        encounter = by_url[document["context"]["encounter"][0]["reference"]]
        assert patient == {"resourceType": "Patient", "id": member["patient_id"]}
        assert encounter["id"] == member["encounter_id"]
        assert encounter["subject"] == document["subject"]
        assert encounter["status"] == "unknown"
        assert encounter["class"] == {
            "extension": [
                {
                    "url": "http://hl7.org/fhir/StructureDefinition/data-absent-reason",
                    "valueCode": "unknown",
                }
            ]
        }
        assert set(encounter) == {"resourceType", "id", "status", "class", "subject"}
        attachment = document["content"][0]["attachment"]
        assert attachment["contentType"] == "application/json"
        payload = json.loads(base64.b64decode(attachment["data"], validate=True))
        collection, index = member["source_path"].split("/")
        contract = next(row for row in roster_contract(task_id) if row[0] == collection)
        source = task.source_data[collection][int(index)]
        expected = {key: source[key] for key in contract[4] if key in source}
        assert payload["authored_observations"] == expected
        assert payload["source_identity"] == {"field": contract[2], "value": source[contract[2]]}
        for key in ("source_path", "source_context", "patient_id", "encounter_id"):
            assert payload[key] == member[key]
        assert payload["source_sha256"] == context["source_sha256"]
        assert payload["contract_sha256"] == context["contract_sha256"]
        assert payload["clinical_validation"] == "not_assessed"
        assert document["status"] == "current" and "docStatus" not in document
        assert not set(contract[5]) & payload["authored_observations"].keys()
    assert report["benchmark_score"] is None
    assert report["grading_complete"] is False
    assert report["coverage"]["measured_clinical_criteria"] == 0
    assert report["coverage"]["measured_safety_criteria"] == 0
    assert report["coverage"]["unassessed_criteria"] == [c["id"] for c in task.criteria]
    assert report["validation"]["source_fidelity"] == "passed"
    assert report["validation"]["structural_fhirpath"] == "not_run"
    assert report["validation"]["terminology"] == "not_run"
    assert report["validation"]["conformance_complete"] is False
    assert report["validation"]["reference_closure"] == "passed"
    encoded = json.dumps(bundle, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    assert report["bundle_sha256"] == hashlib.sha256(encoded).hexdigest()
    assert world.audit_log == []  # Export cannot count as agent retrieval.


def test_deterministic_export_has_no_aliases_or_source_mutations():
    task, context, world = args = scenario()
    source_before, context_before = deepcopy(task.source_data), deepcopy(context)
    patient = world.get_entity("patient", context["roster"][0]["patient_id"])
    patient_before = deepcopy(patient)
    first = export(args)
    expected = deepcopy(first)
    first["bundle"]["entry"][0]["resource"]["id"] = "changed"
    first["coverage"]["unassessed_criteria"].clear()
    assert export(args) == expected
    assert task.source_data == source_before and context == context_before
    assert patient == patient_before


@pytest.mark.parametrize("kind", ["patient", "encounter"])
@pytest.mark.parametrize("change", ["facts", "link", "provenance"])
def test_discordant_world_cannot_export_faithful_sources(kind, change):
    _, context, world = args = scenario()
    record = world.get_entity(kind, context["roster"][0][f"{kind}_id"])
    if change == "facts":
        record["authored_observations"]["summary"] = "Invented facts"
    elif change == "link":
        record["id"] = "PAT-000000000000"
    else:
        record["source_path"] = "wrong/0"
    with pytest.raises(ValueError, match="source"):
        export(args)


def test_changed_authored_source_and_incomplete_context_fail_closed():
    task, context, world = scenario()
    changed = deepcopy(task.source_data)
    changed["patients_requiring_action"][0]["summary"] = "Changed source"
    with pytest.raises(ValueError, match="hash"):
        export((replace(task, source_data=changed), context, world))
    context["roster"].pop()
    with pytest.raises(ValueError, match="every"):
        export((task, context, world))


def test_cross_patient_encounter_link_cannot_export():
    _, context, world = args = scenario()
    first, second = context["roster"][:2]
    world.get_entity("encounter", first["encounter_id"])["patient_id"] = second["patient_id"]
    with pytest.raises(ValueError, match="source"):
        export(args)


def test_reference_validation_failure_is_enforced(monkeypatch):
    from healthcraft.world import fhir_validation

    monkeypatch.setattr(
        fhir_validation,
        "validate_sparse_bundle_links",
        lambda bundle: {"valid": False, "errors": ["Invalid links"]},
    )
    with pytest.raises(ValueError, match="invalid source links"):
        export(scenario())


def test_export_scope_excludes_agent_notes_and_unreviewed_world_enrichment():
    _, context, world = args = scenario()
    member = context["roster"][0]
    world.get_entity("patient", member["patient_id"])["gender"] = "invented"
    world.get_entity("encounter", member["encounter_id"])["clinical_notes"] = ["UNREVIEWED-NOTE-17"]
    report = export(args)
    assert "UNREVIEWED-NOTE-17" not in json.dumps(report) and "invented" not in json.dumps(report)
    assert "not a world snapshot" in report["limitations"]


def test_no_null_or_empty_fhir_placeholders_and_no_arrival_or_demographic_inference():
    report = export(scenario("IR-025"))  # Has source age/sex, but no verified DOB/gender.

    def walk(value):
        assert value is not None and value not in ("", [], {})
        if isinstance(value, dict):
            assert not {"period", "birthDate", "gender", "arrival_time"} & value.keys()
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(report["bundle"])
