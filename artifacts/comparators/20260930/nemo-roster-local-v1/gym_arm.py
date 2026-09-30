"""One planned native-Ollama/Gym roster retrieval attempt, with fake mode for preflight."""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import ipaddress
import json
import os
import platform
import subprocess
import sys
import time
import traceback
from importlib.metadata import distributions
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ['NEMO_GYM_OTEL_ENABLED'] = '0'
ROOT = Path('/Users/kiteboard/healthcraft')
MODEL = 'counsel-nano-q5:latest'
DIGEST = '36896b6271148892f83130812cb14116beeb2a518f98a0a17b469250b84901c8'
RUNTIME = '0.34.4'
SYSTEM = 'You are a tool-using assistant performing a source-record retrieval exercise.'
MAX_STEPS = 8
OUTPUT_BUDGET = 2048
HTTP_TIMEOUT = 120
ATTEMPT_TIMEOUT = 600


def now():
    return datetime.now(timezone.utc).isoformat()


def write(path, data):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(data, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def source_hashes():
    paths = list((ROOT/'src/healthcraft').rglob('*.py'))
    paths += list((ROOT/'integrations/nemo_gym').glob('*.py'))
    paths += list((ROOT/'configs').rglob('*.json'))
    paths += list((ROOT/'configs').rglob('*.yaml'))
    paths += [ROOT/'pyproject.toml', ROOT/'requirements-lock.txt']
    # Task source identity is also independently embedded in the session snapshot.
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths) if p.is_file()}


class ResponseShim:
    def __init__(self, response):
        self.response = response
        self.status = response.status_code
        self.ok = 200 <= self.status < 400
        self.content = self
        self.cookies = dict(response.cookies)
        self.request_info = str(response.request)

    async def read(self):
        return self.response.content

    def raise_for_status(self):
        self.response.raise_for_status()


async def run(output, fake):
    import httpx
    from nemo_gym.server_utils import ServerClient
    from responses_api_agents.simple_agent.app import SimpleAgent, SimpleAgentConfig
    from integrations.nemo_gym.native_ollama import NativeOllamaModel, NativeOllamaModelConfig
    from integrations.nemo_gym.roster_resources import RosterResourcesConfig, RosterResourcesServer
    from healthcraft.integrations.nemo_roster import FIXTURE_KEY, MECHANICAL_PROMPT, tool_definitions
    from healthcraft.llm.local_models import OllamaClient

    before = source_hashes()
    tools = tool_definitions()
    body = {'fixture_key':FIXTURE_KEY, 'episode_id':'matched-roster-attempt-1', '_ng_rollout_id':'matched-roster-attempt-1', 'task_id':'CC-022', 'responses_create_params':{'model':MODEL, 'instructions':SYSTEM, 'input':MECHANICAL_PROMPT, 'tools':[{'type':'function', 'strict':False, **tool} for tool in tools], 'max_output_tokens':OUTPUT_BUDGET, 'temperature':0}}
    write(output/'protocol.json', {'model':MODEL, 'expected_digest':DIGEST, 'expected_runtime':RUNTIME, 'system':SYSTEM, 'user':MECHANICAL_PROMPT, 'tools':tools, 'request':body, 'max_model_responses':MAX_STEPS, 'output_tokens_per_response':OUTPUT_BUDGET, 'native_options':{'num_ctx':32768, 'seed':42, 'temperature':0.0, 'num_predict':OUTPUT_BUDGET}, 'think':False, 'http_timeout_seconds':HTTP_TIMEOUT, 'whole_attempt_timeout_seconds':ATTEMPT_TIMEOUT, 'source_hashes':before, 'canonical_tools_sha256':digest(tools), 'harness_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'python':platform.python_version(), 'packages':sorted({(dist.metadata.get('Name',''),dist.version) for dist in distributions()}), 'healthcraft_head':subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip(), 'healthcraft_source_dirty':bool(subprocess.check_output(['git','-C',str(ROOT),'status','--porcelain','--untracked-files=no'],text=True).strip()), 'mode':'scripted_fake' if fake else 'local_model', 'agent_framework':'NVIDIA NeMo Gym SimpleAgent', 'transport':'in-process ASGI routing; provider native /api/chat over loopback in live mode', 'comparison_scope':'interoperability feasibility only; identical initial native request/settings, not all-turn byte parity or performance comparison', 'tool_result_serialization':'Preserve framework-native representation: Gym keeps compact FastAPI JSON text; HealthCraft native agent uses json.dumps whitespace. Parsed tool data match; subsequent model prompts can differ in whitespace and tokenization.', 'benchmark_score':None, 'benchmark_comparable':False, 'grading_complete':False})
    write(output/'attempt-started.json', {'attempt':1, 'started_at':now(), 'status':'attempted'})
    started = time.monotonic()
    resource = None
    seed = None
    latest_resource_cookies = {}
    requests = []
    scripted_calls = []
    chat_count = 0
    result = {'attempt':1, 'status':'failed', 'execution_completed':False, 'benchmark_score':None, 'benchmark_comparable':False, 'grading_complete':False, 'clinical_validation':'not_assessed', 'safety_validation':'not_assessed'}
    calls_dir = output/'asgi-calls'; calls_dir.mkdir()
    native_dir = output/'native-captures'; native_dir.mkdir()
    gym_dir = output/'gym-model-captures'; gym_dir.mkdir()
    apps = {}

    async def post(server_name, url_path, json, cookies=None):
        nonlocal seed, latest_resource_cookies
        data = json.model_dump(mode='json') if hasattr(json, 'model_dump') else json
        event = {'index':len(requests)+1, 'server':server_name, 'path':url_path, 'request':copy.deepcopy(data), 'started_at':now()}
        requests.append(event)
        began = time.monotonic()
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=apps[server_name]), base_url='http://testserver', cookies=cookies or {}) as client:
                response = await client.post(url_path, json=data)
            event['http_status'] = response.status_code
            try: event['response'] = response.json()
            except ValueError: event['response_text'] = response.text
            if server_name == 'resources':
                latest_resource_cookies = dict(response.cookies)
                if url_path == '/seed_session' and response.status_code == 200:
                    seed = response.json()
            return ResponseShim(response)
        except BaseException as exc:
            event['error'] = {'type':type(exc).__name__, 'message':str(exc)}
            raise
        finally:
            event['ended_at'] = now(); event['wall_seconds'] = time.monotonic()-began
            write(calls_dir/f"call-{event['index']:04d}.json", event)

    def fake_provider(self, path, payload=None):
        nonlocal chat_count
        scripted_calls.append({'path':path, 'payload':copy.deepcopy(payload)})
        if path == '/api/tags': return {'models':[{'name':MODEL, 'digest':DIGEST}]}
        if path == '/api/show': return {'capabilities':['completion','tools','thinking'], 'details':{}}
        if path == '/api/version': return {'version':RUNTIME}
        assert path == '/api/chat'
        chat_count += 1
        message = {'role':'assistant', 'content':''}
        if chat_count == 1:
            message['tool_calls'] = [{'function':{'name':'searchEncounters', 'arguments':{}}}]
        elif chat_count == 2:
            rows = json.loads(payload['messages'][-1]['content'])['data']
            message['tool_calls'] = [{'function':{'name':'getEncounterDetails', 'arguments':{'encounter_id':row['id']}}} for row in rows]
        else:
            assert chat_count == 3
            message['content'] = 'Retrieved all encounter details.'
        return {'model':MODEL, 'message':message, 'done':True, 'done_reason':'stop', 'prompt_eval_count':35, 'eval_count':6}

    try:
        server_client = MagicMock(spec=ServerClient)
        server_client.global_config_dict = {'observability_enabled':True, 'model_call_capture_dir':str(gym_dir.resolve())}
        server_client.post.side_effect = post
        resource = RosterResourcesServer(config=RosterResourcesConfig(host='127.0.0.1', port=0, entrypoint='roster_resources.py', name='resources'), server_client=server_client)
        model = NativeOllamaModel(config=NativeOllamaModelConfig(host='127.0.0.1', port=0, entrypoint='native_ollama.py', name='model', model=MODEL, expected_digest=DIGEST, expected_runtime=RUNTIME, capture_dir=native_dir, output_budget=OUTPUT_BUDGET, timeout=HTTP_TIMEOUT), server_client=server_client)
        agent = SimpleAgent(config=SimpleAgentConfig(host='127.0.0.1', port=0, entrypoint='app.py', name='agent', resources_server={'type':'resources_servers','name':'resources'}, model_server={'type':'responses_api_models','name':'model'}, max_steps=MAX_STEPS), server_client=server_client)
        apps.update(resources=resource.setup_webserver(), model=model.setup_webserver(), agent=agent.setup_webserver())
        async def execute():
            response = await post('agent','/run',body)
            response.raise_for_status()
            return response.response.json()
        if fake:
            with patch.object(OllamaClient, '_request', fake_provider):
                returned = await asyncio.wait_for(execute(), ATTEMPT_TIMEOUT)
        else:
            returned = await asyncio.wait_for(execute(), ATTEMPT_TIMEOUT)
        result.update(status='returned', response=returned, execution_completed=returned.get('execution_completed'))
    except BaseException as exc:
        result.update(status='timeout' if isinstance(exc, TimeoutError) else 'failed', error={'type':type(exc).__name__, 'message':str(exc), 'traceback':traceback.format_exc()})
    finally:
        if seed and resource:
            try:
                snapshot = resource.sessions.snapshot(seed['resources_session_id'])
                write(output/'snapshot-before-close.json', snapshot)
                result['fixture_sha256'] = snapshot['fixture_sha256']
                result['captured_tool_calls'] = len(snapshot['calls'])
                verification = result.get('response') or resource.sessions.verify(seed['resources_session_id'], body['episode_id'], 'incomplete')
                write(output/'mechanical-verification.json', verification)
                result['mechanical_passed'] = verification['mechanical_passed']
                result['mechanical_reward'] = verification['reward']
                certificate = verification.get('certificate')
                result['retrieved_members'] = certificate['coverage']['retrieved_members'] if certificate else None
                result['completion_status'] = verification['completion_status']
            except Exception as exc:
                result['snapshot_error'] = {'type':type(exc).__name__, 'message':str(exc)}
            try:
                closed = await post('resources','/close_session',{'resources_session_id':seed['resources_session_id'], 'episode_id':body['episode_id']},latest_resource_cookies)
                result['cleanup'] = {'http_status':closed.status, 'active_sessions':resource.sessions.active_count}
            except Exception as exc:
                result['cleanup'] = {'error':{'type':type(exc).__name__, 'message':str(exc)}}
        else:
            result['cleanup'] = {'seeded':False, 'active_sessions':resource.sessions.active_count if resource else 0}
        result['source_unchanged'] = source_hashes() == before
        if not result['source_unchanged']:
            result['status'] = 'source_changed'
        result.setdefault('completion_status', 'incomplete')
        result.setdefault('mechanical_passed', False)
        result.setdefault('mechanical_reward', None)
        result.setdefault('retrieved_members', None)
        result['active_sessions_after_cleanup'] = resource.sessions.active_count if resource else 0
        result['wall_seconds'] = time.monotonic()-started
        result['ended_at'] = now()
        result['provider_chat_captures'] = sum(1 for path in native_dir.glob('*/transport-*.json') if json.loads(path.read_text()).get('path')=='/api/chat')
        result['provider_chat_attempts'] = result['provider_chat_captures']
        result['model_inference_attempted'] = bool(result['provider_chat_attempts']) and not fake
        result['duration_seconds'] = result['wall_seconds']
        if fake:
            write(output/'scripted-provider-calls.json', scripted_calls)
        write(output/'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--fake', action='store_true')
    modes.add_argument('--live', action='store_true')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    write(args.output_dir/'scheduled.json', {'scheduled_at':now(), 'protocol':'cc022-roster-matched-local-feasibility/v1', 'arm':'nemo_gym', 'planned_attempts':1, 'scheduled_attempts':1, 'trial':1, 'retries':0, 'attempt_ids':[1], 'mode':'scripted_fake' if args.fake else 'local_model', 'benchmark_score':None, 'benchmark_comparable':False, 'grading_complete':False})
    def guard(event, values):
        if event != 'socket.connect' or not isinstance(values[1], tuple): return
        if args.fake:
            raise AssertionError('Network socket forbidden during fake mode')
        address = values[1]
        if not ipaddress.ip_address(address[0]).is_loopback or address[1] != 11434:
            raise AssertionError('Only native Ollama loopback port 11434 is allowed')
    sys.addaudithook(guard)
    try:
        result = asyncio.run(run(args.output_dir, args.fake))
    except BaseException:
        write(args.output_dir/'setup-failure.json', {'ended_at':now(), 'traceback':traceback.format_exc(), 'scheduled_attempts':1, 'status':'setup_failed'})
        raise
    print(json.dumps({'output_dir':str(args.output_dir), 'status':result['status'], 'execution_completed':result['execution_completed'], 'wall_seconds':result['wall_seconds'], 'provider_chat_captures':result['provider_chat_captures']}))
    return 0 if result['status']=='returned' else 1


if __name__ == '__main__':
    raise SystemExit(main())
