"""Tests for DecisionRule entity."""

from __future__ import annotations

import pytest

from healthcraft.entities.base import EntityType
from healthcraft.entities.decision_rules import DecisionRule, load_decision_rules


class TestLoadDecisionRules:
    """Test bundled decision rule loading."""

    def test_load_returns_dict(self) -> None:
        rules = load_decision_rules()
        assert isinstance(rules, dict)

    def test_load_returns_at_least_10(self) -> None:
        rules = load_decision_rules()
        assert len(rules) >= 10

    def test_all_values_are_decision_rule(self) -> None:
        rules = load_decision_rules()
        for rule in rules.values():
            assert isinstance(rule, DecisionRule)

    def test_rule_entity_type(self) -> None:
        rules = load_decision_rules()
        for rule in rules.values():
            assert rule.entity_type == EntityType.DECISION_RULE

    def test_rule_has_required_fields(self) -> None:
        rules = load_decision_rules()
        for rule in rules.values():
            assert rule.id
            assert rule.name
            assert isinstance(rule.variables, tuple)
            assert isinstance(rule.score_ranges, tuple)

    def test_heart_score_exists(self) -> None:
        rules = load_decision_rules()
        names = [r.name.lower() for r in rules.values()]
        assert any("heart" in n for n in names)

    def test_wells_pe_exists(self) -> None:
        rules = load_decision_rules()
        names = [r.name.lower() for r in rules.values()]
        assert any("wells" in n for n in names)

    def test_qsofa_exists(self) -> None:
        rules = load_decision_rules()
        names = [r.name.lower() for r in rules.values()]
        assert any("qsofa" in n or "sofa" in n for n in names)

    def test_ottawa_exists(self) -> None:
        rules = load_decision_rules()
        names = [r.name.lower() for r in rules.values()]
        assert any("ottawa" in n for n in names)

    def test_rule_is_frozen(self) -> None:
        rules = load_decision_rules()
        rule = next(iter(rules.values()))
        with pytest.raises(AttributeError):
            rule.name = "Modified"  # type: ignore[misc]

    def test_rules_have_score_ranges(self) -> None:
        rules = load_decision_rules()
        for rule in rules.values():
            assert len(rule.score_ranges) >= 1, f"{rule.name} has no score ranges"

    def test_rules_have_variables(self) -> None:
        rules = load_decision_rules()
        for rule in rules.values():
            assert len(rule.variables) >= 1, f"{rule.name} has no variables"
