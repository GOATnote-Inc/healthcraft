"""Independent offline controls for bundle failure accounting and traceability."""

import json

from healthcraft.reconciliation import bundle as bundle_module


def one_reference(monkeypatch):
    monkeypatch.setattr(bundle_module, "ROSTER", (bundle_module.ROSTER[0],))


def test_verifier_failure_after_real_execution_is_not_a_preparation_error(tmp_path, monkeypatch):
    import healthcraft.reconciliation.oracle as oracle

    one_reference(monkeypatch)

    def unavailable(*args, **kwargs):
        raise RuntimeError("Independent verifier failed after execution")

    monkeypatch.setattr(oracle, "verify_reconciliation", unavailable)
    directory = tmp_path / "grader-failure"
    bundle = bundle_module.run_development_suite(directory)
    evidence = json.loads((directory / "reference/evidence.json").read_text())
    assert evidence["completion"]["status"] == "completed"
    assert len(evidence["after"]["entities"]["clinical_note"]) == 1
    assert len(evidence["calls"]) > 0
    assert len(bundle["trials"]) == len(bundle["roster"]) == 1
    assert bundle["trials"][0]["verification"] is None
    assert bundle["trials"][0]["status"] != "preparation_error"


def test_source_drift_is_visible_to_static_report_reader(tmp_path, monkeypatch):
    one_reference(monkeypatch)
    captured = iter([{"fixture.py": "before"}, {"fixture.py": "after"}])
    monkeypatch.setattr(bundle_module, "_hashes", lambda: next(captured))
    directory = tmp_path / "drift"
    bundle = bundle_module.run_development_suite(directory)
    assert bundle["sources_unchanged"] is False
    assert bundle["trials"][0]["verification"]["mechanical_passed"] is True
    report = (directory / "report.html").read_text()
    assert "Source identity changed" in report


def test_initial_source_hashes_survive_finalization_failure(tmp_path, monkeypatch):
    one_reference(monkeypatch)
    initial = {"fixture.py": "source-identity-before-the-only-trial"}
    reads = 0

    def hashes():
        nonlocal reads
        reads += 1
        if reads == 1:
            return initial
        raise OSError("Final source identity capture failed")

    monkeypatch.setattr(bundle_module, "_hashes", hashes)
    directory = tmp_path / "finalization-failure"
    bundle = bundle_module.run_development_suite(directory)
    saved_bundle = json.loads((directory / "bundle.json").read_text())
    assert saved_bundle == bundle
    assert bundle["sources_unchanged"] is False
    assert bundle["source_hashes_after"] is None
    assert bundle["source_identity_error"] == {
        "type": "OSError",
        "message": "Final source identity capture failed",
    }
    assert (directory / "report.html").is_file()
    assert (directory / "manifest.json").is_file()
    # Real completed action evidence is already durable; its execution-time
    # code identity must not have existed solely in lost coordinator memory.
    evidence = json.loads((directory / "reference/evidence.json").read_text())
    assert evidence["completion"]["status"] == "completed"
    assert (directory / "reference/trial.json").is_file()
    json_files = list(directory.rglob("*.json"))
    assert any(initial["fixture.py"] in path.read_text() for path in json_files)


def test_reference_has_one_note_and_no_outside_writes_as_review_control(tmp_path, monkeypatch):
    one_reference(monkeypatch)
    directory = tmp_path / "control"
    bundle = bundle_module.run_development_suite(directory)
    assert bundle["development_controls_matched"] is True
    evidence = json.loads((directory / "reference/evidence.json").read_text())
    notes = list(evidence["after"]["entities"]["clinical_note"].values())
    assert len(notes) == 1
    assert notes[0]["encounter_id"] == "ENC-AAAAAAAA"
    assert notes[0]["patient_id"] == "PAT-AAAAAAAA"
    for encounter_id in ("ENC-BBBBBBBB", "ENC-CCCCCCCC"):
        assert (
            evidence["before"]["entities"]["encounter"][encounter_id]
            == evidence["after"]["entities"]["encounter"][encounter_id]
        )


def test_negative_axis_does_not_match_when_its_evidence_has_invalid_provenance(
    tmp_path, monkeypatch
):
    import healthcraft.reconciliation.oracle as oracle

    actual_verify = oracle.verify_reconciliation

    def verify_one_corrupted_binding(scenario, expectations, evidence):
        # The omitted-source control's intended outcome is source_fidelity=False.
        # Invalid source identity must not be mistaken for that successfully
        # demonstrated negative result; leave every other control unchanged.
        note = next(iter(evidence["after"]["entities"]["clinical_note"].values()), None)
        if note and len(json.loads(note["content"])["observations"]) == 5:
            from copy import deepcopy

            evidence = deepcopy(evidence)
            evidence["scenario_sha256"] = "0" * 64
        return actual_verify(scenario, expectations, evidence)

    monkeypatch.setattr(oracle, "verify_reconciliation", verify_one_corrupted_binding)
    bundle = bundle_module.run_development_suite(tmp_path / "negative-provenance")
    by_id = {trial["id"]: trial for trial in bundle["trials"]}
    assert by_id["reference"]["control_matched"] is True
    corrupted = by_id["omitted_source"]
    assert corrupted["verification"]["status"] == "provenance_error"
    assert corrupted["verification"]["checks"]["source_fidelity"] is False
    assert corrupted["control_matched"] is False
    assert bundle["development_controls_matched"] is False
