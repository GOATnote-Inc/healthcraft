"""Tests for the reasoner, rule versioning, and persistent audit log.

These cover the AI-Factor / feasibility additions:

- Reasoner picks the right primary rule family for each canonical scenario.
- Reasoner skips rules with insufficient extracted data (no false-conflict).
- Reasoner detects conflict when rules truly disagree (forced via stub).
- Rule version is deterministic and content-stable.
- Audit log records one invocation per agent run with the right fields.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from healthcraft.agents_assemble.agent_triage.agent import create_triage_agent
from healthcraft.agents_assemble.agent_triage.reasoner import (
    HeuristicReasoner,
    ReasoningOutput,
    RuleRun,
    _synthesize,
)
from healthcraft.agents_assemble.audit import (
    AuditLog,
    record_invocation,
    reset_default_log,
)
from healthcraft.agents_assemble.demo.bundles import load_scenario
from healthcraft.agents_assemble.superpower_decision_rules.rule_version import (
    rule_version,
    short_version,
)
from healthcraft.entities.decision_rules import load_decision_rules
from healthcraft.world.state import WorldState


@pytest.fixture
def world() -> WorldState:
    w = WorldState()
    for rid, r in load_decision_rules().items():
        w.put_entity("decision_rule", rid, r)
    return w


# ---------------------------------------------------------------------------
# Reasoner — primary rule selection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scenario_id,expected_primary",
    [
        ("stemi", "HEART Score"),
        ("pe_high", "Wells Criteria for PE"),
        ("pe_low", "Wells Criteria for PE"),
        ("sepsis", "qSOFA"),
    ],
)
def test_reasoner_picks_correct_primary_rule(
    world: WorldState, scenario_id: str, expected_primary: str
) -> None:
    bundle = load_scenario(scenario_id).bundle
    out = HeuristicReasoner(world).reason(bundle)
    scored_rules = [r.rule_name for r in out.runs if r.risk_level is not None]
    assert expected_primary in scored_rules


def test_reasoner_drops_rules_with_no_extracted_data(world: WorldState) -> None:
    """Rules whose variables we cannot extract should be skipped, not silently
    treated as 'low risk'. The sepsis bundle should NOT cause CURB-65 / NEWS2
    / MEWS to vote 'low' (their variables aren't extractable)."""
    bundle = load_scenario("sepsis").bundle
    out = HeuristicReasoner(world).reason(bundle)
    scored = {r.rule_name: r.risk_level for r in out.runs if r.risk_level is not None}
    # Only qSOFA has a deterministic extractor for vitals; the others are
    # candidates but should be marked None (insufficient data).
    assert scored == {"qSOFA": "high"}


def test_synthesize_flags_conflict_only_when_real(world: WorldState) -> None:
    runs = [
        RuleRun("HEART Score", 8, "high", "", ""),
        RuleRun("PERC Rule", 0, "low", "", ""),
    ]
    text, conflict = _synthesize(runs)
    assert conflict is True
    assert "CONFLICT" in text


def test_synthesize_concur_when_close(world: WorldState) -> None:
    runs = [
        RuleRun("HEART Score", 5, "moderate", "", ""),
        RuleRun("TIMI", 4, "moderate", "", ""),
    ]
    text, conflict = _synthesize(runs)
    assert conflict is False
    assert "concur" in text


def test_synthesize_no_runs_returns_no_rule_message() -> None:
    text, conflict = _synthesize([])
    assert conflict is False
    assert "No applicable" in text


# ---------------------------------------------------------------------------
# Conflict-driven disposition escalation
# ---------------------------------------------------------------------------


def test_agent_escalates_to_physician_review_on_conflict(world: WorldState) -> None:
    """If the reasoner reports a conflict, disposition becomes
    ``physician_review`` regardless of what the highest-severity rule said."""
    fake = ReasoningOutput(
        chief_complaint="probe",
        applicable_rules=["HEART Score", "PERC Rule"],
        runs=[
            RuleRun("HEART Score", 8, "high", "", ""),
            RuleRun("PERC Rule", 0, "low", "", ""),
        ],
        synthesis="CONFLICT",
        has_conflict=True,
        no_applicable_rule=False,
        unsupported_findings=["new RBBB"],
        method="heuristic",
    )
    with patch.object(HeuristicReasoner, "reason", return_value=fake):
        agent = create_triage_agent(world)
        plan = agent.run({"resourceType": "Bundle", "type": "collection", "entry": []})
    assert plan.disposition["recommendation"] == "physician_review"
    assert plan.reasoning["has_conflict"] is True
    assert plan.reasoning["unsupported_findings"] == ["new RBBB"]


# ---------------------------------------------------------------------------
# Rule versioning
# ---------------------------------------------------------------------------


def test_rule_version_is_deterministic_across_calls(world: WorldState) -> None:
    rules = world.list_entities("decision_rule")
    heart = next(r for r in rules.values() if r.name == "HEART Score")
    assert rule_version(heart) == rule_version(heart)
    assert short_version(heart) == rule_version(heart)[:12]


def test_rule_version_differs_between_rules(world: WorldState) -> None:
    rules = world.list_entities("decision_rule")
    heart = next(r for r in rules.values() if r.name == "HEART Score")
    qsofa = next(r for r in rules.values() if r.name == "qSOFA")
    assert rule_version(heart) != rule_version(qsofa)


def test_rule_version_ignores_description_field(world: WorldState) -> None:
    """Editing free-text doc fields must NOT bump the rule version."""
    rules = world.list_entities("decision_rule")
    heart = next(r for r in rules.values() if r.name == "HEART Score")
    from dataclasses import asdict

    base = asdict(heart)
    edited = dict(base)
    edited["description"] = base["description"] + " (clarified copy)"
    assert rule_version(base) == rule_version(edited)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def test_audit_log_records_invocation(tmp_path: Any) -> None:
    log_path = tmp_path / "audit.jsonl"
    log = AuditLog(log_path)
    record_invocation(
        correlation_id="corr-x",
        bundle_sha256="abc123",
        rule_name="HEART Score",
        rule_version="def456",
        score=5,
        risk_level="moderate",
        disposition="admit",
        has_conflict=False,
        log=log,
    )
    rows = log.read_all()
    assert len(rows) == 1
    assert rows[0]["correlationId"] == "corr-x"
    assert rows[0]["bundleSha256"] == "abc123"
    assert rows[0]["ruleName"] == "HEART Score"
    assert rows[0]["disposition"] == "admit"
    assert "ts" in rows[0]


def test_audit_log_in_memory_when_no_path() -> None:
    reset_default_log()
    log = AuditLog()
    record_invocation(
        correlation_id="corr-y",
        bundle_sha256="z",
        rule_name=None,
        rule_version=None,
        score=None,
        risk_level=None,
        disposition="observation",
        has_conflict=False,
        log=log,
    )
    assert len(log.read_all()) == 1


def test_agent_writes_to_audit_log_via_default(world: WorldState) -> None:
    reset_default_log()
    agent = create_triage_agent(world)
    agent.run(load_scenario("stemi").bundle, sharp={"correlationId": "corr-stemi-audit"})
    from healthcraft.agents_assemble.audit import default_log

    rows = default_log().read_all()
    assert any(r["correlationId"] == "corr-stemi-audit" for r in rows)
