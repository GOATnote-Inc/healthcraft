"""Public model inputs contain a shared task contract, never private case answers."""

import hashlib
import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from healthcraft.reconciliation.controller import (
    PUBLIC_TOOLS,
    SYSTEM_PROMPT,
    CommandController,
    PilotSettings,
    canonical_json,
    command_format_identity,
)

ROOT = Path(__file__).resolve().parents[2]
TARGET = {"patient_id": "PAT-ABCDEF01", "encounter_id": "ENC-ABCDEF02"}
FIELDS = {
    "instruction",
    "tools",
    "initial_messages",
    "initial_messages_sha256",
    "instruction_sha256",
    "tools_sha256",
    "command_format",
}


@pytest.fixture
def api():
    return importlib.import_module("healthcraft.reconciliation.public_case")


def digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def test_public_tools_are_exact_full_canonical_schemas_and_detached(api):
    catalog = json.loads((ROOT / "configs/mcp-tools.json").read_text())
    expected = sorted(
        (tool for tool in catalog["tools"] if tool["name"] in PUBLIC_TOOLS),
        key=lambda tool: tool["name"],
    )
    actual = api.public_tools()
    assert actual == expected
    assert len(actual) == 5
    actual[0]["parameters"]["properties"].clear()
    actual.pop()
    assert api.public_tools() == expected


@pytest.mark.parametrize("defect", ["missing", "duplicate", "bad_parameters", "duplicate_json"])
def test_invalid_public_discovery_is_rejected(api, tmp_path, monkeypatch, defect):
    catalog = {"tools": api.public_tools()}
    if defect == "missing":
        catalog["tools"].pop()
    elif defect == "duplicate":
        catalog["tools"].append(deepcopy(catalog["tools"][0]))
    elif defect == "bad_parameters":
        catalog["tools"][0]["parameters"] = None
    text = json.dumps(catalog)
    if defect == "duplicate_json":
        text = '{"tools": [], ' + text[1:]
    path = tmp_path / "tools.json"
    path.write_text(text)
    monkeypatch.setattr(api, "TOOLS_PATH", path)
    with pytest.raises(ValueError):
        api.public_tools()


@pytest.mark.parametrize(
    "target",
    [
        None,
        [],
        {},
        {"patient_id": TARGET["patient_id"]},
        TARGET | {"case_id": "REC2-001"},
        TARGET | {"source_ids": []},
        TARGET | {"patient_id": None},
        TARGET | {"patient_id": True},
        TARGET | {"patient_id": "PAT-abcdef01"},
        TARGET | {"patient_id": "PAT-ABCDEF01\n"},
        TARGET | {"patient_id": " PAT-ABCDEF01"},
        TARGET | {"patient_id": "PAT-ABCDEF012"},
        TARGET | {"encounter_id": "ENC-../../private"},
        TARGET | {"encounter_id": "ENC-ABCDEF02 extra"},
    ],
)
def test_invalid_or_private_target_rejected_before_discovery(api, monkeypatch, target):
    def forbidden():
        pytest.fail("Invalid/private target must reject before tool discovery")

    monkeypatch.setattr(api, "public_tools", forbidden)
    with pytest.raises(ValueError):
        api.instruction_for(target)
    with pytest.raises(ValueError):
        api.public_case_context(target)


@pytest.mark.parametrize("suffix", ["ABCDEF01", "ABCDEF012345"])
def test_supported_identifier_lengths(api, suffix):
    target = {"patient_id": "PAT-" + suffix, "encounter_id": "ENC-" + suffix}
    instruction = api.instruction_for(target)
    assert target["patient_id"] in instruction
    assert target["encounter_id"] in instruction


def test_all_eight_cases_share_template_without_case_specific_answers(api):
    templates = set()
    directories = sorted((ROOT / "configs/evaluation/reconciliation_v2").glob("REC2-*"))
    assert len(directories) == 8
    for directory in directories:
        scenario = json.loads((directory / "scenario.json").read_text())
        target = scenario["target"]
        context = api.public_case_context(target)
        instruction = context["instruction"]
        templates.add(
            instruction.replace(target["patient_id"], "<patient_id>").replace(
                target["encounter_id"], "<encounter_id>"
            )
        )
        for forbidden in (
            directory.name,
            scenario["id"],
            scenario["clock"],
            *(patient["first_name"] for patient in scenario["patients"]),
            *(patient["last_name"] for patient in scenario["patients"]),
            *(patient["mrn"] for patient in scenario["patients"]),
            *(
                patient["id"]
                for patient in scenario["patients"]
                if patient["id"] != target["patient_id"]
            ),
            *(row["id"] for row in scenario["encounters"] if row["id"] != target["encounter_id"]),
            "SRC-A",
            "EVENT-",
            "designated_control",
            "observation_source_ids",
            "engineering_authored_independent_review_pending",
        ):
            assert forbidden not in instruction
        assert "expectations" not in context
        assert "scenario" not in context
    assert len(templates) == 1


def test_instruction_defines_literal_scope_and_note_contract_without_extra_actions(api):
    instruction = api.instruction_for(TARGET)
    note = json.loads(instruction.split("```json\n", 1)[1].split("\n```", 1)[0])
    assert note == {
        "schema_version": "healthcraft-reconciliation-note/v1",
        **TARGET,
        "observations": [],
        "unresolved_conflicts": [],
        "scope_exclusions": [],
    }
    for phrase in (
        "closed same-name cohort",
        "before the first write",
        "every source row",
        "source_collection",
        "source_path",
        "null and absent fields",
        "literal timestamp strings",
        "RFC 6901",
        "~0",
        "~1",
        "all members",
        "same event_id",
        "target patient and target encounter",
        "other_patient",
        "other_encounter",
        "not a majority vote",
        "not administration events",
        "pending is not a completed study",
        "exact submitted note text",
        "finish only terminates",
    ):
        assert phrase in " ".join(instruction.split())
    assert '"action":"finish"' in instruction
    assert '"action":"abort"' not in instruction
    assert '"action":"finish","reason"' not in instruction


def test_context_binds_actual_controller_messages_without_model_access(api, monkeypatch):
    import healthcraft.reconciliation.controller as controller

    def forbidden(*args, **kwargs):
        pytest.fail("Public context must not instantiate or call a model client")

    monkeypatch.setattr(controller.RecordingOllamaClient, "__init__", forbidden)
    monkeypatch.setattr(controller.OllamaClient, "__init__", forbidden)
    context = api.public_case_context(TARGET)
    assert set(context) == FIELDS
    assert context["instruction"] == api.instruction_for(TARGET)
    assert context["tools"] == api.public_tools()
    assert context["command_format"] == command_format_identity()
    expected = CommandController(
        context["instruction"],
        context["tools"],
        settings=PilotSettings(max_model_responses=2, max_output_tokens=128, seed=99),
        command_format=command_format_identity(),
    ).snapshot()["messages"]
    assert context["initial_messages"] == expected
    assert expected[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert json.loads(expected[1]["content"]) == {
        "instruction": context["instruction"],
        "tools": context["tools"],
    }
    assert context["initial_messages_sha256"] == digest(expected)
    assert context["tools_sha256"] == digest(context["tools"])
    assert (
        context["instruction_sha256"]
        == hashlib.sha256(context["instruction"].encode("utf-8")).hexdigest()
    )


def test_context_is_detached_and_target_identity_changes_message_binding(api):
    target = deepcopy(TARGET)
    original = api.public_case_context(target)
    changed = deepcopy(original)
    changed["tools"][0]["parameters"].clear()
    changed["initial_messages"][0]["content"] = "mutated"
    changed["command_format"]["sha256"] = "mutated"
    assert api.public_case_context(target) == original
    target["encounter_id"] = "ENC-ABCDEF03"
    next_context = api.public_case_context(target)
    assert next_context["initial_messages_sha256"] != original["initial_messages_sha256"]
    assert next_context["instruction_sha256"] != original["instruction_sha256"]
    assert next_context["tools_sha256"] == original["tools_sha256"]
    assert next_context["command_format"] == original["command_format"]
