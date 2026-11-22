"""Offline doubles for transport policy and futures units; no network or market claims."""
import asyncio
from decimal import Decimal
import ssl
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from jsonschema import ValidationError

from backend.app.agent.models import RiskInputs
from backend.app.integrations.tinvest import http_client, ReadOnlySession, SandboxError
from backend.app.integrations.tools import specifications
from backend.app.risk.engine import calculate


@pytest.mark.parametrize('proxy,expected', [('0', False), ('1', True)])
def test_mcp_proxy_is_explicit_and_tls_is_required(monkeypatch, proxy, expected):
    monkeypatch.setenv('TINVEST_MCP_USE_PROXY', proxy)
    with patch('backend.app.integrations.tinvest.httpx.AsyncClient') as constructor:
        http_client(headers={'Authorization': 'Bearer TEST DOUBLE'}, timeout=15)
        options=constructor.call_args.kwargs
        assert options['trust_env'] is expected
        assert options['verify'].verify_mode==ssl.CERT_REQUIRED and options['verify'].check_hostname
        assert options['follow_redirects'] is False


def test_mcp_invalid_proxy_setting_fails(monkeypatch):
    monkeypatch.setenv('TINVEST_MCP_USE_PROXY','maybe')
    with pytest.raises(ValueError): http_client()


def test_readonly_and_argument_validation_happen_before_remote_call():
    class Remote:
        async def call_tool(self,*args): pytest.fail('No request must leave the allowlist/argument gate')
    remote=ReadOnlySession(Remote(), {'invest_get_future': SimpleNamespace(inputSchema={
        'type':'object','properties':{'instrumentId':{'type':'string'}},'required':['instrumentId']})})
    with pytest.raises(SandboxError): asyncio.run(remote.call('invest_post_order',{}))
    with pytest.raises(ValidationError): asyncio.run(remote.call('invest_get_future',{}))


def spec_record(**changes):
    card={'lot':1,'currency':'rub','minPriceIncrement':{'value':'0.5'},
          'minPriceIncrementAmount':{'value':'2'},'expirationDate':'2030-12-20'} | changes
    return {'id':'TEST DOUBLE spec','kind':'spec','status':'ok','observed_at':'2030-01-01T00:00:00Z',
        'result':{'instrument':{'id':'TEST DOUBLE future','kind':'future'},'data':{'instrument':card}}}


def inputs(text, **changes):
    values={name:None for name in RiskInputs.model_fields}
    values.update(instrument_kind='future',instrument_id='TEST DOUBLE future',direction='long')
    for name,number in [('capital','100000'),('risk_percent','1'),('entry','100'),('stop','99'),('quantity','2')]:
        values[name]={'value':number,'quote':text}
    values['capital_currency']={'value':'rub','quote':text}
    values['price_currency']={'value':'points','quote':text}
    return RiskInputs.model_validate(values | changes)


TEXT='TEST DOUBLE: капитал 100000 рублей, риск 1%. Вход 100 пунктов, стоп 99 пунктов, количество 2 контракта.'


def test_quotation_tick_uses_currency_of_same_contract_and_decimal_ratio():
    spec=specifications([spec_record()],'TEST DOUBLE future')
    assert spec['currency']=='rub' and Decimal(spec['point_value'])==4
    assert spec['tick_size']=='0.5' and spec['expiration_date']=='2030-12-20'
    result=calculate(inputs(TEXT),[TEXT],spec)
    assert result['status']=='calculated' and Decimal(result['values']['position_loss'])==8
    assert result['values']['spec_evidence_id']=='TEST DOUBLE spec'


def test_missing_currency_does_not_become_rubles_and_conflict_blocks():
    spec=specifications([spec_record(currency=None)],'TEST DOUBLE future')
    assert 'point_value' not in spec
    assert calculate(inputs(TEXT),[TEXT],spec)['status']=='insufficient_data'
    assert specifications([spec_record(minPriceIncrementAmount={'value':'2','currency':'usd'})],
                          'TEST DOUBLE future') is None


def test_future_currency_prices_and_non_tick_aligned_stop_are_rejected():
    spec=specifications([spec_record()],'TEST DOUBLE future')
    rub=inputs(TEXT,price_currency={'value':'rub','quote':TEXT})
    assert calculate(rub,[TEXT],spec)['status']=='insufficient_data'
    text=TEXT+' Уточнение: стоп 99.2 пункта.'
    off_tick=inputs(text,stop={'value':'99.2','quote':text})
    assert calculate(off_tick,[text],spec)['status']=='invalid_inputs'


@pytest.mark.parametrize('field', ['minPriceIncrement','minPriceIncrementAmount'])
def test_zero_tick_or_value_never_produces_verified_multiplier(field):
    spec=specifications([spec_record(**{field:{'value':'0'}})],'TEST DOUBLE future')
    assert 'point_value' not in spec
