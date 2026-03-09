"""Temporal spine for the HEALTHCRAFT simulation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


class SimulationClock:
    """Manages the simulation's current time.

    All time operations go through this clock to ensure consistency.
    """

    def __init__(self, start_time: datetime | None = None) -> None:
        self._start_time = start_time or datetime(2026, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        self._current_time = self._start_time

    def now(self) -> datetime:
        """Return the current simulation time."""
        return self._current_time

    def advance(self, minutes: int) -> datetime:
        """Advance the clock by the given minutes and return the new time.

        Args:
            minutes: Non-negative number of minutes to advance.

        Returns:
            The new current time after advancement.

        Raises:
            ValueError: If minutes is negative.
        """
        if minutes < 0:
            raise ValueError(f"Cannot advance by negative minutes: {minutes}")
        self._current_time = self._current_time + timedelta(minutes=minutes)
        return self._current_time

    def elapsed_since(self, event_time: datetime) -> timedelta:
        """Return the time elapsed between an event and the current clock time.

        Args:
            event_time: The timestamp of the event.

        Returns:
            A timedelta representing elapsed time (may be negative if event is in the future).
        """
        return self._current_time - event_time

    @property
    def start_time(self) -> datetime:
        """The initial simulation start time."""
        return self._start_time

    def __repr__(self) -> str:
        elapsed = self._current_time - self._start_time
        return f"SimulationClock(now={self._current_time.isoformat()}, elapsed={elapsed})"


@dataclass(frozen=True)
class TimeConstraint:
    """A named temporal constraint on an entity.

    Used to track deadlines such as 'door-to-needle time' or
    'triage completion within 10 minutes of arrival'.
    """

    name: str
    target_minutes: int
    start_time: datetime
    entity_ref: str  # entity_type:entity_id


@dataclass(frozen=True)
class ConstraintViolation:
    """Records a violated time constraint."""

    constraint: TimeConstraint
    elapsed_minutes: float
    overage_minutes: float


class Timeline:
    """Manages active time constraints and checks for violations."""

    def __init__(self, clock: SimulationClock) -> None:
        self._clock = clock
        self._constraints: list[TimeConstraint] = []

    @property
    def clock(self) -> SimulationClock:
        """The simulation clock driving this timeline."""
        return self._clock

    def add_constraint(self, constraint: TimeConstraint) -> None:
        """Register a new time constraint.

        Args:
            constraint: The TimeConstraint to track.
        """
        self._constraints.append(constraint)

    def remove_constraint(self, name: str, entity_ref: str) -> bool:
        """Remove a constraint by name and entity ref.

        Args:
            name: Constraint name.
            entity_ref: Entity reference string.

        Returns:
            True if a constraint was removed, False otherwise.
        """
        before = len(self._constraints)
        self._constraints = [
            c for c in self._constraints if not (c.name == name and c.entity_ref == entity_ref)
        ]
        return len(self._constraints) < before

    @property
    def active_constraints(self) -> list[TimeConstraint]:
        """All currently active constraints."""
        return list(self._constraints)

    def check_constraints(self) -> list[ConstraintViolation]:
        """Check all constraints against the current clock time.

        Returns:
            List of ConstraintViolation for any constraint whose target
            has been exceeded.
        """
        violations: list[ConstraintViolation] = []
        now = self._clock.now()
        for constraint in self._constraints:
            elapsed = (now - constraint.start_time).total_seconds() / 60.0
            if elapsed > constraint.target_minutes:
                violations.append(
                    ConstraintViolation(
                        constraint=constraint,
                        elapsed_minutes=elapsed,
                        overage_minutes=elapsed - constraint.target_minutes,
                    )
                )
        return violations

    def __repr__(self) -> str:
        return f"Timeline(constraints={len(self._constraints)}, clock={self._clock})"
