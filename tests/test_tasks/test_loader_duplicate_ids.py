"""Duplicate criterion_id guard + channel-choice sync.

A duplicate criterion id inside a task silently aliased verdicts in
``results_map = {r.criterion_id: r}`` (last-write-wins) — a safety_critical FAIL
could be masked by a benign PASS with the same id. The loader now rejects it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from healthcraft.llm.orchestrator import _VALID_RUBRIC_CHANNELS
from healthcraft.tasks.loader import load_task, load_tasks

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_duplicate_criterion_id_is_rejected() -> None:
    task = {
        "id": "DUP-1",
        "category": "safety_critical_judgment",
        "level": 3,
        "title": "dup",
        "description": "dup",
        "criteria": [
            {
                "id": "D-C01",
                "assertion": "fail",
                "verification": "llm_judge",
                "safety_critical": True,
            },
            {"id": "D-C01", "assertion": "pass", "verification": "llm_judge"},
        ],
    }
    p = Path(tempfile.mktemp(suffix=".yaml"))
    p.write_text(yaml.safe_dump(task))
    with pytest.raises(ValueError, match="duplicate"):
        load_task(p)


def test_corpus_has_no_duplicate_criterion_ids() -> None:
    # If any shipped task had duplicate ids, the guard above would make this raise.
    assert len(load_tasks(REPO_ROOT / "configs" / "tasks")) == 205


def test_v11_is_a_valid_rubric_channel() -> None:
    # The CLI derives --rubric-channel choices from this set, so v11 is reachable.
    assert "v11" in _VALID_RUBRIC_CHANNELS
