"""Ungraded profiles cannot become historical pass rates or paper metrics."""

from __future__ import annotations

import json
import logging

import pytest

from healthcraft.llm.planner import _load_historical_pass_rates


def _entry(**changes):
    return {
        "task_id": "CC-022",
        "model": "local",
        "category": "clinical_communication",
        "passed": True,
        "reward": 1.0,
        "safety_gate_passed": True,
        **changes,
    }


def _save_entries(root, entries):
    (root / "experiments.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8"
    )


MARKERS = [
    {"scenario_profile": "roster-observations/v1"},
    {"grading_complete": False},
    {"benchmark_comparable": False},
    {"evaluation_mode": "profile_diagnostic"},
    {"benchmark_score": None},
    {"ungraded_criteria": 1},
    {"metadata": {"scenario_context": {"profile_version": "roster-observations/v1"}}},
]


@pytest.mark.parametrize("marker", MARKERS)
def test_planner_excludes_explicitly_unassessed_observations_with_diagnostic_log(
    tmp_path, caplog, marker
):
    _save_entries(tmp_path, [_entry(passed=False, reward=0.0), _entry(**marker)])
    with caplog.at_level(logging.WARNING, logger="healthcraft.planner"):
        rates = _load_historical_pass_rates(tmp_path)
    assert rates == {"CC-022": 0.0}
    assert "unassessed" in caplog.text.lower() and "CC-022" in caplog.text


def test_latest_unassessed_attempt_does_not_resurrect_older_benchmark_grade(tmp_path):
    path = "trajectories/clinical_communication/CC-022_local_42_t1.json"
    _save_entries(
        tmp_path,
        [
            _entry(trajectory_path=path),
            _entry(trajectory_path=path.replace(".json", "_attempt2.json"), grading_complete=False),
        ],
    )
    assert _load_historical_pass_rates(tmp_path) == {}


def test_planner_preserves_legacy_assessed_rates_and_fail_closed_error_trials(tmp_path):
    _save_entries(tmp_path, [_entry(), _entry(passed=False, reward=0.0, error="runtime error")])
    assert _load_historical_pass_rates(tmp_path) == {"CC-022": 0.5}


@pytest.fixture
def paper():
    pytest.importorskip("matplotlib")
    from scripts import generate_paper_figures

    return generate_paper_figures


@pytest.mark.parametrize("marker", MARKERS)
def test_paper_entry_loading_rejects_instead_of_dropping_unassessed_denominator(
    tmp_path, paper, marker
):
    _save_entries(tmp_path, [_entry(), _entry(**marker)])
    with pytest.raises(ValueError, match="unassessed"):
        paper.load_entries(tmp_path)


@pytest.mark.parametrize("metric", ["overall_pass_rate", "overall_avg_reward"])
def test_paper_numeric_summary_cannot_hide_unassessed_experiment_rows(tmp_path, paper, metric):
    _save_entries(tmp_path, [_entry(scenario_profile="roster-observations/v1")])
    (tmp_path / "summary.json").write_text(json.dumps({"pass_rate": 1.0, "avg_reward": 1.0}))
    with pytest.raises(ValueError, match="unassessed"):
        getattr(paper, metric)(tmp_path)


@pytest.mark.parametrize("filename", ["summary.json", "summary-2.json", "summary-10.json"])
def test_paper_assessed_entries_cannot_hide_any_unassessed_summary(tmp_path, paper, filename):
    _save_entries(tmp_path, [_entry()])
    (tmp_path / "summary.json").write_text(json.dumps({"pass_rate": 1.0, "avg_reward": 1.0}))
    (tmp_path / filename).write_text(
        json.dumps({"pass_rate": None, "avg_reward": None, "evaluation_mode": "profile_diagnostic"})
    )
    for reader in (paper.load_entries, paper.overall_pass_rate, paper.overall_avg_reward):
        with pytest.raises(ValueError, match="unassessed"):
            reader(tmp_path)


def test_paper_direct_category_aggregation_rejects_unassessed_entries(paper):
    with pytest.raises(ValueError, match="unassessed"):
        paper.per_category_pass_rate([_entry(), _entry(benchmark_comparable=False)])


@pytest.mark.parametrize(
    "metric,key", [("overall_pass_rate", "pass_rate"), ("overall_avg_reward", "avg_reward")]
)
def test_null_summary_metric_is_unknown_not_zero(tmp_path, paper, metric, key):
    (tmp_path / "summary.json").write_text(json.dumps({key: None}))
    with pytest.raises(ValueError, match=key):
        getattr(paper, metric)(tmp_path)


def test_null_reward_entry_is_rejected_without_summary(tmp_path, paper):
    _save_entries(tmp_path, [_entry(reward=None)])
    with pytest.raises(ValueError, match="reward"):
        paper.overall_avg_reward(tmp_path)


def test_legacy_paper_metrics_remain_unchanged_and_read_only(tmp_path, paper):
    _save_entries(tmp_path, [_entry(), _entry(passed=False, reward=0.0)])
    before = {path: path.read_bytes() for path in tmp_path.iterdir()}
    assert paper.overall_pass_rate(tmp_path) == 0.5
    assert paper.overall_avg_reward(tmp_path) == 0.5
    assert paper.per_category_pass_rate(paper.load_entries(tmp_path)) == {
        "clinical_communication": (1, 2)
    }
    assert {path: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_paper_main_checks_all_pilots_before_any_figure_work(tmp_path, paper, monkeypatch):
    results = tmp_path / "input"
    later_pilot = results / "pilot-v3-gpt54"
    later_pilot.mkdir(parents=True)
    _save_entries(later_pilot, [_entry(grading_complete=False)])
    output = tmp_path / "not-created"
    monkeypatch.setattr(paper, "RESULTS", results)
    monkeypatch.setattr(paper, "FIGURES", output)
    monkeypatch.setattr(paper, "figure_3_per_category", lambda: pytest.fail("figure work began"))
    with pytest.raises(ValueError, match="unassessed"):
        paper.main()
    assert not output.exists()
