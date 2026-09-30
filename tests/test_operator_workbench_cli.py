"""The optional view CLI never replaces the original assignment or importer."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def cli():
    path = Path(__file__).parents[1] / "scripts/operator_workbench.py"
    spec = importlib.util.spec_from_file_location("workbench_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_preserves_explicit_paths_and_reports_view_only(cli, monkeypatch, tmp_path, capsys):
    calls = []

    def build(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "issuer_kind": "incident",
            "packet_sha256": "a" * 64,
            "view_version": "healthcraft-operator-workbench/v1",
        }

    monkeypatch.setattr(cli, "build_workbench", build)
    assert (
        cli.main(
            [
                "build",
                "issuer/manifest.json",
                "--output-dir",
                str(tmp_path / "view"),
                "--source-manifest-override",
                "source/manifest.json",
            ]
        )
        == 0
    )
    assert calls[0][0] == (Path("issuer/manifest.json"), tmp_path / "view")
    assert calls[0][1] == {"source_manifest_override": Path("source/manifest.json")}
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "created"
    assert summary["import_responses_with"] == "original_issuer_manifest"


def test_verify_accepts_pinned_portable_locations(cli, monkeypatch, tmp_path, capsys):
    calls = []

    def validate(*args, **kwargs):
        calls.append((args, kwargs))
        return {"cases": [{}]}, {
            "issuer_kind": "adjudication",
            "packet_sha256": "a" * 64,
            "view_version": "healthcraft-operator-workbench/v1",
        }

    monkeypatch.setattr(cli, "validate_workbench", validate)
    assert (
        cli.main(
            ["verify", "view/manifest.json", "--issuer-manifest-override", "issuer/manifest.json"]
        )
        == 0
    )
    assert calls[0][1] == {
        "issuer_manifest_override": Path("issuer/manifest.json"),
        "source_manifest_override": None,
    }
    assert json.loads(capsys.readouterr().out)["assigned_cases"] == 1


def test_preflight_failure_returns_two_without_success_output(cli, monkeypatch, tmp_path, capsys):
    def build(*a, **k):
        raise ValueError("Original assignment changed")

    monkeypatch.setattr(cli, "build_workbench", build)
    assert cli.main(["build", "issuer/manifest.json", "--output-dir", str(tmp_path / "view")]) == 2
    output = capsys.readouterr()
    assert not output.out
    assert "Original assignment changed" in output.err
