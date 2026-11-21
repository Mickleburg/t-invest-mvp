import asyncio
import hashlib
import json
from pathlib import Path
from backend.app.llm.client import discuss
from .models import Reply
from .prompt import PROMPT,VERSION
from backend.app.risk.engine import calculate
from backend.app.integrations.tools import execute,specifications
from backend.app.storage.repository import now,dump


class Service:
    def __init__(self,store,artifacts,model=discuss,tool=execute,test_doubles=False):
        self.store=store;self.artifacts=Path(artifacts);self.model=model;self.tool=tool;self.locks={};self.test_doubles=test_doubles

    async def message(self,sid,text,request_id,educational=False):
        lock=self.locks.setdefault(sid,asyncio.Lock())
        if lock.locked():raise ValueError('Агент ещё обрабатывает предыдущее сообщение')
        async with lock:
            with self.store.connect() as db:
                existing=db.execute('SELECT session_id FROM turns WHERE id=?',(request_id,)).fetchone()
                if existing:
                    if existing[0]!=sid:raise ValueError('Идентификатор сообщения принадлежит другому диалогу')
                    return self.store.state(sid)
                folder=self.artifacts/request_id;folder.mkdir(parents=True,exist_ok=True)
                db.execute('INSERT INTO turns VALUES(?,?,?,?,?)',(request_id,sid,'processing',now(),str(folder)))
                db.execute('UPDATE sessions SET processing=1,title=CASE WHEN title=? THEN ? ELSE title END WHERE id=?',('Новая идея',text[:60],sid))
            self.store.message(sid,'user',text,{'educational':educational})
            state=self.store.state(sid);evidence=state['evidence'][:];known={}
            educational=any(m['role']=='user' and (m['response'] or {}).get('educational') for m in state['messages'])
            for e in evidence:
                if e['kind']=='search' and e['status']=='ok':known.update({b['id']:b for b in e['result']['instruments']})
            metadata={'started_at':now(),'prompt_version':VERSION,'prompt_sha256':hashlib.sha256(PROMPT.encode()).hexdigest(),
                      'educational':educational,'request_id':request_id,'messages':[{'role':m['role'],'text':m['text']} for m in state['messages']],
                      'llm_transport':'local MCP -> Codex CLI structured output','mocked':self.test_doubles}
            (folder/'input.json').write_text(dump(metadata),encoding='utf-8')
            (folder/'instructions.txt').write_text(PROMPT,encoding='utf-8')
            context={'educational':educational,'messages':metadata['messages'][-30:],'known_instruments':list(known.values()),
                     'evidence':self.compact(evidence),'tools_exhausted':False,'current_time_utc':now()}
            calls=0;attempted=set();status='completed'
            try:
                for step in range(3):
                    context['tools_exhausted']=step==2 or calls>=3
                    (folder/f'context-{step}.json').write_text(dump(context),encoding='utf-8')
                    reply,raw=await self.model(context)
                    (folder/f'ai-{step}.json').write_text(dump(raw),encoding='utf-8')
                    if context['tools_exhausted'] or not reply.tool_requests:break
                    for request in reply.tool_requests:
                        key=dump(request.model_dump())
                        if key in attempted or calls>=3:continue
                        attempted.add(key);calls+=1
                        e=await self.tool(request,known)
                        evidence.append(e)
                        with self.store.connect() as db:db.execute('INSERT INTO evidence VALUES(?,?,?,?)',(e['id'],sid,request_id,dump(e)))
                        (folder/f'tool-{calls}.json').write_text(dump(e),encoding='utf-8')
                        if e['kind']=='search' and e['status']=='ok':known.update({b['id']:b for b in e['result']['instruments']})
                    context.update(evidence=self.compact(evidence),known_instruments=list(known.values()))
                response=reply.model_dump();response['tool_requests']=[]
                valid_ids={e['id'] for e in evidence if e['status']=='ok'}
                if any(f.evidence_id not in valid_ids for f in reply.facts):
                    raise ValueError('Fact references an unavailable source')
                # A formal source reference is checked; semantic grounding still needs evaluation.
                if reply.plan and reply.plan.status=='reviewable' and (reply.plan.missing or reply.risk_inputs is None):
                    response['plan']['status']='preliminary'
                risk=reply.risk_inputs
                if risk and risk.instrument_id and risk.instrument_id not in known:raise ValueError('Unknown risk instrument')
                if risk and risk.instrument_id and known[risk.instrument_id]['kind']!=risk.instrument_kind:raise ValueError('Risk instrument kind mismatch')
                user_messages=[m['text'] for m in state['messages'] if m['role']=='user']
                calc=calculate(risk,user_messages,specifications(evidence,risk.instrument_id) if risk and risk.instrument_id else None)
                response.update(risk_calculation=calc,prompt_version=VERSION,artifact_id=request_id)
                if response['plan'] and (calc['status']!='calculated' or calc['values'].get('over_budget')):response['plan']['status']='preliminary'
                shown=reply.reply
                if reply.questions:shown+='\n\n'+'\n\n'.join(reply.questions)
                self.store.message(sid,'assistant',shown,response)
            except Exception as exc:
                status='failed'
                (folder/'error.json').write_text(dump({'type':type(exc).__name__,'time':now(),'code':'dialogue_failed'}),encoding='utf-8')
                self.store.message(sid,'assistant','Не удалось получить проверяемый ответ агента. Ваше сообщение сохранено. Новые данные не выдуманы; можно повторить запрос или начать новый диалог.',{'error':'dialogue_failed','artifact_id':request_id})
            finally:
                with self.store.connect() as db:
                    db.execute('UPDATE sessions SET processing=0 WHERE id=?',(sid,));db.execute('UPDATE turns SET status=? WHERE id=?',(status,request_id))
            return self.store.state(sid)

    @staticmethod
    def compact(evidence):
        out=[]
        for item in evidence[-12:]:
            e={k:item.get(k) for k in ('id','kind','status','observed_at','error')}
            data=item.get('result')
            encoded=dump(data)
            e['result']=data if len(encoded)<18000 else {'excerpt_json':encoded[:18000],'truncated':True}
            out.append(e)
        return out
