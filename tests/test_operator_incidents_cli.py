"""Exercise the public command boundary without models or reviewer fabrication."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def cli():
    path = Path(__file__).parents[1] / "scripts/operator_incidents.py"
    spec = importlib.util.spec_from_file_location("incident_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_operator_build_passes_explicit_selection_pin_and_assignment(
    cli, monkeypatch, tmp_path, capsys
):
    config = {
        "expected_sha256": "a" * 64,
        "selections": {"review-a": "original-attempt"},
        "protocol": {"protocol_id": "test", "purpose": "engineering_development"},
        "assignment": {"assignment_id": "test", "operator_id": "test", "presentation": "raw"},
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    calls = []

    def build(*args, **kwargs):
        calls.append((args, kwargs))
        return {"packet_id": "test", "cases": [{}]}

    monkeypatch.setattr(cli, "build_incident_packet", build)
    assert (
        cli.main(
            [
                "build",
                "source/manifest.json",
                "--config",
                str(config_path),
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
        == 0
    )
    assert calls[0][1] == config
    assert json.loads(capsys.readouterr().out)["assigned_cases"] == 1


@pytest.mark.parametrize("command", ["import", "adjudication-import"])
def test_invalid_submission_is_preserved_and_returns_one(
    cli, monkeypatch, tmp_path, capsys, command
):
    calls = []

    def receive(*args, **kwargs):
        calls.append((args, kwargs))
        return {"status": "invalid_submission", "counts": {"pending": 2}}

    monkeypatch.setattr(
        cli,
        "import_incident_response" if command == "import" else "import_adjudication_response",
        receive,
    )
    assert (
        cli.main(
            [command, "packet/manifest.json", "invalid.json", "--output-dir", str(tmp_path / "out")]
        )
        == 1
    )
    assert len(calls) == 1
    assert json.loads(capsys.readouterr().out)["counts"] == {"pending": 2}


def test_duplicate_config_keys_fail_before_build(cli, monkeypatch, tmp_path, capsys):
    config = tmp_path / "config.json"
    config.write_text('{"assignment":{},"assignment":{}}')
    monkeypatch.setattr(cli, "build_incident_packet", lambda *a, **k: pytest.fail("called build"))
    assert (
        cli.main(
            [
                "build",
                "source/manifest.json",
                "--config",
                str(config),
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
        == 2
    )
    assert "error" in capsys.readouterr().err.lower()


def test_summary_preserves_null_assigned_records_and_explicit_resolver(
    cli, monkeypatch, tmp_path, capsys
):
    roster = tmp_path / "roster.json"
    roster.write_text('{"reviewer-a":"first/manifest.json","reviewer-b":null}')
    calls = []

    def summarize(*args, **kwargs):
        calls.append((args, kwargs))
        return {"assigned_opportunities": 4, "counts": {"pending": 2}, "cases": []}

    monkeypatch.setattr(cli, "summarize_adjudications", summarize)
    assert (
        cli.main(
            [
                "summary",
                "issued/manifest.json",
                "--records",
                str(roster),
                "--resolver-record",
                "resolver/manifest.json",
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
        == 0
    )
    assert calls[0][0][1] == {"reviewer-a": "first/manifest.json", "reviewer-b": None}
    assert calls[0][1]["resolver_record"] == Path("resolver/manifest.json")
    assert json.loads(capsys.readouterr().out)["assigned_opportunities"] == 4
