"""Validator API: pure-function invariant checks against WorldState.

A validator is a deterministic function ``WorldState -> ValidationResult``.
It reads ``world_state.audit_log`` and entity collections to decide whether
a criterion's formal invariant holds. No LLM calls, no network I/O.

Verdicts:
    VERIFIED               invariant holds
    CONTRADICTED           invariant is violated by evidence in the log
    INSUFFICIENT_EVIDENCE  the log lacks the data to decide either way

The shadow-mode contract: validators run alongside the LLM judge. Both
produce verdicts; neither overrides the other at Phase 0. Agreement is
measured for prompt-quality feedback. Enforce-mode (override judge on
safety-critical) is gated on >=95% judge-validator agreement per criterion.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from healthcraft.world.state import WorldState


class Verdict(Enum):
    VERIFIED = "verified"
    CONTRADICTED = "contradicted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class ValidationResult:
    criterion_id: str
    verdict: Verdict
    evidence: str = ""


ValidatorFn = Callable[[WorldState], ValidationResult]


_REGISTRY: dict[str, ValidatorFn] = {}


def register(criterion_id: str) -> Callable[[ValidatorFn], ValidatorFn]:
    """Decorator that registers a validator under a criterion id.

    Raises ValueError if the criterion already has a registered validator.
    This fails loud to prevent silent override when two modules claim the
    same criterion.
    """

    def _inner(fn: ValidatorFn) -> ValidatorFn:
        if criterion_id in _REGISTRY:
            raise ValueError(f"duplicate validator registration for {criterion_id}")
        _REGISTRY[criterion_id] = fn
        return fn

    return _inner


def get_validator(criterion_id: str) -> ValidatorFn | None:
    return _REGISTRY.get(criterion_id)


def registered_criteria() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY.keys()))


def validate(criterion_id: str, world_state: WorldState) -> ValidationResult:
    """Run the registered validator, or return INSUFFICIENT_EVIDENCE.

    The fallback is deliberate: a criterion without a registered validator
    is not failed -- it is simply outside the PoC-validator's scope.
    """
    fn = get_validator(criterion_id)
    if fn is None:
        return ValidationResult(
            criterion_id=criterion_id,
            verdict=Verdict.INSUFFICIENT_EVIDENCE,
            evidence="no_validator_registered",
        )
    return fn(world_state)
