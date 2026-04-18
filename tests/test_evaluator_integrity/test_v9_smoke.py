"""v9 rubric channel smoke test.

Validates that the v9 code path works end-to-end:

1. With an empty overlay, v9 produces identical results to v8 on all
   golden trajectories (world_state + pattern channels only; llm_judge
   verdicts are taken from saved trajectory in both cases).
2. The v9 overlay file loads without error.
3. BEFORE/AFTER compound operators are available in the v9 channel.

This test uses NO API calls. It replays saved V8 trajectories through
the evaluator's world_state + pattern code paths.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from healthcraft.tasks.evaluator import (
    _build_agent_output,
    _build_replay_world,
    evaluate_task,
)
from healthcraft.tasks.loader import load_task
from healthcraft.tasks.rubrics import (
    VerificationMethod,
)

REPO = Path(__file__).resolve().parents[2]
GOLDEN_INDEX = REPO / "tests" / "fixtures" / "golden_trajectories" / "index.json"
TASKS_DIR = REPO / "configs" / "tasks"
OVERLAY_PATH = REPO / "configs" / "rubrics" / "v9_deterministic_overlay.yaml"


def _load_golden_index() -> list[dict]:
    """Load the golden trajectory manifest."""
    if not GOLDEN_INDEX.exists():
        pytest.skip("Golden trajectory index not found")
    data = json.loads(GOLDEN_INDEX.read_text())
    return data.get("trajectories", [])


def _load_trajectory(entry: dict) -> dict | None:
    """Load a trajectory JSON from the manifest entry."""
    traj_path = REPO / entry["trajectory_path"]
    if not traj_path.exists():
        return None
    return json.loads(traj_path.read_text())


def _find_task(task_id: str):
    """Find and load a task by ID."""
    for yaml_path in sorted(TASKS_DIR.rglob("*.yaml")):
        raw = yaml.safe_load(yaml_path.read_text())
        if raw.get("id") == task_id:
            return load_task(yaml_path)
    return None


def _parse_criteria(raw_criteria):
    """Parse raw criteria dicts into Criterion objects."""
    from healthcraft.tasks.rubrics import Criterion

    criteria = []
    for raw in raw_criteria:
        criteria.append(
            Criterion(
                id=raw["id"],
                assertion=raw.get("assertion", ""),
                dimension=raw.get("dimension", ""),
                safety_critical=raw.get("safety_critical", False),
                verification=VerificationMethod(raw.get("verification", "world_state")),
                check=raw.get("check", ""),
            )
        )
    return criteria


class TestV9OverlayLoads:
    """The v9 overlay file loads and parses correctly."""

    def test_overlay_file_exists(self) -> None:
        assert OVERLAY_PATH.exists(), f"Missing: {OVERLAY_PATH}"

    def test_overlay_parses(self) -> None:
        data = yaml.safe_load(OVERLAY_PATH.read_text())
        assert isinstance(data, dict)
        assert "overlays" in data

    def test_overlay_is_populated(self) -> None:
        """The overlay contains curated entries. Every entry has the required
        schema fields used by the orchestrator's overlay application logic."""
        data = yaml.safe_load(OVERLAY_PATH.read_text())
        overlays = data.get("overlays", [])
        assert len(overlays) > 0, "Overlay must contain entries after population"
        required_fields = {"criterion_id", "verification", "check", "migration_confidence"}
        for entry in overlays:
            missing = required_fields - set(entry.keys())
            assert not missing, f"Entry {entry.get('criterion_id')} missing {missing}"
            assert entry["verification"] == "world_state"
            assert entry["check"].strip(), f"Empty check in {entry['criterion_id']}"
            assert entry["migration_confidence"] in {"high", "medium"}


class TestV9ChannelIdenticalToV8:
    """With empty overlay, v9 produces identical world_state/pattern results."""

    @pytest.fixture()
    def golden_entries(self) -> list[dict]:
        entries = _load_golden_index()
        if not entries:
            pytest.skip("No golden trajectories in manifest")
        return entries

    def test_v9_matches_v8_on_goldens(self, golden_entries: list[dict]) -> None:
        """Core smoke test: v8 and v9 produce identical world_state results."""
        tested = 0
        for entry in golden_entries:
            traj = _load_trajectory(entry)
            if traj is None:
                continue

            task = _find_task(entry["task_id"])
            if task is None:
                continue

            # Build replay world and agent output
            world_v8 = _build_replay_world(traj)
            world_v9 = _build_replay_world(traj)
            agent_output = _build_agent_output(traj)

            # Evaluate with v8 channel
            result_v8 = evaluate_task(task, agent_output, world_v8, rubric_channel="v8")

            # Evaluate with v9 channel (empty overlay = no criterion rewrites)
            result_v9 = evaluate_task(task, agent_output, world_v9, rubric_channel="v9")

            # Compare world_state + pattern criteria only (llm_judge is
            # not exercised by evaluate_task -- it returns unsatisfied)
            criteria = _parse_criteria(task.criteria)
            deterministic_ids = {
                c.id
                for c in criteria
                if c.verification in (VerificationMethod.WORLD_STATE, VerificationMethod.PATTERN)
            }

            v8_det = {
                r.criterion_id: r.satisfied
                for r in result_v8.criteria_results
                if r.criterion_id in deterministic_ids
            }
            v9_det = {
                r.criterion_id: r.satisfied
                for r in result_v9.criteria_results
                if r.criterion_id in deterministic_ids
            }

            assert v8_det == v9_det, (
                f"v8/v9 mismatch on {entry['task_id']}: "
                f"diff = {set(v8_det.items()) ^ set(v9_det.items())}"
            )
            tested += 1

        assert tested >= 5, f"Only tested {tested} trajectories (need >= 5)"

    def test_v9_reward_matches_v8_on_untouched_tasks(self, golden_entries: list[dict]) -> None:
        """Reward is identical between v8 and v9 for tasks whose criteria are
        NOT in the overlay. Tasks that are overlaid may legitimately differ."""
        from healthcraft.llm.orchestrator import _load_overlay

        overlay_ids = set(_load_overlay("v9").keys())
        tested = 0
        for entry in golden_entries[:20]:
            traj = _load_trajectory(entry)
            if traj is None:
                continue

            task = _find_task(entry["task_id"])
            if task is None:
                continue

            task_crit_ids = {c["id"] for c in task.criteria}
            if task_crit_ids & overlay_ids:
                continue  # overlaid -- reward may differ by design

            world_v8 = _build_replay_world(traj)
            world_v9 = _build_replay_world(traj)
            agent_output = _build_agent_output(traj)

            result_v8 = evaluate_task(task, agent_output, world_v8, rubric_channel="v8")
            result_v9 = evaluate_task(task, agent_output, world_v9, rubric_channel="v9")

            assert abs(result_v8.reward - result_v9.reward) < 1e-12, (
                f"Reward mismatch on non-overlaid task {entry['task_id']}: "
                f"v8={result_v8.reward}, v9={result_v9.reward}"
            )
            tested += 1

        assert tested >= 3, f"Only tested {tested} non-overlaid trajectories"


class TestV9OrchestratorOverlayLogic:
    """The orchestrator's v9 overlay application logic works correctly."""

    def test_load_v9_overlay_returns_populated_dict(self) -> None:
        """_load_overlay('v9') returns a dict keyed by criterion_id with
        verification/check entries for every overlay row."""
        from healthcraft.llm.orchestrator import _load_overlay

        overlay = _load_overlay("v9")
        assert len(overlay) > 0
        # Every loaded entry must have the two fields the orchestrator reads.
        for crit_id, entry in overlay.items():
            assert entry.get("verification") == "world_state", crit_id
            assert entry.get("check", "").strip(), crit_id

    def test_valid_rubric_channels(self) -> None:
        """v8, v9, and v10 are all valid channel values."""
        from healthcraft.llm.orchestrator import _VALID_RUBRIC_CHANNELS

        assert "v8" in _VALID_RUBRIC_CHANNELS
        assert "v9" in _VALID_RUBRIC_CHANNELS
        assert "v10" in _VALID_RUBRIC_CHANNELS
