"""Source-context bundles keep inputs and verdicts intact while opting into navigation."""

import importlib
import json
from html.parser import HTMLParser

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
        path.write_text(json.dumps(value, indent=3) + "\n", encoding="utf-8")
        paths[name] = path
    return paths


def api():
    return importlib.import_module("scripts.explain_reconciliation")


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links, self.ids = [], []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "a":
            self.links.append(attrs["href"])
        if "id" in attrs:
            self.ids.append(attrs["id"])


def test_opt_in_changes_only_report_and_mode_manifest_not_original_verdicts(inputs, tmp_path):
    before = {key: path.read_bytes() for key, path in inputs.items()}
    default, context = tmp_path / "default", tmp_path / "context"
    api().write_explanation_bundle(**inputs, output_dir=default)
    api().write_explanation_bundle(**inputs, output_dir=context, source_context=True)
    for name in ("explanation.json", "verification.json"):
        assert (default / name).read_bytes() == (context / name).read_bytes()
    for name, content in before.items():
        assert (context / "inputs" / (name + ".json")).read_bytes() == content
        assert inputs[name].read_bytes() == content
    left = json.loads((default / "manifest.json").read_text())
    right = json.loads((context / "manifest.json").read_text())
    assert "source_context" not in left
    assert right["source_context"] == {
        "enabled": True,
        "schema_version": "healthcraft-reconciliation-source-context/v1",
    }
    assert left["bindings"] == right["bindings"]
    page = Links((context / "report.html").read_text())
    assert page.links and all(link.startswith("#") and link[1:] in page.ids for link in page.links)
    assert len(page.ids) == len(set(page.ids))


def test_opt_in_keeps_exclusive_output_creation(inputs, tmp_path):
    output = tmp_path / "already-exists"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("unchanged")
    with pytest.raises(FileExistsError):
        api().write_explanation_bundle(**inputs, output_dir=output, source_context=True)
    assert list(output.iterdir()) == [sentinel] and sentinel.read_text() == "unchanged"


def test_cli_source_context_uses_same_bound_documents(inputs, tmp_path, capsys):
    args = []
    for name, path in inputs.items():
        args.extend(["--" + name, str(path)])
    output = tmp_path / "cli"
    status = api().main(args + ["--output-dir", str(output), "--source-context"])
    assert status == 0
    assert json.loads(capsys.readouterr().out)["model_calls"] == 0
    assert json.loads((output / "manifest.json").read_text())["source_context"]["enabled"] is True


@pytest.mark.parametrize("flag", [None, 0, 1, "true"])
def test_bundle_rejects_nonboolean_mode_before_input_read_or_output(tmp_path, flag):
    output = tmp_path / "invalid-flag"
    with pytest.raises(ValueError, match="source_context"):
        api().write_explanation_bundle(
            scenario=tmp_path / "absent",
            expectations=tmp_path / "absent",
            evidence=tmp_path / "absent",
            output_dir=output,
            source_context=flag,
        )
    assert not output.exists()


def test_binding_rejection_with_opt_in_leaves_no_partial_bundle(inputs, tmp_path, monkeypatch):
    module = api()
    original = module.explain_reconciliation

    def drifted(*args):
        result = original(*args)
        result["bindings"]["scenario_sha256"] = "0" * 64
        return result

    monkeypatch.setattr(module, "explain_reconciliation", drifted)
    output = tmp_path / "invalid-binding"
    with pytest.raises(ValueError, match="bindings"):
        module.write_explanation_bundle(**inputs, output_dir=output, source_context=True)
    assert not output.exists()
