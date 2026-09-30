"""Offline reports bind exact inputs and never overwrite an earlier report."""

import hashlib
import importlib
import json
from copy import deepcopy

import pytest

from healthcraft.reconciliation.execution import execute_reference, run_reconciliation_trial
from healthcraft.reconciliation.fixture import load_scenario
from healthcraft.reconciliation.oracle import load_expectations, verify_reconciliation


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("HC_IDEMPOTENT_TOOLS", "1")
    scenario, expectations = load_scenario(), load_expectations()
    evidence = run_reconciliation_trial(scenario=scenario, controller=execute_reference)
    documents = dict(scenario=scenario, expectations=expectations, evidence=evidence)
    documents["verification"] = verify_reconciliation(scenario, expectations, evidence)
    paths = {}
    for name, value in documents.items():
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        paths[name] = path
    return paths


def api():
    return importlib.import_module("scripts.explain_reconciliation")


def test_bundle_preserves_exact_inputs_binds_every_payload_and_is_deterministic(inputs, tmp_path):
    original = {name: path.read_bytes() for name, path in inputs.items()}
    left, right = tmp_path / "first", tmp_path / "second"
    for output in (left, right):
        summary = api().write_explanation_bundle(**inputs, output_dir=output, title="Case review")
        assert summary["status"] == "available"
        assert summary["model_calls"] == 0
        manifest = json.loads((output / "manifest.json").read_text())
        assert set(manifest["files"]) == {
            str(p.relative_to(output))
            for p in output.rglob("*")
            if p.is_file() and p.name != "manifest.json"
        }
        for name, digest in manifest["files"].items():
            assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
        for name, content in original.items():
            assert (output / "inputs" / (name + ".json")).read_bytes() == content
        explanation = json.loads((output / "explanation.json").read_text())
        assert explanation["oracle_checks"] == json.loads(original["verification"])["checks"]
        assert (output / "report.html").read_text().startswith("<!doctype html>")
    assert {name: path.read_bytes() for name, path in inputs.items()} == original
    assert (left / "explanation.json").read_bytes() == (right / "explanation.json").read_bytes()
    assert (left / "report.html").read_bytes() == (right / "report.html").read_bytes()


def test_existing_output_is_never_modified_even_if_empty(inputs, tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(FileExistsError):
        api().write_explanation_bundle(**inputs, output_dir=output)
    assert list(output.iterdir()) == []


@pytest.mark.parametrize(
    "raw", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":1e999}', "[]", '{"x":"\\ud800"}']
)
def test_invalid_json_creates_no_output(inputs, tmp_path, raw):
    inputs["evidence"].write_text(raw)
    output = tmp_path / "invalid"
    with pytest.raises(ValueError):
        api().write_explanation_bundle(**inputs, output_dir=output)
    assert not output.exists()


@pytest.mark.parametrize("mutation", ["verdict", "boolean_as_integer"])
def test_supplied_verification_must_match_recomputed_oracle(inputs, tmp_path, mutation):
    verification = json.loads(inputs["verification"].read_text())
    verification["checks"]["readback"] = False if mutation == "verdict" else 1
    inputs["verification"].write_text(json.dumps(verification))
    output = tmp_path / "mismatched"
    with pytest.raises(ValueError, match="verification"):
        api().write_explanation_bundle(**inputs, output_dir=output)
    assert not output.exists()


def test_invalid_provenance_generates_unavailable_report_without_fabricated_counts(
    inputs, tmp_path
):
    evidence = json.loads(inputs["evidence"].read_text())
    evidence["scenario_sha256"] = "0" * 64
    inputs["evidence"].write_text(json.dumps(evidence))
    paths = {key: value for key, value in inputs.items() if key != "verification"}
    summary = api().write_explanation_bundle(**paths, output_dir=tmp_path / "unavailable")
    assert summary["status"] == "unavailable"
    report = json.loads((tmp_path / "unavailable/explanation.json").read_text())
    assert report["observed_execution"] is None
    assert report["notes"] == []


def test_renderer_error_creates_no_partial_report(inputs, tmp_path, monkeypatch):
    module = api()

    def fail(*args, **kwargs):
        raise ValueError("unsupported report")

    monkeypatch.setattr(module, "render_reconciliation_explanation", fail)
    with pytest.raises(ValueError, match="unsupported report"):
        module.write_explanation_bundle(**inputs, output_dir=tmp_path / "bad-render")
    assert not (tmp_path / "bad-render").exists()


@pytest.mark.parametrize("binding", ["evidence_sha256", "oracle_sha256"])
def test_detached_explanation_must_bind_the_actual_inputs(inputs, tmp_path, monkeypatch, binding):
    module = api()
    original = module.explain_reconciliation

    def mismatched(*args):
        explanation = original(*args)
        explanation["bindings"][binding] = "0" * 64
        return explanation

    monkeypatch.setattr(module, "explain_reconciliation", mismatched)
    with pytest.raises(ValueError, match="bindings"):
        module.write_explanation_bundle(**inputs, output_dir=tmp_path / "wrong-binding")
    assert not (tmp_path / "wrong-binding").exists()


def test_cli_reports_available_failed_reconciliation_as_successful_report(inputs, tmp_path, capsys):
    evidence = run_reconciliation_trial(
        scenario=load_scenario(), controller=lambda recorder, target: None
    )
    inputs["evidence"].write_text(json.dumps(evidence))
    arguments = []
    for name in ("scenario", "expectations", "evidence"):
        arguments.extend(["--" + name, str(inputs[name])])
    assert api().main(arguments + ["--output-dir", str(tmp_path / "cli")]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "available"
    assert summary["model_calls"] == 0


def test_recomputed_verification_is_not_edited_by_report_generation(inputs, tmp_path):
    expected = json.loads(inputs["verification"].read_text())
    api().write_explanation_bundle(**inputs, output_dir=tmp_path / "copy")
    assert json.loads((tmp_path / "copy/verification.json").read_text()) == deepcopy(expected)
