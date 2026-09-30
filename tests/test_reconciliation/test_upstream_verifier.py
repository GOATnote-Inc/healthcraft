"""Wrapper contracts use labeled stubs; optional tests execute unchanged upstream code."""

import csv
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
PIN = "bcbb8085fd549469e2dc7455f4bfd68a1b98895a"
SOURCE_SHA = "7ce0c9808afb5efb031c04e535e22f4fd8cad093b6bd500681c87fef2a8fde5d"
LICENSE_SHA = "646f8936b8ddcd14e13e578ff6857e368780b0d1a4f6066bee89211923a373e2"
HEADER = ["table", "_row_id", "cluster_id", "error_family", "error_subtype"]
ROWS = [
    [
        "treatments_given",
        rid,
        "EVENT-A01-reported-status",
        "source_disagreement",
        "opposing_reported_status",
    ]
    for rid in ("SRC-A04", "SRC-A05")
]


@pytest.fixture
def adapter():
    return importlib.import_module("healthcraft.reconciliation.upstream")


@pytest.fixture
def inputs(tmp_path):
    submission = tmp_path / "submission.csv"
    submission.write_text("table,_row_id\ntreatments_given,SRC-A04\n")
    labels = tmp_path / "labels.csv"
    with labels.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(ROWS)
    return submission, labels, tmp_path / "new-output"


@pytest.fixture
def stub_loader(adapter, monkeypatch):
    """No real pandas or upstream metric execution: wrapper unit fixture only."""
    calls = []

    def evaluate(submission, labels, log_dir, turn_count_override):
        calls.append((submission, labels, log_dir, turn_count_override))
        log_dir.mkdir(parents=True, exist_ok=True)
        metrics = {"reward": 1.0, "turn_count": turn_count_override}
        (log_dir / "metrics.json").write_text(json.dumps(metrics))
        (log_dir / "reward.txt").write_text("1.000000\n")
        return 1.0

    monkeypatch.setattr(adapter, "_load_verifier", lambda path: SimpleNamespace(evaluate=evaluate))
    monkeypatch.setattr(adapter, "_pandas_version", lambda: "unit-test-stub-no-runtime")
    return calls


def test_vendor_pin_and_exact_source_license(adapter):
    provenance = json.loads((adapter.VENDOR_DIR / "provenance.json").read_text())
    assert provenance["revision"] == PIN
    assert provenance["repository"] == "https://github.com/microsoft/HealthAgentBench"
    assert (
        hashlib.sha256((adapter.VENDOR_DIR / "harbor_evaluator.py.txt").read_bytes()).hexdigest()
        == SOURCE_SHA
    )
    assert hashlib.sha256((adapter.VENDOR_DIR / "LICENSE").read_bytes()).hexdigest() == LICENSE_SHA


def test_missing_dependency_has_null_reward_and_preserved_denominator(adapter, inputs, monkeypatch):
    def missing():
        raise ModuleNotFoundError("No module named pandas", name="pandas")

    monkeypatch.setattr(adapter, "_pandas_version", missing)
    result = adapter.run_upstream_verifier(*inputs, turn_count=7)
    assert result["status"] == "unavailable_dependency"
    assert result["upstream_reward"] is None
    assert result["scheduled_evaluations"] == 1
    assert result["attempted_evaluations"] == 0
    assert result["declared_turn_count"] == 7
    assert json.loads((inputs[2] / "report.json").read_text()) == result


@pytest.mark.parametrize("turn_count", [None, True, False, -1, 1.5, "2"])
def test_turn_count_is_explicit_nonnegative_integer(adapter, inputs, turn_count):
    with pytest.raises(ValueError, match="turn_count"):
        adapter.run_upstream_verifier(*inputs, turn_count=turn_count)
    assert not inputs[2].exists()


@pytest.mark.parametrize("content", [None, "do not overwrite"])
def test_existing_output_even_empty_is_refused(adapter, inputs, content):
    inputs[2].mkdir()
    if content:
        (inputs[2] / "existing.txt").write_text(content)
    with pytest.raises(FileExistsError):
        adapter.run_upstream_verifier(*inputs, turn_count=0)
    assert list(inputs[2].iterdir()) == ([] if content is None else [inputs[2] / "existing.txt"])


@pytest.mark.parametrize("filename", ["harbor_evaluator.py.txt", "LICENSE", "provenance.json"])
def test_tampered_vendor_never_imports(adapter, inputs, tmp_path, monkeypatch, filename):
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    for source in adapter.VENDOR_DIR.iterdir():
        if source.is_file():
            (vendor / source.name).write_bytes(source.read_bytes())
    (vendor / filename).write_bytes((vendor / filename).read_bytes() + b" ")
    monkeypatch.setattr(adapter, "VENDOR_DIR", vendor)
    monkeypatch.setattr(
        adapter, "_load_verifier", lambda path: pytest.fail("tampered source executed")
    )
    result = adapter.run_upstream_verifier(*inputs, turn_count=2)
    assert result["status"] == "provenance_error"
    assert result["upstream_reward"] is None
    assert result["attempted_evaluations"] == 0


@pytest.mark.parametrize(
    "data",
    [
        "table,_row_id,cluster_id\ntreatments_given,SRC-A04,cluster\n",
        ",".join(HEADER) + "\n",
        ",".join(HEADER) + "\ntreatments_given,SRC-A04,,family,subtype\n",
        ",".join(HEADER) + "\ntreatments_given,SRC-A04,c,f,s,extra\n",
        ",".join(HEADER) + "\ntreatments_given,SRC-A04,c,f\n",
        ",".join(HEADER) + "\ntreatments_given,SRC-A04,c,f,s\ntreatments_given,SRC-A04,c,f,s\n",
        ",".join(HEADER) + "\ntreatments_given,SRC-A04,c,f,s\ntreatments_given,SRC-A05,c,other,s\n",
        "table,_row_id,cluster_id,error_family,error_family\ntreatments_given,SRC-A04,c,f,s\n",
        ",".join(HEADER) + '\n"unclosed',
        ",".join(HEADER) + "\ntreatments_given,SRC-A04,c,f, \n",
    ],
)
def test_invalid_labels_are_grader_input_errors_before_execution(
    adapter, inputs, monkeypatch, data
):
    inputs[1].write_text(data)
    monkeypatch.setattr(
        adapter, "_load_verifier", lambda path: pytest.fail("invalid labels executed")
    )
    result = adapter.run_upstream_verifier(*inputs, turn_count=2)
    assert result["status"] == "invalid_labels"
    assert result["upstream_reward"] is None
    assert result["attempted_evaluations"] == 0
    assert (inputs[2] / "inputs/labels.csv").read_bytes() == inputs[1].read_bytes()


def test_missing_labels_are_not_agent_failure(adapter, inputs):
    inputs[1].unlink()
    result = adapter.run_upstream_verifier(*inputs, turn_count=2)
    assert result["status"] == "invalid_labels"
    assert result["upstream_reward"] is None


def test_stub_execution_snapshots_and_override_not_ambient(
    adapter, inputs, stub_loader, monkeypatch
):
    monkeypatch.setenv("AGENT_TURN_COUNT", "999")
    result = adapter.run_upstream_verifier(*inputs, turn_count=0)
    assert result["status"] == "completed"
    assert result["attempted_evaluations"] == 1
    assert result["metrics"]["turn_count"] == result["declared_turn_count"] == 0
    assert stub_loader[0][3] == 0
    assert stub_loader[0][0] == inputs[2] / "inputs/submission.csv"
    assert stub_loader[0][1] == inputs[2] / "inputs/labels.csv"
    assert result["provenance"]["pandas_version"] == "unit-test-stub-no-runtime"
    assert result["provenance"]["source_sha256"] == SOURCE_SHA
    for relative, digest in result["artifacts"].items():
        assert hashlib.sha256((inputs[2] / relative).read_bytes()).hexdigest() == digest
    assert result["clinical_assessment"] is False
    assert result["persistence_assessment"] is False
    assert result["official_benchmark_result"] is False


def test_grader_exception_retains_partial_artifact_and_null_reward(
    adapter, inputs, stub_loader, monkeypatch
):
    def broken(submission, labels, logs, turn_count_override):
        logs.mkdir()
        (logs / "reward.txt").write_text("1.000000\n")
        raise RuntimeError("grader exploded after partial output")

    monkeypatch.setattr(adapter, "_load_verifier", lambda path: SimpleNamespace(evaluate=broken))
    result = adapter.run_upstream_verifier(*inputs, turn_count=3)
    assert result["status"] == "grader_error"
    assert result["upstream_reward"] is None
    assert result["attempted_evaluations"] == 1
    assert "upstream/reward.txt" in result["artifacts"]


@pytest.mark.parametrize("fault", ["wrong_turn", "wrong_reward", "nonfinite", "duplicate_keys"])
def test_invalid_grader_outputs_are_not_usable_metrics(
    adapter, inputs, stub_loader, monkeypatch, fault
):
    def broken(submission, labels, logs, turn_count_override):
        logs.mkdir()
        metric = {"reward": 1.0, "turn_count": 3 if fault == "wrong_turn" else turn_count_override}
        raw = json.dumps(metric)
        if fault == "nonfinite":
            raw = '{"reward": 1.0, "turn_count": 2, "recall": NaN}'
        if fault == "duplicate_keys":
            raw = '{"reward": 0.0, "reward": 1.0, "turn_count": 2}'
        (logs / "metrics.json").write_text(raw)
        (logs / "reward.txt").write_text("0.000000\n" if fault == "wrong_reward" else "1.000000\n")
        return 1.0

    monkeypatch.setattr(adapter, "_load_verifier", lambda path: SimpleNamespace(evaluate=broken))
    result = adapter.run_upstream_verifier(*inputs, turn_count=2)
    assert result["status"] == "grader_error"
    assert result["upstream_reward"] is None


def real_pandas_or_skip():
    pytest.importorskip("pandas", reason="Optional actual-source execution requires pandas")


@pytest.mark.parametrize("row", ["SRC-A04", "SRC-A05"])
def test_real_unchanged_verifier_accepts_either_source_in_cluster(adapter, inputs, row):
    real_pandas_or_skip()
    inputs[0].write_text(f"table,_row_id\ntreatments_given,{row}\n")
    result = adapter.run_upstream_verifier(*inputs, turn_count=9)
    assert result["status"] == "completed"
    assert result["upstream_reward"] == 1.0
    assert result["metrics"]["n_label_rows"] == 2
    assert result["metrics"]["n_clusters"] == result["metrics"]["n_clusters_caught"] == 1
    assert result["metrics"]["turn_count"] == 9
    assert result["metrics"]["precision_threshold"] == 0.01


@pytest.mark.parametrize("submission", [None, "wrong,columns\nx,y\n", 'table,_row_id\n"unclosed'])
def test_real_malformed_submission_retains_upstream_zero_and_error(adapter, inputs, submission):
    real_pandas_or_skip()
    if submission is None:
        inputs[0].unlink()
    else:
        inputs[0].write_text(submission)
    result = adapter.run_upstream_verifier(*inputs, turn_count=2)
    assert result["status"] == "invalid_submission"
    assert result["upstream_reward"] == 0.0
    assert (inputs[2] / "upstream/verifier_error.txt").is_file()
    assert result["metrics"]["n_clusters"] == 1
    assert result["metrics"]["n_clusters_caught"] == 0


def test_real_valid_empty_submission_is_measured_failure(adapter, inputs):
    real_pandas_or_skip()
    inputs[0].write_text("table,_row_id\n")
    result = adapter.run_upstream_verifier(*inputs, turn_count=1)
    assert result["status"] == "completed"
    assert result["upstream_reward"] == 0.0
    assert result["metrics"]["n_flagged_rows"] == 0


def test_real_duplicates_collapse_and_one_percent_floor_is_preserved(adapter, inputs):
    real_pandas_or_skip()
    inputs[0].write_text(
        "table,_row_id\n"
        + "treatments_given,SRC-A04\n" * 2
        + "".join(f"other,noise-{i}\n" for i in range(99))
    )
    result = adapter.run_upstream_verifier(*inputs, turn_count=4)
    assert result["status"] == "completed"
    assert result["upstream_reward"] == 1.0
    assert result["metrics"]["n_flagged_rows"] == 100
    assert result["metrics"]["precision"] == 0.01


def test_artifact_hash_failure_preserves_executed_denominator_and_raw_outputs(
    adapter, inputs, stub_loader, monkeypatch
):
    original = Path.read_bytes
    failed_path = inputs[2] / "upstream/reward.txt"

    def unreadable_artifact(path):
        if path == failed_path:
            raise OSError("simulated final artifact read failure")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", unreadable_artifact)
    result = adapter.run_upstream_verifier(*inputs, turn_count=6)
    assert result["status"] == "provenance_error"
    assert result["upstream_reward"] is None
    assert result["metrics"] is None
    assert result["attempted_evaluations"] == result["scheduled_evaluations"] == 1
    assert result["inputs"]["labels"]["rows"] == 2
    assert result["artifact_errors"][0]["path"] == "upstream/reward.txt"
    assert failed_path.read_text() == "1.000000\n"
    assert "upstream/metrics.json" in result["artifacts"]
    assert json.loads((inputs[2] / "report.json").read_text()) == result


def test_started_journal_records_attempt_before_verifier_dispatch(
    adapter, inputs, stub_loader, monkeypatch
):
    def interrupted(submission, labels, logs, turn_count_override):
        journal = json.loads((inputs[2] / "report.json").read_text())
        assert journal["attempted_evaluations"] == 1
        assert journal["declared_turn_count"] == turn_count_override == 3
        assert journal["inputs"]["labels"]["rows"] == 2
        raise RuntimeError("simulation of verifier failure")

    monkeypatch.setattr(
        adapter, "_load_verifier", lambda path: SimpleNamespace(evaluate=interrupted)
    )
    result = adapter.run_upstream_verifier(*inputs, turn_count=3)
    assert result["error"]["message"] == "simulation of verifier failure"
    assert result["status"] == "grader_error"
