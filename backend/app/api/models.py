from typing import Literal,Any
from pydantic import BaseModel,ConfigDict

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

class Error(WireModel):
    detail:str
