"""Inventoried development cases retain authored expectations and explicit identities."""

import hashlib
import importlib
import json
from copy import deepcopy

import pytest

from healthcraft.reconciliation.fixture import load_scenario
from healthcraft.reconciliation.oracle import load_expectations


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def write(path, value):
    path.write_bytes(canonical(value) + b"\n")


def api():
    return importlib.import_module("healthcraft.reconciliation.casebook")


@pytest.fixture
def book(tmp_path):
    root = tmp_path / "book"
    root.mkdir()
    manifest = {
        "schema_version": "healthcraft-reconciliation-casebook/v2",
        "id": "source-reconciliation-development/v2",
        "exposure": "development",
        "label_status": "engineering_authored_independent_review_pending",
        "cases": [],
        "files": {},
    }
    for number in (1, 2):
        case_id = f"REC2-{number:03d}"
        directory = root / case_id
        directory.mkdir()
        scenario, expected = load_scenario(), load_expectations()
        scenario.update(
            schema_version="healthcraft-reconciliation-scenario/v2",
            id="synthetic-ed-reconciliation/v2/" + case_id,
        )
        expected.update(
            schema_version="healthcraft-reconciliation-expectations/v2",
            scenario_id=scenario["id"],
            scenario_sha256=digest(scenario),
        )
        write(directory / "scenario.json", scenario)
        write(directory / "expectations.json", expected)
        entry = {
            "case_id": case_id,
            "scenario_family_id": f"fixture-family-{number}",
            "scenario": f"{case_id}/scenario.json",
            "scenario_sha256": digest(scenario),
            "expectations": f"{case_id}/expectations.json",
            "expectations_sha256": digest(expected),
            "designated_control": "valid",
        }
        manifest["cases"].append(entry)
        for field in ("scenario", "expectations"):
            name = entry[field]
            manifest["files"][name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    write(root / "casebook.json", manifest)
    return root, manifest


def refresh(book, case_number=0):
    root, manifest = book
    entry = manifest["cases"][case_number]
    for field in ("scenario", "expectations"):
        raw = (root / entry[field]).read_bytes()
        entry[field + "_sha256"] = digest(json.loads(raw))
        manifest["files"][entry[field]] = hashlib.sha256(raw).hexdigest()
    write(root / "casebook.json", manifest)


def load(book, case_id="REC2-001"):
    root, manifest = book
    return api().load_case(root / "casebook.json", case_id, expected_sha256=digest(manifest))


def test_detached_case_binds_explicit_sources_and_pending_review(book):
    root, manifest = book
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    case = load(book)
    assert case["schema_version"] == "healthcraft-reconciliation-case/v2"
    assert case["casebook_sha256"] == digest(manifest)
    assert case["exposure"] == "development"
    assert case["label_status"] == "engineering_authored_independent_review_pending"
    assert case["scenario_sha256"] == digest(case["scenario"])
    assert case["expectations_sha256"] == digest(case["expectations"])
    case["scenario"]["patients"].clear()
    assert load(book)["scenario"]["patients"]
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("pin", [None, "", "0" * 64, "A" * 64, True])
def test_explicit_registry_requires_the_correct_canonical_pin(book, pin):
    with pytest.raises(ValueError):
        api().load_case(book[0] / "casebook.json", "REC2-001", expected_sha256=pin)


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_case",
        "case_path",
        "unknown_control",
        "label_claim",
        "held_out",
        "unknown_field",
        "missing_file",
        "unlisted_file",
        "symlink",
        "bad_file_hash",
    ],
)
def test_invalid_registry_or_source_inventory_is_not_partially_selected(book, change):
    root, manifest = book
    second = manifest["cases"][1]
    if change == "duplicate_case":
        second["case_id"] = "REC2-001"
    elif change == "case_path":
        second["scenario"] = "../escape.json"
    elif change == "unknown_control":
        second["designated_control"] = "clinical_success"
    elif change == "label_claim":
        manifest["label_status"] = "physician_validated"
    elif change == "held_out":
        manifest["exposure"] = "held_out"
    elif change == "unknown_field":
        manifest["registered"] = True
    elif change == "missing_file":
        (root / second["scenario"]).unlink()
    elif change == "unlisted_file":
        (root / "extra.json").write_text("{}")
    elif change == "bad_file_hash":
        manifest["files"][second["scenario"]] = "0" * 64
    else:
        source = root / second["scenario"]
        outside = root.parent / "outside.json"
        outside.write_bytes(source.read_bytes())
        source.unlink()
        source.symlink_to(outside)
    write(root / "casebook.json", manifest)
    with pytest.raises((ValueError, OSError)):
        load(book)  # The unselected second case must also be validated.


@pytest.mark.parametrize(
    "change",
    [
        "wrong_target",
        "missing_observation",
        "wrong_exclusion",
        "missing_conflict",
        "duplicate_source",
        "source_value",
        "foreign_scenario",
    ],
)
def test_rehashed_expectations_must_match_the_authored_source_contract(book, change):
    root, manifest = book
    path = root / manifest["cases"][1]["expectations"]
    expected = json.loads(path.read_bytes())
    if change == "wrong_target":
        expected["target"]["patient_id"] = "PAT-BBBBBBBB"
    elif change == "missing_observation":
        expected["observation_source_ids"].pop()
    elif change == "wrong_exclusion":
        expected["scope_exclusions"][0]["reason"] = "other_patient"
    elif change == "missing_conflict":
        expected["unresolved_conflicts"] = []
    elif change == "duplicate_source":
        expected["sources"].append(deepcopy(expected["sources"][0]))
    elif change == "source_value":
        expected["sources"][0]["source"]["time"] = "2026-09-30T00:00:00Z"
    else:
        expected["scenario_id"] = "synthetic-ed-reconciliation/v2/REC2-001"
    write(path, expected)
    refresh(book, 1)
    with pytest.raises(ValueError):
        load(book)


@pytest.mark.parametrize("raw", [b'{"id":"a","id":"b"}', b'{"id":NaN}', b'{"id":1e999}', b"[]"])
def test_strict_registry_json(book, raw):
    root, manifest = book
    (root / "casebook.json").write_bytes(raw)
    with pytest.raises(ValueError):
        load(book)


def test_unknown_case_and_default_registry_pin_are_explicit(book, monkeypatch):
    with pytest.raises(ValueError, match="Unknown case"):
        load(book, "REC2-999")
    module = api()
    monkeypatch.setattr(module, "DEFAULT_CASEBOOK_PATH", book[0] / "casebook.json")
    monkeypatch.setattr(module, "DEFAULT_CASEBOOK_SHA256", digest(book[1]))
    cases = module.load_cases()
    assert [case["case_id"] for case in cases] == ["REC2-001", "REC2-002"]
    assert module.load_case(None, "REC2-001") == cases[0]
