"""Preserve authored imaging context without inventing completed studies.

Only six reviewed direct patient fields are projected. Conditional answer
guidance is excluded by exact task/path review; unfamiliar conditional keys
fail closed. This projection is not a clinical interpretation of source text.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from healthcraft.entities.encounters import ImagingStudy
from healthcraft.tasks.source_values import require_finite_source
from healthcraft.temporal import resolve_source_time

_COLLECTIONS = ("imaging", "imaging_results", "imaging_pending", "imaging_available")
_STANDALONES = ("bedside_echo", "fast_exam")

# Private visibility review, not observation metadata. Whole conditional entries
# are omitted; nested expected fields leave the other authored context intact.
_WITHHELD_PATHS = {
    "MW-006": frozenset(
        {
            "/patient/imaging/ct_head_noncontrast/expected_finding",
            "/patient/imaging/ct_angiogram/expected_finding",
        }
    ),
    "MW-009": frozenset(
        {
            "/patient/imaging/ct_results/expected_head",
            "/patient/imaging/ct_results/expected_cspine",
            "/patient/imaging/ct_results/expected_chest",
            "/patient/imaging/ct_results/expected_abdomen",
        }
    ),
    "SCJ-017": frozenset(
        {
            "/patient/imaging/skeletal_survey_if_ordered",
            "/patient/imaging/ct_head_if_ordered",
        }
    ),
}


@dataclass(frozen=True)
class ImagingProjection:
    """Observation-only source records and collection-level omission notices."""

    records: tuple[ImagingStudy, ...]
    notices: tuple[dict[str, Any], ...]


def _pointer_part(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def _observation_view(source: Any, path: str, reviewed: frozenset[str]) -> tuple[Any, int]:
    """Copy a selected tree, rejecting unreviewed conditional guidance keys."""
    omitted = 0
    if isinstance(source, dict):
        result = {}
        for key, value in source.items():
            if not isinstance(key, str):
                raise ValueError("imaging source must be a mapping with string keys")
            child_path = f"{path}/{_pointer_part(key)}"
            normalized = key.lower()
            conditional = (
                normalized == "expected"
                or normalized.startswith("expected_")
                or normalized.endswith("_if_ordered")
            )
            if conditional:
                if child_path not in reviewed:
                    raise ValueError(f"Unreviewed conditional imaging source at {child_path}")
                omitted += 1
                continue
            child, child_omitted = _observation_view(value, child_path, reviewed)
            result[key] = child
            omitted += child_omitted
        return result, omitted
    if isinstance(source, (list, tuple)):
        items = []
        for index, value in enumerate(source):
            child, child_omitted = _observation_view(value, f"{path}/{index}", reviewed)
            items.append(child)
            omitted += child_omitted
        return tuple(items) if isinstance(source, tuple) else items, omitted
    return deepcopy(source), 0


def _record(source: Any, collection: str, label: str, path: str) -> ImagingStudy:
    fields = source if isinstance(source, dict) else {}
    timestamp, timing_status, time_keys = resolve_source_time(
        fields, keys=("time", "timestamp", "time_of_study")
    )
    role = "authored_context"
    if collection in _COLLECTIONS and label == "read_by":
        role = "collection_metadata"
    elif type(source) is bool or label.endswith("_recommended"):
        role = "source_assertion"

    def text(key: str) -> str | None:
        return fields[key] if type(fields.get(key)) is str else None

    return ImagingStudy(
        modality=text("modality"),
        body_part=text("body_part"),
        findings=text("findings"),
        impression=text("impression"),
        timestamp=timestamp,
        result=text("result"),
        report_text=source if type(source) is str else None,
        status=text("status"),
        source_path=path,
        source_collection=collection,
        source_label=label,
        source_role=role,
        source_data=source,
        timing_status=timing_status,
        source_time_keys=time_keys,
    )


def project_imaging(patient_data: dict[str, Any], *, task_id: str) -> ImagingProjection:
    """Project direct imaging context with explicit unknowns and source roles.

    Named collections must be mappings or null. Each remaining child is one
    source record; standalone fields retain even an explicitly supplied null.
    Strings are report text only. Typed fields require exact authored strings,
    while arbitrary nested observations remain in detached ``source_data``.

    Generic time aliases are preserved only as explicit aware instants; they
    do not establish acquisition time. Other event timestamps remain raw.
    Notices identify only a collection and omitted count, never target names
    or values. No source outside the six explicit fields is inspected.
    """
    if not isinstance(patient_data, dict):
        raise ValueError("imaging patient_data must be a mapping")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("imaging task_id must be a nonempty string")

    records = []
    notices = []
    reviewed = _WITHHELD_PATHS.get(task_id, frozenset())
    for collection in (*_COLLECTIONS, *_STANDALONES):
        if collection not in patient_data:
            continue
        source = patient_data[collection]
        is_collection = collection in _COLLECTIONS
        if is_collection and source is None:
            continue
        if is_collection and not isinstance(source, dict):
            raise ValueError(f"{collection} must be a mapping with string keys or null")
        require_finite_source(source)
        path = f"/patient/{collection}"
        observed, omitted = _observation_view(source, path, reviewed)
        if omitted:
            notices.append(
                {
                    "source_collection": collection,
                    "source_path": path,
                    "omitted_field_count": omitted,
                    "notice": "Authored conditional guidance withheld from observations",
                }
            )
        if is_collection:
            records.extend(
                _record(value, collection, label, f"{path}/{_pointer_part(label)}")
                for label, value in observed.items()
            )
        else:
            records.append(_record(observed, collection, collection, path))

    return ImagingProjection(records=tuple(records), notices=tuple(notices))
