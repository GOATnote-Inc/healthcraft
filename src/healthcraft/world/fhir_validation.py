"""Parse independent validator evidence and check sparse export references.

This module does not execute or authenticate a validator, validate all FHIR
profiles, or assess clinical correctness. Supplied provenance records pins;
it is not proof that those artifacts produced the supplied outcomes.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

_SEVERITIES = {"fatal", "error", "warning", "information"}
_HASH = re.compile(r"[0-9a-fA-F]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9.-]{1,64}\Z")
_RESOURCE_TYPES = {"Patient", "Encounter", "DocumentReference"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _json_copy(value: Any) -> Any:
    """Reject Python-only or nonfinite data rather than emitting non-JSON reports."""
    json.dumps(value, allow_nan=False)
    return deepcopy(value)


def _pin(value: Any) -> bool:
    return isinstance(value, str) and bool(_HASH.fullmatch(value))


def _check_provenance(provenance: Any) -> None:
    _require(isinstance(provenance, dict), "Pinned provenance must be an object")
    validator = provenance.get("validator")
    _require(isinstance(validator, dict), "Missing pinned validator provenance")
    version = validator.get("version")
    _require(
        isinstance(version, str) and bool(re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][\w.-]+)?", version)),
        "Validator version must be pinned",
    )
    _require(_pin(validator.get("sha256")), "Missing validator SHA-256")
    _require(provenance.get("fhir_version") == "4.0.1", "Only FHIR R4 4.0.1 is supported")
    packages = provenance.get("packages")
    _require(isinstance(packages, list) and bool(packages), "Missing pinned package manifest")
    identities = set()
    for package in packages:
        _require(isinstance(package, dict), "Package pin must be an object")
        name, version = package.get("name"), package.get("version")
        _require(
            isinstance(name, str)
            and bool(name.strip())
            and isinstance(version, str)
            and bool(version.strip())
            and version not in {"latest", "current"},
            "Each package needs a pinned name and version",
        )
        digest = package.get("sha256", package.get("tree_sha256"))
        _require(_pin(digest), "Each package needs a SHA-256 content pin")
        if "sha256" in package and "tree_sha256" in package:
            _require(package["sha256"] == package["tree_sha256"], "Ambiguous package hash pins")
        _require((name, version) not in identities, "Duplicate package pin")
        identities.add((name, version))
    _require(("hl7.fhir.r4.core", "4.0.1") in identities, "Missing pinned R4 core package")


def _outcomes(payload: Any) -> list[dict]:
    if isinstance(payload, dict) and payload.get("resourceType") == "OperationOutcome":
        return [payload]
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and payload.get("resourceType") == "Bundle":
        _require(payload.get("type") == "collection", "Outcome Bundle must be a collection")
        entries = payload.get("entry")
        _require(isinstance(entries, list) and bool(entries), "Outcome Bundle has no entries")
        _require(
            all(isinstance(entry, dict) and "resource" in entry for entry in entries),
            "Malformed outcome Bundle entry",
        )
        return [entry["resource"] for entry in entries]
    raise ValueError("Expected OperationOutcome, outcome list, or collection Bundle")


def _check_issue(issue: Any) -> None:
    _require(isinstance(issue, dict), "Outcome issue must be an object")
    _require(issue.get("severity") in _SEVERITIES, "Unknown or missing issue severity")
    _require(
        isinstance(issue.get("code"), str) and bool(issue["code"].strip()),
        "Missing issue code",
    )
    if "details" in issue:
        _require(isinstance(issue["details"], dict), "Issue details must be an object")
    if "diagnostics" in issue:
        _require(isinstance(issue["diagnostics"], str), "Issue diagnostics must be text")
    for key in ("expression", "location"):
        if key in issue:
            _require(
                isinstance(issue[key], list) and all(isinstance(item, str) for item in issue[key]),
                f"Issue {key} must be a text list",
            )
    if "extension" in issue:
        _require(
            isinstance(issue["extension"], list)
            and all(isinstance(item, dict) for item in issue["extension"]),
            "Issue extensions must be objects",
        )


def _is_terminology(issue: dict) -> bool:
    if issue["code"] == "code-invalid":
        return True
    for extension in issue.get("extension", []):
        url = extension.get("url", "")
        value = extension.get("valueString", extension.get("valueCode", ""))
        if isinstance(url, str) and isinstance(value, str):
            if url.endswith("operationoutcome-issue-source") and "Terminology" in value:
                return True
            if url.endswith("operationoutcome-message-id") and value.startswith("Terminology_"):
                return True
    return False


def parse_validator_outcomes(
    payload: Any,
    *,
    provenance: Any,
    expected_outcome_count: int = 1,
    process_exit_code: int = 0,
    terminology_enabled: bool = False,
) -> dict:
    """Fail closed on missing evidence; preserve every validator issue.

    ``reported_checks_passed`` means that well-formed, pinned output reported
    no errors and the process exited successfully. It does not establish that
    all checks ran. Even with terminology enabled, this parser cannot attest
    complete conformance. Callers must bind input/output hashes and execution
    provenance independently; an expected count catches truncated batches.
    """
    errors: list[str] = []
    issues: list[dict] = []
    count = 0
    output_valid = provenance_valid = True
    saved_provenance = None
    try:
        saved_provenance = _json_copy(provenance)
        _check_provenance(saved_provenance)
    except (TypeError, ValueError, RecursionError) as exc:
        provenance_valid = False
        errors.append(f"Invalid provenance: {exc}")
    try:
        _require(
            type(expected_outcome_count) is int and expected_outcome_count > 0,
            "expected_outcome_count must be a positive integer",
        )
        values = _outcomes(_json_copy(payload))
        count = len(values)
        _require(count == expected_outcome_count, "Outcome count does not match expected count")
        for index, value in enumerate(values):
            _require(
                isinstance(value, dict) and value.get("resourceType") == "OperationOutcome",
                "Every result must be an OperationOutcome",
            )
            rows = value.get("issue")
            _require(isinstance(rows, list) and bool(rows), "OperationOutcome has no issues")
            for issue in rows:
                _check_issue(issue)
                issues.append({"outcome_index": index, "issue": issue})
    except (TypeError, ValueError, RecursionError) as exc:
        output_valid = False
        errors.append(f"Invalid validator output: {exc}")

    process_ok = type(process_exit_code) is int and process_exit_code == 0
    if not process_ok:
        errors.append("Validator process did not report exit code 0")
    if type(terminology_enabled) is not bool:
        errors.append("terminology_enabled must be a boolean")
        output_valid = False
        terminology_enabled = False
    counts = Counter(row["issue"]["severity"] for row in issues)
    term_issues = [row for row in issues if _is_terminology(row["issue"])]
    structural_issues = [row for row in issues if not _is_terminology(row["issue"])]

    def failed(rows: list[dict]) -> bool:
        return any(row["issue"]["severity"] in {"fatal", "error"} for row in rows)

    explicitly_incomplete = any(row["issue"]["code"] == "incomplete" for row in issues)
    if explicitly_incomplete:
        errors.append("Validator explicitly reported incomplete validation")
    evidence_complete = (
        output_valid and provenance_valid and process_ok and not explicitly_incomplete
    )
    structural_status = "no_errors_reported"
    if failed(structural_issues):
        structural_status = "failed"
    elif not evidence_complete:
        structural_status = "incomplete"
    term_status = "no_errors_reported"
    if failed(term_issues):
        term_status = "failed"
    elif not terminology_enabled:
        term_status = "not_assessed"
    elif not evidence_complete or term_issues:
        term_status = "incomplete"
    return {
        "scope": "reported_validator_evidence",
        "reported_checks_passed": evidence_complete and not failed(issues),
        "output_valid": output_valid,
        "provenance_valid": provenance_valid,
        "provenance": saved_provenance,
        "provenance_authenticated": False,
        "outcome_count": count,
        "expected_outcome_count": expected_outcome_count,
        "process_exit_code": process_exit_code,
        "severity_counts": {severity: counts[severity] for severity in sorted(_SEVERITIES)},
        "issues": issues,
        "structural_fhirpath": {"status": structural_status, "issues": structural_issues},
        "terminology": {
            "enabled": terminology_enabled,
            "status": term_status,
            "complete": False,
            "issues": term_issues,
        },
        "complete_conformance": False,
        "clinical_validation": False,
        "errors": errors,
    }


def validate_sparse_bundle_links(bundle: Any) -> dict:
    """Check identity, closure and patient ownership for the supported export shape.

    This is not a resource-schema or FHIRPath validator. FHIR resource IDs are
    type-scoped, so Patient/x and Encounter/x are distinct valid identities.
    """
    counts: Counter = Counter()
    errors: list[str] = []
    try:
        _require(
            isinstance(bundle, dict)
            and bundle.get("resourceType") == "Bundle"
            and bundle.get("type") == "collection",
            "Expected a collection Bundle",
        )
        entries = bundle.get("entry")
        _require(isinstance(entries, list) and bool(entries), "Bundle must have entries")
        by_url: dict[str, dict] = {}
        by_identity: dict[str, dict] = {}
        resources = []
        for entry in entries:
            _require(isinstance(entry, dict), "Bundle entry must be an object")
            full_url, resource = entry.get("fullUrl"), entry.get("resource")
            _require(
                isinstance(full_url, str)
                and bool(urlsplit(full_url).scheme)
                and not any(char.isspace() for char in full_url)
                and not urlsplit(full_url).fragment,
                "Entry fullUrl must be an absolute URI without a fragment",
            )
            _require(full_url not in by_url, "Duplicate entry fullUrl")
            _require(isinstance(resource, dict), "Entry resource must be an object")
            kind, rid = resource.get("resourceType"), resource.get("id")
            _require(kind in _RESOURCE_TYPES, "Unsupported sparse resource type")
            _require(isinstance(rid, str) and bool(_ID.fullmatch(rid)), "Invalid resource ID")
            identity = f"{kind}/{rid}"
            _require(identity not in by_identity, f"Duplicate resource identity: {identity}")
            by_url[full_url] = by_identity[identity] = resource
            resources.append(resource)
            counts[kind] += 1
        _require(all(counts[kind] for kind in _RESOURCE_TYPES), "Missing sparse resource type")

        def resolve(reference: Any, expected: str | None = None) -> dict:
            _require(isinstance(reference, str), "Reference must be a literal string")
            resource = by_url.get(reference, by_identity.get(reference))
            _require(resource is not None, f"Unresolved reference: {reference}")
            if expected:
                _require(resource["resourceType"] == expected, f"Reference must target {expected}")
            return resource

        def check_all_references(value: Any) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == "reference":
                        resolve(item)
                    else:
                        check_all_references(item)
            elif isinstance(value, list):
                for item in value:
                    check_all_references(item)

        def subject(resource: dict) -> dict:
            value = resource.get("subject")
            _require(isinstance(value, dict), "Resource needs a patient subject reference")
            return resolve(value.get("reference"), "Patient")

        for resource in resources:
            check_all_references(resource)
            if resource["resourceType"] == "Encounter":
                subject(resource)
            if resource["resourceType"] == "DocumentReference":
                patient = subject(resource)
                context = resource.get("context")
                _require(isinstance(context, dict), "DocumentReference needs encounter context")
                links = context.get("encounter")
                _require(isinstance(links, list) and bool(links), "Missing encounter context links")
                linked = set()
                for link in links:
                    _require(isinstance(link, dict), "Encounter context link must be an object")
                    encounter = resolve(link.get("reference"), "Encounter")
                    _require(encounter["id"] not in linked, "Duplicate encounter context link")
                    linked.add(encounter["id"])
                    _require(
                        subject(encounter)["id"] == patient["id"],
                        "DocumentReference and Encounter must have the same patient",
                    )
    except (TypeError, ValueError, RecursionError) as exc:
        errors.append(str(exc))
    return {
        "scope": "sparse_bundle_identity_and_references",
        "valid": not errors,
        "resource_counts": dict(counts),
        "errors": errors,
        "complete_conformance": False,
        "clinical_validation": False,
    }
