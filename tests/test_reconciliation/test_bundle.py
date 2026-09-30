"""The review bundle must keep its declared denominator and raw evidence."""

import json

import pytest


def test_existing_output_directory_is_not_reused(tmp_path):
    from healthcraft.reconciliation.bundle import run_development_suite

    directory = tmp_path / "existing"
    directory.mkdir()
    marker = directory / "marker.txt"
    marker.write_text("original")
    with pytest.raises(FileExistsError):
        run_development_suite(directory)
    assert marker.read_text() == "original"
    assert list(directory.iterdir()) == [marker]


def test_report_retains_missing_scheduled_trial_and_escapes_content():
    from healthcraft.reconciliation.report import render_report

    bundle = {
        "schema_version": "healthcraft-reconciliation-suite/v1",
        "roster": [{"id": "<script>alert(1)</script>", "description": "Not run"}],
        "trials": [],
        "source_hashes_before": {},
        "source_hashes_after": {},
    }
    html = render_report(bundle)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "Missing evidence" in html
    assert "1 scheduled" in html
    assert "0 clinical criteria" in html
    assert "<script src=" not in html


def test_suite_writes_roster_before_any_trial_and_reports_all_controls(tmp_path, monkeypatch):
    import healthcraft.reconciliation.bundle as bundle_module

    actual_run = bundle_module.run_reconciliation_trial
    directory = tmp_path / "suite"
    seen = []

    def inspect_roster(*args, **kwargs):
        roster = json.loads((directory / "roster.json").read_text())
        assert len(roster) >= 8
        seen.append(roster)
        return actual_run(*args, **kwargs)

    monkeypatch.setattr(bundle_module, "run_reconciliation_trial", inspect_roster)
    bundle = bundle_module.run_development_suite(directory)
    assert len(seen) == len(bundle["roster"]) == len(bundle["trials"])
    assert bundle["development_controls_matched"] is True
    by_id = {trial["id"]: trial for trial in bundle["trials"]}
    assert by_id["reference"]["verification"]["mechanical_passed"] is True
    assert by_id["omitted_source"]["verification"]["mechanical_passed"] is False
    assert by_id["ack_without_persistence"]["verification"]["mechanical_passed"] is False
    assert by_id["interrupted_after_write"]["verification"]["checks"]["persisted_action"] is True
    assert by_id["interrupted_after_write"]["verification"]["checks"]["execution_complete"] is False
    for trial in bundle["trials"]:
        assert (directory / trial["id"] / "journal.jsonl").exists()
        assert (directory / trial["id"] / "evidence.json").exists()
        assert trial["upstream"]["status"] == "not_requested"
    assert (directory / "report.html").is_file()
    assert (directory / "manifest.json").is_file()
    assert bundle["model_calls"] == 0
    assert bundle["benchmark_score"] is None


def test_preparation_error_keeps_scheduled_trial_in_bundle(tmp_path, monkeypatch):
    import healthcraft.reconciliation.bundle as bundle_module

    def unavailable(*args, **kwargs):
        raise RuntimeError("fixture construction interrupted")

    monkeypatch.setattr(bundle_module, "run_reconciliation_trial", unavailable)
    bundle = bundle_module.run_development_suite(tmp_path / "suite")
    assert len(bundle["trials"]) == len(bundle["roster"]) >= 8
    assert bundle["development_controls_matched"] is False
    assert all(trial["status"] == "preparation_error" for trial in bundle["trials"])
    assert all(trial["verification"] is None for trial in bundle["trials"])


def test_requested_but_unavailable_upstream_is_explicitly_incomplete(tmp_path, monkeypatch):
    import healthcraft.reconciliation.upstream as upstream
    from healthcraft.reconciliation.bundle import run_development_suite

    monkeypatch.setattr(
        upstream,
        "run_upstream_verifier",
        lambda *args, **kwargs: {"status": "unavailable_dependency", "upstream_reward": None},
    )
    bundle = run_development_suite(tmp_path / "suite", upstream=True)
    assert bundle["development_controls_matched"] is True
    assert bundle["upstream_requested"] is True
    assert bundle["upstream_all_completed"] is False
    assert bundle["upstream_completed_count"] == 0


def test_report_shows_secondary_reward_beside_failed_note_checks():
    from healthcraft.reconciliation.report import render_report

    trial = {
        "id": "invented_administration",
        "description": "Invented care",
        "status": "completed",
        "verification": {"checks": {"source_fidelity": False}},
        "upstream": {"status": "completed", "upstream_reward": 1.0},
    }
    rendered = render_report({"roster": [trial], "trials": [trial]})
    assert "reward 1.0" in rendered
    assert "Not satisfied" in rendered
    assert 'href="invented_administration/evidence.json"' in rendered
