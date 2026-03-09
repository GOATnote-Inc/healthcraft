"""Audit logging for HEALTHCRAFT MCP tool calls.

All tool invocations are logged with timestamps, parameters, and results
to provide a complete audit trail for evaluation and safety review.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class AuditEntry:
    """Immutable record of a single tool invocation.

    Designed to be JSON-serializable for export and analysis.
    """

    tool_name: str
    timestamp: str  # ISO 8601 string for JSON serialization
    params: dict[str, Any]
    result_summary: str
    session_id: str = ""


class AuditLogger:
    """Collects and manages audit entries for MCP tool calls.

    Entries are stored in memory and can be exported as JSON.
    """

    def __init__(self, session_id: str = "") -> None:
        self._session_id = session_id or "default"
        self._entries: list[AuditEntry] = []

    @property
    def session_id(self) -> str:
        """The current session identifier."""
        return self._session_id

    def log_tool_call(
        self,
        tool_name: str,
        params: dict[str, Any],
        result: Any,
        timestamp: datetime | None = None,
    ) -> AuditEntry:
        """Log a tool invocation.

        Args:
            tool_name: Name of the tool invoked.
            params: Parameters passed to the tool.
            result: The tool's return value.
            timestamp: When the call occurred. Defaults to now (UTC).

        Returns:
            The created AuditEntry.
        """
        ts = timestamp or datetime.now(timezone.utc)
        ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)

        # Summarize result
        if isinstance(result, dict):
            result_summary = result.get("status", str(result)[:200])
        else:
            result_summary = str(result)[:200]

        entry = AuditEntry(
            tool_name=tool_name,
            timestamp=ts_str,
            params=_sanitize_params(params),
            result_summary=result_summary,
            session_id=self._session_id,
        )
        self._entries.append(entry)
        return entry

    def get_audit_trail(self, session_id: str | None = None) -> list[AuditEntry]:
        """Retrieve audit entries, optionally filtered by session.

        Args:
            session_id: If provided, filter to this session only.

        Returns:
            List of matching AuditEntry instances.
        """
        if session_id is None:
            return list(self._entries)
        return [e for e in self._entries if e.session_id == session_id]

    def to_json(self, session_id: str | None = None) -> str:
        """Export audit trail as a JSON string.

        Args:
            session_id: If provided, filter to this session only.

        Returns:
            JSON string of the audit entries.
        """
        entries = self.get_audit_trail(session_id)
        return json.dumps([asdict(e) for e in entries], indent=2, default=str)

    @property
    def entry_count(self) -> int:
        """Total number of logged entries."""
        return len(self._entries)

    def clear(self) -> None:
        """Clear all audit entries. Use with caution."""
        self._entries.clear()


def _sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Sanitize parameters for safe logging.

    Truncates long string values and removes any potentially sensitive
    fields.

    Args:
        params: Raw parameter dict.

    Returns:
        Sanitized copy of the params.
    """
    sanitized: dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, str) and len(value) > 500:
            sanitized[key] = value[:500] + "...[truncated]"
        else:
            sanitized[key] = value
    return sanitized
