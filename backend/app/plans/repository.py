"""Versioned plans and atomic immutable confirmation in the existing SQLite store."""
import copy
import json
from decimal import Decimal, localcontext
from datetime import datetime, timezone
from uuid import uuid4

from backend.app.storage.repository import dump, now
from backend.app.risk.plan import evaluate
from .schema import EDITABLE, PlanError, content_hash as plan_hash, validate
from .sources import fresh, latest_attempt, not_expired, quote_value, same_instrument, specification, validate_rules


class Plans:
    def __init__(self, store, test_doubles=False, clock=None):
        self.store, self.test_doubles = store, test_doubles
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _load(self, db, plan_id):
        row = db.execute('SELECT document FROM plans WHERE id=?', (plan_id,)).fetchone()
        if not row: raise PlanError(404, 'План не найден')
        return json.loads(row[0])

    async def get(self, plan_id):
        with self.store.connect() as db: return self._load(db, plan_id)

    def _evidence(self, db, sid):
        return [json.loads(r[0]) for r in db.execute('SELECT payload FROM evidence WHERE session_id=? ORDER BY rowid', (sid,))]

    def _prepare(self, db, plan, user_source):
        """Only the backend can attach market provenance and calculated values."""
        evidence = self._evidence(db, plan['session_id'])
        instrument = plan.get('instrument')
        sources = [user_source]
        spec = None
        if instrument:
            known = [i for e in evidence if e.get('kind') == 'search' and e.get('status') == 'ok'
                     for i in (e.get('result') or {}).get('instruments', [])]
            if not any(same_instrument(i, instrument) for i in known):
                raise PlanError(422, 'Инструмент должен быть однозначно найден в источниках этого диалога')
            spec_id = instrument.get('spec_source_id')
            candidates = [e for e in evidence if specification(e, instrument)]
            chosen = next((e for e in candidates if e['id'] == spec_id), None) if spec_id else (candidates[-1] if candidates else None)
            if spec_id and not chosen: raise PlanError(422, 'Спецификация не принадлежит выбранному инструменту и диалогу')
            spec = specification(chosen, instrument)
            if chosen:
                instrument['spec_source_id'] = chosen['id']
                params = plan.setdefault('parameters', {})
                if spec.get('lot_size'): params.setdefault('lot_size', int(spec['lot_size']))
                if spec.get('point_value'):
                    params.setdefault('point_value', spec['point_value'])
                    params.setdefault('point_value_currency', spec['currency'].upper())
                sources.append(self._source(chosen, instrument, 86400))
            quote = latest_attempt(evidence, instrument, 'quote')
            max_age = min((r.get('max_age_seconds', 300) for r in plan.get('rules', []) if r['automatic']), default=300)
            if quote_value(quote, instrument): sources.append(self._source(quote, instrument, max_age))
        plan['sources'] = sources
        plan['risk'] = evaluate(plan, spec)
        self._missing(plan)
        validate(plan)
        return plan

    @staticmethod
    def _missing(plan):
        labels = {'instrument': 'Конкретный инструмент', 'direction': 'Направление', 'hypothesis': 'Гипотеза',
                  'horizon': 'Горизонт', 'entry_conditions': 'Условия входа', 'exit_conditions': 'Условия выхода',
                  'review_conditions': 'Условия пересмотра', 'rules': 'Правила мониторинга'}
        plan['missing'] = [label for key, label in labels.items() if not plan.get(key) or
                           isinstance(plan[key], str) and not plan[key].strip()]

    def _source(self, evidence, instrument, max_age):
        quote = quote_value(evidence, instrument)
        observed = quote['observed_at'] if quote else evidence.get('observed_at')
        return {'id': evidence['id'], 'kind': 'mcp',
                'locator': f"tinvest-sandbox:{instrument['id']}:{evidence['kind']}",
                'retrieved_at': evidence.get('requested_at') or evidence['observed_at'], 'observed_at': observed,
                'freshness': 'available' if fresh(observed, self.clock(), max_age) else 'stale',
                'synthetic': bool(evidence.get('synthetic', self.test_doubles))}

    async def for_session(self, sid):
        state = self.store.state(sid)
        if not state: raise PlanError(404, 'Диалог не найден')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT document FROM plans WHERE session_id=?', (sid,)).fetchone()
            if row: return json.loads(row[0])
            plan = {'id': str(uuid4()), 'session_id': sid, 'version': 1, 'status': 'draft',
                    'educational': self.test_doubles or any((m['response'] or {}).get('educational') for m in state['messages'] if m['role'] == 'user'),
                    'missing': []}
            latest = next((m for m in reversed(state['messages']) if m['role'] == 'assistant' and
                           ((m['response'] or {}).get('risk_inputs') or (m['response'] or {}).get('plan'))), None)
            user = next((m for m in reversed(state['messages']) if m['role'] == 'user'), None)
            stamp = user['created_at'] if user else state['session']['created_at']
            source = {'id': f"message-{user['id']}" if user else 'session-' + sid, 'kind': 'user',
                      'locator': 'session:' + sid, 'retrieved_at': stamp, 'observed_at': stamp,
                      'freshness': 'available', 'synthetic': self.test_doubles}
            if latest:
                response = latest['response']; summary = response.get('plan') or {}
                for key in ('hypothesis', 'basis', 'counterarguments', 'horizon'):
                    if summary.get(key): plan[key] = summary[key]
                for key, old in [('entry_conditions', 'confirmation'), ('review_conditions', 'invalidation')]:
                    if summary.get(old): plan[key] = summary[old]
                if summary.get('exit'): plan['exit_conditions'] = [summary['exit']]
                inputs = response.get('risk_inputs')
                if inputs and response.get('risk_calculation', {}).get('status') != 'invalid_inputs':
                    evidence = self._evidence(db, sid)
                    known = [i for e in evidence if e.get('kind') == 'search' and e.get('status') == 'ok'
                             for i in (e.get('result') or {}).get('instruments', [])]
                    chosen = next((i for i in known if i['id'] == inputs['instrument_id']), None)
                    if chosen:
                        plan['instrument'] = {k: chosen[k] for k in ('id', 'ticker', 'class_code', 'kind')}
                        if chosen.get('name'): plan['instrument']['name'] = chosen['name']
                    if inputs['direction'] in ('long', 'short'): plan['direction'] = inputs['direction']
                    params = {k: v['value'] for k, v in inputs.items() if isinstance(v, dict) and
                              k in ('entry', 'stop', 'target', 'quantity', 'capital', 'capital_currency', 'costs_per_unit')}
                    if inputs.get('price_currency'): params['price_unit'] = inputs['price_currency']['value']
                    plan['parameters'] = params
                    if inputs.get('risk_percent'): plan['risk'] = {'limit': {'kind': 'percent', 'value': inputs['risk_percent']['value']}}
            self._prepare(db, plan, source)
            if plan.get('parameters', {}).get('stop') and plan.get('direction') and plan.get('instrument', {}).get('spec_source_id'):
                plan['rules'] = [{'id': 'stop-price', 'metric': 'price', 'operator': 'lte' if plan['direction'] == 'long' else 'gte',
                                  'threshold': plan['parameters']['stop'], 'unit': plan['parameters'].get('price_unit', ''),
                                  'automatic': True, 'max_age_seconds': 300, 'source_ids': [plan['instrument']['spec_source_id']]}]
            self._missing(plan)
            validate(plan)
            db.execute('INSERT INTO plans VALUES(?,?,?)', (plan['id'], sid, dump(plan)))
            return plan

    async def update_draft(self, plan_id, expected_version, changes):
        if not changes or set(changes) - EDITABLE: raise PlanError(422, 'Недопустимые поля изменения плана')
        if set(changes) & {'session_id', 'sources', 'missing'}:
            raise PlanError(422, 'Диалог, источники и пробелы назначаются сервером')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = self._load(db, plan_id)
            if current['version'] != expected_version: raise PlanError(409, 'Версия изменилась. Обновите план и проверьте правки')
            plan = copy.deepcopy(current)
            plan.pop('confirmation', None); plan.update(status='draft', version=expected_version + 1)
            for key, value in changes.items():
                if key == 'risk': plan[key] = {'status': 'not_calculated', 'limit': value.get('limit', {})} if isinstance(value, dict) else value
                else: plan[key] = copy.deepcopy(value)
            # Check the entire input before accessing nested objects or doing arithmetic.
            validate(plan)
            if not plan['educational']:
                state = self.store.state(plan['session_id'])
                if self.test_doubles or any((m['response'] or {}).get('educational') for m in state['messages'] if m['role'] == 'user'):
                    raise PlanError(422, 'Учебный диалог нельзя превращать в неучебный план')
            source = {'id': 'edit-' + str(uuid4()), 'kind': 'user', 'locator': 'plan-form:' + plan_id,
                      'retrieved_at': now(), 'observed_at': now(), 'freshness': 'available', 'synthetic': self.test_doubles}
            # Risk.status is server-owned; the draft schema requires it even before calculation.
            self._prepare(db, plan, source)
            db.execute('UPDATE plans SET document=? WHERE id=?', (dump(plan), plan_id))
            return plan

    async def confirm(self, plan_id, expected_version, content_hash, request_id):
        supplied_hash = content_hash
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM confirmations WHERE request_id=?', (request_id,)).fetchone()
            if previous:
                if (previous['plan_id'], previous['version'], previous['content_hash']) != (plan_id, expected_version, supplied_hash):
                    raise PlanError(409, 'Идентификатор подтверждения уже использован с другими параметрами')
                return json.loads(previous['response'])
            plan = self._load(db, plan_id)
            if plan['version'] != expected_version or plan['status'] != 'draft' or plan_hash(plan) != supplied_hash:
                raise PlanError(409, 'Версия или хеш не совпадают. Обновите план перед подтверждением')
            evidence = {e['id']: e for e in self._evidence(db, plan['session_id'])}
            instrument = plan.get('instrument', {})
            spec_e = evidence.get(instrument.get('spec_source_id'))
            spec = specification(spec_e, instrument)
            if not spec: raise PlanError(422, 'Нужна проверенная спецификация выбранного инструмента')
            latest_spec_e = latest_attempt(list(evidence.values()), instrument, 'spec')
            latest_spec = specification(latest_spec_e, instrument)
            if not latest_spec or any(spec.get(k) != latest_spec.get(k) for k in ('lot_size', 'point_value', 'currency', 'tick_size', 'expiration_date', 'last_trade_date')):
                raise PlanError(422, 'Последняя проверка спецификации не удалась или параметры изменились. Обновите данные и пересохраните черновик')
            current = self.clock()
            if instrument['kind'] == 'future' and not not_expired(spec, current):
                raise PlanError(422, 'Неизвестна экспирация или контракт уже завершил торги')
            calculated = evaluate(plan, spec)
            if calculated['status'] != 'calculated' or calculated != plan.get('risk'):
                raise PlanError(422, 'Риск не прошёл серверную проверку: ' + '; '.join(calculated.get('missing', [])))
            validate_rules(plan)
            if spec.get('tick_size'):
                with localcontext() as ctx:
                    ctx.prec = 100
                    if any(Decimal(r['threshold']) % Decimal(spec['tick_size']) != 0 for r in plan.get('rules', []) if r['automatic']):
                        raise PlanError(422, 'Порог правила должен быть кратен шагу цены')
            if not plan.get('horizon', '').strip(): raise PlanError(422, 'Укажите горизонт плана')
            if any(not v.strip() for key in ('entry_conditions', 'exit_conditions', 'review_conditions') for v in plan.get(key, [])):
                raise PlanError(422, 'Условия не могут быть пустыми')
            for rule in plan.get('rules', []):
                if not all(sid in evidence and specification(evidence[sid], instrument) or
                           sid in evidence and quote_value(evidence[sid], instrument) for sid in rule['source_ids']):
                    raise PlanError(422, 'Правило ссылается на неподходящий источник')
            if not plan['educational']:
                current_quote_e = latest_attempt(list(evidence.values()), instrument, 'quote')
                if not quote_value(current_quote_e, instrument) or latest_spec_e.get('synthetic') or current_quote_e.get('synthetic'):
                    raise PlanError(422, 'Последняя проверка рыночных данных не подтверждена неучебным источником')
                quotes = [quote_value(evidence.get(s['id']), instrument) for s in plan['sources'] if s['id'] in evidence]
                ages = [r['max_age_seconds'] for r in plan.get('rules', []) if r['automatic']]
                age = min(ages or [300])
                current_quote = quote_value(current_quote_e, instrument)
                if (not fresh(spec_e.get('observed_at'), current, 86400) or not fresh(latest_spec_e.get('observed_at'), current, 86400)
                        or not fresh(current_quote['observed_at'], current, age) or current_quote['unit'] != plan['parameters']['price_unit']
                        or not any(q and q['unit'] == plan['parameters']['price_unit'] and fresh(q['observed_at'], current, age) for q in quotes)):
                    raise PlanError(422, 'Для неучебного подтверждения нужны свежие спецификация и котировка')
                if any(s['synthetic'] or s['freshness'] != 'available' for s in plan['sources']):
                    raise PlanError(422, 'Учебные, устаревшие или неизвестные источники нельзя использовать в неучебном плане')
            snapshot = copy.deepcopy(plan)
            snapshot.update(status='confirmed', confirmation={'version': expected_version, 'content_hash': supplied_hash,
                            'confirmed_at': current.isoformat(), 'request_id': request_id})
            validate(snapshot)
            payload = dump(snapshot)
            db.execute('INSERT INTO plan_snapshots VALUES(?,?,?)', (plan_id, expected_version, payload))
            db.execute('INSERT INTO confirmations VALUES(?,?,?,?,?)', (request_id, plan_id, expected_version, supplied_hash, payload))
            db.execute('UPDATE plans SET document=? WHERE id=?', (payload, plan_id))
            db.execute('INSERT INTO monitoring VALUES(?,?,?,NULL,?,NULL,NULL) ON CONFLICT(plan_id) DO UPDATE SET confirmed_version=excluded.confirmed_version,state=excluded.state,last_checked_at=NULL,next_check_at=excluded.next_check_at,lease_owner=NULL,lease_until=NULL',
                       (plan_id, expected_version, 'active', current.isoformat()))
            return snapshot
