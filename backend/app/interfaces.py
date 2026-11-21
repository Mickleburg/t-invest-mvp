"""Team boundary contracts. Only LLMProvider is wired today; other targets are CP1-CP3.

Adapters raise ProviderUnavailable (retryable) or ContractViolation (non-retryable).
No raw T-Invest payloads cross the target MarketDataProvider boundary.
"""
from datetime import datetime
from decimal import Decimal
from typing import Protocol,Any,Literal
from pydantic import BaseModel,ConfigDict
from backend.app.agent.models import Reply,RiskInputs

class ProviderUnavailable(RuntimeError):pass
class ContractViolation(ValueError):pass

class MarketSnapshot(BaseModel):
    model_config=ConfigDict(extra='forbid')
    instrument_id:str
    price:Decimal|None
    currency:str|None
    price_unit:Literal['currency','points']
    source:str
    observed_at:datetime
    retrieved_at:datetime
    status:Literal['available','stale','insufficient_data']
    tick_size:Decimal|None=None
    tick_value:Decimal|None=None
    tick_currency:str|None=None

class ResearchEvidence(BaseModel):
    url:str
    quote:str
    retrieved_at:datetime
    published_at:datetime|None=None
    status:Literal['retrieved','blocked','unavailable','unverified']
    verified_event:bool=False

class LLMProvider(Protocol):
    async def complete(self,context:dict[str,Any])->tuple[Reply,dict[str,Any]]:...

class AgentService(Protocol):
    async def message(self,session_id:str,text:str,request_id:str,educational:bool=False)->dict[str,Any]:...

class MarketDataProvider(Protocol):
    async def snapshot(self,instrument_id:str)->MarketSnapshot:...

class ResearchProvider(Protocol):
    async def research(self,question:str,instrument_id:str|None)->list[ResearchEvidence]:...

class RiskEngine(Protocol):
    def calculate(self,inputs:RiskInputs|None,user_messages:list[str],spec:dict|None=None)->dict[str,Any]:...





from .plans.contracts import PlanRepository
from .monitoring.contracts import MonitoringService
