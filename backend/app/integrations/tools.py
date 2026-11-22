"""Small read-only tool dispatcher; no arbitrary tool names or execution."""
import asyncio
from datetime import datetime,timedelta,timezone
from uuid import uuid4
from backend.app.integrations.tinvest import sandbox_session,ENDPOINT,SandboxError
from backend.app.integrations.market import query_term,rank_instruments,instrument_key
from backend.app.integrations.values import decimal_value
from backend.app.integrations.research_client import research_via_mcp


def now():return datetime.now(timezone.utc).isoformat()


def candidates(rows,query):
    # The shared all-asset ranker caps at 40 and puts shares before futures.
    # Rank each supported type first so BR's many share matches cannot hide oil contracts.
    groups=[rank_instruments(rows,query,kind)[:8] for kind in ('share','future')]
    by_id={r.get('uid'):r for r in rows}
    out=[]
    for i in range(8):
        for group in groups:
            if i>=len(group):continue
            item={k:v for k,v in group[i].items() if k!='alternatives'}
            original=by_id[item['id']]
            item['expiration_date']=original.get('expirationDate') or original.get('lastTradeDate')
            out.append(item)
    return sorted(out,key=lambda item:not item['exact_match'])[:8]


async def execute(request,known):
    evidence={'id':str(uuid4()),'kind':request.kind,'requested_at':now(),'status':'error','calls':[],'result':None}
    async def bank(name,args):
        call={'name':name,'arguments':args,'started_at':now(),'endpoint':ENDPOINT,'status':'started'}
        evidence['calls'].append(call)
        try:
            async with asyncio.timeout(24):
                async with sandbox_session() as remote:result=await remote.call(name,args)
            call.update(status='ok',finished_at=now(),response=result)
            return result
        except Exception as exc:
            call.update(status='error',finished_at=now(),error_type=type(exc).__name__,
                        error=str(exc) if isinstance(exc,SandboxError) else 'MCP read failed or timed out')
            raise
    try:
        if request.kind=='search':
            if not request.query:raise ValueError('missing_query')
            query=query_term(request.query)
            raw=await bank('invest_find_instrument',{'query':query,'responseView':['FULL']})
            rows=candidates(raw.get('instruments',[]),query)
            evidence['result']={'instruments':rows,'note':'Кандидаты, не выбор контракта за пользователя и не подтверждение доступности торговли. Проверьте экспирацию и спецификацию.'}
        elif request.kind=='web':
            if not request.question:raise ValueError('missing_question')
            selected=known.get(request.instrument_id) if request.instrument_id else None
            if request.instrument_id and not selected:raise ValueError('unknown_instrument')
            evidence['calls'].append({'name':'research_sources','arguments':{'instrument_id':request.instrument_id,'question':request.question},
                                      'started_at':now(),'status':'started','transport':'local_mcp_chromium'})
            async with asyncio.timeout(120):
                raw=await research_via_mcp(selected or {'id':'external-event','ticker':'','name':'Внешнее событие','isin':''},request.question,'instrument' if selected else 'event')
            evidence['result']=raw;evidence['calls'][-1].update(status='ok',finished_at=now())
        else:
            selected=known.get(request.instrument_id)
            if not selected:raise ValueError('unknown_instrument')
            current=datetime.now(timezone.utc);key=instrument_key(selected)
            if request.kind=='quote':
                raw=await bank('invest_get_market_values',{'instrumentId':[key],'values':['INSTRUMENT_VALUE_LAST_PRICE']})
            elif request.kind=='history':
                raw=await bank('invest_get_candles',{'instrumentId':key,'interval':'CANDLE_INTERVAL_DAY',
                               'from':(current-timedelta(days=30)).isoformat(),'to':current.isoformat(),'limit':35})
            elif request.kind=='news':
                raw=await bank('invest_get_news',{'instrumentId':selected['ticker'],'limit':5})
            elif request.kind=='spec':
                name={'share':'invest_get_share','future':'invest_get_future'}[selected['kind']]
                raw=await bank(name,{'instrumentId':selected['id'],'idType':'INSTRUMENT_ID_TYPE_UID','responseView':['FULL']})
                card=raw.get('instrument',{})
                for field,expected in [('uid',selected['id']),('ticker',selected['ticker']),('classCode',selected['class_code'])]:
                    if card.get(field) and card[field]!=expected:raise ValueError('instrument_mismatch')
            evidence['result']={'instrument':selected,'data':raw}
        evidence.update(status='ok',observed_at=now())
    except Exception as exc:
        evidence.update(status='unavailable',observed_at=now(),error_type=type(exc).__name__,
                        error='Источник недоступен или запрос не прошёл проверку. Вывод по отсутствующим данным не сделан.')
        if evidence['calls'] and evidence['calls'][-1]['status']=='started':
            evidence['calls'][-1].update(status='error',finished_at=now(),error_type=type(exc).__name__)
    return evidence


def specifications(evidence,uid):
    for item in reversed(evidence):
        if item['kind']!='spec' or item['status']!='ok':continue
        result=item['result'];instrument=result.get('instrument',{})
        if instrument.get('id')!=uid:continue
        card=result['data'].get('instrument',{});lot=card.get('lot')
        spec={'evidence_id':item['id'],'lot_size':str(lot) if isinstance(lot,int) and lot>0 else None}
        if instrument['kind']=='future':
            tick=decimal_value(card.get('minPriceIncrement'));money=decimal_value(card.get('minPriceIncrementAmount'))
            # MCP can return a Quotation (no embedded currency), not MoneyValue.
            # Future.currency is the settlement currency of the same contract.
            amount_currency=(card.get('minPriceIncrementAmount') or {}).get('currency')
            settlement_currency=card.get('currency')
            if amount_currency and settlement_currency and amount_currency.lower()!=settlement_currency.lower():
                return None
            currency=amount_currency or settlement_currency
            if tick and money and currency:
                spec.update(point_value=str(money/tick),currency=currency.lower(),
                            tick_size=str(tick),tick_value=str(money),price_unit='points',
                            expiration_date=card.get('expirationDate'),last_trade_date=card.get('lastTradeDate'),
                            observed_at=item.get('observed_at'))
        return spec
    return None
