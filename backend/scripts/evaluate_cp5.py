"""Opt-in LIVE acceptance cases: real providers, sandbox MCP, fresh stores; no doubles."""
import argparse
import asyncio
from dataclasses import replace
from decimal import Decimal
import json
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from uuid import uuid4

from backend.app.agent.service import Service
from backend.app.agent.prompt import PROMPT,VERSION
from backend.app.api.models import SessionState
from backend.app.llm import provider_for
from backend.app.llm.external import APISettings,ChatAPIProvider
from backend.app.storage.repository import Store
from backend.scripts.check_live_slice import TEXT


async def evaluate(args):
    settings=None
    if args.provider=='pt':
        settings=APISettings.from_env('pt')
        key=settings.api_key
        if args.windows_user_key:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as registry:
                key=winreg.QueryValueEx(registry,'LLM_API_KEY')[0]
        settings=replace(settings,api_key=key,model=args.model or settings.model,
            zero_cost_confirmed=args.zero_cost_pt or settings.zero_cost_confirmed)
    cases=[('education','Что такое ГО? Коротко, без торгового плана.')]
    cases += [(f'future-{i+1}',TEXT) for i in range(args.repeats)]
    cases += [('missing-stop',TEXT.replace('стоп 99000 пунктов, ','')),
              ('ambiguous','Хочу фьючерс на нефть BR, но выпуск и экспирацию ещё не выбрал. Помоги уточнить контракт.')]
    results=[]
    args.output.mkdir(parents=True,exist_ok=True)
    for name,text in cases:
        started=time.monotonic()
        row={'case':name,'provider':args.provider,'requested_model':settings.model if settings else 'local_codex',
             'hypothetical_inputs':True,'live_sources':True,'prompt_version':VERSION,
             'prompt_sha256':hashlib.sha256(PROMPT.encode()).hexdigest()}
        with TemporaryDirectory(prefix='tradeguard-cp5-') as folder:
            store=Store(Path(folder)/'smoke.sqlite3')
            provider=ChatAPIProvider(settings) if settings else provider_for('local_codex')
            service=Service(store,Path(folder)/'artifacts',model=provider.complete,test_doubles=False)
            sid=store.create()['session']['id']
            try:
                state=await service.message(sid,text,str(uuid4()),educational=True)
                SessionState.model_validate(state)
                message=state['messages'][-1];response=message['response']
                assert not response.get('error'),'Agent error'
                assert len(message['text'])<=1000,'Long visible response'
                kinds=[e['kind'] for e in state['evidence']]
                calc=response['risk_calculation']
                row.update(tool_kinds=kinds,reply_characters=len(message['text']),risk_status=calc['status'],
                    model_calls=len(list((Path(folder)/'artifacts').glob('*/ai-*.json'))))
                if name.startswith('future-'):
                    assert kinds==['search','spec','quote'],'Unstable tool sequence'
                    assert all(e['status']=='ok' for e in state['evidence']),'Live source failure'
                    assert row['model_calls']==1,'Extra model round'
                    assert calc['status']=='calculated'
                    assert Decimal(calc['values']['risk_budget'])==1000
                    assert Decimal(calc['values']['position_loss'])==2000
                    assert calc['values']['over_budget'] is True
                    assert calc['values']['spec_evidence_id'] in {e['id'] for e in state['evidence']}
                    assert '%' not in message['text'] and '22' not in message['text'],'Model arithmetic in prose'
                    row['risk_values']=calc['values']
                elif name=='education':
                    assert not kinds and response['plan'] is None and response['risk_inputs'] is None
                elif name=='missing-stop':
                    assert calc['status']!='calculated' and 'position_loss' not in calc['values']
                elif name=='ambiguous':
                    assert not any(k in ('spec','quote','history','news') for k in kinds)
                    assert calc['status']!='calculated'
                quality=[json.loads(p.read_text(encoding='utf-8')) for p in (Path(folder)/'artifacts').glob('*/quality.json')]
                row.update(result='passed',quality=quality,actual_settings=getattr(provider,'last_call',None))
                (args.output/(name+'.state.json')).write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
            except Exception as exc:
                row.update(result='failed',exception_type=type(exc).__name__,actual_settings=getattr(provider,'last_call',None),
                    errors=[json.loads(p.read_text(encoding='utf-8')) for p in (Path(folder)/'artifacts').glob('*/error.json')])
                for index,p in enumerate((Path(folder)/'artifacts').glob('*/ai-*.json')):
                    (args.output/f'{name}.failed-ai-{index}.json').write_text(p.read_text(encoding='utf-8'),encoding='utf-8')
        row['elapsed_seconds']=round(time.monotonic()-started,3)
        results.append(row)
        (args.output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(row,ensure_ascii=True),flush=True)
    return all(r['result']=='passed' for r in results)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider',choices=['pt','local_codex'],default='pt')
    parser.add_argument('--model')
    parser.add_argument('--windows-user-key',action='store_true')
    parser.add_argument('--zero-cost-pt',action='store_true')
    parser.add_argument('--repeats',type=int,choices=range(1,6),default=3)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    raise SystemExit(0 if asyncio.run(evaluate(args)) else 1)
