"""Arithmetic only: conditional loss at a supplied exit, not maximum real loss."""
from decimal import Decimal,ROUND_FLOOR,InvalidOperation
from backend.app.risk.grounding import explicit_amounts,explicit_unit
from backend.app.agent.models import RiskInputs


def calculate(inputs:RiskInputs|None,user_messages:list[str],spec=None):
    if inputs is None:return {'status':'insufficient_data','missing':['Параметры расчёта ещё не заданы'],'values':{},'notes':[]}
    notes=['Расчёт предполагает исполнение по заданному уровню выхода. Гэп и проскальзывание могут увеличить фактический убыток.']
    texts='\n'.join(user_messages); fields={}
    try:
        for name,field in inputs.model_dump().items():
            if not isinstance(field,dict):continue
            quote=field['quote']
            if quote not in texts:raise ValueError('Цитата параметра отсутствует в сообщениях пользователя')
            if name.endswith('currency'):
                unit={'points':'pt'}.get(field['value'],field['value'])
                if not explicit_unit(quote,unit):raise ValueError('Валюта параметра не подтверждена цитатой')
                continue
            n=Decimal(field['value'])
            if not n.is_finite() or n<0 or n not in explicit_amounts(quote):raise ValueError('Число не подтверждено цитатой или некорректно')
            fields[name]=n
    except (ValueError,InvalidOperation):
        return {'status':'invalid_inputs','missing':['Проверьте распознанные числа, валюты и исходные цитаты'],'values':{},'notes':[]}
    def currency(name):return getattr(inputs,name).value if getattr(inputs,name) else None
    missing=[]; values={}; capital=fields.get('capital');percent=fields.get('risk_percent')
    account=currency('capital_currency'); price_currency=currency('price_currency')
    if capital is not None and capital<=0:missing.append('Капитал должен быть больше нуля')
    if percent is not None and not 0<percent<=100:missing.append('Лимит риска должен быть больше 0 и не больше 100%')
    if capital and percent is not None and 0<percent<=100:values['risk_budget']=str(capital*percent/100)
    if inputs.direction=='unknown':missing.append('Направление позиции')
    if inputs.instrument_kind=='unknown':missing.append('Тип инструмента')
    for key,label in [('entry','Цена входа'),('stop','Уровень выхода при опровержении')]:
        if key not in fields:missing.append(label)
    if not account:missing.append('Валюта капитала/расчёта')
    multiplier=Decimal(1);lot=fields.get('lot_size');spec_source=None
    if inputs.instrument_kind=='share':
        if not price_currency or price_currency!=account:missing.append('Совпадающие валюты цены и капитала; FX-пересчёт не реализован')
        if spec and spec.get('lot_size') is not None:
            if lot is not None and lot!=Decimal(spec['lot_size']):missing.append('Пользовательский лот расходится со спецификацией MCP')
            lot=Decimal(spec['lot_size']);spec_source=spec.get('evidence_id')
    elif inputs.instrument_kind=='future':
        pv=fields.get('point_value');pvc=currency('point_value_currency')
        if spec and spec.get('point_value'):
            supplied=Decimal(spec['point_value'])
            if pv is not None and pv!=supplied:missing.append('Стоимость пункта пользователя расходится со спецификацией MCP')
            pv=supplied;pvc=spec.get('currency');spec_source=spec.get('evidence_id');lot=Decimal(spec.get('lot_size') or '1')
        else:notes.append('Спецификация фьючерса не подтверждена MCP. Возможный расчёт основан только на допущениях пользователя.')
        if pv is None or pv<=0:missing.append('Стоимость пункта конкретного контракта')
        elif pvc!=account:missing.append('Стоимость пункта в валюте капитала; FX-пересчёт не реализован')
        else:multiplier=pv
        if lot is None:lot=Decimal(1);notes.append('Считаются целые контракты; биржевая кратность лоту не проверена')
    if missing:return {'status':'insufficient_data','missing':missing,'values':values,'notes':notes}
    entry,stop=fields['entry'],fields['stop']
    if entry<=0 or stop<0 or (inputs.direction=='long' and stop>=entry) or (inputs.direction=='short' and stop<=entry):
        return {'status':'invalid_inputs','missing':['Стоп должен быть ниже входа для long и выше для short; вход положителен'],'values':{},'notes':notes}
    cost=fields.get('costs_per_unit',Decimal(0))
    if 'costs_per_unit' not in fields:notes.append('Комиссии и прочие издержки не включены: пользователь не задал их величину')
    per_unit=abs(entry-stop)*multiplier+cost
    values['loss_per_unit']=str(per_unit);values['currency']=account
    if lot is not None and (lot<=0 or lot!=lot.to_integral_value()):
        return {'status':'invalid_inputs','missing':['Лот должен быть положительным целым числом'],'values':{},'notes':notes}
    budget=Decimal(values['risk_budget']) if 'risk_budget' in values else None
    if budget is not None:
        if lot is None:missing.append('Размер лота для расчёта позиции')
        else:
            lots=(budget/(per_unit*lot)).to_integral_value(rounding=ROUND_FLOOR)
            values.update(max_lots=str(lots),max_quantity=str(lots*lot),loss_at_max_quantity=str(lots*lot*per_unit))
            notes.append('Количество ограничено только риском у стопа; доступные средства, другие позиции и допустимое плечо не проверены')
            if lots==0:notes.append('При заданном лимите не помещается даже один лот')
    qty=fields.get('quantity')
    if qty is not None:
        if qty<=0 or qty!=qty.to_integral_value() or (lot and qty%lot!=0):
            return {'status':'invalid_inputs','missing':['Количество должно быть положительным целым и кратным известному лоту'],'values':{},'notes':notes}
        values['position_loss']=str(qty*per_unit)
        if inputs.instrument_kind=='share':
            values['position_notional']=str(qty*entry)
            if capital and qty*entry>capital:notes.append('Стоимость указанной позиции превышает капитал; финансирование покупки без плеча не обеспечено этими параметрами')
        if capital:values['position_risk_percent']=str(qty*per_unit/capital*100)
        if budget is not None:values['over_budget']=qty*per_unit>budget
    elif 'max_quantity' not in values:missing.append('Количество позиции либо капитал и допустимый процент риска')
    if capital is None:missing.append('Капитал для оценки доли риска')
    target=fields.get('target')
    if target is not None:
        gross=(target-entry if inputs.direction=='long' else entry-target)*multiplier
        if gross<=cost:missing.append('Цель должна давать положительный результат после заданных издержек')
        else:
            values['reward_risk_ratio']=str((gross-cost)/per_unit)
            if qty is not None:values['potential_profit']=str(qty*(gross-cost))
    if spec_source:values['spec_evidence_id']=spec_source
    if inputs.instrument_kind=='future':notes.append('Не рассчитаны ГО, доступность средств, маржин-колл, экспирация и изменение стоимости пункта. Это условная оценка, не гарантия максимального убытка.')
    return {'status':'calculated' if not missing else 'partial','missing':missing,'values':values,'notes':notes,
            'formula':'Убыток на единицу = |вход − выход| × стоимость единицы движения + заданные издержки; позиция = floor(лимит / убыток на лот) × лот.'}
