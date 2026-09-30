"""Project authored laboratory fields without inferring clinical measurements.

Raw per-entry source trees remain available alongside the typed projection.
Panels are not flattened, prose is not parsed, and unknown times stay unknown.
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from healthcraft.entities.encounters import LabResult
from healthcraft.tasks.source_values import require_finite_source
from healthcraft.temporal import resolve_source_time


def _scalar_value(value: Any) -> str | int | float | None:
    if value is None or type(value) in (str, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    return None


def _reference(record: dict[str, Any]) -> str | None:
    """Accept only one explicit reference or aliases with exactly equal text."""
    values = [record[key] for key in ("reference", "reference_range") if key in record]
    if not values or any(type(value) is not str for value in values):
        return None
    return values[0] if all(value == values[0] for value in values) else None


def project_labs(labs_data: Any, source_path: str) -> tuple[LabResult, ...]:
    """Preserve each lab entry at an RFC6901 path, without a fallback timestamp.

    Only explicit scalar ``value``, ``unit``, reference aliases and strict
    boolean ``abnormal`` fields are projected from structured entries. Arbitrary
    panel keys and unsupported field types remain in detached ``source_data``.
    Numeric prose, assay thresholds and pending/collection status are not
    interpreted. Source validity beyond this projection is a loader concern.
    """
    if not isinstance(source_path, str) or not source_path.startswith("/"):
        raise ValueError("lab source_path must be an absolute JSON pointer")
    if labs_data is None:
        return ()
    if not isinstance(labs_data, dict) or any(not isinstance(key, str) for key in labs_data):
        raise ValueError("lab data must be a mapping with string keys or null")

    require_finite_source(labs_data)
    results = []
    for name, source in labs_data.items():
        record = source if isinstance(source, dict) else {}
        timestamp, timing_status, time_keys = resolve_source_time(
            record, keys=("time", "timestamp", "time_of_result")
        )
        value = record.get("value") if isinstance(source, dict) else source
        escaped_name = name.replace("~", "~0").replace("/", "~1")
        results.append(
            LabResult(
                test_name=name.replace("_", " ").title(),
                value=_scalar_value(value),
                unit=record["unit"] if type(record.get("unit")) is str else None,
                reference_range=_reference(record),
                timestamp=timestamp,
                abnormal=record["abnormal"] if type(record.get("abnormal")) is bool else None,
                source_path=f"{source_path}/{escaped_name}",
                source_data=deepcopy(source),
                timing_status=timing_status,
                source_time_keys=time_keys,
            )
        )
    return tuple(results)
