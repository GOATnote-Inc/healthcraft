"""Read-only MCP tool handlers for the HEALTHCRAFT ED simulation.

Implements 12 search/get tools (Wave 1). Each function takes
(world: WorldState, params: dict) -> dict and returns a response envelope
with status "ok" or "error".

Corecraft noise: search tools return MAX 10 results with no hasMore signal.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

_MAX_RESULTS = 10  # Pagination limit (Corecraft noise: no hasMore signal)


def _serialize(entity: Any) -> dict:
    """Serialize a dataclass or dict entity to dict."""
    if hasattr(entity, "__dataclass_fields__"):
        return asdict(entity)
    if isinstance(entity, dict):
        return entity
    return {"value": str(entity)}


def _get(entity, field, default=None):
    """Get a field from a dataclass or dict entity."""
    if isinstance(entity, dict):
        return entity.get(field, default)
    return getattr(entity, field, default)


def _ok(data):
    """Build a success response."""
    return {"status": "ok", "data": data}


def _error(code, message):
    """Build an error response."""
    return {"status": "error", "code": code, "message": message}


def _matches_substring(value, query):
    """Case-insensitive substring match. Returns False if either is None."""
    if value is None or query is None:
        return False
    return query.lower() in str(value).lower()


# ---------------------------------------------------------------------------
# 1. searchEncounters
# ---------------------------------------------------------------------------


def search_encounters(world, params):
    """Search encounters with optional filters.

    Params:
        patient_id, date_range, chief_complaint, esi_level, disposition, limit
    """
    encounters = world.list_entities("encounter")
    patient_id = params.get("patient_id")
    chief_complaint = params.get("chief_complaint")
    esi_level = params.get("esi_level")
    disposition = params.get("disposition")
    limit = min(params.get("limit", _MAX_RESULTS), _MAX_RESULTS)

    results = []
    for eid, enc in encounters.items():
        if patient_id and _get(enc, "patient_id") != patient_id:
            continue
        if chief_complaint and not _matches_substring(
            _get(enc, "chief_complaint"), chief_complaint
        ):
            continue
        if esi_level is not None and _get(enc, "esi_level") != esi_level:
            continue
        if disposition and _get(enc, "disposition") != disposition:
            continue

        results.append(
            {
                "id": eid,
                "patient_id": _get(enc, "patient_id"),
                "chief_complaint": _get(enc, "chief_complaint"),
                "esi_level": _get(enc, "esi_level"),
                "arrival_time": _get(enc, "arrival_time"),
                "disposition": _get(enc, "disposition"),
            }
        )
        if len(results) >= limit:
            break

    return _ok(results)


# ---------------------------------------------------------------------------
# 2. searchPatients
# ---------------------------------------------------------------------------


def search_patients(world, params):
    """Search patients by name substring, MRN, or DOB.

    Params:
        query, name, mrn, date_of_birth
    """
    patients = world.list_entities("patient")
    query = params.get("query")
    name = params.get("name")
    mrn = params.get("mrn")
    dob = params.get("date_of_birth")

    results = []
    for pid, pat in patients.items():
        if mrn and _get(pat, "mrn") != mrn:
            continue
        if dob and str(_get(pat, "dob", _get(pat, "date_of_birth"))) != str(dob):
            continue
        if name:
            full_name = f"{_get(pat, 'first_name', '')} {_get(pat, 'last_name', '')}"
            if not _matches_substring(full_name, name):
                continue
        if query:
            full_name = f"{_get(pat, 'first_name', '')} {_get(pat, 'last_name', '')}"
            mrn_val = str(_get(pat, "mrn", ""))
            if not (_matches_substring(full_name, query) or _matches_substring(mrn_val, query)):
                continue

        results.append(
            {
                "id": pid,
                "mrn": _get(pat, "mrn"),
                "first_name": _get(pat, "first_name"),
                "last_name": _get(pat, "last_name"),
                "dob": _get(pat, "dob", _get(pat, "date_of_birth")),
                "sex": _get(pat, "sex"),
            }
        )
        if len(results) >= _MAX_RESULTS:
            break

    return _ok(results)


# ---------------------------------------------------------------------------
# 3. searchClinicalKnowledge
# ---------------------------------------------------------------------------


def search_clinical_knowledge(world, params):
    """Search clinical knowledge by query, category, or condition_id.

    Params:
        query, category, condition_id
    """
    knowledge = world.list_entities("clinical_knowledge")
    query = params.get("query")
    category = params.get("category")
    condition_id = params.get("condition_id")

    results = []
    for kid, ck in knowledge.items():
        if condition_id and _get(ck, "condition_id") != condition_id:
            continue
        if category and _get(ck, "category") != category:
            continue
        if query:
            name = _get(ck, "condition_name", _get(ck, "name", ""))
            if not _matches_substring(name, query):
                continue

        results.append(
            {
                "id": kid,
                "condition_id": _get(ck, "condition_id"),
                "condition_name": _get(ck, "condition_name", _get(ck, "name")),
                "category": _get(ck, "category"),
                "esi": _get(ck, "esi"),
            }
        )
        if len(results) >= _MAX_RESULTS:
            break

    return _ok(results)


# ---------------------------------------------------------------------------
# 4. searchReferenceMaterials
# ---------------------------------------------------------------------------


def search_reference_materials(world, params):
    """Search reference materials by keyword, type, category, or drug_name.

    Params:
        query, material_type, category, drug_name
    """
    materials = world.list_entities("reference_material")
    query = params.get("query")
    material_type = params.get("material_type")
    category = params.get("category")
    drug_name = params.get("drug_name")

    results = []
    for rid, ref in materials.items():
        if material_type and _get(ref, "material_type") != material_type:
            continue
        if category and _get(ref, "category") != category:
            continue
        if drug_name and not _matches_substring(_get(ref, "drug_name"), drug_name):
            continue
        if query:
            title = str(_get(ref, "title", ""))
            keywords = str(_get(ref, "keywords", ""))
            if not (_matches_substring(title, query) or _matches_substring(keywords, query)):
                continue

        results.append(
            {
                "id": rid,
                "title": _get(ref, "title"),
                "material_type": _get(ref, "material_type"),
                "category": _get(ref, "category"),
            }
        )
        if len(results) >= _MAX_RESULTS:
            break

    return _ok(results)


# ---------------------------------------------------------------------------
# 5. searchAvailableResources
# ---------------------------------------------------------------------------


def search_available_resources(world, params):
    """Search ED resources by type, zone, or status.

    Params:
        resource_type, zone, status (default: "available")
    """
    resources = world.list_entities("resource")
    resource_type = params.get("resource_type")
    zone = params.get("zone")
    status = params.get("status", "available")

    results = []
    for rid, res in resources.items():
        if status and _get(res, "status") != status:
            continue
        if resource_type and _get(res, "resource_type") != resource_type:
            continue
        if zone and _get(res, "zone") != zone:
            continue

        results.append(
            {
                "id": rid,
                "name": _get(res, "name"),
                "resource_type": _get(res, "resource_type"),
                "zone": _get(res, "zone"),
                "status": _get(res, "status"),
            }
        )
        if len(results) >= _MAX_RESULTS:
            break

    return _ok(results)


# ---------------------------------------------------------------------------
# 6. getEncounterDetails
# ---------------------------------------------------------------------------


def get_encounter_details(world, params):
    """Return full encounter details including vitals, labs, imaging, meds.

    Params:
        encounter_id (required)
    """
    encounter_id = params.get("encounter_id")
    if not encounter_id:
        return _error("invalid_params", "encounter_id is required")

    encounter = world.get_entity("encounter", encounter_id)
    if encounter is None:
        return _error("not_found", f"Encounter {encounter_id} not found")

    return _ok(_serialize(encounter))


# ---------------------------------------------------------------------------
# 7. getConditionDetails
# ---------------------------------------------------------------------------


def get_condition_details(world, params):
    """Return full clinical knowledge for a condition.

    Tries with "CK-" prefix first, then the raw condition_id.

    Params:
        condition_id (required)
    """
    condition_id = params.get("condition_id")
    if not condition_id:
        return _error("invalid_params", "condition_id is required")

    # Try with CK- prefix first
    prefixed = f"CK-{condition_id}" if not condition_id.startswith("CK-") else condition_id
    entity = world.get_entity("clinical_knowledge", prefixed)

    # Fall back to raw ID
    if entity is None:
        entity = world.get_entity("clinical_knowledge", condition_id)

    # Fall back to searching by condition_id field
    if entity is None:
        for _, ck in world.list_entities("clinical_knowledge").items():
            if _get(ck, "condition_id") == condition_id:
                entity = ck
                break

    if entity is None:
        return _error("not_found", f"Condition {condition_id} not found")

    return _ok(_serialize(entity))


# ---------------------------------------------------------------------------
# 8. getPatientHistory
# ---------------------------------------------------------------------------


def get_patient_history(world, params):
    """Return patient details plus allergies, medications, encounters, insurance.

    Params:
        patient_id (required)
    """
    patient_id = params.get("patient_id")
    if not patient_id:
        return _error("invalid_params", "patient_id is required")

    patient = world.get_entity("patient", patient_id)
    if patient is None:
        return _error("not_found", f"Patient {patient_id} not found")

    data = _serialize(patient)

    # Collect allergies for this patient
    allergies = []
    for _, allergy in world.list_entities("allergy").items():
        if _get(allergy, "patient_id") == patient_id:
            allergies.append(_serialize(allergy))
    data["allergies"] = allergies

    # Collect medications for this patient
    medications = []
    for _, med in world.list_entities("medication").items():
        if _get(med, "patient_id") == patient_id:
            medications.append(_serialize(med))
    data["medications"] = medications

    # Collect encounter IDs for this patient
    encounter_ids = []
    for eid, enc in world.list_entities("encounter").items():
        if _get(enc, "patient_id") == patient_id:
            encounter_ids.append(eid)
    data["encounter_ids"] = encounter_ids

    # Collect insurance for this patient
    insurance_records = []
    for _, ins in world.list_entities("insurance").items():
        if _get(ins, "patient_id") == patient_id:
            insurance_records.append(_serialize(ins))
    data["insurance"] = insurance_records

    return _ok(data)


# ---------------------------------------------------------------------------
# 9. getProtocolDetails
# ---------------------------------------------------------------------------


def get_protocol_details(world, params):
    """Return full protocol details. Search by ID or by name substring.

    Params:
        protocol_id (required)
    """
    protocol_id = params.get("protocol_id")
    if not protocol_id:
        return _error("invalid_params", "protocol_id is required")

    # Try direct ID lookup
    protocol = world.get_entity("protocol", protocol_id)
    if protocol is not None:
        return _ok(_serialize(protocol))

    # Fall back to name substring search
    for pid, proto in world.list_entities("protocol").items():
        name = _get(proto, "name", _get(proto, "title", ""))
        if _matches_substring(name, protocol_id):
            return _ok(_serialize(proto))

    return _error("not_found", f"Protocol {protocol_id} not found")


# ---------------------------------------------------------------------------
# 10. getTransferStatus
# ---------------------------------------------------------------------------


def get_transfer_status(world, params):
    """Return transfer details by transfer_id or list transfers for an encounter.

    Params:
        transfer_id, encounter_id (at least one required)
    """
    transfer_id = params.get("transfer_id")
    encounter_id = params.get("encounter_id")

    if not transfer_id and not encounter_id:
        return _error("invalid_params", "transfer_id or encounter_id is required")

    # Direct lookup by transfer_id
    if transfer_id:
        transfer = world.get_entity("transfer", transfer_id)
        if transfer is None:
            return _error("not_found", f"Transfer {transfer_id} not found")
        return _ok(_serialize(transfer))

    # Find all transfers for the encounter
    transfers = []
    for _, xfr in world.list_entities("transfer").items():
        if _get(xfr, "encounter_id") == encounter_id:
            transfers.append(_serialize(xfr))
        if len(transfers) >= _MAX_RESULTS:
            break

    return _ok(transfers)


# ---------------------------------------------------------------------------
# 11. getInsuranceCoverage
# ---------------------------------------------------------------------------


def get_insurance_coverage(world, params):
    """Return insurance details for a patient.

    Params:
        patient_id (required)
    """
    patient_id = params.get("patient_id")
    if not patient_id:
        return _error("invalid_params", "patient_id is required")

    records = []
    for _, ins in world.list_entities("insurance").items():
        if _get(ins, "patient_id") == patient_id:
            records.append(_serialize(ins))
        if len(records) >= _MAX_RESULTS:
            break

    if not records:
        return _error("not_found", f"No insurance found for patient {patient_id}")

    return _ok(records)


# ---------------------------------------------------------------------------
# 12. getReferenceArticle
# ---------------------------------------------------------------------------


def get_reference_article(world, params):
    """Return full reference material content.

    Params:
        ref_id (required)
    """
    ref_id = params.get("ref_id")
    if not ref_id:
        return _error("invalid_params", "ref_id is required")

    ref = world.get_entity("reference_material", ref_id)
    if ref is None:
        return _error("not_found", f"Reference material {ref_id} not found")

    return _ok(_serialize(ref))
