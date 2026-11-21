import os
from pathlib import Path
from uuid import UUID
from contextlib import asynccontextmanager
from fastapi import FastAPI,HTTPException
from pydantic import Field
from backend.app.common import StrictModel
from backend.app.config import DEFAULT_DATA
from backend.app.storage.repository import Store
from backend.app.agent.service import Service
from backend.app.agent.prompt import VERSION
from backend.app.api.models import Session,SessionState,Health,Error

class Message(StrictModel):
    text:str=Field(min_length=1,max_length=5000)
    request_id:UUID
    educational:bool=False

def create_app(directory=None,model=None,tool=None,test_doubles=None):
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
        yield
    app=FastAPI(title='TradeGuard',lifespan=lifespan)
    def require(sid):
        state=app.state.store.state(sid)
        if state is None:raise HTTPException(404,'Диалог не найден')
        return state
    @app.get('/api/health',response_model=Health)
    def health():return {'prompt_version':VERSION,'trading':False,'data_source':'T-Invest sandbox MCP',
                         'llm_provider':getattr(app.state,'llm_provider','local_codex'),
                         'llm_configured':getattr(app.state,'llm_configured',True)}
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
    return app

