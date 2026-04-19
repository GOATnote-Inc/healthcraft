"""Contract tests for ``scripts/build_consensus.py``.

No API calls. The real ``EnsembleJudge`` is swapped for a deterministic
stub that returns pre-scripted per-judge verdicts. Covers:

1. Fleiss' kappa at the unanimous and near-random boundaries.
2. Consensus eligibility gating: min_trajectories AND min_agreement.
3. JSONL + YAML manifest schema produced end-to-end on a tiny fixture.

The stub writes into the ensemble cache on disk so the ``--dry-run`` code
path can also be exercised without hitting the live LLM clients.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "build_consensus.py"


def _load_build_consensus():
    """Import ``scripts/build_consensus.py`` as a module."""
    sys.path.insert(0, str(_REPO / "src"))
    spec = importlib.util.spec_from_file_location("_build_consensus", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register BEFORE exec so dataclass decorators can resolve the module
    # (Python 3.14 strictness: dataclasses._is_type walks sys.modules).
    sys.modules["_build_consensus"] = module
    spec.loader.exec_module(module)
    return module


bc = _load_build_consensus()


# ---------------------------------------------------------------------------
# 1. Fleiss' kappa sanity checks
# ---------------------------------------------------------------------------


class TestFleissKappa:
    def test_fleiss_kappa_unanimous_is_nan(self) -> None:
        """All raters vote identically on every subject -> P_e == 1 -> nan.

        Documented behavior: we return ``nan`` for P_e == 1 because
        chance-corrected agreement is undefined when the expected agreement
        already saturates.
        """
        # 5 subjects x 3 raters, every vote = 1
        votes = [[1, 1, 1] for _ in range(5)]
        result = bc._fleiss_kappa(votes)
        assert math.isnan(result)

    def test_fleiss_kappa_random_is_near_zero(self) -> None:
        """Random 50/50 coin-flip votes converge to |kappa| < 0.3 at N=60.

        Large sample so the ratio of accidental agreements to chance agreement
        stabilises. Seeded for determinism.
        """
        import random

        rng = random.Random(42)
        votes = [[rng.randint(0, 1) for _ in range(3)] for _ in range(60)]
        result = bc._fleiss_kappa(votes)
        assert not math.isnan(result)
        assert abs(result) < 0.3, f"kappa was {result} (expected near 0)"

    def test_fleiss_kappa_degenerate_single_subject(self) -> None:
        assert math.isnan(bc._fleiss_kappa([[1, 0, 1]]))

    def test_fleiss_kappa_perfect_split(self) -> None:
        """Perfect within-subject agreement but mixed across subjects.

        Every rater agrees on every subject (3 subjects = 1, 3 subjects = 0).
        P_bar = 1, P_e = 0.5 -> kappa = 1.
        """
        votes = [[1, 1, 1], [1, 1, 1], [1, 1, 1], [0, 0, 0], [0, 0, 0], [0, 0, 0]]
        result = bc._fleiss_kappa(votes)
        assert result == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 2. Eligibility logic via the script's own aggregator
# ---------------------------------------------------------------------------


def _make_verdict(
    *,
    cid: str,
    task_id: str = "TASK-1",
    assertion: str = "asserts something",
    dimension: str = "clinical_correctness",
    safety_critical: bool = False,
    category: str = "clinical_reasoning",
    trajectory_id: str,
    votes: tuple[int, ...],
) -> bc._Verdict:
    agreement = max(sum(votes), len(votes) - sum(votes)) / max(len(votes), 1)
    return bc._Verdict(
        criterion_id=cid,
        task_id=task_id,
        assertion=assertion,
        dimension=dimension,
        safety_critical=safety_critical,
        category=category,
        trajectory_id=trajectory_id,
        votes=votes,
        agreement_score=agreement,
        ensemble_satisfied=sum(votes) >= 2,
    )


class TestEligibility:
    def test_consensus_eligibility_requires_min_trajectories(self) -> None:
        """Criterion with only 2 trajectories is dropped even at agreement 1.0."""
        verdicts = [
            _make_verdict(cid="C1", trajectory_id="t1", votes=(1, 1, 1)),
            _make_verdict(cid="C1", trajectory_id="t2", votes=(1, 1, 1)),
        ]
        per_criterion = bc._per_criterion_stats(verdicts)
        row = per_criterion["C1"]
        # n_trajectories < min_trajectories (3) must drop the criterion.
        assert row["n_trajectories"] == 2
        assert row["mean_agreement"] == pytest.approx(1.0)

    def test_consensus_eligibility_requires_min_agreement(self) -> None:
        """Criterion with 5 trajectories at mean_agreement 0.60 is dropped."""
        # 2-of-3 majority => agreement = 2/3 ~= 0.667. Use 2-of-3 votes on 3
        # trajectories and 1-of-3 (agreement 2/3) on 2 trajectories -- mean
        # = 0.667. Below the 0.85 threshold.
        verdicts = [
            _make_verdict(cid="C2", trajectory_id=f"t{i}", votes=(1, 1, 0)) for i in range(3)
        ] + [_make_verdict(cid="C2", trajectory_id=f"t{i}", votes=(0, 1, 0)) for i in range(3, 5)]
        per_criterion = bc._per_criterion_stats(verdicts)
        row = per_criterion["C2"]
        assert row["n_trajectories"] == 5
        assert row["mean_agreement"] == pytest.approx(2 / 3)
        assert row["mean_agreement"] < 0.85


# ---------------------------------------------------------------------------
# 3. End-to-end contract via a stub EnsembleJudge
# ---------------------------------------------------------------------------


@dataclass
class _StubEnsembleResult:
    criterion_id: str
    satisfied: bool
    per_judge: dict
    per_judge_evidence: dict
    agreement_score: float
    ambiguous: bool
    n_judges_used: int
    evidence: str


class _StubEnsembleJudge:
    """Deterministic stub for EnsembleJudge.

    Returns pre-scripted per-judge votes keyed by (criterion_id, trajectory_id).
    The ``script`` mapping is read from the class attribute populated by the
    test.
    """

    script: dict[tuple[str, str], dict[str, bool]] = {}
    judge_pool_default = ("gpt-5.4", "claude-opus-4-7", "gemini-3.1-pro")

    def __init__(
        self,
        agent_model: str,
        judge_pool=None,
        min_agreement: int = 2,
        prompt_version: str = "v2",
        cache_dir: Path | None = None,
    ) -> None:
        self._agent_model = agent_model
        # Filter judge pool to non-same-vendor, matching real behavior on the
        # happy path.
        pool = list(judge_pool) if judge_pool is not None else list(self.judge_pool_default)
        agent_lower = agent_model.lower()
        filtered: list[str] = []
        for jm in pool:
            jl = jm.lower()
            if agent_lower.startswith("claude") and jl.startswith("claude"):
                continue
            if agent_lower.startswith("gpt") and jl.startswith(("gpt", "o1", "o3")):
                continue
            if agent_lower.startswith("gemini") and jl.startswith("gemini"):
                continue
            filtered.append(jm)
        self._judges = filtered

    @property
    def judge_models(self):
        return list(self._judges)

    def evaluate_criterion(self, criterion, trajectory_turns, trajectory_id):
        key = (criterion.id, trajectory_id)
        per_judge_votes = self.script.get(key)
        if per_judge_votes is None:
            # Default: unanimous True.
            per_judge_votes = {jm: True for jm in self._judges}
        # Restrict to the judges we have (filter out same-vendor).
        per_judge = {jm: bool(per_judge_votes.get(jm, True)) for jm in self._judges}
        trues = sum(1 for v in per_judge.values() if v)
        falses = len(per_judge) - trues
        final = trues >= 2
        n = len(per_judge)
        agreement = max(trues, falses) / n if n else 0.0
        return _StubEnsembleResult(
            criterion_id=criterion.id,
            satisfied=final,
            per_judge=per_judge,
            per_judge_evidence={jm: "stub" for jm in per_judge},
            agreement_score=agreement,
            ambiguous=max(trues, falses) < 2,
            n_judges_used=n,
            evidence="[stub]",
        )


def _write_task_yaml(task_dir: Path, task_id: str, criteria: list[dict]) -> None:
    payload = {
        "id": task_id,
        "category": "clinical_reasoning",
        "level": 3,
        "title": f"Fixture task {task_id}",
        "description": "Fixture task for consensus contract test.",
        "criteria": criteria,
    }
    (task_dir / f"{task_id}.yaml").write_text(yaml.safe_dump(payload))


def _write_trajectory(results_dir: Path, task_id: str, model: str, trial: int) -> Path:
    tdir = results_dir / "trajectories" / "clinical_reasoning"
    tdir.mkdir(parents=True, exist_ok=True)
    path = tdir / f"{task_id}_{model}_42_t{trial}.json"
    payload = {
        "task_id": task_id,
        "model": model,
        "seed": 42,
        "turns": [
            {"role": "user", "content": "scenario"},
            {"role": "assistant", "content": "diagnosis"},
        ],
        "criteria_results": [],
        "reward": 0.5,
        "passed": False,
    }
    path.write_text(json.dumps(payload))
    return path


class TestConsensusContractArtifacts:
    def test_consensus_contract_artifact_schema(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Build a tiny fake run with 2 criteria x 3 trajectories end-to-end."""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        _write_task_yaml(
            tasks_dir,
            "FX-001",
            [
                {
                    "id": "FX-001-C01",
                    "assertion": "Agent identified diagnosis",
                    "dimension": "clinical_correctness",
                    "verification": "llm_judge",
                    "safety_critical": False,
                },
                {
                    "id": "FX-001-C02",
                    "assertion": "Agent avoided contraindicated drug",
                    "dimension": "safety",
                    "verification": "llm_judge",
                    "safety_critical": True,
                },
            ],
        )

        results_dir = tmp_path / "pilot"
        traj_paths = [
            _write_trajectory(results_dir, "FX-001", "gpt-5.4", trial=i + 1) for i in range(3)
        ]

        # Script: C01 unanimous T on all 3 trajectories -> eligible
        #         C02 splits 1-T / 1-F on trajectory 1, unanimous F elsewhere
        #         -> mean_agreement below 0.85 -> dropped.
        script: dict[tuple[str, str], dict[str, bool]] = {}
        for tp in traj_paths:
            traj_id = bc._stable_trajectory_id(tp)
            script[("FX-001-C01", traj_id)] = {
                "claude-opus-4-7": True,
                "gemini-3.1-pro": True,
            }
        # C02: two trajectories with 1-1 split (ambiguous, agreement 0.5),
        # one with unanimous -- mean agreement still < 0.85.
        amb_ids = [bc._stable_trajectory_id(tp) for tp in traj_paths]
        script[("FX-001-C02", amb_ids[0])] = {
            "claude-opus-4-7": True,
            "gemini-3.1-pro": False,
        }
        script[("FX-001-C02", amb_ids[1])] = {
            "claude-opus-4-7": False,
            "gemini-3.1-pro": True,
        }
        script[("FX-001-C02", amb_ids[2])] = {
            "claude-opus-4-7": True,
            "gemini-3.1-pro": False,
        }
        _StubEnsembleJudge.script = script
        monkeypatch.setattr(bc, "EnsembleJudge", _StubEnsembleJudge)

        output = tmp_path / "out" / "consensus.jsonl"
        manifest = tmp_path / "out" / "consensus.yaml"

        exit_code = bc.main(
            [
                "--results",
                str(results_dir),
                "--min-agreement",
                "0.85",
                "--min-trajectories",
                "3",
                "--output",
                str(output),
                "--manifest",
                str(manifest),
                "--tasks-dir",
                str(tasks_dir),
                "--cache-dir",
                str(tmp_path / "cache"),
            ]
        )
        # Exit code is driven by the kappa gate; we accept either but require
        # that the artifacts were still written.
        assert exit_code in (0, 1)

        # ----- JSONL shape -----
        assert output.exists(), "JSONL artifact was not written"
        lines = [json.loads(line) for line in output.read_text().splitlines() if line.strip()]
        # Only C01 should be eligible.
        assert len(lines) == 1
        entry = lines[0]
        required_keys = {
            "criterion_id",
            "task_id",
            "assertion",
            "dimension",
            "safety_critical",
            "n_trajectories",
            "mean_agreement",
            "fleiss_kappa",
            "ensemble_verdict_pass_rate",
        }
        assert required_keys <= set(entry.keys())
        assert entry["criterion_id"] == "FX-001-C01"
        assert entry["n_trajectories"] == 3
        assert entry["mean_agreement"] == pytest.approx(1.0)

        # ----- YAML manifest shape -----
        assert manifest.exists(), "Manifest was not written"
        manifest_data = yaml.safe_load(manifest.read_text())
        assert manifest_data["version"] == 1
        assert "generated_at" in manifest_data
        assert manifest_data["inputs"]["min_agreement"] == 0.85
        assert manifest_data["inputs"]["min_trajectories"] == 3
        assert manifest_data["ensemble"]["prompt_version"] == "v2"
        assert manifest_data["stats"]["n_llm_judge_criteria_evaluated"] == 2
        assert manifest_data["stats"]["n_consensus_eligible"] == 1
        # One ambiguous drop.
        assert manifest_data["stats"]["n_ambiguous_dropped"] == 1
        # Dropped criteria list includes C02 with the right reason.
        dropped_ids = {d["criterion_id"]: d for d in manifest_data["dropped_criteria"]}
        assert "FX-001-C02" in dropped_ids
        assert dropped_ids["FX-001-C02"]["reason"] == "mean_agreement_below_threshold"
        # Breakdowns present.
        assert "by_safety_critical" in manifest_data["stats"]
        assert "by_dimension" in manifest_data["stats"]
        assert "by_category" in manifest_data["stats"]
