"""Bounded LIVE PT/MCP UI smoke with the production provider and a fresh store."""
import argparse
import asyncio
from dataclasses import replace
from decimal import Decimal
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

from backend.app.llm.external import APISettings, ChatAPIProvider
from backend.app.llm import provider_for


class LimitedProvider:
    def __init__(self,inner):self.inner=inner;self.calls=0
    async def complete(self,context):
        if self.calls>=6:raise RuntimeError('Smoke model request limit exceeded')
        self.calls+=1
        return await self.inner.complete(context)
    @property
    def last_call(self):return getattr(self.inner,'last_call',None)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zero-cost-pt',action='store_true',help='Use the explicitly confirmed free corporate PT tariff')
    parser.add_argument('--windows-user-key',action='store_true')
    parser.add_argument('--provider',choices=['pt','local_codex'],default='pt')
    parser.add_argument('--once',action='store_true',help='Gracefully stop after one completed user turn')
    parser.add_argument('--port',type=int,default=18003)
    args=parser.parse_args()
    os.environ['LLM_PROVIDER']=args.provider
    if args.provider=='pt':
        settings=APISettings.from_env('pt')
        key=settings.api_key
        if args.windows_user_key:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as registry:
                key=winreg.QueryValueEx(registry,'LLM_API_KEY')[0]
        settings=replace(settings,api_key=key,max_calls=min(settings.max_calls,6))
        if args.zero_cost_pt:
            settings=replace(settings,zero_cost_confirmed=True,
                             input_usd_per_million=Decimal(0),output_usd_per_million=Decimal(0))
        if not key: raise SystemExit('PT key is required')
        provider=ChatAPIProvider(settings)
        if not provider.configured: raise SystemExit('Configure verified prices or explicitly confirmed zero-cost PT')
    else:provider=provider_for('local_codex')
    provider=LimitedProvider(provider)
    from backend.app.main import create_app
    with TemporaryDirectory(prefix='tradeguard-live-smoke-') as folder:
        print('LIVE PT/MCP smoke: production provider; <=6 model requests; fresh temporary store; no trading.',flush=True)
        app=create_app(Path(folder),provider=provider,test_doubles=False)
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=args.port,access_log=False))
        if args.once:
            @app.middleware('http')
            async def stop_after_turn(request,call_next):
                response=await call_next(request)
                if request.method=='POST' and request.url.path.endswith('/messages'):
                    response.headers['x-smoke-model-calls']=str(provider.calls)
                    async def stop_later():
                        await asyncio.sleep(15)
                        server.should_exit=True
                    asyncio.create_task(stop_later())
                return response
        asyncio.run(server.serve())
