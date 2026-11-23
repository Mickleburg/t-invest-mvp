"""Explicit synthetic CP6 fixtures for offline tests and opt-in developer smoke."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from backend.app.agent.models import Reply, RiskInputs

TEXT = 'Учебный SiZ6 SPBFUT: long, капитал 100000 рублей, риск 1%, вход 100000 пунктов, стоп 99000 пунктов, количество 1 контракт.'
INSTRUMENT = {'id': 'CP6-TEST-DOUBLE', 'ticker': 'SiZ6', 'class_code': 'SPBFUT', 'kind': 'future', 'exact_match': True}
NARRATIVE = {'hypothesis': 'УЧЕБНАЯ ГИПОТЕЗА: проверка движения цены', 'horizon': 'Один учебный день',
             'entry_conditions': ['После проверки исходной гипотезы'], 'exit_conditions': ['По заданному стопу'],
             'review_conditions': ['При изменении спецификации пересмотреть план']}


class Fixtures:
    def __init__(self):
        self.current = datetime(2026, 11, 23, 10, tzinfo=timezone.utc)
        self.price = '98000'; self.point_value = '1'; self.unit = 'pt.'
        self.failed = None; self.stale = False; self.future = False; self.wrong_identity = False; self.calls = []

    def clock(self): return self.current

    async def tool(self, request, known):
        self.calls.append(request.kind)
        stamp = self.current.isoformat()
        e = {'id': str(uuid4()), 'kind': request.kind, 'requested_at': stamp, 'observed_at': stamp,
             'status': 'ok', 'calls': [], 'synthetic': True}
        if request.kind == self.failed: return e | {'status': 'unavailable', 'result': None}
        if request.kind == 'search': return e | {'result': {'instruments': [INSTRUMENT]}}
        instrument = INSTRUMENT | ({'id': 'OTHER'} if self.wrong_identity else {})
        if request.kind == 'spec':
            return e | {'result': {'instrument': instrument, 'data': {'instrument': {'uid': instrument['id'], 'ticker': 'SiZ6', 'classCode': 'SPBFUT',
                        'lot': 1, 'currency': 'rub', 'minPriceIncrement': {'value': '1'},
                        'minPriceIncrementAmount': {'value': self.point_value}, 'expirationDate': '2026-12-18'}}}}
        observed = self.current + timedelta(seconds=600 if self.future else -600 if self.stale else 0)
        return e | {'result': {'instrument': instrument, 'data': {'instruments': [{'ticker': 'SiZ6', 'classCode': 'SPBFUT',
                    'priceCurrency': self.unit, 'values': [{'type': 'INSTRUMENT_VALUE_LAST_PRICE', 'value': {'value': self.price}, 'time': observed.isoformat()}]}]}}}

    async def model(self, context):
        fields = {key: None for key in RiskInputs.model_fields}
        fields.update(instrument_kind='future', instrument_id=INSTRUMENT['id'], direction='long')
        for key, value in [('entry', '100000'), ('stop', '99000'), ('capital', '100000'), ('risk_percent', '1'), ('quantity', '1')]:
            fields[key] = {'value': value, 'quote': TEXT}
        fields['price_currency'] = {'value': 'points', 'quote': TEXT}
        fields['capital_currency'] = {'value': 'rub', 'quote': TEXT}
        reply = Reply(reply='УЧЕБНЫЙ ПРОВАЙДЕР', questions=[], plan=None, risk_inputs=RiskInputs.model_validate(fields), facts=[], tool_requests=[])
        return reply, reply.model_dump()
