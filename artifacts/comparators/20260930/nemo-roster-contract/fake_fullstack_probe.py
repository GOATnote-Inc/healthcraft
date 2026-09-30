"""Offline actual-SDK integration probe. Never calls Ollama or hosted APIs."""
import asyncio
import copy
import hashlib
import json
import os
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ['NEMO_GYM_OTEL_ENABLED'] = '0'
import httpx
from nemo_gym.server_utils import ServerClient
from responses_api_agents.simple_agent.app import SimpleAgent, SimpleAgentConfig
from integrations.nemo_gym.native_ollama import NativeOllamaModel, NativeOllamaModelConfig
from integrations.nemo_gym.roster_resources import RosterResourcesConfig, RosterResourcesServer
from healthcraft.integrations.nemo_roster import FIXTURE_KEY, MECHANICAL_PROMPT, tool_definitions
from healthcraft.llm.local_models import OllamaClient

ROOT = Path('/Users/kiteboard/healthcraft')
OUT = Path(tempfile.mkdtemp(prefix='healthcraft-nemo-fake-fullstack-', dir='/private/tmp'))
MODEL, DIGEST = 'counsel-nano-q5:latest', '36896b6271148892f83130812cb14116beeb2a518f98a0a17b469250b84901c8'
CASES = ['complete', 'truncated_final', 'truncated_tool', 'max_steps']
REPORT = {'scope':'offline scripted actual-SDK integration; no model inference', 'started_at':datetime.now(timezone.utc).isoformat(), 'planned_cases':CASES, 'cases':[], 'output_dir':str(OUT), 'source_hashes':{}}
for name in ['src/healthcraft/integrations/nemo_native.py', 'src/healthcraft/integrations/nemo_roster.py', 'integrations/nemo_gym/native_ollama.py', 'integrations/nemo_gym/roster_resources.py', 'configs/mcp-tools.json']:
    REPORT['source_hashes'][name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()

def save():
    (OUT/'report.json').write_text(json.dumps(REPORT, indent=2, sort_keys=True)+'\n')
save()

class ResponseShim:
    def __init__(self, response):
        self.response=response; self.status=response.status_code; self.ok=200<=self.status<400
        self.content=self; self.cookies=dict(response.cookies); self.request_info=str(response.request)
    async def read(self): return self.response.content
    def raise_for_status(self): self.response.raise_for_status()

async def run_case(case):
    entry={'case':case, 'status':'started', 'requests':[]}; REPORT['cases'].append(entry); save()
    captures=OUT/case; captures.mkdir()
    calls=[]; counter=0
    def fake_provider(self, path, payload=None):
        nonlocal counter
        calls.append({'path':path,'payload':copy.deepcopy(payload)})
        if path=='/api/tags': return {'models':[{'name':MODEL,'digest':DIGEST}]}
        if path=='/api/show': return {'capabilities':['completion','tools','thinking'],'details':{}}
        if path=='/api/version': return {'version':'0.34.4'}
        assert path=='/api/chat', path
        counter+=1
        message={'role':'assistant','content':''}; reason='stop'
        if counter==1:
            message['tool_calls']=[{'function':{'name':'searchEncounters','arguments':{}}}]
            if case=='truncated_tool': reason='length'
        elif counter==2:
            result=json.loads(payload['messages'][-1]['content'])
            assert result['status']=='ok' and len(result['data'])==4
            message['tool_calls']=[{'function':{'name':'getEncounterDetails','arguments':{'encounter_id':row['id']}}} for row in result['data']]
        else:
            assert counter==3
            message['content']='Retrieved all encounter details.'
            if case=='truncated_final': reason='length'
        return {'model':MODEL,'message':message,'done':True,'done_reason':reason,'prompt_eval_count':35,'eval_count':6}
    server_client=MagicMock(spec=ServerClient); server_client.global_config_dict={}
    resource=RosterResourcesServer(config=RosterResourcesConfig(host='127.0.0.1',port=0,entrypoint='roster_resources.py',name='resources'),server_client=server_client)
    model=NativeOllamaModel(config=NativeOllamaModelConfig(host='127.0.0.1',port=0,entrypoint='native_ollama.py',name='model',model=MODEL,expected_digest=DIGEST,capture_dir=captures,output_budget=2048),server_client=server_client)
    agent=SimpleAgent(config=SimpleAgentConfig(host='127.0.0.1',port=0,entrypoint='app.py',name='agent',resources_server={'type':'resources_servers','name':'resources'},model_server={'type':'responses_api_models','name':'model'},max_steps=2 if case=='max_steps' else 8),server_client=server_client)
    apps={'resources':resource.setup_webserver(),'model':model.setup_webserver(),'agent':agent.setup_webserver()}
    latest_resource_cookies={}; seed_result=None
    async def post(server_name,url_path,json,cookies=None):
        nonlocal latest_resource_cookies, seed_result
        data=json.model_dump(mode='json') if hasattr(json,'model_dump') else json
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=apps[server_name]),base_url='http://testserver',cookies=cookies or {}) as client:
            response=await client.post(url_path,json=data)
        entry['requests'].append({'server':server_name,'path':url_path,'status':response.status_code})
        if server_name=='resources':
            latest_resource_cookies=dict(response.cookies)
            if url_path=='/seed_session' and response.status_code==200: seed_result=response.json()
        if response.status_code>=400:
            entry.setdefault('http_errors',[]).append({'server':server_name,'path':url_path,'status':response.status_code,'body':response.text})
        return ResponseShim(response)
    server_client.post.side_effect=post
    body={'fixture_key':FIXTURE_KEY,'episode_id':f'episode-{case}','responses_create_params':{'model':MODEL,'instructions':'You are a tool-using assistant performing a source-record retrieval exercise.','input':MECHANICAL_PROMPT,'tools':[{'type':'function','strict':False,**t} for t in tool_definitions()],'max_output_tokens':2048,'temperature':0}}
    try:
        with patch.object(OllamaClient,'_request',fake_provider):
            response=await post('agent','/run',body)
            response.raise_for_status()
            result=response.response.json(); entry['result']=result
        expected_calls=5 if case in ('complete','truncated_final','max_steps') else 0
        assert seed_result is not None
        snapshot=resource.sessions.snapshot(seed_result['resources_session_id'])
        entry['snapshot']=snapshot; entry['provider_calls']=calls
        assert len(snapshot['calls'])==expected_calls, len(snapshot['calls'])
        assert result['reward']==(1.0 if case=='complete' else 0.0), result
        assert result['mechanical_passed']==(case=='complete'), result
        assert result['benchmark_score'] is None and result['benchmark_comparable'] is False and result['grading_complete'] is False
        assert result['certificate']['coverage']['retrieved_members']==(4 if expected_calls==5 else 0)
        assert result['certificate']['coverage']['measured_clinical_criteria']==0
        assert result['certificate']['coverage']['measured_safety_criteria']==0
        for call in calls:
            if call['path']=='/api/chat':
                payload=call['payload']; assert payload['options']=={'temperature':0.0,'seed':42,'num_ctx':32768,'num_predict':2048}
                assert payload['think'] is False and payload['stream'] is False
        closed=await post('resources','/close_session',{'resources_session_id':seed_result['resources_session_id'],'episode_id':body['episode_id']},latest_resource_cookies)
        assert closed.status==200 and resource.sessions.active_count==0
        entry['status']='passed'
    except Exception:
        entry['status']='failed'; entry['traceback']=traceback.format_exc(); entry['provider_calls']=calls
        if seed_result:
            entry['snapshot']=resource.sessions.snapshot(seed_result['resources_session_id'])
    finally:
        entry['provider_chat_count']=counter; save()

async def main():
    for case in CASES:
        await run_case(case)
    REPORT['finished_at']=datetime.now(timezone.utc).isoformat(); save()
    print(json.dumps({'report':str(OUT/'report.json'),'cases':[{k:v for k,v in row.items() if k in ('case','status','provider_chat_count','traceback')} for row in REPORT['cases']]},indent=2))
    return all(row['status']=='passed' for row in REPORT['cases'])

def forbid_network(event,args):
    if event=='socket.connect' and isinstance(args[1],tuple):
        raise AssertionError('Network socket connection forbidden in fake integration probe')
sys.addaudithook(forbid_network)
raise SystemExit(0 if asyncio.run(main()) else 1)
