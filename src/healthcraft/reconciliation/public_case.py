"""Pure public inputs for the synthetic reconciliation development workflow.

Only target identifiers enter this module. It neither loads case data or private
expectations nor constructs a model client. Hashes identify public inputs; they
are not an assessment of an attempt or an independent authenticity guarantee.
"""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from pathlib import Path

from healthcraft.reconciliation.controller import (
    PUBLIC_TOOLS,
    CommandController,
    canonical_json,
    command_format_identity,
)
from healthcraft.reconciliation.terminal import _json_object

TOOLS_PATH = Path(__file__).resolve().parents[3] / "configs/mcp-tools.json"

_INSTRUCTION = """Synthetic source-record reconciliation

Target patient: $PATIENT_ID
Target encounter: $ENCOUNTER_ID

This is a mechanical record attribution and documentation exercise. It does not
ask for a diagnosis, treatment recommendation, clinical truth judgment or safety
assessment. Use only the supplied public tools and their returned records.

Discovery and scope
Retrieve the target patient's getPatientHistory record and use its returned full
name with searchPatients to discover the closed same-name cohort. Retrieve each
returned patient's encounters with searchEncounters, then getEncounterDetails
for every returned encounter. Verify patient and encounter ownership from the
returned identifiers. Retrieve all these source records before the first write.
Do not exclude encounters using date or status filters: an unknown arrival time
or a prior encounter does not make its source assertions disappear. Names alone
do not establish identity. Do not treat a full search page or an error as proof
of complete retrieval.

Source conservation
Read original assertions from source_data in the returned authored_care and
imaging projections. The source collections are active_orders,
current_management, treatments_given and imaging_pending. Keep every source row
with a source_id, together with its actual patient and encounter ownership.
Use the original row, not a normalized projection, as the source value. Preserve
every field, scalar type, literal timestamp strings, offsets, null and absent
fields exactly. Do not replace an unknown value with a guess, a current time,
an encounter arrival time or a default status. Plans and requests are not
administration events; an empty administration list does not erase source
reports. Imaging pending is not a completed study or a finding.

Each observation has exactly these fields: source_id, patient_id, encounter_id,
source_collection, source_path and source. The source field is the entire
original row. Construct source_path from the projection's source_path by
removing only the leading /patient namespace and then following source_data to
that row. Preserve original array indices and object keys. Use RFC 6901 escaping
for each object key: encode ~ as ~0 and / as ~1. A path is relative to that
encounter's original patient_data; it is not a globally unique source identity.

Note contract
Write one JSON note with exactly the following top-level fields. The empty
arrays below show the layout only; populate them from the retrieved records.

```json
{
  "schema_version": "healthcraft-reconciliation-note/v1",
  "patient_id": "$PATIENT_ID",
  "encounter_id": "$ENCOUNTER_ID",
  "observations": [],
  "unresolved_conflicts": [],
  "scope_exclusions": []
}
```

observations: include every source row belonging to the target patient and target
encounter, exactly once, with the complete source descriptor specified above.
Do not include a prior encounter or another patient's row as a target observation.

unresolved_conflicts: consider treatments_given reports from the target patient
and target encounter only. Group reports by the same event_id only when it is
explicitly present and nonempty. If a group has
both literal reported_status values administered and not_administered, retain
all members of that event group in one object with exactly source_ids (an array
of their source identifiers), event_id and field (the string reported_status).
This is not a majority vote: do not choose which report is true or discard any
member. Different event identifiers remain separate even when item or time is
identical. Reused event identifiers outside the target patient and target encounter
do not join the group. Unknown status alone does not establish opposing reports.

scope_exclusions: include every retrieved source row outside the target encounter,
exactly once, with exactly source_id, patient_id, encounter_id and reason. Use
reason other_patient when its patient differs from the target, otherwise use
other_encounter. Preserve those rows' identities without copying their assertions
into observations. The number of observations, exclusions and conflict groups
must follow the returned records, not a preset count.

Persistence and readback
Use updateEncounter on the target encounter with notes containing the JSON note
encoded as a string and a nonempty idempotency_key. Create exactly one new note.
Do not change other encounter fields or any other patient's records. If repeating
a write, use the identical full request and idempotency key; changing the request
under that key or adding a correction note does not satisfy this one-note task.
After the write, retrieve the target encounter with getEncounterDetails. Confirm
the returned target patient and encounter and the exact submitted note text in
clinical_notes. A write acknowledgement alone does not establish stored content.

Use the single JSON command protocol in the system instruction. After the write
and readback, respond with {"action":"finish"}. This finish only terminates the
interaction; independent verification determines whether the persisted result
satisfies the exercise. Do not add a reason, success claim or clinical assessment
to the finish command.
"""


def public_tools() -> list[dict]:
    """Return detached, unmodified canonical schemas for the five public tools."""
    catalog = _json_object(TOOLS_PATH.read_bytes())
    entries = catalog.get("tools")
    if type(entries) is not list or any(
        type(entry) is not dict or type(entry.get("name")) is not str for entry in entries
    ):
        raise ValueError("Public tool catalog is malformed")
    selected = [entry for entry in entries if entry["name"] in PUBLIC_TOOLS]
    if (
        len(selected) != len(PUBLIC_TOOLS)
        or {entry["name"] for entry in selected} != PUBLIC_TOOLS
        or any(type(entry.get("parameters")) is not dict for entry in selected)
    ):
        raise ValueError("Exactly five complete public tool schemas are required")
    return sorted(deepcopy(selected), key=lambda entry: entry["name"])


def instruction_for(target: dict) -> str:
    """Instantiate the shared instruction using only strict target identifiers."""
    if type(target) is not dict or set(target) != {"patient_id", "encounter_id"}:
        raise ValueError("Target must contain only patient_id and encounter_id")
    for field, prefix in (("patient_id", "PAT"), ("encounter_id", "ENC")):
        value = target[field]
        if (
            type(value) is not str
            or re.fullmatch(rf"{prefix}-(?:[A-F0-9]{{8}}|[A-F0-9]{{12}})", value) is None
        ):
            raise ValueError(f"Invalid target {field}")
    return _INSTRUCTION.replace("$PATIENT_ID", target["patient_id"]).replace(
        "$ENCOUNTER_ID", target["encounter_id"]
    )


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def public_case_context(target: dict) -> dict:
    """Build exact model-visible messages and identities without model access."""
    instruction = instruction_for(target)
    tools = public_tools()
    command_format = command_format_identity()
    messages = CommandController(instruction, tools, command_format=command_format).snapshot()[
        "messages"
    ]
    return {
        "instruction": instruction,
        "tools": tools,
        "initial_messages": messages,
        "initial_messages_sha256": _digest(messages),
        "instruction_sha256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
        "tools_sha256": _digest(tools),
        "command_format": command_format,
    }
