"""The bounded local probe reports state fidelity separately from completion."""

import time
from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from healthcraft.llm.review_context import validate_review_context

ROOT = Path(__file__).resolve().parents[2]
spec = spec_from_file_location("local_order_probe", ROOT / "scripts/local_order_probe.py")
probe = module_from_spec(spec)
spec.loader.exec_module(probe)


class Client:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def validate_capabilities(self, *, require_tools):
        assert require_tools
        return {"model_digest": "sha256:test", "num_ctx": 4096, "seed": 42, "think": False}

    def chat(self, messages, **kwargs):
        self.calls.append(deepcopy(kwargs))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return deepcopy(result)


def action(**changes):
    return {
        "content": "",
        "stop_reason": "tool_calls",
        "tool_calls": [
            {
                "id": "native-1",
                "name": "createClinicalOrder",
                "arguments": {
                    **deepcopy(probe.ORDER_REQUEST),
                    **changes,
                },
            }
        ],
    }


def done():
    return {"content": "Done.", "stop_reason": "stop", "tool_calls": []}


@pytest.fixture
def run(monkeypatch):
    monkeypatch.setattr(probe, "source_hashes", lambda: {"source": "abc"})
    monkeypatch.setattr(probe, "runtime_identity", lambda: {"python": "test"})
    monkeypatch.delenv("HC_IDEMPOTENT_TOOLS", raising=False)

    def execute(responses, **kwargs):
        client = Client(responses)
        report = probe.run_probe(
            "ollama:synthetic-test", client_factory=lambda **kw: client, **kwargs
        )
        return report, client

    return execute


def test_actual_server_persists_exact_action_and_sealed_ungraded_trace(run):
    report, client = run([action(), done()])
    assert report["integration_passed"] is True
    assert report["action_fidelity"]["passed"] is True
    assert report["completion"]["status"] == "complete"
    assert len(client.calls) == 2
    assert all(c["max_tokens"] == 256 and c["temperature"] == 0 for c in client.calls)
    assert all([t["name"] for t in c["tools"]] == ["createClinicalOrder"] for c in client.calls)
    trajectory = report["trajectory"]
    assert trajectory["reward"] is trajectory["passed"] is trajectory["safety_gate_passed"] is None
    assert trajectory["metadata"]["grading_enabled"] is False
    assert report["benchmark_score"] is None
    assert validate_review_context(trajectory)["grading_mode"] == "profile_diagnostic"
    assert report["coverage"] == {"clinical": 0, "safety": 0}
    assert report["source_hashes_before"] == report["source_hashes_after"]
    assert report["model_before"] == report["model_after"]
    order = next(iter(report["final_state"]["order"].values()))
    task = report["final_state"]["clinical_task"][order["task_id"]]
    assert task["priority"] == "urgent"
    assert task["notes"] == probe.ORDER_REQUEST["indication"]


@pytest.mark.parametrize(
    "change",
    [
        {"priority": "routine"},
        {"indication": "Different"},
        {"details": {"name": "Wrong"}},
        {"encounter_id": "ENC-FFFFFFFF"},
    ],
)
def test_wrong_persisted_action_or_failed_tool_never_passes(run, change):
    report, _ = run([action(**change), done()])
    assert report["completion"]["status"] == "complete"
    assert report["integration_passed"] is False
    assert report["action_fidelity"]["passed"] is False


def test_text_claim_without_actual_order_fails(run):
    report, _ = run([done()])
    assert report["integration_passed"] is False
    assert report["final_state"]["order"] == {}


def test_duplicate_actual_order_is_not_hidden(run):
    report, _ = run([action(), action(), done()])
    assert len(report["final_state"]["order"]) == 2
    assert report["integration_passed"] is False


@pytest.mark.parametrize(
    "end",
    [
        {"content": "Cut off", "stop_reason": "length", "tool_calls": []},
        RuntimeError("local runtime failed"),
    ],
)
def test_persisted_action_does_not_hide_incomplete_execution(run, end):
    report, _ = run([action(), end])
    assert report["action_fidelity"]["passed"] is True
    assert report["completion"]["status"] == "incomplete"
    assert report["trajectory"]["error"]
    assert report["integration_passed"] is False


def test_four_call_budget_prevents_fifth_actual_model_request(run):
    report, client = run([action()] * 5)
    assert len(client.calls) == report["model_call_count"] == 4
    assert report["budget_exhausted"] is True
    assert report["integration_passed"] is False


def test_source_drift_fails_even_when_action_is_correct(run, monkeypatch):
    hashes = iter([{"source": "before"}, {"source": "after"}])
    monkeypatch.setattr(probe, "source_hashes", lambda: next(hashes))
    report, _ = run([action(), done()])
    assert report["action_fidelity"]["passed"] is True
    assert report["provenance_stable"] is False
    assert report["integration_passed"] is False


def test_missing_runtime_is_captured_without_model_retry(run):
    report, client = run([RuntimeError("offline")])
    assert len(client.calls) == 1
    assert report["integration_passed"] is False
    assert report["exchanges"][0]["error"] == "RuntimeError: offline"


def test_setup_failure_is_saved_as_incomplete_review_capture(monkeypatch):
    def unavailable(**kwargs):
        raise RuntimeError("No installed model")

    report = probe.run_probe("ollama:synthetic-test", client_factory=unavailable)
    assert report["model_call_count"] == 0
    assert report["integration_passed"] is False
    assert report["errors"][0]["stage"] == "model_setup"
    assert (
        report["trajectory"]["metadata"]["review_context"]["payload"]["capture_status"]
        == "incomplete"
    )


def test_existing_output_is_rejected_before_any_execution(tmp_path, monkeypatch):
    path = tmp_path / "report.json"
    path.write_text("immutable")
    monkeypatch.setattr(probe, "run_probe", lambda *a, **kw: pytest.fail("must not run"))
    with pytest.raises(FileExistsError):
        probe.main(["--agent-model", "ollama:synthetic-test", "--output", str(path)])
    assert path.read_text() == "immutable"


@pytest.mark.parametrize("model", ["gpt-5.4", "ollama:nano-cloud", ""])
def test_nonlocal_or_cloud_identifiers_rejected_before_factory(model):
    with pytest.raises(ValueError):
        probe.run_probe(model, client_factory=lambda **kw: pytest.fail("must not connect"))


def test_hard_request_timeout_records_incomplete_attempt_without_retry(run, monkeypatch):
    def stalled(self, messages, **kwargs):
        self.calls.append(kwargs)
        time.sleep(1)
        return done()

    monkeypatch.setattr(Client, "chat", stalled)
    started = time.monotonic()
    report, client = run([], timeout=0.02)
    assert time.monotonic() - started < 0.5
    assert len(client.calls) == 1
    assert report["completion"]["status"] == "incomplete"
    assert "TimeoutError" in report["exchanges"][0]["error"]


def test_model_digest_drift_fails_even_with_correct_order(run, monkeypatch):
    infos = iter([{"model_digest": "before"}, {"model_digest": "after"}])
    monkeypatch.setattr(Client, "validate_capabilities", lambda *a, **kw: next(infos))
    report, _ = run([action(), done()])
    assert report["action_fidelity"]["passed"] is True
    assert report["provenance_stable"] is False
    assert report["integration_passed"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("priority", "routine"),
        ("notes", "wrong"),
        ("encounter_id", "ENC-FFFFFFFF"),
        ("description", '{"details": {}}'),
    ],
)
def test_linked_task_corruption_is_detected_independently(field, value):
    from dataclasses import replace

    from healthcraft.mcp.server import create_server
    from healthcraft.tasks.history_execution import ExecutionRecorder
    from healthcraft.world.state import WorldState

    world = WorldState()
    world.put_entity(
        "encounter", probe.ORDER_REQUEST["encounter_id"], {"patient_id": "PAT-FEED0001"}
    )
    recorder = ExecutionRecorder(create_server(world), world)
    response = recorder.call("createClinicalOrder", probe.ORDER_REQUEST)
    task_id = response["data"]["task_id"]
    original = world.get_entity("clinical_task", task_id)
    world.put_entity("clinical_task", task_id, replace(original, **{field: value}))
    assert probe.verify_action(world, recorder.calls)["passed"] is False


@pytest.mark.parametrize("final_reason", ["missing", None])
def test_native_ollama_missing_stop_provenance_never_becomes_complete(monkeypatch, final_reason):
    from healthcraft.llm.local_models import OllamaClient

    terminal = {"done": True, "message": {"content": "Done."}}
    if final_reason != "missing":
        terminal["done_reason"] = final_reason
    envelopes = iter(
        [
            {
                "done": True,
                "done_reason": "stop",
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "createClinicalOrder",
                                "arguments": probe.ORDER_REQUEST,
                            }
                        },
                    ],
                },
            },
            terminal,
        ]
    )
    actual_calls = []

    def factory(**kwargs):
        client = OllamaClient(**kwargs)
        monkeypatch.setattr(
            client,
            "validate_capabilities",
            lambda **kw: {
                "capabilities": ["completion", "tools"],
                "model_digest": "sha256:test",
            },
        )

        def request(path, payload):
            assert path == "/api/chat"
            actual_calls.append(deepcopy(payload))
            return next(envelopes)

        monkeypatch.setattr(client, "_request", request)
        return client

    report = probe.run_probe("ollama:synthetic-test", client_factory=factory)
    assert len(actual_calls) == 2
    assert actual_calls[0]["options"]["num_predict"] == 256
    assert report["action_fidelity"]["passed"] is True
    assert report["completion"]["status"] != "complete"
    assert report["integration_passed"] is False


def test_fabricated_linked_task_timestamps_do_not_pass_fidelity():
    from dataclasses import replace
    from datetime import timedelta

    from healthcraft.mcp.server import create_server
    from healthcraft.tasks.history_execution import ExecutionRecorder
    from healthcraft.world.state import WorldState

    world = WorldState()
    world.put_entity(
        "encounter", probe.ORDER_REQUEST["encounter_id"], {"patient_id": "PAT-FEED0001"}
    )
    recorder = ExecutionRecorder(create_server(world), world)
    response = recorder.call("createClinicalOrder", probe.ORDER_REQUEST)
    task_id = response["data"]["task_id"]
    original = world.get_entity("clinical_task", task_id)
    world.put_entity(
        "clinical_task",
        task_id,
        replace(
            original,
            created_at=world.timestamp + timedelta(days=365),
            updated_at=world.timestamp + timedelta(days=365),
        ),
    )
    assert probe.verify_action(world, recorder.calls)["passed"] is False
