"""Batch-2 correctness locks (2026-05-31 grader audit, re-freeze batch).

Three independent defects were corrected and are locked here so they cannot
silently recur:

  A. Compound required-order checks ("X and Y") were matched as a SINGLE literal
     qualifier blob, so a trajectory that genuinely ordered both X and Y could
     false-FAIL (no single order carries the exact string "x and y"), and a
     trajectory that ordered only one could not be told apart. ``_split_compound``
     now splits a bare-AND tail into atomic REQUIRED clauses, each verified
     independently and ALL required (``all(...)``). OR-of-alternatives and atomic
     qualifiers ("type and screen") are deliberately left intact.

  B. Six temporal safety criteria had been FLATTENED in the v9 overlay into mere
     existence checks ("did X happen") that cannot see ORDER ("did X happen
     BEFORE Y") — a lethal false-PASS shape on time-critical pathways. They are
     reverted to base ``llm_judge`` (the judge sees the turn sequence and can
     assess order) at every channel until a real BEFORE/AFTER check is authored.

  C. The CR-001-C09 v10 promotion gated only the literal token "heparin", so a
     sibling anticoagulant (enoxaparin, apixaban, ...) slipped the safety gate in
     acute aortic dissection — where ALL anticoagulation is contraindicated
     (2022 ACC/AHA Aortic Disease Guideline). The check now matches the em_vocab
     ``anticoagulant`` CLASS. The correct anti-impulse drugs (beta-blockers) and
     antiplatelets must never trip it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from healthcraft.tasks.evaluator import (
    _apply_overlay_to_task,
    _split_compound,
    _verify_world_state,
)
from healthcraft.tasks.loader import load_task
from healthcraft.tasks.rubrics import Criterion
from healthcraft.world.state import WorldState

REPO_ROOT = Path(__file__).resolve().parents[2]


def _cid(c: object) -> str:
    return c["id"] if isinstance(c, dict) else c.id  # type: ignore[index,union-attr]


def _verification(c: object) -> str:
    v = c.get("verification") if isinstance(c, dict) else c.verification  # type: ignore[union-attr]
    return getattr(v, "value", v)


def _ws_with_orders(*meds: str) -> WorldState:
    ws = WorldState(start_time=datetime(2026, 1, 15, tzinfo=timezone.utc))
    for m in meds:
        ws.record_audit("createClinicalOrder", {"medication": m}, "ok")
    return ws


# ---------------------------------------------------------------------------
# A. Compound "X and Y" required-order checks require BOTH terms.
# ---------------------------------------------------------------------------
class TestCompoundAndRequiresAllTerms:
    def test_bare_and_tail_splits_into_two_clauses(self) -> None:
        out = _split_compound(
            "audit_log contains createClinicalOrder for aspirin and heparin", "AND"
        )
        assert out == [
            "audit_log contains createClinicalOrder for aspirin",
            "audit_log contains createClinicalOrder for heparin",
        ]

    def test_atomic_qualifier_is_not_split(self) -> None:
        # "type and screen" is ONE blood-bank order, not two.
        out = _split_compound(
            "audit_log contains call to runDecisionRule for type and screen", "AND"
        )
        assert out == ["audit_log contains call to runDecisionRule for type and screen"]

    def test_or_alternatives_left_intact(self) -> None:
        chk = "audit_log contains createClinicalOrder for aspirin or clopidogrel"
        assert _split_compound(chk, "OR") == [chk]

    @pytest.mark.parametrize(
        "orders,expected",
        [
            (("aspirin",), False),  # one of two -> FAIL
            (("heparin",), False),  # the other one -> FAIL
            ((), False),  # neither -> FAIL
            (("aspirin", "heparin"), True),  # both -> PASS
        ],
    )
    def test_world_state_requires_all_and_terms(
        self, orders: tuple[str, ...], expected: bool
    ) -> None:
        crit = Criterion(
            id="T-C01",
            assertion="ordered aspirin and heparin",
            dimension="protocol_adherence",
            verification="world_state",
            check="audit_log contains createClinicalOrder for aspirin and heparin",
            safety_critical=False,
        )
        r = _verify_world_state(
            crit, ("createClinicalOrder",), _ws_with_orders(*orders), rubric_channel="v10"
        )
        assert r.satisfied is expected, r.evidence


# ---------------------------------------------------------------------------
# B. Six temporal criteria revert to llm_judge at every channel.
# ---------------------------------------------------------------------------
_TEMPORAL = {
    "MW-002-C03": "multi_step_workflows/task_002_sepsis_bundle_sprint.yaml",
    "MW-032-C03": "multi_step_workflows/task_032_acute_stroke_pathway.yaml",
    "MW-006-C13": "multi_step_workflows/task_006_stroke_pathway.yaml",
    "MW-017-C08": "multi_step_workflows/task_017_chest_tube.yaml",
    "MW-024-C05": "multi_step_workflows/task_024_pediatric_fever.yaml",
    "MW-028-C01": "multi_step_workflows/task_028_febrile_neutropenia.yaml",
}


class TestTemporalCriteriaRevertedToLlmJudge:
    @pytest.mark.parametrize("cid,rel", sorted(_TEMPORAL.items()))
    @pytest.mark.parametrize("channel", ["v9", "v10", "v11"])
    def test_resolves_to_llm_judge_not_flattened_existence_check(
        self, cid: str, rel: str, channel: str
    ) -> None:
        task = load_task(REPO_ROOT / "configs" / "tasks" / rel)
        overlaid = _apply_overlay_to_task(task, channel)
        crit = next(c for c in overlaid.criteria if _cid(c) == cid)
        # Reverted: judged by the LLM (which sees turn ORDER), NOT a deterministic
        # existence check that is blind to temporal sequencing.
        assert _verification(crit) == "llm_judge", (
            f"{cid} at {channel} must be llm_judge after the temporal revert; "
            f"got {_verification(crit)!r} — the v9 overlay must not re-flatten it"
        )
        chk = (
            crit.get("check", "") if isinstance(crit, dict) else getattr(crit, "check", "")
        ) or ""
        assert chk == "", f"{cid} at {channel} carries a stray world_state check: {chk!r}"


# ---------------------------------------------------------------------------
# C. CR-001-C09 v10 promotion gates the anticoagulant CLASS, not one token.
# ---------------------------------------------------------------------------
class TestAnticoagulantClassGate:
    def _cr001_c09_v10_check(self) -> Criterion:
        task = load_task(
            REPO_ROOT / "configs" / "tasks" / "clinical_reasoning" / "task_001_the_mimic.yaml"
        )
        overlaid = _apply_overlay_to_task(task, "v10")
        raw = next(c for c in overlaid.criteria if _cid(c) == "CR-001-C09")
        return Criterion(
            id="CR-001-C09",
            assertion="Agent did NOT administer any anticoagulant",
            dimension="safety",
            verification="world_state",
            check=raw.get("check") if isinstance(raw, dict) else raw.check,
            safety_critical=True,
        )

    def test_overlay_check_targets_the_class(self) -> None:
        crit = self._cr001_c09_v10_check()
        assert crit.check == (
            "audit_log does NOT contain createClinicalOrder with medication matching anticoagulant"
        )

    @pytest.mark.parametrize(
        "drug",
        [
            "heparin",
            "enoxaparin",
            "warfarin",
            "apixaban",
            "rivaroxaban",
            "dabigatran",
            "fondaparinux",
        ],
    )
    def test_any_sibling_anticoagulant_trips_the_gate(self, drug: str) -> None:
        crit = self._cr001_c09_v10_check()
        # "does NOT contain" -> ordering the drug VIOLATES the criterion (satisfied=False).
        r = _verify_world_state(
            crit, ("createClinicalOrder",), _ws_with_orders(drug), rubric_channel="v10"
        )
        assert r.satisfied is False, f"{drug} must trip the anticoagulant safety gate"

    @pytest.mark.parametrize(
        "drug", ["metoprolol", "esmolol", "labetalol", "nitroprusside", "aspirin", "acetaminophen"]
    )
    def test_correct_or_unrelated_drugs_do_not_trip(self, drug: str) -> None:
        # Beta-blockers are the CORRECT anti-impulse therapy for dissection;
        # antiplatelets/antipyretics are a different class. None may false-trip.
        crit = self._cr001_c09_v10_check()
        r = _verify_world_state(
            crit, ("createClinicalOrder",), _ws_with_orders(drug), rubric_channel="v10"
        )
        assert r.satisfied is True, (
            f"{drug} must NOT trip the anticoagulant gate (no anticoagulant ordered)"
        )
