"""Run: uvicorn backend.app.main:app --port 8003. API only; same tested services."""
import os
from pathlib import Path
from .config import DEFAULT_DATA
from .api.routes import create_app as api_app
from .llm import provider_for

def create_app(directory=None,provider=None,test_doubles=False):
    name=os.getenv('LLM_PROVIDER','local_codex')
    selected=provider or provider_for(name)
    location=directory or Path(os.getenv('TRADEGUARD_DATA',DEFAULT_DATA))
    app=api_app(directory=location,model=selected.complete,
                      test_doubles=test_doubles)
    app.state.llm_provider=name
    app.state.llm_configured=provider is not None or name=='local_codex' or getattr(selected,'configured',False)
    return app

app=create_app()
