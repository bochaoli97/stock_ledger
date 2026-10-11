"""
quotes.py -- live stock quotes and price history from Yahoo Finance (standard library only, no API key)

One HTTP request fetches up to BATCH symbols. Prices from Yahoo can be delayed by
a few seconds to 15 minutes depending on the exchange; US stocks are near real time.
Symbols Yahoo does not know are simply left out of the result.
Historical closes are split-adjusted by Yahoo (not dividend-adjusted).
Symbol search (for the type-ahead suggestions) uses Yahoo's search endpoint and only
sees what you type into the symbol box.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

SPARK_URL = "https://query1.finance.yahoo.com/v7/finance/spark"
SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
BATCH = 20  # symbols per request
TIMEOUT = 10  # seconds
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


@dataclass
class Quote:
    price: Decimal
    prev_close: Decimal | None  # previous session's close, for the day change
    time: datetime | None  # time of the last trade
    name: str = ""  # company / fund name
    points: list[tuple[int, float]] = field(default_factory=list)  # (unix time, close) for the chart

    @property
    def change(self) -> Decimal | None:
        return self.price - self.prev_close if self.prev_close else None


@dataclass
class Suggestion:
    """One symbol search result."""

    symbol: str  # as written in the ledger (BRK.B, not Yahoo's BRK-B)
    name: str
    exchange: str = ""  # e.g. NASDAQ, NYSE
    kind: str = ""  # e.g. Equity, ETF, Fund


class QuoteError(OSError):
    """Quotes could not be fetched (no internet, Yahoo unavailable, ...)."""


def yahoo_symbol(symbol: str) -> str:
    """Yahoo writes share classes with a dash: BRK.B -> BRK-B."""
    return symbol.replace(".", "-").replace("/", "-")


def ledger_symbol(ysym: str) -> str:
    """The reverse of yahoo_symbol: BRK-B -> BRK.B. Crypto keeps Yahoo's form (BTC-USD)."""
    return ysym if is_crypto(ysym) else ysym.replace("-", ".")


def is_crypto(symbol: str) -> bool:
    """Crypto is written as coin-USD, Yahoo's way: BTC-USD, ETH-USD. (Plain BTC is a stock-market ETF.)"""
    return symbol.upper().endswith("-USD")


def _dec(value) -> Decimal | None:
    if value is None:
        return None
    d = Decimal(str(value))
    return d if d.is_finite() and d > 0 else None


def parse_spark(data: dict) -> dict[str, Quote]:
    """Turn a spark API response into {yahoo symbol: Quote}."""
    out = {}
    for item in (data.get("spark") or {}).get("result") or []:
        for resp in item.get("response") or []:
            meta = resp.get("meta") or {}
            price = _dec(meta.get("regularMarketPrice"))
            if price is None:
                continue
            closes = ((resp.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
            points = [(t, float(c)) for t, c in zip(resp.get("timestamp") or [], closes) if c is not None]
            ts = meta.get("regularMarketTime")
            out[item["symbol"]] = Quote(
                price=price,
                prev_close=_dec(meta.get("chartPreviousClose") or meta.get("previousClose")),
                time=datetime.fromtimestamp(ts) if ts else None,
                name=meta.get("shortName") or meta.get("longName") or "",
                points=points,
            )
    return out


def fetch_quotes(symbols, rng: str = "1d", interval: str = "5m") -> dict[str, Quote]:
    """Return {symbol: Quote} for the symbols Yahoo knows. Raises QuoteError on network failure.

    The default (today, 5-minute bars) gives the live price plus today's intraday chart;
    pass another range/interval (e.g. "1y", "1d") to get price history instead.
    """
    by_yahoo = {yahoo_symbol(s): s for s in symbols}
    names = sorted(by_yahoo)
    result: dict[str, Quote] = {}
    for i in range(0, len(names), BATCH):
        query = urllib.parse.urlencode(
            {"symbols": ",".join(names[i:i + BATCH]), "range": rng, "interval": interval}
        )
        req = urllib.request.Request(f"{SPARK_URL}?{query}", headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.load(resp)
        except (OSError, ValueError) as e:
            raise QuoteError(str(e)) from e
        for ysym, quote in parse_spark(data).items():
            if ysym in by_yahoo:
                result[by_yahoo[ysym]] = quote
    return result


# ----------------------------------------------------------------------
# Symbol search (type-ahead suggestions)
# ----------------------------------------------------------------------
# Yahoo quote types worth suggesting; options, futures, currencies and indexes are left out
SEARCH_TYPES = {"EQUITY", "ETF", "MUTUALFUND", "MONEYMARKET", "MONEY_MARKET", "CRYPTOCURRENCY"}


def parse_search(data: dict) -> list[Suggestion]:
    """Turn a search API response into suggestions, in Yahoo's relevance order.

    Listings outside the US (symbols with an exchange suffix such as 0700.HK or APC.F) are skipped:
    live quotes only understand US-style symbols. Crypto is kept only when priced in dollars (BTC-USD,
    not BTC-EUR), since the ledger is in dollars.
    """
    out = []
    seen = set()
    for item in data.get("quotes") or []:
        ysym = item.get("symbol") or ""
        kind = item.get("quoteType")
        if not ysym or "." in ysym or kind not in SEARCH_TYPES:
            continue
        if kind == "CRYPTOCURRENCY" and not is_crypto(ysym):
            continue
        sym = ledger_symbol(ysym)
        if sym in seen:
            continue
        seen.add(sym)
        out.append(Suggestion(
            symbol=sym,
            name=item.get("shortname") or item.get("longname") or "",
            exchange="" if kind == "CRYPTOCURRENCY" else item.get("exchDisp") or "",  # Yahoo shows "CCC"
            kind=item.get("typeDisp") or "",
        ))
    return out


def search_symbols(query: str, limit: int = 8) -> list[Suggestion]:
    """Look up symbols by ticker or company name. Raises QuoteError on network failure."""
    query = query.strip()
    if not query:
        return []
    params = urllib.parse.urlencode(
        {"q": query, "quotesCount": limit + 4, "newsCount": 0, "listsCount": 0, "enableFuzzyQuery": "false"}
    )  # a few extra, since non-US listings are dropped
    req = urllib.request.Request(f"{SEARCH_URL}?{params}", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.load(resp)
    except (OSError, ValueError) as e:
        raise QuoteError(str(e)) from e
    return parse_search(data)[:limit]


def match_local(query: str, names: dict[str, str], limit: int = 8) -> list[str]:
    """Rank known symbols ({symbol: company name}) against what was typed, offline.

    Order: exact symbol, symbol prefix, a word in the name starting with the query, then the
    query anywhere in the symbol or name; alphabetical within each. An empty query lists them all.
    """
    q = query.strip().upper()
    if not q:
        return sorted(names)[:limit]
    ranked = []
    for sym, name in names.items():
        s, n = sym.upper(), (name or "").upper()
        if s == q:
            rank = 0
        elif s.startswith(q):
            rank = 1
        elif any(word.startswith(q) for word in n.replace(",", " ").split()):
            rank = 2
        elif q in s or q in n:
            rank = 3
        else:
            continue
        ranked.append((rank, s, sym))
    return [sym for *_, sym in sorted(ranked)][:limit]
