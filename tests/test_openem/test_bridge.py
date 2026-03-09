"""Tests for OpenEM bridge."""

from __future__ import annotations

import pytest

from healthcraft.openem.bridge import HAS_OPENEM, OpenEMBridge


class TestOpenEMBridgeFallback:
    """Test graceful fallback when openem is not installed."""

    def test_bridge_initializes_without_openem(self) -> None:
        # Force fallback mode
        bridge = OpenEMBridge(use_openem=False)
        assert bridge.source in ("bundled_file", "bundled_inline")

    def test_bridge_has_conditions(self) -> None:
        bridge = OpenEMBridge(use_openem=False)
        assert bridge.condition_count > 0

    def test_bridge_loads_bundled_conditions(self) -> None:
        bridge = OpenEMBridge(use_openem=False)
        conditions = bridge.load_conditions()
        assert isinstance(conditions, dict)
        assert len(conditions) > 0


class TestOpenEMBridgeConditionLookup:
    """Test condition lookup operations."""

    def test_get_known_condition(self) -> None:
        bridge = OpenEMBridge(use_openem=False)
        condition = bridge.get_condition("STEMI")
        assert condition is not None
        assert "STEMI" in condition.get("condition_id", condition.get("condition_name", ""))

    def test_get_unknown_condition_returns_none(self) -> None:
        bridge = OpenEMBridge(use_openem=False)
        condition = bridge.get_condition("NONEXISTENT_CONDITION_XYZ")
        assert condition is None

    def test_get_confusion_pairs(self) -> None:
        bridge = OpenEMBridge(use_openem=False)
        pairs = bridge.get_confusion_pairs("STEMI")
        assert isinstance(pairs, list)

    def test_get_confusion_pairs_unknown(self) -> None:
        bridge = OpenEMBridge(use_openem=False)
        pairs = bridge.get_confusion_pairs("NONEXISTENT")
        assert pairs == []

    def test_get_decision_rules(self) -> None:
        bridge = OpenEMBridge(use_openem=False)
        rules = bridge.get_decision_rules("STEMI")
        assert isinstance(rules, list)

    def test_search_conditions(self) -> None:
        bridge = OpenEMBridge(use_openem=False)
        results = bridge.search_conditions("stroke")
        assert isinstance(results, list)
        # Should find STROKE_ISCHEMIC in bundled data
        assert len(results) >= 1

    def test_search_conditions_empty(self) -> None:
        bridge = OpenEMBridge(use_openem=False)
        results = bridge.search_conditions("zzzzz_no_match_zzzzz")
        assert results == []

    def test_search_by_category(self) -> None:
        bridge = OpenEMBridge(use_openem=False)
        results = bridge.search_conditions("cardiovascular")
        assert len(results) >= 1

    def test_bridge_repr(self) -> None:
        bridge = OpenEMBridge(use_openem=False)
        r = repr(bridge)
        assert "OpenEMBridge" in r
        assert "conditions=" in r


class TestOpenEMAvailability:
    """Test HAS_OPENEM flag behavior."""

    def test_has_openem_is_bool(self) -> None:
        assert isinstance(HAS_OPENEM, bool)

    @pytest.mark.skipif(not HAS_OPENEM, reason="OpenEM not installed")
    def test_openem_mode_loads_more_conditions(self) -> None:
        bridge_openem = OpenEMBridge(use_openem=True)
        bridge_bundled = OpenEMBridge(use_openem=False)
        # OpenEM should have more conditions than bundled
        assert bridge_openem.condition_count >= bridge_bundled.condition_count
