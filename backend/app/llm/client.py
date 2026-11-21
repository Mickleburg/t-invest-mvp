import asyncio
import json
import sys
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from backend.app.agent.models import Reply

async def discuss(context):
    async with asyncio.timeout(175):
        async with stdio_client(StdioServerParameters(command=sys.executable,args=['-m','backend.app.agent.llm_mcp'])) as (reader,writer):
            async with ClientSession(reader,writer) as session:
                await session.initialize()
                result=await session.call_tool('discuss',{'context':context})
                if result.isError:raise ValueError('LLM MCP returned an error')
                raw=result.structuredContent
                if raw is None:raw=json.loads(next(b.text for b in result.content if b.type=='text'))
                return Reply.model_validate(raw),raw
