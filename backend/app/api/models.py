from typing import Literal,Any
from uuid import UUID
from pydantic import BaseModel,ConfigDict,Field

class WireModel(BaseModel):
    model_config=ConfigDict(extra='forbid')

class Session(WireModel):
    id:str
    title:str
    created_at:str
    processing:Literal[0,1]

class MessageRecord(WireModel):
    id:int
    session_id:str
    role:Literal['user','assistant']
    text:str
    created_at:str
    response:dict[str,Any]|None

class SessionState(WireModel):
    session:Session
    messages:list[MessageRecord]
    # Prototype evidence is intentionally opaque. CP1 introduces normalized DTOs.
    evidence:list[dict[str,Any]]

class Health(WireModel):
    prompt_version:str
    trading:Literal[False]
    data_source:str
    llm_provider:str='local_codex'
    llm_configured:bool=True
    monitoring_enabled:bool=False

class Error(WireModel):
    detail:str

class PlanPatch(WireModel):
    expected_version:int=Field(ge=1)
    changes:dict[str,Any]=Field(min_length=1)

class PlanConfirmation(WireModel):
    version:int=Field(ge=1)
    content_hash:str=Field(pattern='^[a-f0-9]{64}$')
    request_id:UUID

class MonitoringState(WireModel):
    plan_id:str
    confirmed_version:int
    state:Literal['not_started','active','paused','error']
    last_checked_at:str|None
    next_check_at:str|None

class Check(WireModel):
    id:str
    plan_id:str
    plan_version:int
    rule_id:str
    checked_at:str
    status:Literal['satisfied','affected','insufficient_data','error']
    source_ids:list[str]
    observed_value:str|None

class Notification(WireModel):
    id:str
    plan_id:str
    plan_version:int
    check_id:str
    created_at:str
    text:str
    delivery_status:Literal['stored','delivered','failed']
