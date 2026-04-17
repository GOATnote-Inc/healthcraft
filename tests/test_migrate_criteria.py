"""Regression tests for scripts/migrate_criteria.py keyword matching.

The migration script previously used substring matching (`keyword in text`),
which produced false-positive 'high-confidence' imaging classifications when
short tokens like 'ct' appeared inside unrelated words: 'correct',
'products', 'spectrum', 'induction', 'activity'.

This test locks in word-boundary matching behavior so the high-confidence
bucket remains trustworthy for populating the v9 overlay.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location(
    "migrate_criteria", SCRIPTS_DIR / "migrate_criteria.py"
)
assert spec is not None and spec.loader is not None
migrate_criteria = importlib.util.module_from_spec(spec)
sys.modules["migrate_criteria"] = migrate_criteria
spec.loader.exec_module(migrate_criteria)


# --- False positives from v9_migrations_proposed.yaml (high-confidence bucket) --- #
#
# Each of these is an ordering assertion that previously matched 'ct'
# inside an unrelated word and was auto-labeled 'imaging' with confidence=high.
FALSE_POSITIVE_CT_CASES = [
    # MW-011-C02 -- 'correct' contains 'ct'
    "Agent ordered epinephrine at correct pediatric dose",
    # MW-004-C12 -- 'products' contains 'ct'
    "Agent ordered blood products with appropriate ratios",
    # MW-002-C04 -- 'broad-spectrum' contains 'ct' (in 'spectrum')
    "Agent ordered broad-spectrum coverage",
    # MW-008-C03 -- 'induction' contains 'ct'
    "Agent ordered preoxygenation before induction",
    # CR-041-C11 -- 'activity' contains 'ct'
    "Agent ordered ADAMTS13 activity level",
    # CR-024-C11 -- 'osmotic' contains 'ct'
    "Agent ordered IV mannitol for osmotic reduction",
    # CR-031-C10 -- 'products' contains 'ct'
    "Agent ordered blood products during DIC resuscitation",
]


@pytest.mark.parametrize("assertion", FALSE_POSITIVE_CT_CASES)
def test_ordering_no_ct_substring_false_positive(assertion: str) -> None:
    """Assertions containing 'ct' only inside unrelated words must not
    auto-classify as high-confidence imaging."""
    result = migrate_criteria._propose_ordering(assertion)
    assert result is not None, f"Expected a proposal for: {assertion!r}"
    # The bug: confidence=high with reason mentioning 'ct' -> imaging.
    # After fix, either a different legitimate keyword matches (blood products,
    # antibiotics, iv fluids) OR it falls through to generic low-confidence.
    reason = result["reason"]
    assert "'ct'" not in reason, (
        f"False positive: 'ct' substring matched inside unrelated word. "
        f"Assertion: {assertion!r}, reason: {reason!r}"
    )


def test_ordering_ct_true_positive_still_matches() -> None:
    """'ordered CT head' must still match ct -> imaging at high confidence."""
    result = migrate_criteria._propose_ordering("Agent ordered CT head")
    assert result is not None
    assert result["confidence"] == "high"
    assert result["proposed_check"] == (
        "audit_log contains call to createClinicalOrder for imaging"
    )


def test_ordering_mri_true_positive_still_matches() -> None:
    result = migrate_criteria._propose_ordering("Agent ordered MRI brain without contrast")
    assert result is not None
    assert result["confidence"] == "high"
    assert "imaging" in result["proposed_check"]


def test_ordering_blood_products_routes_to_blood_product_not_imaging() -> None:
    """'blood products' should route to blood_product, not imaging via 'ct' in
    'products'."""
    result = migrate_criteria._propose_ordering(
        "Agent ordered blood products with appropriate ratios"
    )
    assert result is not None
    assert "blood_product" in result["proposed_check"]
    assert "imaging" not in result["proposed_check"]


def test_ordering_antibiotics_routes_to_medication_not_imaging() -> None:
    """'broad-spectrum antibiotics' should route to medication, not imaging via
    'ct' in 'spectrum'."""
    result = migrate_criteria._propose_ordering(
        "Agent ordered broad-spectrum antibiotics appropriate for sepsis"
    )
    assert result is not None
    assert "medication" in result["proposed_check"]
    assert "imaging" not in result["proposed_check"]


def test_match_keyword_word_boundary() -> None:
    assert migrate_criteria._match_keyword("ct", "ordered ct head") is True
    assert migrate_criteria._match_keyword("ct", "ordered a CT".lower()) is True
    assert migrate_criteria._match_keyword("ct", "correct pediatric dose") is False
    assert migrate_criteria._match_keyword("ct", "broad-spectrum") is False
    assert migrate_criteria._match_keyword("ct", "blood products") is False
    assert migrate_criteria._match_keyword("ct", "adamts13 activity") is False
