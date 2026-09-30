"""Additive FHIR R4 source-document view of the reviewed roster profile.

This is deliberately not a general WorldState converter. Sparse identity shells
and a linked DocumentReference preserve reviewed source observations without
turning source prose into verified diagnoses, demographics or encounter times.
"""

from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from healthcraft.tasks.loader import Task
from healthcraft.tasks.roster_certificate import verify_roster_retrieval
from healthcraft.world.state import WorldState

REPRESENTATION_VERSION = "roster-source-fhir/v1"
_ABSENT_REASON = "http://hl7.org/fhir/StructureDefinition/data-absent-reason"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _url(resource_type: str, resource_id: str) -> str:
    identity = f"healthcraft:{REPRESENTATION_VERSION}:{resource_type}/{resource_id}"
    return f"urn:uuid:{uuid5(NAMESPACE_URL, identity)}"


def export_roster_sources(task: Task, context: dict, world: WorldState) -> dict:
    """Return a deterministic, independent export; never modify source/world.

    Only the six reviewed roster tasks are supported. Independent source checks
    reject stale context, wrong membership, changed facts and broken patient links.
    No audit/tool evidence is generated. Official FHIR validation is a separate
    operation, explicitly not_run in this envelope, even if a prior export passed.
    The caller must prevent concurrent world mutations during this synchronous call.
    """
    from healthcraft.world.fhir_validation import validate_sparse_bundle_links

    certificate = verify_roster_retrieval(task, context, [], world)
    if not certificate["checks"]["final_world_source_concordant"]:
        raise ValueError("World records do not match the reviewed authored source")
    entries = []
    documents = []
    for member in context["roster"]:
        record = world.get_entity("encounter", member["encounter_id"])
        payload = {
            "representation_version": REPRESENTATION_VERSION,
            "profile_version": context["profile_version"],
            "task_id": task.id,
            **{
                key: deepcopy(member[key])
                for key in ("patient_id", "encounter_id", "source_path", "source_context")
            },
            "source_identity": deepcopy(record["source_identity"]),
            "authored_observations": deepcopy(record["authored_observations"]),
            "source_sha256": context["source_sha256"],
            "contract_sha256": context["contract_sha256"],
            "clinical_validation": "not_assessed",
        }
        content_sha256 = _digest(payload)
        # Content-bound document identity differs if a reviewed source changes.
        document_id = f"SRC-{content_sha256[:56]}"
        patient_url = _url("Patient", member["patient_id"])
        encounter_url = _url("Encounter", member["encounter_id"])
        resources = [
            {"resourceType": "Patient", "id": member["patient_id"]},
            {
                "resourceType": "Encounter",
                "id": member["encounter_id"],
                "status": "unknown",
                "class": {"extension": [{"url": _ABSENT_REASON, "valueCode": "unknown"}]},
                "subject": {"reference": patient_url},
            },
            {
                "resourceType": "DocumentReference",
                "id": document_id,
                "status": "current",
                "subject": {"reference": patient_url},
                "context": {"encounter": [{"reference": encounter_url}]},
                "content": [
                    {
                        "attachment": {
                            "contentType": "application/json",
                            "data": base64.b64encode(_canonical(payload)).decode("ascii"),
                        }
                    }
                ],
            },
        ]
        entries.extend(
            {"fullUrl": _url(resource["resourceType"], resource["id"]), "resource": resource}
            for resource in resources
        )
        documents.append(
            {
                "document_id": document_id,
                "source_path": member["source_path"],
                "content_sha256": content_sha256,
            }
        )
    bundle = {
        "resourceType": "Bundle",
        "id": f"SRC-{_digest(entries)[:56]}",
        "type": "collection",
        "entry": entries,
    }
    links = validate_sparse_bundle_links(bundle)
    if not links["valid"]:
        raise ValueError(f"Export has invalid source links: {links['errors']}")
    return {
        "representation_version": REPRESENTATION_VERSION,
        "fhir_version": "4.0.1",
        "profile_version": context["profile_version"],
        "task_id": task.id,
        "source_sha256": context["source_sha256"],
        "contract_sha256": context["contract_sha256"],
        "bundle": bundle,
        "bundle_sha256": _digest(bundle),
        "documents": documents,
        "benchmark_score": None,
        "benchmark_comparable": False,
        "grading_complete": False,
        "coverage": {
            "source_members": len(documents),
            "resource_count": len(entries),
            "measured_clinical_criteria": 0,
            "measured_safety_criteria": 0,
            "unassessed_criteria": [criterion["id"] for criterion in task.criteria],
        },
        "validation": {
            "source_fidelity": "passed",
            "reference_closure": "passed",
            "structural_fhirpath": "not_run",
            "terminology": "not_run",
            "conformance_complete": False,
        },
        "limitations": (
            "Reviewed source observations only; not a world snapshot or clinical record. "
            "Agent notes, generated seed facts, withheld answer fields and unreviewed enrichment "
            "are excluded. Source claims remain unverified. Patient demographics, encounter "
            "class, status and arrival are not inferred. This exporter does not run an official "
            "FHIR validator or establish clinical validity, safety, interoperability with an "
            "implementation guide, or benchmark performance. Hashes detect content drift, "
            "not authenticity. Other entity types and linked-history profiles are unsupported."
        ),
    }
