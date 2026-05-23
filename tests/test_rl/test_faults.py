"""Tests for healthcraft.mcp.faults.FaultInjector (PR-B / WS-5).

Pure-Python, no network, no GPU. The injector wraps an inner dispatcher
and never calls a real MCP tool — these tests use an identity stub.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from healthcraft.mcp.faults import FaultInjector, FaultProfile
from healthcraft.world.state import WorldState


def _world() -> WorldState:
    return WorldState(start_time=datetime(2026, 1, 1, tzinfo=timezone.utc))


def _identity_dispatch(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Reference dispatcher: returns a success envelope unchanged."""
    return {"status": "ok", "data": {"tool": tool_name, "params": dict(params)}}


# ---------------------------------------------------------------------------
# FaultProfile validation
# ---------------------------------------------------------------------------


def test_profile_defaults_are_zero_fault():
    p = FaultProfile()
    assert p.transient_failure_rate == 0.0
    assert p.latency_mean_minutes == 0.0
    assert p.latency_jitter_minutes == 0.0
    assert p.retry_budget == 5
    assert p.max_retry_after_seconds == 5


def test_profile_rejects_out_of_range_rate():
    with pytest.raises(ValueError, match="transient_failure_rate"):
        FaultProfile(transient_failure_rate=1.5)
    with pytest.raises(ValueError, match="transient_failure_rate"):
        FaultProfile(transient_failure_rate=-0.1)


def test_profile_rejects_negative_latency():
    with pytest.raises(ValueError, match="latency_mean"):
        FaultProfile(latency_mean_minutes=-1.0)
    with pytest.raises(ValueError, match="latency_jitter"):
        FaultProfile(latency_jitter_minutes=-0.5)


def test_profile_rejects_invalid_retry_budget():
    with pytest.raises(ValueError, match="retry_budget"):
        FaultProfile(retry_budget=0)


def test_profile_rejects_invalid_max_retry_after():
    with pytest.raises(ValueError, match="max_retry_after_seconds"):
        FaultProfile(max_retry_after_seconds=0)


# ---------------------------------------------------------------------------
# FaultInjector behaviour
# ---------------------------------------------------------------------------


def test_zero_fault_profile_is_identity():
    """All zeros → wrapped dispatcher returns whatever the inner returns."""
    inj = FaultInjector(FaultProfile(), _world())
    wrapped = inj.wrap(_identity_dispatch)
    r = wrapped("anyTool", {"x": 1})
    assert r["status"] == "ok"
    assert r["data"]["tool"] == "anyTool"
    assert r["data"]["params"] == {"x": 1}


def test_transient_failure_returns_service_unavailable():
    """transient_failure_rate=1.0 → every call returns service_unavailable."""
    inj = FaultInjector(FaultProfile(transient_failure_rate=1.0, seed=42), _world())
    wrapped = inj.wrap(_identity_dispatch)
    r = wrapped("createClinicalOrder", {"idempotency_key": "k1"})
    assert r["status"] == "error"
    assert r["code"] == "service_unavailable"
    assert "retry_after" in r
    assert 1 <= r["retry_after"] <= 5


def test_latency_advances_world_clock():
    """Latency injection advances the simulated clock; no wall-clock sleep."""
    w = _world()
    t0 = w.timestamp
    inj = FaultInjector(FaultProfile(latency_mean_minutes=3.0, seed=1), w)
    wrapped = inj.wrap(_identity_dispatch)
    wrapped("anyTool", {})
    delta_minutes = (w.timestamp - t0).total_seconds() / 60.0
    # mean=3, no jitter → 3 minutes exactly (clock has minute resolution).
    assert delta_minutes == 3.0


def test_retry_budget_enforces_cap():
    """retry_budget+1 attempts with the same key → final call overflows."""
    inj = FaultInjector(FaultProfile(retry_budget=3, seed=7), _world())
    wrapped = inj.wrap(_identity_dispatch)
    # First 3 attempts proceed.
    for _ in range(3):
        r = wrapped("createClinicalOrder", {"idempotency_key": "k-overflow"})
        assert r.get("code") != "retry_budget_exceeded"
    # 4th attempt overflows.
    r = wrapped("createClinicalOrder", {"idempotency_key": "k-overflow"})
    assert r["status"] == "error"
    assert r["code"] == "retry_budget_exceeded"


def test_retry_budget_independent_per_key():
    """Each idempotency_key has its own budget."""
    inj = FaultInjector(FaultProfile(retry_budget=2, seed=0), _world())
    wrapped = inj.wrap(_identity_dispatch)
    wrapped("createClinicalOrder", {"idempotency_key": "k1"})
    wrapped("createClinicalOrder", {"idempotency_key": "k1"})
    # k2 has fresh budget — first attempt must not overflow.
    r = wrapped("createClinicalOrder", {"idempotency_key": "k2"})
    assert r.get("code") != "retry_budget_exceeded"


def test_no_idempotency_key_bypasses_budget():
    """Calls without a key are not budget-tracked (no notion of logical retry)."""
    inj = FaultInjector(FaultProfile(retry_budget=1, seed=0), _world())
    wrapped = inj.wrap(_identity_dispatch)
    for _ in range(10):
        r = wrapped("getEncounterDetails", {})
        assert r.get("code") != "retry_budget_exceeded"


def test_seeded_reproducibility():
    """Same seed + same profile → same pass/fail sequence."""
    profile = FaultProfile(transient_failure_rate=0.5, seed=12345)
    wrapped_a = FaultInjector(profile, _world()).wrap(_identity_dispatch)
    wrapped_b = FaultInjector(profile, _world()).wrap(_identity_dispatch)
    seq_a = [wrapped_a("getEncounterDetails", {})["status"] for _ in range(20)]
    seq_b = [wrapped_b("getEncounterDetails", {})["status"] for _ in range(20)]
    assert seq_a == seq_b


def test_distinct_seeds_diverge():
    """Different seeds → different fault sequences (probabilistically certain at N=50)."""
    p1 = FaultProfile(transient_failure_rate=0.5, seed=1)
    p2 = FaultProfile(transient_failure_rate=0.5, seed=2)
    wrapped_a = FaultInjector(p1, _world()).wrap(_identity_dispatch)
    wrapped_b = FaultInjector(p2, _world()).wrap(_identity_dispatch)
    a = [wrapped_a("getEncounterDetails", {})["status"] for _ in range(50)]
    b = [wrapped_b("getEncounterDetails", {})["status"] for _ in range(50)]
    assert a != b


def test_attempt_count_property_reflects_state():
    """attempt_count property exposes the per-bucket counter."""
    inj = FaultInjector(FaultProfile(retry_budget=10, seed=0), _world())
    wrapped = inj.wrap(_identity_dispatch)
    wrapped("createClinicalOrder", {"idempotency_key": "k1"})
    wrapped("createClinicalOrder", {"idempotency_key": "k1"})
    wrapped("createClinicalOrder", {"idempotency_key": "k2"})
    counts = inj.attempt_count
    assert counts[("createClinicalOrder", "k1")] == 2
    assert counts[("createClinicalOrder", "k2")] == 1
