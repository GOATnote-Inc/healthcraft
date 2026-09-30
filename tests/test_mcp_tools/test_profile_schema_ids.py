"""Advertised lookup schemas must accept deterministic experimental roster IDs."""

import json
from pathlib import Path

import jsonschema
import pytest

from healthcraft.tasks.loader import load_tasks
from healthcraft.tasks.roster_profile import build_roster_profile, supported_roster_tasks
from healthcraft.world.state import WorldState

ROOT = Path(__file__).parents[2]
SCHEMAS = {
    tool["name"]: tool["parameters"]
    for tool in json.loads((ROOT / "configs/mcp-tools.json").read_text())["tools"]
}
LOOKUPS = (
    ("searchEncounters", "patient_id", "PAT"),
    ("getPatientHistory", "patient_id", "PAT"),
    ("getEncounterDetails", "encounter_id", "ENC"),
)


def test_all_33_authored_roster_identities_satisfy_advertised_lookup_schemas():
    tasks = {task.id: task for task in load_tasks(ROOT / "configs/tasks")}
    count = 0
    for task_id in supported_roster_tasks():
        context = build_roster_profile(WorldState(), tasks[task_id])
        for row in context["roster"]:
            count += 1
            for name, field, _ in LOOKUPS:
                jsonschema.validate({field: row[field]}, SCHEMAS[name])
    assert count == 33


@pytest.mark.parametrize("name,field,prefix", LOOKUPS)
@pytest.mark.parametrize("suffix", ["0123ABCD", "012345ABCDEF"])
def test_existing_and_roster_hex_lengths_are_accepted(name, field, prefix, suffix):
    jsonschema.validate({field: f"{prefix}-{suffix}"}, SCHEMAS[name])


@pytest.mark.parametrize("name,field,prefix", LOOKUPS)
@pytest.mark.parametrize(
    "suffix", ["1234567", "123456789", "12345678901", "1234567890123", "0123abcd", "012345abcdef"]
)
def test_unadvertised_lengths_and_lowercase_remain_invalid(name, field, prefix, suffix):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({field: f"{prefix}-{suffix}"}, SCHEMAS[name])
