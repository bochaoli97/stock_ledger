#!/usr/bin/env python3
"""Offline quote fixtures, loaded by a temporary Python startup hook in UI tests.

Production code has no fixture data or testing endpoints.
"""
import time
from datetime import datetime, timezone
from decimal import Decimal
from quotes import Quote, Suggestion


def fetch(symbols, rng="1d", interval="5m"):
    now = int(time.time())
    output = {}
    for symbol in symbols:
        price = 185.25 if symbol == "AAPL" else 420.50 if symbol == "MSFT" else 96000.12
        points = [(now - (59 - i) * 300, price * (1 + ((i % 7) - 3) * .0004) - (59 - i) * .025)
                  for i in range(60)]
        output[symbol] = Quote(Decimal(str(price)), Decimal(str(price - 2)),
                               datetime.fromtimestamp(now, timezone.utc),
                               {"AAPL": "Apple", "MSFT": "Microsoft"}.get(symbol, symbol), points)
    return output


def search(query, limit=8):
    return [Suggestion("AAPL", "Apple"), Suggestion("MSFT", "Microsoft")][:limit]
