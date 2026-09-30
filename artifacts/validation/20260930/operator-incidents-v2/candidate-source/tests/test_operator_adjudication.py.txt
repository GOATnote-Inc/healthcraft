"""Report-validity declarations stay separate from structural acceptance."""

import importlib
import json
from copy import deepcopy

import pytest


@pytest.fixture
def core():
    return importlib.import_module("healthcraft.operator_adjudication")


@pytest.fixture
def packet(core):
    return {
        "schema_version": "healthcraft-operator-incident-adjudication-packet/v2",
        "packet_id": "adjudication-1",
        "assignment_id": "assignment-1",
        "adjudicator_id": "synthetic-test-reviewer",
        "role": "initial",
        "protocol": {"protocol_id": "development", "purpose": "engineering_development"},
        "operator_packet_sha256": "a" * 64,
        "operator_response_sha256": "b" * 64,
        "validity_rubric": core.validity_rubric(),
        "cases": [
            {
                "review_case_id": "review-a",
                "scenario_family_id": "test-family",
                "operator_report_status": "submitted",
                "documents": {
                    "task": {"target": {"patient_id": "PAT-A", "encounter_id": "ENC-A"}},
                    "scenario": {"source": None},
                    "evidence": {"completion": {"status": "completed"}, "notes": []},
                    "runtime": None,
                    "response": {"identified_target": {"patient_id": "PAT-WRONG"}},
                    "prior_judgments": None,
                },
            },
            {
                "review_case_id": "review-b",
                "scenario_family_id": "test-family",
                "operator_report_status": "pending",
                "documents": {
                    "task": {},
                    "scenario": {},
                    "evidence": None,
                    "runtime": None,
                    "response": None,
                    "prior_judgments": None,
                },
            },
        ],
        "limitations": ["Synthetic development fixture; no human judgment."],
    }


def fill_check(row, *, judgment="supported"):
    row.update(
        judgment=judgment,
        rationale="Synthetic reviewer declaration, not an actual expert assessment.",
        evidence_refs=[{"document": "task", "pointer": "/target/patient_id"}],
        response_pointers=["/identified_target/patient_id"],
    )


def completed_response(core, packet, *, decision="valid"):
    response = core.adjudication_template(packet)
    case = response["cases"][0]
    for check in case["checks"]:
        fill_check(check)
    case.update(overall=decision, rationale="Synthetic fixture assessment.")
    return response


def test_template_is_blank_and_all_opportunities_survive(core, packet):
    response = core.adjudication_template(packet)
    assert response["reviewer_declaration"]["independent_review"] is None
    assert all(case["overall"] is None for case in response["cases"])
    received = core.validate_adjudication_response(response, packet)
    assert set(received) == {"review-a", "review-b"}
    assert all(row["status"] == "pending" for row in received.values())


def test_partial_text_is_preserved_without_inferred_judgment(core, packet):
    response = core.adjudication_template(packet)
    row = response["cases"][0]["checks"][0]
    row["rationale"] = "Unfinished thought retained exactly."
    row["response_pointers"] = ["/identified_target"]
    received = core.validate_adjudication_response(response, packet)
    assert received["review-a"]["status"] == "pending"
    assert received["review-a"]["response"] == response["cases"][0]


def test_unsupported_target_requires_explicit_invalid_overall(core, packet):
    response = completed_response(core, packet, decision="invalid")
    response["cases"][0]["checks"][0]["judgment"] = "unsupported"
    received = core.validate_adjudication_response(response, packet)
    assert received["review-a"]["decision"] == "invalid"
    assert received["review-a"]["status"] == "declared"


def test_structural_acceptance_does_not_automatically_correct_reviewer(core, packet):
    # Deliberately wrong target remains a human declaration, never software truth.
    response = completed_response(core, packet)
    received = core.validate_adjudication_response(response, packet)
    assert received["review-a"]["decision"] == "valid"
    assert "verified" not in received["review-a"]


def test_missing_case_stays_absent_for_denominator_accounting(core, packet):
    response = completed_response(core, packet)
    response["cases"] = response["cases"][:1]
    received = core.validate_adjudication_response(response, packet)
    assert set(received) == {"review-a"}


@pytest.mark.parametrize("field", ["packet_sha256", "operator_response_sha256", "adjudicator_id"])
def test_foreign_assignment_or_extra_binding_is_rejected(core, packet, field):
    response = completed_response(core, packet)
    response[field] = "different"
    with pytest.raises(ValueError):
        core.validate_adjudication_response(response, packet)


@pytest.mark.parametrize("field", ["overall", "judgment"])
def test_boolean_is_not_a_review_verdict(core, packet, field):
    response = completed_response(core, packet)
    if field == "overall":
        response["cases"][0][field] = True
    else:
        response["cases"][0]["checks"][0][field] = True
    with pytest.raises(ValueError):
        core.validate_adjudication_response(response, packet)


@pytest.mark.parametrize("fault", ["unsupported", "pending", "unassessed"])
def test_valid_overall_cannot_contradict_required_checks(core, packet, fault):
    response = completed_response(core, packet)
    row = response["cases"][0]["checks"][0]
    row["judgment"] = None if fault == "pending" else fault
    if fault == "unassessed":
        row["unassessed_reason"] = "insufficient_evidence"
    with pytest.raises(ValueError):
        core.validate_adjudication_response(response, packet)


def test_available_real_null_is_a_reference_but_missing_runtime_is_not(core, packet):
    response = completed_response(core, packet)
    row = response["cases"][0]["checks"][0]
    row["evidence_refs"] = [{"document": "scenario", "pointer": "/source"}]
    core.validate_adjudication_response(response, packet)
    row["evidence_refs"] = [{"document": "runtime", "pointer": ""}]
    with pytest.raises(ValueError):
        core.validate_adjudication_response(response, packet)


def test_assessed_check_requires_both_source_and_response_references(core, packet):
    response = completed_response(core, packet)
    response["cases"][0]["checks"][0]["response_pointers"] = []
    with pytest.raises(ValueError):
        core.validate_adjudication_response(response, packet)


def test_wrong_pointer_and_duplicate_check_are_not_adjudication(core, packet):
    response = completed_response(core, packet)
    response["cases"][0]["checks"][0]["response_pointers"] = ["/missing"]
    with pytest.raises(ValueError):
        core.validate_adjudication_response(response, packet)
    response = completed_response(core, packet)
    response["cases"][0]["checks"].append(deepcopy(response["cases"][0]["checks"][0]))
    with pytest.raises(ValueError):
        core.validate_adjudication_response(response, packet)


def test_no_report_cannot_be_declared_valid(core, packet):
    packet["cases"][0]["documents"]["response"] = None
    packet["cases"][0]["operator_report_status"] = "pending"
    response = completed_response(core, packet)
    with pytest.raises(ValueError):
        core.validate_adjudication_response(response, packet)


def test_explicit_abstention_is_not_missing_adjudication(core, packet):
    response = core.adjudication_template(packet)
    row = response["cases"][1]
    row.update(overall="unassessed", unassessed_reason="reviewer_abstention", rationale="Abstain.")
    for check in row["checks"]:
        check.update(
            judgment="unassessed", unassessed_reason="reviewer_abstention", rationale="Abstain."
        )
    received = core.validate_adjudication_response(response, packet)
    assert received["review-b"]["status"] == "abstained"


def test_response_is_detached_from_input(core, packet):
    response = completed_response(core, packet)
    received = core.validate_adjudication_response(response, packet)
    response["cases"][0]["rationale"] = "Changed later."
    assert received["review-a"]["response"]["rationale"] == "Synthetic fixture assessment."


@pytest.fixture
def issued(core, packet, tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_implementation", lambda: {"synthetic-test-issuer": "a" * 64})
    monkeypatch.setattr(
        core, "_render", lambda packet, template: json.dumps([packet, template], sort_keys=True)
    )
    # Filesystem receipt tests use declared synthetic packets, not human outcomes.
    root = tmp_path / "issued"
    operator = {
        "operator_id": "synthetic-operator",
        "protocol": packet["protocol"],
        "cases": [
            {
                "review_case_id": case["review_case_id"],
                "scenario_family_id": case["scenario_family_id"],
                "documents": {
                    key: case["documents"][key]
                    for key in ("task", "scenario", "evidence", "runtime")
                },
            }
            for case in packet["cases"]
        ],
    }
    raw, received, _ = operator_submission(operator)
    packet.update(
        operator_packet_sha256=core._digest(operator),
        operator_response_sha256=core._sha(raw),
        cases=core._source_cases(operator, received, []),
    )
    core._issue_packet(
        packet,
        root,
        source_bindings={
            "operator_manifest_sha256": core._sha(b"{}"),
            "operator_response_sha256": core._sha(raw),
        },
        coordinator_files={
            "coordinator/operator-packet.json": core._canonical(operator) + b"\n",
            "coordinator/operator-response.json": raw,
            "coordinator/operator-manifest.json": b"{}",
            "coordinator/operator-validation.json": b'{"errors":[]}',
        },
    )
    return root


def submit(core, issued, tmp_path, value, name="import", raw=None):
    path = tmp_path / (name + "-response.json")
    path.write_bytes(raw if raw is not None else json.dumps(value).encode())
    return core.import_adjudication_response(issued / "manifest.json", path, tmp_path / name)


def test_import_retains_raw_bytes_and_all_assigned_case_opportunities(
    core, packet, issued, tmp_path
):
    value = completed_response(core, packet)
    raw = json.dumps(value, indent=3).encode() + b"\n"
    result = submit(core, issued, tmp_path, value, raw=raw)
    assert result["status"] == "recorded"
    assert result["counts"] == {
        "assigned": 2,
        "declared": 1,
        "pending": 1,
        "unassessed": 0,
        "abstained": 0,
    }
    assert (tmp_path / "import/submission.json").read_bytes() == raw
    assert result["reviewer_declaration"]["independent_review"] is None
    assert result["clinical_validation"] == "not_established"


@pytest.mark.parametrize("fault", ["duplicate_json", "foreign_reviewer", "wrong_response_hash"])
def test_invalid_adjudication_retained_without_losing_assignments(
    core, packet, issued, tmp_path, fault
):
    value = completed_response(core, packet)
    if fault == "duplicate_json":
        raw = (
            json.dumps(value)
            .replace('"overall": "valid"', '"overall": "invalid", "overall": "valid"')
            .encode()
        )
    elif fault == "foreign_reviewer":
        value["adjudicator_id"] = "somebody-else"
        raw = json.dumps(value).encode()
    else:
        value["packet_sha256"] = "c" * 64
        raw = json.dumps(value).encode()
    result = submit(core, issued, tmp_path, value, raw=raw)
    assert result["status"] == "invalid_submission"
    assert result["counts"]["assigned"] == result["counts"]["pending"] == 2
    assert (tmp_path / "import/submission.json").read_bytes() == raw


def test_tampered_packet_rejected_before_receipt_output(core, packet, issued, tmp_path):
    path = issued / "public/packet.json"
    path.write_text(path.read_text().replace("PAT-WRONG", "PAT-A"))
    with pytest.raises(ValueError):
        submit(core, issued, tmp_path, completed_response(core, packet))
    assert not (tmp_path / "import").exists()


def test_import_output_is_exclusive(core, packet, issued, tmp_path):
    response = completed_response(core, packet)
    submit(core, issued, tmp_path, response)
    before = (tmp_path / "import/submission.json").read_bytes()
    with pytest.raises(FileExistsError):
        submit(core, issued, tmp_path, response)
    assert (tmp_path / "import/submission.json").read_bytes() == before


def test_duplicate_record_does_not_manufacture_independent_agreement(
    core, packet, issued, tmp_path
):
    submit(core, issued, tmp_path, completed_response(core, packet))
    with pytest.raises(ValueError):
        core.summarize_adjudications(
            issued / "manifest.json",
            {
                packet["adjudicator_id"]: tmp_path / "import/manifest.json",
                "another-person": tmp_path / "import/manifest.json",
            },
            tmp_path / "summary",
        )
    assert not (tmp_path / "summary").exists()


def test_missing_assigned_reviewer_remains_pending(core, packet, issued, tmp_path):
    submit(core, issued, tmp_path, completed_response(core, packet))
    result = core.summarize_adjudications(
        issued / "manifest.json",
        {packet["adjudicator_id"]: tmp_path / "import/manifest.json", "missing-reviewer": None},
        tmp_path / "summary",
    )
    assert result["assigned_opportunities"] == 4
    assert result["counts"]["pending"] == 3
    assert [row["status"] for row in result["cases"]] == ["pending", "pending"]


def test_disagreeing_initial_judgments_are_retained_without_voting(core, packet, issued, tmp_path):
    submit(core, issued, tmp_path, completed_response(core, packet))
    second = deepcopy(packet)
    second.update(packet_id="second-packet", adjudicator_id="second-reviewer")
    root = tmp_path / "issued-second"
    first_manifest = json.loads((issued / "manifest.json").read_text())
    core._issue_packet(
        second,
        root,
        source_bindings=first_manifest["source_bindings"],
        coordinator_files={
            name: (issued / name).read_bytes()
            for name in first_manifest["source_bindings"]["coordinator_files"]
        },
    )
    value = completed_response(core, second, decision="invalid")
    value["cases"][0]["checks"][0]["judgment"] = "unsupported"
    submit(core, root, tmp_path, value, name="second")
    result = core.summarize_adjudications(
        issued / "manifest.json",
        {
            packet["adjudicator_id"]: tmp_path / "import/manifest.json",
            "second-reviewer": tmp_path / "second/manifest.json",
        },
        tmp_path / "summary",
    )
    assert result["cases"][0]["status"] == "disputed"
    assert result["cases"][0]["resolved_decision"] is None
    assert len(result["cases"][0]["initial_judgments"]) == 2


def operator_submission(operator):
    from healthcraft.operator_incidents import (
        incident_response_template,
        validate_incident_response,
    )

    operator.update(
        packet_id="synthetic-operator-packet", assignment_id="synthetic-operator-assignment"
    )
    original = incident_response_template(operator)
    row = original["cases"][0]
    refs = [{"document": "task", "pointer": "/target/patient_id"}]
    row["identified_target"].update(
        status="identified",
        patient_id="PAT-WRONG",
        encounter_id="ENC-WRONG",
        rationale="Synthetic incorrect report.",
        evidence_refs=refs,
    )
    for axis in row["axes"]:
        axis.update(judgment="yes", rationale="Synthetic unverified assertion.", evidence_refs=refs)
    row["incident_assessment"].update(
        status="none_identified", summary="Synthetic unsupported assertion.", evidence_refs=refs
    )
    original["cases"] = [row]
    raw = json.dumps(original, indent=4).encode()
    return raw, validate_incident_response(original, operator), original


def test_builder_binds_exact_operator_submission_without_prefilled_verdicts(
    core, packet, tmp_path, monkeypatch
):
    monkeypatch.setattr(core, "_implementation", lambda: {"synthetic-test-issuer": "a" * 64})
    monkeypatch.setattr(
        core, "_render", lambda packet, template: json.dumps([packet, template], sort_keys=True)
    )
    source_packet = {
        "protocol": packet["protocol"],
        "operator_id": "test-operator",
        "cases": [
            {
                "review_case_id": c["review_case_id"],
                "scenario_family_id": c["scenario_family_id"],
                "documents": {
                    k: c["documents"][k] for k in ("task", "scenario", "evidence", "runtime")
                },
                "assistance": {"hidden_from_adjudicator": "MODEL_VERDICT_CANARY"},
            }
            for c in packet["cases"]
        ],
    }
    raw, received, original = operator_submission(source_packet)
    monkeypatch.setattr(
        core, "_operator_inputs", lambda *a, **k: (source_packet, raw, received, b"{}", [])
    )
    result = core.build_adjudication_packet(
        tmp_path / "source/manifest.json",
        tmp_path / "response.json",
        tmp_path / "built",
        assignment={"assignment_id": "adj-a", "adjudicator_id": "reviewer-a", "role": "initial"},
    )
    assert result["operator_response_sha256"] == core._sha(raw)
    assert result["cases"][0]["documents"]["response"] == original["cases"][0]
    assert result["cases"][1]["operator_report_status"] == "pending"
    assert b"MODEL_VERDICT_CANARY" not in (tmp_path / "built/public/packet.json").read_bytes()
    assert (tmp_path / "built/coordinator/operator-response.json").read_bytes() == raw
    assert all(row["overall"] is None for row in core.adjudication_template(result)["cases"])


def test_reviewer_cannot_be_the_assigned_operator_under_same_declared_id(
    core, packet, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        core,
        "_operator_inputs",
        lambda *a, **k: ({"operator_id": "same-person"}, b"{}", {}, b"{}", []),
    )
    with pytest.raises(ValueError):
        core.build_adjudication_packet(
            tmp_path / "source/manifest.json",
            tmp_path / "response.json",
            tmp_path / "output",
            assignment={
                "assignment_id": "adj-a",
                "adjudicator_id": "same-person",
                "role": "initial",
            },
        )
    assert not (tmp_path / "output").exists()


@pytest.fixture
def disputed(core, packet, tmp_path, monkeypatch):
    monkeypatch.setattr(core, "_implementation", lambda: {"synthetic-test-issuer": "a" * 64})
    monkeypatch.setattr(
        core, "_render", lambda packet, template: json.dumps([packet, template], sort_keys=True)
    )
    operator = {
        "operator_id": "test-operator",
        "protocol": packet["protocol"],
        "cases": [
            {
                "review_case_id": case["review_case_id"],
                "scenario_family_id": case["scenario_family_id"],
                "documents": {
                    key: case["documents"][key]
                    for key in ("task", "scenario", "evidence", "runtime")
                },
            }
            for case in packet["cases"]
        ],
    }
    raw, received, _ = operator_submission(operator)
    monkeypatch.setattr(
        core, "_operator_inputs", lambda *a, **k: (operator, raw, received, b"{}", [])
    )
    imports, issued = {}, {}
    for name, decision in [("reviewer-a", "valid"), ("reviewer-b", "invalid")]:
        folder = tmp_path / name
        value = core.build_adjudication_packet(
            tmp_path / "source/manifest.json",
            tmp_path / "response.json",
            folder,
            assignment={"assignment_id": name, "adjudicator_id": name, "role": "initial"},
        )
        answer = completed_response(core, value, decision=decision)
        if decision == "invalid":
            answer["cases"][0]["checks"][0]["judgment"] = "unsupported"
        submit(core, folder, tmp_path, answer, name=name + "-import")
        imports[name] = tmp_path / (name + "-import") / "manifest.json"
        issued[name] = folder / "manifest.json"
    return imports, issued


def test_explicit_resolver_only_sees_disputed_reports_and_preserves_initial_judgments(
    core, disputed, tmp_path
):
    records, issued = disputed
    output = tmp_path / "resolver"
    packet = core.build_adjudication_packet(
        tmp_path / "source/manifest.json",
        tmp_path / "response.json",
        output,
        assignment={
            "assignment_id": "resolve-1",
            "adjudicator_id": "resolver-a",
            "role": "resolver",
        },
        prior_records=records,
    )
    assert [case["review_case_id"] for case in packet["cases"]] == ["review-a"]
    assert len(packet["cases"][0]["documents"]["prior_judgments"]) == 2
    assert core.adjudication_template(packet)["cases"][0]["overall"] is None
    response = completed_response(core, packet, decision="invalid")
    response["cases"][0]["checks"][0]["judgment"] = "unsupported"
    submit(core, output, tmp_path, response, name="resolution")
    result = core.summarize_adjudications(
        issued["reviewer-a"],
        records,
        tmp_path / "resolved-summary",
        resolver_record=tmp_path / "resolution/manifest.json",
    )
    row = result["cases"][0]
    assert row["status"] == "resolved_invalid"
    assert row["resolved_decision"] == "invalid"
    assert [r["decision"] for r in row["initial_judgments"]] == ["valid", "invalid"]
    assert result["cases"][1]["status"] == "pending"
    assert result["assigned_opportunities"] == 4


def test_original_reviewer_cannot_also_resolve_their_disagreement(core, disputed, tmp_path):
    records, _ = disputed
    with pytest.raises(ValueError):
        core.build_adjudication_packet(
            tmp_path / "source/manifest.json",
            tmp_path / "response.json",
            tmp_path / "resolver",
            assignment={
                "assignment_id": "resolve-1",
                "adjudicator_id": "reviewer-a",
                "role": "resolver",
            },
            prior_records=records,
        )
    assert not (tmp_path / "resolver").exists()


def test_resolution_cannot_be_reused_after_an_initial_submission_changes(core, disputed, tmp_path):
    records, issued = disputed
    output = tmp_path / "resolver"
    packet = core.build_adjudication_packet(
        tmp_path / "source/manifest.json",
        tmp_path / "response.json",
        output,
        assignment={
            "assignment_id": "resolve-1",
            "adjudicator_id": "resolver-a",
            "role": "resolver",
        },
        prior_records=records,
    )
    answer = completed_response(core, packet, decision="invalid")
    answer["cases"][0]["checks"][0]["judgment"] = "unsupported"
    submit(core, output, tmp_path, answer, name="resolution")
    first_packet, _, _ = core.validate_adjudication_packet(issued["reviewer-a"])
    changed = completed_response(core, first_packet)
    changed["cases"][0]["rationale"] = "A new explicitly recorded reviewer revision."
    submit(core, issued["reviewer-a"].parent, tmp_path, changed, name="revision")
    changed_records = {**records, "reviewer-a": tmp_path / "revision/manifest.json"}
    with pytest.raises(ValueError):
        core.summarize_adjudications(
            issued["reviewer-a"],
            changed_records,
            tmp_path / "summary",
            resolver_record=tmp_path / "resolution/manifest.json",
        )
    assert not (tmp_path / "summary").exists()


def test_same_operator_identity_with_case_change_cannot_adjudicate(
    core, packet, monkeypatch, tmp_path
):
    operator = {
        "operator_id": "Review-Operator",
        "protocol": packet["protocol"],
        "cases": [
            {
                **case,
                "documents": {
                    key: value
                    for key, value in case["documents"].items()
                    if key not in ("response", "prior_judgments")
                },
            }
            for case in packet["cases"]
        ],
    }
    monkeypatch.setattr(core, "_operator_inputs", lambda *a, **k: (operator, b"{}", {}, b"{}", []))
    with pytest.raises(ValueError, match="operator cannot"):
        core.build_adjudication_packet(
            tmp_path / "source/manifest.json",
            tmp_path / "response.json",
            tmp_path / "issued",
            assignment={
                "assignment_id": "test",
                "adjudicator_id": "review-operator",
                "role": "initial",
            },
        )
    assert not (tmp_path / "issued").exists()


def test_dispute_waits_for_all_assigned_initial_reviewers(core, disputed, tmp_path):
    records, issued = disputed
    records = {**records, "reviewer-c": None}
    result = core.summarize_adjudications(issued["reviewer-a"], records, tmp_path / "summary")
    assert result["assigned_opportunities"] == 6
    assert result["cases"][0]["status"] == "disputed"
    assert result["cases"][0]["initial_judgments"][2]["status"] == "pending"
    with pytest.raises(ValueError, match="No complete disputed"):
        core.build_adjudication_packet(
            tmp_path / "source/manifest.json",
            tmp_path / "response.json",
            tmp_path / "resolver",
            assignment={
                "assignment_id": "test",
                "adjudicator_id": "resolver-a",
                "role": "resolver",
            },
            prior_records=records,
        )
    assert not (tmp_path / "resolver").exists()


def test_unfinished_resolver_preserves_dispute_and_separate_denominator(core, disputed, tmp_path):
    records, issued = disputed
    packet = core.build_adjudication_packet(
        tmp_path / "source/manifest.json",
        tmp_path / "response.json",
        tmp_path / "resolver",
        assignment={"assignment_id": "test", "adjudicator_id": "resolver-a", "role": "resolver"},
        prior_records=records,
    )
    submit(
        core, tmp_path / "resolver", tmp_path, core.adjudication_template(packet), name="unfinished"
    )
    result = core.summarize_adjudications(
        issued["reviewer-a"],
        records,
        tmp_path / "summary",
        resolver_record=tmp_path / "unfinished/manifest.json",
    )
    assert result["cases"][0]["status"] == "disputed"
    assert result["cases"][0]["resolved_decision"] is None
    assert result["resolution"]["assigned_opportunities"] == 1
    assert result["resolution"]["counts"]["pending"] == 1
    assert result["assigned_opportunities"] == 4


def test_adjudicator_can_cite_strict_decoded_json_array(core, packet):
    packet["cases"][0]["documents"]["evidence"]["captured_text"] = '[{"id":"source-a"}]'
    value = completed_response(core, packet)
    value["cases"][0]["checks"][0]["evidence_refs"] = [
        {
            "document": "evidence",
            "pointer": "/captured_text",
            "decoded_json_pointer": "/0/id",
        }
    ]
    assert core.validate_adjudication_response(value, packet)["review-a"]["status"] == "declared"


def test_resolver_displayed_prior_judgments_must_match_original_imports(core, disputed, tmp_path):
    records, _ = disputed
    root = tmp_path / "resolver"
    packet = core.build_adjudication_packet(
        tmp_path / "source/manifest.json",
        tmp_path / "response.json",
        root,
        assignment={"assignment_id": "test", "adjudicator_id": "resolver-a", "role": "resolver"},
        prior_records=records,
    )
    packet["cases"][0]["documents"]["prior_judgments"][0]["decision"] = "invalid"
    manifest = json.loads((root / "manifest.json").read_text())
    payloads = {
        "public/packet.json": core._canonical(packet) + b"\n",
        "public/response-template.json": core._canonical(core.adjudication_template(packet))
        + b"\n",
        "public/report.html": core._render(packet, core.adjudication_template(packet)).encode(),
    }
    for name, raw in payloads.items():
        (root / name).write_bytes(raw)
        manifest["files"][name] = core._sha(raw)
    manifest["packet_sha256"] = core._digest(packet)
    (root / "manifest.json").write_bytes(core._canonical(manifest) + b"\n")
    with pytest.raises(ValueError, match="prior|initial"):
        core.validate_adjudication_packet(root / "manifest.json")
