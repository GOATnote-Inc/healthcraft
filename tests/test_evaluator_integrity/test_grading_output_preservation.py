"""Standalone grades are immutable outputs, including before costly judging."""

from __future__ import annotations

import json
import sys

import pytest
import yaml

from healthcraft.llm import evaluator
from healthcraft.tasks.rubrics import CriterionResult
from healthcraft.trajectory import Trajectory


class CountingJudge:
    _judge_model = "offline-stub"

    def __init__(self):
        self.calls = 0

    def evaluate_criterion(self, criterion, turns):
        self.calls += 1
        return CriterionResult(criterion.id, True, "Synthetic verdict")


@pytest.fixture
def fixture(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "task.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "TEST-001",
                "category": "test",
                "level": 1,
                "title": "Synthetic grading",
                "description": "Original synthetic fixture",
                "criteria": [
                    {
                        "id": "C1",
                        "assertion": "Agent provided the result",
                        "verification": "llm_judge",
                        "dimension": "documentation_quality",
                    }
                ],
            }
        )
    )
    originals = tmp_path / "originals"
    originals.mkdir()
    for name in ("a", "b"):
        trajectory = Trajectory("TEST-001", "offline-agent", 42, "Synthetic")
        trajectory.add_turn("assistant", "A synthetic result")
        trajectory.save(originals / f"{name}.json")
    return tasks, originals, tmp_path / "grading"


def grading_result():
    return evaluator.GradingResult(
        "source.json",
        "TEST-001",
        "offline-agent",
        "offline-stub",
        "default",
        [],
        0.0,
        False,
        True,
        {},
        0.0,
        False,
    )


def invoke_cli(monkeypatch, fixture, *, paths=None, output=None, factory=None):
    tasks, originals, default_output = fixture
    output = output or default_output
    args = [
        "evaluator",
        "--trajectory-dir",
        str(originals),
        "--tasks-dir",
        str(tasks),
        "--output-dir",
        str(output),
        "--judge-model",
        "offline-stub",
        "--judge-key",
        "not-a-key",
    ]
    monkeypatch.setattr(sys, "argv", args)
    if paths is not None:
        monkeypatch.setattr(evaluator, "selected_trajectory_paths", lambda _: paths)
    judge = CountingJudge()
    constructed = []

    def make(*args):
        constructed.append(args)
        return factory(judge) if factory else judge

    monkeypatch.setattr(evaluator, "create_skeptical_judge", make)
    return evaluator.main, judge, constructed


@pytest.mark.parametrize("occupied", ["file", "directory", "dangling_symlink"])
def test_direct_save_refuses_occupied_destination(tmp_path, occupied):
    destination = tmp_path / "grade.json"
    missing = tmp_path / "not-created.json"
    if occupied == "file":
        destination.write_bytes(b"earlier grade\n")
    elif occupied == "directory":
        destination.mkdir()
    else:
        destination.symlink_to(missing)
    with pytest.raises(FileExistsError, match="fresh.*output-dir"):
        grading_result().save(destination)
    if occupied == "file":
        assert destination.read_bytes() == b"earlier grade\n"
    elif occupied == "directory":
        assert destination.is_dir()
    else:
        assert destination.is_symlink() and not missing.exists()


@pytest.mark.parametrize("alongside", [False, True])
def test_file_api_collision_is_detected_before_judge_call(fixture, alongside):
    tasks, originals, output = fixture
    source = originals / "a.json"
    before = source.read_bytes()
    output = originals if alongside else output
    output.mkdir(exist_ok=True)
    destination = output / "a_grading.json"
    destination.write_bytes(b"retained grade")
    judge = CountingJudge()
    with pytest.raises(FileExistsError, match="fresh.*output-dir"):
        evaluator.evaluate_trajectory_file(
            source, judge, tasks_dir=tasks, output_dir=None if alongside else output
        )
    assert judge.calls == 0 and destination.read_bytes() == b"retained grade"
    assert source.read_bytes() == before


def test_file_api_dangling_destination_stops_before_judge(fixture):
    tasks, originals, output = fixture
    output.mkdir()
    target = output / "missing-target"
    destination = output / "a_grading.json"
    destination.symlink_to(target)
    judge = CountingJudge()
    with pytest.raises(FileExistsError):
        evaluator.evaluate_trajectory_file(
            originals / "a.json", judge, tasks_dir=tasks, output_dir=output
        )
    assert judge.calls == 0 and destination.is_symlink() and not target.exists()


@pytest.mark.parametrize("destination", ["b_grading.json", "evaluation_summary.json"])
@pytest.mark.parametrize("dangling", [False, True])
def test_cli_preflights_later_grade_and_summary_before_any_judge_or_write(
    fixture, monkeypatch, destination, dangling
):
    _, originals, output = fixture
    before = {p: p.read_bytes() for p in originals.glob("*.json")}
    output.mkdir()
    occupied = output / destination
    target = output / "not-created"
    if dangling:
        occupied.symlink_to(target)
    else:
        occupied.write_bytes(b"previous evidence")
    run, judge, constructed = invoke_cli(monkeypatch, fixture)
    with pytest.raises(SystemExit) as caught:
        run()
    assert caught.value.code != 0
    assert constructed == [] and judge.calls == 0
    assert not (output / "a_grading.json").exists()
    assert before == {p: p.read_bytes() for p in originals.glob("*.json")}
    if dangling:
        assert occupied.is_symlink() and not target.exists()
    else:
        assert occupied.read_bytes() == b"previous evidence"


def test_cli_rejects_two_inputs_mapping_to_same_grade_before_judge(fixture, monkeypatch):
    _, originals, output = fixture
    second = originals / "nested" / "a.json"
    second.parent.mkdir()
    second.write_bytes((originals / "a.json").read_bytes())
    run, judge, constructed = invoke_cli(monkeypatch, fixture, paths=[originals / "a.json", second])
    with pytest.raises(SystemExit) as caught:
        run()
    assert caught.value.code != 0
    assert constructed == [] and judge.calls == 0 and not output.exists()


def test_cli_rejects_casefold_output_alias_before_judge(fixture, monkeypatch):
    _, originals, output = fixture
    upper = originals / "A.json"
    # No second input must exist: planned output aliases are rejected before
    # input grading, including on case-sensitive test filesystems.
    run, judge, constructed = invoke_cli(monkeypatch, fixture, paths=[originals / "a.json", upper])
    with pytest.raises(SystemExit) as caught:
        run()
    assert caught.value.code != 0
    assert constructed == [] and judge.calls == 0 and not output.exists()


def test_cli_rejects_canonical_alias_destinations_without_making_directories(
    fixture, monkeypatch, tmp_path
):
    tasks, originals, output = fixture
    alias = tmp_path / "originals-alias"
    alias.symlink_to(originals, target_is_directory=True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "evaluator",
            "--trajectory-dir",
            str(originals),
            "--tasks-dir",
            str(tasks),
            "--judge-key",
            "not-a-key",
        ],
    )
    monkeypatch.setattr(
        evaluator, "selected_trajectory_paths", lambda _: [originals / "a.json", alias / "a.json"]
    )
    constructed = []
    monkeypatch.setattr(
        evaluator,
        "create_skeptical_judge",
        lambda *args: constructed.append(args) or CountingJudge(),
    )
    with pytest.raises(SystemExit) as caught:
        evaluator.main()
    assert caught.value.code != 0 and constructed == []
    assert not (originals / "a_grading.json").exists() and not output.exists()


@pytest.mark.parametrize("api", ["file", "cli"])
def test_known_parent_file_rejected_before_judge(fixture, monkeypatch, api):
    tasks, originals, output = fixture
    output.write_bytes(b"not a directory")
    if api == "file":
        judge = CountingJudge()
        with pytest.raises(OSError):
            evaluator.evaluate_trajectory_file(
                originals / "a.json", judge, tasks_dir=tasks, output_dir=output
            )
        assert judge.calls == 0
    else:
        run, judge, constructed = invoke_cli(monkeypatch, fixture)
        with pytest.raises(SystemExit) as caught:
            run()
        assert caught.value.code != 0 and constructed == [] and judge.calls == 0
    assert output.read_bytes() == b"not a directory"


def test_direct_save_race_winner_is_preserved(tmp_path, monkeypatch):
    destination = tmp_path / "grade.json"
    result = grading_result()
    payload = result.to_json()

    def write_competing_result():
        destination.write_bytes(b"race winner")
        return payload

    monkeypatch.setattr(result, "to_json", write_competing_result)
    with pytest.raises(FileExistsError):
        result.save(destination)
    assert destination.read_bytes() == b"race winner"


@pytest.mark.parametrize("destination", ["a_grading.json", "evaluation_summary.json"])
def test_cli_write_time_race_never_overwrites_winner_or_emits_success(
    fixture, monkeypatch, capsys, caplog, destination
):
    _, _, output = fixture

    def create_race(judge):
        output.mkdir(exist_ok=True)
        (output / destination).write_bytes(b"race winner")
        return judge

    run, judge, constructed = invoke_cli(monkeypatch, fixture, factory=create_race)
    caplog.set_level("INFO", logger="healthcraft.evaluator")
    with pytest.raises(SystemExit) as caught:
        run()
    assert caught.value.code != 0 and len(constructed) == 1
    assert (output / destination).read_bytes() == b"race winner"
    assert capsys.readouterr().out == ""
    assert "STANDALONE EVALUATION COMPLETE" not in caplog.text
    if destination == "evaluation_summary.json":
        assert judge.calls == 2  # Newly produced grades survive final summary collision.
        assert (output / "a_grading.json").is_file() and (output / "b_grading.json").is_file()
    else:
        assert judge.calls == 0


def test_fresh_cli_output_grades_normally_and_keeps_originals(fixture, monkeypatch, capsys):
    _, originals, output = fixture
    before = {p: p.read_bytes() for p in originals.glob("*.json")}
    run, judge, constructed = invoke_cli(monkeypatch, fixture)
    run()
    summary = json.loads(capsys.readouterr().out)
    assert summary["total_evaluated"] == 2 and judge.calls == 2 and len(constructed) == 1
    assert json.loads((output / "evaluation_summary.json").read_text()) == summary
    assert json.loads((output / "a_grading.json").read_text())["reward"] == 1.0
    assert before == {p: p.read_bytes() for p in originals.glob("*.json")}


def test_existing_unrelated_output_files_do_not_block_fresh_grade(fixture):
    tasks, originals, output = fixture
    output.mkdir()
    unrelated = output / "notes.txt"
    unrelated.write_bytes(b"retain unrelated file")
    judge = CountingJudge()
    result = evaluator.evaluate_trajectory_file(
        originals / "a.json", judge, tasks_dir=tasks, output_dir=output
    )
    assert result.reward == 1.0 and judge.calls == 1
    assert unrelated.read_bytes() == b"retain unrelated file"
