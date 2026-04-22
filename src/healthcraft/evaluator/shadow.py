"""Shadow-mode hook for the PoC-validator.

Phase 1 per docs/POC_VALIDATOR_EXTENSION.md: the validator runs alongside
the judge; neither overrides. (judge, validator) verdict pairs are written
to an append-only JSONL sink for agreement analysis.

Defaults are off-by-default so existing behavior (V8 replay, all pilots)
is byte-identical when the env var is not set. The cheapest possible
gate is an env var so we don't need to plumb a new config through
evaluator call sites.

Enable via env:
    HEALTHCRAFT_POC_VALIDATOR_SHADOW=1

Custom log path (optional):
    HEALTHCRAFT_POC_VALIDATOR_LOG=results/poc_validator_log.jsonl

The caller is responsible for cleaning / rotating the log. The only
invariant this module enforces is "we only ever append."
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from healthcraft.evaluator.validator import get_validator, validate
from healthcraft.tasks.rubrics import Criterion, CriterionResult, VerificationMethod
from healthcraft.world.state import WorldState

_ENV_ENABLED = "HEALTHCRAFT_POC_VALIDATOR_SHADOW"
_ENV_LOG_PATH = "HEALTHCRAFT_POC_VALIDATOR_LOG"
_DEFAULT_LOG_PATH = "results/poc_validator_log.jsonl"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def is_shadow_enabled() -> bool:
    return os.environ.get(_ENV_ENABLED, "").strip().lower() in _TRUTHY


def shadow_log_path() -> Path:
    return Path(os.environ.get(_ENV_LOG_PATH, _DEFAULT_LOG_PATH))


@dataclass(frozen=True)
class ShadowEntry:
    """One (criterion, judge_verdict, validator_verdict) pair."""

    task_id: str
    criterion_id: str
    safety_critical: bool
    judge_satisfied: bool
    judge_evidence: str
    validator_verdict: str
    validator_evidence: str
    timestamp: str

    def to_json_line(self) -> str:
        return json.dumps(
            {
                "task_id": self.task_id,
                "criterion_id": self.criterion_id,
                "safety_critical": self.safety_critical,
                "judge_satisfied": self.judge_satisfied,
                "judge_evidence": self.judge_evidence,
                "validator_verdict": self.validator_verdict,
                "validator_evidence": self.validator_evidence,
                "timestamp": self.timestamp,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


def run_shadow_pass(
    task_id: str,
    criteria: Iterable[Criterion],
    results: Iterable[CriterionResult],
    world_state: WorldState,
) -> list[ShadowEntry]:
    """Run the validator for every safety_critical + llm_judge criterion
    that has a registered invariant.

    Returns a list of ShadowEntry. Does NOT modify the inputs. Writes
    nothing to disk. Callers who want persistence hand the result to
    ``append_shadow_log``.

    If shadow mode is disabled via env, returns [] without running any
    validators. This keeps the V8 replay path cheap when shadow is off.
    """
    if not is_shadow_enabled():
        return []

    results_by_id = {r.criterion_id: r for r in results}
    entries: list[ShadowEntry] = []
    ts = datetime.now(timezone.utc).isoformat()

    for c in criteria:
        if not c.safety_critical:
            continue
        if c.verification is not VerificationMethod.LLM_JUDGE:
            continue
        if get_validator(c.id) is None:
            continue  # no pilot invariant for this criterion

        jr = results_by_id.get(c.id)
        if jr is None:
            continue

        vr = validate(c.id, world_state)
        entries.append(
            ShadowEntry(
                task_id=task_id,
                criterion_id=c.id,
                safety_critical=True,
                judge_satisfied=bool(jr.satisfied),
                judge_evidence=str(jr.evidence)[:500],
                validator_verdict=vr.verdict.value,
                validator_evidence=str(vr.evidence)[:500],
                timestamp=ts,
            )
        )

    return entries


def append_shadow_log(entries: Iterable[ShadowEntry]) -> None:
    """Append entries to the shadow log file. Creates parent dir if needed."""
    entries = list(entries)
    if not entries:
        return
    path = shadow_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for e in entries:
            f.write(e.to_json_line() + "\n")
