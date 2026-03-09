"""World state management for the HEALTHCRAFT simulation."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from healthcraft.entities.base import EntityType


@dataclass(frozen=True)
class AuditEntry:
    """Immutable record of a tool invocation against world state."""

    tool_name: str
    timestamp: datetime
    params: dict[str, Any]
    result_summary: str


class WorldState:
    """Holds all 14 entity collections and the simulation clock.

    Entity collections are dicts keyed by entity ID. The world state also
    maintains an append-only audit log of all tool calls.
    """

    def __init__(self, start_time: datetime | None = None) -> None:
        self._start_time = start_time or datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        self._current_time = self._start_time
        self._entities: dict[str, dict[str, Any]] = {
            entity_type.value: {} for entity_type in EntityType
        }
        self._audit_log: list[AuditEntry] = []

    # --- Entity access ---

    def get_entity(self, entity_type: str, entity_id: str) -> Any | None:
        """Retrieve an entity by type and ID.

        Args:
            entity_type: One of the EntityType values (e.g. "patient").
            entity_id: The unique entity identifier.

        Returns:
            The entity if found, else None.
        """
        collection = self._entities.get(entity_type)
        if collection is None:
            raise KeyError(f"Unknown entity type: {entity_type}")
        return collection.get(entity_id)

    def put_entity(self, entity_type: str, entity_id: str, entity: Any) -> None:
        """Store or update an entity.

        Args:
            entity_type: One of the EntityType values.
            entity_id: The unique entity identifier.
            entity: The entity object to store.
        """
        collection = self._entities.get(entity_type)
        if collection is None:
            raise KeyError(f"Unknown entity type: {entity_type}")
        collection[entity_id] = entity

    def list_entities(self, entity_type: str) -> dict[str, Any]:
        """Return all entities of a given type.

        Args:
            entity_type: One of the EntityType values.

        Returns:
            Dict of entity_id -> entity.
        """
        collection = self._entities.get(entity_type)
        if collection is None:
            raise KeyError(f"Unknown entity type: {entity_type}")
        return dict(collection)

    # --- Snapshot ---

    def snapshot(self) -> WorldState:
        """Return a deep-copy snapshot of the current world state.

        The snapshot is independent -- mutations to the original do not
        affect the snapshot and vice versa.
        """
        snap = WorldState.__new__(WorldState)
        snap._start_time = self._start_time
        snap._current_time = self._current_time
        snap._entities = copy.deepcopy(self._entities)
        snap._audit_log = list(self._audit_log)  # AuditEntry is frozen, shallow copy OK
        return snap

    # --- Clock ---

    @property
    def timestamp(self) -> datetime:
        """Current simulation time."""
        return self._current_time

    def advance_time(self, minutes: int) -> None:
        """Advance the simulation clock by the given number of minutes.

        Args:
            minutes: Non-negative number of minutes to advance.

        Raises:
            ValueError: If minutes is negative.
        """
        if minutes < 0:
            raise ValueError(f"Cannot advance time by negative minutes: {minutes}")
        from datetime import timedelta

        self._current_time = self._current_time + timedelta(minutes=minutes)

    # --- Audit log ---

    @property
    def audit_log(self) -> list[AuditEntry]:
        """The append-only audit log of tool invocations."""
        return self._audit_log

    def record_audit(
        self,
        tool_name: str,
        params: dict[str, Any],
        result_summary: str,
    ) -> AuditEntry:
        """Append an audit entry for a tool call.

        Args:
            tool_name: Name of the tool invoked.
            params: Parameters passed to the tool.
            result_summary: Brief summary of the result.

        Returns:
            The created AuditEntry.
        """
        entry = AuditEntry(
            tool_name=tool_name,
            timestamp=self._current_time,
            params=dict(params),
            result_summary=result_summary,
        )
        self._audit_log.append(entry)
        return entry

    # --- Repr ---

    def __repr__(self) -> str:
        counts = {k: len(v) for k, v in self._entities.items() if v}
        return f"WorldState(time={self._current_time.isoformat()}, entities={counts})"
