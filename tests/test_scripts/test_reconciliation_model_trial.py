"""Direct host pilot retains one attempted run and the real public response."""

import base64
import hashlib
import importlib
import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from healthcraft.reconciliation.controller import (
    PUBLIC_TOOLS,
    CommandController,
    PilotSettings,
    canonical_json,
)
from healthcraft.reconciliation.service import ReconciliationSession


@pytest.fixture
def api():
    return importlib.import_module("scripts.reconciliation_model_trial")


@pytest.fixture
def aliased_api(api, tmp_path, monkeypatch):
    """Load the real runner through a portable checkout symlink, without access."""
    checkout = tmp_path / "canonical-checkout"
    files = {
        "scripts/reconciliation_model_trial.py": Path(api.__file__).read_bytes(),
        "src/healthcraft/llm/local_models.py": b"# local provider fixture\n",
        "src/healthcraft/reconciliation/component.py": b"# component fixture\n",
        "configs/mcp-tools.json": b'{"tools":[]}\n',
        "pyproject.toml": b"# project fixture\n",
        "constraints-fixture.txt": b"# dependency fixture\n",
    }
    for relative, content in files.items():
        path = checkout / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    alias = tmp_path / "checkout-alias"
    alias.symlink_to(checkout, target_is_directory=True)
    path = alias / "scripts/reconciliation_model_trial.py"
    spec = importlib.util.spec_from_file_location("aliased_reconciliation_model_trial", path)
    module = importlib.util.module_from_spec(spec)
    # The runner adjusts sys.path on import; keep that change local to this test.
    monkeypatch.setattr(sys, "path", list(sys.path))
    spec.loader.exec_module(module)
    assert module.ROOT == checkout.resolve()
    assert Path(module.__file__) != Path(module.__file__).resolve()
    return module, checkout, files


def test_source_hashes_accept_checkout_alias_and_detect_actual_changes(aliased_api):
    module, checkout, files = aliased_api
    expected = {
        relative: hashlib.sha256(content).hexdigest() for relative, content in files.items()
    }
    assert module._source_hashes() == expected
    assert module._source_hashes() == expected
    relative = "src/healthcraft/reconciliation/component.py"
    changed = b"# changed component fixture\n"
    (checkout / relative).write_bytes(changed)
    after = module._source_hashes()
    assert after == {**expected, relative: hashlib.sha256(changed).hexdigest()}


def test_symlinked_runner_keeps_before_after_hashes_on_preparation_failure(aliased_api, tmp_path):
    module, _, _ = aliased_api

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid config must not access discovery or a model")

    result = module.run_trial(
        model_config={},
        instruction="public",
        output_dir=tmp_path / "retained-attempt",
        backend_container="owned-backend",
        process_runner=forbidden,
        client_factory=forbidden,
    )
    assert result["failure_stage"] == "preparation"
    assert result["model_calls"] == 0
    assert result["scheduled_attempts"] == 1
    assert result["source_hashes_before"] == result["source_hashes_after"]
    assert result["sources_unchanged"] is True
    assert "source_identity_error" not in result


@pytest.mark.parametrize("through_symlink", [False, True])
def test_source_hashes_refuse_script_resolving_outside_declared_root(
    aliased_api, tmp_path, monkeypatch, through_symlink
):
    module, checkout, _ = aliased_api
    outside = tmp_path / "outside.py"
    outside.write_text("# outside declared source root\n")
    path = outside
    if through_symlink:
        path = checkout / "scripts/outside-link.py"
        path.symlink_to(outside)
    monkeypatch.setattr(module, "__file__", str(path))
    with pytest.raises(ValueError):
        module._source_hashes()


def config(instruction="public"):
    tools = [
        tool
        for tool in json.loads(
            (Path(__file__).resolve().parents[2] / "configs/mcp-tools.json").read_text()
        )["tools"]
        if tool["name"] in PUBLIC_TOOLS
    ]
    messages = CommandController(instruction, tools).snapshot()["messages"]
    return {
        "model": "local-test:latest",
        "expected_digest": "a" * 64,
        "expected_runtime": "0.34.4",
        "settings": asdict(PilotSettings()),
        "initial_messages_sha256": hashlib.sha256(
            canonical_json(messages).encode("utf-8")
        ).hexdigest(),
    }


def fake_model_factory(outputs, instances, *, pre_error=None, post_error=None):
    class Client:
        def __init__(self, **kwargs):
            self.settings = kwargs["settings"]
            self.sink = kwargs["event_sink"]
            self.exchanges = []
            self.identity_before = self.identity_after = None
            self.post_calls = 0
            self.inputs = []
            self.outputs = iter(outputs)
            instances.append(self)

        def preflight(self):
            self.identity_before = {"model_digest": "a" * 64, "runtime_version": "0.34.4"}
            if pre_error:
                raise pre_error
            return deepcopy(self.identity_before)

        def postflight(self):
            self.post_calls += 1
            self.identity_after = {
                "model_digest": "b" * 64 if post_error else "a" * 64,
                "runtime_version": "0.34.4",
            }
            if post_error:
                raise post_error
            return deepcopy(self.identity_after)

        def chat(self, messages, **kwargs):
            self.inputs.append(deepcopy(messages))
            event = {"request": {"messages": messages, **kwargs}, "response": None}
            self.exchanges.append(event)
            self.sink({"event": "model_dispatched", "exchange": deepcopy(event)})
            content = next(self.outputs)
            if isinstance(content, BaseException):
                raise content
            event["response"] = {"content": content}
            self.sink({"event": "model_returned", "exchange": deepcopy(event)})
            return {"content": content, "stop_reason": "stop", "tool_calls": []}

    return Client


def bridge(service, seen, *, failure=None):
    def run(argv, **kwargs):
        seen.append({"argv": list(argv), "kwargs": deepcopy(kwargs)})
        assert kwargs.get("shell", False) is False
        assert argv[:3] == ["docker", "exec", "-i"]
        assert argv[3] == "owned-backend"
        assert kwargs["timeout"] == 30
        if failure:
            raise failure
        request = json.loads(kwargs["input"])
        body = b"" if request["payload"] is None else json.dumps(request["payload"]).encode()
        status, response = service.handle(
            request["method"], request["path"], body, "Bearer direct-test"
        )
        wrapped = {
            "http_status": status,
            "body_b64": base64.b64encode(json.dumps(response).encode()).decode(),
        }
        return SimpleNamespace(returncode=0, stdout=json.dumps(wrapped), stderr="")

    return run


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setenv("HEALTHCRAFT_IDEMPOTENT_TOOLS", "1")
    session = ReconciliationSession(token="direct-test")
    yield session
    session.close()


def test_one_attempt_uses_exact_public_messages_and_no_success_claim(api, service, tmp_path):
    instances, processes = [], []
    factory = fake_model_factory(
        [
            '{"action":"call","name":"getPatientHistory","params":{"patient_id":"PAT-AAAAAAAA"}}',
            '{"action":"finish"}',
        ],
        instances,
    )
    output = tmp_path / "trial"
    result = api.run_trial(
        model_config=config("same public instruction"),
        instruction="same public instruction",
        output_dir=output,
        backend_container="owned-backend",
        process_runner=bridge(service, processes),
        client_factory=factory,
    )
    assert result["execution_kind"] == "direct_http_via_coordinator"
    assert result["status"] == "terminated"
    assert result["scheduled_attempts"] == 1
    assert result["benchmark_score"] is None
    assert result["clinical_assessment"] == "unassessed"
    assert result["config"] == config("same public instruction")
    assert len(instances[0].inputs) == 2
    assert instances[0].post_calls == 1
    assert len(processes) == 2  # Discovery + one actual tool command.
    assert (
        json.loads(instances[0].inputs[0][1]["content"])["instruction"] == "same public instruction"
    )
    assert "tools" in json.loads(instances[0].inputs[0][1]["content"])
    assert result["controller"]["calls"][0]["response"]["data"]["id"] == "PAT-AAAAAAAA"
    assert json.loads((output / "receipt.json").read_text()) == result
    assert (output / "scheduled.json").exists()
    assert result["source_hashes_before"] == result["source_hashes_after"]
    assert "direct-test" not in json.dumps(result)


def test_journals_are_written_before_transport_and_after_raw_response(api, service, tmp_path):
    output = tmp_path / "trial"
    instances, processes = [], []
    underlying = bridge(service, processes)

    def run(argv, **kwargs):
        assert (output / "scheduled.json").exists()
        events = [
            json.loads(line) for line in (output / "transport.jsonl").read_text().splitlines()
        ]
        assert events[-1]["event"] == "requested"
        return underlying(argv, **kwargs)

    result = api.run_trial(
        model_config=config(),
        instruction="public",
        output_dir=output,
        backend_container="owned-backend",
        process_runner=run,
        client_factory=fake_model_factory(['{"action":"finish"}'], instances),
    )
    assert result["status"] == "terminated"
    events = [json.loads(line) for line in (output / "transport.jsonl").read_text().splitlines()]
    assert [event["event"] for event in events] == ["requested", "returned", "validated"]
    model_events = [json.loads(line) for line in (output / "model.jsonl").read_text().splitlines()]
    assert [event["event"] for event in model_events] == ["model_dispatched", "model_returned"]


@pytest.mark.parametrize(
    "fault",
    ["missing_setting", "extra_setting", "extra_key", "bad_digest", "nonfinite", "duplicate_json"],
)
def test_invalid_config_is_a_retained_preparation_failure(api, service, tmp_path, fault):
    value = config()
    if fault == "missing_setting":
        del value["settings"]["seed"]
    elif fault == "extra_setting":
        value["settings"]["unknown"] = 1
    elif fault == "extra_key":
        value["api_key"] = "do-not-persist"
    elif fault == "bad_digest":
        value["expected_digest"] = "ABCD"
    elif fault == "nonfinite":
        value["settings"]["temperature"] = float("inf")
    else:
        value = tmp_path / "config.json"
        value.write_text('{"model":"one","model":"two"}')
    calls = []
    result = api.run_trial(
        model_config=value,
        instruction="public",
        output_dir=tmp_path / "trial",
        backend_container="owned-backend",
        process_runner=lambda *a, **k: calls.append(a),
    )
    assert result["status"] == "failed"
    assert result["failure_stage"] == "preparation"
    assert result["scheduled_attempts"] == 1
    assert result["model_calls"] == 0
    assert calls == []
    assert "do-not-persist" not in json.dumps(result)


def test_existing_output_is_not_overwritten(api, tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    (output / "keep").write_text("unchanged")
    with pytest.raises(FileExistsError):
        api.run_trial(
            model_config=config(),
            instruction="public",
            output_dir=output,
            backend_container="owned-backend",
        )
    assert list(output.iterdir()) == [output / "keep"]


@pytest.mark.parametrize("identifier", ["--privileged", "x; touch /tmp/no", "", "x y", "../other"])
def test_backend_identifier_cannot_be_docker_option_or_shell(api, tmp_path, identifier):
    calls = []
    result = api.run_trial(
        model_config=config(),
        instruction="public",
        output_dir=tmp_path / "trial",
        backend_container=identifier,
        process_runner=lambda *a, **k: calls.append(a),
    )
    assert result["failure_stage"] == "preparation"
    assert calls == []


def test_unknown_tool_outcome_retains_process_partial_output_without_retry(api, service, tmp_path):
    instances, processes = [], []
    underlying = bridge(service, processes)

    def run(argv, **kwargs):
        if processes:
            processes.append({"argv": argv})
            raise subprocess.TimeoutExpired(argv, 30, output=b'{"partial":', stderr=b"timeout")
        return underlying(argv, **kwargs)

    result = api.run_trial(
        model_config=config(),
        instruction="public",
        output_dir=tmp_path / "trial",
        backend_container="owned-backend",
        process_runner=run,
        client_factory=fake_model_factory(
            ['{"action":"call","name":"getPatientHistory","params":{}}'], instances
        ),
    )
    assert result["status"] == "failed"
    assert result["failure_stage"] == "tool_transport"
    assert result["transport"][-1]["outcome"] == "unknown"
    assert result["transport"][-1]["stdout"] == '{"partial":'
    assert len(processes) == 2
    assert instances[0].post_calls == 1


def test_actual_tool_error_reaches_controller_and_is_retained(api, service, tmp_path):
    instances, processes = [], []
    result = api.run_trial(
        model_config=config(),
        instruction="public",
        output_dir=tmp_path / "trial",
        backend_container="owned-backend",
        process_runner=bridge(service, processes),
        client_factory=fake_model_factory(
            ['{"action":"call","name":"getPatientHistory","params":{"patient_id":"PAT-NOTFOUND"}}'],
            instances,
        ),
    )
    assert result["status"] == "failed"
    assert result["controller"]["calls"][0]["response"]["status"] == "error"
    assert result["controller"]["completion"]["reason"] == "tool_error"
    assert len(instances[0].inputs) == 1


@pytest.mark.parametrize("phase", ["preflight", "inference", "postflight"])
def test_identity_and_provider_errors_preserve_attempt_and_postflight(
    api, service, tmp_path, phase
):
    instances, processes = [], []
    factory = fake_model_factory(
        [RuntimeError("provider interrupted") if phase == "inference" else '{"action":"finish"}'],
        instances,
        pre_error=ValueError("wrong identity") if phase == "preflight" else None,
        post_error=ValueError("identity drift") if phase == "postflight" else None,
    )
    result = api.run_trial(
        model_config=config(),
        instruction="public",
        output_dir=tmp_path / "trial",
        backend_container="owned-backend",
        process_runner=bridge(service, processes),
        client_factory=factory,
    )
    assert result["status"] == "failed"
    assert instances[0].post_calls == 1
    assert result["identity_before"] is not None
    assert result["identity_after"] is not None
    if phase == "postflight":
        assert result["controller"]["completion"]["status"] == "terminated"
        assert result["postflight_error"]
    if phase == "inference":
        assert result["model_calls"] == 1
        assert result["model_exchanges"][0]["response"] is None


def test_fixed_bridge_only_reads_public_token_and_routes(api):
    assert "/run/reconciliation/public" in api.BRIDGE_SCRIPT
    assert "/run/reconciliation/admin" not in api.BRIDGE_SCRIPT
    assert "healthcraft.reconciliation" not in api.BRIDGE_SCRIPT
    assert "/finalize" not in api.BRIDGE_SCRIPT
    assert "shell=True" not in Path(api.__file__).read_text()


def test_preparation_identity_is_durable_before_first_public_request(api, service, tmp_path):
    output = tmp_path / "trial"
    processes, instances = [], []
    underlying = bridge(service, processes)

    def run(argv, **kwargs):
        prepared = json.loads((output / "prepared.json").read_text())
        assert prepared["config"] == config()
        assert prepared["source_hashes_before"]
        assert prepared["instruction"] == "public"
        return underlying(argv, **kwargs)

    receipt = api.run_trial(
        model_config=config(),
        instruction="public",
        output_dir=output,
        backend_container="owned-backend",
        process_runner=run,
        client_factory=fake_model_factory(['{"action":"finish"}'], instances),
    )
    assert receipt["status"] == "terminated"
    assert json.loads((output / "identity-before.json").read_text()) == receipt["identity_before"]
    assert json.loads((output / "identity-after.json").read_text()) == receipt["identity_after"]


def test_final_hash_failure_retains_finished_model_and_records_provenance_failure(
    api, service, tmp_path, monkeypatch
):
    count = [0]

    def hashes():
        count[0] += 1
        if count[0] == 2:
            raise OSError("source unavailable")
        return {"controller.py": "known-before"}

    monkeypatch.setattr(api, "_source_hashes", hashes)
    instances, processes = [], []
    result = api.run_trial(
        model_config=config(),
        instruction="public",
        output_dir=tmp_path / "trial",
        backend_container="owned-backend",
        process_runner=bridge(service, processes),
        client_factory=fake_model_factory(['{"action":"finish"}'], instances),
    )
    assert result["status"] == "failed"
    assert result["controller"]["completion"]["status"] == "terminated"
    assert result["model_calls"] == 1
    assert result["source_identity_error"]["type"] == "OSError"
    assert result["source_hashes_after"] is None
    assert result["sources_unchanged"] is False
    assert json.loads((tmp_path / "trial" / "receipt.json").read_text()) == result


@pytest.mark.parametrize(
    "raw",
    [
        '{"http_status":200,"http_status":500,"body_b64":"e30="}',
        '{"http_status":200,"body_b64":"invalid base64"}',
        '{"http_status":true,"body_b64":"e30="}',
        '{"http_status":200,"body_b64":"'
        + base64.b64encode(b'{"status":"ok","x":1e999}').decode()
        + '"}',
        "[]",
    ],
)
def test_malformed_bridge_reply_is_retained_without_inference_or_retry(api, tmp_path, raw):
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=raw, stderr="")

    result = api.run_trial(
        model_config=config(),
        instruction="public",
        output_dir=tmp_path / "trial",
        backend_container="owned-backend",
        process_runner=run,
    )
    assert result["status"] == "failed"
    assert result["model_calls"] == 0
    assert result["transport"][0]["stdout"] == raw
    assert result["transport"][0]["outcome"] == "unknown"
    assert len(calls) == 1


def test_primary_interrupt_remains_interrupted_when_postflight_also_fails(api, service, tmp_path):
    instances, processes = [], []
    factory = fake_model_factory(
        [KeyboardInterrupt("stopped")], instances, post_error=ValueError("postflight unavailable")
    )
    result = api.run_trial(
        model_config=config(),
        instruction="public",
        output_dir=tmp_path / "trial",
        backend_container="owned-backend",
        process_runner=bridge(service, processes),
        client_factory=factory,
    )
    assert result["status"] == "interrupted"
    assert result["error"]["type"] == "KeyboardInterrupt"
    assert result["postflight_error"]["type"] == "ValueError"
    assert result["model_calls"] == 1


def test_real_shared_client_capture_through_runner_has_no_native_tools(
    api, service, tmp_path, monkeypatch
):
    from healthcraft.reconciliation.controller import RecordingOllamaClient

    native_requests = []

    def transport(self, path, payload=None):
        if path == "/api/tags":
            return {"models": [{"name": "local-test:latest", "digest": "a" * 64}]}
        if path == "/api/show":
            return {"capabilities": ["completion"], "details": {"family": "gemma3"}}
        if path == "/api/version":
            return {"version": "0.34.4"}
        assert path == "/api/chat"
        assert (tmp_path / "trial" / "identity-before.json").exists()
        native_requests.append(deepcopy(payload))
        return {
            "model": "local-test:latest",
            "done": True,
            "done_reason": "stop",
            "message": {"role": "assistant", "content": '{"action":"finish"}'},
        }

    monkeypatch.setattr(RecordingOllamaClient, "_transport_request", transport)
    result = api.run_trial(
        model_config=config("same public instruction"),
        instruction="same public instruction",
        output_dir=tmp_path / "trial",
        backend_container="owned-backend",
        process_runner=bridge(service, []),
    )
    assert result["status"] == "terminated"
    assert len(native_requests) == 1
    assert "tools" not in native_requests[0]
    assert "format" not in native_requests[0]
    assert "command_format" not in result["config"]
    assert native_requests[0]["options"] == {
        "temperature": 0,
        "seed": 42,
        "num_ctx": 32768,
        "num_predict": 4096,
    }
    assert result["model_exchanges"][0]["request"] == native_requests[0]


def test_structured_config_is_preserved_detached_and_reaches_real_shared_client(
    api, service, tmp_path, monkeypatch
):
    from healthcraft.reconciliation.controller import (
        RecordingOllamaClient,
        command_format_identity,
        command_format_schema,
    )

    model_config = {**config(), "command_format": command_format_identity()}
    normalized, _ = api._model_config(model_config)
    assert normalized == model_config
    normalized["command_format"]["sha256"] = "0" * 64
    assert model_config["command_format"] == command_format_identity()
    native_requests = []

    def transport(self, path, payload=None):
        if path == "/api/tags":
            return {"models": [{"name": "local-test:latest", "digest": "a" * 64}]}
        if path == "/api/show":
            return {"capabilities": ["completion"], "details": {"family": "gemma3"}}
        if path == "/api/version":
            return {"version": "0.34.4"}
        assert path == "/api/chat"
        native_requests.append(deepcopy(payload))
        events = [
            json.loads(line)
            for line in (tmp_path / "trial" / "model.jsonl").read_text().splitlines()
        ]
        assert events[-1]["exchange"]["request"] == payload
        assert payload["format"] == command_format_schema()
        return {
            "model": "local-test:latest",
            "done": True,
            "done_reason": "stop",
            "message": {"role": "assistant", "content": '{"action":"finish"}'},
        }

    monkeypatch.setattr(RecordingOllamaClient, "_transport_request", transport)
    result = api.run_trial(
        model_config=model_config,
        instruction="public",
        output_dir=tmp_path / "trial",
        backend_container="owned-backend",
        process_runner=bridge(service, []),
    )
    assert result["status"] == "terminated"
    assert result["config"] == model_config
    assert result["controller"]["command_format"] == command_format_identity()
    assert result["initial_messages_sha256_actual"] == config()["initial_messages_sha256"]
    assert len(native_requests) == 1
    assert "tools" not in native_requests[0] and "think" not in native_requests[0]
    assert native_requests[0]["options"] == {
        "temperature": 0,
        "seed": 42,
        "num_ctx": 32768,
        "num_predict": 4096,
    }
    assert result["model_exchanges"][0]["request"] == native_requests[0]


def test_reviewed_format_identity_is_accepted_with_five_legacy_fields(api):
    identity = {
        "version": "healthcraft-reconciliation-command/v2",
        "sha256": "40c74bce3587de9fbd7385f81314f8f6d3d23e978b3024bba2d7b7a734b48794",
    }
    value = {**config(), "command_format": identity}
    normalized, _ = api._model_config(value)
    assert normalized == value
    normalized["command_format"]["sha256"] = "0" * 64
    assert value["command_format"] == identity


@pytest.mark.parametrize(
    "identity",
    [
        None,
        {},
        "json",
        {"version": "unrecognized", "sha256": "a" * 64},
        {"version": "unrecognized"},
        {"sha256": "a" * 64},
    ],
)
def test_invalid_present_command_format_fails_before_discovery_or_client(api, tmp_path, identity):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid format reached discovery or model construction")

    result = api.run_trial(
        model_config={**config(), "command_format": identity},
        instruction="public",
        output_dir=tmp_path / "trial",
        backend_container="owned-backend",
        process_runner=forbidden,
        client_factory=forbidden,
    )
    assert result["status"] == "failed"
    assert result["failure_stage"] == "preparation"
    assert result["scheduled_attempts"] == 1
    assert result["model_calls"] == 0
    assert result["transport"] == []
    assert json.loads((tmp_path / "trial" / "receipt.json").read_text()) == result


@pytest.mark.parametrize("fault", ["digest", "version", "extra", "missing_prompt"])
def test_changed_structured_identity_or_missing_prompt_blocks_discovery(api, tmp_path, fault):
    from healthcraft.reconciliation.controller import command_format_identity

    model_config = {**config(), "command_format": command_format_identity()}
    if fault == "digest":
        model_config["command_format"]["sha256"] = "0" * 64
    elif fault == "version":
        model_config["command_format"]["version"] += "-changed"
    elif fault == "extra":
        model_config["command_format"]["schema"] = {}
    else:
        del model_config["initial_messages_sha256"]

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid frozen configuration reached public or model access")

    result = api.run_trial(
        model_config=model_config,
        instruction="public",
        output_dir=tmp_path / "trial",
        backend_container="owned-backend",
        process_runner=forbidden,
        client_factory=forbidden,
    )
    assert result["failure_stage"] == "preparation"
    assert result["model_calls"] == 0


def test_structured_format_does_not_replace_initial_prompt_guard(api, service, tmp_path):
    from healthcraft.reconciliation.controller import command_format_identity

    instances, processes = [], []
    result = api.run_trial(
        model_config={**config(), "command_format": command_format_identity()},
        instruction="changed public instruction",
        output_dir=tmp_path / "trial",
        backend_container="owned-backend",
        process_runner=bridge(service, processes),
        client_factory=fake_model_factory(['{"action":"finish"}'], instances),
    )
    assert result["failure_stage"] == "prompt_identity"
    assert len(processes) == 1
    assert instances == []


def test_backend_and_exact_fixed_argv_are_bound_before_dispatch(api, service, tmp_path):
    output = tmp_path / "trial"
    instances, processes = [], []
    underlying = bridge(service, processes)
    expected_argv = ["docker", "exec", "-i", "owned-backend", "python", "-c", api.BRIDGE_SCRIPT]

    def run(argv, **kwargs):
        events = [
            json.loads(line) for line in (output / "transport.jsonl").read_text().splitlines()
        ]
        assert events[-1]["event"] == "requested"
        assert events[-1]["exchange"]["argv"] == argv == expected_argv
        assert (
            json.loads((output / "prepared.json").read_text())["backend_container"]
            == "owned-backend"
        )
        return underlying(argv, **kwargs)

    result = api.run_trial(
        model_config=config(),
        instruction="public",
        output_dir=output,
        backend_container="owned-backend",
        process_runner=run,
        client_factory=fake_model_factory(['{"action":"finish"}'], instances),
    )
    assert result["status"] == "terminated"
    assert result["backend_container"] == "owned-backend"
    assert result["transport"][0]["argv"] == expected_argv
    # The script contains the fixed public-token path, but never its value.
    assert "direct-test" not in json.dumps(result)


@pytest.mark.parametrize(
    "fault", ["missing", "malformed", "mismatch", "changed_instruction", "changed_schema"]
)
def test_initial_prompt_identity_blocks_all_model_access_on_mismatch(api, service, tmp_path, fault):
    model_config = config()
    instruction = "public"
    if fault == "missing":
        del model_config["initial_messages_sha256"]
    elif fault == "malformed":
        model_config["initial_messages_sha256"] = "NOT-A-DIGEST"
    elif fault == "mismatch":
        model_config["initial_messages_sha256"] = "0" * 64
    elif fault == "changed_instruction":
        instruction = "changed public instruction"
    else:
        service._tools[0]["description"] += " changed publicly advertised description"
    instances, processes = [], []
    output = tmp_path / "trial"
    result = api.run_trial(
        model_config=model_config,
        instruction=instruction,
        output_dir=output,
        backend_container="owned-backend",
        process_runner=bridge(service, processes),
        client_factory=fake_model_factory(['{"action":"finish"}'], instances),
    )
    assert result["status"] == "failed"
    assert result["model_calls"] == 0
    assert instances == []
    if fault in {"missing", "malformed"}:
        assert result["failure_stage"] == "preparation"
        assert processes == []
    else:
        assert result["failure_stage"] == "prompt_identity"
        binding = json.loads((output / "initial-prompt.json").read_text())
        assert binding["expected_sha256"] == model_config["initial_messages_sha256"]
        assert binding["actual_sha256"] != binding["expected_sha256"]
        assert (
            binding["actual_sha256"]
            == hashlib.sha256(canonical_json(binding["messages"]).encode("utf-8")).hexdigest()
        )


def test_matching_prompt_identity_is_durable_before_preflight(api, service, tmp_path):
    instances, processes = [], []
    output = tmp_path / "trial"
    factory = fake_model_factory(['{"action":"finish"}'], instances)

    class Client(factory):
        def preflight(self):
            binding = json.loads((output / "initial-prompt.json").read_text())
            assert (
                binding["actual_sha256"]
                == binding["expected_sha256"]
                == config()["initial_messages_sha256"]
            )
            return super().preflight()

    result = api.run_trial(
        model_config=config(),
        instruction="public",
        output_dir=output,
        backend_container="owned-backend",
        process_runner=bridge(service, processes),
        client_factory=Client,
    )
    assert result["status"] == "terminated"
    assert (
        result["initial_messages_sha256_expected"]
        == result["initial_messages_sha256_actual"]
        == config()["initial_messages_sha256"]
    )
