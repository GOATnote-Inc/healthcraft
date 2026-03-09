"""Tests for WorldState."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from healthcraft.world.state import WorldState


class TestWorldStateEntityCRUD:
    """Test entity storage and retrieval."""

    def test_put_and_get_entity(self) -> None:
        world = WorldState()
        entity = {"id": "PAT-001", "name": "Test Patient"}
        world.put_entity("patient", "PAT-001", entity)
        assert world.get_entity("patient", "PAT-001") == entity

    def test_get_nonexistent_entity_returns_none(self) -> None:
        world = WorldState()
        assert world.get_entity("patient", "PAT-999") is None

    def test_put_overwrites_existing(self) -> None:
        world = WorldState()
        world.put_entity("patient", "PAT-001", {"id": "PAT-001", "v": 1})
        world.put_entity("patient", "PAT-001", {"id": "PAT-001", "v": 2})
        assert world.get_entity("patient", "PAT-001")["v"] == 2

    def test_unknown_entity_type_raises(self) -> None:
        world = WorldState()
        with pytest.raises(KeyError, match="Unknown entity type"):
            world.get_entity("nonexistent_type", "X")

    def test_put_unknown_entity_type_raises(self) -> None:
        world = WorldState()
        with pytest.raises(KeyError, match="Unknown entity type"):
            world.put_entity("nonexistent_type", "X", {})

    def test_list_entities(self) -> None:
        world = WorldState()
        world.put_entity("patient", "PAT-001", {"id": "PAT-001"})
        world.put_entity("patient", "PAT-002", {"id": "PAT-002"})
        entities = world.list_entities("patient")
        assert len(entities) == 2
        assert "PAT-001" in entities
        assert "PAT-002" in entities

    def test_list_entities_returns_copy(self) -> None:
        world = WorldState()
        world.put_entity("patient", "PAT-001", {"id": "PAT-001"})
        entities = world.list_entities("patient")
        entities["PAT-999"] = {"id": "PAT-999"}
        # Original should be unaffected
        assert world.get_entity("patient", "PAT-999") is None


class TestWorldStateSnapshot:
    """Test snapshot immutability."""

    def test_snapshot_returns_copy(self) -> None:
        world = WorldState()
        world.put_entity("patient", "PAT-001", {"id": "PAT-001"})
        snap = world.snapshot()
        assert snap.get_entity("patient", "PAT-001") is not None

    def test_snapshot_is_independent(self) -> None:
        world = WorldState()
        world.put_entity("patient", "PAT-001", {"id": "PAT-001"})
        snap = world.snapshot()

        # Mutate original
        world.put_entity("patient", "PAT-002", {"id": "PAT-002"})

        # Snapshot should not have the new entity
        assert snap.get_entity("patient", "PAT-002") is None

    def test_snapshot_time_is_independent(self) -> None:
        world = WorldState()
        snap = world.snapshot()

        world.advance_time(60)

        assert snap.timestamp != world.timestamp


class TestWorldStateTime:
    """Test time advancement."""

    def test_initial_timestamp(self) -> None:
        start = datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        world = WorldState(start_time=start)
        assert world.timestamp == start

    def test_advance_time(self) -> None:
        start = datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        world = WorldState(start_time=start)
        world.advance_time(30)
        expected = start + timedelta(minutes=30)
        assert world.timestamp == expected

    def test_advance_negative_raises(self) -> None:
        world = WorldState()
        with pytest.raises(ValueError, match="negative"):
            world.advance_time(-5)

    def test_advance_zero_is_noop(self) -> None:
        world = WorldState()
        before = world.timestamp
        world.advance_time(0)
        assert world.timestamp == before


class TestWorldStateAuditLog:
    """Test audit logging."""

    def test_audit_log_starts_empty(self) -> None:
        world = WorldState()
        assert len(world.audit_log) == 0

    def test_record_audit_appends(self) -> None:
        world = WorldState()
        entry = world.record_audit("get_patient", {"patient_id": "PAT-001"}, "ok")
        assert len(world.audit_log) == 1
        assert world.audit_log[0] is entry

    def test_audit_entry_is_frozen(self) -> None:
        world = WorldState()
        entry = world.record_audit("test_tool", {}, "ok")
        with pytest.raises(AttributeError):
            entry.tool_name = "modified"  # type: ignore[misc]

    def test_audit_entry_has_correct_fields(self) -> None:
        world = WorldState()
        entry = world.record_audit("order_lab", {"test": "CBC"}, "ordered")
        assert entry.tool_name == "order_lab"
        assert entry.params == {"test": "CBC"}
        assert entry.result_summary == "ordered"
        assert isinstance(entry.timestamp, datetime)

    def test_multiple_audit_entries(self) -> None:
        world = WorldState()
        world.record_audit("tool_a", {}, "ok")
        world.record_audit("tool_b", {}, "ok")
        world.record_audit("tool_c", {}, "ok")
        assert len(world.audit_log) == 3
        names = [e.tool_name for e in world.audit_log]
        assert names == ["tool_a", "tool_b", "tool_c"]
