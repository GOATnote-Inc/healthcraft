"""Resolve authored instants without filling missing dates, zones, or precision."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from typing import Any, Mapping

_RFC3339 = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-5][0-9]:[0-5][0-9]"
    r"(?:\.([0-9]+))?(?:[Zz]|[+-][0-9]{2}:[0-5][0-9])"
)


def instant_key(value: Any) -> tuple[datetime, str]:
    """UTC whole seconds and exact decimal fraction; require an explicit zone."""
    fraction = None
    if isinstance(value, str):
        match = _RFC3339.fullmatch(value)
        if match is None:
            raise ValueError("Expected RFC3339 date-time with an explicit timezone")
        fraction = (match.group(1) or "").rstrip("0")
        if match.group(1) is not None:
            value = value[: match.start(1) - 1] + value[match.end(1) :]
        if value.endswith(("Z", "z")):
            value = value[:-1] + "+00:00"
        value = datetime.fromisoformat(re.sub(r"\.[0-9]+", "", value))
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("Expected a timezone-aware timestamp")
    value = value.astimezone(timezone.utc)
    if fraction is None:
        fraction = f"{value.microsecond:06d}".rstrip("0")
    return value.replace(microsecond=0), fraction


def _time_status(value: Any) -> str:
    if value is None:
        return "missing"
    try:
        instant_key(value)
        return "explicit"
    except (ValueError, OverflowError):
        pass
    if isinstance(value, datetime):
        return "naive" if value.utcoffset() is None else "invalid"
    if isinstance(value, date):
        return "date_only"
    if not isinstance(value, str):
        return "invalid"
    if re.fullmatch(r"[0-9]{4}(?:-[0-9]{2}(?:-[0-9]{2})?)?", value):
        try:
            date.fromisoformat(
                value + ("-01-01" if len(value) == 4 else "-01" if len(value) == 7 else "")
            )
            return "date_only"
        except ValueError:
            return "invalid"
    if re.fullmatch(
        r"[0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]+)?)?(?:[+-][0-9]{2}:[0-9]{2})?", value
    ):
        try:
            time.fromisoformat(re.sub(r"\.[0-9]+", "", value))
            return "time_only"
        except ValueError:
            return "invalid"
    if re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:60(?:\.[0-9]+)?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})",
        value,
    ):
        try:
            instant_key(value.replace(":60", ":59", 1))
            return "unsupported"
        except (ValueError, OverflowError):
            return "invalid"
    if re.match(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt ]", value):
        try:
            parsed = datetime.fromisoformat(re.sub(r"\.[0-9]+", "", value))
            return "naive" if parsed.utcoffset() is None else "invalid"
        except ValueError:
            return "invalid"
    return "unresolved"


def resolve_source_time(
    record: Mapping[str, Any], keys: tuple[str, ...] = ("time", "timestamp", "time_of_result")
) -> tuple[datetime | str | None, str, tuple[str, ...]]:
    """Preserve an unambiguous authored instant, otherwise expose uncertainty.

    Distinct roles such as issued/updated_at are deliberately not aliases.
    Raw values must remain in the caller's source record even when unresolved.
    """
    present = tuple(key for key in keys if key in record)
    if not present:
        return None, "missing", ()
    values = [record[key] for key in present]
    statuses = [_time_status(value) for value in values]
    if all(status == "explicit" for status in statuses):
        if all(instant_key(value) == instant_key(values[0]) for value in values[1:]):
            return values[0], "explicit", present
    elif all(status == statuses[0] for status in statuses) and all(
        type(value) is type(values[0]) and value == values[0] for value in values[1:]
    ):
        return None, statuses[0], present
    return None, "conflicting", present
