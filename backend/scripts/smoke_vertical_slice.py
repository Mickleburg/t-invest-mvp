"""Bounded LIVE PT/MCP UI smoke with the production provider and a fresh store."""
import argparse
from dataclasses import replace
from decimal import Decimal
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

from backend.app.llm.external import APISettings, ChatAPIProvider


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zero-cost-pt',action='store_true',help='Use the explicitly confirmed free corporate PT tariff')
    parser.add_argument('--windows-user-key',action='store_true')
    parser.add_argument('--port',type=int,default=18003)
    args=parser.parse_args()
    os.environ['LLM_PROVIDER']='pt'
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
    from backend.app.main import create_app
    with TemporaryDirectory(prefix='tradeguard-live-smoke-') as folder:
        print('LIVE PT/MCP smoke: production provider; <=6 model requests; fresh temporary store; no trading.',flush=True)
        app=create_app(Path(folder),provider=provider,test_doubles=False)
        uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False)
