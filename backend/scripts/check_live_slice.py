"""Opt-in browser check against the isolated live smoke server (no test doubles)."""
import argparse
import asyncio
from datetime import datetime,timezone
from decimal import Decimal
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from backend.app.integrations.tools import specifications

TEXT=('Учебная проверка на реальном фьючерсе SiZ6 SPBFUT, декабрь 2026. '
      'Для примера гипотеза: ослабление рубля в течение недели; направление long. '
      'Параметры условные, не текущая цена и не заявка: капитал 100000 рублей, риск 1%, '
      'вход 100000 пунктов, стоп 99000 пунктов, количество 2 контракта. '
      'Проверь спецификацию и последнюю доступную котировку через MCP. '
      'Сохрани risk_inputs, полный план пока не нужен. Арифметику сделает сервер.')


async def check(url, output):
    if urlsplit(url).hostname not in ('127.0.0.1','localhost'):
        raise ValueError('Use a local isolated smoke server')
    output.mkdir(parents=True,exist_ok=True)
    report={'time_utc':datetime.now(timezone.utc).isoformat(),'mode':'live_pt_and_sandbox_mcp',
            'hypothetical_inputs':True,'trading':False}
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        page=await browser.new_page(viewport={'width':1365,'height':1000})
        errors=[]
        page.on('pageerror',lambda error:errors.append(type(error).__name__))
        try:
            await page.goto(url,wait_until='networkidle')
            await page.locator('#input').wait_for(state='visible')
            # The frontend opens the most recent session on first load. Start a
            # fresh one so a repeat cannot pass using earlier evidence/results.
            async with page.expect_response(lambda r:r.url.endswith('/api/sessions') and r.request.method=='POST'):
                await page.locator('#newChat').click()
            await page.locator('#educational').check()
            async def send(text):
                await page.locator('#input').fill(text)
                async with page.expect_response(lambda r:'/messages' in r.url and r.request.method=='POST',timeout=180000) as pending:
                    await page.locator('#send').click()
                response=await pending.value
                assert response.status==200
                return await response.json()
            state=await send(TEXT)
            report['turns']=1
            # The agent may spend its first tool budget clarifying/searching.
            # A real follow-up completes the same scenario, without injecting data.
            if not any(e['kind']=='quote' and e['status']=='ok' for e in state['evidence']):
                state=await send('Теперь запроси последнюю доступную котировку через quote для уже найденного SiZ6. '
                    'Повторять search не нужно; если спецификации ещё нет, запроси spec. '
                    'Сохрани исходные учебные параметры в risk_inputs: капитал 100000 рублей, риск 1%, '
                    'вход 100000 пунктов, стоп 99000 пунктов, long, количество 2 контракта.')
                report['turns']=2
            (output/'state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
            latest=next(m for m in reversed(state['messages']) if m['role']=='assistant')
            assert not latest['response'].get('error'), 'Agent returned an error'
            evidence=state['evidence']
            instrument=next(i for e in evidence if e['kind']=='search' and e['status']=='ok'
                            for i in e['result']['instruments'] if i['ticker']=='SiZ6' and i['kind']=='future')
            spec=specifications(evidence,instrument['id'])
            assert spec and spec.get('point_value') and spec.get('tick_size')
            quote=next(e for e in evidence if e['kind']=='quote' and e['status']=='ok')
            assert quote['result']['instrument']['id']==instrument['id']
            values=quote['result']['data']['instruments'][0]['values']
            last_price=next(v for v in values if v['type']=='INSTRUMENT_VALUE_LAST_PRICE')
            calc=latest['response']['risk_calculation']
            assert calc['status']=='calculated', 'Risk was not calculated'
            assert calc['values']['spec_evidence_id']==spec['evidence_id']
            assert Decimal(calc['values']['risk_budget'])==1000
            assert Decimal(calc['values']['position_loss'])==2000*Decimal(spec['point_value'])
            assert calc['values']['over_budget'] is True
            await page.locator('#risk').wait_for(state='visible')
            await page.get_by_text('Указанная позиция превышает согласованный лимит риска.',exact=True).wait_for()
            await page.screenshot(path=str(output/'desktop.png'),full_page=True)
            await page.set_viewport_size({'width':390,'height':844})
            await page.screenshot(path=str(output/'mobile.png'),full_page=True)
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile horizontal overflow'
            assert not errors, 'Browser JavaScript errors'
            report.update(result='passed',session_id=state['session']['id'],specification=spec,
                last_price=last_price,risk=calc,browser_errors=errors,
                tools=[c['name'] for e in evidence for c in e['calls']],
                screenshots=['desktop.png','mobile.png'])
        except Exception as exc:
            report.update(result='failed',exception_type=type(exc).__name__,browser_errors=errors)
            raise
        finally:
            (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(report,ensure_ascii=True),flush=True)
            await browser.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:15173')
    parser.add_argument('--output',type=Path,default=Path('backend/runtime/mcp-smoke'))
    args=parser.parse_args()
    asyncio.run(check(args.url,args.output))
