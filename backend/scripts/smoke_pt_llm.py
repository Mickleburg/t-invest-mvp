"""One opt-in PT request. Reports structure/timing, never credentials or response text."""
import argparse
import asyncio
from dataclasses import replace
import json
import time

from openai import AsyncOpenAI
from pydantic import ValidationError

from backend.app.agent.models import Reply
from backend.app.agent.prompt import PROMPT
from backend.app.llm.external import APISettings, api_http_client


async def smoke(settings, *, reply_schema=False, json_mode=False):
    sent = {}

    async def inspect_request(request):
        sent['bearer_header_matches_key'] = request.headers.get('authorization') == 'Bearer ' + settings.api_key
        sent['model_is_bare_id'] = not json.loads(request.content)['model'].startswith('pt/')

    result = {'model': settings.model, 'stage': 'reply' if reply_schema else 'minimal',
              'key_present': bool(settings.api_key), 'http_status': None,
              'exception_type': None, 'tls_verification': True, 'json_mode': json_mode}
    if not settings.api_key:
        return result | {'exception_type': 'MissingAPIKey'}
    started = time.monotonic()
    try:
        http = api_http_client(settings)
        http.event_hooks['request'].append(inspect_request)
        async with AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url,
                timeout=settings.timeout, max_retries=0, http_client=http) as client:
            messages = ([{'role': 'system', 'content': PROMPT + '\nJSON schema:\n' + json.dumps(Reply.model_json_schema(), ensure_ascii=False)},
                         {'role': 'user', 'content': json.dumps({'messages': [{'role': 'user', 'text': 'Что такое ГО? Кратко, без плана и инструментов.'}], 'evidence': [], 'known_instruments': [], 'tools_exhausted': True}, ensure_ascii=False)}]
                        if reply_schema else [{'role': 'user', 'content': 'Return exactly OK.'}])
            async with asyncio.timeout(settings.timeout):
                raw = await client.chat.completions.with_raw_response.create(
                    model=settings.model, messages=messages,
                    max_tokens=settings.max_output_tokens if reply_schema else 128,
                    **({'response_format': {'type': 'json_object'}} if json_mode else {}))
                result['http_status'] = raw.status_code
                completion = raw.parse()
        result['structure'] = {
            'object': completion.object, 'choices_count': len(completion.choices),
            'usage_present': completion.usage is not None}
        if not completion.choices:
            result['exception_type'] = 'MissingChoices'
        else:
            choice = completion.choices[0]
            message = choice.message
            result['structure'].update(finish_reason=choice.finish_reason, role=message.role,
                content_type=type(message.content).__name__, content_characters=len(message.content or ''),
                reasoning_present=bool(getattr(message, 'reasoning_content', None)),
                native_tool_calls=bool(message.tool_calls))
            if reply_schema:
                try:
                    reply = Reply.model_validate_json(message.content or '')
                    result['reply_schema'] = 'valid'
                    result['reply_characters'] = len(reply.reply)
                    result['runtime_accepts_response'] = (choice.finish_reason == 'stop'
                        and not message.tool_calls and bool(message.content and message.content.strip()))
                except ValidationError as exc:
                    result['reply_schema'] = 'invalid'
                    result['validation_errors'] = [{'type': e['type'], 'loc': list(e['loc'])}
                        for e in exc.errors(include_input=False, include_context=False, include_url=False)]
                    text = (message.content or '').strip()
                    result['content_has_json_fence'] = text.startswith('```json\n') and text.endswith('\n```')
                    if result['content_has_json_fence']:
                        try:
                            Reply.model_validate_json(text[len('```json\n'):-len('\n```')])
                            result['fenced_reply_schema'] = 'valid'
                        except ValidationError:
                            result['fenced_reply_schema'] = 'invalid'
            else:
                result['minimal_ok'] = (message.content or '').strip() == 'OK'
    except Exception as exc:
        result['http_status'] = getattr(exc, 'status_code', result['http_status'])
        result['exception_type'] = type(exc).__name__
        chain = []
        cause = exc.__cause__
        while cause is not None and len(chain) < 5:
            chain.append(type(cause).__name__)
            cause = cause.__cause__
        result['exception_causes'] = chain
    result.update(sent)
    result['elapsed_seconds'] = round(time.monotonic() - started, 3)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='deepseek')
    parser.add_argument('--reply', action='store_true', help='Check the real application Reply schema')
    parser.add_argument('--json-mode', action='store_true', help='Probe PT JSON object response format')
    parser.add_argument('--windows-user-key', action='store_true', help='Read LLM_API_KEY from Windows User env in memory only')
    args = parser.parse_args()
    settings = APISettings.from_env('pt')
    key = settings.api_key
    if args.windows_user_key:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as registry:
            key = winreg.QueryValueEx(registry, 'LLM_API_KEY')[0]
    settings = replace(settings, model=args.model, api_key=key)
    settings.validate()
    report = asyncio.run(smoke(settings, reply_schema=args.reply, json_mode=args.json_mode))
    print(json.dumps(report, ensure_ascii=False))
    success = (report.get('http_status') == 200 and report.get('exception_type') is None
               and (report.get('runtime_accepts_response') if args.reply else report.get('minimal_ok')))
    raise SystemExit(0 if success else 1)
