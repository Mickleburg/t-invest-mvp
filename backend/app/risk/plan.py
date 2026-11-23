"""Adapter for explicit HTTP form values; all financial arithmetic uses Decimal."""
from decimal import Decimal, InvalidOperation, localcontext

from backend.app.agent.models import RiskInputs
from backend.app.risk.engine import calculate

ENGINE_VERSION = 'decimal-plan-v1'


def evaluate(plan, spec):
    params = plan.get('parameters', {})
    limit = plan.get('risk', {}).get('limit', {})
    missing = []
    result = {'status': 'insufficient_data', 'limit': limit, 'missing': missing,
              'engine_version': ENGINE_VERSION, 'assumptions': []}
    try:
        for key in ('entry', 'stop', 'target', 'quantity', 'capital', 'point_value', 'costs_per_unit'):
            if key in params and len(params[key]) > 40: raise ValueError()
        if len(limit.get('value', '')) > 40: raise ValueError()
        instrument = plan.get('instrument', {})
        kind = instrument.get('kind', 'unknown')
        if kind == 'unknown' or not spec or not spec.get('lot_size'):
            missing.append('Нужна проверенная спецификация выбранного инструмента')
            return result
        currency = params.get('capital_currency', '').lower()
        unit = params.get('price_unit', '').lower()
        if currency not in ('rub', 'usd', 'eur'): missing.append('Укажите валюту капитала RUB, USD или EUR')
        if params.get('lot_size') != int(spec['lot_size']): missing.append('Лот должен совпадать со спецификацией')
        if kind == 'future':
            if not spec.get('point_value'): missing.append('Неизвестна стоимость пункта')
            elif (Decimal(params.get('point_value', '0')) != Decimal(spec['point_value']) or
                  params.get('point_value_currency', '').lower() != spec['currency']):
                missing.append('Стоимость пункта и валюта должны совпадать со спецификацией')
            if unit != 'points': missing.append('Цена фьючерса задаётся в points')
        elif unit != currency or spec.get('currency') != currency:
            missing.append('Валюты цены, капитала и спецификации должны совпадать')
        if not limit.get('kind') or Decimal(limit.get('value', '0')) <= 0: missing.append('Укажите положительный лимит риска')
        if limit.get('kind') == 'money' and limit.get('currency', '').lower() != currency:
            missing.append('Валюта денежного лимита должна совпадать с валютой капитала')
        for key in ('entry', 'stop', 'quantity', 'capital'):
            if key not in params: missing.append('Не задан параметр: ' + key)
        if missing: return result
        # These are explicit form fields, not alleged quotations from a conversation.
        values = {key: None for key in RiskInputs.model_fields}
        values.update(instrument_kind=kind, instrument_id=instrument['id'], direction=plan.get('direction', 'unknown'))
        texts = []
        for key in ('entry', 'stop', 'target', 'quantity', 'capital', 'costs_per_unit'):
            if key in params:
                quote = f'{key}: {params[key]}'
                texts.append(quote); values[key] = {'value': params[key], 'quote': quote}
        for key, value in [('capital_currency', currency), ('price_currency', unit)]:
            quote = f"{key}: {'пунктов' if value == 'points' else value}"
            texts.append(quote); values[key] = {'value': value, 'quote': quote}
        if limit['kind'] == 'percent':
            quote = f"risk_percent: {limit['value']}%"
            texts.append(quote); values['risk_percent'] = {'value': limit['value'], 'quote': quote}
        with localcontext() as ctx:
            ctx.prec = 100
            calc = calculate(RiskInputs.model_validate(values), texts, spec)
            result.update(assumptions=calc['notes'], missing=calc['missing'])
            if calc['status'] != 'calculated': return result
            v = calc['values']
            budget = (Decimal(params['capital']) * Decimal(limit['value']) / 100
                      if limit['kind'] == 'percent' else Decimal(limit['value']))
            if budget > Decimal(params['capital']): result['missing'].append('Лимит превышает капитал')
            if Decimal(v['position_loss']) > budget: result['missing'].append('Убыток у стопа превышает лимит')
            result['calculation'] = {'loss_at_stop': v['position_loss'], 'risk_percent': v['position_risk_percent'],
                                     'currency': currency.upper(), 'quantity': params['quantity'],
                                     'spec_source_ids': [spec['evidence_id']]}
            if 'reward_risk_ratio' in v: result['calculation']['reward_risk'] = v['reward_risk_ratio']
            result['status'] = 'calculated' if not result['missing'] else 'invalid'
        return result
    except (ValueError, InvalidOperation, KeyError, ArithmeticError):
        result.update(status='invalid', missing=['Проверьте числа, единицы и параметры риска'])
        return result
