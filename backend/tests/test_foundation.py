import copy
import json
from pathlib import Path
import tempfile
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator,FormatChecker
from backend.scripts.check_contracts import check
from backend.app.main import create_app
from backend.app.llm import provider_for
from backend.app.interfaces import ProviderUnavailable

ROOT=Path(__file__).resolve().parents[2]

def test_contract_freeze_and_examples():assert check()['implemented_drift'] is False

@pytest.mark.parametrize('mutation',['missing_risk','stale','synthetic_live','manual_auto','partial_future'])
def test_confirmed_plan_rejects_incomplete_or_unsafe_structure(mutation):
    schema=json.loads((ROOT/'contracts/trade_plan.schema.json').read_text(encoding='utf-8'))
    plan=json.loads((ROOT/'contracts/examples/trade_plan.confirmed.json').read_text(encoding='utf-8'))
    if mutation=='missing_risk':del plan['risk']
    if mutation=='stale':plan['educational']=False;plan['sources'][0].update(synthetic=False,freshness='stale')
    if mutation=='synthetic_live':plan['educational']=False
    if mutation=='manual_auto':plan['rules'][0].update(metric='manual_event',automatic=True)
    if mutation=='partial_future':del plan['parameters']['point_value']
    assert list(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(plan))

def test_minimal_draft_is_allowed():
    schema=json.loads((ROOT/'contracts/trade_plan.schema.json').read_text(encoding='utf-8'))
    Draft202012Validator(schema,format_checker=FormatChecker()).validate({'id':'00000000-0000-4000-8000-000000000001','version':1,'status':'draft','educational':True})

def test_api_only_and_disabled_provider_are_honest(tmp_path,monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER','disabled')
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/').status_code==404 and client.get('/static/app.js').status_code==404
        health=client.get('/api/health').json();assert not health['llm_configured'] and not health['trading']
        sid=client.post('/api/sessions').json()['session']['id']
        assert client.get('/api/sessions/'+sid).status_code==200
        assert client.get('/api/plans/missing').status_code==404

def test_provider_can_be_replaced_without_service_changes(tmp_path):
    from backend.app.agent.models import Reply
    from uuid import uuid4
    class Provider:
        async def complete(self,context):
            reply=Reply(reply='TEST DOUBLE: clarified',questions=[],plan=None,risk_inputs=None,facts=[],tool_requests=[])
            return reply,reply.model_dump()
    with TestClient(create_app(tmp_path,provider=Provider(),test_doubles=True)) as client:
        sid=client.post('/api/sessions').json()['session']['id']
        result=client.post(f'/api/sessions/{sid}/messages',json={'text':'test','request_id':str(uuid4())}).json()
        assert result['messages'][-1]['text']=='TEST DOUBLE: clarified'

def test_backend_modules_do_not_import_removed_prototypes():
    import ast
    for path in (ROOT/'backend').rglob('*.py'):
        if '.venv' in path.parts or 'runtime' in path.parts:continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            names = [a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else []
            assert not any(name.split('.')[0] in ('thesisguard','tradeguard') for name in names), str(path)
