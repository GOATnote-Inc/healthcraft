"""Evidence review must expose uncertainty and preserve immutable source records."""

from __future__ import annotations

import json
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

from healthcraft.llm.review_context import freeze_review_context, seal_review_context
from healthcraft.reporting import collect_evidence, render_evidence, write_evidence_report
from healthcraft.tasks.loader import Task
from healthcraft.trajectory import CriterionEvalResult, Trajectory


def trajectory(**changes):
    return {
        "task_id": "IR-002",
        "model": "ollama:local/model",
        "seed": 42,
        "turns": [
            {
                "role": "assistant",
                "content": "Retrieved history",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "name": "getPatientHistory",
                        "arguments": {"patient_id": "PAT-1"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "content": '{"status":"ok","encounter_ids":["ENC-1"]}',
            },
            {"role": "assistant", "content": "Retrieved ENC-1."},
        ],
        "criteria_results": [{"id": "IR-002-C01", "satisfied": True, "evidence": "ENC-1"}],
        "reward": 1.0,
        "passed": True,
        "safety_gate_passed": True,
        "error": None,
        "metadata": {"stop_reason": "stop"},
        **changes,
    }


def save(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_latest_retry_is_one_trial_with_all_attempts_available(tmp_path):
    name = "trajectories/ir/IR-002_ollama%2Fmodel_42_t3.json"
    original = save(tmp_path, name, trajectory(error="provider failure"))
    latest = save(tmp_path, name.replace(".json", "_attempt10.json"), trajectory())
    save(tmp_path, name.replace(".json", "_attempt2.json"), trajectory(error="retry failure"))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.json")}
    report = collect_evidence(tmp_path)
    assert report["counts"]["selected_trials"] == 1
    assert report["counts"]["raw_attempts"] == 3
    record = report["records"][0]
    assert record["path"] == str(latest.resolve())
    assert record["trial"] == 3 and record["attempt"] == 10
    assert record["status"] == "recorded_pass"
    assert str(original.resolve()) in record["attempt_paths"]
    assert {p: p.read_bytes() for p in tmp_path.rglob("*.json")} == before


@pytest.mark.parametrize("grading_complete", [True, False])
def test_experimental_profile_does_not_display_placeholders_as_scores(tmp_path, grading_complete):
    save(
        tmp_path,
        "run.json",
        trajectory(
            metadata={
                "stop_reason": "stop",
                "grading_complete": grading_complete,
                "scenario_context": {"profile_version": "roster-observations/v1"},
            }
        ),
    )
    report = collect_evidence(tmp_path)
    record = report["records"][0]
    assert record["completion"] == "complete"
    assert record["status"] == "incomplete"
    assert record["criteria"][0]["status"] == "ungraded"
    assert report["counts"]["recorded_pass"] == 0
    html = render_evidence(report)
    assert "roster-observations/v1" in html
    assert "Benchmark and safety outcomes: not assessed" in html
    assert "compatibility placeholders" in html
    assert "Recorded reward:" not in html


def test_corrupt_latest_never_resurrects_a_success(tmp_path):
    base = save(tmp_path, "IR-002_m_42_t1.json", trajectory())
    latest = base.with_stem(base.stem + "_attempt2")
    latest.write_text("{broken", encoding="utf-8")
    report = collect_evidence(tmp_path)
    assert len(report["records"]) == 1
    assert report["records"][0]["status"] == "invalid"
    assert report["counts"]["recorded_pass"] == 0
    assert "{broken" in render_evidence(report)


@pytest.mark.parametrize(
    "field,value",
    [
        ("passed", "true"),
        ("safety_gate_passed", 1),
        ("reward", True),
        ("reward", None),
        ("criteria_results", []),
        ("turns", None),
    ],
)
def test_invalid_or_missing_result_fields_cannot_appear_complete(tmp_path, field, value):
    save(tmp_path, "run.json", trajectory(**{field: value}))
    record = collect_evidence(tmp_path)["records"][0]
    assert record["status"] == "incomplete"
    assert record["issues"]


@pytest.mark.parametrize("verdict", ["false", "true", 0, 1, None, [], {}])
def test_criterion_verdicts_are_strict_json_booleans(tmp_path, verdict):
    save(
        tmp_path,
        "run.json",
        trajectory(criteria_results=[{"id": "C01", "satisfied": verdict, "evidence": "source"}]),
    )
    report = collect_evidence(tmp_path)
    assert report["records"][0]["status"] == "incomplete"
    assert report["counts"]["criterion_invalid"] == 1
    assert report["counts"]["criterion_failed"] == 0


def test_errors_abstentions_and_deferred_grading_are_not_rubric_failures(tmp_path):
    entries = [
        {"id": "C1", "satisfied": False, "evidence": "Clinical assertion unsatisfied"},
        {"id": "C2", "satisfied": False, "evidence": "Judge error: truncated response"},
        {"id": "C3", "satisfied": False, "evidence": "Disagreement", "abstained": True},
        {
            "id": "C4",
            "satisfied": False,
            "evidence": "LLM judge not yet implemented — criterion evaluation deferred",
        },
    ]
    save(tmp_path, "partial.json", trajectory(passed=False, criteria_results=entries))
    save(
        tmp_path,
        "error.json",
        trajectory(
            error="provider timeout",
            passed=False,
            safety_gate_passed=False,
            metadata={"failure_stage": "agent"},
        ),
    )
    report = collect_evidence(tmp_path)
    assert report["counts"]["criterion_failed"] == 1
    assert report["counts"]["criterion_error"] == 1
    assert report["counts"]["criterion_abstained"] == 1
    assert report["counts"]["criterion_ungraded"] == 2
    assert report["counts"]["error"] == 1
    error = next(r for r in report["records"] if r["status"] == "error")
    assert error["failure_stage"] == "agent"
    assert "not assessed" in error["safety_label"].lower()


def test_missing_and_duplicate_criteria_are_visible_and_coverage_is_not_invented(tmp_path):
    save(
        tmp_path,
        "run.json",
        trajectory(
            criteria_results=[
                {"id": "C1", "satisfied": True, "evidence": "source"},
                {"id": "C1", "satisfied": True},
            ]
        ),
    )
    record = collect_evidence(tmp_path)["records"][0]
    assert record["status"] == "incomplete"
    assert any("duplicate" in issue.lower() for issue in record["issues"])
    assert record["expected_criteria"] is None
    assert "expected total unavailable" in render_evidence(collect_evidence(tmp_path))


def test_latest_summary_is_context_not_a_replacement_for_missing_trials(tmp_path):
    save(tmp_path, "summary.json", {"total_runs": 1, "ungraded_criteria": 0})
    save(tmp_path, "summary-2.json", {"total_runs": 4, "ungraded_criteria": 3})
    save(tmp_path, "trajectories/run.json", trajectory())
    report = collect_evidence(tmp_path)
    assert len(report["summaries"]) == 1
    assert report["summaries"][0]["data"]["total_runs"] == 4
    assert report["counts"]["selected_trials"] == 1
    assert any("4" in issue and "1" in issue for issue in report["issues"])
    (tmp_path / "summary-2.json").write_text("{broken", encoding="utf-8")
    report = collect_evidence(tmp_path)
    assert report["summaries"][0]["error"]
    assert report["summaries"][0]["data"] is None


def test_diagnostic_artifacts_and_unknown_json_do_not_become_benchmark_trials(tmp_path):
    save(tmp_path, "smoke.json", {"kind": "local_integration_smoke", "passed": True})
    save(tmp_path, "certificate.json", {"verification": {"mechanical_passed": True}, "calls": []})
    save(tmp_path, "unknown.json", {"something": "retain me"})
    save(tmp_path, "run_grading.json", {"passed": True})
    report = collect_evidence(tmp_path)
    assert report["counts"]["selected_trials"] == 0
    assert len(report["records"]) == 3
    assert {r["status"] for r in report["records"]} == {"diagnostic", "unsupported"}
    assert "retain me" in render_evidence(report)


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_untrusted_content_is_text_not_html_or_executable_links(tmp_path):
    attack = '</pre><script>alert(1)</script><img src=x onerror="alert(2)">'
    path = save(
        tmp_path,
        "evidence #1.json",
        trajectory(
            task_id=attack,
            model=attack,
            turns=[{"role": "assistant", "content": attack}],
            criteria_results=[{"id": attack, "satisfied": False, "evidence": attack}],
            passed=False,
        ),
    )
    html = render_evidence(collect_evidence(tmp_path))
    parsed = Elements()
    parsed.feed(html)
    assert len([tag for tag, _ in parsed.tags if tag == "script"]) == 1
    assert not any(tag == "img" for tag, _ in parsed.tags)
    assert not any(name.startswith("on") for _, attrs in parsed.tags for name in attrs)
    assert any(attrs.get("href") == path.resolve().as_uri() for _, attrs in parsed.tags)
    assert attack not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "connect-src 'none'" in html
    assert "getPatientHistory" not in html  # replaced trace is not fabricated


def test_report_has_review_controls_trace_and_explicit_limitations(tmp_path):
    save(tmp_path, "run.json", trajectory())
    html = render_evidence(collect_evidence(tmp_path))
    for text in (
        "Status filter",
        "Criterion filter",
        "getPatientHistory",
        "ENC-1",
        "Raw source",
        "Tool calls",
        "IR-001-C03",
        "IR-002",
        "clinical readiness",
    ):
        assert text in html
    assert "<details" in html
    assert 'id="status-filter"' in html and 'id="criterion-filter"' in html
    assert "innerHTML" not in html


def test_output_is_exclusive_and_cli_exposes_malformed_input(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    (source / "broken.json").write_text("{broken", encoding="utf-8")
    output = tmp_path / "review.html"
    write_evidence_report(source, output)
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        write_evidence_report(source, output)
    assert output.read_bytes() == before
    script = Path(__file__).resolve().parents[1] / "scripts/build_evidence_report.py"
    result = subprocess.run(
        [sys.executable, str(script), str(source), "--output", str(output)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "already exists" in result.stderr.lower()


def test_empty_directory_is_explicit_not_a_success(tmp_path):
    report = collect_evidence(tmp_path)
    assert report["counts"]["selected_trials"] == 0
    assert any("No JSON" in issue for issue in report["issues"])
    assert "No evidence records" in render_evidence(report)


@pytest.mark.parametrize("metadata", [{}, {"stop_reason": "mystery"}, {"stop_reason": []}])
def test_unknown_completion_does_not_validate_a_recorded_pass(tmp_path, metadata):
    save(tmp_path, "run.json", trajectory(metadata=metadata))
    report = collect_evidence(tmp_path)
    record = report["records"][0]
    assert record["completion"] == "unknown"
    assert record["status"] == "incomplete"
    assert "Recorded reward" in render_evidence(report)
    assert "not assessed" in record["safety_label"].lower()


def test_complete_stop_with_unanswered_call_cannot_establish_completion(tmp_path):
    turns = trajectory()["turns"]
    del turns[1]
    save(tmp_path, "run.json", trajectory(turns=turns))
    record = collect_evidence(tmp_path)["records"][0]
    assert record["completion"] == "incomplete"
    assert any("unanswered" in issue.lower() for issue in record["issues"])


@pytest.mark.parametrize("payload", ['{"passed":true,"passed":false}', '{"reward":NaN}'])
def test_ambiguous_or_nonstandard_json_is_visible_as_invalid(tmp_path, payload):
    (tmp_path / "run.json").write_text(payload, encoding="utf-8")
    assert collect_evidence(tmp_path)["records"][0]["status"] == "invalid"


def test_planned_but_absent_trials_remain_visible(tmp_path):
    save(
        tmp_path,
        "summary.json",
        {
            "total_tasks": 3,
            "trials": 2,
            "total_runs": 1,
            "ungraded_criteria": 7,
            "grading_complete": False,
        },
    )
    save(tmp_path, "trajectories/run.json", trajectory())
    report = collect_evidence(tmp_path)
    assert any("6 planned" in issue for issue in report["issues"])
    assert "Reported ungraded criteria: 7" in render_evidence(report)


def test_empty_narrative_is_distinct_from_incomplete_tool_action(tmp_path):
    turns = trajectory()["turns"]
    turns[-1]["content"] = ""
    save(tmp_path, "run.json", trajectory(turns=turns))
    report = collect_evidence(tmp_path)
    assert report["records"][0]["completion"] == "complete"
    assert report["records"][0]["status"] == "recorded_pass"
    assert "no final narrative" in render_evidence(report).lower()


def test_identity_only_partial_checkpoint_is_an_incomplete_trial(tmp_path):
    save(tmp_path, "partial.json", {"task_id": "IR-002", "model": "local"})
    report = collect_evidence(tmp_path)
    assert report["counts"]["selected_trials"] == 1
    assert report["records"][0]["status"] == "incomplete"


def test_completed_roundtrips_can_reuse_provider_call_ids(tmp_path):
    turns = trajectory()["turns"]
    turns = turns[:2] + turns[:2] + turns[2:]
    save(tmp_path, "run.json", trajectory(turns=turns))
    record = collect_evidence(tmp_path)["records"][0]
    assert record["completion"] == "complete"


def test_duplicate_pending_ids_remain_ambiguous(tmp_path):
    turns = trajectory()["turns"]
    turns[0]["tool_calls"] *= 2
    save(tmp_path, "run.json", trajectory(turns=turns))
    assert collect_evidence(tmp_path)["records"][0]["completion"] == "unknown"


@pytest.mark.parametrize(
    "metadata",
    [
        {"stop_reason": "stop", "termination_kind": "provider_refusal"},
        {"stop_reason": "stop", "provider_refusal": "I cannot comply"},
        {"stop_reason": "stop", "termination_kind": []},
    ],
)
def test_contradictory_termination_metadata_is_not_verified_completion(tmp_path, metadata):
    save(tmp_path, "run.json", trajectory(metadata=metadata))
    record = collect_evidence(tmp_path)["records"][0]
    assert record["completion"] == "unknown"
    assert record["status"] == "incomplete"


def test_max_output_tokens_is_known_incomplete_termination(tmp_path):
    save(tmp_path, "run.json", trajectory(metadata={"stop_reason": "max_output_tokens"}))
    assert collect_evidence(tmp_path)["records"][0]["completion"] == "incomplete"


@pytest.mark.parametrize(
    "saved_verdict,evidence",
    [
        (
            True,
            # Actual CC-002-C05 evidence from acct-full-opus48-grok-v10.
            "[grok-4/v2] PARSE FAILURE (fail-closed): judge response was not valid JSON; "
            'defaulted satisfied=True via keyword scan. Raw: {\n  "class": "POSITIVE",\n  '
            '"satisfied": true,\n  "evidence_quote": "## CARDIOLOGY CONSULT — Henry Taylor, '
            "62M (MRN-A9C76B90)\\n**Urgency:** Urgent / same shift · **Consultant:** "
            "Dr. Amara Okafor (on-cal",
        ),
        (
            False,
            # Actual CC-003-C05 evidence from acct-pilot-opus48-v10.
            "[gpt-5.5/v2] PARSE FAILURE (fail-closed): judge response was not valid JSON; "
            "defaulted satisfied=False via keyword scan. Raw: ",
        ),
        (False, "PARSE FAILURE (fail-closed): expected a JSON object; satisfied must be a boolean"),
    ],
)
def test_historical_parse_failure_markers_are_errors_not_saved_verdicts(
    tmp_path, saved_verdict, evidence
):
    path = save(
        tmp_path,
        "run.json",
        trajectory(
            criteria_results=[{"id": "C01", "satisfied": saved_verdict, "evidence": evidence}]
        ),
    )
    before = path.read_bytes()
    report = collect_evidence(tmp_path)
    criterion = report["records"][0]["criteria"][0]
    assert criterion["status"] == "error"
    assert criterion["raw"]["satisfied"] is saved_verdict
    assert criterion["evidence"] == evidence
    assert report["counts"]["criterion_error"] == 1
    assert report["counts"]["criterion_passed"] == 0
    assert report["counts"]["criterion_failed"] == 0
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "evidence",
    [
        "The note quotes PARSE FAILURE (fail-closed): this is source text, not a grader error.",
        "[grok-4/v2] The agent corrected a PARSE FAILURE (fail-closed): mentioned in a note.",
        "PARSE FAILURE (fail-closed) was discussed by the agent.",
        "[grok-4/v2]\nPARSE FAILURE (fail-closed): not the historical prefix format.",
    ],
)
def test_parse_failure_marker_must_be_the_exact_anchored_grader_prefix(tmp_path, evidence):
    save(
        tmp_path,
        "run.json",
        trajectory(criteria_results=[{"id": "C01", "satisfied": True, "evidence": evidence}]),
    )
    assert collect_evidence(tmp_path)["records"][0]["criteria"][0]["status"] == "passed"


def captured_trajectory():
    criteria = tuple(
        {
            "id": f"CAPTURE-C{index}",
            "assertion": f"Synthetic condition {index}",
            "verification": "world_state",
            "dimension": "documentation_quality",
        }
        for index in (1, 2)
    )
    task = Task(
        id="CAPTURE",
        category="integration_diagnostic",
        level=1,
        title="Synthetic",
        description="Read the synthetic patient record",
        initial_state={},
        expected_tools=(),
        metadata={},
        criteria=criteria,
    )
    trace = Trajectory(
        task_id=task.id,
        model="synthetic-no-inference",
        seed=42,
        system_prompt="Synthetic source review",
    )
    trace.add_turn("user", task.description)
    trace.add_turn("assistant", "Recorded synthetic completion")
    trace.reward, trace.passed, trace.safety_gate_passed = 1.0, True, True
    trace.rubric_channel = "v8"
    trace.criteria_results = [
        CriterionEvalResult(id=criterion["id"], satisfied=True, evidence="Synthetic saved label")
        for criterion in criteria
    ]
    trace.metadata = {
        "stop_reason": "stop",
        "expected_criteria_count": 2,
        "grading_complete": True,
        "ungraded_criteria": 0,
        "checkpoint_identity": "synthetic-identity",
        "agent_tool_definitions": [],
        "scenario_context": {},
    }
    draft = freeze_review_context(
        task,
        list(criteria),
        rubric_channel="v8",
        scenario_context={},
        checkpoint_identity="synthetic-identity",
        grading_mode="benchmark",
    )
    trace.metadata["review_context"] = seal_review_context(draft, trace)
    return trace.to_dict()


@pytest.mark.parametrize(
    "location,marker,global_profile",
    [
        ("metadata", {"scenario_profile": "source-test/v1"}, True),
        ("top", {"scenario_profile": "source-test/v1"}, True),
        ("metadata", {"evaluation_mode": "profile_diagnostic"}, True),
        ("top", {"evaluation_mode": "profile_diagnostic"}, True),
        ("metadata", {"benchmark_score": None}, False),
        ("top", {"benchmark_score": None}, False),
        ("metadata", {"benchmark_comparable": False}, False),
        ("top", {"benchmark_comparable": False}, False),
        ("metadata", {"ungraded_criteria": 1}, False),
        ("top", {"ungraded_criteria": 1}, False),
        ("metadata", {"grading_complete": False}, False),
        ("top", {"grading_complete": False}, False),
    ],
)
def test_canonical_unassessed_markers_block_full_score_but_preserve_known_rows(
    tmp_path, location, marker, global_profile
):
    value = trajectory()
    (value["metadata"] if location == "metadata" else value).update(marker)
    path = save(tmp_path, "marked.json", value)
    original = path.read_bytes()
    report = collect_evidence(tmp_path)
    record = report["records"][0]
    assert report["counts"]["recorded_pass"] == 0
    assert record["assessment_limited"] is True
    assert record["criteria"][0]["status"] == ("ungraded" if global_profile else "passed")
    assert record["criteria"][0]["raw"]["satisfied"] is True
    html = render_evidence(report)
    assert "Recorded reward: 1.0" not in html
    assert '"reward": 1.0' not in html  # JSON is escaped in the raw-evidence section.
    assert "&quot;reward&quot;: 1.0" in html
    assert path.read_bytes() == original


def test_valid_capture_binds_exact_criterion_cohort_without_current_task_reads(
    tmp_path, monkeypatch
):
    value = captured_trajectory()
    save(tmp_path, "captured.json", value)
    monkeypatch.setattr(
        "healthcraft.tasks.loader.load_task", lambda *a, **kw: pytest.fail("No current task lookup")
    )
    report = collect_evidence(tmp_path)
    record = report["records"][0]
    assert record["status"] == "recorded_pass"
    assert record["provenance"] == "valid"
    assert record["criterion_coverage"]["expected_ids"] == ["CAPTURE-C1", "CAPTURE-C2"]
    assert record["criterion_coverage"]["status"] == "matches"
    assert "Captured provenance: valid" in render_evidence(report)


@pytest.mark.parametrize("mutation", ["hash", "turn", "task_id", "missing_payload", "incomplete"])
def test_present_invalid_capture_blocks_clean_pass_and_bound_criterion_counts(tmp_path, mutation):
    value = captured_trajectory()
    if mutation == "hash":
        value["metadata"]["review_context"]["sha256"] = "0" * 64
    elif mutation == "turn":
        value["turns"][-1]["content"] = "Changed clinical action claim"
    elif mutation == "task_id":
        value["task_id"] = "OTHER-TASK"
    elif mutation == "missing_payload":
        value["metadata"]["review_context"] = None
    else:
        from healthcraft.llm.review_context import context_digest

        capture = value["metadata"]["review_context"]
        capture["payload"]["capture_status"] = "incomplete"
        capture["sha256"] = context_digest(capture["payload"])
    save(tmp_path, "captured.json", value)
    report = collect_evidence(tmp_path)
    record = report["records"][0]
    assert record["provenance"] == "invalid"
    assert record["status"] == "incomplete"
    assert report["counts"]["recorded_pass"] == report["counts"]["criterion_passed"] == 0
    assert any("provenance" in issue.lower() for issue in record["issues"])
    assert "Recorded reward: 1.0" not in render_evidence(report)


@pytest.mark.parametrize(
    "mutation,missing,unexpected",
    [
        ("missing", ["CAPTURE-C2"], []),
        ("wrong_same_count", ["CAPTURE-C2"], ["OTHER-C2"]),
        ("extra", [], ["OTHER-C3"]),
        ("duplicate", ["CAPTURE-C2"], []),
    ],
)
def test_frozen_rubric_coverage_matches_ids_not_only_count(tmp_path, mutation, missing, unexpected):
    value = captured_trajectory()
    if mutation == "missing":
        value["criteria_results"].pop()
    elif mutation == "wrong_same_count":
        value["criteria_results"][1]["id"] = "OTHER-C2"
    elif mutation == "extra":
        value["criteria_results"].append(
            {"id": "OTHER-C3", "satisfied": True, "evidence": "unrelated"}
        )
    else:
        value["criteria_results"][1]["id"] = "CAPTURE-C1"
    save(tmp_path, "captured.json", value)
    report = collect_evidence(tmp_path)
    record = report["records"][0]
    assert record["provenance"] == "valid"
    assert record["criterion_coverage"]["status"] == "mismatch"
    assert record["criterion_coverage"]["missing_ids"] == missing
    assert record["criterion_coverage"]["unexpected_ids"] == unexpected
    assert record["status"] == "incomplete"
    assert record["expected_criteria"] == 2
    for criterion in record["criteria"]:
        if criterion["id"] in unexpected:
            assert criterion["status"] == "invalid"
    assert "Recorded reward: 1.0" not in render_evidence(report)


@pytest.mark.parametrize("count", [3, 0, -1, True, "2"])
def test_expected_count_metadata_cannot_override_frozen_criterion_set(tmp_path, count):
    value = captured_trajectory()
    value["metadata"]["expected_criteria_count"] = count
    save(tmp_path, "captured.json", value)
    record = collect_evidence(tmp_path)["records"][0]
    assert record["expected_criteria"] == 2
    assert record["status"] == "incomplete"
    assert any("expected_criteria_count" in issue for issue in record["issues"])


def test_partial_grading_retains_known_verdicts_and_reports_disagreement(tmp_path):
    value = captured_trajectory()
    value["metadata"]["ungraded_criteria"] = 1
    save(tmp_path, "captured.json", value)
    report = collect_evidence(tmp_path)
    record = report["records"][0]
    assert record["status"] == "incomplete"
    assert report["counts"]["criterion_passed"] == 2
    assert any(
        "ungraded_criteria" in issue and "disagree" in issue.lower() for issue in record["issues"]
    )
    assert "Recorded reward: 1.0" not in render_evidence(report)


def test_absent_legacy_context_is_explicitly_unknown_not_reconstructed(tmp_path):
    save(tmp_path, "legacy.json", trajectory())
    report = collect_evidence(tmp_path)
    record = report["records"][0]
    assert record["provenance"] == "unknown"
    assert record["criterion_coverage"]["status"] == "unknown"
    assert record["status"] == "recorded_pass"
    assert "Captured provenance: unknown" in render_evidence(report)


@pytest.mark.parametrize("mutation", [None, "turn", "hash", "task_id"])
def test_actual_saved_5cd2955_local_probe_capture_and_mutants_remain_unassessed(tmp_path, mutation):
    root = Path(__file__).resolve().parents[1]
    source = root / "artifacts/local-order-probe/20260930/order-transport-v1/trajectory.json"
    before = source.read_bytes()
    value = json.loads(before)
    if mutation == "turn":
        value["turns"][-1]["content"] += " Changed saved action."
    elif mutation == "hash":
        value["metadata"]["review_context"]["sha256"] = "0" * 64
    elif mutation == "task_id":
        value["task_id"] = "OTHER-TASK"
    save(tmp_path, "real_saved_copy.json", value)
    report = collect_evidence(tmp_path)
    record = report["records"][0]
    assert record["provenance"] == ("valid" if mutation is None else "invalid")
    assert report["counts"]["recorded_pass"] == report["counts"]["criterion_passed"] == 0
    assert record["assessment_limited"] is True
    assert source.read_bytes() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("ungraded_criteria", True),
        ("ungraded_criteria", -1),
        ("ungraded_criteria", "0"),
        ("grading_complete", "true"),
        ("grading_complete", 1),
    ],
)
def test_malformed_legacy_grading_metadata_cannot_appear_assessed(tmp_path, field, value):
    data = trajectory()
    data["metadata"][field] = value
    save(tmp_path, "legacy.json", data)
    record = collect_evidence(tmp_path)["records"][0]
    assert record["status"] == "incomplete"
    assert any(field in issue for issue in record["issues"])
    assert record["criteria"][0]["status"] == "passed"
    assert "Recorded reward: 1.0" not in render_evidence(collect_evidence(tmp_path))


def test_partial_frozen_coverage_keeps_valid_judgment_separate_from_ungraded_row(tmp_path):
    data = captured_trajectory()
    data["metadata"].update(grading_complete=False, ungraded_criteria=1)
    data["criteria_results"][1].update(satisfied=False, graded=False)
    save(tmp_path, "partial.json", data)
    report = collect_evidence(tmp_path)
    record = report["records"][0]
    assert record["criterion_coverage"]["status"] == "matches"
    assert record["status"] == "incomplete"
    assert report["counts"]["criterion_passed"] == 1
    assert report["counts"]["criterion_ungraded"] == 1
    assert not any("disagrees" in issue for issue in record["issues"])


def test_valid_captured_profile_mode_blocks_legacy_placeholder_verdicts(tmp_path):
    from healthcraft.llm.review_context import context_digest

    data = captured_trajectory()
    context = data["metadata"]["review_context"]
    context["payload"]["grading_mode"] = "profile_diagnostic"
    context["sha256"] = context_digest(context["payload"])
    data["metadata"].update(grading_complete=False, ungraded_criteria=2)
    save(tmp_path, "profile.json", data)
    report = collect_evidence(tmp_path)
    record = report["records"][0]
    assert record["provenance"] == "valid"
    assert record["unvalidated_profile"] is True
    assert report["counts"]["criterion_ungraded"] == 2
    assert report["counts"]["criterion_passed"] == 0


@pytest.mark.parametrize(
    "execution_error,criteria,expected_criterion_error_trials,expected_status",
    [
        (
            None,
            [
                {
                    "id": "C1",
                    "satisfied": False,
                    "evidence": "Judge error: unavailable",
                    "error": "unavailable",
                }
            ],
            1,
            "incomplete",
        ),
        (
            None,
            [
                {"id": "C1", "satisfied": False, "evidence": "Judge error: unavailable"},
                {
                    "id": "C2",
                    "satisfied": False,
                    "evidence": "PARSE FAILURE (fail-closed): malformed",
                },
            ],
            1,
            "incomplete",
        ),
        (
            "provider timeout",
            [{"id": "C1", "satisfied": False, "evidence": "Not graded", "graded": False}],
            0,
            "error",
        ),
        (
            "provider timeout",
            [{"id": "C1", "satisfied": False, "evidence": "Judge error: unavailable"}],
            1,
            "error",
        ),
        (
            None,
            [
                {"id": "C1", "satisfied": False, "evidence": "Not graded", "graded": False},
                {"id": "C2", "satisfied": False, "evidence": "Abstained", "abstained": True},
            ],
            0,
            "incomplete",
        ),
        (None, [], 0, "incomplete"),
    ],
)
def test_trajectory_and_unique_trial_criterion_errors_are_separate(
    tmp_path, execution_error, criteria, expected_criterion_error_trials, expected_status
):
    save(
        tmp_path,
        "run.json",
        trajectory(error=execution_error, passed=False, reward=0, criteria_results=criteria),
    )
    report = collect_evidence(tmp_path)
    assert report["counts"]["selected_trials"] == 1
    assert report["records"][0]["status"] == expected_status
    assert report["counts"]["error"] == int(execution_error is not None)
    assert report["counts"]["trials_with_criterion_errors"] == expected_criterion_error_trials
    assert report["counts"]["rubric_fail"] == report["counts"]["criterion_failed"] == 0
    html = render_evidence(report)
    assert "Execution / grader errors" not in html
    assert f"<b>{int(execution_error is not None)}</b>Trajectory errors" in html
    assert f"<b>{expected_criterion_error_trials}</b>Trials with criterion errors" in html
    assert "Trajectory-error and criterion-error trial counts can overlap" in html
    assert "each selected trial is counted once in each error category." in html


def test_criterion_error_trial_count_uses_selected_trajectory_only(tmp_path):
    failed = trajectory(
        passed=False,
        criteria_results=[{"id": "C1", "satisfied": False, "evidence": "Judge error: unavailable"}],
    )
    save(tmp_path, "trajectories/IR-002_model_42_t1.json", failed)
    save(tmp_path, "trajectories/IR-002_model_42_t1_attempt2.json", trajectory())
    save(
        tmp_path,
        "diagnostic.json",
        {"kind": "diagnostic", "criteria_results": failed["criteria_results"]},
    )
    report = collect_evidence(tmp_path)
    assert report["counts"]["selected_trials"] == 1
    assert report["counts"]["raw_attempts"] == 2
    assert report["counts"]["recorded_pass"] == 1
    assert report["counts"]["diagnostic"] == 1
    assert report["counts"]["trials_with_criterion_errors"] == 0


def test_empty_report_has_zero_observed_error_counts_without_clinical_inference(tmp_path):
    report = collect_evidence(tmp_path)
    assert report["counts"]["selected_trials"] == 0
    assert report["counts"]["trials_with_criterion_errors"] == 0
    html = render_evidence(report)
    assert "No completion or safety conclusion is available" in html
