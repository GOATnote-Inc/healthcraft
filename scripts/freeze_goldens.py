"""Freeze a stratified sample of V8 trajectories as a golden replay manifest.

This is a one-shot, deterministic, read-only walker over the immutable
``results/pilot-v8-{claude-opus,gpt54}/trajectories/`` directories. It does
NOT copy trajectory files (results/ is append-only per CLAUDE.md). It writes
a manifest to ``tests/fixtures/golden_trajectories/index.json`` containing,
for each selected trajectory:

    {
      "task_id":             str,
      "category":            str,
      "model":               str,
      "trajectory_path":     str  (relative to repo root),
      "expected_reward":     float,
      "expected_passed":     bool,
      "expected_safety_gate": bool,
      "n_criteria":          int,
      "criteria_results_hash": str  (SHA256 of canonical (id, satisfied) tuples)
    }

Stratification: 5 trajectories per category (6 categories) = 30 total.
Selection within a category is biased to balance models and pass/fail
outcomes so the replay test exercises both verdict directions.

Determinism: ``random.Random(42)`` everywhere. Re-running this script
against the same V8 result tree produces a byte-identical manifest.

Usage:
    python scripts/freeze_goldens.py
    python scripts/freeze_goldens.py --output tests/fixtures/golden_trajectories/index.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RESULTS_DIRS = [
    REPO_ROOT / "results" / "pilot-v8-claude-opus",
    REPO_ROOT / "results" / "pilot-v8-gpt54",
]
DEFAULT_OUTPUT = REPO_ROOT / "tests" / "fixtures" / "golden_trajectories" / "index.json"
DEFAULT_SEED = 42
DEFAULT_PER_CATEGORY = 5

CATEGORIES = (
    "clinical_reasoning",
    "multi_step_workflows",
    "information_retrieval",
    "clinical_communication",
    "safety_critical_judgment",
    "temporal_reasoning",
)


def criteria_results_hash(criteria_results: list[dict[str, Any]]) -> str:
    """SHA256 over the canonical sorted (id, satisfied) tuples.

    Excludes ``evidence`` because it includes timestamps and judge prose
    that vary between deterministic and llm_judge channels. The contract
    we lock is: criterion id X reaches verdict Y. That's what replay must
    reproduce.
    """
    canonical = sorted((str(c["id"]), bool(c["satisfied"])) for c in criteria_results)
    blob = json.dumps(canonical, separators=(",", ":"), sort_keys=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_trajectory_meta(path: Path) -> dict[str, Any] | None:
    """Read a trajectory file and return only the fields we manifest.

    Returns None if the trajectory is malformed or missing required fields.
    """
    try:
        with path.open() as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None

    required = ("task_id", "model", "reward", "passed", "criteria_results")
    if not all(k in data for k in required):
        return None

    # safety_gate_passed was added later in the v8 pilot; tolerate absence.
    safety_gate = data.get("safety_gate_passed")
    if safety_gate is None:
        # Derive from criteria_results: any safety_critical violation -> False.
        # We don't have safety_critical in the trajectory itself, so fall back
        # to the conservative read: passed implies safety_gate_passed.
        safety_gate = bool(data["passed"])

    return {
        "task_id": str(data["task_id"]),
        "model": str(data["model"]),
        "expected_reward": float(data["reward"]),
        "expected_passed": bool(data["passed"]),
        "expected_safety_gate": bool(safety_gate),
        "n_criteria": len(data["criteria_results"]),
        "criteria_results_hash": criteria_results_hash(data["criteria_results"]),
    }


def stratified_sample(
    candidates_by_category: dict[str, list[Path]],
    per_category: int,
    rng: random.Random,
) -> dict[str, list[Path]]:
    """Pick `per_category` trajectories from each category.

    Within a category, prefers a balanced mix:
      - both models represented when possible
      - both pass=True and pass=False represented when possible

    Falls back to random selection if balance is impossible (e.g.,
    a category with only successful runs).
    """
    selected: dict[str, list[Path]] = {}

    for category, paths in candidates_by_category.items():
        if not paths:
            selected[category] = []
            continue

        # Preload metadata so we can stratify on (model, passed).
        meta = []
        for p in paths:
            m = load_trajectory_meta(p)
            if m is not None:
                meta.append((p, m))

        if not meta:
            selected[category] = []
            continue

        # Bucket by (model, passed).
        buckets: dict[tuple[str, bool], list[tuple[Path, dict]]] = defaultdict(list)
        for p, m in meta:
            buckets[(m["model"], m["expected_passed"])].append((p, m))

        # Round-robin pick from buckets to balance, then fill to `per_category`.
        bucket_keys = sorted(buckets.keys())
        rng.shuffle(bucket_keys)

        picks: list[Path] = []
        cursor = 0
        # First pass: one per bucket.
        for k in bucket_keys:
            if len(picks) >= per_category:
                break
            bucket = buckets[k]
            chosen = rng.choice(bucket)
            picks.append(chosen[0])
            buckets[k] = [x for x in bucket if x[0] != chosen[0]]
            cursor += 1

        # Second pass: round-robin until full.
        while len(picks) < per_category:
            non_empty = [k for k in bucket_keys if buckets[k]]
            if not non_empty:
                break
            k = non_empty[cursor % len(non_empty)]
            bucket = buckets[k]
            chosen = rng.choice(bucket)
            picks.append(chosen[0])
            buckets[k] = [x for x in bucket if x[0] != chosen[0]]
            cursor += 1

        selected[category] = sorted(picks)

    return selected


def collect_candidates(
    results_dirs: list[Path],
) -> dict[str, list[Path]]:
    """Walk pilot result trees and group trajectory paths by category."""
    by_category: dict[str, list[Path]] = {c: [] for c in CATEGORIES}

    for root in results_dirs:
        traj_root = root / "trajectories"
        if not traj_root.is_dir():
            continue
        for category in CATEGORIES:
            cat_dir = traj_root / category
            if not cat_dir.is_dir():
                continue
            for path in sorted(cat_dir.glob("*.json")):
                by_category[category].append(path)

    return by_category


def build_manifest(
    selected: dict[str, list[Path]],
    repo_root: Path,
) -> dict[str, Any]:
    """Build the JSON manifest from selected trajectories."""
    trajectories: list[dict[str, Any]] = []
    for category, paths in selected.items():
        for p in paths:
            meta = load_trajectory_meta(p)
            if meta is None:
                continue
            rel_path = str(p.relative_to(repo_root))
            trajectories.append(
                {
                    "task_id": meta["task_id"],
                    "category": category,
                    "model": meta["model"],
                    "trajectory_path": rel_path,
                    "expected_reward": meta["expected_reward"],
                    "expected_passed": meta["expected_passed"],
                    "expected_safety_gate": meta["expected_safety_gate"],
                    "n_criteria": meta["n_criteria"],
                    "criteria_results_hash": meta["criteria_results_hash"],
                }
            )

    # Sort for deterministic output ordering.
    trajectories.sort(key=lambda t: (t["category"], t["task_id"], t["model"]))

    return {
        "version": 1,
        "seed": DEFAULT_SEED,
        "per_category": DEFAULT_PER_CATEGORY,
        "categories": list(CATEGORIES),
        "n_trajectories": len(trajectories),
        "trajectories": trajectories,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Manifest output path (default: %(default)s)",
    )
    parser.add_argument(
        "--per-category",
        type=int,
        default=DEFAULT_PER_CATEGORY,
        help="Trajectories per category (default: %(default)d)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="Random seed (default: %(default)d)",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        action="append",
        default=None,
        help=(
            "Results directory to scan (repeatable). "
            "Default: results/pilot-v8-claude-opus and results/pilot-v8-gpt54."
        ),
    )
    args = parser.parse_args()

    results_dirs = args.results_dir or DEFAULT_RESULTS_DIRS
    rng = random.Random(args.seed)

    by_category = collect_candidates(results_dirs)

    total_candidates = sum(len(v) for v in by_category.values())
    print(
        f"[freeze_goldens] scanned {len(results_dirs)} pilot dir(s); "
        f"found {total_candidates} candidate trajectories across "
        f"{sum(1 for v in by_category.values() if v)} categories"
    )

    selected = stratified_sample(by_category, args.per_category, rng)
    manifest = build_manifest(selected, REPO_ROOT)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=False)
        fh.write("\n")

    try:
        display_path = args.output.relative_to(REPO_ROOT)
    except ValueError:
        display_path = args.output
    print(f"[freeze_goldens] wrote {manifest['n_trajectories']} trajectories to {display_path}")
    for category in CATEGORIES:
        n = sum(1 for t in manifest["trajectories"] if t["category"] == category)
        print(f"  {category}: {n}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
