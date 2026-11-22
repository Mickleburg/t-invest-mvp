"""Replaceable LLM binding. External providers use configuration only."""
from backend.app.interfaces import LLMProvider,ProviderUnavailable

class LocalCodexProvider:
    async def complete(self,context):
        from backend.app.llm.client import discuss
        return await discuss(context)

class DisabledProvider:
    async def complete(self,context):
        raise ProviderUnavailable('LLM provider is disabled or not implemented')

def provider_for(name:str)->LLMProvider:
    if name=='local_codex':return LocalCodexProvider()
    if name in ('pt','deepseek'):
        from .external import APISettings,ChatAPIProvider
        return ChatAPIProvider(APISettings.from_env(name))
    if name in ('disabled','external_api'):return DisabledProvider()
    raise ValueError('Unknown LLM_PROVIDER; use local_codex, disabled, pt or deepseek')
