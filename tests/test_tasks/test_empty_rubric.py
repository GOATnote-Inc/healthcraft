"""An empty task rubric is invalid configuration, never an assessed outcome."""

from dataclasses import replace

import pytest

from healthcraft.tasks import evaluator
from healthcraft.tasks.loader import Task, load_task, load_tasks
from healthcraft.tasks.rubrics import check_safety_gate, compute_reward
from healthcraft.world.state import WorldState


def task():
    return Task(
        id="ZERO-001",
        category="clinical_reasoning",
        level=1,
        title="Synthetic marker",
        description="Emit a literal synthetic marker.",
        initial_state={},
        expected_tools=(),
        criteria=(
            {
                "id": "ZERO-001-C01",
                "assertion": "Response contains marker",
                "verification": "pattern",
                "dimension": "documentation_quality",
                "check": "EXPECTED-MARKER",
            },
        ),
        metadata={},
    )


@pytest.mark.parametrize("criteria", [(), [], None, "not a criterion sequence"])
def test_direct_evaluation_rejects_invalid_rubric_before_reading_output(criteria):
    class UntouchedOutput:
        def get(self, *args):
            pytest.fail("Invalid rubric consumed agent output")

    with pytest.raises(ValueError, match="nonempty criteria"):
        evaluator.evaluate_task(replace(task(), criteria=criteria), UntouchedOutput(), WorldState())


@pytest.mark.parametrize("error", [None, "Captured synthetic interruption"])
def test_replay_rejects_empty_rubric_before_world_reconstruction(monkeypatch, error):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid rubric constructed a replay world")

    monkeypatch.setattr(evaluator, "WorldState", forbidden)
    trajectory = {"task_id": "ZERO-001", "turns": [], "criteria_results": [], "error": error}
    with pytest.raises(ValueError, match="nonempty criteria"):
        evaluator.replay_from_trajectory(trajectory, replace(task(), criteria=()))


@pytest.mark.parametrize("criteria_line", ["", "criteria: []\n"])
def test_empty_legacy_task_remains_loadable_but_cannot_be_scored(tmp_path, criteria_line):
    path = tmp_path / "empty.yaml"
    path.write_text(
        "id: ZERO-001\ncategory: clinical_reasoning\nlevel: 1\n"
        "title: Synthetic empty task\ndescription: Task retained for inspection only.\n"
        + criteria_line
    )
    raw = path.read_bytes()
    loaded = load_task(path)
    assert loaded.criteria == ()
    assert load_tasks(tmp_path)[0] == loaded
    with pytest.raises(ValueError, match="nonempty criteria"):
        evaluator.evaluate_task(loaded, {}, WorldState())
    with pytest.raises(ValueError, match="nonempty criteria"):
        load_tasks(tmp_path, strict=True)
    assert path.read_bytes() == raw


@pytest.mark.parametrize("output,expected", [("EXPECTED-MARKER", True), ("different", False)])
def test_nonempty_criterion_has_ordinary_binary_result(output, expected):
    result = evaluator.evaluate_task(task(), {"output": output}, WorldState())
    assert result.passed is expected
    assert result.reward == float(expected)
    assert result.safety_gate_passed is True
    assert len(result.criteria_results) == 1


def test_low_level_empty_reduction_helpers_keep_their_existing_contract():
    assert compute_reward([], []) == 0.0
    assert check_safety_gate([], []) is True
