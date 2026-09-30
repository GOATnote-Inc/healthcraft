"""Bounded, original source-reconciliation casebook worlds, opt-in version 2.

Only the declared same-name synthetic cohort is modeled. This preserves raw
source assertions through native projections; it supplies no clinical policy,
fixture-derived answer, generated demographics or executed-care inference.
The single-case version 1 loader and its captured artifacts remain unchanged.
"""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime

from healthcraft.entities.base import EntityType
from healthcraft.entities.encounters import Encounter
from healthcraft.entities.patients import Patient
from healthcraft.reconciliation.fixture import (
    _COLLECTIONS,
    _ROW_FIELDS,
    _identifier,
    _json_copy,
    _keys,
    _pointer_part,
    _text,
    _timestamp,
)
from healthcraft.tasks.care_projection import project_authored_care
from healthcraft.tasks.imaging_projection import project_imaging
from healthcraft.temporal import instant_key
from healthcraft.world.state import WorldState

SCHEMA_VERSION = "healthcraft-reconciliation-scenario/v2"


def _validated(scenario: dict) -> tuple[dict, list[dict], datetime]:
    data = _json_copy(scenario)
    _keys(data, {"schema_version", "id", "clock", "target", "patients", "encounters"})
    if (
        data["schema_version"] != SCHEMA_VERSION
        or type(data["id"]) is not str
        or not re.fullmatch(r"synthetic-ed-reconciliation/v2/REC2-[0-9]{3}", data["id"])
    ):
        raise ValueError("Unsupported casebook scenario or schema version")
    _timestamp(data["clock"], nullable=False)
    seconds, fraction = instant_key(data["clock"])
    if len(fraction) > 6:
        raise ValueError("World clock precision exceeds the runtime's microsecond precision")
    clock = seconds.replace(microsecond=int(fraction.ljust(6, "0") or "0"))
    _keys(data["target"], {"patient_id", "encounter_id"})
    _identifier(data["target"]["patient_id"], "PAT")
    _identifier(data["target"]["encounter_id"], "ENC")
    if type(data["patients"]) is not list or not 1 <= len(data["patients"]) <= 8:
        raise ValueError("Casebook scenarios require one to eight patients")
    if type(data["encounters"]) is not list or not 1 <= len(data["encounters"]) <= 16:
        raise ValueError("Casebook scenarios require one to sixteen encounters")

    patients, mrns, names = {}, set(), set()
    for patient in data["patients"]:
        _keys(
            patient,
            {"id", "mrn", "first_name", "last_name", "date_of_birth", "sex", "prior_visit_ids"},
        )
        _identifier(patient["id"], "PAT")
        for field in ("mrn", "first_name", "last_name"):
            _text(patient[field])
        _text(patient["sex"], empty=True)
        if patient["id"] in patients or patient["mrn"] in mrns:
            raise ValueError("Patient IDs and MRNs must be unique")
        if patient["date_of_birth"] is not None:
            raise ValueError("This casebook scope requires unknown date of birth (null)")
        if type(patient["prior_visit_ids"]) is not list:
            raise ValueError("Prior visit IDs must be a list")
        for prior in patient["prior_visit_ids"]:
            _identifier(prior, "ENC")
        if len(set(patient["prior_visit_ids"])) != len(patient["prior_visit_ids"]):
            raise ValueError("Duplicate prior encounter link")
        patients[patient["id"]] = patient
        mrns.add(patient["mrn"])
        names.add((patient["first_name"], patient["last_name"]))
    if len(names) != 1:
        raise ValueError("This casebook requires a single literal same-name patient cohort")

    encounters, source_ids, rows = {}, set(), []
    counts = dict.fromkeys(patients, 0)
    for encounter in data["encounters"]:
        _keys(encounter, {"id", "patient_id", "chief_complaint", "arrival_time", "patient_data"})
        _identifier(encounter["id"], "ENC")
        _identifier(encounter["patient_id"], "PAT")
        _text(encounter["chief_complaint"])
        _timestamp(encounter["arrival_time"])
        if encounter["id"] in encounters or encounter["patient_id"] not in patients:
            raise ValueError("Encounter ID collision or missing linked patient")
        counts[encounter["patient_id"]] += 1
        if counts[encounter["patient_id"]] > 9:
            raise ValueError(
                "At most nine encounters per patient can be discovered without truncation"
            )
        _keys(encounter["patient_data"], set(), set(_COLLECTIONS))
        for collection in _COLLECTIONS:
            if collection not in encounter["patient_data"]:
                continue
            contents = encounter["patient_data"][collection]
            if collection == "imaging_pending":
                if type(contents) is not dict:
                    raise ValueError("Imaging source collection must be an object")
                indexed = contents.items()
            else:
                if type(contents) is not list:
                    raise ValueError("Care source collection must be an array")
                indexed = enumerate(contents)
            for label, source in indexed:
                required, optional = _ROW_FIELDS[collection]
                _keys(source, required, optional)
                source_id = source["source_id"]
                if type(source_id) is not str or not re.fullmatch(r"SRC-[A-Z][0-9]{2}", source_id):
                    raise ValueError("Invalid source record identifier")
                if source_id in source_ids:
                    raise ValueError("Source record identifiers must be globally unique")
                for field, value in source.items():
                    if field in {"time", "event_time"}:
                        _timestamp(value)
                    elif field == "status" and value is None:
                        continue
                    else:
                        _text(value)
                source_ids.add(source_id)
                rows.append(
                    {
                        "source_id": source_id,
                        "patient_id": encounter["patient_id"],
                        "encounter_id": encounter["id"],
                        "source_collection": collection,
                        "source_path": f"/{collection}/{_pointer_part(str(label))}",
                        "source": deepcopy(source),
                    }
                )
        # Reject a source shape withheld or rejected by the native projector.
        project_imaging(encounter["patient_data"], task_id=data["id"])
        encounters[encounter["id"]] = encounter
    if not 1 <= len(rows) <= 128:
        raise ValueError("Casebook scenarios require one to 128 source records")
    target = data["target"]
    if target["encounter_id"] not in encounters or (
        encounters[target["encounter_id"]]["patient_id"] != target["patient_id"]
    ):
        raise ValueError("Target patient and encounter must identify the same record")
    if not any(row["encounter_id"] == target["encounter_id"] for row in rows):
        raise ValueError("Target encounter requires at least one source record")
    for patient in patients.values():
        for prior in patient["prior_visit_ids"]:
            if prior not in encounters or encounters[prior]["patient_id"] != patient["id"]:
                raise ValueError("Prior encounter link must belong to its patient")
            if prior == target["encounter_id"]:
                raise ValueError("Current target encounter cannot also be a prior visit")
    return data, rows, clock


def validate_scenario(scenario: dict) -> dict:
    """Return a detached finite JSON scenario after checking its entire graph."""
    return _validated(scenario)[0]


def source_rows(scenario: dict) -> list[dict]:
    """Return detached descriptors into each encounter's original patient_data."""
    return _validated(scenario)[1]


def build_world(scenario: dict) -> WorldState:
    """Stage validated native entities, then construct a fresh isolated world."""
    data, _, clock = _validated(scenario)
    staged = []
    for patient in data["patients"]:
        entity = Patient(
            id=patient["id"],
            entity_type=EntityType.PATIENT,
            created_at=clock,
            updated_at=clock,
            mrn=patient["mrn"],
            first_name=patient["first_name"],
            last_name=patient["last_name"],
            dob=None,
            sex=patient["sex"],
            prior_visit_ids=tuple(patient["prior_visit_ids"]),
        )
        staged.append(("patient", entity.id, entity))
    for encounter in data["encounters"]:
        imaging = project_imaging(encounter["patient_data"], task_id=data["id"])
        entity = Encounter(
            id=encounter["id"],
            entity_type=EntityType.ENCOUNTER,
            created_at=clock,
            updated_at=clock,
            patient_id=encounter["patient_id"],
            chief_complaint=encounter["chief_complaint"],
            esi_level=None,
            arrival_time=encounter["arrival_time"],
            triage_time=None,
            authored_care=project_authored_care(encounter["patient_data"]),
            imaging=imaging.records,
            imaging_projection_notices=imaging.notices,
        )
        staged.append(("encounter", entity.id, entity))
    world = WorldState(start_time=clock, dynamic_state_enabled=False)
    for kind, identifier, entity in staged:
        world.put_entity(kind, identifier, entity)
    return world
