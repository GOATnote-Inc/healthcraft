"""Spawned public-only workers cannot erase native state or forge completion."""

import importlib
import json
import os
import signal
import subprocess
import sys
import time
from copy import deepcopy
from dataclasses import asdict
from functools import partial
from pathlib import Path

import pytest

from healthcraft.reconciliation.casebook import load_cases
from healthcraft.reconciliation.controller import (
    CommandController,
    PilotSettings,
    command_format_identity,
)


def api():
    return importlib.import_module("healthcraft.reconciliation.model_case")


def config(*, timeout=5):
    return {
        "model": "test-local:latest",
        "expected_digest": "a" * 64,
        "expected_runtime": "0.test",
        "settings": asdict(PilotSettings(attempt_timeout_seconds=timeout)),
        "command_format": command_format_identity(),
    }


def worker_receipt(cfg, *, status="terminated"):
    controller = CommandController(
        cfg["instruction"],
        cfg["tools"],
        settings=PilotSettings(**cfg["settings"]),
        command_format=cfg["command_format"],
    ).snapshot()
    controller["completion"] = {"status": "terminated", "reason": "model_finish"}
    controller["model_requests"] = 1
    identity = {
        "model": cfg["model"],
        "model_digest": cfg["expected_digest"],
        "runtime_version": cfg["expected_runtime"],
    }
    return {
        "schema_version": "healthcraft-reconciliation-model-worker/v1",
        "status": status,
        "config": deepcopy(cfg),
        "controller": controller,
        "model_exchanges": [{"index": 1, "request": {}, "response": {}, "error": None}],
        "model_calls": 1,
        "identity_before": identity,
        "identity_after": deepcopy(identity),
        "postflight_status": "matched",
        "initial_messages_sha256_expected": cfg["initial_messages_sha256"],
        "initial_messages_sha256_actual": cfg["initial_messages_sha256"],
    }


def scripted_worker(connection, cfg, output_dir, *, variant="valid"):
    # The ordinary fake worker calls actual parent handlers; no Ollama/network.
    (output_dir / "public-input.json").write_text(json.dumps(cfg))
    if variant == "missing_journal_timeout":
        time.sleep(30)
        return
    (output_dir / "model.jsonl").write_text(
        json.dumps({"event": "model_dispatched", "exchange": {"index": 1}}) + "\n"
    )
    target = (
        json.loads(cfg["instruction"].split("TARGET_JSON=")[-1])
        if "TARGET_JSON=" in cfg["instruction"]
        else None
    )
    # Read target from the public instruction only, not a test-case oracle.
    if target is None:
        import re

        target = {
            "patient_id": re.search(r"PAT-(?:[A-F0-9]{12}|[A-F0-9]{8})", cfg["instruction"])[0],
            "encounter_id": re.search(r"ENC-(?:[A-F0-9]{12}|[A-F0-9]{8})", cfg["instruction"])[0],
        }
    message = {
        "event": "call",
        "id": 1,
        "name": "updateEncounter",
        "params": {"encounter_id": target["encounter_id"], "notes": "Actual scripted-worker note"},
    }
    if variant == "wrong_id":
        message["id"] = 2
    elif variant == "bool_id":
        message["id"] = True
    elif variant == "bad_name":
        message["name"] = "createClinicalOrder"
    elif variant == "extra_field":
        message["unrequested"] = True
    elif variant == "nondict_params":
        message["params"] = []
    elif variant == "nan_params":
        message["params"]["value"] = float("nan")
    connection.send(message)
    response = connection.recv()
    (output_dir / "parent-response.json").write_text(json.dumps(response))
    if variant == "duplicate_id":
        connection.send(message)
        connection.recv()
        return
    if variant == "deadline":
        time.sleep(30)
        return
    if variant == "no_finished":
        return
    receipt = worker_receipt(cfg)
    if variant == "worker_failed":
        receipt.update(
            status="failed", error={"type": "ValueError", "message": "original worker failure"}
        )
    elif variant == "worker_interrupted":
        receipt.update(
            status="interrupted",
            error={"type": "KeyboardInterrupt", "message": "original worker interruption"},
        )
    elif variant == "wrong_identity":
        receipt["identity_after"]["model_digest"] = "b" * 64
    elif variant == "wrong_prompt":
        receipt["initial_messages_sha256_actual"] = "c" * 64
    elif variant == "wrong_config":
        receipt["config"]["settings"]["seed"] = 99
    elif variant == "postflight_error":
        receipt["postflight_error"] = {"type": "ValueError", "message": "drift"}
    elif variant == "wrong_controller":
        receipt["controller"]["completion"] = {"status": "failed"}
    elif variant == "invalid_count":
        receipt["model_calls"] = True
    elif variant == "missing_model_journal":
        (output_dir / "model.jsonl").unlink()
    elif variant == "truncated_model_journal":
        with (output_dir / "model.jsonl").open("a") as stream:
            stream.write('{"event":')
    elif variant == "duplicate_journal_key":
        (output_dir / "model.jsonl").write_text('{"event":"other","event":"model_dispatched"}\n')
    (output_dir / "receipt.json").write_text(json.dumps(receipt))
    connection.send({"event": "finished", "receipt": receipt})
    if variant == "nonzero_exit":
        os._exit(7)
    if variant == "after_finished":
        connection.send(message)


def run(tmp_path, variant="valid", *, timeout=5):
    return api().run_model_case(
        load_cases()[0],
        config(timeout=timeout),
        tmp_path / "out",
        worker_target=partial(scripted_worker, variant=variant),
    )


def test_actual_spawn_public_inputs_native_write_and_receipts(tmp_path):
    result = run(tmp_path)
    assert result["schema_version"] == "healthcraft-reconciliation-model-attempt/v2"
    assert result["status"] == "completed" and result["error"] is None
    assert result["model_calls"] == 1
    assert result["worker_exitcode"] == 0 and result["worker_cleanup"]["alive"] is False
    assert result["start_method"] == "spawn"
    output = tmp_path / "out"
    evidence = json.loads((output / "execution.json").read_text())
    assert evidence["completion"] == {"status": "completed"}
    assert len(evidence["after"]["entities"]["clinical_note"]) == 1
    assert len(evidence["calls"]) == len(evidence["audit"]) == 1
    public = json.loads((output / "worker/public-input.json").read_text())
    assert set(public) == {
        "model",
        "expected_digest",
        "expected_runtime",
        "settings",
        "command_format",
        "instruction",
        "tools",
        "initial_messages_sha256",
    }
    assert (
        "expectations" not in public
        and "scenario" not in public
        and "casebook_sha256" not in public
    )
    reply = json.loads((output / "worker/parent-response.json").read_text())
    assert (
        set(reply) == {"id", "response"}
        and reply["id"] == 1
        and reply["response"]["status"] == "ok"
    )
    assert json.loads((output / "receipt.json").read_text()) == result
    assert result["benchmark_score"] is None and result["clinical_assessment"] == "unassessed"


@pytest.mark.parametrize(
    "variant", ["wrong_id", "bool_id", "bad_name", "extra_field", "nondict_params", "nan_params"]
)
def test_malformed_worker_events_cannot_dispatch_or_disappear(tmp_path, variant):
    result = run(tmp_path, variant)
    assert result["status"] == "failed"
    evidence = json.loads((tmp_path / "out/execution.json").read_text())
    assert evidence["calls"] == evidence["audit"] == []
    assert not evidence["after"]["entities"]["clinical_note"]
    events = [json.loads(line) for line in (tmp_path / "out/parent.jsonl").read_text().splitlines()]
    assert any(event.get("event") == "worker_frame" and event.get("body_b64") for event in events)
    assert result["worker_cleanup"]["alive"] is False


@pytest.mark.parametrize(
    "variant",
    [
        "duplicate_id",
        "worker_failed",
        "wrong_identity",
        "wrong_prompt",
        "wrong_config",
        "postflight_error",
        "wrong_controller",
        "invalid_count",
        "nonzero_exit",
        "no_finished",
        "after_finished",
    ],
)
def test_no_false_completion_or_loss_after_real_write(tmp_path, variant):
    result = run(tmp_path, variant)
    assert result["status"] == "failed"
    evidence = json.loads((tmp_path / "out/execution.json").read_text())
    assert evidence["completion"]["status"] == "failed"
    assert len(evidence["after"]["entities"]["clinical_note"]) == 1
    assert len(evidence["calls"]) == 1
    assert result["worker_cleanup"]["alive"] is False
    if variant == "worker_failed":
        assert result["worker_receipt"]["error"]["message"] == "original worker failure"


def test_worker_interrupt_preserves_native_state_and_original_receipt(tmp_path):
    result = run(tmp_path, "worker_interrupted")
    assert result["status"] == "interrupted"
    assert result["worker_receipt"]["error"]["type"] == "KeyboardInterrupt"
    assert (
        len(
            json.loads((tmp_path / "out/execution.json").read_text())["after"]["entities"][
                "clinical_note"
            ]
        )
        == 1
    )


def test_hard_deadline_terminates_worker_retains_write_and_dispatch_count(tmp_path):
    start = time.monotonic()
    result = run(tmp_path, "deadline", timeout=2)
    assert time.monotonic() - start < 8
    assert result["status"] == "failed" and result["error"]["type"] == "TimeoutError"
    assert result["worker_cleanup"]["alive"] is False
    assert result["model_calls"] == 1
    assert result["worker_receipt"] is None
    assert (
        len(
            json.loads((tmp_path / "out/execution.json").read_text())["after"]["entities"][
                "clinical_note"
            ]
        )
        == 1
    )


def test_missing_worker_capture_does_not_invent_zero_model_calls(tmp_path):
    result = run(tmp_path, "missing_journal_timeout", timeout=1)
    assert result["status"] == "failed" and result["model_calls"] is None
    assert result["model_call_accounting"] == "unknown_missing_journal"


@pytest.mark.parametrize(
    "change",
    [
        "case_hash",
        "missing_setting",
        "extra_model_field",
        "bad_digest",
        "wrong_format",
        "cloud_alias",
    ],
)
def test_invalid_case_or_model_configuration_rejected_before_output(tmp_path, change):
    case = load_cases()[0]
    cfg = config()
    if change == "case_hash":
        case["scenario_sha256"] = "f" * 64
    elif change == "missing_setting":
        del cfg["settings"]["seed"]
    elif change == "extra_model_field":
        cfg["base_url"] = "http://example.invalid"
    elif change == "bad_digest":
        cfg["expected_digest"] = "A" * 64
    elif change == "wrong_format":
        cfg["command_format"]["sha256"] = "f" * 64
    else:
        cfg["model"] = "model-cloud:latest"
    with pytest.raises(ValueError):
        api().run_model_case(case, cfg, tmp_path / "out", worker_target=scripted_worker)
    assert not (tmp_path / "out").exists()


def test_existing_output_and_original_inputs_are_unchanged(tmp_path):
    output = tmp_path / "out"
    output.mkdir()
    (output / "prior").write_text("immutable")
    case, cfg = load_cases()[0], config()
    before = deepcopy((case, cfg))
    with pytest.raises(FileExistsError):
        api().run_model_case(case, cfg, output, worker_target=scripted_worker)
    assert (output / "prior").read_text() == "immutable" and (case, cfg) == before


@pytest.mark.parametrize(
    "variant", ["missing_model_journal", "truncated_model_journal", "duplicate_journal_key"]
)
def test_worker_success_without_valid_dispatch_capture_cannot_complete(tmp_path, variant):
    result = run(tmp_path, variant)
    assert result["status"] == "failed"
    assert result["model_calls"] is None
    assert (
        len(
            json.loads((tmp_path / "out/execution.json").read_text())["after"]["entities"][
                "clinical_note"
            ]
        )
        == 1
    )


def native_worker(connection, cfg, output_dir):
    import re

    from healthcraft.reconciliation.controller import RecordingOllamaClient
    from healthcraft.reconciliation.model_worker import run_worker

    class Envelopes(RecordingOllamaClient):
        def _transport_request(self, path, payload=None):
            if path == "/api/tags":
                return {"models": [{"name": self._model, "digest": cfg["expected_digest"]}]}
            if path == "/api/show":
                return {"details": {"family": "test"}, "capabilities": ["completion"]}
            if path == "/api/version":
                return {"version": cfg["expected_runtime"]}
            assert path == "/api/chat"
            assert "tools" not in payload and payload["keep_alive"] == 0
            assert payload["format"] and payload["options"]["num_ctx"] == cfg["settings"]["num_ctx"]
            encounter_id = re.search(r"ENC-(?:[A-F0-9]{12}|[A-F0-9]{8})", cfg["instruction"])[0]
            count = len(self.exchanges)
            command = {"action": "finish"}
            if count in (1, 3):
                command = {
                    "action": "call",
                    "name": "getEncounterDetails",
                    "params": {"encounter_id": encounter_id},
                }
            elif count == 2:
                command = {
                    "action": "call",
                    "name": "updateEncounter",
                    "params": {
                        "encounter_id": encounter_id,
                        "notes": "Real worker/native-parent integration",
                    },
                }
            return {
                "model": self._model,
                "done": True,
                "done_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(command)},
                "prompt_eval_count": 1,
                "eval_count": 1,
            }

    run_worker(connection, cfg, output_dir, client_factory=Envelopes)


def test_actual_worker_controller_native_envelopes_and_parent_handlers_integrate(tmp_path):
    result = api().run_model_case(
        load_cases()[0], config(), tmp_path / "out", worker_target=native_worker
    )
    assert result["status"] == "completed", result
    assert result["model_calls"] == 4
    assert result["worker_receipt"]["controller"]["completion"] == {
        "status": "terminated",
        "reason": "model_finish",
    }
    evidence = json.loads((tmp_path / "out/execution.json").read_text())
    assert len(evidence["calls"]) == len(evidence["audit"]) == 3
    notes = list(evidence["after"]["entities"]["clinical_note"].values())
    assert (
        len(notes) == 1
        and evidence["calls"][-1]["response"]["data"]["clinical_notes"][-1][1]
        == notes[0]["content"]
    )


def partial_frame_worker(connection, cfg, output_dir):
    import struct

    os.write(connection.fileno(), struct.pack("!i", 100) + b"x")
    time.sleep(10)


def blocked_reply_worker(connection, cfg, output_dir):
    import re

    encounter = re.search(r"ENC-(?:[A-F0-9]{12}|[A-F0-9]{8})", cfg["instruction"])[0]
    connection.send(
        {
            "event": "call",
            "id": 1,
            "name": "updateEncounter",
            "params": {
                "encounter_id": encounter,
                "notes": "Synthetic IPC payload " * 65536,
            },
        }
    )
    time.sleep(10)


@pytest.mark.parametrize("worker", ["partial_frame_worker", "blocked_reply_worker"])
def test_partial_pipe_frame_cannot_defeat_parent_hard_deadline(tmp_path, worker):
    root = Path(__file__).resolve().parents[2]
    code = (
        "import json; from pathlib import Path; "
        f"from tests.test_reconciliation.test_model_case import config, {worker}; "
        "from healthcraft.reconciliation.casebook import load_cases; "
        "from healthcraft.reconciliation.model_case import run_model_case; "
        f"r=run_model_case(load_cases()[0],config(timeout=1),Path({str(tmp_path / 'partial')!r}),worker_target={worker}); "
        "print(json.dumps(r))"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=4)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        pytest.fail("Partial worker pipe frame blocked the parent's hard deadline")
    assert process.returncode == 0, stderr
    receipt = json.loads(stdout)
    assert receipt["status"] == "failed" and receipt["error"]["type"] == "TimeoutError"
    assert receipt["worker_cleanup"]["alive"] is False
    assert (tmp_path / "partial/execution.json").is_file()
    if worker == "blocked_reply_worker":
        evidence = json.loads((tmp_path / "partial/execution.json").read_text())
        assert len(evidence["after"]["entities"]["clinical_note"]) == 1
        assert len(evidence["calls"]) == 1 and evidence["calls"][0]["response"]["status"] == "ok"
