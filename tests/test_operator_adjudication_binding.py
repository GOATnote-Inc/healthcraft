"""Independent source-backed adjudication projection and preservation contracts."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from healthcraft import operator_adjudication as adjudication
from healthcraft import operator_incidents as incidents

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/reconciliation/20260930/casebook-native-v2/run"
ASSIGNMENT = {"assignment_id": "review-1", "adjudicator_id": "reviewer-1", "role": "initial"}


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(adjudication._canonical(value) + b"\n")


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def source_backed(tmp_path):
    """Copy a two-attempt subset; never mutate committed source evidence."""
    source = tmp_path / "source"
    source.mkdir()
    manifest = json.loads((SOURCE / "manifest.json").read_text())
    selected = {"REC2-001/reference", "REC2-001/designated"}
    names = {
        name
        for name in manifest["files"]
        if name == "REC2-001/case.json"
        or any(name.startswith(attempt + "/") for attempt in selected)
    }
    for name in names:
        output = source / name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes((SOURCE / name).read_bytes())
    manifest["files"] = {name: _sha(source / name) for name in names}
    manifest["roster"] = [row for row in manifest["roster"] if row["id"] in selected]
    manifest["outcomes"] = [row for row in manifest["outcomes"] if row["id"] in selected]
    _write(source / "manifest.json", manifest)
    operator = tmp_path / "operator"
    packet = incidents.build_incident_packet(
        source / "manifest.json",
        operator,
        expected_sha256=_sha(source / "manifest.json"),
        selections={"opaque-1": "REC2-001/reference", "opaque-2": "REC2-001/designated"},
        protocol={"protocol_id": "dev-1", "purpose": "engineering_development"},
        assignment={
            "assignment_id": "operator-1",
            "operator_id": "author-1",
            "presentation": "raw",
        },
    )
    response = incidents.incident_response_template(packet)
    response["cases"][0]["incident_assessment"]["summary"] = "Exact original draft report"
    response_path = tmp_path / "response.json"
    _write(response_path, response)
    issued = tmp_path / "adjudication"
    result = adjudication.build_adjudication_packet(
        operator / "manifest.json", response_path, issued, assignment=ASSIGNMENT
    )
    return {
        "source": source,
        "operator": operator,
        "response": response_path,
        "issued": issued,
        "packet": result,
    }


def _rehash_presentation(folder, packet):
    """Keep saved originals intact while making derived files self-consistent."""
    template = adjudication.adjudication_template(packet)
    files = {
        "public/packet.json": adjudication._canonical(packet) + b"\n",
        "public/response-template.json": adjudication._canonical(template) + b"\n",
        "public/report.html": adjudication._render(packet, template).encode("utf-8"),
    }
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["packet_sha256"] = adjudication._digest(packet)
    for name, raw in files.items():
        (folder / name).write_bytes(raw)
        manifest["files"][name] = hashlib.sha256(raw).hexdigest()
    _write(folder / "manifest.json", manifest)


@pytest.mark.parametrize("change", ["response", "scenario", "status", "missing_case"])
def test_self_rehashed_presentation_must_match_retained_originals(source_backed, change):
    folder = source_backed["issued"]
    originals = {p: p.read_bytes() for p in (folder / "coordinator").rglob("*") if p.is_file()}
    packet = source_backed["packet"]
    if change == "response":
        packet["cases"][0]["documents"]["response"]["incident_assessment"]["summary"] = (
            "Different report never submitted"
        )
    elif change == "scenario":
        packet["cases"][0]["documents"]["scenario"]["target"]["patient_id"] = "PAT-FFFFFFFF"
    elif change == "status":
        packet["cases"][0]["operator_report_status"] = "submitted"
    else:
        packet["cases"].pop()
    _rehash_presentation(folder, packet)
    with pytest.raises(ValueError):
        adjudication.validate_adjudication_packet(folder / "manifest.json")
    assert all(path.read_bytes() == raw for path, raw in originals.items())


def test_missing_coordinator_originals_cannot_disable_binding(source_backed):
    folder = source_backed["issued"]
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["source_bindings"]["coordinator_files"] = {}
    manifest["files"] = {
        name: digest
        for name, digest in manifest["files"].items()
        if not name.startswith("coordinator/")
    }
    shutil.rmtree(folder / "coordinator")
    _write(folder / "manifest.json", manifest)
    packet = source_backed["packet"]
    packet["cases"][0]["documents"]["response"]["incident_assessment"]["summary"] = (
        "Unbound replacement without original submission"
    )
    _rehash_presentation(folder, packet)
    with pytest.raises(ValueError):
        adjudication.validate_adjudication_packet(folder / "manifest.json")


@pytest.mark.parametrize("operation", ["build", "import", "summary"])
def test_adjudication_cannot_write_inside_original_pinned_source(source_backed, operation):
    source, issued = source_backed["source"], source_backed["issued"]
    original_files = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    output = source / ("forbidden-" + operation)
    with pytest.raises(ValueError):
        if operation == "build":
            adjudication.build_adjudication_packet(
                source_backed["operator"] / "manifest.json",
                source_backed["response"],
                output,
                assignment={**ASSIGNMENT, "assignment_id": "review-2"},
            )
        elif operation == "import":
            adjudication.import_adjudication_response(
                issued / "manifest.json", issued / "public/response-template.json", output
            )
        else:
            adjudication.summarize_adjudications(
                issued / "manifest.json", {"reviewer-1": None}, output
            )
    assert not output.exists()
    assert {p: p.read_bytes() for p in source.rglob("*") if p.is_file()} == original_files
    incidents.validate_incident_packet(source_backed["operator"] / "manifest.json")


def test_source_backed_blank_review_preserves_all_opportunities(source_backed, tmp_path):
    issued = source_backed["issued"]
    packet, _, _ = adjudication.validate_adjudication_packet(issued / "manifest.json")
    assert packet["cases"][0]["documents"]["response"]["incident_assessment"]["summary"] == (
        "Exact original draft report"
    )
    receipt = adjudication.import_adjudication_response(
        issued / "manifest.json", issued / "public/response-template.json", tmp_path / "import"
    )
    assert receipt["counts"] == {
        "assigned": 2,
        "declared": 0,
        "pending": 2,
        "unassessed": 0,
        "abstained": 0,
    }
    summary = adjudication.summarize_adjudications(
        issued / "manifest.json",
        {"reviewer-1": tmp_path / "import/manifest.json", "reviewer-2": None},
        tmp_path / "summary",
    )
    assert summary["assigned_opportunities"] == 4
    assert summary["counts"]["pending"] == 4
    assert len(summary["cases"]) == 2
