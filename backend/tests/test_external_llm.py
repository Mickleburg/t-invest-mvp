"""Offline SDK transport tests; no keys or paid services."""
import asyncio
from decimal import Decimal
import json

import httpx
import pytest

from backend.app.interfaces import ProviderUnavailable
from backend.app.llm.external import APISettings, ChatAPIProvider


def settings(**changes):
    values = dict(provider='deepseek', base_url='https://api.deepseek.com',
                  model='test-model', api_key='test-secret',
                  input_usd_per_million=Decimal('1'), output_usd_per_million=Decimal('1'))
    return APISettings(**(values | changes))


def payload():
    return dict(reply='TEST DOUBLE: объяснение.', questions=[], plan=None,
                risk_inputs=None, facts=[], tool_requests=[])


def response(content=None, finish='stop'):
    return dict(id='test', object='chat.completion', created=0, model='test-model',
                choices=[dict(index=0, finish_reason=finish,
                              message=dict(role='assistant', content=content))])


def run(provider):
    return asyncio.run(provider.complete({'messages': [{'role': 'user', 'text': 'Что такое ГО?'}]}))


def test_sdk_request_and_local_schema_validation():
    def handle(request):
        assert str(request.url) == 'https://api.deepseek.com/chat/completions'
        assert request.headers['authorization'] == 'Bearer test-secret'
        body = json.loads(request.content)
        assert body['model'] == 'test-model' and body['max_tokens'] == 2048
        assert 'tools' not in body and 'response_format' not in body
        assert 'test-secret' not in body['messages'][0]['content']
        return httpx.Response(200, json=response(json.dumps(payload())))
    reply, raw = run(ChatAPIProvider(settings(), transport=httpx.MockTransport(handle)))
    assert reply.reply == payload()['reply'] and raw == payload()


@pytest.mark.parametrize('content,finish', [('', 'stop'), ('not JSON', 'stop'),
    ('{}', 'stop'), (json.dumps(payload()), 'length'),
    (json.dumps(payload() | {'tool_requests': [{'kind': 'place_order'}]}), 'stop')])
def test_malformed_truncated_and_unsafe_reply_rejected(content, finish):
    provider = ChatAPIProvider(settings(), transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=response(content, finish))))
    with pytest.raises(ProviderUnavailable): run(provider)


@pytest.mark.parametrize('status', [401, 429, 500, 302])
def test_http_failure_no_retry_no_sensitive_error(status, caplog):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={'error': {'message': 'test-secret'}},
                              headers={'Location': 'https://other.example'})
    with pytest.raises(ProviderUnavailable) as exc:
        run(ChatAPIProvider(settings(), transport=httpx.MockTransport(handle)))
    assert len(calls) == 1
    assert 'test-secret' not in str(exc.value) + caplog.text


def test_timeout_is_safe():
    def handle(request): raise httpx.ReadTimeout('test-secret')
    with pytest.raises(ProviderUnavailable, match='unavailable'):
        run(ChatAPIProvider(settings(), transport=httpx.MockTransport(handle)))


@pytest.mark.parametrize('change', [dict(api_key=''), dict(input_usd_per_million=Decimal('0')),
    dict(max_input_bytes=10), dict(max_reserved_tokens=10), dict(max_cost_usd=Decimal('.000001'))])
def test_budget_or_configuration_blocks_before_network(change):
    def handle(request): pytest.fail('Network must not be called')
    with pytest.raises(ProviderUnavailable):
        run(ChatAPIProvider(settings(**change), transport=httpx.MockTransport(handle)))


def test_concurrent_calls_reserve_budget_atomically_and_failure_keeps_reservation():
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(500, json={})
    provider = ChatAPIProvider(settings(max_calls=1), transport=httpx.MockTransport(handle))
    async def scenario():
        return await asyncio.gather(provider.complete({}), provider.complete({}), return_exceptions=True)
    assert all(isinstance(r, ProviderUnavailable) for r in asyncio.run(scenario()))
    assert len(calls) == 1 and provider.reserved_cost > 0


@pytest.mark.parametrize('change', [dict(base_url='http://api.deepseek.com'),
    dict(base_url='https://other.example'), dict(base_url='https://api.deepseek.com?key=x'),
    dict(max_cost_usd=Decimal('NaN')), dict(timeout=float('inf')), dict(max_calls=0)])
def test_bad_settings_rejected(change):
    with pytest.raises(ValueError): ChatAPIProvider(settings(**change))


def test_http_agent_storage_path_uses_api_adapter(tmp_path):
    from fastapi.testclient import TestClient
    from uuid import uuid4
    from backend.app.main import create_app
    provider = ChatAPIProvider(settings(), transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=response(json.dumps(payload())))))
    with TestClient(create_app(tmp_path, provider=provider, test_doubles=True)) as client:
        sid = client.post('/api/sessions').json()['session']['id']
        result = client.post(f'/api/sessions/{sid}/messages', json={
            'text': 'Что такое ГО?', 'request_id': str(uuid4())})
        assert result.status_code == 200
        assert result.json()['messages'][-1]['text'] == payload()['reply']
        history = client.get(f'/api/sessions/{sid}').json()
        assert history['messages'][-1]['response']['risk_calculation']['status'] != 'calculated'
        assert client.get('/api/health').json()['trading'] is False


def test_pt_uses_bare_model_and_verified_json_mode():
    def handle(request):
        body = json.loads(request.content)
        assert str(request.url) == 'https://api-llm.ptsecurity.com/v1/chat/completions'
        assert body['model'] == 'deepseek'
        assert body['response_format'] == {'type': 'json_object'}
        return httpx.Response(200, json=response(json.dumps(payload())))
    provider = ChatAPIProvider(settings(provider='pt', base_url='https://api-llm.ptsecurity.com/v1',
        model='deepseek'), transport=httpx.MockTransport(handle))
    assert run(provider)[0].reply == payload()['reply']
    with pytest.raises(ValueError, match='bare'):
        ChatAPIProvider(settings(provider='pt', base_url='https://api-llm.ptsecurity.com/v1', model='pt/deepseek'))


@pytest.mark.parametrize('pattern,bypass', [('*.ptsecurity.com', True), ('.ptsecurity.com', True),
    ('api-llm.ptsecurity.com', True), ('*', True), ('*.other.example', False),
    ('*.security.com', False), ('', False)])
def test_pt_proxy_routing_keeps_tls_verification(monkeypatch, pattern, bypass):
    import ssl
    from backend.app.llm import external
    from unittest.mock import patch
    monkeypatch.delenv('no_proxy', raising=False)
    monkeypatch.setenv('NO_PROXY', pattern)
    async def scenario():
        with patch.object(external.httpx, 'AsyncClient') as constructor:
            external.api_http_client(settings(provider='pt', base_url='https://api-llm.ptsecurity.com/v1'))
            options = constructor.call_args.kwargs
            assert options['trust_env'] is not bypass
            assert options['verify'].verify_mode == ssl.CERT_REQUIRED
            assert options['verify'].check_hostname
    asyncio.run(scenario())


def test_explicit_ca_is_loaded_and_invalid_file_fails_closed(monkeypatch):
    import certifi
    from backend.app.llm.external import api_http_client
    monkeypatch.setenv('SSL_CERT_FILE', certifi.where())
    async def scenario():
        async with api_http_client(settings()) as client:
            assert client is not None
    asyncio.run(scenario())
    monkeypatch.setenv('SSL_CERT_FILE', 'nonexistent-corporate-ca.pem')
    with pytest.raises(FileNotFoundError): api_http_client(settings())


def test_confirmed_zero_cost_pt_keeps_call_limits():
    provider=ChatAPIProvider(settings(provider='pt',base_url='https://api-llm.ptsecurity.com/v1',
        model='deepseek',input_usd_per_million=Decimal(0),output_usd_per_million=Decimal(0),
        zero_cost_confirmed=True,max_calls=1),transport=httpx.MockTransport(
        lambda request:httpx.Response(200,json=response(json.dumps(payload())))))
    assert run(provider)[0].reply==payload()['reply']
    assert provider.reserved_cost==0 and provider.reserved_tokens>0
    with pytest.raises(ProviderUnavailable,match='budget exhausted'):run(provider)
    assert not ChatAPIProvider(settings(input_usd_per_million=Decimal(0),
        output_usd_per_million=Decimal(0),zero_cost_confirmed=True)).configured


def test_zero_cost_env_requires_explicit_confirmation(monkeypatch):
    monkeypatch.setenv('LLM_API_KEY','TEST DOUBLE')
    monkeypatch.setenv('LLM_BASE_URL','https://api-llm.ptsecurity.com/v1')
    monkeypatch.setenv('LLM_MODEL','deepseek')
    monkeypatch.setenv('LLM_INPUT_USD_PER_MILLION','0')
    monkeypatch.setenv('LLM_OUTPUT_USD_PER_MILLION','0')
    monkeypatch.setenv('LLM_ZERO_COST_CONFIRMED','0')
    assert not ChatAPIProvider(APISettings.from_env('pt')).configured
    monkeypatch.setenv('LLM_ZERO_COST_CONFIRMED','1')
    assert ChatAPIProvider(APISettings.from_env('pt')).configured


def test_pt_generation_settings_and_model_identity():
    def handle(request):
        body=json.loads(request.content)
        assert body['temperature']==0 and body['chat_template_kwargs']=={'enable_thinking':False}
        return httpx.Response(200,json=response(json.dumps(payload()))|{'model':'ACTUAL-TEST-MODEL'})
    provider=ChatAPIProvider(settings(provider='pt',base_url='https://api-llm.ptsecurity.com/v1',
        model='qwen35-122b-a10b',temperature=0,disable_thinking=True),transport=httpx.MockTransport(handle))
    run(provider)
    assert provider.last_call['response_model']=='ACTUAL-TEST-MODEL'
    assert provider.last_call['requested_model']=='qwen35-122b-a10b'


@pytest.mark.parametrize('temperature',[-.1,2.1,float('nan')])
def test_invalid_temperature_fails_before_network(temperature):
    with pytest.raises(ValueError):ChatAPIProvider(settings(temperature=temperature))


def test_default_pt_profile_is_explicit_and_can_be_overridden(monkeypatch):
    monkeypatch.delenv('LLM_MODEL',raising=False)
    monkeypatch.delenv('LLM_BASE_URL',raising=False)
    monkeypatch.setenv('LLM_DISABLE_THINKING','')
    monkeypatch.setenv('LLM_TEMPERATURE','0')
    selected=APISettings.from_env('pt')
    assert selected.model=='deepseek' and selected.disable_thinking and selected.temperature==0
    monkeypatch.setenv('LLM_DISABLE_THINKING','0')
    assert not APISettings.from_env('pt').disable_thinking
    monkeypatch.setenv('LLM_DISABLE_THINKING','typo')
    with pytest.raises(ValueError):APISettings.from_env('pt')
