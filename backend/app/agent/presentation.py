"""Bounded prose and source-owned market facts. Risk arithmetic belongs to Python."""
import re
from datetime import datetime

from backend.app.integrations.tools import specifications
from backend.app.integrations.values import decimal_value

MAX_REPLY=700
MAX_QUESTION=140
MAX_SHOWN=1000
ARITHMETIC=re.compile(r'[%=≈×]|процент|вдвое|втрое|удво|утро|разниц\w* (?:цен|состав)|умнож|раздели|прибав|вычесть',re.I)
NUMBER_WORDS=re.compile(r'\b(?:ноль|нуль|один|одна|одно|два|две|двух|три|трех|трёх|четыре|пять|шесть|семь|восемь|девять|десять|двадцать|тридцать|сорок|сто|тысяч\w*|миллион\w*|половин\w*|треть|четверть)\b',re.I)


def source_time(value):
    if not isinstance(value,str) or len(value)>40:return 'не указано'
    try:datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:return 'не указано'
    return value


def qualitative(text,limit,tickers=()):
    """No model-authored numbers/computations in prose; data is shown separately."""
    clean=[]
    for part in re.split(r'(?<=[.!?])\s+|\n+',text.strip()):
        inspected=part
        for ticker in tickers:inspected=re.sub(r'(?<!\w)'+re.escape(ticker)+r'(?!\w)','',inspected,flags=re.I)
        if re.search(r'\d',inspected) or ARITHMETIC.search(inspected) or NUMBER_WORDS.search(inspected):continue
        part=re.sub(r'^\s*[-*#]+\s*','',part).strip()
        if part and len(' '.join(clean+[part]))<=limit:clean.append(part)
        if len(clean)==4:break
    return ' '.join(clean)


def market_facts(evidence):
    facts=[]
    for e in evidence:
        if e['status']!='ok' or e['kind'] not in ('spec','quote'):continue
        result=e['result'];instrument=result.get('instrument',{});ticker=instrument.get('ticker','')
        if e['kind']=='spec':
            spec=specifications([e],instrument.get('id'))
            if spec and spec.get('point_value'):
                facts.append({'statement':f"{ticker}: шаг цены {spec['tick_size']} пунктов, стоимость шага {spec['tick_value']} {spec['currency'].upper()}, лот {spec['lot_size'] or 'не указан'}. Экспирация: {source_time(spec.get('expiration_date'))}. Последний день торгов: {source_time(spec.get('last_trade_date'))}.",'evidence_id':e['id']})
        else:
            for item in result.get('data',{}).get('instruments',[]):
                for value in item.get('values',[]):
                    if value.get('type')=='INSTRUMENT_VALUE_LAST_PRICE' and isinstance(value.get('value'),dict):
                        price=decimal_value(value['value'])
                        if price is not None:
                            unit=item.get('priceCurrency')
                            unit=unit if unit in ('pt.','points','rub','usd','eur') else 'единица неизвестна'
                            facts.append({'statement':f"{ticker}: последняя доступная котировка {price} {unit}; время источника {source_time(value.get('time'))}. Это не подтверждение текущей цены исполнения.",'evidence_id':e['id']})
    return facts[-6:]


def present(reply,calc,evidence,known,education=False,risk_requested=False,selected_id=None):
    response=reply.model_dump()
    tickers=[i['ticker'] for i in known.values() if i.get('ticker')]
    audit={'raw_reply_characters':len(reply.reply),'risk_summary_owned_by':'python' if reply.risk_inputs or risk_requested else None}
    questions=[qualitative(q,MAX_QUESTION,tickers) for q in reply.questions]
    response['questions']=[q for q in questions if q][:2]
    if reply.risk_inputs or risk_requested:
        target_id=reply.risk_inputs.instrument_id if reply.risk_inputs else selected_id
        spec=specifications(evidence,target_id)
        spec_ok=bool(spec and spec.get('point_value'))
        priced_ids={f['evidence_id'] for f in market_facts(evidence)}
        quotes=[e for e in evidence if e['kind']=='quote'
                and (e.get('result') or {}).get('instrument',{}).get('id')==target_id]
        quote_ok=bool(quotes and quotes[-1]['id'] in priced_ids)
        if calc['status']=='calculated':
            text='Условный риск рассчитан программно; значения и ограничения — в карточке риска.'
            if calc['values'].get('over_budget'):text+=' Указанная позиция превышает заданный лимит.'
        elif calc['status']=='invalid_inputs':
            text='Параметры не прошли проверку. Исправьте числа, единицы или направление стопа; подробности — в карточке риска.'
        else:text='Для полного расчёта пока не хватает проверенных параметров. Недостающие данные перечислены в карточке риска.'
        if spec_ok and quote_ok:text+=' Спецификация и последняя доступная котировка получены; время данных указано в источниках.'
        elif not spec_ok:text+=' Спецификация для расчёта не подтверждена полностью.'
        elif not quote_ok:text+=' Последняя котировка не подтверждена; рыночная цена остаётся неизвестной.'
        response['reply']=text
    else:
        response['reply']=qualitative(reply.reply,MAX_REPLY,tickers) or 'Проверяемого краткого вывода пока нет. Уточните вопрос или недостающие основания.'
    if education:
        response.update(plan=None,risk_inputs=None,facts=[],tool_requests=[])
    else:
        response['facts']=market_facts(evidence)
        plan=response.get('plan')
        if plan:
            for field in ('hypothesis','horizon','entry','exit'):
                value=plan.get(field)
                if value:plan[field]=qualitative(value,300,tickers) or ('Гипотеза требует уточнения.' if field=='hypothesis' else None)
            for field in ('basis','counterarguments','confirmation','invalidation','missing'):
                plan[field]=[s for t in plan[field] if (s:=qualitative(t,180,tickers))][:3]
            plan['risk_notes']=calc.get('notes',[])[:5]
            selected=known.get(reply.risk_inputs.instrument_id) if reply.risk_inputs else None
            plan['instrument']=f"{selected['ticker']} ({selected['class_code']})" if selected else None
            if reply.risk_inputs:plan['direction']=reply.risk_inputs.direction
            if reply.risk_inputs and calc['status']!='invalid_inputs':
                risk=reply.risk_inputs
                plan['entry']=f'{risk.entry.value} {risk.price_currency.value}' if risk.entry and risk.price_currency else None
    response['tool_requests']=[]
    audit.update(shown_reply_characters=len(response['reply']),
                 model_prose_replaced=response['reply']!=reply.reply)
    return response,audit
