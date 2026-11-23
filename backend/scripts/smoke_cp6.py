"""Opt-in isolated browser acceptance: fixture by default; PT/MCP only with --mode pt."""
import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from playwright.async_api import async_playwright
import uvicorn

from backend.app.api.routes import create_app
from backend.scripts.smoke_vertical_slice import LimitedProvider

LIVE_TEXT = ('Учебная проверка на реальном фьючерсе SiZ6 SPBFUT, декабрь 2026. '
             'Для примера гипотеза: ослабление рубля в течение недели; направление long. '
             'Параметры условные, не текущая цена и не заявка: капитал 100000 рублей, риск 1%, '
             'вход 100000 пунктов, стоп 99000 пунктов, количество 1 контракт. '
             'Проверь спецификацию и последнюю доступную котировку через MCP. '
             'Сохрани risk_inputs, полный план пока не нужен. Арифметику сделает сервер.')


async def poll(function, predicate, seconds=90):
    async with asyncio.timeout(seconds):
        while True:
            value = await function()
            if predicate(value): return value
            await asyncio.sleep(.5)


async def smoke(args):
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    report = {'time_utc': datetime.now(timezone.utc).isoformat(), 'mode': args.mode,
              'synthetic_sources': args.mode == 'fixture', 'hypothetical_inputs': True, 'trading': False}
    fixture = None
    if args.mode == 'fixture':
        # Explicit opt-in developer fixture, never imported by the application.
        from backend.scripts.cp6_fixtures import Fixtures, TEXT
        fixture = Fixtures(); fixture.current = datetime.now(timezone.utc)
        provider = LimitedProvider(SimpleNamespace(complete=fixture.model)); text = TEXT
    else:
        from backend.app.llm.external import APISettings, ChatAPIProvider
        settings = APISettings.from_env('pt'); key = settings.api_key
        if args.windows_user_key:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as registry:
                key = winreg.QueryValueEx(registry, 'LLM_API_KEY')[0]
        settings = replace(settings, api_key=key, model='deepseek', temperature=0, disable_thinking=True, max_calls=2)
        if args.zero_cost_pt: settings = replace(settings, zero_cost_confirmed=True, input_usd_per_million=Decimal(0), output_usd_per_million=Decimal(0))
        real = ChatAPIProvider(settings)
        if not real.configured: raise ValueError('Configure PT key and verified price ceilings or confirmed zero-cost PT')
        provider = LimitedProvider(real); text = LIVE_TEXT
    os.environ['TRADEGUARD_MONITORING_INTERVAL_SECONDS'] = '10'
    port, frontend_port = args.port, args.frontend_port
    url = f'http://127.0.0.1:{frontend_port}'
    server = task = node = browser = None
    with TemporaryDirectory(prefix='tradeguard-cp6-smoke-') as folder:
        def build():
            app = create_app(folder, model=provider.complete, tool=fixture.tool if fixture else None,
                             test_doubles=bool(fixture), worker_enabled=True)
            app.state.llm_provider = 'OFFLINE_TEST_DOUBLE' if fixture else 'pt'
            return app

        async def start(app):
            service = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, access_log=False, log_level='warning'))
            running = asyncio.create_task(service.serve())
            async with asyncio.timeout(10):
                while not service.started:
                    if running.done(): await running
                    await asyncio.sleep(.1)
            return service, running

        async def stop(service, running):
            if service:
                service.should_exit = True
                await asyncio.wait_for(running, 10)
        try:
            app = build(); server, task = await start(app)
            environment = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ('API_KEY', 'TINVEST', 'INVEST_TOKEN'))}
            environment.update(API_UPSTREAM=f'http://127.0.0.1:{port}', PORT=str(frontend_port))
            node = await asyncio.create_subprocess_exec('node', 'frontend/dev-server.mjs', env=environment,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch()
                page = await browser.new_page(viewport={'width': 1365, 'height': 1000})
                errors = []; page.on('pageerror', lambda error: errors.append(type(error).__name__))
                await page.goto(url, wait_until='networkidle')
                await page.locator('#input').wait_for(state='visible')
                await page.locator('#educational').check()
                await page.locator('#input').fill(text)
                async with page.expect_response(lambda r: r.url.endswith('/messages') and r.request.method == 'POST', timeout=180000) as pending:
                    await page.locator('#send').click()
                turn = await (await pending.value).json()
                last = turn['messages'][-1]
                assert not last['response'].get('error'), 'Agent failed'
                assert [e['kind'] for e in turn['evidence']] == ['search', 'spec', 'quote']
                assert provider.calls == 1
                await page.locator('#planEditor').wait_for(state='attached')
                await page.locator('#planEditDetails > summary').click()
                for field, value in [('planHypothesis', 'Учебная гипотеза: ослабление рубля'), ('planHorizon', 'Учебная неделя'),
                                     ('plan_entry_conditions', 'После проверки исходной гипотезы'), ('plan_exit_conditions', 'По заданному стопу'),
                                     ('plan_review_conditions', 'Пересмотреть при изменении спецификации')]:
                    await page.locator('#' + field).fill(value)
                async with page.expect_response(lambda r: r.request.method == 'PATCH') as saved:
                    await page.locator('#savePlan').click()
                draft = await (await saved.value).json(); pid = draft['id']; sid = draft['session_id']
                assert draft['version'] == 2 and draft['risk']['status'] == 'calculated', draft['risk']['missing']
                assert Decimal(draft['risk']['calculation']['loss_at_stop']) == 1000
                await page.locator('#reviewPlan').check()
                async with page.expect_response(lambda r: r.url.endswith('/confirm')) as confirmed:
                    await page.locator('#confirmPlan').click()
                confirmation_response = await confirmed.value
                assert confirmation_response.status == 200
                snapshot = await confirmation_response.json()
                assert snapshot['status'] == 'confirmed' and snapshot['confirmation']['version'] == 2
                async def get(suffix): return await (await page.request.get(url + f'/api/plans/{pid}/' + suffix)).json()
                checks = await poll(lambda: get('checks'), bool)
                assert checks[0]['plan_version'] == 2
                if fixture: assert checks[0]['status'] == 'satisfied'
                else: assert checks[0]['status'] in ('satisfied', 'affected', 'insufficient_data')
                notifications = await poll(lambda: get('notifications'), lambda rows: bool(rows) and rows[0]['delivery_status'] == 'delivered')
                assert notifications[0]['check_id'] == checks[0]['id']
                await page.locator('#planEditDetails > summary').click()
                await page.locator('#planHypothesis').fill('Новый учебный черновик; подтверждённые условия прежние')
                async with page.expect_response(lambda r: r.request.method == 'PATCH') as changed:
                    await page.locator('#savePlan').click()
                new = await (await changed.value).json()
                assert new['version'] == 3 and new['status'] == 'draft'
                assert (await get('monitoring'))['confirmed_version'] == 2
                # Real restart of backend against the SAME temporary volume, not a copied DB.
                await stop(server, task); server = task = None
                app = build(); server, task = await start(app)
                await page.reload(wait_until='networkidle')
                await page.locator('#planEditor').wait_for(state='attached')
                repeated = await poll(lambda: get('checks'), lambda rows: len(rows) >= 2, seconds=30)
                assert repeated[0]['plan_version'] == 2
                notices_after = await get('notifications')
                assert len(notices_after) == len(notifications), 'Duplicate notification after restart'
                with app.state.store.connect() as db:
                    stored = json.loads(db.execute('SELECT document FROM plan_snapshots WHERE plan_id=? AND version=2', (pid,)).fetchone()[0])
                assert stored == snapshot
                restored = await (await page.request.get(url + f'/api/plans/{pid}')).json()
                assert restored['version'] == 3 and restored['hypothesis'] == new['hypothesis']
                await page.screenshot(path=str(output / 'desktop.png'), full_page=True)
                await page.set_viewport_size({'width': 390, 'height': 844})
                await page.screenshot(path=str(output / 'mobile.png'), full_page=True)
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert not errors, 'Browser JavaScript error'
                final_state = await (await page.request.get(url + '/api/sessions/' + sid)).json()
                (output / 'state.json').write_text(json.dumps(final_state, ensure_ascii=False, indent=2), encoding='utf-8')
                report.update(result='passed', model_calls=provider.calls, provider=provider.last_call,
                    initial_tools=[e['kind'] for e in turn['evidence']], draft_version=3, confirmed_version=2,
                    checks=repeated, notifications=notices_after, snapshot_unchanged=True, backend_restarted=True,
                    browser_errors=errors, mobile_overflow=False, screenshots=['desktop.png', 'mobile.png'])
        except Exception as exc:
            report.update(result='failed', exception_type=type(exc).__name__)
            raise
        finally:
            if browser: await browser.close()
            await stop(server, task)
            if node:
                node.terminate(); await asyncio.wait_for(node.wait(), 10)
            (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(report, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['fixture', 'pt'], default='fixture')
    parser.add_argument('--windows-user-key', action='store_true')
    parser.add_argument('--zero-cost-pt', action='store_true')
    parser.add_argument('--port', type=int, default=18103)
    parser.add_argument('--frontend-port', type=int, default=15174)
    parser.add_argument('--output', type=Path, default=Path('backend/runtime/cp6-smoke'))
    asyncio.run(smoke(parser.parse_args()))
