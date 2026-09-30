"""Offline source-concordance witness through real injection and MCP retrieval.

No models, clinical scoring, timeline inference or benchmark grading. Expected
records are selected directly from YAML independently of injector constants.
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
from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from healthcraft.mcp.server import create_server  # noqa: E402
from healthcraft.tasks.history_execution import ExecutionRecorder  # noqa: E402
from healthcraft.tasks.inject import inject_task_patient  # noqa: E402
from healthcraft.world.state import WorldState  # noqa: E402

# Public measurement-source scope of this certificate, not imported implementation lists.
LAB_GROUPS = ("labs", "labs_available", "labs_post_rosc", "labs_at_discharge", "initial_labs")
TIME_KEYS = {
    "vitals": ("time", "timestamp", "time_of_vitals"),
    "labs": ("time", "timestamp", "time_of_result"),
}
TIME_STATUSES = {
    "explicit",
    "missing",
    "naive",
    "date_only",
    "time_only",
    "unresolved",
    "invalid",
    "unsupported",
    "conflicting",
}


def _json(value):
    def default(item):
        if isinstance(item, (datetime, date)):
            return item.isoformat()
        if isinstance(item, Enum):
            return item.value
        raise TypeError(f"Unsupported source type: {type(item).__name__}")

    return json.loads(json.dumps(value, default=default, allow_nan=False))


def _canonical(value):
    return json.dumps(_json(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _pointer(key):
    return key.replace("~", "~0").replace("/", "~1")


def catalog_paths():
    return sorted((ROOT / "configs/tasks").rglob("*.yaml"))


def source_hashes(paths):
    files = set((ROOT / "src/healthcraft").rglob("*.py"))
    files.update(p for p in (ROOT / "configs").rglob("*") if p.is_file())
    files.update({Path(__file__).resolve(), ROOT / "pyproject.toml", *paths})
    files.update(ROOT.glob("requirements*.txt"))
    files.update(ROOT.glob("constraints*.txt"))
    return {
        str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p): hashlib.sha256(
            p.read_bytes()
        ).hexdigest()
        for p in sorted(files)
    }


def _instant(value):
    """Independent syntactic instant check; never complete partial source dates."""
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("naive")
        return value.replace(microsecond=0).astimezone(timezone.utc), Decimal(
            value.microsecond
        ) / 1000000
    if not isinstance(value, str):
        raise ValueError("not a timestamp")
    match = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2})[Tt](\d{2}:[0-5]\d:[0-5]\d)(?:\.(\d+))?([Zz]|[+-]\d{2}:[0-5]\d)", value
    )
    if match is None:
        raise ValueError("not an explicit instant")
    day, clock, fraction, zone = match.groups()
    parsed = datetime.fromisoformat(f"{day}T{clock}{'+00:00' if zone.lower() == 'z' else zone}")
    return parsed.astimezone(timezone.utc), Decimal("0." + (fraction or "0"))


def _expected_time(source, keys):
    present = [key for key in keys if key in source]
    if not present:
        return None, present
    try:
        instants = [_instant(source[key]) for key in present]
        if all(instant == instants[0] for instant in instants):
            return _json(source[present[0]]), present
    except (ValueError, OverflowError):
        pass
    return None, present


def _expected_records(patient):
    records = {"vitals": {}, "labs": {}}
    for key, value in patient.items():
        if key.startswith("vitals") or key.endswith("vitals"):
            pointer = "/patient/" + _pointer(key)
            if isinstance(value, dict):
                records["vitals"][pointer] = value
            elif isinstance(value, list):
                for index, entry in enumerate(value):
                    if not isinstance(entry, dict):
                        raise ValueError(f"Invalid vital source {pointer}/{index}")
                    records["vitals"][f"{pointer}/{index}"] = entry
            elif value is not None:
                raise ValueError(f"Invalid vital source {pointer}")
    for key in LAB_GROUPS:
        group = patient.get(key)
        if group is None:
            continue
        if not isinstance(group, dict):
            raise ValueError(f"Invalid laboratory group {key}")
        for name, value in group.items():
            if not isinstance(name, str):
                raise ValueError("Laboratory source key must be a string")
            records["labs"][f"/patient/{key}/{_pointer(name)}"] = value
    return records


def execute_task(raw):
    """One fresh deterministic world and actual synchronous retrieval per patient."""
    world = WorldState()
    ids = inject_task_patient(
        world, raw["id"], deepcopy(raw["patient"]), deepcopy(raw.get("setting", {}))
    )
    recorder = ExecutionRecorder(create_server(world), world)
    recorder.call("getEncounterDetails", {"encounter_id": ids["encounter_id"]})
    return _json(
        {"calls": recorder.calls, "audit": [asdict(entry) for entry in world.audit_log], **ids}
    )


def _check_records(kind, expected, returned, errors):
    counts = Counter()
    if not isinstance(returned, (list, tuple)):
        errors.append(f"{kind}: missing or malformed returned record list")
        return 0, counts
    actual = {}
    for row in returned:
        if not isinstance(row, dict) or not isinstance(row.get("source_path"), str):
            errors.append(f"{kind}: missing source path")
            continue
        pointer = row["source_path"]
        if pointer in actual:
            errors.append(f"{kind}: duplicate source path {pointer}")
        actual[pointer] = row
        status = row.get("timing_status")
        if status not in TIME_STATUSES:
            errors.append(f"{pointer}: invalid timing status")
        else:
            counts[status] += 1
    if set(actual) != set(expected):
        errors.append(f"{kind}: missing or unexpected source paths")
    for pointer in set(actual) & set(expected):
        row, source = actual[pointer], expected[pointer]
        if "source_data" not in row or _canonical(row["source_data"]) != _canonical(source):
            errors.append(f"{pointer}: raw source altered")
        timestamp, keys = _expected_time(
            source if isinstance(source, dict) else {}, TIME_KEYS[kind]
        )
        if row.get("source_time_keys") != keys:
            errors.append(f"{pointer}: source timing keys altered")
        if _canonical(row.get("timestamp")) != _canonical(timestamp):
            errors.append(f"{pointer}: timestamp or precision altered/invented")
        if timestamp is not None and row.get("timing_status") != "explicit":
            errors.append(f"{pointer}: explicit source instant not identified")
        elif timestamp is None and row.get("timing_status") == "explicit":
            errors.append(f"{pointer}: unresolved source reported explicit")
        if not keys and row.get("timing_status") != "missing":
            errors.append(f"{pointer}: absent timing source not marked missing")
    return len(returned), counts


def run_certificate(task_paths=None):
    full_catalog = task_paths is None
    paths = catalog_paths() if full_catalog else sorted(map(Path, task_paths))
    before = source_hashes(paths)
    report = {
        "kind": "authored-observation-source-concordance/v1",
        "benchmark_score": None,
        "grading_enabled": False,
        "clinical_criteria_assessed": 0,
        "safety_criteria_assessed": 0,
        "scope": "full_catalog" if full_catalog else "explicit_subset",
        "tasks": [],
        "errors": [],
        "counts": {
            "tasks_expected": 205 if full_catalog else len(paths),
            "tasks_reported": 0,
            "patient_tasks": 0,
            "no_patient_tasks": 0,
            "vitals_expected": 0,
            "vitals_returned": 0,
            "labs_expected": 0,
            "labs_returned": 0,
            "tool_calls": 0,
        },
        "timing_status_counts": {"vitals": Counter(), "labs": Counter()},
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": {
                name: importlib.metadata.version(name) for name in ("PyYAML", "jsonschema")
            },
        },
        "limitations": "Mechanical source transport only. No clinical correctness, chronology inference, model judgment, benchmark reward, superiority, or readiness is assessed. This certificate checks raw source records and time fields, not typed value/unit/reference/abnormal projections. Nested other-patient observations and unrecognized lab groups are outside scope. Hashes detect drift but do not authenticate third-party evidence.",
    }
    ids_seen = set()
    for path in paths:
        row = {
            "source_file": str(path),
            "task_id": None,
            "status": "error",
            "errors": [],
            "expected": {"vitals": 0, "labs": 0},
            "returned": {"vitals": 0, "labs": 0},
            "actual_calls": [],
            "audit": [],
            "timing_status_counts": {"vitals": {}, "labs": {}},
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
                row["status"] = "no_patient_unassessed"
                report["counts"]["no_patient_tasks"] += 1
                continue
            if not isinstance(patient, dict) or not patient:
                raise ValueError("Malformed patient section")
            report["counts"]["patient_tasks"] += 1
            expected = _expected_records(patient)
            for kind in expected:
                row["expected"][kind] = len(expected[kind])
                report["counts"][f"{kind}_expected"] += len(expected[kind])
            result = execute_task(raw)
            if not isinstance(result, dict):
                raise ValueError("Task execution skipped or missing")
            calls, audit = result["calls"], result["audit"]
            row["actual_calls"] = calls
            row["audit"] = audit
            report["counts"]["tool_calls"] += len(calls)
            if len(calls) != 1 or len(audit) != 1:
                raise ValueError("Expected one actual retrieval and audit")
            call = calls[0]
            if not (
                call["name"] == audit[0]["tool_name"] == "getEncounterDetails"
                and call["params"] == audit[0]["params"] == {"encounter_id": result["encounter_id"]}
                and call["audit_index"] == 0
                and call["response"].get("status") == audit[0]["result_summary"] == "ok"
            ):
                raise ValueError("Failed, mismatched or unaudited retrieval")
            data = call["response"]["data"]
            if (
                data.get("id") != result["encounter_id"]
                or data.get("patient_id") != result["patient_id"]
            ):
                raise ValueError("Wrong encounter/patient response identity")
            for kind in expected:
                returned, statuses = _check_records(
                    kind, expected[kind], data.get(kind), row["errors"]
                )
                row["returned"][kind] = returned
                report["counts"][f"{kind}_returned"] += returned
                row["timing_status_counts"][kind] = dict(statuses)
                report["timing_status_counts"][kind].update(statuses)
            for name in ("arrival", "triage"):
                field = name + "_time"
                value, keys = _expected_time(patient, (field,))
                row[name] = {
                    "source_keys": keys,
                    "source": _json(patient.get(field)),
                    "expected": value,
                    "returned": data.get(field),
                }
                if field not in data or _canonical(data[field]) != _canonical(value):
                    row["errors"].append(
                        f"{field}: source instant changed or missing time invented"
                    )
            row["status"] = "concordant" if not row["errors"] else "mismatch"
        except Exception as exc:
            row["errors"].append(f"{type(exc).__name__}: {exc}")
    report["counts"]["tasks_reported"] = len(report["tasks"])
    if not paths:
        report["errors"].append("No source tasks supplied")
    if len(report["tasks"]) != report["counts"]["tasks_expected"]:
        report["errors"].append("Catalog task denominator changed or tasks were skipped")
    if full_catalog and (
        report["counts"]["patient_tasks"] != 196
        or report["counts"]["labs_expected"] != 991
        or report["counts"]["vitals_expected"] != 208
    ):
        report["errors"].append(
            "Expected version-1 196-patient/208-vital/991-lab catalog denominator changed"
        )
    after = source_hashes(paths)
    report.update(
        source_hashes_before=before, source_hashes_after=after, provenance_stable=before == after
    )
    if before != after:
        report["errors"].append("Source/config hash drift during certificate")
    report["mechanical_passed"] = not report["errors"] and all(
        not row["errors"] for row in report["tasks"]
    )
    return _json(report)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        with args.output.open("x", encoding="utf-8") as handle:
            failure = {
                "kind": "authored-observation-source-concordance/v1",
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
        print(f"Observation certificate error: {exc}", file=sys.stderr)
        return 2
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
