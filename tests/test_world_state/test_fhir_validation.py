"""Fail-closed evidence parsing and sparse FHIR bundle link checks."""

from __future__ import annotations

from copy import deepcopy
from importlib import import_module

import pytest


@pytest.fixture
def validation():
    return import_module("healthcraft.world.fhir_validation")


@pytest.fixture
def provenance():
    return {
        "validator": {"version": "6.10.4", "sha256": "a" * 64},
        "fhir_version": "4.0.1",
        "packages": [{"name": "hl7.fhir.r4.core", "version": "4.0.1", "tree_sha256": "b" * 64}],
    }


def outcome(severity="information", code="informational", text="No errors reported"):
    return {
        "resourceType": "OperationOutcome",
        "issue": [{"severity": severity, "code": code, "details": {"text": text}}],
    }


@pytest.mark.parametrize("severity", ["error", "fatal"])
def test_errors_fail_even_when_java_exits_zero(validation, provenance, severity):
    result = validation.parse_validator_outcomes(
        outcome(severity, "invariant", "att-1 failed"), provenance=provenance
    )
    assert result["reported_checks_passed"] is False
    assert result["structural_fhirpath"]["status"] == "failed"
    assert result["severity_counts"][severity] == 1
    assert result["process_exit_code"] == 0


def test_positive_retains_warnings_without_claiming_terminology(validation, provenance):
    supplied = outcome("warning", "invariant", "dom-6 narrative recommended")
    result = validation.parse_validator_outcomes(supplied, provenance=provenance)
    assert result["reported_checks_passed"] is True
    assert result["structural_fhirpath"]["status"] == "no_errors_reported"
    assert result["terminology"]["status"] == "not_assessed"
    assert result["terminology"]["complete"] is False
    assert result["complete_conformance"] is False
    assert result["issues"][0]["issue"] == supplied["issue"][0]
    supplied["issue"][0]["details"]["text"] = "changed"
    provenance["validator"]["version"] = "changed"
    assert result["issues"][0]["issue"]["details"]["text"] != "changed"
    assert result["provenance"]["validator"]["version"] == "6.10.4"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        [],
        {"resourceType": "OperationOutcome"},
        {"resourceType": "OperationOutcome", "issue": []},
        {"resourceType": "OperationOutcome", "issue": [None]},
        {"resourceType": "OperationOutcome", "issue": [{"severity": "warning"}]},
        outcome("success"),
        {"resourceType": "Bundle", "type": "collection", "entry": []},
        {"resourceType": "Bundle", "type": "collection", "entry": [{}]},
        {"resourceType": "Patient", "issue": outcome()["issue"]},
    ],
)
def test_missing_or_malformed_output_fails_closed(validation, provenance, payload):
    result = validation.parse_validator_outcomes(payload, provenance=provenance)
    assert result["reported_checks_passed"] is False
    assert result["output_valid"] is False
    assert result["structural_fhirpath"]["status"] == "incomplete"
    assert result["errors"]


def test_multiple_outcomes_preserve_order_and_require_expected_count(validation, provenance):
    payload = {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [{"resource": outcome()}, {"resource": outcome("error", "required")}],
    }
    result = validation.parse_validator_outcomes(
        payload, provenance=provenance, expected_outcome_count=2
    )
    assert result["output_valid"] is True
    assert result["reported_checks_passed"] is False
    assert [row["outcome_index"] for row in result["issues"]] == [0, 1]
    truncated = validation.parse_validator_outcomes(
        [outcome()], provenance=provenance, expected_outcome_count=2
    )
    assert truncated["output_valid"] is False


def test_nonzero_process_exit_cannot_pass_good_output(validation, provenance):
    result = validation.parse_validator_outcomes(
        outcome(), provenance=provenance, process_exit_code=1
    )
    assert result["reported_checks_passed"] is False
    assert result["structural_fhirpath"]["status"] == "incomplete"


def test_explicit_incomplete_validation_cannot_pass(validation, provenance):
    result = validation.parse_validator_outcomes(
        outcome("warning", "incomplete", "Validation could not finish"), provenance=provenance
    )
    assert result["reported_checks_passed"] is False
    assert result["structural_fhirpath"]["status"] == "incomplete"


def test_terminology_issue_separated_and_never_hidden(validation, provenance):
    issue = outcome(
        "information", "code-invalid", "Value could not be checked without terminology server"
    )
    result = validation.parse_validator_outcomes(
        issue, provenance=provenance, terminology_enabled=True
    )
    assert result["structural_fhirpath"]["status"] == "no_errors_reported"
    assert result["terminology"]["status"] == "incomplete"
    assert result["terminology"]["complete"] is False
    assert result["issues"][0]["issue"] == issue["issue"][0]


def test_invalid_terminology_code_still_fails_overall(validation, provenance):
    result = validation.parse_validator_outcomes(
        outcome("error", "code-invalid", "DAR code not in required ValueSet"),
        provenance=provenance,
    )
    assert result["reported_checks_passed"] is False
    assert result["terminology"]["status"] == "failed"


@pytest.mark.parametrize("invalid", [None, {}, {"validator": {"version": "latest"}}])
def test_missing_pinned_provenance_is_incomplete(validation, invalid):
    result = validation.parse_validator_outcomes(outcome(), provenance=invalid)
    assert result["reported_checks_passed"] is False
    assert result["provenance_valid"] is False


def test_enabled_terminology_is_not_proof_of_complete_conformance(validation, provenance):
    result = validation.parse_validator_outcomes(
        outcome(), provenance=provenance, terminology_enabled=True
    )
    assert result["terminology"]["status"] == "no_errors_reported"
    assert result["complete_conformance"] is False


@pytest.fixture
def bundle():
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "fullUrl": "urn:uuid:00000000-0000-0000-0000-000000000001",
                "resource": {"resourceType": "Patient", "id": "one"},
            },
            {
                "fullUrl": "urn:uuid:00000000-0000-0000-0000-000000000002",
                "resource": {
                    "resourceType": "Encounter",
                    "id": "one",
                    "subject": {"reference": "Patient/one"},
                },
            },
            {
                "fullUrl": "urn:uuid:00000000-0000-0000-0000-000000000003",
                "resource": {
                    "resourceType": "DocumentReference",
                    "id": "one",
                    "subject": {"reference": "Patient/one"},
                    "context": {"encounter": [{"reference": "Encounter/one"}]},
                },
            },
        ],
    }


def test_bundle_links_are_only_links_not_fhir_conformance(validation, bundle):
    result = validation.validate_sparse_bundle_links(bundle)
    assert result["valid"] is True
    assert result["resource_counts"] == {"Patient": 1, "Encounter": 1, "DocumentReference": 1}
    assert result["complete_conformance"] is False
    # These fixture resources deliberately omit unrelated required FHIR fields.
    assert "status" not in bundle["entry"][1]["resource"]


def test_matching_fullurl_references_are_supported(validation, bundle):
    patient, encounter, document = bundle["entry"]
    encounter["resource"]["subject"]["reference"] = patient["fullUrl"]
    document["resource"]["subject"]["reference"] = patient["fullUrl"]
    document["resource"]["context"]["encounter"][0]["reference"] = encounter["fullUrl"]
    assert validation.validate_sparse_bundle_links(bundle)["valid"] is True


@pytest.mark.parametrize("mutation", ["fullurl", "resource_id", "duplicate_entry"])
def test_duplicate_identity_is_rejected(validation, bundle, mutation):
    if mutation == "fullurl":
        bundle["entry"][1]["fullUrl"] = bundle["entry"][0]["fullUrl"]
    else:
        extra = deepcopy(bundle["entry"][0])
        if mutation == "resource_id":
            extra["fullUrl"] = "urn:uuid:00000000-0000-0000-0000-000000000004"
        bundle["entry"].append(extra)
    assert validation.validate_sparse_bundle_links(bundle)["valid"] is False


@pytest.mark.parametrize("role", ["encounter", "document", "context"])
def test_unresolved_or_wrong_reference_type_is_rejected(validation, bundle, role):
    enc = bundle["entry"][1]["resource"]
    doc = bundle["entry"][2]["resource"]
    if role == "encounter":
        enc["subject"]["reference"] = "Patient/missing"
    elif role == "document":
        doc["subject"]["reference"] = "Encounter/one"
    else:
        doc["context"]["encounter"][0]["reference"] = "Patient/one"
    assert validation.validate_sparse_bundle_links(bundle)["valid"] is False


def test_document_and_encounter_must_have_same_patient(validation, bundle):
    bundle["entry"].append(
        {
            "fullUrl": "urn:uuid:00000000-0000-0000-0000-000000000004",
            "resource": {"resourceType": "Patient", "id": "two"},
        }
    )
    bundle["entry"][2]["resource"]["subject"]["reference"] = "Patient/two"
    result = validation.validate_sparse_bundle_links(bundle)
    assert result["valid"] is False
    assert any("patient" in error.lower() for error in result["errors"])


def test_other_nested_references_must_also_resolve(validation, bundle):
    bundle["entry"][2]["resource"]["author"] = [{"reference": "Patient/missing"}]
    assert validation.validate_sparse_bundle_links(bundle)["valid"] is False


@pytest.mark.parametrize(
    "bad", [None, {}, {"resourceType": "Bundle", "type": "collection", "entry": []}]
)
def test_malformed_bundle_fails_closed(validation, bad):
    result = validation.validate_sparse_bundle_links(bad)
    assert result["valid"] is False
    assert result["errors"]


def test_missing_context_or_unsupported_resources_cannot_pass(validation, bundle):
    bundle["entry"][2]["resource"].pop("context")
    assert validation.validate_sparse_bundle_links(bundle)["valid"] is False
    bundle["entry"][0]["resource"]["resourceType"] = "Practitioner"
    assert validation.validate_sparse_bundle_links(bundle)["valid"] is False
