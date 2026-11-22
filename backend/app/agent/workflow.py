"""Deterministic data stages for an explicitly named futures contract."""
from dataclasses import dataclass
import re

from .models import ToolRequest

FUTURE=re.compile(r'(?<!\w)([A-Za-z]{1,6}[FGHJKMNQUVXZ]\d{1,2})(?!\w)',re.I)
EDUCATION=re.compile(r'^\s*(?:что (?:такое|значит|означает)|объясни(?:те)?|расскажи(?:те)? (?:что|про термин))',re.I)


@dataclass(frozen=True)
class Route:
    education: bool
    ticker: str|None
    class_code: str|None
    needs_data: bool
    smalltalk: bool=False


def route_for(messages):
    latest=messages[-1] if messages else ''
    if EDUCATION.search(latest):return Route(True,None,None,False)
    if re.fullmatch(r'\s*(?:спасибо|благодарю|понятно|ясно|ок|здравствуйте|привет)[.! ]*\s*',latest,re.I):
        return Route(False,None,None,False,True)
    ticker=None
    for text in reversed(messages):
        tickers={m.group(1).upper() for m in FUTURE.finditer(text)}
        if tickers:
            ticker=next(iter(tickers)) if len(tickers)==1 else None
            break
    combined='\n'.join(messages)
    needs_data=bool(re.search(r'котиров|спецификац|\bцен[ауы]?\b|\bquote\b|\bspec\b|капитал|стоп|риск\s*\d',latest,re.I))
    return Route(False,ticker,'SPBFUT' if re.search(r'\bSPBFUT\b',combined,re.I) else None,needs_data)


def selected_instrument(route,known):
    matches=[i for i in known.values() if i['kind']=='future' and i.get('ticker','').upper()==route.ticker
             and (route.class_code is None or i.get('class_code')==route.class_code)]
    return matches[0] if len(matches)==1 else None


def next_required(route,known,attempted):
    if route.education or not route.ticker or not route.needs_data:return None
    selected=selected_instrument(route,known)
    if not selected:
        if ('search',route.ticker) in attempted:return None
        return ToolRequest(kind='search',query=route.ticker,instrument_id=None,question=None)
    for kind in ('spec','quote'):
        if (kind,selected['id']) not in attempted:
            return ToolRequest(kind=kind,query=None,instrument_id=selected['id'],question=None)
    return None


def request_key(request):
    if request.kind=='web':return (request.kind,request.instrument_id,request.question)
    return (request.kind,(request.query or '').upper() if request.kind=='search' else request.instrument_id)
