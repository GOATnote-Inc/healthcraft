"""v11 rubric channel smoke test.

Validates the v11 code path:

1. ``_load_overlay('v11')`` composes v9 + v10 + v11 entries (v11 is
   additive on top of v10 and may be empty by default).
2. The v11 YAML is present and parses cleanly with the expected schema
   (``overlays`` present, list-shaped; entries, if any, match v10 schema).
3. When v11 is empty, ``_load_overlay('v11') == _load_overlay('v10')``.
4. ``replay_from_trajectory(..., rubric_channel='v11')`` runs without
   error against a golden V8 trajectory, and preserves the v8 criterion
   id set (overlay must not change which criteria are evaluated).
5. The 11 BANNED_IDS locked in v10 must not reappear in v11.

No API calls. Exercises world_state code paths only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from healthcraft.llm.orchestrator import _VALID_RUBRIC_CHANNELS, _load_overlay
from healthcraft.tasks.evaluator import replay_from_trajectory
from healthcraft.tasks.loader import load_task

REPO = Path(__file__).resolve().parents[2]
GOLDEN_INDEX = REPO / "tests" / "fixtures" / "golden_trajectories" / "index.json"
TASKS_DIR = REPO / "configs" / "tasks"
V11_OVERLAY = REPO / "configs" / "rubrics" / "v11_consensus_overlay.yaml"


def _find_task(task_id: str):
    for yaml_path in sorted(TASKS_DIR.rglob("*.yaml")):
        raw = yaml.safe_load(yaml_path.read_text())
        if raw.get("id") == task_id:
            return load_task(yaml_path)
    return None


class TestV11OverlayFile:
    """The v11 overlay file exists and parses with the expected schema."""

    def test_v11_overlay_exists(self) -> None:
        assert V11_OVERLAY.exists(), f"Missing: {V11_OVERLAY}"

    def test_v11_overlay_parses(self) -> None:
        data = yaml.safe_load(V11_OVERLAY.read_text())
        assert isinstance(data, dict), "v11 overlay must be a YAML mapping at top level"
        assert "overlays" in data, "v11 overlay must have an 'overlays' key"
        assert isinstance(data["overlays"], list), (
            "v11 overlays must be a list (may be empty by default)"
        )

    def test_v11_overlay_schema(self) -> None:
        """If overlays are populated, each entry must carry the v10 fields."""
        data = yaml.safe_load(V11_OVERLAY.read_text())
        overlays = data.get("overlays") or []
        if not overlays:
            pytest.skip("v11 overlay is empty (default); schema check skipped")
        required = {"criterion_id", "verification", "check"}
        for entry in overlays:
            missing = required - set(entry.keys())
            assert not missing, f"{entry.get('criterion_id')} missing {missing}"
            assert entry["verification"] == "world_state"
            assert entry["check"].strip()


class TestV11Loader:
    """_load_overlay composes v9 + v10 + v11."""

    def test_v11_valid_channel(self) -> None:
        assert "v11" in _VALID_RUBRIC_CHANNELS

    def test_v11_includes_v9_and_v10_entries(self) -> None:
        v9 = _load_overlay("v9")
        v10 = _load_overlay("v10")
        v11 = _load_overlay("v11")
        assert set(v9).issubset(set(v11)), (
            "v11 must include every v9 criterion_id (v11 composes on top of v9)"
        )
        assert set(v10).issubset(set(v11)), (
            "v11 must include every v10 criterion_id (v11 composes on top of v10)"
        )

    def test_v11_empty_by_default_is_equal_to_v10(self) -> None:
        """Shipped default: v11 YAML has no entries, so the composed overlay
        must equal the v10 composed overlay exactly."""
        data = yaml.safe_load(V11_OVERLAY.read_text())
        overlays = data.get("overlays") or []
        if overlays:
            pytest.skip("v11 overlay has entries; equality check does not apply")
        assert _load_overlay("v11") == _load_overlay("v10")


class TestV11NoBannedIds:
    """Post-audit guard: 11 banned criterion_ids from v10 must not reappear in v11."""

    BANNED_IDS = frozenset(
        {
            "IR-007-C05",
            "IR-017-C04",
            "IR-028-C03",
            "TR-002-C05",
            "TR-025-C11",
            "IR-023-C08",
            "MW-027-C02",
            "SCJ-009-C07",
            "TR-003-C07",
            "TR-013-C11",
            "TR-016-C04",
        }
    )

    def test_banned_entries_not_in_v11(self) -> None:
        v11 = _load_overlay("v11")
        intersect = self.BANNED_IDS & set(v11)
        assert not intersect, (
            f"These criterion_ids were removed after the 2026-04-18 v10 audits "
            f"(semantic inversion / wrong-drug match / qualifier lost) and must "
            f"not reappear in v11: {sorted(intersect)}"
        )

    def test_banned_entries_not_in_v11_yaml_file(self) -> None:
        """Also check the raw YAML file so a faulty merge cannot hide a banned ID."""
        data = yaml.safe_load(V11_OVERLAY.read_text()) or {}
        raw_ids = {e.get("criterion_id") for e in (data.get("overlays") or [])}
        intersect = self.BANNED_IDS & raw_ids
        assert not intersect, f"BANNED_IDS found in v11 YAML file directly: {sorted(intersect)}"


class TestReplayV11:
    """replay_from_trajectory honors rubric_channel='v11'."""

    @pytest.fixture()
    def golden_entry(self) -> dict | None:
        if not GOLDEN_INDEX.exists():
            pytest.skip("golden index missing")
        data = json.loads(GOLDEN_INDEX.read_text())
        entries = data.get("trajectories", [])
        if not entries:
            pytest.skip("golden index empty")
        for e in entries:
            if e.get("task_id") == "CC-001":
                return e
        return entries[0]

    def test_replay_v11_runs_without_error(self, golden_entry: dict) -> None:
        """Replay must not crash, and the criterion id set must be preserved."""
        traj_path = REPO / golden_entry["trajectory_path"]
        if not traj_path.exists():
            pytest.skip("golden trajectory missing on disk")
        traj = json.loads(traj_path.read_text())
        task = _find_task(golden_entry["task_id"])
        if task is None:
            pytest.skip(f"task {golden_entry['task_id']} not found")

        v8 = replay_from_trajectory(traj, task, rubric_channel="v8")
        v11 = replay_from_trajectory(traj, task, rubric_channel="v11")

        v8_ids = {r.criterion_id for r in v8.criteria_results}
        v11_ids = {r.criterion_id for r in v11.criteria_results}
        assert v8_ids == v11_ids, "v11 overlay must not change the criterion id set"

    def test_replay_v11_matches_v10_when_empty(self, golden_entry: dict) -> None:
        """If v11 YAML is empty, v11 replay must be identical to v10 replay."""
        data = yaml.safe_load(V11_OVERLAY.read_text())
        overlays = data.get("overlays") or []
        if overlays:
            pytest.skip("v11 overlay has entries; equality-to-v10 does not apply")

        traj_path = REPO / golden_entry["trajectory_path"]
        if not traj_path.exists():
            pytest.skip("golden trajectory missing on disk")
        traj = json.loads(traj_path.read_text())
        task = _find_task(golden_entry["task_id"])
        if task is None:
            pytest.skip(f"task {golden_entry['task_id']} not found")

        v10 = replay_from_trajectory(traj, task, rubric_channel="v10")
        v11 = replay_from_trajectory(traj, task, rubric_channel="v11")

        assert v10.reward == pytest.approx(v11.reward)
        assert v10.passed == v11.passed
        assert v10.safety_gate_passed == v11.safety_gate_passed

        v10_results = {r.criterion_id: (r.satisfied, r.evidence) for r in v10.criteria_results}
        v11_results = {r.criterion_id: (r.satisfied, r.evidence) for r in v11.criteria_results}
        assert v10_results == v11_results
