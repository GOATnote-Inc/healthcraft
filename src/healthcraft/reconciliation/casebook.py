"""Pinned development casebooks with separately authored expectation receipts.

Inventory and mechanical consistency checks do not constitute independent
clinical review. Every case in this version is exposed development material.
The loader never generates or replaces the expectation files it checks.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from healthcraft.reconciliation.fixture import _json_copy, _keys
from healthcraft.reconciliation.fixture_v2 import source_rows, validate_scenario

DEFAULT_CASEBOOK_PATH = (
    Path(__file__).resolve().parents[3] / "configs/evaluation/reconciliation_v2/casebook.json"
)
DEFAULT_CASEBOOK_SHA256 = "39f8bcbc16e011cf10b79c78c70e39cf165b44d245fb92417f9688972d0d5cdb"
CONTROLS = frozenset(
    {
        "valid",
        "wrong_exclusion",
        "wrong_target",
        "ack_without_storage",
        "duplicate_notes",
        "incorrect_content_readback",
        "interrupted_after_write",
        "incomplete_capture",
    }
)
_LABEL_STATUS = "engineering_authored_independent_review_pending"


def canonical_bytes(value: object) -> bytes:
    """Canonical finite JSON, including exact scalar and container types."""
    return json.dumps(
        _json_copy(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _pairs(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key}")
        result[key] = value
    return result


def _read(path: Path) -> tuple[bytes, dict]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Casebook inputs must be regular, non-symlink files")
    raw = path.read_bytes()
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
        canonical_bytes(value)
    except (UnicodeError, RecursionError, TypeError) as exc:
        raise ValueError("Casebook input must be finite UTF-8 JSON") from exc
    if type(value) is not dict:
        raise ValueError("Casebook input must be a JSON object")
    return raw, value


def _hash(value: object) -> None:
    if type(value) is not str or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("An explicit lowercase SHA-256 digest is required")


def _same(actual: object, expected: object, message: str) -> None:
    if canonical_bytes(actual) != canonical_bytes(expected):
        raise ValueError(message)


def _expectations(scenario: dict, expected: dict) -> None:
    _keys(
        expected,
        {
            "schema_version",
            "scenario_id",
            "scenario_sha256",
            "target",
            "sources",
            "observation_source_ids",
            "unresolved_conflicts",
            "scope_exclusions",
        },
    )
    if expected["schema_version"] != "healthcraft-reconciliation-expectations/v2":
        raise ValueError("Unsupported expectations schema")
    if expected["scenario_id"] != scenario["id"] or expected["scenario_sha256"] != digest(scenario):
        raise ValueError("Expectations must bind their exact source scenario")
    _same(expected["target"], scenario["target"], "Expectations target differs from scenario")
    rows = source_rows(scenario)
    if type(expected["sources"]) is not list:
        raise ValueError("Expected sources must be an array")
    # Lists have a stable source-ID ordering in this receipt contract. Comparing
    # whole descriptors also rejects duplicate IDs, invented facts and aliases.
    _same(
        expected["sources"],
        sorted(rows, key=lambda row: row["source_id"]),
        "Authored source ledger differs from original source rows",
    )
    target = scenario["target"]
    included = [row for row in rows if row["encounter_id"] == target["encounter_id"]]
    _same(
        expected["observation_source_ids"],
        sorted(row["source_id"] for row in included),
        "Observation ledger must cover exactly the target encounter",
    )
    excluded = []
    for row in sorted(rows, key=lambda row: row["source_id"]):
        if row["encounter_id"] != target["encounter_id"]:
            excluded.append(
                {
                    **{key: row[key] for key in ("source_id", "patient_id", "encounter_id")},
                    "reason": "other_patient"
                    if row["patient_id"] != target["patient_id"]
                    else "other_encounter",
                }
            )
    _same(expected["scope_exclusions"], excluded, "Scope ledger misstates source ownership")
    groups = defaultdict(list)
    for row in included:
        if row["source_collection"] == "treatments_given" and "event_id" in row["source"]:
            groups[row["source"]["event_id"]].append(row)
    conflicts = []
    for event_id, group in sorted(groups.items()):
        statuses = {row["source"]["reported_status"] for row in group}
        if {"administered", "not_administered"} <= statuses:
            conflicts.append(
                {
                    "source_ids": sorted(row["source_id"] for row in group),
                    "event_id": event_id,
                    "field": "reported_status",
                }
            )
    _same(
        expected["unresolved_conflicts"],
        conflicts,
        "Conflict ledger must retain every source for opposing literal event reports",
    )


def load_cases(
    casebook_path: Path | None = None,
    *,
    expected_sha256: str | None = None,
) -> tuple[dict, ...]:
    """Validate the entire pinned inventory before returning detached cases.

    Explicit paths require a separately supplied canonical digest. Reading a
    digest from the same untrusted file would not authenticate that file.
    """
    if casebook_path is None:
        casebook_path = DEFAULT_CASEBOOK_PATH
        expected_sha256 = DEFAULT_CASEBOOK_SHA256 if expected_sha256 is None else expected_sha256
    _hash(expected_sha256)
    path = Path(casebook_path)
    root = path.parent
    if root.is_symlink():
        raise ValueError("Casebook directory must not be a symlink")
    _, book = _read(path)
    if digest(book) != expected_sha256:
        raise ValueError("Casebook canonical digest mismatch")
    _keys(book, {"schema_version", "id", "exposure", "label_status", "cases", "files"})
    if (
        book["schema_version"] != "healthcraft-reconciliation-casebook/v2"
        or book["id"] != "source-reconciliation-development/v2"
        or book["exposure"] != "development"
        or book["label_status"] != _LABEL_STATUS
    ):
        raise ValueError("Unsupported casebook schema, exposure or label status")
    if type(book["cases"]) is not list or not 1 <= len(book["cases"]) <= 128:
        raise ValueError("Casebook requires one to 128 cases")
    if type(book["files"]) is not dict:
        raise ValueError("Casebook requires a file inventory")
    ids, payloads = set(), set()
    for entry in book["cases"]:
        _keys(
            entry,
            {
                "case_id",
                "scenario_family_id",
                "scenario",
                "scenario_sha256",
                "expectations",
                "expectations_sha256",
                "designated_control",
            },
        )
        case_id = entry["case_id"]
        if (
            type(case_id) is not str
            or not re.fullmatch(r"REC2-[0-9]{3}", case_id)
            or case_id in ids
        ):
            raise ValueError("Invalid or duplicate case identity")
        ids.add(case_id)
        family = entry["scenario_family_id"]
        if type(family) is not str or not re.fullmatch(r"[a-z0-9][a-z0-9/-]{0,127}", family):
            raise ValueError("Invalid declared scenario family")
        if (
            type(entry["designated_control"]) is not str
            or entry["designated_control"] not in CONTROLS
        ):
            raise ValueError("Unknown designated development control")
        for field in ("scenario", "expectations"):
            name = f"{case_id}/{field}.json"
            if entry[field] != name:
                raise ValueError("Case files require controlled paths within their case directory")
            _hash(entry[field + "_sha256"])
            payloads.add(name)
    if set(book["files"]) != payloads:
        raise ValueError("Casebook file inventory is not exact")
    actual_files, actual_dirs = set(), set()
    for item in root.rglob("*"):
        if item.is_symlink():
            raise ValueError("Symlink in casebook inventory")
        relative = item.relative_to(root).as_posix()
        if item.is_file():
            actual_files.add(relative)
        elif item.is_dir():
            actual_dirs.add(relative)
        else:
            raise ValueError("Unexpected filesystem object in casebook inventory")
    if actual_files != payloads | {path.name} or actual_dirs != ids:
        raise ValueError("Missing or unlisted casebook files/directories")
    cases = []
    for entry in book["cases"]:
        values = {}
        for field in ("scenario", "expectations"):
            name = entry[field]
            _hash(book["files"][name])
            raw, value = _read(root / name)
            if hashlib.sha256(raw).hexdigest() != book["files"][name]:
                raise ValueError("Casebook payload file digest mismatch")
            if digest(value) != entry[field + "_sha256"]:
                raise ValueError("Casebook payload canonical digest mismatch")
            values[field] = value
        scenario = validate_scenario(values["scenario"])
        if scenario["id"] != f"synthetic-ed-reconciliation/v2/{entry['case_id']}":
            raise ValueError("Scenario identity does not match case identity")
        _expectations(scenario, values["expectations"])
        cases.append(
            {
                "schema_version": "healthcraft-reconciliation-case/v2",
                **{
                    key: entry[key]
                    for key in (
                        "case_id",
                        "scenario_family_id",
                        "scenario_sha256",
                        "expectations_sha256",
                        "designated_control",
                    )
                },
                "casebook_sha256": expected_sha256,
                "exposure": book["exposure"],
                "label_status": book["label_status"],
                **values,
            }
        )
    return tuple(cases)


def load_case(
    casebook_path: Path | None,
    case_id: str,
    *,
    expected_sha256: str | None = None,
) -> dict:
    """Select only after validating every case, including unselected entries."""
    cases = load_cases(casebook_path, expected_sha256=expected_sha256)
    for case in cases:
        if case["case_id"] == case_id:
            return case
    raise ValueError(f"Unknown case: {case_id}")
