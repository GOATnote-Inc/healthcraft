"""Offline reviewer masking and strict, non-clinical import receipts."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from healthcraft.clinical_review import build_review_packet, import_review_response


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


@pytest.fixture
def source(tmp_path):
    criteria = [
        {
            "id": "IR-PRIVATE-C01",
            "assertion": "The encounter was retrieved.",
            "dimension": "clinical_completeness",
            "verification": "world_state",
            "check": "PRIVATE-CHECK-EXPRESSION",
            "safety_critical": True,
        },
        {
            "id": "IR-PRIVATE-C02",
            "assertion": "The response describes the visible finding.",
            "dimension": "clinical_correctness",
            "verification": "llm_judge",
            "check": "",
            "safety_critical": False,
        },
    ]
    task = {
        "id": "IR-PRIVATE",
        "category": "information_retrieval",
        "level": 1,
        "title": "PRIVATE-TASK-TITLE",
        "description": "Retrieve the encounter.",
        "initial_state": {"answer": "PRIVATE-HIDDEN-ANSWER"},
        "expected_tools": ["getEncounterDetails"],
        "criteria": deepcopy(criteria),
        "metadata": {"clinical_note": "PRIVATE-AUTHOR-NOTE"},
        "source_data": {"answer": "PRIVATE-SOURCE-ANSWER"},
    }
    tool = {
        "name": "getEncounterDetails",
        "description": "Read an encounter",
        "parameters": {"type": "object", "properties": {"encounter_id": {"type": "string"}}},
    }
    payload = {
        "task": task,
        "effective_criteria": criteria,
        "rubric_channel": "v10",
        "scenario_context": {},
        "checkpoint_identity": "PRIVATE-CHECKPOINT",
        "presented_system": "Use the supplied records.",
        "presented_user": task["description"],
        "tool_definitions": [tool],
        "capture_status": "complete",
        "grading_mode": "benchmark",
    }
    data = {
        "task_id": task["id"],
        "model": "PRIVATE-MODEL-ALIAS",
        "seed": 42,
        "system_prompt": payload["presented_system"],
        "turns": [
            {"role": "user", "content": payload["presented_user"], "timestamp": "PRIVATE-TIME"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "provider_tool_123",
                        "name": "getEncounterDetails",
                        "arguments": {"encounter_id": "ENC-1"},
                    }
                ],
                "provider": "PRIVATE-PROVIDER",
            },
            {
                "role": "tool",
                "tool_call_id": "provider_tool_123",
                "content": '{"status":"ok","finding":"visible finding"}',
            },
            {"role": "assistant", "content": "The visible finding was retrieved."},
        ],
        "criteria_results": [
            {"id": criteria[0]["id"], "satisfied": True, "evidence": "PRIVATE-GRADER-EVIDENCE"},
            {"id": criteria[1]["id"], "satisfied": False, "evidence": "PRIVATE-JUDGE-EVIDENCE"},
        ],
        "reward": 0.5,
        "passed": False,
        "rubric_channel": "v10",
        "metadata": {
            "stop_reason": "stop",
            "termination_kind": "complete",
            "checkpoint_identity": payload["checkpoint_identity"],
            "agent_tool_definitions": [tool],
            "review_context": {
                "schema_version": "clinical-review-context/v1",
                "payload": payload,
                "sha256": digest(payload),
            },
        },
    }
    payload["turns_sha256"] = digest(data["turns"])
    data["metadata"]["review_context"]["sha256"] = digest(payload)
    path = tmp_path / "IR-PRIVATE_PRIVATE-MODEL-ALIAS_42_t1.json"
    path.write_text(json.dumps(data))
    return path


@pytest.fixture
def protocol():
    return {
        "protocol_id": "protocol-1",
        "version": "1",
        "purpose": "engineering_pilot",
        "sampling_plan": "All assigned criterion opportunities, selected before review.",
        "eligibility_rule": "Captured model-visible evidence only.",
    }


def build(source, tmp_path, protocol, name="packet"):
    root = tmp_path / name
    result = build_review_packet(
        [source],
        root,
        protocol=protocol,
        reviewer_assignment={"reviewer_id": "reviewer-1", "role": "independent"},
    )
    return root, result


def read(path):
    return json.loads(path.read_text())


def mutate_source(source, change, *, rehash=False):
    data = read(source)
    change(data)
    if rehash:
        context = data["metadata"]["review_context"]
        context["payload"]["turns_sha256"] = digest(data["turns"])
        context["sha256"] = digest(context["payload"])
    source.write_text(json.dumps(data))


def response_for(root, *, verdict="satisfied"):
    response = read(root / "reviewer" / "response-template.json")
    response["reviewer_id"] = "reviewer-1"
    response["reviewer_attestation"] = {
        "qualification_statement": "Engineering fixture, not a clinical expert review.",
        "conflicts_statement": "Synthetic test only.",
        "independent_review": True,
    }
    packet = read(root / "reviewer" / "packet.json")
    item = response["reviews"][0]
    item.update(
        criterion_validity="valid",
        verdict=verdict,
        unassessed_reason="reviewer_abstention" if verdict == "unassessed" else None,
        evidence_refs=[packet["items"][0]["evidence_refs"][-1]],
        rationale="Visible evidence supports this engineering fixture label.",
        blinding="intact",
    )
    return response


def submit(root, response, tmp_path, name="receipt"):
    path = tmp_path / f"{name}-response.json"
    path.write_text(json.dumps(response))
    return import_review_response(root / "coordinator" / "manifest.json", path, tmp_path / name)


def test_packet_is_physically_masked_and_source_bound(source, tmp_path, protocol):
    original = source.read_bytes()
    root, manifest = build(source, tmp_path, protocol)
    public = "\n".join(p.read_text() for p in (root / "reviewer").iterdir())
    for hidden in (
        "PRIVATE-",
        "provider_tool_123",
        str(source),
        "safety_critical",
        "criteria_results",
        "reward",
        "world_state",
        "llm_judge",
    ):
        assert hidden not in public
    packet = read(root / "reviewer" / "packet.json")
    assert len(packet["items"]) == 2
    turns = packet["cases"][0]["turns"]
    assert turns[1]["tool_calls"][0]["id"] == turns[2]["tool_call_id"]
    assert turns[1]["tool_calls"][0]["id"] != "provider_tool_123"
    assert turns[2]["content"] == read(source)["turns"][2]["content"]
    assert manifest["sources"][0]["trajectory_sha256"] == hashlib.sha256(original).hexdigest()
    assert (
        manifest["sources"][0]["review_context_sha256"]
        == read(source)["metadata"]["review_context"]["sha256"]
    )
    assert manifest["clinical_validation_status"] == "pending"
    assert source.read_bytes() == original


@pytest.mark.parametrize("failure", ["missing", "hash", "incomplete", "presented"])
def test_unbound_or_changed_context_rejected_before_creating_output(
    source, tmp_path, protocol, failure
):
    def change(data):
        context = data["metadata"]["review_context"]
        if failure == "missing":
            del data["metadata"]["review_context"]
        elif failure == "hash":
            context["payload"]["effective_criteria"][0]["assertion"] = "Changed."
        elif failure == "incomplete":
            context["payload"]["capture_status"] = "incomplete"
        else:
            data["turns"][0]["content"] = "Not the captured prompt."

    mutate_source(source, change, rehash=failure == "incomplete")
    with pytest.raises(ValueError):
        build(source, tmp_path, protocol)
    assert not (tmp_path / "packet").exists()


def test_all_sources_preflight_no_partial_packet(source, tmp_path, protocol):
    invalid = tmp_path / "broken.json"
    invalid.write_text("{")
    with pytest.raises(ValueError):
        build_review_packet(
            [source, invalid],
            tmp_path / "packet",
            protocol=protocol,
            reviewer_assignment={"reviewer_id": "reviewer-1", "role": "independent"},
        )
    assert not (tmp_path / "packet").exists()


def test_duplicate_sources_rejected_instead_of_double_counted(source, tmp_path, protocol):
    with pytest.raises(ValueError, match="duplicate"):
        build_review_packet(
            [source, source],
            tmp_path / "packet",
            protocol=protocol,
            reviewer_assignment={"reviewer_id": "reviewer-1", "role": "independent"},
        )


def test_same_provider_call_id_can_be_reused_after_answer(source, tmp_path, protocol):
    def change(data):
        data["turns"][3:3] = deepcopy(data["turns"][1:3])

    mutate_source(source, change, rehash=True)
    root, _ = build(source, tmp_path, protocol)
    turns = read(root / "reviewer" / "packet.json")["cases"][0]["turns"]
    assert turns[1]["tool_calls"][0]["id"] == turns[2]["tool_call_id"]
    assert turns[3]["tool_calls"][0]["id"] == turns[4]["tool_call_id"]
    assert turns[1]["tool_calls"][0]["id"] != turns[3]["tool_calls"][0]["id"]


def test_known_model_name_in_free_text_blocks_export_without_rewriting(source, tmp_path, protocol):
    mutate_source(
        source, lambda d: d["turns"][-1].update(content="I am PRIVATE-MODEL-ALIAS."), rehash=True
    )
    with pytest.raises(ValueError, match="identity|blind"):
        build(source, tmp_path, protocol)
    assert not (tmp_path / "packet").exists()


def test_all_known_cohort_models_are_checked_against_the_entire_packet(source, tmp_path, protocol):
    second = source.with_name("second-model.json")
    data = read(source)
    data["model"] = "OTHER-MODEL-ALIAS"
    second.write_text(json.dumps(data))
    mutate_source(
        source,
        lambda d: d["turns"][-1].update(content="OTHER-MODEL-ALIAS supplied another answer."),
        rehash=True,
    )
    with pytest.raises(ValueError, match="identity|blind"):
        build_review_packet(
            [source, second],
            tmp_path / "packet",
            protocol=protocol,
            reviewer_assignment={"reviewer_id": "reviewer-1", "role": "independent"},
        )
    assert not (tmp_path / "packet").exists()


def test_untrusted_markdown_is_fenced_without_active_html(source, tmp_path, protocol):
    attack = "```\n<script>alert(1)</script>\n[click](https://example.invalid)\n````"
    mutate_source(source, lambda d: d["turns"][-1].update(content=attack), rehash=True)
    root, _ = build(source, tmp_path, protocol)
    markdown = (root / "reviewer" / "packet.md").read_text()
    assert "`````text\n" + attack + "\n`````" in markdown
    assert read(root / "reviewer" / "packet.json")["cases"][0]["turns"][-1]["content"] == attack


def test_incomplete_and_ungraded_execution_remains_reviewable_but_not_calibrated(
    source, tmp_path, protocol
):
    mutate_source(
        source, lambda d: d["metadata"].update(stop_reason="max_tokens", grading_complete=False)
    )
    root, manifest = build(source, tmp_path, protocol)
    assert manifest["sources"][0]["execution_status"] == "incomplete"
    assert manifest["sources"][0]["unassessed_experiment"] is True
    assert manifest["clinical_validation_status"] == "pending"
    assert len(read(root / "reviewer" / "packet.json")["items"]) == 2


def test_partial_import_preserves_full_assigned_denominator_without_clinical_claim(
    source, tmp_path, protocol
):
    root, _ = build(source, tmp_path, protocol)
    response = response_for(root)
    receipt = submit(root, response, tmp_path)
    assert receipt["counts"] == {
        "assigned": 2,
        "submitted": 1,
        "assessed": 1,
        "unassessed": 0,
        "pending": 1,
    }
    assert receipt["clinical_validation_status"] == "unvalidated_submission"
    assert receipt["reviewer_attestation"]["independent_review"] is True
    assert len(receipt["items"]) == 2
    assert receipt["items"][1]["status"] == "pending"
    assert "accuracy" not in receipt


def test_omitted_row_stays_pending_and_abstention_is_not_negative(source, tmp_path, protocol):
    root, _ = build(source, tmp_path, protocol)
    response = response_for(root, verdict="unassessed")
    response["reviews"].pop()
    receipt = submit(root, response, tmp_path)
    assert receipt["counts"] == {
        "assigned": 2,
        "submitted": 1,
        "assessed": 0,
        "unassessed": 1,
        "pending": 1,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(packet_sha256="0" * 64),
        lambda r: r.update(assignment_id="wrong"),
        lambda r: r.update(reviewer_id="different-reviewer"),
        lambda r: r["reviews"][0].update(verdict=True),
        lambda r: r["reviews"][0].update(verdict="false"),
        lambda r: r["reviews"][0].update(evidence_refs=["made-up-reference"]),
        lambda r: r["reviews"][0].update(criterion_validity="ambiguous"),
        lambda r: r["reviews"][0].update(unassessed_reason="reviewer_abstention"),
        lambda r: r["reviews"][0].update(rationale=""),
        lambda r: r["reviews"][0].update(extra=True),
        lambda r: r["reviews"].append(deepcopy(r["reviews"][0])),
        lambda r: r["reviews"][0].update(item_id="foreign-item"),
        lambda r: r["reviews"][1].update(rationale="Half-filled blank row"),
        lambda r: r["reviewer_attestation"].update(independent_review="true"),
    ],
)
def test_import_rejects_malformed_or_misbound_responses_before_output(
    source, tmp_path, protocol, mutation
):
    root, _ = build(source, tmp_path, protocol)
    response = response_for(root)
    mutation(response)
    with pytest.raises(ValueError):
        submit(root, response, tmp_path)
    assert not (tmp_path / "receipt").exists()


def test_packet_tampering_is_detected_on_import(source, tmp_path, protocol):
    root, _ = build(source, tmp_path, protocol)
    response = response_for(root)
    packet_path = root / "reviewer" / "packet.json"
    packet = read(packet_path)
    packet["items"][0]["criterion"]["assertion"] = "Changed after distribution."
    packet_path.write_text(json.dumps(packet))
    with pytest.raises(ValueError, match="hash|digest|changed"):
        submit(root, response, tmp_path)


def test_readable_rendering_tampering_is_detected_on_import(source, tmp_path, protocol):
    root, _ = build(source, tmp_path, protocol)
    response = response_for(root)
    (root / "reviewer" / "packet.md").write_text("Changed instructions and evidence.")
    with pytest.raises(ValueError, match="rendering|Markdown|hash|digest"):
        submit(root, response, tmp_path)


def test_duplicate_json_keys_are_rejected(source, tmp_path, protocol):
    root, _ = build(source, tmp_path, protocol)
    response = response_for(root)
    path = tmp_path / "response.json"
    raw = json.dumps(response)
    path.write_text(raw[:-1] + ',"reviewer_id":"reviewer-1"}')
    with pytest.raises(ValueError, match="duplicate"):
        import_review_response(root / "coordinator" / "manifest.json", path, tmp_path / "receipt")


def test_outputs_are_exclusive(source, tmp_path, protocol):
    root, _ = build(source, tmp_path, protocol)
    before = (root / "reviewer" / "packet.json").read_bytes()
    with pytest.raises(FileExistsError):
        build(source, tmp_path, protocol)
    response = response_for(root)
    submit(root, response, tmp_path)
    with pytest.raises(FileExistsError):
        submit(root, response, tmp_path)
    assert (root / "reviewer" / "packet.json").read_bytes() == before


def test_explicit_original_and_retry_both_preserve_assigned_opportunities(
    source, tmp_path, protocol
):
    latest = source.with_name(source.stem + "_attempt2.json")
    latest.write_bytes(source.read_bytes())
    root = tmp_path / "packet"
    manifest = build_review_packet(
        [source, latest],
        root,
        protocol=protocol,
        reviewer_assignment={"reviewer_id": "reviewer-1", "role": "independent"},
    )
    assert len(manifest["sources"]) == 2
    assert {item["original_path"] for item in manifest["sources"]} == {str(source), str(latest)}
    assert len(manifest["items"]) == 4
    assert len({item["trial_group"] for item in manifest["sources"]}) == 1
    assert {item["attempt_number"] for item in manifest["sources"]} == {1, 2}
    latest.write_text("{")
    with pytest.raises(ValueError):
        build_review_packet(
            [source, latest],
            tmp_path / "second-packet",
            protocol=protocol,
            reviewer_assignment={"reviewer_id": "reviewer-1", "role": "independent"},
        )


def test_directory_keeps_all_attempts_and_records_known_sidecar_exclusions(
    source, tmp_path, protocol
):
    latest = source.with_name(source.stem + "_attempt2.json")
    latest.write_bytes(source.read_bytes())
    sidecar = source.with_name(source.stem + "_grading.json")
    sidecar.write_text("{}")
    manifest = build_review_packet(
        tmp_path,
        tmp_path / "packet",
        protocol=protocol,
        reviewer_assignment={"reviewer_id": "reviewer-1", "role": "independent"},
    )
    assert len(manifest["sources"]) == 2
    assert manifest["selection"]["input_count"] == 3
    assert manifest["selection"]["selected_count"] == 2
    assert manifest["selection"]["excluded"] == [
        {"path": str(sidecar), "reason": "known_generated_sidecar"}
    ]


def test_frozen_coordinator_snapshot_is_portable_and_tampering_is_rejected(
    source, tmp_path, protocol
):
    root, manifest = build(source, tmp_path, protocol)
    response = response_for(root)
    source.unlink()
    receipt = submit(root, response, tmp_path)
    assert receipt["counts"]["assigned"] == 2
    snapshot = root / "coordinator" / manifest["sources"][0]["snapshot"]
    snapshot.write_text("{}")
    with pytest.raises(ValueError, match="snapshot hash"):
        submit(root, response, tmp_path, name="changed-receipt")


def test_cli_build_import_and_error_statuses(source, tmp_path, protocol):
    script = Path(__file__).resolve().parents[1] / "scripts" / "clinical_review.py"
    protocol_file, assignment_file = tmp_path / "protocol.json", tmp_path / "assignment.json"
    protocol_file.write_text(json.dumps(protocol))
    assignment_file.write_text(json.dumps({"reviewer_id": "reviewer-1", "role": "independent"}))
    root = tmp_path / "packet"
    command = [
        sys.executable,
        str(script),
        "build",
        str(source),
        "--protocol",
        str(protocol_file),
        "--assignment",
        str(assignment_file),
        "--output-dir",
        str(root),
    ]
    created = subprocess.run(command, capture_output=True, text=True)
    assert created.returncode == 0, created.stderr
    assert "pending" in created.stdout
    duplicate = subprocess.run(command, capture_output=True, text=True)
    assert duplicate.returncode == 2
    response = tmp_path / "response.json"
    response.write_text(json.dumps(response_for(root)))
    imported = subprocess.run(
        [
            sys.executable,
            str(script),
            "import",
            str(root / "coordinator" / "manifest.json"),
            str(response),
            "--output-dir",
            str(tmp_path / "receipt"),
        ],
        capture_output=True,
        text=True,
    )
    assert imported.returncode == 0, imported.stderr
    assert "unvalidated" in imported.stdout
    assert "1 pending" in imported.stdout


def test_clinical_purpose_and_self_reported_credentials_never_establish_validation(
    source, tmp_path, protocol
):
    protocol["purpose"] = "clinical_adjudication"
    root, manifest = build(source, tmp_path, protocol)
    response = response_for(root)
    response["reviewer_attestation"]["qualification_statement"] = (
        "Claims to be an emergency physician."
    )
    response["reviewer_attestation"]["independent_review"] = False
    receipt = submit(root, response, tmp_path)
    assert manifest["clinical_validation_status"] == "pending"
    assert receipt["clinical_validation_status"] == "unvalidated_submission"
    assert receipt["reviewer_attestation"]["independent_review"] is False
