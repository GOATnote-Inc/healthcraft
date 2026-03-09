"""Computation MCP tool handlers for the HEALTHCRAFT ED simulation.

Implements 4 compute tools that derive new information from world state
without mutating it: resource availability checks, transfer time estimation,
clinical decision rule scoring, and treatment plan validation.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from healthcraft.world.state import WorldState

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _serialize(entity: Any) -> dict[str, Any]:
    """Convert a dataclass entity or dict to a plain dict.

    Uses ``dataclasses.asdict`` when possible, with a dict passthrough
    fallback so callers never need to inspect the entity type.
    """
    if hasattr(entity, "__dataclass_fields__"):
        return asdict(entity)
    if isinstance(entity, dict):
        return dict(entity)
    return {"value": str(entity)}


def _ok(data: Any) -> dict[str, Any]:
    """Return a success envelope."""
    return {"status": "ok", "data": data}


def _error(code: str, message: str) -> dict[str, Any]:
    """Return an error envelope."""
    return {"status": "error", "code": code, "message": message}


def _get_field(obj: Any, field: str, default: Any = None) -> Any:
    """Read a field from a dataclass or dict with fallback."""
    if hasattr(obj, field):
        return getattr(obj, field)
    if isinstance(obj, dict):
        return obj.get(field, default)
    return default


# ---------------------------------------------------------------------------
# 1. check_resource_availability
# ---------------------------------------------------------------------------


def check_resource_availability(world: WorldState, params: dict[str, Any]) -> dict[str, Any]:
    """Check whether *count* resources of a given type are available.

    Params
    ------
    resource_type : str (required)
        The resource type to search for (e.g. ``"bed"``, ``"ct_scanner"``).
    count : int (optional, default 1)
        Number of resources needed.
    zone : str (optional)
        Restrict the search to a specific zone.

    Returns
    -------
    dict
        ``{"available": bool, "count_available": int,
        "count_requested": int, "matching_resources": [...]}``
    """
    resource_type = params.get("resource_type")
    if not resource_type:
        return _error("missing_param", "resource_type is required")

    count = int(params.get("count", 1))
    zone = params.get("zone")

    resources = world.list_entities("resource")
    matching: list[dict[str, Any]] = []

    for _rid, resource in resources.items():
        r_type = _get_field(resource, "resource_type", "")
        r_status = _get_field(resource, "status", "")
        r_zone = _get_field(resource, "zone", "")

        if r_type != resource_type:
            continue
        if r_status != "available":
            continue
        if zone and r_zone != zone:
            continue

        matching.append(
            {
                "id": _get_field(resource, "id", _rid),
                "resource_id": _get_field(resource, "resource_id", ""),
                "name": _get_field(resource, "name", ""),
                "zone": r_zone,
                "status": r_status,
                "notes": _get_field(resource, "notes", ""),
            }
        )

    return _ok(
        {
            "available": len(matching) >= count,
            "count_available": len(matching),
            "count_requested": count,
            "matching_resources": matching,
        }
    )


# ---------------------------------------------------------------------------
# 2. calculate_transfer_time
# ---------------------------------------------------------------------------

# Bundled facility lookup table.  Keys are facility names (case-sensitive);
# values map transport mode -> estimated minutes.  ``None`` means that
# transport mode is not available for that facility.

_FACILITY_TRANSFER_TIMES: dict[str, dict[str, int | None]] = {
    "Riverside Community Hospital": {
        "ground_als": 15,
        "ground_bls": 15,
        "helicopter": 10,
    },
    "University Medical Center": {
        "ground_als": 25,
        "ground_bls": 25,
        "helicopter": 12,
    },
    "Children's Memorial Hospital": {
        "ground_als": 20,
        "ground_bls": 20,
        "helicopter": 10,
    },
    "Regional Burn Center": {
        "ground_als": 40,
        "ground_bls": 40,
        "helicopter": 15,
    },
    "Lakeside Psychiatric": {
        "ground_als": 30,
        "ground_bls": 30,
        "helicopter": None,
    },
    "St. Mary's Rehabilitation": {
        "ground_als": 35,
        "ground_bls": 35,
        "helicopter": None,
    },
    "Metro Level I Trauma": {
        "ground_als": 20,
        "ground_bls": 20,
        "helicopter": 8,
    },
    "County General Hospital": {
        "ground_als": 30,
        "ground_bls": 30,
        "helicopter": 12,
    },
}

_VALID_TRANSPORT_MODES = {"ground_als", "ground_bls", "helicopter", "fixed_wing"}

# Fixed-wing adds 45 min for airport transfer overhead.
_FIXED_WING_OVERHEAD_MINUTES = 45


def calculate_transfer_time(world: WorldState, params: dict[str, Any]) -> dict[str, Any]:
    """Estimate transfer time to a named facility.

    Params
    ------
    facility_name : str (required)
        Destination facility name (must match the lookup table).
    transport_mode : str (optional, default ``"ground_als"``)
        One of ``ground_als``, ``ground_bls``, ``helicopter``, ``fixed_wing``.

    Returns
    -------
    dict
        ``{"facility": str, "transport_mode": str,
        "estimated_minutes": int, "notes": str}``
    """
    facility_name = params.get("facility_name")
    if not facility_name:
        return _error("missing_param", "facility_name is required")

    transport_mode = params.get("transport_mode", "ground_als")
    if transport_mode not in _VALID_TRANSPORT_MODES:
        return _error(
            "invalid_param",
            f"Invalid transport_mode '{transport_mode}'. "
            f"Valid modes: {', '.join(sorted(_VALID_TRANSPORT_MODES))}",
        )

    facility = _FACILITY_TRANSFER_TIMES.get(facility_name)
    if facility is None:
        available = ", ".join(sorted(_FACILITY_TRANSFER_TIMES.keys()))
        return _error(
            "facility_not_found",
            f"Facility '{facility_name}' not found. Available facilities: {available}",
        )

    notes = ""

    if transport_mode == "fixed_wing":
        # Fixed-wing uses the helicopter base time plus airport overhead.
        heli_time = facility.get("helicopter")
        if heli_time is None:
            return _error(
                "transport_unavailable",
                f"No air transport available to {facility_name}",
            )
        estimated_minutes = heli_time + _FIXED_WING_OVERHEAD_MINUTES
        notes = (
            f"Fixed-wing estimate includes {_FIXED_WING_OVERHEAD_MINUTES} min "
            f"airport transfer overhead added to base air time of {heli_time} min"
        )
    else:
        base_time = facility.get(transport_mode)
        if base_time is None:
            return _error(
                "transport_unavailable",
                f"Transport mode '{transport_mode}' is not available to {facility_name}",
            )
        estimated_minutes = base_time

        if transport_mode == "helicopter":
            notes = "Helicopter availability subject to weather and crew status"
        elif transport_mode == "ground_bls":
            notes = "BLS transport — no ALS interventions en route"
        else:
            notes = "ALS ground transport with paramedic crew"

    return _ok(
        {
            "facility": facility_name,
            "transport_mode": transport_mode,
            "estimated_minutes": estimated_minutes,
            "notes": notes,
        }
    )


# ---------------------------------------------------------------------------
# 3. run_decision_rule
# ---------------------------------------------------------------------------


def run_decision_rule(world: WorldState, params: dict[str, Any]) -> dict[str, Any]:
    """Apply a clinical decision rule and return the computed score.

    Looks up a ``decision_rule`` entity by name (case-insensitive), sums the
    supplied variable values, and finds the matching score range.

    Params
    ------
    rule_name : str (required)
        Display name of the rule (e.g. ``"HEART Score"``).
    variables : dict[str, float|int] (required)
        Mapping of variable name -> numeric value.

    Returns
    -------
    dict
        ``{"rule_name": str, "score": number, "max_score": number,
        "risk_level": str, "recommendation": str, "variables_used": dict}``
    """
    rule_name = params.get("rule_name")
    if not rule_name:
        return _error("missing_param", "rule_name is required")

    variables = params.get("variables")
    if not isinstance(variables, dict):
        return _error("missing_param", "variables must be a dict of variable_name -> value")

    # Case-insensitive lookup across all decision_rule entities.
    rules = world.list_entities("decision_rule")
    matched_rule = None
    for _rid, rule in rules.items():
        name = _get_field(rule, "name", "")
        if name.lower() == rule_name.lower():
            matched_rule = rule
            break

    if matched_rule is None:
        available_names = sorted(
            _get_field(r, "name", "") for r in rules.values() if _get_field(r, "name", "")
        )
        return _error(
            "rule_not_found",
            f"Decision rule '{rule_name}' not found. "
            f"Available rules: {', '.join(available_names) if available_names else 'none loaded'}",
        )

    # Compute score by summing provided variable values.
    rule_variables = _get_field(matched_rule, "variables", ())
    score: float = 0
    max_score: float = 0
    variables_used: dict[str, Any] = {}

    for var_def in rule_variables:
        var_name = (
            var_def.get("name", "")
            if isinstance(var_def, dict)
            else _get_field(var_def, "name", "")
        )
        var_max = (
            var_def.get("max_value", 0)
            if isinstance(var_def, dict)
            else _get_field(var_def, "max_value", 0)
        )
        max_score += var_max

        # Match variable by case-insensitive name.
        supplied_value = None
        for supplied_name, supplied_val in variables.items():
            if supplied_name.lower() == var_name.lower():
                supplied_value = supplied_val
                break

        if supplied_value is not None:
            score += float(supplied_value)
            variables_used[var_name] = supplied_value
        else:
            variables_used[var_name] = 0

    # Find matching score range.
    score_ranges = _get_field(matched_rule, "score_ranges", ())
    risk_level = "unknown"
    recommendation = "No matching score range found"

    for sr in score_ranges:
        min_s = sr.get("min_score", 0) if isinstance(sr, dict) else _get_field(sr, "min_score", 0)
        max_s = sr.get("max_score", 0) if isinstance(sr, dict) else _get_field(sr, "max_score", 0)
        if min_s <= score <= max_s:
            risk_level = (
                sr.get("risk_level", "unknown")
                if isinstance(sr, dict)
                else _get_field(sr, "risk_level", "unknown")
            )
            recommendation = (
                sr.get("recommendation", "")
                if isinstance(sr, dict)
                else _get_field(sr, "recommendation", "")
            )
            break

    # Return score as int if it has no fractional part, else float.
    score_out: int | float = int(score) if score == int(score) else score
    max_score_out: int | float = int(max_score) if max_score == int(max_score) else max_score

    return _ok(
        {
            "rule_name": _get_field(matched_rule, "name", rule_name),
            "score": score_out,
            "max_score": max_score_out,
            "risk_level": risk_level,
            "recommendation": recommendation,
            "variables_used": variables_used,
        }
    )


# ---------------------------------------------------------------------------
# 4. validate_treatment_plan
# ---------------------------------------------------------------------------

# Known drug interaction pairs.  Each entry is a frozenset of two lowercase
# drug keywords and the associated warning.

_KNOWN_INTERACTIONS: list[tuple[frozenset[str], str]] = [
    (frozenset({"warfarin", "aspirin"}), "Increased bleeding risk"),
    (frozenset({"heparin", "alteplase"}), "Major bleeding risk - verify indication"),
    (frozenset({"metformin", "contrast dye"}), "Hold metformin 48h post contrast"),
    (frozenset({"ace inhibitors", "potassium"}), "Hyperkalemia risk"),
]

# Known allergy cross-reactivity groups.  Key is the allergy name (title
# case); value is the set of medications that should be flagged.

_ALLERGY_CROSS_REACTIVITY: dict[str, set[str]] = {
    "Penicillin": {"Amoxicillin", "Ampicillin", "Piperacillin"},
    "Sulfa": {"Sulfamethoxazole", "Furosemide"},
    "Cephalosporins": {"Ceftriaxone", "Cefazolin", "Cephalexin"},
}


def _medication_matches_keyword(medication: str, keyword: str) -> bool:
    """Check if a medication name contains a keyword (case-insensitive)."""
    return keyword in medication.lower()


def _check_drug_interactions(
    proposed_medications: list[str],
    current_medications: list[str],
) -> list[str]:
    """Return warnings for known interactions between proposed and current meds."""
    warnings: list[str] = []
    all_meds_lower = [m.lower() for m in proposed_medications + current_medications]

    for pair, warning in _KNOWN_INTERACTIONS:
        keywords = list(pair)
        # Both keywords must appear somewhere in the combined med list.
        found = [False, False]
        for med in all_meds_lower:
            for i, kw in enumerate(keywords):
                if kw in med:
                    found[i] = True
        if all(found):
            warnings.append(f"{' + '.join(sorted(pair))}: {warning}")

    # Also check proposed meds against each other.
    if len(proposed_medications) > 1:
        proposed_lower = [m.lower() for m in proposed_medications]
        for pair, warning in _KNOWN_INTERACTIONS:
            keywords = list(pair)
            found = [False, False]
            for med in proposed_lower:
                for i, kw in enumerate(keywords):
                    if kw in med:
                        found[i] = True
            if all(found):
                msg = f"{' + '.join(sorted(pair))}: {warning}"
                if msg not in warnings:
                    warnings.append(msg)

    return warnings


def _check_allergy_conflicts(
    proposed_medications: list[str],
    patient_allergies: list[str],
) -> list[str]:
    """Return allergy conflict descriptions for proposed medications."""
    conflicts: list[str] = []

    for allergy in patient_allergies:
        allergy_title = allergy.strip().title()
        allergy_lower = allergy.strip().lower()

        # Direct match: allergy name appears in a proposed med.
        for med in proposed_medications:
            if allergy_lower in med.lower():
                conflicts.append(
                    f"Patient allergic to {allergy} — proposed medication "
                    f"'{med}' is contraindicated"
                )

        # Cross-reactivity check.
        cross_meds = _ALLERGY_CROSS_REACTIVITY.get(allergy_title, set())
        for med in proposed_medications:
            for cross_med in cross_meds:
                if cross_med.lower() in med.lower():
                    note = ""
                    if allergy_title == "Sulfa" and cross_med == "Furosemide":
                        note = " (note: low cross-reactivity)"
                    conflicts.append(
                        f"Patient allergic to {allergy} — proposed medication "
                        f"'{med}' may cross-react with {allergy_title} allergy "
                        f"(related: {cross_med}){note}"
                    )

    return conflicts


def validate_treatment_plan(world: WorldState, params: dict[str, Any]) -> dict[str, Any]:
    """Validate a proposed treatment plan against patient data.

    Checks proposed medications and procedures against patient allergies,
    known drug interactions with current medications, and basic protocol
    compliance.

    Params
    ------
    encounter_id : str (required)
        The encounter to validate against.
    medications : list[str] (optional)
        List of proposed medication names.
    procedures : list[str] (optional)
        List of proposed procedure names.
    patient_id : str (optional)
        Explicit patient ID.  If omitted, resolved from the encounter.

    Returns
    -------
    dict
        ``{"valid": bool, "warnings": [...], "contraindications": [...],
        "allergy_conflicts": [...]}``
    """
    encounter_id = params.get("encounter_id")
    if not encounter_id:
        return _error("missing_param", "encounter_id is required")

    proposed_medications: list[str] = list(params.get("medications") or [])
    proposed_procedures: list[str] = list(params.get("procedures") or [])

    # Resolve encounter.
    encounter = world.get_entity("encounter", encounter_id)
    if encounter is None:
        return _error("encounter_not_found", f"Encounter '{encounter_id}' not found")

    # Resolve patient.
    patient_id = params.get("patient_id") or _get_field(encounter, "patient_id", "")
    patient = world.get_entity("patient", patient_id) if patient_id else None

    warnings: list[str] = []
    contraindications: list[str] = []
    allergy_conflicts: list[str] = []

    # --- Allergy checks ---
    if patient is not None and proposed_medications:
        patient_allergies = list(_get_field(patient, "allergies", ()))
        allergy_conflicts = _check_allergy_conflicts(proposed_medications, patient_allergies)
        # Allergy conflicts are also contraindications.
        contraindications.extend(allergy_conflicts)

    # --- Drug interaction checks ---
    if proposed_medications:
        current_medications: list[str] = []
        if patient is not None:
            current_medications = list(_get_field(patient, "medications", ()))

        # Also include medications already administered during this encounter.
        meds_administered = _get_field(encounter, "meds_administered", ())
        for med_admin in meds_administered:
            med_name = _get_field(med_admin, "medication_name", "")
            if med_name:
                current_medications.append(med_name)

        interaction_warnings = _check_drug_interactions(
            proposed_medications,
            current_medications,
        )
        warnings.extend(interaction_warnings)

    # --- Basic protocol compliance checks ---
    if not proposed_medications and not proposed_procedures:
        warnings.append("Treatment plan contains no medications or procedures")

    if patient is not None:
        advance_directives = _get_field(patient, "advance_directives", "")
        if advance_directives == "comfort_only" and proposed_procedures:
            contraindications.append(
                "Patient has comfort-only advance directive — "
                "invasive procedures require goals-of-care discussion"
            )
        if advance_directives in ("dnr", "dnr_dni"):
            for proc in proposed_procedures:
                if any(
                    kw in proc.lower()
                    for kw in ("intubation", "cpr", "defibrillation", "resuscitation")
                ):
                    contraindications.append(
                        f"Patient has {advance_directives.upper()} directive — "
                        f"procedure '{proc}' may conflict with advance directive"
                    )

    valid = len(contraindications) == 0

    return _ok(
        {
            "valid": valid,
            "warnings": warnings,
            "contraindications": contraindications,
            "allergy_conflicts": allergy_conflicts,
        }
    )
