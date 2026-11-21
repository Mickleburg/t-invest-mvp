"""Public web research with isolated Chromium; retrieved text is evidence to review, not a trading signal."""
import asyncio
import base64
import os
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from playwright.async_api import async_playwright

PRIMARY_DOMAINS = ("sberbank.com", "sberbank.ru", "moex.com", "e-disclosure.ru", "tbank.ru",
    "gazprom.ru", "lukoil.ru", "rosneft.ru", "interrao.ru", "t-technologies.ru",
    "tinkoff-group.com", "alrosa.ru", "nornickel.ru", "severstal.com", "magnit.com", "x5.ru",
    "kremlin.ru", "mid.ru", "president.gov.ua", "mfa.gov.ua", "un.org", "osce.org", "tass.ru", "interfax.ru", "reuters.com", "apnews.com",
    "eia.gov", "iea.org", "cbr.ru")
SEARCH_DOMAINS = ("bing.com", "duckduckgo.com")


def allowed_url(url: str, search=False) -> bool:
    parsed = urlparse(url)
    domains = PRIMARY_DOMAINS + (SEARCH_DOMAINS if search else ())
    try:
        port = parsed.port
    except ValueError:
        return False
    return parsed.scheme == "https" and not parsed.username and port in (None, 443) and any(
        parsed.hostname == d or (parsed.hostname or "").endswith("." + d) for d in domains)


def unwrap_url(raw):
    try:
        parsed = urlparse(raw)
        args = parse_qs(parsed.query)
        if (parsed.hostname or "").endswith("bing.com") and args.get("u", [""])[0].startswith("a1"):
            value = args["u"][0][2:]
            return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        if args.get("uddg"):
            return unquote(args["uddg"][0])
    except (ValueError, UnicodeError):
        return ""
    return raw


def build_query(instrument: dict, question: str, scope: str = "instrument") -> str:
    identity = " ".join(str(instrument.get(k) or "") for k in ("name", "ticker", "isin"))
    if scope not in ("instrument", "event"):
        raise ValueError("Неизвестная область исследования")
    query = (f"{identity} {question} официальный эмитент раскрытие" if scope == "instrument"
             else f"{question} официальное заявление дата")
    return query


def reference_urls(instrument: dict, question: str, scope: str) -> list[str]:
    """Fallback references must match the question, not displace search results."""
    if scope != 'instrument': return []
    topic=question.casefold(); urls=[]
    if instrument.get('ticker') in ('SBER','SBERP'):
        if 'дивиденд' in topic: urls.append('https://www.sberbank.com/investor-relations/dividends')
        if any(w in topic for w in ('отчет','отчёт','прибыл','результат')):
            urls.append('https://www.sberbank.com/investor-relations/groupresults')
    if instrument.get('kind')=='share' and any(w in topic for w in ('дивиденд','котиров','цен')):
        urls.append('https://www.tbank.ru/invest/stocks/'+quote_plus(instrument['ticker'])+'/')
    return urls


async def research(instrument: dict, question: str, scope: str = "instrument") -> dict:
    query = build_query(instrument, question, scope)
    sources, failures = [], []
    candidates = []
    references=reference_urls(instrument,question,scope)
    async with asyncio.timeout(85):
        async with async_playwright() as runtime:
            # No authenticated browser profile, cookies, T-Invest headers or model instructions.
            env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ("TOKEN", "API_KEY", "SECRET"))}
            browser = await runtime.chromium.launch(headless=True, env=env)
            context = await browser.new_context(accept_downloads=False, locale="ru-RU")
            async def route(request_route):
                request = request_route.request
                if request.method != "GET" or request.resource_type in ("image", "media", "font") or not allowed_url(request.url, search=True):
                    await request_route.abort()
                else:
                    await request_route.continue_()
            await context.route("**/*", route)
            page = await context.new_page()
            try:
                for engine, url, selector in [
                    ("Bing", "https://www.bing.com/search?q=" + quote_plus(query), "li.b_algo h2 a"),
                    ("DuckDuckGo", "https://html.duckduckgo.com/html/?q=" + quote_plus(query), "a.result__a"),
                ]:
                    try:
                        response = await page.goto(url, wait_until="domcontentloaded", timeout=12000)
                        if response and response.status < 400:
                            links = await page.locator(selector).evaluate_all("nodes => nodes.map(n => n.href)")
                            candidates.extend(unwrap_url(link) for link in links)
                            if links:
                                break
                        failures.append({"source": engine, "status": "search_unavailable"})
                    except Exception:
                        failures.append({"source": engine, "status": "search_unavailable"})
                for url in dict.fromkeys([*candidates,*references]):
                    if not allowed_url(url):
                        continue
                    if len(sources) >= 4:
                        break
                    item = {"url": url, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                            "status": "unavailable", "verified_event": False}
                    try:
                        response = await page.goto(url, wait_until="domcontentloaded", timeout=10000)
                        item["http_status"] = response.status if response else None
                        if response and response.status < 400 and allowed_url(page.url):
                            item["title"] = (await page.title())[:250]
                            text = " ".join((await page.locator("body").inner_text(timeout=3000)).split())
                            lowered = text.casefold()
                            if any(marker in lowered for marker in ("support id", "access denied", "captcha", "доступ ограничен", "подтвердите, что вы человек", "проверка браузера")):
                                item.update(status="blocked", title=item["title"], excerpt="Сайт вернул страницу ограничения доступа. Содержимое документа не получено.")
                                sources.append(item)
                                continue
                            identity_terms = [str(instrument.get(k) or "").casefold() for k in ("ticker", "isin", "name")]
                            event_terms = [w.strip('.,;:!?«»()').casefold() for w in question.split() if len(w) > 5]
                            relevant = (any(term and term in text.casefold() for term in identity_terms) if scope == "instrument"
                                        else sum(term in text.casefold() for term in set(event_terms)) >= min(2, len(set(event_terms))) and bool(event_terms))
                            # Keep a short traceable excerpt, not a mirrored article.
                            terms = [w for w in ("дивиденд", "оферт", "купон", "ставк", "отчет", "отчёт") if w in question.lower()]
                            if not terms:
                                terms = [w for w in question.lower().split() if len(w) > 4]
                            focused = await page.locator('h2,h3,h4').evaluate_all("(nodes, terms) => { const heading = nodes.find(n => terms.some(t => n.innerText.toLowerCase().includes(t))); return heading ? (heading.closest('section') || heading.parentElement.parentElement).innerText : ''; }", terms)
                            if len(focused) > 100:
                                text = " ".join(focused.split())
                            pos = next((text.lower().find(w) for w in terms if w in text.lower()), 0)
                            item.update(status="retrieved" if relevant else "identity_unverified",
                                        excerpt=text[max(0, pos - 100):max(0, pos - 100) + 900],
                                        final_url=page.url, instrument_match=relevant,
                                        role=("broker_reference" if "tbank.ru" in urlparse(page.url).hostname else
                                              "media_report" if any((urlparse(page.url).hostname or "").endswith(d) for d in ("tass.ru", "interfax.ru", "reuters.com", "apnews.com")) else "primary_candidate"))
                    except Exception:
                        item["status"] = "unavailable"
                    sources.append(item)
            finally:
                await context.close()
                await browser.close()
    return {"query": query, "question": question, "scope": scope, "instrument_id": instrument["id"],
            "sources": sources, "search_failures": failures, "engine": "chromium",
            "conclusion": "Найденные страницы требуют проверки даты, выпуска и формулировки события. Они не изменяют детерминированный результат автоматически.",
            "retrieved_at": datetime.now(timezone.utc).isoformat()}
