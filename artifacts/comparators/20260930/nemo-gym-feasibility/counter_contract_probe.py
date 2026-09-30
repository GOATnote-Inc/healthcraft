"""Bounded in-process contract probe; no model or network calls permitted."""
import json
import socket
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "counter-contract-result.json"
if OUT.exists():
    raise SystemExit("Refusing to overwrite prior probe result")

events = []
checks = []


def network_guard(event, args):
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo"}:
        raise RuntimeError(f"Network access disabled in counter contract probe: {event}")


sys.addaudithook(network_guard)
sys.path.insert(0, str(ROOT / "upstream"))
result = {"kind": "deterministic_contract_probe", "model_calls": 0, "checks": checks, "events": events}
try:
    from unittest.mock import MagicMock
    from fastapi.testclient import TestClient
    from nemo_gym.server_utils import ServerClient
    from resources_servers.example_session_state_mgmt.app import (
        StatefulCounterResourcesServer,
        StatefulCounterResourcesServerConfig,
    )
    from resources_servers.example_session_state_mgmt.tests.test_app import TestApp

    TestApp().test_sanity()
    checks.append({"name": "upstream_test_sanity", "passed": True})
    server = StatefulCounterResourcesServer(
        config=StatefulCounterResourcesServerConfig(
            host="127.0.0.1", port=0, entrypoint="app.py", name="counter_contract_probe"
        ),
        server_client=MagicMock(spec=ServerClient),
    )
    app = server.setup_webserver()
    row = json.loads((ROOT / "upstream/resources_servers/example_session_state_mgmt/data/example.jsonl").read_text().splitlines()[0])
    # This placeholder is schema input for the deterministic verifier, never a model result.
    response_stub = {
        "id": "deterministic-contract-placeholder", "created_at": 0, "model": "no-model",
        "object": "response", "output": [], "parallel_tool_calls": False,
        "tool_choice": "auto", "tools": [], "status": "completed",
    }

    def post(client, session, path, body=None):
        r = client.post(path, json=body) if body is not None else client.post(path)
        events.append({"session": session, "path": path, "body": body, "status_code": r.status_code, "response": r.json()})
        assert r.status_code == 200, (path, r.status_code, r.text)
        return r.json()

    with TestClient(app) as a, TestClient(app) as b:
        post(a, "A", "/seed_session", {"initial_count": 3})
        assert post(a, "A", "/get_counter_value") == {"count": 3}
        post(a, "A", "/increment_counter", {"count": 1})
        post(a, "A", "/increment_counter", {"count": 2})
        assert post(a, "A", "/get_counter_value") == {"count": 6}
        good = post(a, "A", "/verify", {**row, "response": response_stub})
        assert good["reward"] == 1.0
        bad = post(a, "A", "/verify", {**row, "expected_count": 7, "response": response_stub})
        assert bad["reward"] == 0.0
        checks.append({"name": "seed_tool_read_and_positive_negative_verifier", "passed": True})
        post(b, "B", "/seed_session", {"initial_count": 9})
        assert post(b, "B", "/get_counter_value") == {"count": 9}
        assert post(a, "A", "/get_counter_value") == {"count": 6}
        checks.append({"name": "cookie_session_isolation", "passed": True})
        post(a, "A", "/seed_session", {"initial_count": 100})
        assert post(a, "A", "/get_counter_value") == {"count": 6}
        checks.append({"name": "reseed_preserves_existing_state_as_shipped", "passed": True, "limitation": "Not a reset: requested initial_count=100, actual remains6"})
        invalid = a.post("/increment_counter", json={"count": "not-an-integer"})
        events.append({"session": "A", "path": "/increment_counter", "body": {"count": "not-an-integer"}, "status_code": invalid.status_code, "response": invalid.json()})
        assert invalid.status_code == 422
        assert post(a, "A", "/get_counter_value") == {"count": 6}
        checks.append({"name": "invalid_tool_input_rejected_without_mutation", "passed": True})
    result["status"] = "passed"
except BaseException as exc:
    result.update(status="failed", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
finally:
    with OUT.open("x") as f:
        json.dump(result, f, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != "events"}, indent=2))
if result["status"] != "passed":
    raise SystemExit(1)
