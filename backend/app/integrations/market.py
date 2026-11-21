"""Instrument identity and search ranking shared by agent tools."""
import re

KINDS = {"share": "INSTRUMENT_TYPE_SHARE", "bond": "INSTRUMENT_TYPE_BOND",
         "etf": "INSTRUMENT_TYPE_ETF", "future": "INSTRUMENT_TYPE_FUTURES",
         "currency": "INSTRUMENT_TYPE_CURRENCY"}

def query_term(text: str) -> str:
    term = text.strip()
    term = re.sub(r"^(?:найди(?:те)?|покажи(?:те)?|открой(?:те)?|хочу|интересует)\s+", "", term, flags=re.I)
    term = re.sub(r"^(?:акци[яиюй]|облигаци[яиюй]|бумаг[ауи]|фонд)\s+", "", term, flags=re.I)
    aliases = {"сбер": "SBER", "сбера": "SBER", "сбербанк": "SBER", "сбербанка": "SBER", "сбер преф": "SBERP", "сбербанк преф": "SBERP",
               "газпром": "GAZP", "лукойл": "LKOH", "т технологии": "T"}
    return aliases.get(term.lower(), term)

def rank_instruments(rows: list, query: str, kind: str) -> list[dict]:
    expected = KINDS.get(kind)
    rows = [b for b in rows if b.get("uid") and b.get("instrumentKind") in KINDS.values()
            and (not expected or b.get("instrumentKind") == expected)]
    reverse = {v: k for k, v in KINDS.items()}
    def score(b):
        ticker = b.get("ticker", "").upper()
        return (ticker == query.upper(), b.get("isin", "").upper() == query.upper(),
                {"INSTRUMENT_TYPE_SHARE": 5, "INSTRUMENT_TYPE_BOND": 4, "INSTRUMENT_TYPE_ETF": 3,
                 "INSTRUMENT_TYPE_CURRENCY": 2, "INSTRUMENT_TYPE_FUTURES": 1}.get(b.get("instrumentKind"), 0),
                b.get("classCode") in ("TQBR", "TQOB", "TQCB", "TQTF", "CETS", "SPBFUT"),
                bool(b.get("apiTradeAvailableFlag")), ticker.startswith(query.upper()))
    ranked = sorted(rows, key=score, reverse=True)
    seen, results = set(), []
    for b in ranked:
        if b["uid"] in seen:
            continue
        seen.add(b["uid"])
        results.append({"id": b["uid"], "name": b.get("name", b["uid"]), "ticker": b.get("ticker"),
                        "isin": b.get("isin"), "class_code": b.get("classCode"),
                        "kind": reverse[b["instrumentKind"]], "origin": "tinvest_sandbox",
                        "exact_match": b.get("ticker", "").upper() == query.upper(),
                        "trade_available": bool(b.get("apiTradeAvailableFlag"))})
    groups = {}
    for item in results:
        identity = (item["kind"], item.get("isin") or item["ticker"])
        if identity not in groups:
            groups[identity] = {**item, "alternatives": []}
        else:
            groups[identity]["alternatives"].append(item)
    return list(groups.values())[:40]

def instrument_key(instrument):
    return f"{instrument['ticker']}_{instrument['class_code']}"
