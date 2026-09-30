"""The offline roster retains each attempt without upgrading failed evidence."""

import hashlib
import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BOOK = ROOT / "configs/evaluation/reconciliation_v2/casebook.json"
PIN = "39f8bcbc16e011cf10b79c78c70e39cf165b44d245fb92417f9688972d0d5cdb"
AXES = ("provenance", "source_fidelity", "persisted_action", "readback", "execution_complete")
EXPECTED = ["TTTTT", "TFFFT", "TFFFT", "TTFFT", "TTFFT", "TFFFT", "TTTFF", "FFFFF"]


def api():
    return importlib.import_module("healthcraft.reconciliation.casebook_runner")


def read(path):
    return json.loads(path.read_text())


def tree_hashes(root):
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


def test_default_full_roster_exact_files_and_faithful_control_patterns(tmp_path):
    output = tmp_path / "new-evidence"
    result = api().run_casebook(output)
    assert result == read(output / "manifest.json")
    assert result["schema_version"] == "healthcraft-reconciliation-casebook-run/v2"
    assert result["status"] == "completed"
    assert result["counts"] == {
        "scheduled": 16,
        "attempted": 16,
        "recorded": 16,
        "matched": 16,
        "mismatched": 0,
        "errors": 0,
    }
    assert result["purpose"] == "development_controls"
    assert result["clinical_validated"] is False and result["benchmark_score"] is None
    assert result["model_calls"] == 0 and result["sources_unchanged"] is True
    assert result["casebook_sha256"] == PIN
    assert len(result["roster"]) == len(result["outcomes"]) == 16
    actual = tree_hashes(output)
    actual.pop("manifest.json")
    assert actual == result["files"]
    identity = read(output / "source-identity.json")
    assert "src/healthcraft/reconciliation/casebook_runner.py" in identity["before"]
    assert "configs/mcp-tools.json" in identity["before"]
    assert "scripts/reconciliation_casebook.py" in identity["before"]
    assert identity["before"] == identity["after"]
    for index in range(1, 9):
        cid = f"REC2-{index:03d}"
        case = read(output / cid / "case.json")
        assert case["case_id"] == cid and case["casebook_sha256"] == PIN
        for arm in ("reference", "designated"):
            folder = output / cid / arm
            evidence, verdict = read(folder / "execution.json"), read(folder / "verification.json")
            control = read(folder / "control.json")
            assert "evidence" not in control and "original_evidence" not in control
            assert control["model_calls"] == 0
            pattern = "".join("T" if verdict["checks"][k] else "F" for k in AXES)
            assert pattern == ("TTTTT" if arm == "reference" else EXPECTED[index - 1])
            assert evidence["case_binding"]["case_id"] == cid
            assert read(folder / "attempt.json")["matched"] is True
            if cid == "REC2-008" and arm == "designated":
                original = read(folder / "original-execution.json")
                events = [
                    json.loads(line) for line in (folder / "journal.jsonl").read_text().splitlines()
                ]
                assert evidence["after"] is None and original["after"] is not None
                assert events[-1]["call"]["response"] == original["calls"][-1]["response"]
                assert control["capture_transformation"]["actual_execution_interrupted"] is False
            else:
                assert not (folder / "original-execution.json").exists()


@pytest.mark.parametrize("mode", ["reference", "designated"])
def test_selected_cases_are_deterministic_and_one_attempt_per_selected_mode(tmp_path, mode):
    result = api().run_casebook(tmp_path / "out", case_ids=["REC2-003", "REC2-001"], mode=mode)
    assert result["counts"]["scheduled"] == result["counts"]["matched"] == 2
    assert [(r["case_id"], r["mode"]) for r in result["roster"]] == [
        ("REC2-001", mode),
        ("REC2-003", mode),
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"case_ids": []},
        {"case_ids": [""]},
        {"case_ids": [" REC2-001"]},
        {"case_ids": ["REC2-001", "REC2-001"]},
        {"case_ids": ["REC2-999"]},
        {"case_ids": "REC2-001"},
        {"case_ids": [None]},
        {"mode": "unknown"},
        {"casebook_path": BOOK},
        {"casebook_path": BOOK, "expected_sha256": "0" * 64},
    ],
)
def test_preflight_rejection_creates_no_output_or_attempts(tmp_path, monkeypatch, kwargs):
    module = api()
    calls = []
    monkeypatch.setattr(module, "run_control", lambda *a, **k: calls.append(k))
    with pytest.raises(ValueError):
        module.run_casebook(tmp_path / "out", **kwargs)
    assert not (tmp_path / "out").exists() and calls == []


def test_unselected_corrupt_case_rejects_before_first_run(tmp_path, monkeypatch):
    root = tmp_path / "book"
    shutil.copytree(BOOK.parent, root)
    (root / "REC2-008/scenario.json").write_text("{}")
    called = []
    monkeypatch.setattr(api(), "run_control", lambda *a, **k: called.append(k))
    with pytest.raises(ValueError):
        api().run_casebook(
            tmp_path / "output",
            casebook_path=root / "casebook.json",
            expected_sha256=PIN,
            case_ids=["REC2-001"],
        )
    assert not called and not (tmp_path / "output").exists()


@pytest.mark.parametrize("alias", [False, True])
def test_output_within_casebook_rejected_including_parent_alias(tmp_path, alias):
    source = tmp_path / "book"
    shutil.copytree(BOOK.parent, source)
    root = source
    if alias:
        root = tmp_path / "alias"
        root.symlink_to(source, target_is_directory=True)
    before = tree_hashes(source)
    with pytest.raises(ValueError, match="inside|within|contain"):
        api().run_casebook(
            root / "new", casebook_path=source / "casebook.json", expected_sha256=PIN
        )
    assert tree_hashes(source) == before


@pytest.mark.parametrize("kind", ["directory", "file", "dangling_symlink"])
def test_existing_output_is_never_modified(tmp_path, kind):
    output = tmp_path / "out"
    if kind == "directory":
        output.mkdir()
        (output / "prior").write_text("original")
    elif kind == "file":
        output.write_text("original")
    else:
        output.symlink_to(tmp_path / "absent", target_is_directory=True)
    with pytest.raises(OSError):
        api().run_casebook(output, case_ids=["REC2-001"])
    if kind == "directory":
        assert (output / "prior").read_text() == "original"
    elif kind == "file":
        assert output.read_text() == "original"
    else:
        assert output.is_symlink() and not (tmp_path / "absent").exists()


def test_control_exception_retains_attempt_journal_and_remaining_roster(tmp_path, monkeypatch):
    module = api()
    actual = module.run_control
    seen = []

    def interrupted(case, **kwargs):
        seen.append((case["case_id"], kwargs["control"]))
        result = actual(case, **kwargs)
        if len(seen) == 1:
            raise RuntimeError("receipt construction interrupted after actual execution")
        return result

    monkeypatch.setattr(module, "run_control", interrupted)
    output = tmp_path / "out"
    result = module.run_casebook(output)
    assert len(seen) == 16 and len(result["outcomes"]) == 16
    assert result["counts"]["errors"] == 1 and result["counts"]["matched"] == 15
    failed = output / "REC2-001/reference"
    assert read(failed / "error.json")["type"] == "RuntimeError"
    assert len((failed / "journal.jsonl").read_text().splitlines()) == 20
    assert not (failed / "execution.json").exists()
    assert result["outcomes"][0]["matched"] is False


def test_grader_exception_does_not_erase_successfully_captured_execution(tmp_path, monkeypatch):
    module = api()
    actual = module.verify_case
    seen = []

    def fail_once(case, evidence):
        seen.append(case["case_id"])
        if len(seen) == 1:
            raise RuntimeError("grading unavailable")
        return actual(case, evidence)

    monkeypatch.setattr(module, "verify_case", fail_once)
    result = module.run_casebook(tmp_path / "out", case_ids=["REC2-001", "REC2-002"])
    assert len(seen) == 4 and result["counts"]["errors"] == 1
    folder = tmp_path / "out/REC2-001/reference"
    assert read(folder / "execution.json")["completion"]["status"] == "completed"
    assert read(folder / "control.json")["control"] == "valid"
    assert read(folder / "error.json")["stage"] == "verification"


@pytest.mark.parametrize(
    "mutation",
    ["wrong_boolean", "numeric_boolean", "wrong_status", "missing_axis", "mechanical_pass"],
)
def test_unexpected_or_malformed_verdict_is_not_a_matched_control(tmp_path, monkeypatch, mutation):
    module = api()
    actual = module.verify_case

    def changed(case, evidence):
        result = actual(case, evidence)
        if mutation == "wrong_boolean":
            result["checks"]["readback"] = False
        elif mutation == "numeric_boolean":
            result["checks"]["readback"] = 1
        elif mutation == "wrong_status":
            result["status"] = "provenance_error"
        elif mutation == "missing_axis":
            del result["checks"]["readback"]
        else:
            result["mechanical_passed"] = False
        return result

    monkeypatch.setattr(module, "verify_case", changed)
    result = module.run_casebook(tmp_path / "out", case_ids=["REC2-001"], mode="reference")
    assert result["status"] == "mismatch"
    assert result["counts"]["matched"] == 0 and result["counts"]["mismatched"] == 1
    assert result["outcomes"][0]["matched"] is False


def test_source_inventory_drift_and_hash_failure_never_certify(tmp_path, monkeypatch):
    module = api()
    actual = module._source_hashes
    before = actual()
    calls = []

    def drift():
        calls.append(1)
        return before if len(calls) == 1 else {**before, "src/new.py": "0" * 64}

    monkeypatch.setattr(module, "_source_hashes", drift)
    result = module.run_casebook(tmp_path / "changed", case_ids=["REC2-001"])
    assert result["status"] == "implementation_changed" and result["sources_unchanged"] is False
    assert result["development_controls_matched"] is False
    assert result["counts"]["matched"] == 2  # Historical actual controls still retained.
    calls.clear()

    def unavailable_after():
        calls.append(1)
        if len(calls) == 1:
            return before
        raise OSError("source read failed")

    monkeypatch.setattr(module, "_source_hashes", unavailable_after)
    result = module.run_casebook(tmp_path / "unreadable", case_ids=["REC2-001"])
    assert result["sources_unchanged"] is False
    assert read(tmp_path / "unreadable/source-identity.json")["error"]["type"] == "OSError"


def test_cli_runs_outside_repository_and_reports_preflight_errors(tmp_path):
    script = ROOT / "scripts/reconciliation_casebook.py"
    env = {"PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1"}
    command = [
        sys.executable,
        str(script),
        "--output-dir",
        str(tmp_path / "out"),
        "--case",
        "REC2-001",
        "--mode",
        "reference",
    ]
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["counts"]["scheduled"] == 1 and summary["benchmark_score"] is None
    again = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert again.returncode == 2
    assert json.loads(again.stderr)["error"]["type"] == "FileExistsError"
    invalid = subprocess.run(
        command[:-2] + ["--case", "REC2-001"], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert invalid.returncode == 2


@pytest.mark.parametrize("mutation", ["not_applied", "missing_original", "failed_original"])
def test_incomplete_capture_only_matches_a_verified_original_and_applied_omission(
    tmp_path, monkeypatch, mutation
):
    module = api()
    actual = module.run_control

    def changed(case, **kwargs):
        capture = actual(case, **kwargs)
        if mutation == "not_applied":
            capture["capture_transformation"] = {
                "kind": "not_applied",
                "reason": "original_capture_not_complete",
            }
        elif mutation == "missing_original":
            capture["original_evidence"] = None
        else:
            capture["original_evidence"]["completion"] = {
                "status": "failed",
                "error": {"type": "RuntimeError", "message": "original failed"},
            }
        return capture

    monkeypatch.setattr(module, "run_control", changed)
    result = module.run_casebook(tmp_path / "out", case_ids=["REC2-008"], mode="designated")
    assert result["counts"]["matched"] == 0
    assert result["development_controls_matched"] is False
    assert (
        read(tmp_path / "out/REC2-008/designated/verification.json")["status"] == "provenance_error"
    )
    if mutation == "failed_original":
        original = read(tmp_path / "out/REC2-008/designated/original-verification.json")
        assert original["mechanical_passed"] is False


def test_actual_incomplete_control_setup_failure_is_retained_as_error(tmp_path, monkeypatch):
    import healthcraft.reconciliation.case_controls as controls
    from healthcraft.reconciliation.execution_v2 import run_case

    def failed_case(case, **kwargs):
        def fail(recorder, *, target):
            recorder.call("getEncounterDetails", {"encounter_id": target["encounter_id"]})
            raise RuntimeError("actual original controller failed")

        return run_case(case, controller=fail, journal_path=kwargs["journal_path"])

    monkeypatch.setattr(controls, "run_case", failed_case)
    result = api().run_casebook(tmp_path / "out", case_ids=["REC2-008"], mode="designated")
    assert result["counts"]["errors"] == 1 and result["counts"]["matched"] == 0
    folder = tmp_path / "out/REC2-008/designated"
    assert (
        read(folder / "execution.json")["completion"]["error"]["message"]
        == "actual original controller failed"
    )
    assert read(folder / "control.json")["capture_transformation"]["kind"] == "not_applied"
    assert len((folder / "journal.jsonl").read_text().splitlines()) == 2


def test_per_run_io_failure_retains_roster_and_other_attempts(tmp_path, monkeypatch):
    module = api()
    actual = module._write

    def fail_one(path, value):
        if path.as_posix().endswith("REC2-001/reference/execution.json"):
            raise OSError("test output write failed")
        return actual(path, value)

    monkeypatch.setattr(module, "_write", fail_one)
    result = module.run_casebook(tmp_path / "out", case_ids=["REC2-001", "REC2-002"])
    assert result["counts"]["scheduled"] == result["counts"]["recorded"] == 4
    assert result["counts"]["errors"] == 1 and result["counts"]["matched"] == 3
    assert result["outcomes"][0]["status"] == "io_error"
    assert read(tmp_path / "out/REC2-001/reference/error.json")["stage"] == "capture_persistence"
    assert (tmp_path / "out/REC2-001/reference/journal.jsonl").is_file()


def test_cli_mismatch_exits_one_after_retaining_manifest(tmp_path, monkeypatch, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "casebook_cli_peer", ROOT / "scripts/reconciliation_casebook.py"
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    module = api()
    actual = module.verify_case

    def mismatch(case, evidence):
        verdict = actual(case, evidence)
        verdict["checks"]["readback"] = False
        return verdict

    monkeypatch.setattr(module, "verify_case", mismatch)
    result = cli.main(
        ["--output-dir", str(tmp_path / "out"), "--case", "REC2-001", "--mode", "reference"]
    )
    assert result == 1
    assert json.loads(capsys.readouterr().out)["counts"]["matched"] == 0
    assert (tmp_path / "out/manifest.json").is_file()
