"""One local NeMo Gym trajectory; unmodified upstream servers, bounded loopback transport."""
import asyncio
import hashlib
import ipaddress
import json
import os
import signal
import socket
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUN = ROOT / "local-trajectory-01"
RUN.mkdir()  # Deliberately exclusive: a second invocation cannot reuse artifacts.
sys.path.insert(0, str(ROOT / "upstream"))
os.environ["NEMO_GYM_VLLM_TRANSPORT_LOG"] = str(RUN / "ollama-transport.jsonl")
started = time.monotonic()
record = {
    "kind": "local_integration_probe", "scheduled_trials": 1, "started_trials": 0,
    "completed_http_trials": 0, "failed_trials": 0, "clinical_or_superiority_claim": False,
    "upstream_revision": "82e1834ccf2dd578af26a1abc686c15e17569594",
    "model": "counsel-nano-q5:latest",
    "model_digest": "36896b6271148892f83130812cb14116beeb2a518f98a0a17b469250b84901c8",
    "max_steps": 5, "max_output_tokens_per_call": 512, "wall_limit_seconds": 150,
    "network_connections": [], "status": "initializing",
}


def save_record():
    record["elapsed_seconds"] = time.monotonic() - started
    with (RUN / "trial-accounting.json").open("x") as f:
        json.dump(record, f, indent=2)


def timeout_exit(signum, frame):
    record.update(status="wall_timeout", failed_trials=1)
    save_record()
    os._exit(124)


signal.signal(signal.SIGALRM, timeout_exit)
signal.alarm(150)


def network_guard(event, args):
    if event in {"socket.connect", "socket.connect_ex", "socket.bind"}:
        address = args[1]
        if isinstance(address, tuple):
            if not ipaddress.ip_address(address[0]).is_loopback:
                raise RuntimeError(f"Non-loopback socket prohibited: {address}")
            record["network_connections"].append({"event": event, "address": list(address)})
    elif event == "socket.getaddrinfo":
        if args[0] not in ("127.0.0.1", "::1", "localhost", None):
            raise RuntimeError(f"External name lookup prohibited: {args[0]}")


sys.addaudithook(network_guard)


class CaptureASGI:
    """Pass bytes unchanged; retain full request/response and cookie hashes locally."""
    def __init__(self, app, name):
        self.app, self.name = app, name
        self.path = RUN / f"{name}-http.jsonl"
        self.path.touch(exist_ok=False)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_body, response_body = bytearray(), bytearray()
        entry = {"component": self.name, "method": scope["method"], "path": scope["path"], "started_at": time.time()}
        entry["cookie_hash"] = next((hashlib.sha256(v).hexdigest() for k, v in scope.get("headers", []) if k == b"cookie"), None)

        async def recv():
            message = await receive()
            if message["type"] == "http.request":
                request_body.extend(message.get("body", b""))
            return message

        async def forward(message):
            if message["type"] == "http.response.start":
                entry["status_code"] = message["status"]
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, recv, forward)
        except BaseException as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            entry.update(request_body=request_body.decode(), response_body=response_body.decode(), completed_at=time.time())
            with self.path.open("a") as f:
                f.write(json.dumps(entry) + "\n")


async def main():
    import httpx
    import uvicorn
    from omegaconf import OmegaConf
    from nemo_gym.config_types import BaseServerConfig
    from nemo_gym.server_utils import ServerClient
    import nemo_gym.server_utils as server_utils
    from resources_servers.example_session_state_mgmt.app import StatefulCounterResourcesServer, StatefulCounterResourcesServerConfig
    from responses_api_agents.simple_agent.app import SimpleAgent, SimpleAgentConfig
    from responses_api_models.vllm_model.app import VLLMModel, VLLMModelConfig

    sockets = {}
    for name in ("resources", "agent", "policy_model"):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        s.listen(128)
        sockets[name] = s
    common = {name: {"host": "127.0.0.1", "port": s.getsockname()[1], "name": name, "entrypoint": "app.py"} for name, s in sockets.items()}
    global_config = {
        "observability_enabled": False, "telemetry": {"enabled": False},
        "resources": {"resources_servers": {"example_session_state_mgmt": common["resources"]}},
        "agent": {"responses_api_agents": {"simple_agent": common["agent"]}},
        "policy_model": {"responses_api_models": {"vllm_model": common["policy_model"]}},
    }
    client = ServerClient(head_server_config=BaseServerConfig(host="127.0.0.1", port=0), global_config_dict=OmegaConf.create(global_config))
    resources = StatefulCounterResourcesServer(config=StatefulCounterResourcesServerConfig(**common["resources"]), server_client=client)
    agent_config = SimpleAgentConfig(**common["agent"], resources_server={"type": "resources_servers", "name": "resources"}, model_server={"type": "responses_api_models", "name": "policy_model"}, max_steps=5, skip_verification=False)
    model_config = VLLMModelConfig(
        **common["policy_model"], base_url="http://127.0.0.1:11434/v1", api_key="local-not-used",
        model=record["model"], return_token_id_information=False, uses_reasoning_parser=True,
        uses_interleaved_reasoning=True, request_prompt_and_generation_token_ids=False,
        supply_prefix_token_ids=False, use_completions_api=False, render_chat_template=False,
        is_responses_native=False, endpoint_file=None,
        sampling_overrides={"temperature": 0, "max_tokens": 512},
    )
    agent = SimpleAgent(config=agent_config, server_client=client)
    model = VLLMModel(config=model_config, server_client=client)
    instances = {"resources": resources, "agent": agent, "policy_model": model}
    resolved = {"global": global_config, "agent": agent_config.model_dump(), "model": model_config.model_dump()}
    with (RUN / "resolved-config.json").open("x") as f:
        json.dump(resolved, f, indent=2)
    servers, tasks = [], []
    try:
        for name, instance in instances.items():
            app = CaptureASGI(instance.setup_webserver(), name)
            srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=common[name]["port"], log_level="warning", http="httptools", lifespan="off", timeout_graceful_shutdown=1, proxy_headers=False))
            servers.append(srv)
            tasks.append(asyncio.create_task(srv.serve(sockets=[sockets[name]])))
        for _ in range(100):
            if all(s.started for s in servers):
                break
            await asyncio.sleep(0.05)
        assert all(s.started for s in servers), "Server startup did not finish in five seconds"
        row = json.loads((ROOT / "upstream/resources_servers/example_session_state_mgmt/data/example.jsonl").read_text().splitlines()[0])
        row["responses_create_params"].update(parallel_tool_calls=False, max_output_tokens=512, temperature=0, reasoning={"effort": "low"})
        with (RUN / "materialized-input.json").open("x") as f:
            json.dump(row, f, indent=2)
        record.update(started_trials=1, status="running")
        async with httpx.AsyncClient(timeout=120, trust_env=False, follow_redirects=False) as http:
            result = await asyncio.wait_for(http.post(f"http://127.0.0.1:{common['agent']['port']}/run", json=row), timeout=120)
        with (RUN / "raw-run-response.json").open("x") as f:
            try:
                raw = result.json()
            except ValueError:
                raw = {"unparsed_body": result.text}
            json.dump({"status_code": result.status_code, "body": raw}, f, indent=2)
        record.update(status="http_completed" if result.status_code == 200 else "http_error", completed_http_trials=int(result.status_code == 200), failed_trials=int(result.status_code != 200), http_status=result.status_code, recorded_reward=raw.get("reward"), recorded_mask_sample=raw.get("mask_sample"), response_status=raw.get("response", {}).get("status"), incomplete_details=raw.get("response", {}).get("incomplete_details"))
        record["final_counter_values"] = list(resources.session_id_to_counter.values())
    finally:
        for srv in servers:
            srv.should_exit = True
        try:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=3)
        except TimeoutError:
            for task in tasks:
                task.cancel()
        for s in sockets.values():
            s.close()
        if server_utils._GLOBAL_AIOHTTP_CLIENT is not None:
            await server_utils._GLOBAL_AIOHTTP_CLIENT.close()


try:
    asyncio.run(main())
except BaseException as exc:
    record.update(status="failed", failed_trials=1, error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
finally:
    signal.alarm(0)
    save_record()
    print(json.dumps({k: v for k, v in record.items() if k != "network_connections"}, indent=2))
