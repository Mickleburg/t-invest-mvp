"""Proposed CP3 interface; implementation is not available yet."""
from typing import Protocol, Any

class MonitoringService(Protocol):
    async def check(self,plan_id:str,confirmed_version:int,request_id:str)->dict[str,Any]:...
