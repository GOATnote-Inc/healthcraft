"""Load an opt-in original synthetic source-reconciliation case.

This is a closed source transport contract, not a clinical interpretation or
an expected-answer generator. No published task, default injector, physiology
or reward behavior is changed.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from healthcraft.entities.base import EntityType
from healthcraft.entities.encounters import Encounter
from healthcraft.entities.patients import Patient
from healthcraft.tasks.care_projection import project_authored_care
from healthcraft.tasks.imaging_projection import project_imaging
from healthcraft.temporal import instant_key
from healthcraft.world.state import WorldState

SCHEMA_VERSION = "healthcraft-reconciliation-scenario/v1"
SCENARIO_ID = "synthetic-ed-reconciliation/v1"
DEFAULT_SCENARIO_PATH = (
    Path(__file__).resolve().parents[3] / "configs/evaluation/reconciliation_v1/scenario.json"
)
_COLLECTIONS = ("active_orders", "current_management", "treatments_given", "imaging_pending")
_ROW_FIELDS = {
    "active_orders": ({"source_id", "order_id", "item", "status", "time"}, set()),
    "current_management": ({"source_id", "item", "status", "time"}, {"kind"}),
    "treatments_given": (
        {"source_id", "item", "reported_status", "event_time"},
        {"event_id", "reporter"},
    ),
    "imaging_pending": (
        {"source_id", "study_id", "modality", "body_part", "status", "time"},
        set(),
    ),
}


def _keys(value: Any, required: set[str], optional: set[str] | None = None) -> None:
    if (
        type(value) is not dict
        or not required <= value.keys()
        or value.keys() - (required | (optional or set()))
    ):
        raise ValueError("Missing or unrecognized scenario fields")


def _json_copy(value: Any) -> Any:
    """Require finite JSON, including exact container/scalar types and string keys."""
    try:
        encoded = json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("Scenario requires finite acyclic JSON") from exc
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is dict and all(type(key) is str for key in item):
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
        elif item is not None and type(item) not in (str, bool, int, float):
            raise ValueError("Scenario requires JSON containers and string object keys")
    return json.loads(encoded)


def _text(value: Any, *, empty: bool = False) -> None:
    if type(value) is not str or (not empty and not value.strip()):
        raise ValueError("Expected a nonempty source string")


def _identifier(value: Any, prefix: str) -> None:
    if type(value) is not str or not re.fullmatch(
        rf"{prefix}-(?:[A-F0-9]{{8}}|[A-F0-9]{{12}})", value
    ):
        raise ValueError(f"Invalid {prefix} identifier")


def _timestamp(value: Any, *, nullable: bool = True) -> None:
    if value is None and nullable:
        return
    if type(value) is not str:
        raise ValueError("Timestamp must be an explicit RFC3339 string or null")
    try:
        instant_key(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError("Timestamp must identify an explicit aware instant") from exc


def _pointer_part(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _validated(scenario: dict) -> tuple[dict, list[dict], datetime]:
    data = _json_copy(scenario)
    _keys(data, {"schema_version", "id", "clock", "target", "patients", "encounters"})
    if data["schema_version"] != SCHEMA_VERSION or data["id"] != SCENARIO_ID:
        raise ValueError("Unsupported reconciliation scenario or schema version")
    _timestamp(data["clock"], nullable=False)
    seconds, fraction = instant_key(data["clock"])
    if len(fraction) > 6:
        raise ValueError("World clock precision exceeds the runtime's microsecond precision")
    clock = seconds.replace(microsecond=int(fraction.ljust(6, "0") or "0"))
    _keys(data["target"], {"patient_id", "encounter_id"})
    _identifier(data["target"]["patient_id"], "PAT")
    _identifier(data["target"]["encounter_id"], "ENC")
    if type(data["patients"]) is not list or len(data["patients"]) != 2:
        raise ValueError("This opt-in case requires exactly two patients")
    if type(data["encounters"]) is not list or len(data["encounters"]) != 3:
        raise ValueError("This opt-in case requires exactly three encounters")

    patients, mrns = {}, set()
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
        dob = patient["date_of_birth"]
        if dob is not None:
            if type(dob) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", dob):
                raise ValueError("Date of birth must be an ISO date or null")
            date.fromisoformat(dob)
        if type(patient["prior_visit_ids"]) is not list:
            raise ValueError("Prior visit IDs must be a list")
        for prior in patient["prior_visit_ids"]:
            _identifier(prior, "ENC")
        if len(set(patient["prior_visit_ids"])) != len(patient["prior_visit_ids"]):
            raise ValueError("Duplicate prior encounter link")
        patients[patient["id"]] = patient
        mrns.add(patient["mrn"])

    encounters, ids, rows = {}, set(), []
    for encounter in data["encounters"]:
        _keys(encounter, {"id", "patient_id", "chief_complaint", "arrival_time", "patient_data"})
        _identifier(encounter["id"], "ENC")
        _identifier(encounter["patient_id"], "PAT")
        _text(encounter["chief_complaint"])
        _timestamp(encounter["arrival_time"])
        if encounter["id"] in encounters or encounter["patient_id"] not in patients:
            raise ValueError("Encounter ID collision or missing linked patient")
        _keys(encounter["patient_data"], set(), set(_COLLECTIONS))
        for collection in _COLLECTIONS:
            if collection not in encounter["patient_data"]:
                continue
            contents = encounter["patient_data"][collection]
            if collection == "imaging_pending":
                if type(contents) is not dict:
                    raise ValueError("Imaging source collection must be an object")
                indexed = list(contents.items())
            else:
                if type(contents) is not list:
                    raise ValueError("Care source collection must be an array")
                indexed = list(enumerate(contents))
            for label, source in indexed:
                required, optional = _ROW_FIELDS[collection]
                _keys(source, required, optional)
                source_id = source["source_id"]
                if type(source_id) is not str or not re.fullmatch(r"SRC-[A-Z][0-9]{2}", source_id):
                    raise ValueError("Invalid source record identifier")
                if source_id in ids:
                    raise ValueError("Source record identifiers must be globally unique")
                for field, value in source.items():
                    if field in {"time", "event_time"}:
                        _timestamp(value)
                    elif field == "status" and value is None:
                        continue
                    else:
                        _text(value)
                ids.add(source_id)
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
        # Loader and row enumeration must not accept a shape that the native
        # observation projector would reject or withhold during construction.
        project_imaging(encounter["patient_data"], task_id=data["id"])
        encounters[encounter["id"]] = encounter
    if len(rows) != 8:
        raise ValueError("This opt-in case requires exactly eight original source records")
    target = data["target"]
    if target["encounter_id"] not in encounters or (
        encounters[target["encounter_id"]]["patient_id"] != target["patient_id"]
    ):
        raise ValueError("Target patient and encounter must identify the same record")
    for patient in patients.values():
        for prior in patient["prior_visit_ids"]:
            if prior not in encounters or encounters[prior]["patient_id"] != patient["id"]:
                raise ValueError("Prior encounter link must belong to its patient")
            if prior == target["encounter_id"]:
                raise ValueError("Current target encounter cannot also be a prior visit")
    return data, rows, clock


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant: {value}")


def load_scenario(path: Path | None = None) -> dict:
    """Read and validate an explicit scenario; never fall back on a failed load."""
    raw = json.loads(
        (DEFAULT_SCENARIO_PATH if path is None else Path(path)).read_text(encoding="utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )
    data, _, _ = _validated(raw)
    return data


def source_rows(scenario: dict) -> list[dict]:
    """Return detached descriptors with pointers into each original patient_data."""
    _, rows, _ = _validated(scenario)
    return rows


def build_world(scenario: dict) -> WorldState:
    """Validate/stage every entity before constructing a fresh isolated world."""
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
            dob=date.fromisoformat(patient["date_of_birth"]) if patient["date_of_birth"] else None,
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


def _normalize(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _normalize(asdict(value))
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if type(value) is dict:
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def snapshot_world(world: WorldState) -> dict:
    """Detach JSON-shaped state for all collections; capture audit separately."""
    return _json_copy(
        {
            "timestamp": world.timestamp.isoformat(),
            "entities": {
                kind.value: {
                    identifier: _normalize(entity)
                    for identifier, entity in sorted(world.list_entities(kind.value).items())
                }
                for kind in EntityType
            },
        }
    )
