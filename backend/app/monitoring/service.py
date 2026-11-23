"""Read-only checks of immutable confirmed plans; durable leases and notifications."""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from backend.app.agent.models import ToolRequest
from backend.app.integrations.tools import execute
from backend.app.plans.schema import PlanError
from backend.app.plans.sources import fresh, instant, not_expired, quote_value, specification
from backend.app.storage.repository import dump

log = logging.getLogger(__name__)
OPERATORS = {'lt': lambda a, b: a < b, 'lte': lambda a, b: a <= b,
             'gt': lambda a, b: a > b, 'gte': lambda a, b: a >= b}


class Monitor:
    def __init__(self, store, tool=execute, test_doubles=False, interval=60, clock=None):
        self.store, self.tool, self.test_doubles = store, tool, test_doubles
        self.interval = max(10, min(int(interval), 3600))
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def state(self, plan_id):
        with self.store.connect() as db:
            row = db.execute('SELECT plan_id,confirmed_version,state,last_checked_at,next_check_at FROM monitoring WHERE plan_id=?', (plan_id,)).fetchone()
            if row: return dict(row)
            plan = db.execute('SELECT document FROM plans WHERE id=?', (plan_id,)).fetchone()
            if not plan: raise PlanError(404, 'План не найден')
            return {'plan_id': plan_id, 'confirmed_version': json.loads(plan[0])['version'],
                    'state': 'not_started', 'last_checked_at': None, 'next_check_at': None}

    def checks(self, plan_id):
        self.state(plan_id)
        with self.store.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT payload FROM plan_checks WHERE plan_id=? ORDER BY rowid DESC LIMIT 100', (plan_id,))]

    def notifications(self, plan_id):
        self.state(plan_id)
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT id,plan_id,plan_version,check_id,created_at,text,delivery_status FROM notifications WHERE plan_id=? ORDER BY rowid DESC LIMIT 100', (plan_id,))]

    def acknowledge(self, plan_id, notification_id):
        with self.store.connect() as db:
            db.execute("UPDATE notifications SET delivery_status='delivered' WHERE id=? AND plan_id=?", (notification_id, plan_id))
            row = db.execute('SELECT id,plan_id,plan_version,check_id,created_at,text,delivery_status FROM notifications WHERE id=? AND plan_id=?', (notification_id, plan_id)).fetchone()
            if not row: raise PlanError(404, 'Уведомление не найдено')
            return dict(row)

    async def check(self, plan_id, confirmed_version, request_id):
        owner = str(uuid4()); current = self.clock(); current_text = current.isoformat()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM check_runs WHERE request_id=?', (request_id,)).fetchone()
            if previous:
                if (previous['plan_id'], previous['plan_version']) != (plan_id, confirmed_version):
                    raise PlanError(409, 'Идентификатор проверки уже использован для другой версии')
                return json.loads(previous['response'])
            monitoring = db.execute('SELECT * FROM monitoring WHERE plan_id=?', (plan_id,)).fetchone()
            if not monitoring: raise PlanError(404, 'Подтверждённая версия не найдена')
            if monitoring['confirmed_version'] != confirmed_version: raise PlanError(409, 'Подтверждена другая версия')
            if monitoring['lease_until'] and monitoring['lease_until'] > current_text:
                raise PlanError(409, 'Проверка этой версии уже выполняется')
            snapshot = db.execute('SELECT document FROM plan_snapshots WHERE plan_id=? AND version=?', (plan_id, confirmed_version)).fetchone()
            if not snapshot: raise PlanError(409, 'Подтверждённый снимок отсутствует')
            plan = json.loads(snapshot[0])
            original = db.execute('SELECT payload FROM evidence WHERE id=? AND session_id=?',
                                  (plan['instrument'].get('spec_source_id'), plan['session_id'])).fetchone()
            baseline_spec = specification(json.loads(original[0]), plan['instrument']) if original else None
            db.execute('UPDATE monitoring SET lease_owner=?,lease_until=? WHERE plan_id=?',
                       (owner, (current + timedelta(seconds=120)).isoformat(), plan_id))
        try:
            instrument = plan['instrument']; evidence = []
            for kind in ('spec', 'quote'):
                try:
                    async with asyncio.timeout(30):
                        item = await self.tool(ToolRequest(kind=kind, instrument_id=instrument['id'], query=None, question=None), {instrument['id']: instrument})
                except Exception:
                    item = {'id': str(uuid4()), 'kind': kind, 'status': 'unavailable', 'result': None,
                            'observed_at': self.clock().isoformat(), 'error': 'Источник недоступен; условие не проверено', 'calls': []}
                item['synthetic'] = bool(item.get('synthetic') or self.test_doubles)
                item['instrument_id'] = instrument['id']
                evidence.append(item)
            checked = self.clock(); spec = specification(evidence[0], instrument); quote = quote_value(evidence[1], instrument)
            checks = []; reasons = {}
            for rule in plan['rules']:
                status, value, reason = self._evaluate(plan, rule, spec, quote, evidence, checked, baseline_spec)
                check = {'id': str(uuid4()), 'plan_id': plan_id, 'plan_version': confirmed_version, 'rule_id': rule['id'],
                         'checked_at': checked.isoformat(), 'status': status, 'source_ids': [e['id'] for e in evidence],
                         'observed_value': value}
                checks.append(check); reasons[check['id']] = reason
            response = {'checks': checks}
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                lease = db.execute('SELECT * FROM monitoring WHERE plan_id=?', (plan_id,)).fetchone()
                if lease['confirmed_version'] != confirmed_version or lease['lease_owner'] != owner:
                    raise PlanError(409, 'Во время проверки изменилась подтверждённая версия или владелец проверки')
                for item in evidence:
                    db.execute('INSERT INTO evidence VALUES(?,?,NULL,?)', (item['id'], plan['session_id'], dump(item)))
                for check in checks:
                    previous = db.execute('SELECT payload FROM plan_checks WHERE plan_id=? AND plan_version=? AND rule_id=? ORDER BY rowid DESC LIMIT 1',
                                          (plan_id, confirmed_version, check['rule_id'])).fetchone()
                    old_status = json.loads(previous[0])['status'] if previous else None
                    db.execute('INSERT INTO plan_checks VALUES(?,?,?,?,?,?)', (check['id'], plan_id, confirmed_version, check['rule_id'], request_id, dump(check)))
                    if check['status'] != old_status and (check['status'] != 'affected' or old_status is not None):
                        label = {'satisfied': 'Условие выполнено', 'affected': 'Порог не достигнут', 'insufficient_data': 'Недостаточно данных', 'error': 'Ошибка проверки'}[check['status']]
                        rule_name = 'ценовое условие' if check['rule_id'] == 'stop-price' else check['rule_id']
                        source_name = 'тестовые данные' if any(e['synthetic'] for e in evidence) else 'T-Invest sandbox MCP'
                        text = f"{instrument['ticker']} · версия {confirmed_version} · {rule_name}: {label}. {reasons[check['id']]} Источник: {source_name}."
                        if plan['educational']: text = 'Учебный план. ' + text
                        db.execute('INSERT INTO notifications VALUES(?,?,?,?,?,?,?,?)',
                                   (str(uuid4()), plan_id, confirmed_version, check['rule_id'], check['id'], checked.isoformat(), text, 'stored'))
                db.execute('INSERT INTO check_runs VALUES(?,?,?,?)', (request_id, plan_id, confirmed_version, dump(response)))
                db.execute("UPDATE monitoring SET state='active',last_checked_at=?,next_check_at=?,lease_owner=NULL,lease_until=NULL WHERE plan_id=? AND lease_owner=?",
                           (checked.isoformat(), (checked + timedelta(seconds=self.interval)).isoformat(), plan_id, owner))
            return response
        finally:
            with self.store.connect() as db:
                db.execute('UPDATE monitoring SET lease_owner=NULL,lease_until=NULL WHERE plan_id=? AND lease_owner=?', (plan_id, owner))

    def _evaluate(self, plan, rule, spec, quote, evidence, checked, baseline_spec):
        from decimal import Decimal
        if not rule['automatic']: return 'insufficient_data', None, 'Ручное событие требует проверки человеком.'
        if not spec or not fresh(evidence[0].get('observed_at'), checked, 86400):
            return 'insufficient_data', None, 'Свежая спецификация недоступна.'
        if not baseline_spec or any(spec.get(k) != baseline_spec.get(k) for k in
                                    ('tick_size', 'tick_value', 'expiration_date', 'last_trade_date', 'currency')):
            return 'insufficient_data', None, 'Спецификация изменилась относительно подтверждённого снимка.'
        params = plan['parameters']
        if str(spec.get('lot_size')) != str(params['lot_size']): return 'insufficient_data', None, 'Спецификация лота изменилась.'
        if plan['instrument']['kind'] == 'future':
            if not not_expired(spec, checked): return 'insufficient_data', None, 'Экспирация неизвестна или торги контрактом завершены.'
            if (not spec.get('point_value') or Decimal(spec['point_value']) != Decimal(params['point_value']) or
                    spec.get('currency') != params['point_value_currency'].lower()):
                return 'insufficient_data', None, 'Стоимость пункта или валюта изменилась; пересмотрите план.'
        if not plan['educational'] and any(e['synthetic'] for e in evidence):
            return 'insufficient_data', None, 'Учебный источник не подходит неучебному плану.'
        if not quote or quote['unit'] != rule['unit'] or not fresh(quote['observed_at'], checked, rule['max_age_seconds']):
            return 'insufficient_data', None, 'Котировка отсутствует, устарела или имеет другую единицу.'
        satisfied = OPERATORS[rule['operator']](quote['value'], Decimal(rule['threshold']))
        time = instant(quote['observed_at']).astimezone(timezone(timedelta(hours=3))).strftime('%d.%m.%Y %H:%M:%S МСК')
        unit = 'пунктов' if quote['unit'] == 'points' else quote['unit'].upper()
        operator = {'lt': '<', 'lte': '≤', 'gt': '>', 'gte': '≥'}[rule['operator']]
        reason = f"Котировка {quote['value']} {unit}; время источника {time}; порог {operator} {rule['threshold']}."
        return 'satisfied' if satisfied else 'affected', str(quote['value']), reason

    async def tick(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT plan_id,confirmed_version FROM monitoring WHERE state IN ('active','error') AND next_check_at<=? ORDER BY next_check_at LIMIT 20", (self.clock().isoformat(),)).fetchall()
        for row in rows:
            try: await self.check(row['plan_id'], row['confirmed_version'], str(uuid4()))
            except PlanError: pass
            except Exception as exc:
                # No raw provider response, credentials or personal plan text in logs.
                log.warning('monitoring_failed type=%s', type(exc).__name__)
                with self.store.connect() as db:
                    db.execute("UPDATE monitoring SET state='error',next_check_at=? WHERE plan_id=? AND confirmed_version=?",
                               ((self.clock() + timedelta(seconds=self.interval)).isoformat(), row['plan_id'], row['confirmed_version']))

    async def run(self):
        while True:
            try: await self.tick()
            except Exception as exc: log.warning('monitoring_cycle_failed type=%s', type(exc).__name__)
            await asyncio.sleep(5)
