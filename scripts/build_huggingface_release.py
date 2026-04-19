#!/usr/bin/env python3
"""HealthCraft HuggingFace release builder.

Emits a HealthBench-style release surface so frontier labs can plug
HealthCraft into their existing evaluation harnesses.

Outputs (under ``--output-dir``):

  * ``healthcraft_full.jsonl``       -- all tasks, one JSON object per task
  * ``healthcraft_consensus.jsonl``  -- Full filtered to Consensus-eligible
                                        llm_judge criteria (world_state /
                                        pattern criteria pass through
                                        unfiltered because they never hit the
                                        judge)
  * ``healthcraft_hard.jsonl``       -- subset of Full where
                                        ``task_id in HARD`` (task-level,
                                        criteria unfiltered)
  * ``manifest.json``                -- release contract
  * ``README.md``                    -- HuggingFace dataset card
  * ``LICENSE``                      -- MIT for the dataset

The script does NOT push to HuggingFace. That is a user-gated follow-up.

Usage::

    python scripts/build_huggingface_release.py \\
        --tasks-dir configs/tasks \\
        --consensus data/consensus/healthcraft_consensus_v1.jsonl \\
        --hard data/hard/healthcraft_hard_v1.jsonl \\
        --output-dir data/huggingface_release \\
        --version 1.0.0 \\
        --rubric-channel v10
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from healthcraft.tasks.loader import Task, load_tasks  # noqa: E402

_DEFAULT_TASKS_DIR = _PROJECT_ROOT / "configs" / "tasks"
_DEFAULT_CONSENSUS = _PROJECT_ROOT / "data" / "consensus" / "healthcraft_consensus_v1.jsonl"
_DEFAULT_HARD = _PROJECT_ROOT / "data" / "hard" / "healthcraft_hard_v1.jsonl"
_DEFAULT_OUTPUT = _PROJECT_ROOT / "data" / "huggingface_release"

_MIT_LICENSE_TEXT = """MIT License

Copyright (c) 2026 Brandon Dent, MD and GOATnote, Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this dataset and associated documentation files (the "Dataset"), to deal
in the Dataset without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Dataset, and to permit persons to whom the Dataset is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Dataset.

THE DATASET IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE DATASET OR THE USE OR OTHER DEALINGS
IN THE DATASET.

Note: This license covers the DATASET ONLY (``data/huggingface_release/``
and the task / criteria definitions distributed with it). The HealthCraft
code -- ``src/``, ``scripts/``, ``evals/`` -- remains under Apache License
2.0, per the repository's top-level LICENSE file.
"""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ConsensusIndex:
    """Loaded Consensus manifest: which llm_judge criterion_ids are eligible."""

    criterion_ids: frozenset[str]
    source_path: Path
    status: str  # "ok" | "not_built_yet"


@dataclass(frozen=True)
class _HardIndex:
    """Loaded Hard manifest: which task_ids are in the Hard subset."""

    task_ids: frozenset[str]
    source_path: Path
    status: str  # "ok" | "not_built_yet"


# ---------------------------------------------------------------------------
# Manifest loaders
# ---------------------------------------------------------------------------


def _load_consensus_index(path: Path) -> _ConsensusIndex:
    """Read the Consensus JSONL and return eligible criterion_ids.

    If the file does not exist, return a ``not_built_yet`` index.
    """
    if not path.exists():
        return _ConsensusIndex(criterion_ids=frozenset(), source_path=path, status="not_built_yet")
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        cid = row.get("criterion_id")
        if isinstance(cid, str):
            ids.add(cid)
    return _ConsensusIndex(criterion_ids=frozenset(ids), source_path=path, status="ok")


def _load_hard_index(path: Path) -> _HardIndex:
    """Read the Hard JSONL and return the set of task_ids in the Hard subset.

    If the file does not exist, return a ``not_built_yet`` index.
    """
    if not path.exists():
        return _HardIndex(task_ids=frozenset(), source_path=path, status="not_built_yet")
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        tid = row.get("task_id")
        if isinstance(tid, str):
            ids.add(tid)
    return _HardIndex(task_ids=frozenset(ids), source_path=path, status="ok")


# ---------------------------------------------------------------------------
# Task -> release-record serialization
# ---------------------------------------------------------------------------


def _serialize_criterion(raw: dict[str, Any]) -> dict[str, Any]:
    """Project a task's raw criterion dict into the release schema.

    Carries only the stable, user-consumable fields -- criterion_id,
    assertion, dimension, safety_critical, verification, check (empty for
    llm_judge).
    """
    return {
        "id": raw.get("id", ""),
        "assertion": raw.get("assertion", ""),
        "dimension": raw.get("dimension", "clinical_completeness"),
        "safety_critical": bool(raw.get("safety_critical", False)),
        "verification": raw.get("verification", ""),
        "check": raw.get("check", ""),
    }


def _serialize_task(
    task: Task,
    *,
    subset: str,
    criteria: list[dict[str, Any]],
) -> dict[str, Any]:
    """Serialize a ``Task`` into a release-surface JSON record."""
    return {
        "task_id": task.id,
        "subset": subset,
        "category": task.category,
        "level": task.level,
        "title": task.title,
        "description": task.description,
        "setting": dict(task.initial_state or {}),
        "patient": dict(task.patient) if task.patient else None,
        "expected_tools": list(task.expected_tools),
        "criteria": criteria,
        "metadata": dict(task.metadata or {}),
    }


def _filter_consensus_criteria(task: Task, consensus_ids: frozenset[str]) -> list[dict[str, Any]]:
    """Filter a task's criteria for the Consensus subset.

    Rules:
      * World-state and pattern criteria pass through unchanged -- they never
        hit the judge, so Consensus has nothing to say about them.
      * llm_judge criteria are kept only when their id is in the Consensus
        manifest.
    """
    kept: list[dict[str, Any]] = []
    for raw in task.criteria:
        verification = raw.get("verification", "")
        if verification == "llm_judge":
            if raw.get("id") in consensus_ids:
                kept.append(_serialize_criterion(raw))
        else:
            kept.append(_serialize_criterion(raw))
    return kept


def _all_criteria(task: Task) -> list[dict[str, Any]]:
    """Full criteria list for a task -- used for Full and Hard subsets."""
    return [_serialize_criterion(raw) for raw in task.criteria]


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, payload: str) -> None:
    """Write ``payload`` atomically (tmp in same dir, then os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _emit_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Emit a list of release records as one JSON object per line."""
    lines = [json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows]
    _atomic_write(path, "\n".join(lines) + ("\n" if lines else ""))


def _count_criteria(rows: list[dict[str, Any]]) -> int:
    return sum(len(r.get("criteria", [])) for r in rows)


# ---------------------------------------------------------------------------
# Manifest & README
# ---------------------------------------------------------------------------


def _build_subset_manifest_entry(
    *,
    file_name: str,
    rows: list[dict[str, Any]],
    index_status: str,
    source_manifest: str | None,
    build_command: str | None,
) -> dict[str, Any]:
    """One ``subsets.<name>`` block in the top-level manifest."""
    entry: dict[str, Any] = {
        "n_tasks": len(rows),
        "n_criteria": _count_criteria(rows),
        "file": file_name,
    }
    if source_manifest is not None:
        entry["source_manifest"] = source_manifest
    if index_status == "not_built_yet":
        entry["status"] = "not_built_yet"
        if build_command:
            entry["build_command"] = build_command
    return entry


def _write_manifest(
    output_dir: Path,
    *,
    version: str,
    rubric_channel: str,
    full_rows: list[dict[str, Any]],
    consensus_rows: list[dict[str, Any]],
    hard_rows: list[dict[str, Any]],
    consensus_index: _ConsensusIndex,
    hard_index: _HardIndex,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rubric_channel": rubric_channel,
        "subsets": {
            "full": _build_subset_manifest_entry(
                file_name="healthcraft_full.jsonl",
                rows=full_rows,
                index_status="ok",
                source_manifest=None,
                build_command=None,
            ),
            "consensus": _build_subset_manifest_entry(
                file_name="healthcraft_consensus.jsonl",
                rows=consensus_rows,
                index_status=consensus_index.status,
                source_manifest=str(
                    consensus_index.source_path.with_suffix(".yaml").relative_to(_PROJECT_ROOT)
                )
                if consensus_index.source_path.is_absolute()
                and _PROJECT_ROOT in consensus_index.source_path.parents
                else str(consensus_index.source_path.with_suffix(".yaml")),
                build_command=(
                    "python scripts/build_consensus.py --results "
                    "results/pilot-v8-claude-opus results/pilot-v8-gpt54 "
                    "results/pilot-v9-gemini-pro "
                    "--output data/consensus/healthcraft_consensus_v1.jsonl "
                    "--manifest data/consensus/consensus_criteria.yaml"
                ),
            ),
            "hard": _build_subset_manifest_entry(
                file_name="healthcraft_hard.jsonl",
                rows=hard_rows,
                index_status=hard_index.status,
                source_manifest=str(
                    hard_index.source_path.with_suffix(".yaml").relative_to(_PROJECT_ROOT)
                )
                if hard_index.source_path.is_absolute()
                and _PROJECT_ROOT in hard_index.source_path.parents
                else str(hard_index.source_path.with_suffix(".yaml")),
                build_command=(
                    "python scripts/build_hard.py --results "
                    "results/pilot-v8-claude-opus results/pilot-v8-gpt54 "
                    "results/pilot-v9-gemini-pro "
                    "--output data/hard/healthcraft_hard_v1.jsonl "
                    "--manifest data/hard/hard_tasks.yaml"
                ),
            ),
        },
        "grader": {
            "module": "evals/healthcraft_simple_eval.py",
            "mode": "ensemble",
            "judges": ["gpt-5.4", "claude-opus-4-7", "gemini-3.1-pro"],
            "min_agreement": 2,
        },
        "license": "MIT",
        "citation": (
            "Dent, B. (2026). HealthCraft: Emergency Medicine RL Training "
            "Environment Adapting Corecraft to Clinical Workflows. "
            "GOATnote, Inc."
        ),
    }
    _atomic_write(
        output_dir / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
    )
    return manifest


def _write_readme(
    output_dir: Path,
    *,
    version: str,
    manifest: dict[str, Any],
) -> None:
    """Emit a HuggingFace-style dataset card (YAML frontmatter + markdown)."""
    full = manifest["subsets"]["full"]
    consensus = manifest["subsets"]["consensus"]
    hard = manifest["subsets"]["hard"]

    # YAML frontmatter follows the HuggingFace dataset-card spec.
    frontmatter_lines = [
        "---",
        "license: mit",
        f'pretty_name: "HealthCraft {version}"',
        "tags:",
        "- emergency-medicine",
        "- clinical-reasoning",
        "- rl-training",
        "- corecraft",
        "- fhir",
        "- healthcare",
        "- evaluation",
        "task_categories:",
        "- question-answering",
        "- text-generation",
        "- other",
        "language:",
        "- en",
        "size_categories:",
        "- n<1K",
        "configs:",
        "- config_name: full",
        "  data_files:",
        "  - split: test",
        "    path: healthcraft_full.jsonl",
        "- config_name: consensus",
        "  data_files:",
        "  - split: test",
        "    path: healthcraft_consensus.jsonl",
        "- config_name: hard",
        "  data_files:",
        "  - split: test",
        "    path: healthcraft_hard.jsonl",
        "---",
        "",
    ]

    consensus_status = consensus.get("status", "ok")
    hard_status = hard.get("status", "ok")
    consensus_blurb = (
        f"{consensus['n_tasks']} tasks, {consensus['n_criteria']} criteria"
        if consensus_status == "ok"
        else "pending (run `scripts/build_consensus.py` first)"
    )
    hard_blurb = (
        f"{hard['n_tasks']} tasks, {hard['n_criteria']} criteria"
        if hard_status == "ok"
        else "pending (run `scripts/build_hard.py` first)"
    )

    body_lines = [
        f"# HealthCraft {version}",
        "",
        "**HealthCraft** is an emergency medicine RL training environment that adapts",
        "Corecraft (arXiv:2602.16179v5) to clinical workflows. Tasks cover clinical",
        "reasoning, multi-step workflows, information retrieval, clinical communication,",
        "safety-critical judgment, and temporal reasoning across a simulated emergency",
        "department.",
        "",
        "## Subsets",
        "",
        "| Subset    | Tasks | Criteria | Description |",
        "|-----------|-------|----------|-------------|",
        f"| `full`      | {full['n_tasks']} | {full['n_criteria']} | "
        "All tasks, all criteria. Use this for training and broad eval. |",
        f"| `consensus` | {consensus['n_tasks']} | {consensus['n_criteria']} | "
        "Subset of Full where every `llm_judge` criterion has passed a three-judge "
        "ensemble agreement filter. World-state and pattern criteria pass through "
        "unfiltered. Use this for reproducible benchmarking. |",
        f"| `hard`      | {hard['n_tasks']} | {hard['n_criteria']} | "
        "Task-level subset: bottom-quantile frontier-agent mean reward. Use this "
        "for bench-saturation-resistant evaluation. Criteria are unfiltered. |",
        "",
        f"- Consensus: {consensus_blurb}",
        f"- Hard: {hard_blurb}",
        "",
        "## Grader",
        "",
        "The reference grader lives at `evals/healthcraft_simple_eval.py` in the",
        "`healthcraft` repository. It is compatible with the OpenAI `simple-evals`",
        "harness surface. Default judge mode is **ensemble**: three cross-vendor",
        "frontier judges (gpt-5.4, claude-opus-4-7, gemini-3.1-pro) vote",
        "independently, and a supermajority (2-of-3) decides each `llm_judge`",
        "criterion verdict. Same-vendor judges are filtered out automatically so",
        "the agent is never its own judge.",
        "",
        "`world_state` and `pattern` criteria are verified deterministically and",
        "do not consume judge API calls.",
        "",
        "## Reward",
        "",
        "Per Corecraft Eq. 1, the per-task reward is the mean of binary criteria",
        "results. Any violated `safety_critical: true` criterion triggers a safety",
        "gate and sets the reward to 0. This gate is the dominant failure mode in",
        "pilot evaluations -- see the model cards in `docs/MODEL_CARDS/`.",
        "",
        "## Record schema (one JSON object per line)",
        "",
        "```json",
        "{",
        '  "task_id": "CR-001",',
        '  "subset": "full",',
        '  "category": "clinical_reasoning",',
        '  "level": 4,',
        '  "title": "The Mimic",',
        '  "description": "...",',
        '  "setting": {"time": "...", "facility": "..."},',
        '  "patient": {"age": 52, "chief_complaint": "..."},',
        '  "expected_tools": ["getEncounterDetails", "getPatientHistory"],',
        '  "criteria": [',
        "    {",
        '      "id": "CR-001-C05",',
        '      "assertion": "Agent cancelled the STEMI/cath lab alert",',
        '      "dimension": "safety",',
        '      "safety_critical": true,',
        '      "verification": "world_state",',
        '      "check": "audit_log contains call to updateEncounter"',
        "    }",
        "  ],",
        '  "metadata": {"confusion_pair": "stemi_vs_aortic_dissection"}',
        "}",
        "```",
        "",
        "## License",
        "",
        "Dataset: **MIT** (this directory).",
        "",
        "Code (`src/`, `scripts/`, `evals/`): **Apache-2.0** (see the repository's",
        "top-level `LICENSE`).",
        "",
        "## Citation",
        "",
        "```",
        f"{manifest['citation']}",
        "```",
        "",
    ]

    _atomic_write(output_dir / "README.md", "\n".join(frontmatter_lines + body_lines))


def _write_license(output_dir: Path) -> None:
    _atomic_write(output_dir / "LICENSE", _MIT_LICENSE_TEXT)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def _category_breakdown(rows: list[dict[str, Any]]) -> dict[str, int]:
    by_cat: dict[str, int] = defaultdict(int)
    for r in rows:
        by_cat[str(r.get("category", "unknown"))] += 1
    return dict(sorted(by_cat.items()))


def _print_summary(
    *,
    output_dir: Path,
    version: str,
    full_rows: list[dict[str, Any]],
    consensus_rows: list[dict[str, Any]],
    hard_rows: list[dict[str, Any]],
    consensus_status: str,
    hard_status: str,
) -> None:
    print(f"[ok] HealthCraft release v{version} -> {output_dir}")
    print(f"  full:      n_tasks={len(full_rows)} n_criteria={_count_criteria(full_rows)}")
    print(
        f"  consensus: n_tasks={len(consensus_rows)} "
        f"n_criteria={_count_criteria(consensus_rows)} status={consensus_status}"
    )
    print(
        f"  hard:      n_tasks={len(hard_rows)} "
        f"n_criteria={_count_criteria(hard_rows)} status={hard_status}"
    )
    cats = _category_breakdown(full_rows)
    if cats:
        cat_str = ", ".join(f"{k}={v}" for k, v in cats.items())
        print(f"  by_category (full): {cat_str}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--tasks-dir",
        type=Path,
        default=_DEFAULT_TASKS_DIR,
        help=f"Task YAML directory (default {_DEFAULT_TASKS_DIR}).",
    )
    p.add_argument(
        "--consensus",
        type=Path,
        default=_DEFAULT_CONSENSUS,
        help=(f"Consensus JSONL (from scripts/build_consensus.py). Default: {_DEFAULT_CONSENSUS}"),
    )
    p.add_argument(
        "--hard",
        type=Path,
        default=_DEFAULT_HARD,
        help=f"Hard JSONL (from scripts/build_hard.py). Default: {_DEFAULT_HARD}",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help=f"Release output directory (default {_DEFAULT_OUTPUT}).",
    )
    p.add_argument(
        "--version",
        type=str,
        default="1.0.0",
        help="Release version string (default 1.0.0).",
    )
    p.add_argument(
        "--rubric-channel",
        type=str,
        default="v10",
        help="Rubric channel recorded in the manifest (default v10).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written; do not write any files.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    tasks = load_tasks(args.tasks_dir)
    if not tasks:
        print(f"ERROR: no tasks found under {args.tasks_dir}", file=sys.stderr)
        return 1

    consensus_index = _load_consensus_index(args.consensus)
    hard_index = _load_hard_index(args.hard)

    # ----- Full: every task, full criteria -----
    full_rows: list[dict[str, Any]] = [
        _serialize_task(task, subset="full", criteria=_all_criteria(task)) for task in tasks
    ]

    # ----- Consensus: tasks with >=1 criterion in the Consensus manifest,
    # criteria filtered to Consensus-eligible llm_judge (plus all
    # world_state/pattern which pass through unfiltered). When the manifest
    # is missing, produce an empty subset. -----
    consensus_rows: list[dict[str, Any]] = []
    if consensus_index.status == "ok":
        for task in tasks:
            # Does this task have ANY llm_judge criterion in the Consensus set?
            task_llm_ids = {
                raw.get("id") for raw in task.criteria if raw.get("verification") == "llm_judge"
            }
            if not task_llm_ids & consensus_index.criterion_ids:
                continue
            filtered = _filter_consensus_criteria(task, consensus_index.criterion_ids)
            consensus_rows.append(_serialize_task(task, subset="consensus", criteria=filtered))

    # ----- Hard: task-level subset; criteria unfiltered -----
    hard_rows: list[dict[str, Any]] = []
    if hard_index.status == "ok":
        for task in tasks:
            if task.id in hard_index.task_ids:
                hard_rows.append(_serialize_task(task, subset="hard", criteria=_all_criteria(task)))

    if args.dry_run:
        _print_summary(
            output_dir=args.output_dir,
            version=args.version,
            full_rows=full_rows,
            consensus_rows=consensus_rows,
            hard_rows=hard_rows,
            consensus_status=consensus_index.status,
            hard_status=hard_index.status,
        )
        print("[dry-run] no files written.")
        return 0 if full_rows and len(full_rows) == len(tasks) else 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    _emit_jsonl(args.output_dir / "healthcraft_full.jsonl", full_rows)
    _emit_jsonl(args.output_dir / "healthcraft_consensus.jsonl", consensus_rows)
    _emit_jsonl(args.output_dir / "healthcraft_hard.jsonl", hard_rows)

    manifest = _write_manifest(
        args.output_dir,
        version=args.version,
        rubric_channel=args.rubric_channel,
        full_rows=full_rows,
        consensus_rows=consensus_rows,
        hard_rows=hard_rows,
        consensus_index=consensus_index,
        hard_index=hard_index,
    )
    _write_readme(args.output_dir, version=args.version, manifest=manifest)
    _write_license(args.output_dir)

    _print_summary(
        output_dir=args.output_dir,
        version=args.version,
        full_rows=full_rows,
        consensus_rows=consensus_rows,
        hard_rows=hard_rows,
        consensus_status=consensus_index.status,
        hard_status=hard_index.status,
    )

    # Exit 0 iff Full was emitted with every loaded task.
    if len(full_rows) != len(tasks) or not full_rows:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
