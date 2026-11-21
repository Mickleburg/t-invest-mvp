from mcp.server.fastmcp import FastMCP
from .web_research import research
from .research_summary import summarize

server = FastMCP("ThesisGuard public research")


@server.tool()
async def research_sources(instrument: dict, question: str, scope: str = "instrument") -> dict:
    """Search public primary-source pages using isolated Chromium; no event confirmation."""
    result = await research(instrument, question, scope)
    try:
        result["analysis"] = await summarize(result)
    except Exception:
        result["analysis"] = {"observations": [], "limitations": ["Сводка модели недоступна или не прошла проверку цитат. Изучите источники вручную."], "verified_event": False}
    return result


if __name__ == "__main__":
    server.run(transport="stdio")
