"""A declared frontier cohort must be complete before any provider access."""

from types import SimpleNamespace

import pytest
import yaml

from healthcraft.llm import orchestrator as orch
from healthcraft.tasks.loader import load_tasks
from healthcraft.trajectory import Trajectory
from healthcraft.world.state import WorldState


def authored(identifier):
    return {
        "id": identifier,
        "category": "clinical_reasoning",
        "level": 1,
        "title": "Offline selection fixture",
        "description": "Emit done.",
        "criteria": [
            {
                "id": f"{identifier}-C01",
                "assertion": "Agent emitted done",
                "verification": "pattern",
                "dimension": "documentation_quality",
                "check": "done",
            }
        ],
    }


@pytest.fixture
def cohort(tmp_path):
    root = tmp_path / "tasks"
    root.mkdir()

    def write(name, value):
        (root / name).write_text(yaml.safe_dump(value), encoding="utf-8")

    write("a.yaml", authored("CR-001"))
    write("b.yaml", authored("CR-002"))
    return root, tmp_path / "output", write


def api(cohort, **kwargs):
    directory, output, _ = cohort
    options = {
        "agent_model": "ollama:offline-test",
        "agent_key": "",
        "judge_model": None,
        "judge_key": None,
        "task_filter": "all",
        "trials": 1,
        "tasks_dir": directory,
        "results_dir": output,
    }
    return orch.run_frontier_evaluation(**(options | kwargs))


@pytest.fixture
def forbid_provider(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid cohort reached provider/client boundary")

    monkeypatch.setattr(orch, "create_client", forbidden)
    monkeypatch.setattr(orch, "_api_preflight", forbidden)
    monkeypatch.setattr(orch, "run_agent_task", forbidden)


@pytest.mark.parametrize("trials", [0, -1, True, False, 1.5, "1", None])
def test_api_invalid_trial_count_precedes_output_and_provider(cohort, forbid_provider, trials):
    result = api(cohort, trials=trials)
    assert "trials" in result["error"]
    assert not cohort[1].exists()


@pytest.mark.parametrize("maximum", [0, -1, True, False, 1.5, "1"])
def test_api_invalid_cap_precedes_output_and_provider(cohort, forbid_provider, maximum):
    result = api(cohort, max_tasks=maximum)
    assert "max_tasks" in result["error"]
    assert not cohort[1].exists()


@pytest.mark.parametrize(
    "selection,needle",
    [
        ("CR-001,MISSING", "MISSING"),
        ("MISSING", "MISSING"),
        ("CR-001,CR-001", "Repeated"),
        ("CR-001,", "empty"),
        (",CR-001", "empty"),
        ("CR-001,,CR-002", "empty"),
        ("", "empty"),
        (None, "string"),
    ],
)
def test_api_explicit_roster_is_exact_before_provider(cohort, forbid_provider, selection, needle):
    result = api(cohort, task_filter=selection)
    assert needle in result["error"]
    assert not cohort[1].exists()


def test_missing_id_is_checked_before_intentional_cap(cohort, forbid_provider):
    result = api(cohort, task_filter="CR-001,MISSING", max_tasks=1)
    assert "MISSING" in result["error"]
    assert not cohort[1].exists()


@pytest.mark.parametrize("selection", ["all", "CR-001,CR-002", "CR-001"])
def test_duplicate_authored_id_rejected_even_after_requested_match(
    cohort, forbid_provider, selection
):
    cohort[2]("z-duplicate.yaml", authored("CR-001"))
    result = api(cohort, task_filter=selection)
    assert "Duplicate task ID" in result["error"] and "CR-001" in result["error"]
    assert not cohort[1].exists()


def test_casefold_output_identity_collision_rejected_before_provider(cohort, forbid_provider):
    cohort[2]("z-case-variant.yml", authored("cr-001"))
    result = api(cohort, task_filter="CR-001", max_tasks=1)
    assert "case-insensitive" in result["error"]
    assert "CR-001" in result["error"] and "cr-001" in result["error"]
    assert not cohort[1].exists()


def test_casefold_output_identity_collision_cli_rejected_before_preflight(cohort, forbid_provider):
    cohort[2]("z-case-variant.yml", authored("cr-001"))
    with pytest.raises(SystemExit) as caught:
        orch.main(
            [
                "--agent-model",
                "ollama:offline-test",
                "--tasks",
                "CR-001",
                "--tasks-dir",
                str(cohort[0]),
                "--results-dir",
                str(cohort[1]),
            ]
        )
    assert caught.value.code == 2
    assert not cohort[1].exists()


@pytest.mark.parametrize("selection", ["all", "CR-001,CR-002", "CR-001"])
@pytest.mark.parametrize("malformed", ["id: CR-003\n", "[not: valid", "- list\n"])
def test_whole_supplied_directory_is_strict(cohort, forbid_provider, selection, malformed):
    (cohort[0] / "z-invalid.yml").write_text(malformed)
    result = api(cohort, task_filter=selection)
    assert "z-invalid.yml" in result["error"]
    assert not cohort[1].exists()


@pytest.mark.parametrize("field,value", [("id", 3), ("id", "../outside"), ("category", [])])
def test_malformed_identity_cannot_alias_or_escape_trial_paths(
    cohort, forbid_provider, field, value
):
    row = authored("CR-002")
    row[field] = value
    cohort[2]("b.yaml", row)
    result = api(cohort)
    assert field in result["error"]
    assert not cohort[1].exists()


def test_missing_task_directory_rejected_before_output_provider(cohort, forbid_provider):
    result = api(cohort, tasks_dir=cohort[0] / "missing")
    assert "directory" in result["error"]
    assert not cohort[1].exists()


@pytest.mark.parametrize("missing", [False, True])
def test_empty_or_missing_rubric_rejected_before_provider(cohort, forbid_provider, missing):
    row = authored("CR-002")
    if missing:
        row.pop("criteria")
    else:
        row["criteria"] = []
    cohort[2]("b.yaml", row)
    result = api(cohort, max_tasks=1)
    assert "nonempty criteria" in result["error"]
    assert not cohort[1].exists()


@pytest.mark.parametrize("missing", [False, True])
def test_empty_or_missing_rubric_cli_rejected_before_preflight(cohort, forbid_provider, missing):
    row = authored("CR-002")
    if missing:
        row.pop("criteria")
    else:
        row["criteria"] = []
    cohort[2]("b.yaml", row)
    with pytest.raises(SystemExit) as caught:
        orch.main(
            [
                "--agent-model",
                "ollama:offline-test",
                "--tasks",
                "CR-001",
                "--tasks-dir",
                str(cohort[0]),
                "--results-dir",
                str(cohort[1]),
            ]
        )
    assert caught.value.code == 2
    assert not cohort[1].exists()


def test_cap_does_not_hide_duplicate_or_malformed_authored_task(cohort, forbid_provider):
    cohort[2]("z.yaml", authored("CR-002"))
    assert "Duplicate task ID" in api(cohort, max_tasks=1)["error"]
    cohort[2]("z.yaml", {"id": "CR-003"})
    assert "z.yaml" in api(cohort, max_tasks=1)["error"]
    assert not cohort[1].exists()


@pytest.mark.parametrize("selection", ["CR-001,MISSING", "CR-001,CR-001", "CR-001,"])
def test_cli_checks_roster_before_preflight(cohort, forbid_provider, selection, capsys):
    with pytest.raises(SystemExit) as caught:
        orch.main(
            [
                "--agent-model",
                "ollama:offline-test",
                "--tasks",
                selection,
                "--tasks-dir",
                str(cohort[0]),
                "--results-dir",
                str(cohort[1]),
            ]
        )
    assert caught.value.code == 2
    assert not cohort[1].exists()
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize("malformed", [False, True])
def test_cli_checks_whole_directory_before_preflight(cohort, forbid_provider, malformed):
    cohort[2]("z.yaml", {"id": "CR-003"} if malformed else authored("CR-001"))
    with pytest.raises(SystemExit) as caught:
        orch.main(
            [
                "--agent-model",
                "ollama:offline-test",
                "--tasks",
                "all",
                "--tasks-dir",
                str(cohort[0]),
            ]
        )
    assert caught.value.code == 2
    assert not cohort[1].exists()


@pytest.fixture
def offline_execution(monkeypatch):
    attempts = []
    monkeypatch.setattr(orch, "create_client", lambda *a: SimpleNamespace(_model="offline-test"))
    monkeypatch.setattr(orch, "environment_digest", lambda _: "stable-test-environment")
    monkeypatch.setattr(orch.WorldSeeder, "seed_world", lambda *a: WorldState())

    def agent(client, task, server, prompt):
        attempts.append(task.id)
        trajectory = Trajectory(task.id, "offline-test", 42, prompt)
        trajectory.add_turn("assistant", "done")
        trajectory.metadata.update(stop_reason="stop", termination_kind="complete")
        return trajectory

    monkeypatch.setattr(orch, "run_agent_task", agent)
    return attempts


def test_yaml_yml_exact_selection_sorted_and_resume_unchanged(cohort, offline_execution):
    (cohort[0] / "b.yaml").rename(cohort[0] / "b.yml")
    first = api(cohort, task_filter=" CR-002, CR-001 ", trials=2)
    assert "error" not in first
    assert first["total_tasks"] == 2 and first["total_runs"] == 4
    assert offline_execution == ["CR-001", "CR-001", "CR-002", "CR-002"]
    before = {p: p.read_bytes() for p in cohort[1].rglob("*") if p.is_file()}
    resumed = api(cohort, task_filter="CR-001,CR-002", trials=2)
    assert resumed == first
    assert len(offline_execution) == 4
    assert before == {p: p.read_bytes() for p in cohort[1].rglob("*") if p.is_file()}


def test_valid_cap_applies_after_complete_roster_validation(cohort, offline_execution):
    result = api(cohort, task_filter="CR-002,CR-001", max_tasks=1)
    assert result["total_tasks"] == result["total_runs"] == 1
    assert offline_execution == ["CR-001"]


def test_cap_above_selected_count_retains_all_selected_tasks(cohort, offline_execution):
    result = api(cohort, task_filter="CR-002,CR-001", max_tasks=5)
    assert result["total_tasks"] == result["total_runs"] == 2
    assert offline_execution == ["CR-001", "CR-002"]


def test_legacy_loader_keeps_empty_rubric_when_strict_not_requested(cohort):
    row = authored("CR-002")
    row.pop("criteria")
    cohort[2]("b.yaml", row)
    assert load_tasks(cohort[0])[1].criteria == ()


def test_legacy_loader_still_warns_and_skips_when_strict_not_requested(cohort):
    cohort[2]("z-invalid.yaml", {"id": "CR-003"})
    with pytest.warns(UserWarning, match="Skipped invalid task"):
        selected = load_tasks(cohort[0])
    assert [task.id for task in selected] == ["CR-001", "CR-002"]
