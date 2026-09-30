"""Operator review CLI preserves explicit assignments and distinguishes invalid receipts."""

import importlib
import json
from pathlib import Path

import pytest


def api():
    return importlib.import_module("scripts.operator_review")


def build_args(tmp_path):
    protocol = tmp_path / "protocol.json"
    assignment = tmp_path / "assignment.json"
    protocol.write_text('{"protocol_id":"tutorial-01","purpose":"engineering_tutorial"}')
    assignment.write_text(
        '{"assignment_id":"assignment-01","reviewer_id":"tutorial-user","presentation":"raw"}'
    )
    return [
        "build",
        "--case",
        "case-01=" + str(tmp_path / "source-one"),
        "--case",
        "case-02=" + str(tmp_path / "source-two"),
        "--protocol",
        str(protocol),
        "--assignment",
        str(assignment),
        "--output-dir",
        str(tmp_path / "packet"),
    ]


def test_build_preserves_case_order_and_passes_strict_metadata(tmp_path, monkeypatch, capsys):
    module = api()
    calls = []

    def build(cases, output_dir, **metadata):
        calls.append((cases, output_dir, metadata))
        return {"packet_id": "packet-01", "cases": [{"case_id": c} for c in cases]}

    monkeypatch.setattr(module, "build_operator_packet", build)
    assert module.main(build_args(tmp_path)) == 0
    cases, output, metadata = calls[0]
    assert list(cases) == ["case-01", "case-02"]
    assert cases["case-02"] == tmp_path / "source-two"
    assert output == tmp_path / "packet"
    assert metadata["assignment"]["presentation"] == "raw"
    summary = json.loads(capsys.readouterr().out)
    assert summary["assigned_cases"] == 2 and summary["assigned_axes"] == 12
    assert summary["status"] == "created"
    assert summary["clinical_validation"] == "not_established"


@pytest.mark.parametrize("entry", ["case-01=other", "missing-separator", "=directory", "case-03="])
def test_invalid_case_roster_never_invokes_builder(tmp_path, monkeypatch, capsys, entry):
    module = api()
    monkeypatch.setattr(
        module, "build_operator_packet", lambda *a, **k: pytest.fail("invalid roster reached build")
    )
    assert module.main(build_args(tmp_path) + ["--case", entry]) == 2
    assert "error" in capsys.readouterr().err.lower()
    assert not (tmp_path / "packet").exists()


@pytest.mark.parametrize("text", ['{"purpose":"a","purpose":"b"}', '{"x":NaN}', "[]"])
def test_invalid_metadata_stops_before_build(tmp_path, monkeypatch, capsys, text):
    module = api()
    args = build_args(tmp_path)
    (tmp_path / "protocol.json").write_text(text)
    monkeypatch.setattr(
        module,
        "build_operator_packet",
        lambda *a, **k: pytest.fail("invalid metadata reached build"),
    )
    assert module.main(args) == 2
    assert "error" in capsys.readouterr().err.lower()


@pytest.mark.parametrize("status,exit_code", [("recorded", 0), ("invalid_submission", 1)])
def test_import_reports_receipt_without_claiming_correctness(
    tmp_path, monkeypatch, capsys, status, exit_code
):
    module = api()
    calls = []

    def record(*args):
        calls.append(args)
        return {"status": status, "counts": {"assigned_axes": 12, "pending_axes": 12}}

    monkeypatch.setattr(module, "import_operator_response", record)
    assert (
        module.main(["import", "manifest.json", "response.json", "--output-dir", str(tmp_path)])
        == exit_code
    )
    assert calls == [(Path("manifest.json"), Path("response.json"), tmp_path)]
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == status and summary["counts"]["pending_axes"] == 12
    assert summary["clinical_validation"] == "not_established"
    assert summary["adjudication"] == "not_performed"


def test_packet_error_has_no_completion_message(tmp_path, monkeypatch, capsys):
    module = api()

    def reject(*args):
        raise ValueError("packet evidence was changed")

    monkeypatch.setattr(module, "import_operator_response", reject)
    assert module.main(["import", "m.json", "r.json", "--output-dir", str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "packet evidence was changed" in captured.err


def test_real_cli_build_blank_and_invalid_response_keep_all_assignments(tmp_path, capsys):
    """Exercise source snapshots, renderer, CLI and importer together without a model."""
    from healthcraft.reconciliation.execution import execute_reference, run_reconciliation_trial
    from healthcraft.reconciliation.fixture import load_scenario
    from healthcraft.reconciliation.oracle import load_expectations
    from scripts.explain_reconciliation import write_explanation_bundle

    scenario = load_scenario()
    documents = {
        "scenario": scenario,
        "expectations": load_expectations(),
        "evidence": run_reconciliation_trial(scenario=scenario, controller=execute_reference),
    }
    paths = {}
    for name, value in documents.items():
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps(value) + "\n")
        paths[name] = path
    bundle = tmp_path / "source"
    write_explanation_bundle(**paths, output_dir=bundle, source_context=True)
    args = ["build", "--case", "case-01=" + str(bundle), *build_args(tmp_path)[5:]]
    assert api().main(args) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["assigned_axes"] == 6
    packet = tmp_path / "packet"
    before = {p.relative_to(packet): p.read_bytes() for p in packet.rglob("*") if p.is_file()}
    for label, response, expected_code, expected_status in [
        ("blank", packet / "response-template.json", 0, "recorded"),
        ("invalid", tmp_path / "invalid.json", 1, "invalid_submission"),
    ]:
        if label == "invalid":
            response.write_bytes(b'{"cases": [broken json}\n')
        assert (
            api().main(
                [
                    "import",
                    str(packet / "manifest.json"),
                    str(response),
                    "--output-dir",
                    str(tmp_path / (label + "-receipt")),
                ]
            )
            == expected_code
        )
        summary = json.loads(capsys.readouterr().out)
        assert summary["status"] == expected_status
        assert summary["counts"]["assigned_axes"] == 6
        assert summary["counts"]["pending_axes"] == 6
    after = {p.relative_to(packet): p.read_bytes() for p in packet.rglob("*") if p.is_file()}
    assert before == after
