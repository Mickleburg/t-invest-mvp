"""Replaceable provider binding; no external API implementation is claimed yet."""
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
    if name in ('disabled','external_api'):return DisabledProvider()
    raise ValueError('Unknown LLM_PROVIDER; use local_codex, disabled or reserved external_api')
