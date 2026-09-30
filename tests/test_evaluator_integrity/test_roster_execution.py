"""Real roster witnesses must retain provenance and never become clinical scores."""

from __future__ import annotations

import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from healthcraft.llm.checkpoint import content_digest
from healthcraft.mcp.server import create_server
from healthcraft.tasks.history_execution import ExecutionRecorder
from healthcraft.tasks.loader import load_task
from healthcraft.tasks.roster_profile import build_roster_profile, supported_roster_tasks
from healthcraft.world.state import WorldState

ROOT = Path(__file__).resolve().parents[2]


def _module():
    return importlib.import_module("healthcraft.tasks.roster_execution")


def test_actual_cohort_retrieves_all_33_members_with_66_audited_calls():
    report = _module().run_roster_references(world_factory=WorldState)
    assert report["mechanical_passed"] is True
    assert report["task_ids"] == list(supported_roster_tasks())
    assert report["total_members"] == 33 and report["total_tool_calls"] == 66
    assert report["benchmark_score"] is None
    assert report["coverage"]["measured_clinical_criteria"] == 0
    assert report["coverage"]["measured_safety_criteria"] == 0
    assert report["provenance_before"] == report["provenance_after"]
    for task in report["tasks"]:
        assert task["verification"]["mechanical_passed"] is True
        assert task["world_preparation"] == "caller_supplied"
        assert task["benchmark_score"] is None
        assert task["trace_sha256"] == content_digest(task["calls"])
        assert len(task["calls"]) == 2 * len(task["context"]["roster"])
        assert [c["name"] for c in task["calls"]] == [
            "getEncounterDetails",
            "getPatientHistory",
        ] * len(task["context"]["roster"])
        assert [c["audit_index"] for c in task["calls"]] == list(range(len(task["calls"])))
    assert json.loads(json.dumps(report, allow_nan=False)) == report


def test_controller_receives_only_ids_and_actual_source_values_come_from_tools(monkeypatch):
    module = _module()
    real = module.execute_roster_reference
    passed_rosters = []

    def recording_controller(recorder, *, roster):
        assert all(set(member) == {"patient_id", "encounter_id"} for member in roster)
        passed_rosters.append(deepcopy(roster))
        return real(recorder, roster=roster)

    monkeypatch.setattr(module, "execute_roster_reference", recording_controller)
    report = module.run_roster_reference("CC-022", world=WorldState())
    assert len(passed_rosters[0]) == 4
    source = load_task(ROOT / "configs/tasks/clinical_communication/task_022_nurse_delegation.yaml")
    for index, raw in enumerate(source.source_data["patients_requiring_action"]):
        for call in report["calls"][index * 2 : index * 2 + 2]:
            assert call["response"]["data"]["authored_observations"] == {
                "bed": raw["bed"],
                "summary": raw["summary"],
            }


def test_default_cohort_seeds_a_fresh_mercy_point_world_for_each_task(monkeypatch):
    module = _module()
    seen = []
    original = module.WorldSeeder.seed_world

    def seed(self, path):
        world = original(self, path)
        assert world.entity_counts["patient"] > 0
        seen.append(world)
        return world

    monkeypatch.setattr(module.WorldSeeder, "seed_world", seed)
    report = module.run_roster_references(seed=42)
    assert len(seen) == len({id(world) for world in seen}) == 6
    assert all(task["world_preparation"] == "seeded_mercy_point" for task in report["tasks"])


def _controller_fixture():
    module = _module()
    task = load_task(ROOT / "configs/tasks/clinical_communication/task_022_nurse_delegation.yaml")
    world = WorldState()
    context = build_roster_profile(world, task)
    server = create_server(world)
    recorder = ExecutionRecorder(server, world)
    roster = [
        {key: row[key] for key in ("patient_id", "encounter_id")} for row in context["roster"]
    ]
    return module, server, recorder, roster


@pytest.mark.parametrize("tool_name", ["getEncounterDetails", "getPatientHistory"])
@pytest.mark.parametrize("kind", ["failed", "missing", "wrong_owner", "truncated", "changed_fact"])
def test_controller_rejects_failed_missing_misattributed_or_truncated_responses(tool_name, kind):
    module, server, recorder, roster = _controller_fixture()
    original = server.call_tool

    def damaged(name, params):
        response = original(name, params)
        if name != tool_name:
            return response
        if kind == "failed":
            return {"status": "error", "code": "fixture_error"}
        if kind == "missing":
            return {"status": "ok"}
        data = response["data"]
        if kind == "wrong_owner":
            data["patient_id" if name == "getEncounterDetails" else "id"] = "PAT-WRONG"
        elif kind == "truncated":
            data["authored_observations"] = {}
        else:
            data["authored_observations"]["summary"] = "Different value"
        return response

    server.call_tool = damaged
    with pytest.raises(ValueError, match="(retrieval|response|observations)"):
        module.execute_roster_reference(recorder, roster=roster)


def test_context_observations_cannot_be_given_to_the_controller():
    module, _, recorder, roster = _controller_fixture()
    roster[0]["authored_observations"] = {"summary": "oracle"}
    with pytest.raises(ValueError, match="IDs only"):
        module.execute_roster_reference(recorder, roster=roster)


@pytest.mark.parametrize("section", ["source_sha256", "runtime_sha256", "environment_sha256"])
def test_provenance_drift_aborts_the_whole_cohort(monkeypatch, section):
    module = _module()
    original = module._provenance
    calls = 0

    def changed():
        nonlocal calls
        result = original()
        calls += 1
        if calls > 1:
            result[section] = "0" * 64
        return result

    monkeypatch.setattr(module, "_provenance", changed)
    with pytest.raises(ValueError, match="provenance.*changed"):
        module.run_roster_references(world_factory=WorldState)


def test_cli_preserves_existing_artifact_without_starting_execution(tmp_path, monkeypatch):
    cli = importlib.import_module("scripts.certify_roster_tasks")
    output = tmp_path / "immutable.json"
    output.write_text("existing evidence\n")
    monkeypatch.setattr(cli, "run_roster_references", lambda **kwargs: pytest.fail("ran"))
    assert cli.main(["--output", str(output)]) == 2
    assert output.read_text() == "existing evidence\n"


def test_cli_writes_recomputable_provenance_and_trace_hashes(tmp_path, monkeypatch):
    module = _module()
    cli = importlib.import_module("scripts.certify_roster_tasks")
    monkeypatch.setattr(
        cli,
        "run_roster_references",
        lambda **kwargs: module.run_roster_references(world_factory=WorldState, **kwargs),
    )
    output = tmp_path / "new.json"
    assert cli.main(["--output", str(output)]) == 0
    report = json.loads(output.read_text())
    before = report["provenance_before"]
    assert before["source_sha256"] == content_digest(before["source_hashes"])
    assert before["runtime_sha256"] == content_digest(before["runtime"])
    import hashlib

    for relative, expected in before["source_hashes"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_cli_provenance_failure_creates_no_report(tmp_path, monkeypatch):
    cli = importlib.import_module("scripts.certify_roster_tasks")
    output = tmp_path / "absent.json"

    def drift(**kwargs):
        raise ValueError("Cohort provenance changed during execution")

    monkeypatch.setattr(cli, "run_roster_references", drift)
    assert cli.main(["--output", str(output)]) == 2
    assert not output.exists()


def test_consistent_but_invented_observations_fail_independent_verification_and_cli(
    tmp_path, monkeypatch
):
    module = _module()
    cli = importlib.import_module("scripts.certify_roster_tasks")
    original = module.build_roster_profile

    def invented(world, task):
        context = original(world, task)
        if task.id == "CC-022":
            member = context["roster"][0]
            for kind in ("patient", "encounter"):
                record = world.get_entity(kind, member[f"{kind}_id"])
                record["authored_observations"]["summary"] = "Consistent invented source fact"
        return context

    monkeypatch.setattr(module, "build_roster_profile", invented)
    monkeypatch.setattr(
        cli,
        "run_roster_references",
        lambda **kwargs: module.run_roster_references(world_factory=WorldState, **kwargs),
    )
    output = tmp_path / "failed.json"
    assert cli.main(["--output", str(output)]) == 1
    report = json.loads(output.read_text())
    assert report["mechanical_passed"] is False
    assert report["benchmark_score"] is None
    assert report["tasks"][0]["verification"]["checks"]["source_facts_concordant"] is False


def test_cli_exclusive_create_preserves_a_file_created_during_execution(tmp_path, monkeypatch):
    cli = importlib.import_module("scripts.certify_roster_tasks")
    output = tmp_path / "race.json"

    def completed(**kwargs):
        output.write_text("another completed writer\n")
        return {"mechanical_passed": True}

    monkeypatch.setattr(cli, "run_roster_references", completed)
    assert cli.main(["--output", str(output)]) == 2
    assert output.read_text() == "another completed writer\n"
