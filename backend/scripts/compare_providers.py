"""Opt-in provider comparison on identical educational inputs and source snapshots."""
import argparse
import asyncio
from dataclasses import replace
from datetime import datetime,timezone
import json
import hashlib
from pathlib import Path
import time

from openai import AsyncOpenAI
from pydantic import ValidationError

from backend.app.agent.models import Reply
from backend.app.agent.prompt import PROMPT,VERSION
from backend.app.agent.service import Service
from backend.app.llm.external import APISettings,api_http_client


def contexts(snapshot):
    state=json.loads(snapshot.read_text(encoding='utf-8'))
    user=next(m['text'] for m in state['messages'] if m['role']=='user')
    known={i['id']:i for e in state['evidence'] if e['kind']=='search' and e['status']=='ok'
           for i in e['result']['instruments']}
    base={'educational':True,'evidence':[],'known_instruments':[],
          'tools_exhausted':False,'current_time_utc':datetime.now(timezone.utc).isoformat()}
    return {'education':base|{'messages':[{'role':'user','text':'Что такое ГО? Коротко, без торгового плана.'}]},
            'initial':base|{'messages':[{'role':'user','text':user}]},
            'with_sources':base|{'messages':[{'role':'user','text':user}],
                'known_instruments':list(known.values()),'evidence':Service.compact(state['evidence']),
                'tools_exhausted':True}}


async def compare(output,snapshot,models,temperature,local=False,disable_thinking=False):
    cases=contexts(snapshot)
    results=[]
    output.mkdir(parents=True,exist_ok=True)
    (output/'instructions.txt').write_text(PROMPT,encoding='utf-8')
    (output/'contexts.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
    if local:
        from backend.app.llm import provider_for
        provider=provider_for('local_codex')
    else:
        settings=APISettings.from_env('pt')
        if not settings.api_key:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as key:
                settings=replace(settings,api_key=winreg.QueryValueEx(key,'LLM_API_KEY')[0])
    for model in models:
        for name,context in cases.items():
            started=time.monotonic()
            row={'requested_model':model,'case':name,'prompt_version':VERSION,
                 'prompt_sha256':hashlib.sha256(PROMPT.encode()).hexdigest(),
                 'temperature':temperature if not local else None,'max_output_tokens':4096 if not local else None,
                 'disable_thinking':disable_thinking,'http_status':None}
            try:
                if local:
                    reply,raw=await provider.complete(context)
                    row['response_model']='local_codex (CLI default)'
                else:
                    async with AsyncOpenAI(api_key=settings.api_key,base_url=settings.base_url,
                        timeout=90,max_retries=0,http_client=api_http_client(settings)) as client:
                        async with asyncio.timeout(90):
                            response=await client.chat.completions.with_raw_response.create(
                                model=model,max_tokens=4096,response_format={'type':'json_object'},
                                **({'extra_body':{'chat_template_kwargs':{'enable_thinking':False}}} if disable_thinking else {}),
                                **({'temperature':temperature} if temperature is not None else {}),
                                messages=[{'role':'system','content':PROMPT+'\nJSON schema:\n'+json.dumps(Reply.model_json_schema(),ensure_ascii=False)},
                                          {'role':'user','content':json.dumps(context,ensure_ascii=False)}])
                    row['http_status']=response.status_code
                    completion=response.parse()
                    row['response_model']=completion.model
                    row['finish_reason']=completion.choices[0].finish_reason
                    row['reasoning_characters']=len(getattr(completion.choices[0].message,'reasoning_content',None) or '')
                    reply=Reply.model_validate_json(completion.choices[0].message.content or '')
                    if completion.choices[0].finish_reason!='stop':raise ValueError('Incomplete output')
                    raw=reply.model_dump()
                    if settings.api_key in json.dumps(raw):raise ValueError('Credential echo')
                kinds=[r.kind for r in reply.tool_requests]
                row.update(status='valid',reply_characters=len(reply.reply),
                    question_characters=[len(q) for q in reply.questions],tool_kinds=kinds,
                    repeated_search=kinds.count('search')>1,
                    risk_inputs_present=reply.risk_inputs is not None,
                    reply=raw)
            except Exception as exc:
                row.update(status='failed',exception_type=type(exc).__name__,
                           http_status=getattr(exc,'status_code',row['http_status']))
                if isinstance(exc,ValidationError):
                    row['validation_errors']=[{'type':e['type'],'loc':list(e['loc'])}
                        for e in exc.errors(include_input=False,include_context=False)]
            row['elapsed_seconds']=round(time.monotonic()-started,3)
            results.append(row)
            (output/'comparison.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:v for k,v in row.items() if k!='reply'},ensure_ascii=True),flush=True)
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--snapshot',type=Path,default=Path('backend/runtime/mcp-smoke/state.json'))
    parser.add_argument('--models',nargs='+',default=['deepseek','qwen35-122b-a10b','positive-llm-qwen36','positive-llm-code'])
    parser.add_argument('--temperature',type=float)
    parser.add_argument('--local-codex',action='store_true')
    parser.add_argument('--disable-thinking',action='store_true')
    args=parser.parse_args()
    asyncio.run(compare(args.output,args.snapshot,args.models,args.temperature,args.local_codex,args.disable_thinking))
