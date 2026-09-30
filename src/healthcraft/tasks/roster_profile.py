"""Explicit observation projection for six published multi-patient scenarios.

Experimental and opt-in. Source assessments are not clinical ground truth;
withheld recommendations and missing facts can limit full-task solvability.
"""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from typing import Any

from healthcraft.tasks.loader import Task
from healthcraft.world.state import WorldState

PROFILE_VERSION = "roster-observations/v1"

# collection, count, identity field, mandatory observation, allowed fields,
# withheld fields, literal source context. Unknown additions require review.
_CONTRACTS = {
    "CC-022": (
        (
            "patients_requiring_action",
            4,
            "bed",
            "summary",
            ("bed", "summary"),
            ("acuity", "needed_actions", "time_sensitivity"),
            "Current ED patient",
        ),
    ),
    "CC-027": (
        (
            "incoming_ambulances",
            3,
            "unit",
            "patient_summary",
            ("unit", "patient_summary", "eta_minutes"),
            ("acuity",),
            "Incoming ambulance",
        ),
    ),
    "CC-028": (
        (
            "incoming_patients",
            7,
            "triage_tag",
            "summary",
            ("triage_tag", "summary"),
            ("needs",),
            "Incoming casualty; source tag is not verified triage",
        ),
    ),
    "IR-018": (
        (
            "patients_requiring_iv_fluids",
            7,
            "id",
            "condition",
            ("id", "condition"),
            ("priority", "fluid_need", "esi"),
            "Current ED patient, except Incoming EMS",
        ),
    ),
    "IR-023": (
        (
            "patients_on_norepinephrine",
            3,
            "id",
            "condition",
            ("id", "condition", "current_dose", "trend", "antibiotics"),
            ("note", "estimated_duration"),
            "Current ED patient on norepinephrine",
        ),
        (
            "patients_at_risk",
            2,
            "id",
            "condition",
            ("id", "condition", "status"),
            ("note",),
            "Current ED patient described as at risk",
        ),
        (
            "icu_requests",
            2,
            "id",
            "condition",
            ("id", "condition"),
            ("current_vasopressor",),
            "ICU request; not an ED arrival",
        ),
    ),
    "IR-025": (
        (
            "incoming_patients",
            5,
            "ems_id",
            "ems_report",
            ("ems_id", "age", "sex", "ems_report", "ems_triage"),
            ("actual_priority", "note"),
            "Arriving EMS patient; EMS triage is unverified",
        ),
    ),
}


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def supported_roster_tasks() -> tuple[str, ...]:
    return tuple(_CONTRACTS)


def roster_contract(task_id: str) -> tuple:
    """Return the reviewed selector contract, without projecting any source facts."""
    if task_id not in _CONTRACTS:
        raise ValueError(f"Unsupported task for {PROFILE_VERSION}: {task_id}")
    return deepcopy(_CONTRACTS[task_id])


def build_roster_profile(world: WorldState, task: Task) -> dict:
    """Validate the whole projection before adding distinct, source-linked records.

    No patient is merged with seeded people by name, bed, unit, or label. No
    clinical facts, demographics, arrival instants, or resource allocations are
    inferred. Source YAML and historical benchmark injection stay unchanged.
    """
    contracts = _CONTRACTS.get(task.id)
    if contracts is None:
        raise ValueError(f"Unsupported task for {PROFILE_VERSION}: {task.id}")
    source = deepcopy(task.source_data)
    if not isinstance(source, dict) or source.get("id") != task.id:
        raise ValueError("Profile requires the matching authored task source")
    staged: list[tuple[str, str, dict]] = []
    roster, withheld = [], []
    labels: set[str] = set()
    target_ids: set[str] = set()
    for collection, count, identity, fact, allowed, excluded, source_context in contracts:
        rows = source.get(collection)
        if not isinstance(rows, list) or len(rows) != count:
            raise ValueError(f"{collection} must contain exactly {count} supplied records")
        for index, raw in enumerate(rows):
            pointer = f"{collection}/{index}"
            if not isinstance(raw, dict) or set(raw) - set(allowed) - set(excluded):
                raise ValueError(f"{pointer} contains unreviewed fields or is not a record")
            identity_value = raw.get(identity)
            if type(identity_value) not in (str, int) or not str(identity_value).strip():
                raise ValueError(f"{pointer} requires a nonempty source identity")
            if not isinstance(raw.get(fact), str) or not raw[fact].strip():
                raise ValueError(f"{pointer} requires the authored {fact}")
            observations = {field: deepcopy(raw[field]) for field in allowed if field in raw}
            for field, value in observations.items():
                if type(value) not in (str, int, float) or (
                    isinstance(value, float) and not math.isfinite(value)
                ):
                    raise ValueError(f"{pointer}/{field} must be an authored scalar")
            label = f"Bed {identity_value}" if identity == "bed" else str(identity_value)
            if label in labels:
                raise ValueError(f"Ambiguous duplicate source identity: {label}")
            labels.add(label)
            identity_hash = _digest([PROFILE_VERSION, task.id, collection, identity_value])[
                :12
            ].upper()
            patient_id, encounter_id = f"PAT-{identity_hash}", f"ENC-{identity_hash}"
            if patient_id in target_ids or encounter_id in target_ids:
                raise ValueError("Profile identifier collision")
            target_ids.update((patient_id, encounter_id))
            provenance = {
                "task_id": task.id,
                "source_path": pointer,
                "source_identity": {"field": identity, "value": identity_value},
                "source_context": source_context,
                "profile_version": PROFILE_VERSION,
            }
            patient = {
                "id": patient_id,
                "entity_type": "patient",
                "authored_observations": deepcopy(observations),
                **deepcopy(provenance),
            }
            encounter = {
                "id": encounter_id,
                "entity_type": "encounter",
                "patient_id": patient_id,
                "arrival_time": None,
                "clinical_notes": [],
                "authored_observations": deepcopy(observations),
                **deepcopy(provenance),
            }
            staged.extend(
                (("patient", patient_id, patient), ("encounter", encounter_id, encounter))
            )
            roster.append(
                {
                    "label": label,
                    "patient_id": patient_id,
                    "encounter_id": encounter_id,
                    "source_path": pointer,
                    "source_context": source_context,
                }
            )
            for field in excluded:
                if field in raw:
                    withheld.append(
                        {
                            "path": f"{pointer}/{field}",
                            "reason": (
                                "Answer-bearing, mixed, or unattributed assessment; "
                                "requires source-role review"
                            ),
                        }
                    )
    for kind, entity_id, _ in staged:
        if world.get_entity(kind, entity_id) is not None:
            raise ValueError(f"Profile identifier collision: {entity_id} already exists")
    context = {
        "profile_version": PROFILE_VERSION,
        "task_id": task.id,
        "source_sha256": _digest(source),
        "contract_sha256": _digest([PROFILE_VERSION, contracts]),
        "roster": roster,
        "withheld": withheld,
        "clinical_validation": "not_assessed",
        "benchmark_comparable": False,
    }
    for kind, entity_id, record in staged:
        world.put_entity(kind, entity_id, record)
    return deepcopy(context)
