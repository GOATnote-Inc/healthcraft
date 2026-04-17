"""World state management for the HEALTHCRAFT simulation."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from healthcraft.entities.base import EntityType
from healthcraft.world.physiology import VitalsSnapshot, VitalsTrajectory, interpolate
from healthcraft.world.reassessment import check_reassessment_triggers


@dataclass(frozen=True)
class AuditEntry:
    """Immutable record of a tool invocation against world state.

    The original 4 fields (tool_name, timestamp, params, result_summary)
    are the V8 contract. The additional fields are Phase 4 additive
    extensions -- they default to V8-compatible values so existing code
    and V8 audit log JSON both parse correctly.
    """

    tool_name: str
    timestamp: datetime
    params: dict[str, Any]
    result_summary: str
    # Phase 4 additive fields (all default to V8-compatible values)
    idempotency_key: str = ""
    attempt_number: int = 1
    error_code: str = ""
    deduplicated: bool = False


class WorldState:
    """Holds all 14 entity collections and the simulation clock.

    Entity collections are dicts keyed by entity ID. The world state also
    maintains an append-only audit log of all tool calls.

    When ``dynamic_state_enabled=True``, physiology overlays produce
    time-varying vitals via ``get_current_vitals()``. When ``False``
    (default), all behavior is identical to V8.
    """

    def __init__(
        self,
        start_time: datetime | None = None,
        *,
        dynamic_state_enabled: bool = False,
    ) -> None:
        self._start_time = start_time or datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        self._current_time = self._start_time
        self._entities: dict[str, dict[str, Any]] = {
            entity_type.value: {} for entity_type in EntityType
        }
        self._audit_log: list[AuditEntry] = []

        # Phase 3: dynamic state overlay (default off = V8 behavior)
        self._dynamic_state_enabled = dynamic_state_enabled
        self._physiology: dict[str, VitalsTrajectory] = {}
        self._last_vitals: dict[str, VitalsSnapshot] = {}

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
        snap._dynamic_state_enabled = self._dynamic_state_enabled
        snap._physiology = dict(self._physiology)  # VitalsTrajectory is frozen
        snap._last_vitals = dict(self._last_vitals)  # VitalsSnapshot is frozen
        return snap

    # --- Clock ---

    @property
    def timestamp(self) -> datetime:
        """Current simulation time."""
        return self._current_time

    def advance_time(self, minutes: int) -> list[Any]:
        """Advance the simulation clock by the given number of minutes.

        When ``dynamic_state_enabled=True``, also interpolates vitals for
        all attached physiology overlays and emits ``_reassessment_prompt``
        audit entries for any threshold crossings. When ``False`` (default),
        behavior is identical to V8: only the clock advances.

        Args:
            minutes: Non-negative number of minutes to advance.

        Returns:
            List of reassessment triggers (empty if dynamic state is off).

        Raises:
            ValueError: If minutes is negative.
        """
        if minutes < 0:
            raise ValueError(f"Cannot advance time by negative minutes: {minutes}")

        self._current_time = self._current_time + timedelta(minutes=minutes)

        # Short-circuit: V8 behavior when dynamic state is off
        if not self._dynamic_state_enabled or not self._physiology:
            return []

        # Interpolate vitals and check reassessment triggers
        all_triggers: list[Any] = []
        elapsed = (self._current_time - self._start_time).total_seconds() / 60.0

        for patient_id, trajectory in self._physiology.items():
            current = interpolate(trajectory, elapsed)
            previous = self._last_vitals.get(patient_id)
            triggers = check_reassessment_triggers(patient_id, previous, current)
            self._last_vitals[patient_id] = current

            for trigger in triggers:
                self.record_audit(
                    tool_name="_reassessment_prompt",
                    params={
                        "patient_id": patient_id,
                        "parameter": trigger.parameter,
                        "value": trigger.value,
                        "threshold": trigger.threshold,
                    },
                    result_summary=trigger.message,
                )
                all_triggers.append(trigger)

        return all_triggers

    # --- Physiology overlay ---

    def attach_physiology(
        self,
        patient_id: str,
        trajectory: VitalsTrajectory,
    ) -> None:
        """Attach a physiology trajectory to a patient.

        Only effective when ``dynamic_state_enabled=True``. When attached,
        ``get_current_vitals()`` returns interpolated vitals based on
        simulation time, and ``advance_time()`` checks for reassessment
        triggers.

        Args:
            patient_id: Patient ID to attach the trajectory to.
            trajectory: The vitals trajectory.
        """
        self._physiology[patient_id] = trajectory

    def get_current_vitals(self, patient_id: str) -> VitalsSnapshot | None:
        """Get interpolated vitals for a patient at the current simulation time.

        When dynamic state is enabled and a physiology trajectory is attached,
        returns interpolated vitals. Otherwise returns None (callers should
        fall back to static encounter vitals -- V8 behavior).

        Args:
            patient_id: Patient ID.

        Returns:
            Interpolated VitalsSnapshot, or None if no trajectory attached
            or dynamic state is off.
        """
        if not self._dynamic_state_enabled:
            return None
        trajectory = self._physiology.get(patient_id)
        if trajectory is None:
            return None
        elapsed = (self._current_time - self._start_time).total_seconds() / 60.0
        return interpolate(trajectory, elapsed)

    @property
    def dynamic_state_enabled(self) -> bool:
        """Whether dynamic patient state is active."""
        return self._dynamic_state_enabled

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
        *,
        error_code: str = "",
    ) -> AuditEntry:
        """Append an audit entry for a tool call.

        Args:
            tool_name: Name of the tool invoked.
            params: Parameters passed to the tool.
            result_summary: Brief summary of the result.
            error_code: When ``result_summary == "error"``, the error code
                from the tool response (e.g. ``"missing_param"``,
                ``"unknown_task_type"``). Defaults to empty for backward
                compatibility with V8 audit logs that didn't capture it.

        Returns:
            The created AuditEntry.
        """
        entry = AuditEntry(
            tool_name=tool_name,
            timestamp=self._current_time,
            params=dict(params),
            result_summary=result_summary,
            error_code=error_code,
        )
        self._audit_log.append(entry)
        return entry

    # --- Repr ---

    def __repr__(self) -> str:
        counts = {k: len(v) for k, v in self._entities.items() if v}
        return f"WorldState(time={self._current_time.isoformat()}, entities={counts})"
