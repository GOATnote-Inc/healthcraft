"""Contract tests for the Phase 5 HuggingFace release surface.

No network calls. Covers:

1. Build emits three JSONLs + manifest + README + LICENSE
2. Manifest schema
3. Consensus subset filters criteria correctly
4. Full subset contains all tasks
5. Missing Consensus/Hard source is handled gracefully
6. Simple-evals grader --help parses cleanly
7. ``scripts/regen_leaderboard.py`` is idempotent
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_BUILD_SCRIPT = _REPO / "scripts" / "build_huggingface_release.py"
_REGEN_SCRIPT = _REPO / "scripts" / "regen_leaderboard.py"
_EVAL_SCRIPT = _REPO / "evals" / "healthcraft_simple_eval.py"
_CARDS_DIR = _REPO / "docs" / "MODEL_CARDS"


def _load_module(path: Path, name: str):
    """Import a script file as a module with unique name (no sys.modules reuse)."""
    sys.path.insert(0, str(_REPO / "src"))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bhr = _load_module(_BUILD_SCRIPT, "_build_huggingface_release")
regen = _load_module(_REGEN_SCRIPT, "_regen_leaderboard")


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _write_task(tasks_dir: Path, task_id: str, criteria: list[dict]) -> None:
    """Write a minimal task YAML to ``tasks_dir``."""
    payload = {
        "id": task_id,
        "category": "clinical_reasoning",
        "level": 3,
        "title": f"Fixture {task_id}",
        "description": f"Fixture task {task_id} for release contract test.",
        "setting": {"world_seed": 42, "time": "2026-01-01T00:00:00Z"},
        "patient": {"age": 45, "chief_complaint": "test"},
        "expected_tools": ["getEncounterDetails"],
        "criteria": criteria,
        "metadata": {"fixture": True},
    }
    (tasks_dir / f"{task_id}.yaml").write_text(yaml.safe_dump(payload))


def _consensus_jsonl(path: Path, criterion_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "criterion_id": cid,
                "task_id": cid.rsplit("-", 1)[0],
                "assertion": "fixture",
                "dimension": "clinical_correctness",
                "safety_critical": False,
                "n_trajectories": 3,
                "mean_agreement": 1.0,
                "fleiss_kappa": 1.0,
                "ensemble_verdict_pass_rate": 1.0,
            }
        )
        for cid in criterion_ids
    ]
    path.write_text("\n".join(lines) + "\n")


def _hard_jsonl(path: Path, task_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "task_id": tid,
                "category": "clinical_reasoning",
                "rank": rank,
                "n_trials": 6,
                "models_covered": ["claude-opus-4-6", "gpt-5.4"],
                "mean_reward": 0.1,
                "pass_rate": 0.0,
                "safety_gate_pass_rate": 0.0,
                "per_model": {},
                "criteria_count": 3,
                "safety_critical_count": 1,
            }
        )
        for rank, tid in enumerate(task_ids, start=1)
    ]
    path.write_text("\n".join(lines) + "\n")


def _build_tmp_tasks(tasks_dir: Path) -> None:
    """Two tasks, mixed verification methods."""
    tasks_dir.mkdir(parents=True, exist_ok=True)
    _write_task(
        tasks_dir,
        "FX-001",
        [
            {
                "id": "FX-001-C01",
                "assertion": "Agent retrieved encounter details",
                "dimension": "clinical_completeness",
                "verification": "world_state",
                "check": "audit_log contains call to getEncounterDetails",
                "safety_critical": False,
            },
            {
                "id": "FX-001-C02",
                "assertion": "Agent identified correct diagnosis",
                "dimension": "clinical_correctness",
                "verification": "llm_judge",
                "safety_critical": False,
            },
            {
                "id": "FX-001-C03",
                "assertion": "Agent did NOT order anticoagulation",
                "dimension": "safety",
                "verification": "llm_judge",
                "safety_critical": True,
            },
        ],
    )
    _write_task(
        tasks_dir,
        "FX-002",
        [
            {
                "id": "FX-002-C01",
                "assertion": "Agent consulted appropriate specialist",
                "dimension": "clinical_completeness",
                "verification": "llm_judge",
                "safety_critical": False,
            },
        ],
    )


# ---------------------------------------------------------------------------
# 1 / 2 / 3 / 4: End-to-end build
# ---------------------------------------------------------------------------


class TestBuild:
    def test_build_emits_three_jsonls(self, tmp_path: Path) -> None:
        tasks_dir = tmp_path / "tasks"
        _build_tmp_tasks(tasks_dir)

        consensus = tmp_path / "data" / "consensus.jsonl"
        _consensus_jsonl(consensus, ["FX-001-C02", "FX-002-C01"])

        hard = tmp_path / "data" / "hard.jsonl"
        _hard_jsonl(hard, ["FX-002"])

        output = tmp_path / "release"
        exit_code = bhr.main(
            [
                "--tasks-dir",
                str(tasks_dir),
                "--consensus",
                str(consensus),
                "--hard",
                str(hard),
                "--output-dir",
                str(output),
                "--version",
                "9.9.9",
                "--rubric-channel",
                "v10",
            ]
        )
        assert exit_code == 0

        for name in (
            "healthcraft_full.jsonl",
            "healthcraft_consensus.jsonl",
            "healthcraft_hard.jsonl",
            "manifest.json",
            "README.md",
            "LICENSE",
        ):
            assert (output / name).exists(), f"{name} missing"

    def test_manifest_schema(self, tmp_path: Path) -> None:
        tasks_dir = tmp_path / "tasks"
        _build_tmp_tasks(tasks_dir)
        consensus = tmp_path / "data" / "consensus.jsonl"
        _consensus_jsonl(consensus, ["FX-001-C02"])
        hard = tmp_path / "data" / "hard.jsonl"
        _hard_jsonl(hard, ["FX-001"])
        output = tmp_path / "release"

        bhr.main(
            [
                "--tasks-dir",
                str(tasks_dir),
                "--consensus",
                str(consensus),
                "--hard",
                str(hard),
                "--output-dir",
                str(output),
                "--version",
                "1.0.0",
            ]
        )
        manifest = json.loads((output / "manifest.json").read_text())
        assert manifest["version"] == "1.0.0"
        assert "generated_at" in manifest
        assert manifest["rubric_channel"] == "v10"
        assert set(manifest["subsets"].keys()) == {"full", "consensus", "hard"}
        for key in ("full", "consensus", "hard"):
            s = manifest["subsets"][key]
            assert "n_tasks" in s
            assert "n_criteria" in s
            assert "file" in s
        grader = manifest["grader"]
        assert grader["module"] == "evals/healthcraft_simple_eval.py"
        assert grader["mode"] == "ensemble"
        assert grader["min_agreement"] == 2
        assert len(grader["judges"]) == 3
        assert manifest["license"] == "MIT"
        assert "citation" in manifest

    def test_consensus_subset_filters_criteria(self, tmp_path: Path) -> None:
        """Only llm_judge criteria listed in consensus are kept; world_state stays."""
        tasks_dir = tmp_path / "tasks"
        _build_tmp_tasks(tasks_dir)
        consensus = tmp_path / "data" / "consensus.jsonl"
        # Only C02 is consensus-eligible, C03 is dropped.
        _consensus_jsonl(consensus, ["FX-001-C02"])
        hard = tmp_path / "data" / "hard.jsonl"
        _hard_jsonl(hard, [])  # empty hard
        output = tmp_path / "release"

        bhr.main(
            [
                "--tasks-dir",
                str(tasks_dir),
                "--consensus",
                str(consensus),
                "--hard",
                str(hard),
                "--output-dir",
                str(output),
            ]
        )

        lines = [
            json.loads(line)
            for line in (output / "healthcraft_consensus.jsonl").read_text().splitlines()
            if line.strip()
        ]
        # FX-001 is present (has C02 in consensus); FX-002 is not (C01 not in consensus).
        task_ids = {r["task_id"] for r in lines}
        assert task_ids == {"FX-001"}
        fx001 = next(r for r in lines if r["task_id"] == "FX-001")
        criterion_ids = {c["id"] for c in fx001["criteria"]}
        # C01 (world_state) passes through; C02 (llm_judge, in consensus) kept;
        # C03 (llm_judge, NOT in consensus) filtered out.
        assert criterion_ids == {"FX-001-C01", "FX-001-C02"}

    def test_full_subset_contains_all_tasks(self, tmp_path: Path) -> None:
        tasks_dir = tmp_path / "tasks"
        _build_tmp_tasks(tasks_dir)
        consensus = tmp_path / "data" / "consensus.jsonl"
        _consensus_jsonl(consensus, [])
        hard = tmp_path / "data" / "hard.jsonl"
        _hard_jsonl(hard, [])
        output = tmp_path / "release"

        bhr.main(
            [
                "--tasks-dir",
                str(tasks_dir),
                "--consensus",
                str(consensus),
                "--hard",
                str(hard),
                "--output-dir",
                str(output),
            ]
        )
        lines = [
            json.loads(line)
            for line in (output / "healthcraft_full.jsonl").read_text().splitlines()
            if line.strip()
        ]
        assert len(lines) == 2
        assert {r["task_id"] for r in lines} == {"FX-001", "FX-002"}
        # All criteria are present in Full.
        fx001 = next(r for r in lines if r["task_id"] == "FX-001")
        assert {c["id"] for c in fx001["criteria"]} == {
            "FX-001-C01",
            "FX-001-C02",
            "FX-001-C03",
        }

    def test_missing_consensus_source_graceful(self, tmp_path: Path) -> None:
        tasks_dir = tmp_path / "tasks"
        _build_tmp_tasks(tasks_dir)
        output = tmp_path / "release"
        missing_consensus = tmp_path / "does_not_exist_consensus.jsonl"
        missing_hard = tmp_path / "does_not_exist_hard.jsonl"

        exit_code = bhr.main(
            [
                "--tasks-dir",
                str(tasks_dir),
                "--consensus",
                str(missing_consensus),
                "--hard",
                str(missing_hard),
                "--output-dir",
                str(output),
            ]
        )
        # Full was emitted, so exit 0.
        assert exit_code == 0
        # Consensus + Hard JSONLs exist but are empty.
        cons_path = output / "healthcraft_consensus.jsonl"
        hard_path = output / "healthcraft_hard.jsonl"
        assert cons_path.exists()
        assert hard_path.exists()
        assert cons_path.read_text().strip() == ""
        assert hard_path.read_text().strip() == ""
        # Manifest records not_built_yet status with a build_command.
        manifest = json.loads((output / "manifest.json").read_text())
        assert manifest["subsets"]["consensus"]["status"] == "not_built_yet"
        assert "build_command" in manifest["subsets"]["consensus"]
        assert manifest["subsets"]["hard"]["status"] == "not_built_yet"
        assert "build_command" in manifest["subsets"]["hard"]


# ---------------------------------------------------------------------------
# 6: simple-evals grader --help parses
# ---------------------------------------------------------------------------


class TestSimpleEvalHelp:
    def test_simple_eval_help_parses(self) -> None:
        """``evals/healthcraft_simple_eval.py --help`` exits 0 with usage text."""
        result = subprocess.run(
            [sys.executable, str(_EVAL_SCRIPT), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "usage:" in result.stdout
        assert "--dataset" in result.stdout
        assert "--agent-model" in result.stdout


# ---------------------------------------------------------------------------
# 7: regen_leaderboard is idempotent
# ---------------------------------------------------------------------------


class TestRegenLeaderboardIdempotent:
    def test_regen_leaderboard_idempotent(self, tmp_path: Path) -> None:
        # Point the regen script at the real model cards but write into tmp.
        assert _CARDS_DIR.exists(), "Expected docs/MODEL_CARDS to exist from Phase 5"
        output = tmp_path / "LEADERBOARD.md"

        exit_code_1 = regen.main(
            [
                "--cards-dir",
                str(_CARDS_DIR),
                "--output",
                str(output),
            ]
        )
        assert exit_code_1 == 0
        first = output.read_bytes()

        exit_code_2 = regen.main(
            [
                "--cards-dir",
                str(_CARDS_DIR),
                "--output",
                str(output),
            ]
        )
        assert exit_code_2 == 0
        second = output.read_bytes()

        assert first == second, "regen_leaderboard.py is not idempotent"

    def test_regen_leaderboard_check_flag_on_stale_fails(self, tmp_path: Path) -> None:
        """--check exits 1 if the on-disk file differs from regenerated output."""
        assert _CARDS_DIR.exists()
        output = tmp_path / "LEADERBOARD.md"
        output.write_text("stale content", encoding="utf-8")
        exit_code = regen.main(
            [
                "--cards-dir",
                str(_CARDS_DIR),
                "--output",
                str(output),
                "--check",
            ]
        )
        assert exit_code == 1


# ---------------------------------------------------------------------------
# Sanity: dry-run with real repo (no files written)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_REPO / "configs" / "tasks").exists(),
    reason="real tasks dir unavailable",
)
def test_dry_run_on_real_repo(tmp_path: Path) -> None:
    """Dry-run against the real repo emits no files and returns 0."""
    output = tmp_path / "release"
    exit_code = bhr.main(
        [
            "--tasks-dir",
            str(_REPO / "configs" / "tasks"),
            "--consensus",
            str(tmp_path / "missing_consensus.jsonl"),
            "--hard",
            str(tmp_path / "missing_hard.jsonl"),
            "--output-dir",
            str(output),
            "--dry-run",
        ]
    )
    assert exit_code == 0
    assert not output.exists()
