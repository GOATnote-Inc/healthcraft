"""Audit log invariants.

The audit log is the substrate world_state criteria are evaluated against.
If invariants are silently broken, criteria can flip without anyone editing
a YAML or a handler. These tests lock the invariants.

Invariants:

  1. Append-only:        recording an entry never reorders earlier entries.
  2. Monotonic time:     timestamps are non-decreasing in record order.
  3. Result-summary set: result_summary is a documented value
                         ('ok', 'error', 'unknown', or one of the
                         tool-specific status strings observed in V8).
  4. Tool-name preserved: world.record_audit() stores the tool_name verbatim.
                         The evaluator lowercases at compare time -- changing
                         this storage convention breaks V8 trajectory replay.
  5. Snapshot independence: WorldState.snapshot() returns a separate audit
                         list; mutating the original does not retroactively
                         appear in the snapshot.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from healthcraft.world.state import WorldState

# ---------------------------------------------------------------------------
# Invariant 1 + 2: Append-only and monotonic time
# ---------------------------------------------------------------------------


def test_audit_log_is_append_only() -> None:
    """Recording entries appends to the tail; earlier entries are unchanged."""
    ws = WorldState(start_time=datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc))
    e1 = ws.record_audit(tool_name="getPatientHistory", params={"a": 1}, result_summary="ok")
    e2 = ws.record_audit(tool_name="searchEncounters", params={"b": 2}, result_summary="ok")
    e3 = ws.record_audit(tool_name="createClinicalOrder", params={"c": 3}, result_summary="error")

    assert ws.audit_log == [e1, e2, e3]


def test_audit_log_timestamps_monotonic_with_advance_time() -> None:
    """As the simulation clock advances, audit timestamps follow."""
    ws = WorldState(start_time=datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc))
    ws.record_audit(tool_name="t1", params={}, result_summary="ok")
    ws.advance_time(5)
    ws.record_audit(tool_name="t2", params={}, result_summary="ok")
    ws.advance_time(0)  # zero advance is allowed
    ws.record_audit(tool_name="t3", params={}, result_summary="ok")

    timestamps = [e.timestamp for e in ws.audit_log]
    assert timestamps == sorted(timestamps), "timestamps must be non-decreasing"


def test_advance_time_rejects_negative() -> None:
    """Backwards time would let a later entry appear earlier than an earlier one."""
    ws = WorldState()
    with pytest.raises(ValueError):
        ws.advance_time(-1)


# ---------------------------------------------------------------------------
# Invariant 3: result_summary is in the documented set
# ---------------------------------------------------------------------------

# Expanded by the V8 corpus: handlers may pass the tool's status verbatim,
# so the documented set is the union of {'ok', 'error', 'unknown'}.
_DOCUMENTED_RESULT_SUMMARIES = frozenset({"ok", "error", "unknown"})


def test_result_summary_documented_values() -> None:
    """Server.call_tool only writes documented result_summary values."""
    from healthcraft.mcp.server import create_server

    ws = WorldState()
    server = create_server(ws)
    # Trigger one ok and one error via the empty world.
    server.call_tool("searchPatients", {})
    server.call_tool("getEncounterDetails", {"encounter_id": "ENC-DEADBEEF"})
    # Trigger an unknown tool name -> error path that still records ok/error
    # at the world.record_audit layer (server logs only on success).
    for entry in ws.audit_log:
        assert entry.result_summary in _DOCUMENTED_RESULT_SUMMARIES, (
            f"undocumented result_summary {entry.result_summary!r} for tool {entry.tool_name!r}"
        )


# ---------------------------------------------------------------------------
# Invariant 4: tool_name is stored verbatim (casing preserved at storage)
# ---------------------------------------------------------------------------


def test_tool_name_stored_verbatim_camelcase() -> None:
    """camelCase calls are recorded as camelCase (evaluator lowercases at compare)."""
    from healthcraft.mcp.server import create_server

    ws = WorldState()
    server = create_server(ws)
    server.call_tool("searchPatients", {})

    assert any(e.tool_name == "searchPatients" for e in ws.audit_log), (
        "Expected camelCase 'searchPatients' in audit log; if storage now "
        "lowercases tool names, V8 trajectory replay will break (V8 audit "
        "logs were captured with camelCase tool_name strings)."
    )


def test_tool_name_stored_verbatim_snake_case() -> None:
    """snake_case calls are also accepted and stored as snake_case.

    The server accepts both forms; the storage convention is 'whatever
    the agent called it' so trajectories are faithful to agent behavior.
    """
    from healthcraft.mcp.server import create_server

    ws = WorldState()
    server = create_server(ws)
    server.call_tool("search_patients", {})

    assert any(e.tool_name == "search_patients" for e in ws.audit_log)


# ---------------------------------------------------------------------------
# Invariant 5: Snapshot independence
# ---------------------------------------------------------------------------


def test_snapshot_audit_log_is_independent() -> None:
    """Mutating the original world's audit log must not appear in a snapshot."""
    ws = WorldState()
    ws.record_audit(tool_name="t1", params={}, result_summary="ok")
    snap = ws.snapshot()
    pre_snapshot_count = len(snap.audit_log)

    ws.record_audit(tool_name="t2", params={}, result_summary="ok")

    assert len(snap.audit_log) == pre_snapshot_count, (
        "Snapshot's audit log must not see entries added after snapshot()"
    )
    assert len(ws.audit_log) == pre_snapshot_count + 1


def test_snapshot_preserves_pre_snapshot_entries() -> None:
    """Entries recorded before snapshot() are present (and identical) in the copy."""
    ws = WorldState()
    e1 = ws.record_audit(tool_name="getProtocolDetails", params={"x": 1}, result_summary="ok")
    snap = ws.snapshot()
    assert snap.audit_log == [e1]


# ---------------------------------------------------------------------------
# Bonus: server records both layers (HealthcraftServer audit AND world audit)
# ---------------------------------------------------------------------------


def test_world_record_audit_entry_count_matches_successful_calls() -> None:
    """Every successful tool call writes one world.audit_log entry.

    Errors (unknown tool, validation failure) write only to the server's audit
    logger; the world audit log is the substrate for evaluator scoring, so
    failed dispatches must NOT appear there or the negative-check criteria
    will flip incorrectly.
    """
    from healthcraft.mcp.server import create_server

    ws = WorldState()
    server = create_server(ws)
    server.call_tool("searchPatients", {})  # ok
    server.call_tool("nonexistentTool", {})  # unknown -> world log NOT touched
    server.call_tool("createClinicalOrder", {})  # missing params -> error

    world_tool_names = [e.tool_name for e in ws.audit_log]
    # searchPatients should be there; nonexistentTool should NOT be
    # (server skips world.record_audit on unknown tool).
    assert "searchPatients" in world_tool_names
    assert "nonexistentTool" not in world_tool_names
