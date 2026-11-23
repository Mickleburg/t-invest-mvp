"""Identity, timestamp and provenance checks shared by confirmation and worker."""
from datetime import datetime, timezone
from decimal import Decimal

from backend.app.integrations.tools import specifications
from backend.app.integrations.values import decimal_value
from .schema import PlanError


def instant(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError, AttributeError): return None


def fresh(value, current, seconds):
    observed = instant(value)
    return observed is not None and -5 <= (current - observed).total_seconds() <= seconds


def same_instrument(actual, expected):
    return all(actual.get(k) == expected.get(k) for k in ('id', 'ticker', 'class_code', 'kind'))


def latest_attempt(evidence, instrument, kind):
    """A recent failed refresh must not be hidden by an earlier successful read."""
    for e in reversed(evidence):
        if e.get('kind') != kind: continue
        identity = e.get('instrument_id') or (e.get('result') or {}).get('instrument', {}).get('id')
        if identity:
            if identity == instrument['id']: return e
            continue
        key = f"{instrument['ticker']}_{instrument['class_code']}"
        for call in e.get('calls', []):
            value = call.get('arguments', {}).get('instrumentId')
            if value in (instrument['id'], key) or isinstance(value, list) and key in value: return e
        if e.get('status') != 'ok' and not e.get('calls'): return e
    return None


def specification(evidence, instrument):
    if not evidence or evidence.get('kind') != 'spec' or evidence.get('status') != 'ok': return None
    result = evidence.get('result') or {}
    if not same_instrument(result.get('instrument', {}), instrument): return None
    card = result.get('data', {}).get('instrument', {})
    for name, key in [('uid', 'id'), ('ticker', 'ticker'), ('classCode', 'class_code')]:
        if card.get(name) is not None and card[name] != instrument[key]: return None
    spec = specifications([evidence], instrument['id'])
    if spec and instrument['kind'] == 'share': spec['currency'] = card.get('currency', '').lower()
    return spec


def quote_value(evidence, instrument):
    if not evidence or evidence.get('kind') != 'quote' or evidence.get('status') != 'ok': return None
    result = evidence.get('result') or {}
    if not same_instrument(result.get('instrument', {}), instrument): return None
    matches = []
    for row in result.get('data', {}).get('instruments', []):
        if row.get('ticker') != instrument['ticker'] or row.get('classCode') != instrument['class_code']: return None
        unit = row.get('priceCurrency', '').lower()
        unit = 'points' if unit in ('pt.', 'points') else unit
        for item in row.get('values', []):
            if item.get('type') != 'INSTRUMENT_VALUE_LAST_PRICE': continue
            value = decimal_value(item.get('value'))
            if value is not None and value.is_finite() and value > 0:
                matches.append({'value': value, 'unit': unit, 'observed_at': item.get('time')})
    return matches[0] if len(matches) == 1 else None


def not_expired(spec, current):
    # Expiry is a date; last-trade is an instant. Missing expiry is uncertainty.
    expiry = (spec or {}).get('expiration_date')
    if not expiry: return False
    try:
        if datetime.fromisoformat(expiry.replace('Z', '+00:00')).date() <= current.date(): return False
    except (ValueError, TypeError): return False
    last = instant(spec.get('last_trade_date'))
    return not last or last > current


def validate_rules(plan):
    seen = set(); source_ids = {s['id'] for s in plan.get('sources', [])}
    for rule in plan.get('rules', []):
        if not rule['id'].strip() or len(rule['id']) > 160 or rule['id'] in seen: raise PlanError(422, 'Идентификаторы правил должны быть уникальны и не длиннее 160 символов')
        seen.add(rule['id'])
        if not rule['source_ids'] or not set(rule['source_ids']) <= source_ids:
            raise PlanError(422, 'У правила нет проверенного источника выбранного инструмента')
        if rule['automatic']:
            if rule['unit'] != plan.get('parameters', {}).get('price_unit'):
                raise PlanError(422, 'Единица правила не совпадает с единицей цены')
            if not 1 <= rule['max_age_seconds'] <= 3600 or len(rule['threshold']) > 40 or Decimal(rule['threshold']) <= 0:
                raise PlanError(422, 'Проверьте порог и допустимый возраст котировки (до 3600 секунд)')
        elif rule['metric'] != 'manual_event' or rule['operator'] != 'manual':
            raise PlanError(422, 'Ручное событие нельзя объявлять автоматической проверкой')
