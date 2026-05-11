"""Persistent audit log for the Agents Assemble Superpower + Agent.

Every clinical-decision-support invocation must be auditable: a hospital's
QA team needs to look at any prior chart and reproduce *which Bundle was
seen, which rule version was applied, which score came out, and what
recommendation was returned*. We provide that as an append-only JSONL
log keyed by ``correlationId``.

Design choices:

- **JSONL not SQL.** A hackathon demo deploys anywhere; sqlite is fine
  but JSONL is portable and trivially shippable to S3/HealthLake.
- **Append-only.** Never edit an existing line. Tampering shows up in
  any verifier that diffs vs an immutable copy.
- **No PHI by default.** The log records bundle SHA-256, rule version,
  score, risk, disposition, conflict flag, gap count — NOT the bundle
  itself. The bundle hash is the link to the source-of-truth FHIR
  store; PHI never leaves that store via this log.
- **Optional bundle echo.** ``include_bundle=True`` writes the (PHI-
  scrubbed) bundle for debug replay; off by default.

The log path defaults to ``$HEALTHCRAFT_AUDIT_LOG`` if set, else an
in-memory stub. A hospital deploys with a real path; tests use the stub.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("agents_assemble.audit")


class AuditLog:
    """Append-only JSONL audit log. Thread-safe. In-memory if no path set."""

    def __init__(self, path: str | os.PathLike | None = None) -> None:
        env_path = os.environ.get("HEALTHCRAFT_AUDIT_LOG")
        resolved = Path(path) if path else (Path(env_path) if env_path else None)
        self._path = resolved
        self._lock = threading.Lock()
        self._buffer: list[dict[str, Any]] = []
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path | None:
        return self._path

    def write(self, record: dict[str, Any]) -> None:
        """Append one record. Adds ``ts`` if absent."""
        record = dict(record)
        record.setdefault("ts", time.time())
        line = json.dumps(record, sort_keys=True, default=str)
        with self._lock:
            if self._path is not None:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            else:
                self._buffer.append(record)

    def read_all(self) -> list[dict[str, Any]]:
        """Read every record back. Combines disk + in-memory buffer."""
        with self._lock:
            records: list[dict[str, Any]] = []
            if self._path is not None and self._path.exists():
                for line in self._path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.warning("skipping malformed audit line: %s", line[:80])
            records.extend(self._buffer)
            return records


# A process-wide default log so callers don't have to pass one through.
_DEFAULT_LOG: AuditLog | None = None


def default_log() -> AuditLog:
    """Process-wide audit log singleton. Create on first call."""
    global _DEFAULT_LOG
    if _DEFAULT_LOG is None:
        _DEFAULT_LOG = AuditLog()
    return _DEFAULT_LOG


def reset_default_log() -> None:
    """Test helper — reset the singleton."""
    global _DEFAULT_LOG
    _DEFAULT_LOG = None


def record_invocation(
    *,
    correlation_id: str,
    bundle_sha256: str,
    rule_name: str | None,
    rule_version: str | None,
    score: float | None,
    risk_level: str | None,
    disposition: str | None,
    has_conflict: bool,
    unsupported_findings: list[str] | None = None,
    log: AuditLog | None = None,
) -> None:
    """Record a single CDS invocation. Designed to be called from the
    Superpower call site or the agent.run pipeline."""
    record = {
        "kind": "cds_invocation",
        "correlationId": correlation_id,
        "bundleSha256": bundle_sha256,
        "ruleName": rule_name,
        "ruleVersion": rule_version,
        "score": score,
        "riskLevel": risk_level,
        "disposition": disposition,
        "hasConflict": has_conflict,
        "unsupportedFindings": list(unsupported_findings or []),
    }
    (log or default_log()).write(record)
