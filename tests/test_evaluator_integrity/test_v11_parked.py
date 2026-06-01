"""v11 consensus overlay is PARKED — tripwire (2026-05-31 v11 audit).

The audit (workflow waz7dce3y) confirmed CRITICAL gaps in the machinery that
would POPULATE v11 — scripts/propose_overlay_entries.py accepts a deterministic
check on >=0.95 oracle agreement ALONE, with no clinical-correctness gate and no
hard safety_critical refusal, defaulting to the contaminated saved_judge oracle
(findings D2-F1, D2-F2, D5-F1, D5-F2). A hallucinated safety PASS could be
laundered into a permanent deterministic v11 check.

These are LATENT today only because v11 is empty (v11 == v10). This test is the
tripwire: if anyone runs the proposer and populates v11 before the gated
hardening lands (physician-adjudicated safety gate + ensemble-oracle reuse +
proposer test coverage), CI goes red and forces the review. Until then, any
accounting "graded at v10" is provably identical to v11.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from healthcraft.llm.orchestrator import _load_overlay

REPO_ROOT = Path(__file__).resolve().parents[2]
V11_FILE = REPO_ROOT / "configs" / "rubrics" / "v11_consensus_overlay.yaml"


def test_v11_overlay_file_is_empty() -> None:
    data = yaml.safe_load(V11_FILE.read_text(encoding="utf-8"))
    assert data["overlays"] == [], (
        "v11 consensus overlay is no longer empty — the proposer was run. v11 is "
        "PARKED pending the gated hardening (audit waz7dce3y: D2-F1/F2, D5-F1/F2). "
        "Populating it requires that work first; remove this tripwire only then."
    )
    assert data.get("n_accepted", 0) == 0


def test_v11_channel_equals_v10_while_parked() -> None:
    # Empty v11 must be a strict no-op over v10. (The smoke test self-disables on
    # population; this asserts the parked invariant directly.)
    assert _load_overlay("v11") == _load_overlay("v10")
