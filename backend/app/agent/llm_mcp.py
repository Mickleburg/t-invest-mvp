"""One real schema-bound dialogue LLM, using the existing MCP/CLI bridge."""
from mcp.server.fastmcp import FastMCP
from backend.app.llm.structured import structured_llm
from .models import Reply
from .prompt import PROMPT

server=FastMCP('TradeGuard dialogue')

@server.tool()
async def discuss(context:dict)->dict:
    payload=await structured_llm(PROMPT,context,Reply.model_json_schema())
    Reply.model_validate(payload)
    return payload

if __name__=='__main__':server.run(transport='stdio')
