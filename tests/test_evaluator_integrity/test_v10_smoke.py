"""v10 rubric channel smoke test.

Validates the v10 code path:

1. `_load_overlay('v10')` returns v9 entries plus v10 entries (v10 is
   additive on top of v9).
2. `replay_from_trajectory(..., rubric_channel='v10')` rewrites the
   criterion's verification method from ``llm_judge`` to ``world_state``
   and re-derives the verdict against the reconstructed audit log.
3. `replay_from_trajectory` with the default channel=v8 remains
   byte-identical to pre-v10 behavior (no overlay applied).
4. The v10 YAML schema matches v9: every entry has the required fields
   the orchestrator reads at runtime.

No API calls. Exercises world_state code paths only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from healthcraft.llm.orchestrator import _VALID_RUBRIC_CHANNELS, _load_overlay
from healthcraft.tasks.evaluator import (
    _apply_overlay_to_task,
    replay_from_trajectory,
)
from healthcraft.tasks.loader import load_task

REPO = Path(__file__).resolve().parents[2]
GOLDEN_INDEX = REPO / "tests" / "fixtures" / "golden_trajectories" / "index.json"
TASKS_DIR = REPO / "configs" / "tasks"
V9_OVERLAY = REPO / "configs" / "rubrics" / "v9_deterministic_overlay.yaml"
V10_OVERLAY = REPO / "configs" / "rubrics" / "v10_deterministic_overlay.yaml"


def _find_task(task_id: str):
    for yaml_path in sorted(TASKS_DIR.rglob("*.yaml")):
        raw = yaml.safe_load(yaml_path.read_text())
        if raw.get("id") == task_id:
            return load_task(yaml_path)
    return None


class TestV10OverlayFile:
    """The v10 overlay file exists and parses with the expected schema."""

    def test_v10_overlay_exists(self) -> None:
        assert V10_OVERLAY.exists(), f"Missing: {V10_OVERLAY}"

    def test_v10_overlay_schema(self) -> None:
        data = yaml.safe_load(V10_OVERLAY.read_text())
        assert isinstance(data, dict)
        assert data.get("overlays"), "v10 overlay must have entries"
        required = {"criterion_id", "verification", "check", "migration_confidence"}
        for entry in data["overlays"]:
            missing = required - set(entry.keys())
            assert not missing, f"{entry.get('criterion_id')} missing {missing}"
            assert entry["verification"] == "world_state"
            assert entry["check"].strip()
            assert entry["migration_confidence"] in {"high", "medium"}


class TestV10Loader:
    """_load_overlay composes v9 + v10."""

    def test_v10_valid_channel(self) -> None:
        assert "v10" in _VALID_RUBRIC_CHANNELS

    def test_v10_includes_v9_entries(self) -> None:
        v9 = _load_overlay("v9")
        v10 = _load_overlay("v10")
        assert set(v9).issubset(set(v10)), (
            "v10 must include every v9 criterion_id (v10 composes on top of v9)"
        )

    def test_v10_adds_new_entries(self) -> None:
        v9 = _load_overlay("v9")
        v10 = _load_overlay("v10")
        assert len(v10) > len(v9), "v10 must add new criterion_ids beyond v9"

    def test_v8_loads_nothing(self) -> None:
        assert _load_overlay("v8") == {}

    def test_v10_file_entries_all_have_world_state(self) -> None:
        v10 = _load_overlay("v10")
        for crit_id, entry in v10.items():
            assert entry["verification"] == "world_state", crit_id
            assert entry["check"].strip(), crit_id


class TestApplyOverlayToTask:
    """_apply_overlay_to_task rewrites criteria that match the overlay."""

    def test_v8_does_not_rewrite(self) -> None:
        """CC-001 has CC-001-C09 in v10; v8 channel must leave it untouched."""
        task = _find_task("CC-001")
        if task is None:
            pytest.skip("CC-001 task not found")
        before = {c["id"]: dict(c) for c in task.criteria}
        after_task = _apply_overlay_to_task(task, "v8")
        after = {c["id"]: dict(c) for c in after_task.criteria}
        assert before == after, "v8 channel must not rewrite criteria"

    def test_v10_rewrites_sulfa_criterion(self) -> None:
        """CC-001-C09 ("did NOT prescribe sulfa-based antibiotic") must be
        promoted from llm_judge to world_state under v10."""
        task = _find_task("CC-001")
        if task is None:
            pytest.skip("CC-001 task not found")
        rewritten = _apply_overlay_to_task(task, "v10")
        cc001_c09 = next(c for c in rewritten.criteria if c["id"] == "CC-001-C09")
        assert cc001_c09["verification"] == "world_state"
        assert "sulfa" in cc001_c09["check"].lower()

    def test_overlay_preserves_non_overlaid_criteria(self) -> None:
        """Criteria not in the overlay must survive unchanged."""
        task = _find_task("CC-001")
        if task is None:
            pytest.skip("CC-001 task not found")
        overlay = _load_overlay("v10")
        rewritten = _apply_overlay_to_task(task, "v10")
        for orig, new in zip(task.criteria, rewritten.criteria, strict=True):
            if orig["id"] in overlay:
                continue
            assert orig == new, f"non-overlaid criterion {orig['id']} was mutated"


class TestReplayChannel:
    """replay_from_trajectory honors the rubric_channel parameter."""

    @pytest.fixture()
    def golden_entry(self) -> dict | None:
        if not GOLDEN_INDEX.exists():
            pytest.skip("golden index missing")
        data = json.loads(GOLDEN_INDEX.read_text())
        entries = data.get("trajectories", [])
        if not entries:
            pytest.skip("golden index empty")
        # Pick a CC-001 trajectory if one exists, otherwise first available.
        for e in entries:
            if e.get("task_id") == "CC-001":
                return e
        return entries[0]

    def test_replay_default_channel_is_v8(self, golden_entry: dict) -> None:
        """Default replay call signature (no rubric_channel arg) == v8 behavior."""
        traj_path = REPO / golden_entry["trajectory_path"]
        if not traj_path.exists():
            pytest.skip("golden trajectory missing on disk")
        traj = json.loads(traj_path.read_text())
        task = _find_task(golden_entry["task_id"])
        if task is None:
            pytest.skip(f"task {golden_entry['task_id']} not found")

        default = replay_from_trajectory(traj, task)
        v8 = replay_from_trajectory(traj, task, rubric_channel="v8")
        assert default.reward == v8.reward
        assert default.passed == v8.passed
        assert default.safety_gate_passed == v8.safety_gate_passed

    def test_replay_v10_promotes_overlaid_criterion(self, golden_entry: dict) -> None:
        """For an overlaid criterion, v10 replay must mark the result as
        derived from world_state (fresh) rather than saved judge verdict.
        The simplest observable: the v10 result's criterion_id set equals
        the v8 result's set, but the satisfied flag is re-derived from the
        reconstructed audit log. We only assert no crash and the expected
        criterion count."""
        traj_path = REPO / golden_entry["trajectory_path"]
        if not traj_path.exists():
            pytest.skip("golden trajectory missing on disk")
        traj = json.loads(traj_path.read_text())
        task = _find_task(golden_entry["task_id"])
        if task is None:
            pytest.skip(f"task {golden_entry['task_id']} not found")

        v8 = replay_from_trajectory(traj, task, rubric_channel="v8")
        v10 = replay_from_trajectory(traj, task, rubric_channel="v10")

        v8_ids = {r.criterion_id for r in v8.criteria_results}
        v10_ids = {r.criterion_id for r in v10.criteria_results}
        assert v8_ids == v10_ids, "overlay must not change the criterion id set"

    def test_replay_v8_byte_identical_to_pre_v10(self, golden_entry: dict) -> None:
        """V8 replay path must remain byte-identical to what the golden
        trajectory recorded (this is the existing contract; v10 changes
        must not regress it)."""
        traj_path = REPO / golden_entry["trajectory_path"]
        if not traj_path.exists():
            pytest.skip("golden trajectory missing on disk")
        traj = json.loads(traj_path.read_text())
        task = _find_task(golden_entry["task_id"])
        if task is None:
            pytest.skip(f"task {golden_entry['task_id']} not found")

        result = replay_from_trajectory(traj, task, rubric_channel="v8")
        assert result.reward == pytest.approx(traj["reward"])
        assert result.passed == traj["passed"]
        assert result.safety_gate_passed == traj.get("safety_gate_passed", True)


class TestV10NoInvertedSemantics:
    """Post-audit guard: entries with known-bad patterns must not be present.

    The 2026-04-18 replay audit flagged 5 entries as semantic inversions or
    wrong-drug matches; they were removed. This test locks the removal in
    so a future regenerator doesn't re-introduce them."""

    BANNED_IDS = frozenset(
        {
            "IR-007-C05",
            "IR-017-C04",
            "IR-028-C03",
            "TR-002-C05",
            "TR-025-C11",
        }
    )

    def test_banned_entries_not_in_v10(self) -> None:
        v10 = _load_overlay("v10")
        intersect = self.BANNED_IDS & set(v10)
        assert not intersect, (
            f"These criterion_ids were removed after the 2026-04-18 audit "
            f"(semantic inversion / wrong-drug match) and must not reappear "
            f"in v10: {sorted(intersect)}"
        )
