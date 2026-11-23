"""CP6 interface, implemented by Monitor; checks refer to confirmed snapshots."""
from typing import Protocol, Any

class MonitoringService(Protocol):
    async def check(self,plan_id:str,confirmed_version:int,request_id:str)->dict[str,Any]:...
