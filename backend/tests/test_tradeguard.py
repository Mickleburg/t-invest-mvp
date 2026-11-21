"""Offline tests use explicit doubles and hypothetical input, never live market assertions."""
import asyncio
from decimal import Decimal
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from backend.app.agent.models import Reply,RiskInputs,ToolRequest
from backend.app.risk.engine import calculate
from backend.app.api.routes import create_app
from backend.app.integrations.tools import execute,specifications,candidates

TEXT='Покупка акций. Капитал 100000 рублей, риск 2%. Вход 300 рублей, стоп 294 рубля, цель 312 рублей. Лот 10 акций, количество 400 акций.'

def risk(**changes):
    base={key:None for key in RiskInputs.model_fields}
    base.update(instrument_kind='share',direction='long')
    for key,value in [('capital','100000'),('risk_percent','2'),('entry','300'),('stop','294'),('target','312'),('lot_size','10'),('quantity','400')]:base[key]={'value':value,'quote':TEXT}
    for key in ('capital_currency','price_currency'):base[key]={'value':'rub','quote':TEXT}
    return RiskInputs.model_validate({**base,**changes})

def reply(**changes):
    return Reply.model_validate({'reply':'Уточним основания идеи.','questions':['Чьи ожидания и за какой период?'],
                                'plan':None,'risk_inputs':None,'facts':[],'tool_requests':[],**changes})

def test_position_sizing_and_over_budget_are_deterministic():
    result=calculate(risk(),[TEXT]);v=result['values']
    assert result['status']=='calculated'
    assert Decimal(v['risk_budget'])==2000 and Decimal(v['max_quantity'])==330
    assert Decimal(v['loss_at_max_quantity'])==1980 and Decimal(v['position_loss'])==2400
    assert Decimal(v['position_risk_percent'])==Decimal('2.4') and v['over_budget']
    assert Decimal(v['reward_risk_ratio'])==2
    assert any('Комиссии' in n for n in result['notes'])

@pytest.mark.parametrize('field,value',[('entry','999'),('capital','NaN'),('stop','-1')])
def test_unprovided_numbers_never_calculated(field,value):
    r=calculate(risk(**{field:{'value':value,'quote':TEXT}}),[TEXT])
    assert r['status']=='invalid_inputs' and not r['values']

def test_wrong_stop_direction_and_currency_mismatch():
    assert calculate(risk(direction='short'),[TEXT])['status']=='invalid_inputs'
    foreign=TEXT+' Валюта цен USD.'
    r=calculate(risk(price_currency={'value':'usd','quote':foreign}),[foreign])
    assert r['status']=='insufficient_data' and 'max_quantity' not in r['values']

def test_missing_capital_or_stop_is_not_guessed():
    r=calculate(risk(stop=None),[TEXT]);assert r['status']=='insufficient_data'
    r=calculate(risk(capital=None),[TEXT]);assert r['status']=='partial' and 'position_risk_percent' not in r['values']

def test_lot_and_fractional_quantity_rejected():
    text=TEXT+' 405 акций, 1.5 акций.'
    for quantity in ('405','1.5'):
        assert calculate(risk(quantity={'value':quantity,'quote':text}),[text])['status']=='invalid_inputs'

def test_futures_without_point_value_never_use_stock_formula():
    r=calculate(risk(instrument_kind='future'),[TEXT])
    assert r['status']=='insufficient_data' and 'position_loss' not in r['values']

def test_futures_assumptions_are_labelled_and_mcp_conflict_blocks():
    text=TEXT+' Стоимость пункта 1000 рублей.'
    f=risk(instrument_kind='future',point_value={'value':'1000','quote':text},point_value_currency={'value':'rub','quote':text})
    r=calculate(f,[text]);assert r['status']=='calculated' and any('не подтверждена' in n for n in r['notes'])
    assert Decimal(r['values']['loss_per_unit'])==6000
    conflict=calculate(f,[text],{'point_value':'500','currency':'rub','lot_size':'1','evidence_id':'spec-test'})
    assert conflict['status']=='insufficient_data'

def test_future_spec_point_value_uses_tick_amount_divided_by_tick_size():
    records=[{'id':'e','kind':'spec','status':'ok','result':{'instrument':{'id':'future-1','kind':'future'},
      'data':{'instrument':{'lot':1,'minPriceIncrement':{'value':'0.01'},'minPriceIncrementAmount':{'value':'10','currency':'rub'}}}}}]
    assert Decimal(specifications(records,'future-1')['point_value'])==1000
    assert specifications(records,'other-id') is None


def test_many_share_matches_cannot_hide_futures():
    rows=[{'uid':f's{i}','ticker':f'BR{i}','classCode':'TQBR','instrumentKind':'INSTRUMENT_TYPE_SHARE'} for i in range(100)]
    rows.append({'uid':'oil','ticker':'BRZ6','classCode':'SPBFUT','name':'Нефть Brent','instrumentKind':'INSTRUMENT_TYPE_FUTURES','expirationDate':'2026-12-01'})
    result=candidates(rows,'BR')
    assert any(r['id']=='oil' and r['expiration_date']=='2026-12-01' for r in result)
    assert len(result)<=8


def test_exact_sber_still_first_with_mixed_candidates():
    rows=[{'uid':'f','ticker':'SBRZ6','classCode':'SPBFUT','instrumentKind':'INSTRUMENT_TYPE_FUTURES'},
          {'uid':'s','ticker':'SBER','classCode':'TQBR','instrumentKind':'INSTRUMENT_TYPE_SHARE'}]
    assert candidates(rows,'SBER')[0]['id']=='s'

def test_unknown_instrument_is_rejected_before_bank_call(monkeypatch):
    def fail():pytest.fail('No network call allowed for an unbound instrument')
    monkeypatch.setattr('backend.app.integrations.tools.sandbox_session',fail)
    r=asyncio.run(execute(ToolRequest(kind='quote',query=None,instrument_id='invented',question=None),{}))
    assert r['status']=='unavailable' and r['calls']==[]

def test_api_history_context_idempotency_and_educational_mode(tmp_path):
    contexts=[]
    async def model(context):contexts.append(context.copy());r=reply();return r,r.model_dump()
    with TestClient(create_app(tmp_path,model=model)) as client:
        sid=client.post('/api/sessions').json()['session']['id'];base='/api/sessions/'+sid
        body={'text':'Учебная идея про Сбер','request_id':str(uuid4()),'educational':True}
        first=client.post(base+'/messages',json=body).json()
        assert first['messages'][-1]['role']=='assistant' and not first['session']['processing']
        client.post(base+'/messages',json=body);assert len(contexts)==1
        body={'text':'Отвечаю на уточнение','request_id':str(uuid4()),'educational':False}
        client.post(base+'/messages',json=body)
        assert contexts[-1]['educational'] and contexts[-1]['messages'][-1]['text']==body['text']
        assert any(m['role']=='assistant' for m in contexts[-1]['messages'])
        assert client.get(base).json()['session']['title']=='Учебная идея про Сбер'

def test_invalid_source_reference_does_not_become_a_fact(tmp_path):
    async def model(context):
        r=reply(facts=[{'statement':'Придуманный внешний факт','evidence_id':'absent'}]);return r,r.model_dump()
    with TestClient(create_app(tmp_path,model=model)) as client:
        sid=client.post('/api/sessions').json()['session']['id']
        r=client.post(f'/api/sessions/{sid}/messages',json={'text':'Тест','request_id':str(uuid4())}).json()
        assert r['messages'][-1]['response']['error']=='dialogue_failed'
        assert 'Придуманный внешний факт' not in r['messages'][-1]['text']

def test_source_failure_is_given_to_model_without_mock_success(tmp_path):
    contexts=[]
    async def model(context):
        contexts.append(context)
        requests=[{'kind':'search','query':'SBER','instrument_id':None,'question':None}] if not context['evidence'] else []
        r=reply(tool_requests=requests);return r,r.model_dump()
    async def tool(request,known):return {'id':'failed-source','kind':'search','status':'unavailable','calls':[],'result':None,'observed_at':'2026-11-21T00:00:00Z'}
    with TestClient(create_app(tmp_path,model=model,tool=tool)) as client:
        sid=client.post('/api/sessions').json()['session']['id']
        r=client.post(f'/api/sessions/{sid}/messages',json={'text':'Тест','request_id':str(uuid4())}).json()
        assert r['evidence'][0]['status']=='unavailable' and len(contexts)==2
