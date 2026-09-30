"""One-shot local source reading uses actual tools and native completion evidence."""

import json
import time
from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from jsonschema import validate

ROOT = Path(__file__).resolve().parents[2]
spec = spec_from_file_location("local_care_probe", ROOT / "scripts/local_care_probe.py")
probe = module_from_spec(spec)
spec.loader.exec_module(probe)


@pytest.fixture
def native(monkeypatch):
    calls = []
    replies = []
    metadata_reads = {}
    monkeypatch.setattr(probe, "source_hashes", lambda: {"synthetic_source": "frozen"})
    monkeypatch.setattr(probe, "runtime_identity", lambda: {"python": "test"})

    def request(client, path, payload=None):
        calls.append({"model": client._model, "path": path, "payload": deepcopy(payload)})
        if path == "/api/tags":
            metadata_reads[client._model] = metadata_reads.get(client._model, 0) + 1
            return {"models": [{"name": client._model, "digest": "a" * 64}]}
        if path == "/api/show":
            # Text-only capability is sufficient for both arms.
            return {"capabilities": ["completion"], "details": {"family": "synthetic"}}
        if path == "/api/version":
            return {"version": "test-runtime"}
        assert path == "/api/chat"
        item = replies.pop(0)
        if callable(item):
            return item(client, payload)
        if isinstance(item, Exception):
            raise item
        return deepcopy(item)

    monkeypatch.setattr(probe.OllamaClient, "_request", request)
    return calls, replies, metadata_reads


def envelope(answer, reason="stop", **changes):
    return {
        "done": True,
        "done_reason": reason,
        "message": {"role": "assistant", "content": json.dumps(answer)},
        **changes,
    }


def correct_answer():
    return probe.expected_extraction(probe.build_evidence())


def test_fixture_runs_actual_tools_preserves_source_and_audit():
    evidence = probe.build_evidence()
    assert [call["name"] for call in evidence["actual_calls"]] == [
        "getEncounterDetails",
        "validateTreatmentPlan",
        "processDischarge",
    ]
    details, validation, discharge = [call["response"] for call in evidence["actual_calls"]]
    assert details["status"] == discharge["status"] == "ok"
    assert details["data"]["meds_administered"] == []
    rows = {
        row["source_collection"]: row["source_data"] for row in details["data"]["authored_care"]
    }
    assert rows["active_orders"] == probe.SYNTHETIC_PATIENT["active_orders"]
    assert rows["current_management"] == probe.SYNTHETIC_PATIENT["current_management"]
    assert validation["code"] == "unresolved_medication_context"
    assert "not established" in discharge["data"]["discharge_summary"]
    assert len(evidence["audit_log"]) == 3
    for index, (call, audit) in enumerate(zip(evidence["actual_calls"], evidence["audit_log"])):
        assert call["audit_index"] == index
        assert call["params"] == audit["params"]
        assert call["name"] == audit["tool_name"]
    assert evidence["final_state"]["clinical_note"]
    assert evidence["fixture_verified"] is True


def test_actual_fixture_calls_obey_published_tool_schemas_and_patient_links():
    schemas = {
        tool["name"]: tool["parameters"]
        for tool in json.loads((ROOT / "configs/mcp-tools.json").read_text())["tools"]
    }
    evidence = probe.build_evidence()
    for call in evidence["actual_calls"]:
        validate(call["params"], schemas[call["name"]])
    validation = evidence["actual_calls"][1]
    assert validation["params"]["patient_id"] == evidence["ids"]["patient_id"]
    assert validation["params"]["encounter_id"] == evidence["ids"]["encounter_id"]


def test_one_fixed_text_request_per_model_with_raw_evidence(native, monkeypatch):
    calls, replies, metadata_reads = native
    monkeypatch.setenv("OPENAI_API_KEY", "SENTINEL-SECRET-NEVER-CAPTURE")
    monkeypatch.setenv("HC_OLLAMA_BASE_URL", "https://example.invalid")
    expected = correct_answer()
    replies.extend([envelope(expected), envelope(expected)])
    report = probe.run_probe()
    chats = [call for call in calls if call["path"] == "/api/chat"]
    assert len(chats) == 2
    assert len(metadata_reads) == 2 and set(metadata_reads.values()) == {2}
    assert chats[0]["payload"]["messages"] == chats[1]["payload"]["messages"]
    for chat in chats:
        assert "tools" not in chat["payload"]
        assert chat["payload"]["keep_alive"] == 0
        assert chat["payload"]["options"] == {
            "num_ctx": 8192,
            "seed": 42,
            "temperature": 0,
            "num_predict": 768,
        }
    assert report["scheduled_attempts"] == 2
    assert report["benchmark_score"] is None
    assert report["clinical_assessed"] is report["safety_assessed"] is False
    assert "SENTINEL-SECRET-NEVER-CAPTURE" not in json.dumps(report)
    for attempt in report["attempts"]:
        assert attempt["model_call_count"] == 1
        assert attempt["completion"]["status"] == "complete"
        assert attempt["source_reading"]["status"] == "verified"
        assert attempt["model_before"] == attempt["model_after"]
        assert attempt["model_before"]["base_url"] == "http://127.0.0.1:11434"
        assert attempt["raw_exchanges"][0]["response"]["done_reason"] == "stop"
    assert report["provenance_stable"] is True


@pytest.mark.parametrize("reason", [None, "length", "unexpected", "content_filter"])
def test_correct_extraction_does_not_hide_unknown_or_incomplete_generation(native, reason):
    _, replies, _ = native
    replies.extend([envelope(correct_answer(), reason=reason), envelope(correct_answer())])
    report = probe.run_probe()
    failed = report["attempts"][0]
    assert failed["completion"]["status"] != "complete"
    assert failed["source_reading"]["status"] == "not_assessed"
    assert report["attempts"][1]["source_reading"]["status"] == "verified"


def test_missing_native_stop_reason_not_inferred(native):
    _, replies, _ = native
    response = envelope(correct_answer())
    del response["done_reason"]
    replies.extend([response, envelope(correct_answer())])
    assert probe.run_probe()["attempts"][0]["completion"]["status"] == "unknown"


@pytest.mark.parametrize(
    "message",
    [
        {"role": "assistant", "content": "I refuse", "refusal": "blocked"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "processDischarge", "arguments": {}}}],
        },
    ],
)
def test_refusal_or_unadvertised_tool_call_never_executes_or_passes(native, message):
    _, replies, _ = native
    replies.extend([envelope({}, message=message), envelope(correct_answer())])
    report = probe.run_probe()
    assert report["attempts"][0]["source_reading"]["status"] == "not_assessed"
    assert len(report["evidence"]["actual_calls"]) == 3
    assert len(report["evidence"]["audit_log"]) == 3


@pytest.mark.parametrize("mutation", ["invent_route", "held_as_given", "valid_true", "no_doses"])
def test_source_distortions_report_field_mismatches_without_clinical_scoring(native, mutation):
    _, replies, _ = native
    answer = correct_answer()
    if mutation == "invent_route":
        answer["authored_care"][0]["source_data"][0]["route"] = "PO"
    elif mutation == "held_as_given":
        answer["meds_administered"] = [{"medication_name": "SYNTHETIC-HELD-B"}]
    elif mutation == "valid_true":
        answer["validation"] = {"status": "ok", "valid": True}
    else:
        answer["discharge_treatments"] = "No medications administered during visit"
    replies.extend([envelope(answer), envelope(correct_answer())])
    attempt = probe.run_probe()["attempts"][0]
    assert attempt["completion"]["status"] == "complete"
    assert attempt["source_reading"]["status"] == "mismatch"
    assert not all(attempt["source_reading"]["fields_match"].values())
    assert "score" not in attempt["source_reading"]


def test_runtime_error_is_retained_and_second_scheduled_attempt_still_runs(native):
    calls, replies, _ = native
    replies.extend([RuntimeError("synthetic offline failure"), envelope(correct_answer())])
    report = probe.run_probe()
    assert len([c for c in calls if c["path"] == "/api/chat"]) == 2
    assert report["attempts"][0]["status"] == "failed"
    assert report["attempts"][0]["raw_exchanges"][0]["error"]
    assert report["attempts"][1]["source_reading"]["status"] == "verified"


def test_wall_clock_deadline_has_no_retry(native):
    calls, replies, _ = native

    def slow(client, payload):
        time.sleep(1)
        return envelope({})

    replies.extend([slow, envelope(correct_answer())])
    started = time.monotonic()
    report = probe.run_probe(timeout=0.02)
    assert time.monotonic() - started < 0.5
    assert report["attempts"][0]["status"] == "failed"
    assert len([c for c in calls if c["path"] == "/api/chat"]) == 2


def test_model_digest_drift_and_source_drift_are_not_accepted(native, monkeypatch):
    _, replies, _ = native
    replies.extend([envelope(correct_answer()), envelope(correct_answer())])
    before_after = iter([{"source": "before"}, {"source": "after"}])
    monkeypatch.setattr(probe, "source_hashes", lambda: next(before_after))
    report = probe.run_probe()
    assert report["provenance_stable"] is False
    assert all(a["source_reading"]["status"] == "verified" for a in report["attempts"])
    assert report["diagnostic_status"] == "invalid_provenance"


def test_missing_model_setup_retains_both_scheduled_failures():
    def missing(**kwargs):
        raise RuntimeError("Synthetic missing installed model")

    report = probe.run_probe(client_factory=missing)
    assert len(report["attempts"]) == report["scheduled_attempts"] == 2
    assert all(a["status"] == "failed" and a["model_call_count"] == 0 for a in report["attempts"])


@pytest.mark.parametrize(
    "content", ['{"validation":null,"validation":{}}', '{"value":NaN}', "not JSON"]
)
def test_invalid_or_duplicate_key_json_is_not_scored(native, content):
    _, replies, _ = native
    replies.extend(
        [
            envelope({}, message={"role": "assistant", "content": content}),
            envelope(correct_answer()),
        ]
    )
    attempt = probe.run_probe()["attempts"][0]
    assert attempt["source_reading"]["status"] == "invalid_format"


@pytest.mark.parametrize(
    "models",
    [
        ("gpt-5.4", "ollama:local"),
        ("ollama:cloud-one", "ollama:local"),
        ("ollama:same", "ollama:same"),
        ("ollama:one",),
    ],
)
def test_nonlocal_duplicate_or_wrong_scheduled_model_count_rejected(models):
    with pytest.raises(ValueError):
        probe.run_probe(models=models, client_factory=lambda **kw: pytest.fail("No access"))


def test_existing_output_refused_before_execution(tmp_path, monkeypatch):
    path = tmp_path / "probe.json"
    path.write_text("immutable")
    monkeypatch.setattr(probe, "run_probe", lambda **kw: pytest.fail("No access"))
    with pytest.raises(FileExistsError):
        probe.main(["--output", str(path)])
    assert path.read_text() == "immutable"


def test_cli_journals_all_scheduled_attempts_before_model_access(tmp_path, native, monkeypatch):
    path = tmp_path / "new.json"
    _, replies, _ = native

    def check_journal(client, payload):
        current = json.loads(path.read_text())
        assert current["scheduled_attempts"] == 2
        assert [a["status"] for a in current["attempts"]] == ["started", "scheduled"]
        return envelope(correct_answer())

    replies.extend([check_journal, envelope(correct_answer())])
    assert probe.main(["--output", str(path)]) == 0
    final = json.loads(path.read_text())
    assert len(final["attempts"]) == 2
    assert all(a["status"] == "finished" for a in final["attempts"])


def test_model_digest_change_is_explicit_even_with_correct_extraction(native, monkeypatch):
    _, replies, _ = native
    replies.extend([envelope(correct_answer()), envelope(correct_answer())])
    original = probe.OllamaClient._request
    reads = {}

    def drift(client, path, payload=None):
        result = original(client, path, payload)
        if path == "/api/tags":
            reads[client._model] = reads.get(client._model, 0) + 1
            if reads[client._model] == 2:
                result["models"][0]["digest"] = "b" * 64
        return result

    monkeypatch.setattr(probe.OllamaClient, "_request", drift)
    report = probe.run_probe()
    assert report["diagnostic_status"] == "invalid_provenance"
    assert all(not a["model_provenance_stable"] for a in report["attempts"])


@pytest.mark.parametrize(
    "raw",
    [
        {"done": False, "done_reason": "stop", "message": {"content": "partial"}},
        {"done": True, "done_reason": "stop", "message": None},
    ],
)
def test_malformed_native_envelope_is_retained_without_assessment(native, raw):
    _, replies, _ = native
    replies.extend([raw, envelope(correct_answer())])
    first = probe.run_probe()["attempts"][0]
    assert first["raw_exchanges"][0]["response"] == raw
    assert first["source_reading"]["status"] == "not_assessed"
    assert first["status"] == "failed"


def test_summary_keeps_scheduled_attempted_completed_and_unassessed_distinct(native):
    _, replies, _ = native
    replies.extend([envelope(correct_answer(), reason="length"), envelope(correct_answer())])
    report = probe.run_probe()
    assert report["execution_counts"] == {
        "scheduled": 2,
        "inference_attempted": 2,
        "completed": 1,
        "source_reading_assessed": 1,
        "clinical_unassessed": 2,
        "safety_unassessed": 2,
    }


def test_corrupt_persisted_discharge_note_refuses_both_inference_requests(native, monkeypatch):
    calls, _, _ = native
    original = probe.ExecutionRecorder.call

    def corrupt(recorder, name, params):
        response = original(recorder, name, params)
        if name == "processDischarge":
            note = next(iter(recorder._world.list_entities("clinical_note").values()))
            note["content"] = "Tampered persisted evidence"
        return response

    monkeypatch.setattr(probe.ExecutionRecorder, "call", corrupt)
    report = probe.run_probe()
    assert report["evidence"]["fixture_verified"] is False
    assert not [c for c in calls if c["path"] == "/api/chat"]
    assert all(a["status"] == "failed" for a in report["attempts"])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_output_tokens": 1025},
        {"max_output_tokens": True},
        {"timeout": float("nan")},
        {"timeout": float("inf")},
        {"timeout": 61},
        {"timeout": 0},
        {"timeout": True},
    ],
)
def test_nonfinite_or_unbounded_limits_rejected_before_runtime(kwargs):
    with pytest.raises(ValueError):
        probe.run_probe(client_factory=lambda **kw: pytest.fail("No runtime access"), **kwargs)


def test_cli_harness_failure_preserves_latest_attempt_journal(tmp_path, monkeypatch):
    path = tmp_path / "new.json"

    def partial(*, progress, **kwargs):
        report = probe._scheduled(probe.MODELS)
        report["attempts"][0]["status"] = "finished"
        report["attempts"][0]["raw_exchanges"] = [{"response": {"done": True}}]
        progress(report)
        raise RuntimeError("Failure before second scheduled attempt")

    monkeypatch.setattr(probe, "run_probe", partial)
    assert probe.main(["--output", str(path)]) == 1
    report = json.loads(path.read_text())
    assert report["scheduled_attempts"] == 2
    assert report["attempts"][0]["raw_exchanges"]
    assert report["attempts"][1]["status"] == "scheduled"
    assert report["diagnostic_status"] == "harness_failure"


@pytest.mark.parametrize("role", ["user", "tool", "system", None, "missing"])
def test_native_nonassistant_or_missing_role_never_proves_completion(native, role):
    _, replies, _ = native
    raw = envelope(correct_answer())
    if role == "missing":
        del raw["message"]["role"]
    else:
        raw["message"]["role"] = role
    replies.extend([raw, envelope(correct_answer())])
    report = probe.run_probe()
    first = report["attempts"][0]
    assert first["status"] == "failed"
    assert first["completion"]["status"] != "complete"
    assert first["source_reading"]["status"] == "not_assessed"
    assert first["raw_exchanges"][0]["response"] == raw
    assert any("role" in error["error"] for error in first["errors"])
    assert report["attempts"][1]["source_reading"]["status"] == "verified"


@pytest.mark.parametrize(
    "tool,field,bad_value",
    [
        ("getEncounterDetails", "patient_id", "PAT-WRONG"),
        ("getEncounterDetails", "id", "ENC-WRONG"),
        ("getEncounterDetails", "chief_complaint", "Invented source complaint"),
        ("processDischarge", "patient_id", "PAT-WRONG"),
        ("processDischarge", "encounter_id", "ENC-WRONG"),
        ("processDischarge", "discharge_id", "NOTE-WRONG"),
    ],
)
def test_unbound_tool_response_refuses_inference(native, monkeypatch, tool, field, bad_value):
    calls, _, _ = native
    real_create = probe.create_server

    def create(world):
        server = real_create(world)
        actual_call = server.call_tool

        def corrupt(name, params):
            response = actual_call(name, params)
            if name == tool:
                response["data"][field] = bad_value
            return response

        server.call_tool = corrupt
        return server

    monkeypatch.setattr(probe, "create_server", create)
    report = probe.run_probe()
    assert report["evidence"]["fixture_verified"] is False
    assert not [call for call in calls if call["path"] == "/api/chat"]
    assert all(a["status"] == "failed" for a in report["attempts"])


def test_dependency_constraint_manifest_is_bound_to_source_identity():
    import hashlib

    constraint = ROOT / "constraints-security.txt"
    assert constraint.is_file()
    assert (
        probe.source_hashes()[constraint.name]
        == hashlib.sha256(constraint.read_bytes()).hexdigest()
    )


def test_dispatch_and_raw_response_are_journaled_before_postflight(tmp_path, native, monkeypatch):
    path = tmp_path / "durable.json"
    _, replies, _ = native
    response = envelope(correct_answer())

    def check_dispatch(client, payload):
        journal = json.loads(path.read_text())
        attempt = journal["attempts"][0]
        assert attempt["model_call_count"] == 1
        assert journal["execution_counts"]["inference_attempted"] == 1
        assert attempt["request_state"] == "dispatch_started"
        assert attempt["raw_exchanges"][0]["request"] == payload
        assert attempt["raw_exchanges"][0]["response"] is None
        return response

    replies.extend([check_dispatch, envelope(correct_answer())])
    original = probe.OllamaClient._request
    reads = 0

    def check_response(client, endpoint, payload=None):
        nonlocal reads
        if client._model == probe.MODELS[0].removeprefix("ollama:") and endpoint == "/api/tags":
            reads += 1
            if reads == 2:
                attempt = json.loads(path.read_text())["attempts"][0]
                assert attempt["raw_exchanges"][0]["response"] == response
                assert attempt["request_state"] == "response_received"
        return original(client, endpoint, payload)

    monkeypatch.setattr(probe.OllamaClient, "_request", check_response)
    assert probe.main(["--output", str(path)]) == 0
    assert reads == 2
    assert all(
        a["source_reading"]["status"] == "verified"
        for a in json.loads(path.read_text())["attempts"]
    )


def test_interrupted_journal_update_preserves_previous_scheduled_evidence(
    tmp_path, native, monkeypatch
):
    path = tmp_path / "journal.json"
    original_dump = probe.json.dump
    interrupted = False

    def interrupted_dump(value, stream, **kwargs):
        nonlocal interrupted
        if "evidence" in value and not interrupted:
            interrupted = True
            stream.write('{"partial":')
            raise OSError("Synthetic interrupted journal write")
        return original_dump(value, stream, **kwargs)

    monkeypatch.setattr(probe.json, "dump", interrupted_dump)
    assert probe.main(["--output", str(path)]) == 1
    journal = json.loads(path.read_text())
    assert journal["scheduled_attempts"] == 2
    assert len(journal["attempts"]) == 2
    assert journal["diagnostic_status"] == "harness_failure"
    assert "interrupted journal write" in journal["harness_error"]
