"""Read-only T-Invest sandbox MCP transport. No REST/gRPC or account operations."""
import asyncio
import json
import logging
import os
import ssl
from contextlib import asynccontextmanager

import httpx
from jsonschema import validate
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .credentials import load_token

ENDPOINT = "https://sandbox-invest-public-api.tbank.ru/mcp"
ALLOWED_TOOLS = frozenset({
    "invest_find_instrument", "invest_get_asset", "invest_get_asset_fundamentals",
    "invest_get_bond", "invest_get_bond_events", "invest_get_bond_accrued", "invest_get_brand",
    "invest_get_dfa", "invest_get_forecast", "invest_get_insider_deals", "invest_get_instrument_reports",
    "invest_get_risk_rates", "invest_get_share_dividends", "invest_get_trading_schedule",
    "invest_list_assets", "invest_list_bonds", "invest_list_brands", "invest_list_consensus_forecasts",
    "invest_list_countries", "invest_list_currencies", "invest_list_dfas", "invest_list_etfs",
    "invest_list_futures", "invest_list_indicatives", "invest_list_options", "invest_list_shares",
    "invest_list_structured_notes", "invest_get_last_trades", "invest_get_market_values",
    "invest_get_orderbook", "invest_get_tech_analysis", "invest_get_trading_statuses",
    "invest_list_signals", "invest_list_strategies", "invest_get_currency", "invest_get_etf",
    "invest_get_future", "invest_get_news", "invest_get_option", "invest_get_share",
    "invest_get_structured_note", "invest_get_candles",
})
log = logging.getLogger(__name__)


class SandboxError(Exception):
    """Safe error for display; never includes server text or request headers."""
    def __init__(self,message,*,retryable=False):
        super().__init__(message)
        self.retryable=retryable


def http_client(**kwargs):
    # Uses the OS trust store (including locally installed corporate CAs), never verify=False.
    # Corporate proxies may buffer the MCP SSE stream. Direct is the sandbox default;
    # installations requiring an egress proxy can explicitly opt into env routing.
    proxy = os.getenv('TINVEST_MCP_USE_PROXY', '0')
    if proxy not in ('0', '1'):
        raise ValueError('TINVEST_MCP_USE_PROXY must be 0 or 1')
    return httpx.AsyncClient(**kwargs, verify=ssl.create_default_context(),
                             trust_env=proxy == '1', follow_redirects=False)


def decode_result(result) -> dict:
    if result.isError:
        raise SandboxError("MCP-инструмент вернул ошибку. Проверьте доступность бумаги и токен песочницы.")
    payload = result.structuredContent
    if payload is None:
        blocks = [block.text for block in result.content if block.type == "text"]
        if len(blocks) != 1:
            raise SandboxError("MCP вернул неподдерживаемый формат ответа")
        payload = json.loads(blocks[0])
    if not isinstance(payload, dict):
        raise SandboxError("MCP вернул ответ без JSON-объекта")
    return payload


class ReadOnlySession:
    def __init__(self, session, tools):
        self.session = session
        self.tools = tools

    async def call(self, name: str, arguments: dict) -> dict:
        if name not in ALLOWED_TOOLS:
            raise SandboxError("Этот MCP-инструмент запрещён в TradeGuard")
        if name not in self.tools:
            raise SandboxError(f"MCP-инструмент {name} недоступен на сервере")
        validate(arguments, self.tools[name].inputSchema)
        log.info("sandbox.tool.start name=%s", name)
        result = decode_result(await self.session.call_tool(name, arguments))
        log.info("sandbox.tool.done name=%s", name)
        return result


@asynccontextmanager
async def sandbox_session():
    try:
        async with asyncio.timeout(60):
            async with streamablehttp_client(
                ENDPOINT, headers={"Authorization": "Bearer " + load_token()},
                httpx_client_factory=http_client, timeout=15, sse_read_timeout=15,
            ) as (reader, writer, _):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    tools = {}
                    cursor = None
                    for _ in range(10):
                        page = await session.list_tools(cursor=cursor)
                        tools.update({tool.name: tool for tool in page.tools})
                        cursor = page.nextCursor
                        if not cursor:
                            break
                    else:
                        raise SandboxError("Слишком много страниц MCP-инструментов")
                    yield ReadOnlySession(session, tools)
    except Exception as exc:
        # SDK wraps transport errors in ExceptionGroup. Only classify safe known codes.
        def leaves(error):
            if isinstance(error, BaseExceptionGroup):
                return [leaf for child in error.exceptions for leaf in leaves(child)]
            return [error]
        errors = leaves(exc)
        log.warning("sandbox.failed types=%s", ",".join(type(e).__name__ for e in errors))
        safe = next((e for e in errors if isinstance(e, SandboxError)), None)
        if safe:
            raise safe from None
        status = next((e.response.status_code for e in errors if isinstance(e, httpx.HTTPStatusError)), None)
        if status in (401, 403):
            raise SandboxError("Песочница отклонила авторизацию. Проверьте токен и его права.") from None
        if any(isinstance(e, (TimeoutError, httpx.TimeoutException)) for e in errors):
            raise SandboxError("MCP песочницы не ответил вовремя. Повторите загрузку данных.",retryable=True) from None
        if any(isinstance(e,httpx.TransportError) for e in errors):
            raise SandboxError("Соединение с MCP песочницы прервано. Повторите загрузку данных.",retryable=True) from None
        raise SandboxError("Не удалось получить данные MCP песочницы. Проверьте соединение, сертификаты и журнал.") from None
