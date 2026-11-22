"""OpenAI-compatible transport; PT JSON mode plus local Reply validation."""
import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
import json
import logging
import os
import ssl
from urllib.parse import urlsplit

import certifi
import httpx
from openai import AsyncOpenAI

from backend.app.agent.models import Reply
from backend.app.agent.prompt import PROMPT
from backend.app.interfaces import ProviderUnavailable

log = logging.getLogger(__name__)


def api_http_client(settings, *, transport=None):
    """Keep CA verification and honour corporate NO_PROXY wildcard suffixes."""
    tls = ssl.create_default_context(cafile=certifi.where())
    tls.load_default_certs()  # Includes the Windows certificate store.
    if extra_ca := os.getenv('SSL_CERT_FILE'):
        tls.load_verify_locations(cafile=extra_ca)
    host = urlsplit(settings.base_url).hostname
    bypass = False
    if settings.provider == 'pt':
        for entry in (os.getenv('NO_PROXY') or os.getenv('no_proxy', '')).split(','):
            pattern = entry.strip().lower()
            suffix = pattern.removeprefix('*.').lstrip('.')
            if pattern == '*' or (suffix and (host == suffix or host.endswith('.' + suffix))):
                bypass = True
                break
    return httpx.AsyncClient(transport=transport, verify=tls, trust_env=not bypass,
                             follow_redirects=False)


@dataclass(repr=False)
class APISettings:
    provider: str
    base_url: str
    model: str
    api_key: str = field(repr=False)
    timeout: float = 45
    max_output_tokens: int = 2048
    max_input_bytes: int = 60000
    max_calls: int = 30
    max_reserved_tokens: int = 200000
    max_cost_usd: Decimal = Decimal('1')
    input_usd_per_million: Decimal = Decimal('0')
    output_usd_per_million: Decimal = Decimal('0')
    zero_cost_confirmed: bool = False
    temperature: float|None = 0.0
    disable_thinking: bool = False

    @classmethod
    def from_env(cls, provider):
        defaults = {'pt': ('https://api-llm.ptsecurity.com/v1', 'deepseek'),
                    'deepseek': ('https://api.deepseek.com', 'deepseek-flash')}
        base, model = defaults[provider]
        model=os.getenv('LLM_MODEL',model)
        thinking_default='1' if provider=='pt' and model in ('deepseek','qwen35-122b-a10b','positive-llm-qwen36') else '0'
        try:
            thinking_setting=os.getenv('LLM_DISABLE_THINKING') or thinking_default
            if thinking_setting not in ('0','1'):raise ValueError('Invalid thinking setting')
            settings = cls(provider, os.getenv('LLM_BASE_URL', base),
                           model, os.getenv('LLM_API_KEY', ''),
                           float(os.getenv('LLM_TIMEOUT_SECONDS', '45')),
                           int(os.getenv('LLM_MAX_OUTPUT_TOKENS', '2048')),
                           int(os.getenv('LLM_MAX_INPUT_BYTES', '60000')),
                           int(os.getenv('LLM_MAX_CALLS', '30')),
                           int(os.getenv('LLM_MAX_RESERVED_TOKENS', '200000')),
                           Decimal(os.getenv('LLM_MAX_COST_USD', '1')),
                           Decimal(os.getenv('LLM_INPUT_USD_PER_MILLION', '0')),
                           Decimal(os.getenv('LLM_OUTPUT_USD_PER_MILLION', '0')),
                           zero_cost_confirmed=os.getenv('LLM_ZERO_COST_CONFIRMED','0')=='1',
                           temperature=float(os.getenv('LLM_TEMPERATURE','0')) if os.getenv('LLM_TEMPERATURE','0') else None,
                           disable_thinking=thinking_setting=='1')
            settings.validate()
            return settings
        except Exception:
            raise ValueError('Invalid LLM API configuration') from None

    def validate(self):
        url = urlsplit(self.base_url)
        hosts = {'pt': 'api-llm.ptsecurity.com', 'deepseek': 'api.deepseek.com'}
        if (url.scheme != 'https' or url.hostname != hosts.get(self.provider)
                or url.username or url.password or url.query or url.fragment
                or url.port not in (None, 443) or url.path.rstrip('/') not in ('', '/v1')):
            raise ValueError('Invalid LLM endpoint')
        if not self.model or len(self.model) > 120:
            raise ValueError('Invalid model')
        if self.provider == 'pt' and self.model.startswith('pt/'):
            raise ValueError('Use the bare PT API model ID, without pt/')
        for value in (self.timeout, self.max_output_tokens, self.max_input_bytes,
                      self.max_calls, self.max_reserved_tokens, self.max_cost_usd):
            if not Decimal(str(value)).is_finite() or value <= 0:
                raise ValueError('Invalid limits')
        for value in (self.input_usd_per_million, self.output_usd_per_million):
            if not value.is_finite() or value < 0:
                raise ValueError('Invalid price')
        if self.temperature is not None and (not Decimal(str(self.temperature)).is_finite() or not 0<=self.temperature<=2):
            raise ValueError('Invalid temperature')


class ChatAPIProvider:
    def __init__(self, settings: APISettings, *, transport=None):
        settings.validate()
        self.settings = settings
        self.transport = transport
        self.calls = 0
        self.reserved_tokens = 0
        self.reserved_cost = Decimal('0')
        self.lock = asyncio.Lock()
        self.last_call = None

    @property
    def configured(self):
        s = self.settings
        priced=s.input_usd_per_million > 0 and s.output_usd_per_million > 0
        free_pt=(s.provider=='pt' and s.zero_cost_confirmed
                 and s.input_usd_per_million==0 and s.output_usd_per_million==0)
        return bool(s.api_key and (priced or free_pt))

    async def complete(self, context):
        s = self.settings
        if not self.configured:
            raise ProviderUnavailable('LLM key and explicit price ceilings are required')
        messages = [
            {'role': 'system', 'content': PROMPT + '\nJSON schema:\n' + json.dumps(Reply.model_json_schema(), ensure_ascii=False)},
            {'role': 'user', 'content': json.dumps(context, ensure_ascii=False)},
        ]
        # Reserve conservatively using UTF-8 bytes + envelope allowance, not a tokenizer claim.
        input_bytes = len(json.dumps(messages, ensure_ascii=False).encode('utf-8'))
        if input_bytes > s.max_input_bytes:
            raise ProviderUnavailable('LLM input limit exceeded')
        tokens = input_bytes + 1024 + s.max_output_tokens
        cost = ((input_bytes + 1024) * s.input_usd_per_million
                + s.max_output_tokens * s.output_usd_per_million) / Decimal(1000000)
        async with self.lock:
            if (self.calls >= s.max_calls or self.reserved_tokens + tokens > s.max_reserved_tokens
                    or self.reserved_cost + cost > s.max_cost_usd):
                raise ProviderUnavailable('LLM process budget exhausted')
            self.calls += 1
            self.reserved_tokens += tokens
            self.reserved_cost += cost
        # Failed calls keep their reservation. SDK retries disabled: one reservation, one request.
        phase='request'
        try:
            async with AsyncOpenAI(api_key=s.api_key, base_url=s.base_url, timeout=s.timeout,
                                   max_retries=0,
                                   http_client=api_http_client(s, transport=self.transport)) as client:
                async with asyncio.timeout(s.timeout):
                    result = await client.chat.completions.create(
                        model=s.model, messages=messages, max_tokens=s.max_output_tokens,
                        **({'temperature':s.temperature} if s.temperature is not None else {}),
                        **({'extra_body':{'chat_template_kwargs':{'enable_thinking':False}}} if s.provider=='pt' and s.disable_thinking else {}),
                        **({'response_format': {'type': 'json_object'}} if s.provider == 'pt' else {}))
            phase='completion'
            self.last_call={'requested_model':s.model,'response_model':result.model,
                'temperature':s.temperature,'disable_thinking':s.disable_thinking,
                'max_output_tokens':s.max_output_tokens,'finish_reason':result.choices[0].finish_reason if result.choices else None}
            if not result.choices or result.choices[0].finish_reason != 'stop':
                raise ValueError('Incomplete response')
            message = result.choices[0].message
            if message.tool_calls or not message.content or not message.content.strip():
                raise ValueError('Unsupported response')
            phase='reply_schema'
            reply = Reply.model_validate_json(message.content)
            return reply, reply.model_dump()
        except Exception as exc:
            # No provider body, exception text, headers, key or reasoning in logs/artifacts.
            log.warning('llm.api.failed provider=%s phase=%s type=%s', s.provider,phase,type(exc).__name__)
            raise ProviderUnavailable('LLM API unavailable or invalid response') from None
