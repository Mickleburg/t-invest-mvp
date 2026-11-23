import os
import asyncio
from contextlib import suppress
from pathlib import Path
from uuid import UUID
from contextlib import asynccontextmanager
from fastapi import FastAPI,HTTPException
from fastapi.responses import JSONResponse
from pydantic import Field
from backend.app.common import StrictModel
from backend.app.config import DEFAULT_DATA
from backend.app.storage.repository import Store
from backend.app.agent.service import Service
from backend.app.agent.prompt import VERSION
from backend.app.api.models import Session,SessionState,Health,Error,MessageRecord,PlanPatch,PlanConfirmation,MonitoringState,Check,Notification
from backend.app.plans.repository import Plans
from backend.app.plans.schema import PlanError,content_hash,openapi_schemas
from backend.app.monitoring.service import Monitor

class Message(StrictModel):
    text:str=Field(min_length=1,max_length=5000)
    request_id:UUID
    educational:bool=False

def create_app(directory=None,model=None,tool=None,test_doubles=None,worker_enabled=None):
    @asynccontextmanager
    async def lifespan(app):
        path=Path(directory or os.getenv('TRADEGUARD_DATA',DEFAULT_DATA));path.mkdir(parents=True,exist_ok=True)
        app.state.store=Store(path/'tradeguard.sqlite3')
        with app.state.store.connect() as db:
            pending=[r[0] for r in db.execute('SELECT id FROM sessions WHERE processing=1')]
            db.execute('UPDATE sessions SET processing=0');db.execute("UPDATE turns SET status='interrupted' WHERE status='processing'")
        for sid in pending:app.state.store.message(sid,'assistant','Предыдущий ответ прерван перезапуском сервера. Контекст сохранён; отправьте следующий запрос, чтобы продолжить.')
        kwargs={}
        if model:kwargs['model']=model
        if tool:kwargs['tool']=tool
        doubles=bool(model or tool) if test_doubles is None else test_doubles
        app.state.service=Service(app.state.store,path/'artifacts',test_doubles=doubles,**kwargs)
        app.state.plans=Plans(app.state.store,test_doubles=doubles)
        app.state.monitor=Monitor(app.state.store,test_doubles=doubles,
            interval=os.getenv('TRADEGUARD_MONITORING_INTERVAL_SECONDS','60'),**({'tool':tool} if tool else {}))
        enabled=worker_enabled if worker_enabled is not None else not doubles and os.getenv('TRADEGUARD_MONITORING_ENABLED','1')=='1'
        app.state.monitoring_enabled=enabled
        worker=asyncio.create_task(app.state.monitor.run()) if enabled else None
        try:yield
        finally:
            if worker:
                worker.cancel()
                with suppress(asyncio.CancelledError):await worker
    app=FastAPI(title='TradeGuard',lifespan=lifespan)
    @app.exception_handler(PlanError)
    async def plan_error(request,exc):return JSONResponse({'detail':exc.detail},status_code=exc.status)
    def require(sid):
        state=app.state.store.state(sid)
        if state is None:raise HTTPException(404,'Диалог не найден')
        return state
    @app.get('/api/health',response_model=Health)
    def health():return {'prompt_version':VERSION,'trading':False,'data_source':'TEST DOUBLE (offline)' if app.state.service.test_doubles else 'T-Invest sandbox MCP',
                         'llm_provider':getattr(app.state,'llm_provider','local_codex'),
                         'llm_configured':getattr(app.state,'llm_configured',True),
                         'monitoring_enabled':app.state.monitoring_enabled}
    @app.get('/api/sessions',response_model=list[Session])
    def sessions():
        with app.state.store.connect() as db:return [dict(r) for r in db.execute('SELECT * FROM sessions ORDER BY created_at DESC LIMIT 60')]
    @app.post('/api/sessions',response_model=SessionState)
    def create():return app.state.store.create()
    @app.get('/api/sessions/{sid}',response_model=SessionState,responses={404:{'model':Error}})
    def state(sid:str):return require(sid)
    @app.post('/api/sessions/{sid}/messages',response_model=SessionState,responses={404:{'model':Error},409:{'model':Error}})
    async def message(sid:str,body:Message):
        require(sid)
        if not body.text.strip():raise HTTPException(422,'Введите сообщение')
        try:return await app.state.service.message(sid,body.text.strip(),str(body.request_id),body.educational)
        except ValueError as exc:raise HTTPException(409,str(exc)) from None
    errors={code:{'model':Error} for code in (404,409,422,503)}
    plan_responses={**errors,200:{'description':'Версия плана; ETag содержит SHA256 канонического черновика',
        'headers':{'ETag':{'schema':{'type':'string'},'description':'Quoted SHA256; use the 64 hex characters as content_hash'}},
        'content':{'application/json':{'schema':{'$ref':'#/components/schemas/TradePlan'}}}}}
    def plan_response(plan):return JSONResponse(plan,headers={'ETag':'"'+content_hash(plan)+'"','Cache-Control':'no-store'})
    @app.get('/api/sessions/{sid}/messages',response_model=list[MessageRecord],responses=errors)
    def message_history(sid:str):return require(sid)['messages']
    @app.get('/api/sessions/{sid}/plan',responses=plan_responses)
    async def session_draft(sid:str):return plan_response(await app.state.plans.for_session(sid))
    @app.get('/api/plans/{plan_id}',responses=plan_responses)
    async def get_plan(plan_id:str):return plan_response(await app.state.plans.get(plan_id))
    @app.patch('/api/plans/{plan_id}',responses=plan_responses)
    async def update_draft(plan_id:str,body:PlanPatch):
        return plan_response(await app.state.plans.update_draft(plan_id,body.expected_version,body.changes))
    @app.post('/api/plans/{plan_id}/confirm',responses=plan_responses)
    async def confirm_version(plan_id:str,body:PlanConfirmation):
        return plan_response(await app.state.plans.confirm(plan_id,body.version,body.content_hash,str(body.request_id)))
    @app.get('/api/plans/{plan_id}/monitoring',response_model=MonitoringState,responses=errors)
    def monitoring_state(plan_id:str):return app.state.monitor.state(plan_id)
    @app.get('/api/plans/{plan_id}/checks',response_model=list[Check],responses=errors)
    def checks(plan_id:str):return app.state.monitor.checks(plan_id)
    @app.get('/api/plans/{plan_id}/notifications',response_model=list[Notification],responses=errors)
    def notifications(plan_id:str):return app.state.monitor.notifications(plan_id)
    @app.post('/api/plans/{plan_id}/notifications/{notification_id}/ack',response_model=Notification,responses=errors)
    def acknowledge_notification(plan_id:str,notification_id:str):return app.state.monitor.acknowledge(plan_id,notification_id)
    original_openapi=app.openapi
    def openapi():
        spec=original_openapi()
        spec['components']['schemas'].update(openapi_schemas())
        spec['components']['schemas']['PlanPatch']['properties']['changes']={'$ref':'#/components/schemas/PlanChanges'}
        return spec
    app.openapi=openapi
    return app

