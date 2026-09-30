"""Offline source transport certificate for reviewed care and imaging fields.

Actual injection and MCP retrieval are checked against independent YAML source
selection. This is mechanical development evidence, never clinical grading.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import sys
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import certify_observation_fidelity as observation  # noqa: E402

# Independent selectors transcribed from the frozen direct-source audits, not
# imported from injection/projection modules. The source reviews are not a
# clinical oracle or a preregistered clinical performance protocol.
CARE_FIELDS = (
    "active_orders",
    "current_management",
    "current_treatment",
    "ems_interventions",
    "field_interventions",
    "medication_changes",
    "medication_error_details",
    "medications_from_bottles",
    "pending_order",
    "pending_orders",
    "prescribed_medications",
    "procedures_performed",
    "proposed_treatment",
    "psychiatric_medication_timeline",
    "response_to_initial_treatment",
    "sedation_medications",
    "treatments_given",
    "verbal_order_as_received",
    "original_prescriptions",
    "resuscitation_summary",
    "anesthesia_record",
    "transfusion_details",
)
IMAGING_GROUPS = ("imaging", "imaging_available", "imaging_pending", "imaging_results")
IMAGING_STANDALONES = ("bedside_echo", "fast_exam")
OMITTED_PATHS = {
    "MW-006": (
        "/patient/imaging/ct_head_noncontrast/expected_finding",
        "/patient/imaging/ct_angiogram/expected_finding",
    ),
    "MW-009": (
        "/patient/imaging/ct_results/expected_head",
        "/patient/imaging/ct_results/expected_cspine",
        "/patient/imaging/ct_results/expected_chest",
        "/patient/imaging/ct_results/expected_abdomen",
    ),
    "SCJ-017": (
        "/patient/imaging/skeletal_survey_if_ordered",
        "/patient/imaging/ct_head_if_ordered",
    ),
}
KIND = "authored-care-imaging-source-concordance/v1"
SELECTION_REVIEWS = {
    "care_scope_sha256": "532425410ac7eab4b8e0bbefab3ed5303b0416695ab10a29da31669e5dae7f4e",
    "imaging_inventory_sha256": "738e1590da1ac2cc76908c2c5d0799474590181ccbff2264ce1e9806952d5c6a",
    "source_revision": "aa21717d0fa6454e4e7af51d3f50206ec2c6026b",
}

catalog_paths = observation.catalog_paths
execute_task = observation.execute_task


def source_hashes(paths):
    hashes = observation.source_hashes(paths)
    files = {Path(__file__).resolve(), Path(observation.__file__).resolve()}
    files.update(p for p in (ROOT / "system-prompts").rglob("*") if p.is_file())
    for path in sorted(files):
        hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(sorted(hashes.items()))


def runtime_metadata():
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {name: importlib.metadata.version(name) for name in ("PyYAML", "jsonschema")},
    }


def _time_status(source, timestamp, keys):
    """Independently classify unresolved source syntax; do not infer chronology."""
    if timestamp is not None:
        return "explicit"
    if not keys:
        return "missing"
    values = [source[key] for key in keys]
    if any(type(value) is not type(values[0]) or value != values[0] for value in values[1:]):
        return "conflicting"
    value = values[0]
    if value is None:
        return "missing"
    if isinstance(value, datetime):
        return "naive" if value.utcoffset() is None else "invalid"
    if isinstance(value, date):
        return "date_only"
    if not isinstance(value, str):
        return "invalid"
    if re.fullmatch(r"\d{4}(?:-\d{2}){0,2}", value):
        try:
            date.fromisoformat((value + "-01-01")[:10])
            return "date_only"
        except ValueError:
            return "invalid"
    if re.fullmatch(r"\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:[+-]\d{2}:\d{2})?", value):
        try:
            time.fromisoformat(re.sub(r"\.\d+", "", value))
            return "time_only"
        except ValueError:
            return "invalid"
    if re.fullmatch(
        r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:[0-5]\d:60(?:\.\d+)?(?:[Zz]|[+-]\d{2}:[0-5]\d)",
        value,
    ):
        try:
            observation._instant(value.replace(":60", ":59", 1))
            return "unsupported"
        except (ValueError, OverflowError):
            pass
    if re.match(r"\d{4}-\d{2}-\d{2}[Tt ]", value):
        try:
            parsed = datetime.fromisoformat(re.sub(r"\.\d+", "", value))
            return "naive" if parsed.utcoffset() is None else "invalid"
        except ValueError:
            return "invalid"
    return "unresolved"


def _reject_unreviewed_guidance(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("Imaging source key must be a string")
            lowered = key.lower()
            if (
                lowered == "expected"
                or lowered.startswith("expected_")
                or lowered.endswith("_if_ordered")
            ):
                raise ValueError("Unreviewed conditional imaging source")
            _reject_unreviewed_guidance(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_unreviewed_guidance(child)


def expected_records(raw):
    """Derive expected grouped values directly from authored patient fields."""
    patient = raw["patient"]
    care = {
        f"/patient/{key}": {
            "source_path": f"/patient/{key}",
            "source_collection": key,
            "source_data": deepcopy(patient[key]),
        }
        for key in CARE_FIELDS
        if key in patient
    }
    observed = deepcopy(patient)
    omitted = []
    withheld = []
    for pointer in OMITTED_PATHS.get(raw["id"], ()):
        components = pointer.split("/")[2:]
        parent = observed
        for key in components[:-1]:
            if not isinstance(parent, dict) or key not in parent:
                parent = None
                break
            parent = parent[key]
        if isinstance(parent, dict) and components[-1] in parent:
            withheld.append(parent.pop(components[-1]))
            omitted.append(pointer)
    notices = [
        {
            "source_collection": key,
            "source_path": f"/patient/{key}",
            "omitted_field_count": sum(p.startswith(f"/patient/{key}/") for p in omitted),
            "notice": "Authored conditional guidance withheld from observations",
        }
        for key in (*IMAGING_GROUPS, *IMAGING_STANDALONES)
        if any(p.startswith(f"/patient/{key}/") for p in omitted)
    ]
    images = {}
    for collection in (*IMAGING_GROUPS, *IMAGING_STANDALONES):
        if collection not in observed:
            continue
        source = observed[collection]
        if collection in IMAGING_GROUPS:
            if source is None:
                continue
            if not isinstance(source, dict):
                raise ValueError("Imaging collection must be a mapping or null")
            entries = source.items()
        else:
            entries = [(collection, source)]
        _reject_unreviewed_guidance(source)
        for label, value in entries:
            pointer = f"/patient/{collection}"
            if collection in IMAGING_GROUPS:
                pointer += "/" + observation._pointer(label)
            fields = value if isinstance(value, dict) else {}
            timestamp, keys = observation._expected_time(
                fields, ("time", "timestamp", "time_of_study")
            )
            row = {
                key: fields.get(key) if type(fields.get(key)) is str else None
                for key in ("modality", "body_part", "findings", "impression", "result", "status")
            }
            role = "authored_context"
            if collection in IMAGING_GROUPS and label == "read_by":
                role = "collection_metadata"
            elif type(value) is bool or label.endswith("_recommended"):
                role = "source_assertion"
            row.update(
                source_path=pointer,
                source_collection=collection,
                source_label=label,
                source_data=value,
                source_role=role,
                timestamp=timestamp,
                source_time_keys=keys,
                timing_status=_time_status(fields, timestamp, keys),
                report_text=value if type(value) is str else None,
            )
            images[pointer] = row
    return care, images, notices, omitted, withheld


def _check_rows(kind, expected, returned, errors):
    if not isinstance(returned, list):
        errors.append(f"{kind}: missing or malformed record list")
        return 0
    actual = {}
    for row in returned:
        if not isinstance(row, dict) or not isinstance(row.get("source_path"), str):
            errors.append(f"{kind}: missing or malformed source path")
            continue
        pointer = row["source_path"]
        if pointer in actual:
            errors.append(f"{kind}: duplicate source path {pointer}")
        actual[pointer] = row
    if actual.keys() != expected.keys():
        errors.append(f"{kind}: missing or unexpected source paths")
    for pointer in expected.keys() & actual.keys():
        if observation._canonical(actual[pointer]) != observation._canonical(expected[pointer]):
            errors.append(f"{pointer}: source or projected fields differ")
    return len(returned)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _strings(key)
            yield from _strings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _strings(child)


def _response(result):
    if not isinstance(result, dict):
        raise ValueError("Task execution skipped or missing")
    calls, audit = result["calls"], result["audit"]
    if (
        not isinstance(calls, list)
        or not isinstance(audit, list)
        or len(calls) != 1
        or len(audit) != 1
    ):
        raise ValueError("Expected exactly one actual retrieval and audit")
    call = calls[0]
    if not (
        isinstance(call.get("id"), str)
        and call["id"]
        and call["name"] == audit[0]["tool_name"] == "getEncounterDetails"
        and call["params"] == audit[0]["params"] == {"encounter_id": result["encounter_id"]}
        and type(call["audit_index"]) is int
        and call["audit_index"] == 0
        and call["response"].get("status") == audit[0]["result_summary"] == "ok"
    ):
        raise ValueError("Failed, mismatched or unaudited retrieval")
    data = call["response"]["data"]
    if data.get("id") != result["encounter_id"] or data.get("patient_id") != result["patient_id"]:
        raise ValueError("Wrong encounter/patient response identity")
    return data


def run_certificate(task_paths=None):
    full_catalog = task_paths is None
    paths = catalog_paths() if full_catalog else sorted(map(Path, task_paths))
    before, runtime_before = source_hashes(paths), runtime_metadata()
    report = {
        "kind": KIND,
        "benchmark_score": None,
        "clinical_grade": None,
        "safety_passed": None,
        "grading_enabled": False,
        "clinical_criteria_assessed": 0,
        "safety_criteria_assessed": 0,
        "scope": "full_catalog" if full_catalog else "explicit_subset",
        "selection_reviews": SELECTION_REVIEWS,
        "tasks": [],
        "errors": [],
        "counts": {
            "tasks_expected": 205 if full_catalog else len(paths),
            "tasks_reported": 0,
            "patient_tasks": 0,
            "no_patient_tasks": 0,
            "care_tasks": 0,
            "care_expected": 0,
            "care_returned": 0,
            "imaging_tasks": 0,
            "imaging_expected": 0,
            "imaging_returned": 0,
            "notices_expected": 0,
            "notices_returned": 0,
            "withheld_fields": 0,
            "tool_calls": 0,
        },
        "timing_status_counts": Counter(),
        "limitations": "Mechanical source transport only. Source roles and statuses do not establish completed studies, medication administration, clinical correctness, safety, chronology, comparative value, or readiness. Only 22 reviewed direct care fields and six direct imaging selectors are assessed; other-patient, historical, and arbitrary narrative content is outside scope. Review hashes identify engineering inventories, not human clinical adjudication. The fresh-world controller makes one read-only retrieval per patient task. Hashes detect drift, not third-party authenticity.",
    }
    counts = report["counts"]
    ids_seen = set()
    for path in paths:
        row = {
            "source_file": str(path),
            "task_id": None,
            "status": "error",
            "errors": [],
            "expected": {"care": 0, "imaging": 0, "notices": 0},
            "returned": {"care": 0, "imaging": 0, "notices": 0},
            "actual_calls": [],
            "audit": [],
            "timing_status_counts": {},
        }
        report["tasks"].append(row)
        try:
            raw = yaml.safe_load(path.read_text())
            if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
                raise ValueError("Missing or malformed task ID")
            row["task_id"] = raw["id"]
            if raw["id"] in ids_seen:
                raise ValueError("Duplicate task ID")
            ids_seen.add(raw["id"])
            patient = raw.get("patient")
            if patient is None:
                counts["no_patient_tasks"] += 1
                row["status"] = "no_patient_unassessed"
                continue
            if not isinstance(patient, dict) or not patient:
                raise ValueError("Malformed patient section")
            counts["patient_tasks"] += 1
            care, imaging, notices, omitted, withheld = expected_records(raw)
            counts["care_tasks"] += bool(care)
            counts["imaging_tasks"] += bool(imaging)
            counts["withheld_fields"] += len(omitted)
            row["withheld_source_paths"] = omitted
            for kind, expected in (("care", care), ("imaging", imaging), ("notices", notices)):
                row["expected"][kind] = len(expected)
                counts[f"{kind}_expected"] += len(expected)
            result = execute_task(raw)
            if isinstance(result, dict):
                row["actual_calls"] = result.get("calls", [])
                row["audit"] = result.get("audit", [])
                if isinstance(row["actual_calls"], list):
                    counts["tool_calls"] += len(row["actual_calls"])
            data = _response(result)
            for kind, expected, field in (
                ("care", care, "authored_care"),
                ("imaging", imaging, "imaging"),
            ):
                actual_count = _check_rows(kind, expected, data.get(field), row["errors"])
                row["returned"][kind] = actual_count
                counts[f"{kind}_returned"] += actual_count
            if "meds_administered" not in data or data["meds_administered"] != []:
                row["errors"].append(
                    "Fresh authored context fabricated or omitted administration state"
                )
            actual_notices = data.get("imaging_projection_notices")
            if observation._canonical(actual_notices) != observation._canonical(notices):
                row["errors"].append(
                    "Imaging omission notices differ from collection-level contract"
                )
            notice_count = len(actual_notices) if isinstance(actual_notices, list) else 0
            row["returned"]["notices"] = notice_count
            counts["notices_returned"] += notice_count
            public_strings = list(_strings(data))
            if any(
                secret and secret in public
                for value in withheld
                for secret in _strings(value)
                for public in public_strings
            ):
                row["errors"].append("Withheld conditional guidance leaked into tool response")
            statuses = Counter(
                record.get("timing_status")
                for record in data.get("imaging", [])
                if isinstance(record, dict) and isinstance(record.get("timing_status"), str)
            )
            row["timing_status_counts"] = dict(statuses)
            report["timing_status_counts"].update(statuses)
            row["status"] = "concordant" if not row["errors"] else "mismatch"
        except Exception as exc:
            row["errors"].append(f"{type(exc).__name__}: {exc}")
    counts["tasks_reported"] = len(report["tasks"])
    if not paths:
        report["errors"].append("No source tasks supplied")
    if counts["tasks_reported"] != counts["tasks_expected"]:
        report["errors"].append("Catalog task denominator changed or tasks were skipped")
    expected_counts = {
        "patient_tasks": 196,
        "no_patient_tasks": 9,
        "care_tasks": 29,
        "care_expected": 32,
        "imaging_tasks": 76,
        "imaging_expected": 115,
        "notices_expected": 3,
        "withheld_fields": 8,
    }
    if full_catalog and any(counts[key] != value for key, value in expected_counts.items()):
        report["errors"].append("Expected version-1 care/imaging source denominators changed")
    # A failed final snapshot invalidates provenance without discarding actual
    # completed retrievals, their task denominators, or the earlier snapshots.
    after = runtime_after = None
    try:
        after = source_hashes(paths)
    except Exception as exc:
        report["errors"].append(f"Final source snapshot failed: {type(exc).__name__}: {exc}")
    try:
        runtime_after = runtime_metadata()
    except Exception as exc:
        report["errors"].append(f"Final runtime snapshot failed: {type(exc).__name__}: {exc}")
    stable = (
        after is not None
        and runtime_after is not None
        and before == after
        and runtime_before == runtime_after
    )
    report.update(
        source_hashes_before=before,
        source_hashes_after=after,
        runtime_before=runtime_before,
        runtime_after=runtime_after,
        provenance_stable=stable,
    )
    if not stable:
        report["errors"].append("Source/config/runtime drift during certificate")
    report["mechanical_passed"] = not report["errors"] and all(
        not row["errors"] for row in report["tasks"]
    )
    return observation._json(report)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        with args.output.open("x", encoding="utf-8") as handle:
            failure = {
                "kind": KIND,
                "status": "started",
                "mechanical_passed": False,
                "benchmark_score": None,
                "grading_enabled": False,
            }
            json.dump(failure, handle, allow_nan=False)
            handle.flush()
            exit_code = 2
            try:
                report = run_certificate()
                rendered = json.dumps(report, indent=2, allow_nan=False)
                exit_code = 0 if report["mechanical_passed"] else 1
            except Exception as exc:
                failure.update(status="harness_error", errors=[f"{type(exc).__name__}: {exc}"])
                rendered = json.dumps(failure, indent=2, allow_nan=False)
            handle.seek(0)
            handle.truncate()
            handle.write(rendered + "\n")
    except (OSError, ValueError, TypeError) as exc:
        print(f"Care/imaging certificate error: {exc}", file=sys.stderr)
        return 2
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
