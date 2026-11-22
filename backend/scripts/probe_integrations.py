"""Opt-in network diagnostics. Prints statuses only, never payloads/credentials."""
import argparse
import asyncio
import json


async def probe(mcp=False, llm=False):
    from backend.app.llm.external import APISettings, api_http_client
    results = {}
    for name, url in [('pt', 'https://api-llm.ptsecurity.com/v1/models'),
                      ('deepseek', 'https://api.deepseek.com/models')]:
        try:
            settings = APISettings(name, url.removesuffix('/models'), 'probe', '')
            async with api_http_client(settings) as client:
                response = await client.get(url, timeout=10)
            results[name] = {'unauthenticated_http_status': response.status_code,
                             'compatibility': 'not_tested'}
        except Exception:
            results[name] = {'network': 'unavailable', 'compatibility': 'not_tested'}
    if mcp:
        from backend.app.integrations.tinvest import sandbox_session, ALLOWED_TOOLS
        try:
            async with sandbox_session() as session:
                results['sandbox_mcp'] = {'initialize': 'ok',
                    'allowed_tools_available': len(ALLOWED_TOOLS.intersection(session.tools)),
                    'market_data_call': 'not_tested'}
        except Exception:
            results['sandbox_mcp'] = {'initialize': 'failed'}
    if llm:
        # Explicit, single billable smoke request. Does not enable native JSON/tool modes.
        from openai import AsyncOpenAI
        from backend.app.llm.external import APISettings, api_http_client
        from backend.app.agent.models import Reply
        from backend.app.agent.prompt import PROMPT
        import os
        settings = APISettings.from_env(os.environ['LLM_PROVIDER'])
        try:
            if not settings.api_key:
                raise ValueError('Missing key')
            async with AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url,
                    timeout=45, max_retries=0,
                    http_client=api_http_client(settings)) as client:
                async with asyncio.timeout(45):
                    result = await client.chat.completions.create(model=settings.model, max_tokens=2048,
                        **({'temperature':settings.temperature} if settings.temperature is not None else {}),
                        **({'extra_body':{'chat_template_kwargs':{'enable_thinking':False}}} if settings.provider=='pt' and settings.disable_thinking else {}),
                        **({'response_format': {'type': 'json_object'}} if settings.provider == 'pt' else {}),
                        messages=[{'role': 'system', 'content': PROMPT + '\nJSON schema:\n' + json.dumps(Reply.model_json_schema())},
                                  {'role': 'user', 'content': 'Что такое ГО? Кратко, без плана и инструментов.'}])
            if result.choices[0].finish_reason != 'stop':
                raise ValueError('Incomplete output')
            reply = Reply.model_validate_json(result.choices[0].message.content)
            results['llm_smoke'] = {'provider': settings.provider, 'reply_schema': 'valid',
                'educational_no_tools': not reply.tool_requests,
                'reply_characters': len(reply.reply), 'native_json_tool_modes': 'not_tested',
                'calls': 1, 'max_output_tokens': 2048}
        except Exception:
            results['llm_smoke'] = {'provider': settings.provider, 'reply_schema': 'failed_or_unavailable', 'calls_attempted': 1}
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mcp', action='store_true', help='Authenticate read-only sandbox MCP and list tools')
    parser.add_argument('--llm', action='store_true', help='One billable request, max 2048 output tokens; requires explicit LLM_PROVIDER/key')
    args = parser.parse_args()
    print(json.dumps(asyncio.run(probe(args.mcp, args.llm))))
