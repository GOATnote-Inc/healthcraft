"""Task append instructions survive loading, composition, and run provenance."""

from __future__ import annotations

import errno
import json
from dataclasses import replace
from pathlib import Path

import jsonschema
import pytest
import yaml

from healthcraft import eval_runner
from healthcraft.llm import orchestrator, planner
from healthcraft.llm.agent import run_agent_task
from healthcraft.llm.checkpoint import checkpoint_identity
from healthcraft.mcp.server import create_server
from healthcraft.rl.env import HealthCraftEnv
from healthcraft.tasks.loader import load_task
from healthcraft.world.state import WorldState

ROOT = Path(__file__).resolve().parents[2]
APPEND = "Confirm source provenance before documenting findings.\nKeep uncertainty explicit."
COMPONENTS = ("base.txt", "mercy_point.txt", "policies.txt", "tool_reference.txt")


def _document(**fields):
    return {
        "id": "IR-999",
        "category": "information_retrieval",
        "level": 1,
        "title": "Append contract",
        "description": "A synthetic prompt composition task.",
        "criteria": [
            {
                "id": "IR-999-C01",
                "assertion": "Completed the synthetic task",
                "verification": "pattern",
                "check": "complete",
            }
        ],
        **fields,
    }


def _load(tmp_path, **fields):
    path = tmp_path / "task.yaml"
    path.write_text(yaml.safe_dump(_document(**fields)))
    return load_task(path)


@pytest.fixture
def prompt_dir(tmp_path, monkeypatch):
    directory = tmp_path / "prompts"
    directory.mkdir()
    for component in COMPONENTS:
        (directory / component).write_text(f"Contents of {component}\n", encoding="utf-8")
    monkeypatch.setattr(orchestrator, "_SYSTEM_PROMPT_DIR", directory)
    monkeypatch.setattr(eval_runner, "_SYSTEM_PROMPT_DIR", directory)
    monkeypatch.setattr(planner, "_SYSTEM_PROMPT_DIR", directory)
    return directory


@pytest.fixture(params=["live", "simulated"])
def builder(request):
    return (
        orchestrator._load_system_prompt
        if request.param == "live"
        else eval_runner.load_system_prompt
    )


def test_loader_preserves_appended_text_verbatim(tmp_path):
    task = _load(tmp_path, system_prompt_append=APPEND)
    assert getattr(task, "system_prompt_append", None) == APPEND
    assert replace(task, description="Copied task").system_prompt_append == APPEND


def test_each_default_builder_appends_once_without_changing_existing_context(
    tmp_path, prompt_dir, builder
):
    original = builder(_load(tmp_path))
    with_append = builder(_load(tmp_path, system_prompt_append=APPEND))
    assert with_append == original + "\n\n" + APPEND
    assert with_append.count(APPEND) == 1


@pytest.mark.parametrize("override", ["Literal override", "custom.txt"])
def test_append_follows_override_text_or_file(tmp_path, prompt_dir, builder, override):
    (prompt_dir / "custom.txt").write_text("Custom override\n", encoding="utf-8")
    original = builder(_load(tmp_path, system_prompt_override=override))
    task = _load(tmp_path, system_prompt_override=override, system_prompt_append=APPEND)
    assert builder(task) == original + "\n\n" + APPEND


@pytest.mark.parametrize("value", [None, ""])
def test_null_or_empty_append_preserves_default_and_override_bytes(
    tmp_path, prompt_dir, builder, value
):
    for override in (None, "Explicit override"):
        original = builder(_load(tmp_path, system_prompt_override=override))
        task = _load(tmp_path, system_prompt_override=override, system_prompt_append=value)
        assert builder(task) == original


def test_append_is_literal_text_even_when_a_matching_file_exists(tmp_path, prompt_dir, builder):
    (prompt_dir / "policy-append.txt").write_text("Do not read this file as appended text.")
    original = builder(_load(tmp_path))
    task = _load(tmp_path, system_prompt_append="policy-append.txt")
    assert builder(task) == original + "\n\npolicy-append.txt"


def test_append_applies_when_default_prompt_files_are_absent(tmp_path, prompt_dir, builder):
    for component in COMPONENTS:
        (prompt_dir / component).unlink()
    original = builder(_load(tmp_path))
    assert builder(_load(tmp_path, system_prompt_append=APPEND)) == original + "\n\n" + APPEND


@pytest.mark.parametrize("value", [True, 7, [], {}, ["policy"]])
def test_loader_rejects_malformed_append_instead_of_silently_dropping_it(tmp_path, value):
    with pytest.raises(ValueError, match="system_prompt_append.*string.*null"):
        _load(tmp_path, system_prompt_append=value)


def test_task_schema_describes_append_and_rejects_wrong_types():
    schema = json.loads((ROOT / "configs/schemas/task.schema.json").read_text())
    assert schema["properties"].get("system_prompt_append", {}).get("type") == ["string", "null"]
    for valid in (None, "", APPEND):
        jsonschema.validate(_document(system_prompt_append=valid), schema)
    for invalid in (True, 7, [], {}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(_document(system_prompt_append=invalid), schema)


def _identity(task):
    return checkpoint_identity(
        task,
        orchestrator._load_system_prompt(task),
        agent_model="synthetic",
        judge_model=None,
        judge_enabled=False,
        rubric_channel="v10",
        dynamic_state=False,
        overlay={},
        environment="unchanged-test-environment",
        agent_settings={},
        judge_settings={},
    )


def test_appended_instruction_change_invalidates_checkpoint_identity(tmp_path, prompt_dir):
    original = _load(tmp_path, system_prompt_append="Initial instruction")
    changed = _load(tmp_path, system_prompt_append="Different instruction")
    assert _identity(original) != _identity(changed)
    assert _identity(changed) == _identity(changed)


def test_planner_exposes_append_separately_from_component_filenames(tmp_path, prompt_dir):
    _load(tmp_path, system_prompt_append=APPEND)
    plan = planner.plan_evaluation("gpt-test", tasks_dir=tmp_path, results_dir=tmp_path / "results")
    task_plan = plan.to_dict()["task_plans"][0]
    assert task_plan.get("system_prompt_append") == APPEND
    assert task_plan["system_prompt_components"] == list(COMPONENTS)


class CaptureClient:
    _model = "synthetic-capture"

    def __init__(self):
        self.prompts = []

    def chat(self, messages, **kwargs):
        self.prompts.append(messages[0]["content"])
        return {"content": "complete", "tool_calls": [], "stop_reason": "stop"}


def test_composed_append_reaches_agent_and_rl_exactly_once(tmp_path, prompt_dir):
    task = _load(tmp_path, system_prompt_append=APPEND)
    prompt = orchestrator._load_system_prompt(task)
    client = CaptureClient()
    trajectory = run_agent_task(client, task, create_server(WorldState()), prompt)
    assert trajectory.system_prompt.endswith(APPEND)
    assert client.prompts == [prompt]
    assert trajectory.system_prompt.count(APPEND) == 1
    env = HealthCraftEnv(world_config_path=None)
    env.reset(task=task, episode_seed=42, system_prompt=prompt)
    result = env.rollout(client)
    assert result.trajectory.system_prompt == prompt
    assert client.prompts == [prompt, prompt]


def test_simulated_trajectory_records_appended_instructions(tmp_path, prompt_dir, monkeypatch):
    task = _load(tmp_path, system_prompt_append=APPEND)
    monkeypatch.setattr(
        eval_runner,
        "run_task_locally",
        lambda *args, **kwargs: ({"reasoning": "complete"}, WorldState()),
    )
    trajectory = eval_runner.evaluate_and_capture(task, "synthetic", 42, 1, tmp_path / "results")
    assert trajectory.system_prompt.endswith(APPEND)
    assert trajectory.turns[0].content == trajectory.system_prompt


def test_live_resume_rejects_changed_append_before_reusing_scores(
    tmp_path, prompt_dir, monkeypatch
):
    state = {"task": _load(tmp_path, system_prompt_append="First appended instruction")}
    client = CaptureClient()
    monkeypatch.setattr(orchestrator, "load_tasks", lambda _: [state["task"]])
    monkeypatch.setattr(orchestrator, "create_client", lambda *args, **kwargs: client)
    monkeypatch.setattr(orchestrator.WorldSeeder, "seed_world", lambda *args: WorldState())
    monkeypatch.setattr(orchestrator, "environment_digest", lambda _: "fixed-test-environment")
    results = tmp_path / "runs"
    options = dict(
        agent_model="gpt-test",
        agent_key="unused",
        judge_model="claude-test",
        judge_key=None,
        trials=1,
        results_dir=results,
    )
    first = orchestrator.run_frontier_evaluation(**options)
    assert "error" not in first
    assert client.prompts[0].endswith("First appended instruction")
    before = {str(path): path.read_bytes() for path in results.rglob("*") if path.is_file()}
    state["task"] = _load(tmp_path, system_prompt_append="Changed appended instruction")
    second = orchestrator.run_frontier_evaluation(**options)
    assert "checkpoint" in second["error"].lower()
    assert len(client.prompts) == 1
    assert {str(path): path.read_bytes() for path in results.rglob("*") if path.is_file()} == before


def test_explicit_agent_and_rl_prompt_remains_a_complete_pass_through_contract(tmp_path):
    task = _load(tmp_path, system_prompt_append=APPEND)
    supplied = "Caller-supplied complete prompt"
    client = CaptureClient()
    direct = run_agent_task(client, task, create_server(WorldState()), supplied)
    assert direct.system_prompt == supplied
    env = HealthCraftEnv(world_config_path=None)
    env.reset(task=task, episode_seed=42, system_prompt=supplied)
    assert env.rollout(client).trajectory.system_prompt == supplied
    assert client.prompts == [supplied, supplied]


def test_long_literal_override_survives_legacy_path_length_error(
    tmp_path, prompt_dir, builder, monkeypatch
):
    literal = "Literal override instructions. " * 200
    task = _load(tmp_path, system_prompt_override=literal, system_prompt_append=APPEND)
    original_exists = Path.exists

    def legacy_exists(path):
        if path.name == literal:
            # Python 3.10/3.12 propagate this; Python 3.14 exists suppresses it.
            raise OSError(errno.ENAMETOOLONG, "Filename too long")
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", legacy_exists)
    assert builder(task) == literal + "\n\n" + APPEND


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO])
def test_override_lookup_does_not_swallow_unrelated_io_errors(
    tmp_path, prompt_dir, builder, monkeypatch, error_number
):
    task = _load(tmp_path, system_prompt_override="custom.txt", system_prompt_append=APPEND)
    original_exists = Path.exists

    def broken_exists(path):
        if path.name == "custom.txt":
            raise OSError(error_number, "Synthetic file lookup failure")
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", broken_exists)
    with pytest.raises(OSError) as exc:
        builder(task)
    assert exc.value.errno == error_number
