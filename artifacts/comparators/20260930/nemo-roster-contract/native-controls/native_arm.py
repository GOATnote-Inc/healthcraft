"""One local-only native HealthCraft mechanical attempt; explicit live opt-in.

This temporary harness changes no repository source. Fake mode performs no
network/model access. Live invocation remains the parent task's decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import signal
import subprocess
import sys
import time
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from importlib.metadata import distributions
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path('/Users/kiteboard/healthcraft')
sys.path.insert(0, str(ROOT / 'src'))
from healthcraft.integrations.nemo_native import _RecordingClient
from healthcraft.integrations.nemo_roster import (
    FIXTURE_KEY, MECHANICAL_PROMPT, RosterSessions, TASK_PATH, tool_definitions,
)
from healthcraft.llm import agent
from healthcraft.llm.local_models import LocalModelError, OllamaClient
from healthcraft.tasks.loader import load_task
from healthcraft.trajectory import Trajectory, trajectory_completion

SYSTEM_PROMPT = 'You are a tool-using assistant performing a source-record retrieval exercise.'
MODEL = 'counsel-nano-q5:latest'
DIGEST = '36896b6271148892f83130812cb14116beeb2a518f98a0a17b469250b84901c8'
RUNTIME = '0.34.4'
MAX_ROUNDS = 8
BUDGET = 2048
HTTP_TIMEOUT = 120
WALL_TIMEOUT = 600
PROTOCOL = 'cc022-roster-matched-local-feasibility/v1'
NATIVE_OPTIONS = {'temperature': 0.0, 'seed': 42, 'num_ctx': 32768, 'num_predict': BUDGET}


def write(path: Path, value) -> None:
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False, default=str)
        handle.write('\n')


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def identities() -> dict:
    files = set((ROOT / 'src/healthcraft').rglob('*.py'))
    files.update((ROOT / 'configs').rglob('*.json'))
    files.update((ROOT / 'configs').rglob('*.yaml'))
    files.update((ROOT / 'integrations/nemo_gym').glob('*.py'))
    files.update(ROOT / name for name in ('pyproject.toml', 'requirements-lock.txt'))
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(files) if path.is_file()}
    packages = sorted({(dist.metadata.get('Name', ''), dist.version) for dist in distributions()})
    head = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
                          check=True, capture_output=True, text=True, timeout=5).stdout.strip()
    return {
        'git_head': head, 'identity_scope': 'working-tree file hashes; HEAD alone is not this candidate',
        'source_hashes': hashes, 'source_sha256': digest(hashes),
        'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'python': platform.python_version(), 'implementation': platform.python_implementation(),
        'platform': platform.platform(), 'packages': packages, 'packages_sha256': digest(packages),
    }


class NativeClient(_RecordingClient):
    """Actual native client return contract, forcing the predeclared output budget."""

    def chat(self, messages, tools=None, temperature=0.0, max_tokens=BUDGET):
        if temperature != 0.0 or max_tokens != BUDGET:
            raise ValueError('Native arm received inference settings outside its fixed contract')
        return super().chat(messages, tools=tools, temperature=0.0, max_tokens=BUDGET)


class ResourceView:
    def __init__(self, sessions, session_id, tools):
        self.available_tools = [tool['name'] for tool in tools]
        self.sessions = sessions
        self.session_id = session_id

    def call_tool(self, name, params):
        return self.sessions.call(self.session_id, name, params)


def fake_provider(mode):
    count = 0

    def request(self, path, payload=None):
        nonlocal count
        if path == '/api/tags':
            return {'models': [{'name': MODEL, 'digest': 'mismatch' if mode == 'digest_mismatch' else DIGEST}]}
        if path == '/api/show':
            return {'capabilities': ['completion', 'tools', 'thinking'], 'details': {}}
        if path == '/api/version':
            return {'version': RUNTIME}
        if path != '/api/chat':
            raise AssertionError(f'Unexpected provider path: {path}')
        count += 1
        assert payload['model'] == MODEL and payload['options'] == NATIVE_OPTIONS
        assert payload['think'] is False and payload['stream'] is False
        assert payload['tools'] == [{'type': 'function', 'function': tool} for tool in tool_definitions()]
        assert payload['messages'][:2] == [
            {'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': MECHANICAL_PROMPT},
        ]
        if mode == 'timeout':
            raise TimeoutError('scripted native timeout; no network access')
        message, reason = {'role': 'assistant', 'content': ''}, 'stop'
        if count == 1:
            message['tool_calls'] = [{'function': {'name': 'searchEncounters', 'arguments': {}}}]
            if mode == 'truncated_tool':
                reason = 'length'
        elif count == 2:
            # The fake controller discovers IDs solely from actual returned tool data.
            result = json.loads(payload['messages'][-1]['content'])
            assert result['status'] == 'ok' and len(result['data']) == 4
            message['tool_calls'] = [
                {'function': {'name': 'getEncounterDetails', 'arguments': {'encounter_id': row['id']}}}
                for row in result['data']
            ]
        else:
            assert count == 3
            message['content'] = 'Retrieved all encounter details.'
            if mode == 'truncated_final':
                reason = 'length'
        return {'model': MODEL, 'message': message, 'done': True, 'done_reason': reason,
                'prompt_eval_count': 35, 'eval_count': 6}

    return request


def run_attempt(output_dir: Path, *, fake_mode: str | None = None) -> dict:
    output_dir.mkdir(parents=False, exist_ok=False)
    scheduled = {
        'protocol': PROTOCOL, 'arm': 'healthcraft_native', 'fixture_key': FIXTURE_KEY,
        'scheduled_attempts': 1, 'trial': 1, 'retries': 0,
        'scheduled_at': datetime.now(timezone.utc).isoformat(),
        'fake_transport': fake_mode is not None, 'fake_case': fake_mode,
        'model': MODEL, 'expected_model_digest': DIGEST, 'expected_runtime': RUNTIME,
        'base_url': 'http://127.0.0.1:11434', 'native_options': NATIVE_OPTIONS,
        'think': False, 'stream': False,
        'max_model_rounds': 2 if fake_mode == 'max_steps' else MAX_ROUNDS,
        'declared_live_max_model_rounds': MAX_ROUNDS,
        'native_http_timeout_seconds': HTTP_TIMEOUT, 'whole_attempt_timeout_seconds': WALL_TIMEOUT,
        'benchmark_score': None, 'benchmark_comparable': False, 'grading_complete': False,
        'clinical_validation': 'not_assessed',
    }
    # Denominator and fixed settings are durable before any model metadata/inference access.
    write(output_dir / 'scheduled.json', scheduled)
    sessions, session_id, episode_id = RosterSessions(), uuid4().hex, uuid4().hex
    trajectory = None
    client = None
    task = None
    outer_error = None
    verification = None
    cleanup = {'closed': False}
    started = time.monotonic()
    original_rounds = agent.MAX_TOOL_ROUNDS
    original_alarm = signal.getsignal(signal.SIGALRM)

    def expired(signum, frame):
        raise TimeoutError(f'Whole attempt exceeded {WALL_TIMEOUT} seconds')

    try:
        tools = tool_definitions()
        write(output_dir / 'inputs.json', {'system': SYSTEM_PROMPT, 'prompt': MECHANICAL_PROMPT,
                                          'tools': tools, 'inputs_sha256': digest([SYSTEM_PROMPT, MECHANICAL_PROMPT, tools])})
        write(output_dir / 'source-runtime.json', identities())
        task = replace(load_task(TASK_PATH), description=MECHANICAL_PROMPT, initial_state={})
        seeded = sessions.seed(session_id, FIXTURE_KEY, episode_id)
        write(output_dir / 'seed.json', seeded)
        provider_dir = output_dir / 'provider'
        provider_dir.mkdir()
        client = NativeClient(directory=provider_dir, model=MODEL, base_url='http://127.0.0.1:11434',
                              seed=42, num_ctx=32768, think=False, timeout=HTTP_TIMEOUT)
        agent.MAX_TOOL_ROUNDS = 2 if fake_mode == 'max_steps' else MAX_ROUNDS
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, WALL_TIMEOUT)
        stub = patch.object(OllamaClient, '_request', fake_provider(fake_mode)) if fake_mode is not None else nullcontext()
        with stub:
            info = client.validate_capabilities(require_tools=True)
            write(output_dir / 'model-preflight.json', {**info, 'fake_transport': fake_mode is not None})
            if info['model_digest'] != DIGEST:
                raise LocalModelError('Installed native model digest differs from declared digest')
            if info['runtime_version'] != RUNTIME or info['model'] != MODEL:
                raise LocalModelError('Installed native runtime/model differs from declared identity')
            if 'thinking' not in info['capabilities']:
                raise LocalModelError('Installed model does not declare thinking capability')
            trajectory = agent.run_agent_task(client, task, ResourceView(sessions, session_id, tools), SYSTEM_PROMPT)
    except Exception as exc:
        outer_error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, original_alarm)
        agent.MAX_TOOL_ROUNDS = original_rounds
        try:
            if trajectory is None:
                trajectory = Trajectory(task_id='CC-022', model=MODEL, seed=42, system_prompt=SYSTEM_PROMPT,
                                        error=f"Attempt did not reach agent completion: {outer_error}")
            trajectory.model = f'ollama:{MODEL}'
            trajectory.metadata.update({
                'fixture_key': FIXTURE_KEY, 'evaluation_mode': 'profile_diagnostic',
                'scenario_profile': 'roster-observations/v1', 'benchmark_comparable': False,
                'benchmark_score': None, 'grading_complete': False,
                'clinical_validation': 'not_assessed', 'ungraded_criteria': len(task.criteria) if task else None,
                'fake_transport': fake_mode is not None,
                'original_task_criteria_unassessed': [item['id'] for item in task.criteria] if task else [],
                'rubric_fields_meaning': 'Ungraded compatibility placeholders; not measured reward/pass/safety',
                'model_call_budget': BUDGET, 'declared_max_model_rounds': MAX_ROUNDS,
                'test_round_cap_override': 2 if fake_mode == 'max_steps' else None,
            })
            # Match the existing profile-diagnostic serialization convention; never emit safe=True.
            trajectory.set_results([], 0.0, False, False, {})
            raw_trajectory = trajectory.to_dict()
            write(output_dir / 'trajectory.json', raw_trajectory)
            completion, reason = trajectory_completion(raw_trajectory['turns'], raw_trajectory['metadata'], trajectory.error)
            write(output_dir / 'completion.json', {'status': completion, 'reason': reason, 'agent_error': trajectory.error,
                                                  'outer_error': outer_error})
            if sessions.active_count:
                write(output_dir / 'snapshot.json', sessions.snapshot(session_id))
                verification = sessions.verify(session_id, episode_id, completion)
                write(output_dir / 'mechanical-verification.json', verification)
        finally:
            if sessions.active_count:
                try:
                    cleanup = {'closed': True, **sessions.close(session_id, session_id, episode_id)}
                except Exception as exc:
                    cleanup = {'closed': False, 'error': {'type': type(exc).__name__, 'message': str(exc)}}
            write(output_dir / 'cleanup.json', cleanup)
    native_calls = [] if client is None else [event for event in client.events if event['path'] == '/api/chat']
    result = {
        **scheduled, 'finished_at': datetime.now(timezone.utc).isoformat(),
        'duration_seconds': time.monotonic() - started,
        'provider_chat_attempts': len(native_calls), 'model_inference_attempted': bool(native_calls) and fake_mode is None,
        'completion_status': completion, 'agent_error': trajectory.error, 'outer_error': outer_error,
        'mechanical_passed': verification is not None and verification['mechanical_passed'],
        'mechanical_reward': None if verification is None else verification['reward'],
        'retrieved_members': None if not verification or not verification.get('certificate') else verification['certificate']['coverage']['retrieved_members'],
        'cleanup': cleanup, 'active_sessions_after_cleanup': sessions.active_count,
        'limit_scope': 'Engineering source-retrieval feasibility only; no benchmark/clinical comparison',
    }
    write(output_dir / 'result.json', result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--execute-local', action='store_true', help='Explicitly run one already-authorized local attempt')
    mode.add_argument('--fake', choices=['complete', 'truncated_final', 'truncated_tool', 'max_steps', 'timeout', 'digest_mismatch'])
    args = parser.parse_args()
    result = run_attempt(args.output_dir, fake_mode=args.fake)
    print(json.dumps({key: result[key] for key in ('fake_transport', 'completion_status', 'mechanical_passed', 'provider_chat_attempts', 'retrieved_members')}, sort_keys=True))
    return 0 if result['mechanical_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
