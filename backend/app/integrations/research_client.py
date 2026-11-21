import asyncio
import json
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def research_via_mcp(instrument, question, scope="instrument"):
    async with asyncio.timeout(240):
        async with stdio_client(StdioServerParameters(command=sys.executable, args=["-m", "backend.app.integrations.research_mcp"])) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                result = await session.call_tool("research_sources", {"instrument": instrument, "question": question, "scope": scope})
                if result.isError:
                    raise ValueError("Веб-исследование недоступно. Попробуйте позже; результат не подтверждён.")
                return result.structuredContent or json.loads(next(b.text for b in result.content if b.type == "text"))
