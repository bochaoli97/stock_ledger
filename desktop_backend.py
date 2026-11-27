"""Headless desktop service. Reuses the existing Decimal ledger and SQLite schema.

The Electron main process owns this process and communicates over JSON lines on
stdin/stdout. SQLite stays on one thread; slow network requests use workers.
Run with an explicit --db path. This module has no Qt dependency.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import queue
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import i18n
from csv_export import finance_tables, stock_tables, write_tables
from finance import (EXPENSE, INCOME, FinMonth, entry_from_text, finance_rows,
                     month_of, month_range, parse_month, period_months, summarize)
from ledger import (PERIODS, TXN_TYPES, TYPE_FIELDS, ZERO, Txn, combine_results,
                    combine_series, fmt_money, fmt_pct, fmt_price, fmt_qty,
                    parse_date, period_range, replay, to_decimal, today,
                    valuation, value_series)
from quotes import fetch_quotes, fetch_stock_history, is_live, match_local, search_symbols
from storage import Storage, daily_backup

ALL_ACCOUNTS = -1
RANGES = {"1D": ("1d", "5m"), "1W": ("5d", "30m"), "1M": ("1mo", "1d"),
          "3M": ("3mo", "1d"), "YTD": ("ytd", "1d"), "1Y": ("1y", "1d"),
          "ALL": ("max", "1mo")}
STOCK_RANGES = {**RANGES, "5Y": ("5y", "1wk"), "10Y": ("10y", "1wk"), "ALL": ("max", "1d")}


def usd(value, sign=False):
    value = Decimal(str(value))
    return ("-$" if value < 0 else "+$" if sign and value > 0 else "$") + fmt_money(abs(value))


def encode(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


class ServiceError(ValueError):
    def __init__(self, message, code="INVALID_INPUT", details=None):
        super().__init__(message)
        self.code, self.details = code, details


class LedgerService:
    def __init__(self, path: Path, *, backup=True):
        path = Path(path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        if backup:
            daily_backup(path, path.parent / "backups")
        self.db = Storage(path)
        i18n.set_language(self.db.get_setting("language", "zh"))
        self.quotes = {}
        self.quote_times = {}
        self.history = {}
        self.updated_at = None

    def close(self):
        self.db.close()

    @property
    def live(self):
        return self.db.get_setting("live_prices", "1") == "1"

    def accounts(self):
        return [dict(row) for row in self.db.list_accounts()]

    def account_id(self, value=None, *, single=False):
        accounts = self.accounts()
        ids = {a["id"] for a in accounts}
        if value is None:
            last = self.db.get_setting("last_account", "")
            value = -1 if last == "all" else int(last) if last.isdigit() else None
            if value not in ids and value != -1:
                value = accounts[0]["id"] if accounts else None
        if value is not None:
            value = int(value)
        if value == ALL_ACCOUNTS and not single:
            return value
        if value not in ids:
            if not accounts and not single:
                return None
            raise ServiceError("Please select an existing account", "ACCOUNT_REQUIRED")
        return value

    def result(self, account_id):
        if account_id == ALL_ACCOUNTS:
            return combine_results(replay(self.db.list_txns(a["id"])) for a in self.accounts())
        return replay(self.db.list_txns(account_id)) if account_id is not None else replay([])

    def prices(self):
        return {s: p for s, (p, _) in self.db.get_prices().items()}

    def day_change(self, result):
        change = base = ZERO
        for p in result.open_positions:
            q = self.quotes.get(p.symbol)
            if q and q.change is not None:
                change += p.quantity * q.change
                base += p.quantity * q.prev_close
        return change, base

    def summary(self, result, prices):
        v = valuation(result, prices)
        change, base = self.day_change(result)
        priced_cost = sum((p.cost for p in result.open_positions if p.symbol in prices), ZERO)
        return {"total": usd(result.cash + v.market_value), "cash": usd(result.cash),
                "market_value": usd(v.market_value), "cost": usd(result.total_cost),
                "unrealized": usd(v.unrealized, True) if priced_cost else "-",
                "unrealized_pct": fmt_pct(v.unrealized / priced_cost) if priced_cost else "-",
                "realized": usd(result.realized, True), "income": usd(result.dividends + result.interest),
                "net_deposits": usd(result.net_deposits), "fees": usd(result.fees),
                "dividends": usd(result.dividends), "interest": usd(result.interest),
                "change": usd(change, True), "change_pct": fmt_pct(change / base) if base else "",
                "missing": v.missing}

    def snapshot(self, params):
        aid = self.account_id(params.get("account_id"))
        result, prices, accounts = self.result(aid), self.prices(), self.accounts()
        names = {a["id"]: a["name"] for a in accounts}
        holdings = []
        for p in result.all_positions:
            price, q = prices.get(p.symbol), self.quotes.get(p.symbol)
            value = p.quantity * price if price is not None else p.cost
            gain = value - p.cost if price is not None else None
            holdings.append({"symbol": p.symbol, "name": q.name if q else p.symbol,
                             "quantity": fmt_qty(p.quantity), "quantity_raw": format(p.quantity, "f"),
                             "open": p.is_open, "avg_cost": usd(p.avg_cost), "cost": usd(p.cost),
                             "price": usd(price) if price is not None else "-",
                             "price_raw": format(price, "f") if price is not None else "",
                             "market_value": usd(value), "unrealized": usd(gain, True) if gain is not None else "-",
                             "unrealized_pct": fmt_pct(gain / p.cost) if gain is not None and p.cost else "",
                             "realized": usd(p.realized, True), "dividends": usd(p.dividends),
                             "change": usd(q.change, True) if q and q.change is not None else "-",
                             "change_pct": fmt_pct(q.change / q.prev_close) if q and q.change is not None else "",
                             "points": q.points if q else [], "live": bool(q and is_live(p.symbol, q))})
        txns = []
        for row in reversed(result.rows):
            txn = dataclasses.asdict(row.txn)
            txns.append({**txn, "type_label": row.txn.type_label, "account_name": names.get(row.txn.account_id, ""),
                         "quantity_text": fmt_qty(row.txn.quantity), "price_text": fmt_price(row.txn.price),
                         "amount_text": usd(row.txn.amount), "fee_text": usd(row.txn.fee),
                         "cash_change": usd(row.txn.cash_change, True), "cash_after": usd(row.cash_after),
                         "shares_after": fmt_qty(row.qty_after), "avg_after": usd(row.avg_cost_after),
                         "source_shares_after": fmt_qty(row.source_after[0]) if row.source_after else None,
                         "source_avg_after": usd(row.source_after[1]) if row.source_after else None,
                         "realized": usd(row.realized, True)})
        for a in accounts:
            a["summary"] = self.summary(self.result(a["id"]), prices)
        periods = [{"code": code, "label": i18n.tr(label), "bounds": period_range(code)}
                   for code, label in PERIODS.items()]
        years = sorted({row.txn.date[:4] for row in result.rows}, reverse=True)
        periods.extend({"code": y, "label": y, "bounds": period_range(y)} for y in years)
        finance_balance = None
        if self.db.finance_enabled():
            rows = finance_rows(self.db.list_finance_months(), self.db.list_finance_categories())
            if rows:
                total = result.cash + valuation(result, prices).market_value
                finance_balance = {"month": rows[-1].month.month, "balance": usd(rows[-1].ending),
                                   "net_worth": usd(total + rows[-1].ending)}
        return {"account_id": aid, "accounts": accounts, "summary": self.summary(result, prices),
                "holdings": holdings, "transactions": txns, "periods": periods,
                "settings": {"theme": self.db.get_setting("theme", "dark"),
                             "language": i18n.language(), "text_size": self.db.get_setting("text_size", "Large"),
                             "live": self.live, "finance": self.db.finance_enabled()},
                "finance_balance": finance_balance, "updated_at": self.updated_at, "today": today(),
                "transaction_types": [{"code": k, "label": i18n.tr(v), "fields": TYPE_FIELDS[k]}
                                      for k, v in TXN_TYPES.items()], "translations": i18n.ZH}

    def parse_txn(self, raw, aid, txn_id=None):
        t = Txn(date=parse_date(raw.get("date", "")), type=str(raw.get("type", "")),
                symbol=str(raw.get("symbol", "")), symbol2=str(raw.get("symbol2", "")),
                note=str(raw.get("note", "")), account_id=aid, id=txn_id,
                **{field: to_decimal(raw.get(field, "")) for field in ("quantity", "price", "fee", "amount")}).normalized()
        t.validate()
        return t

    def save_account(self, params):
        name = str(params.get("name", "")).strip()
        if not name:
            raise ServiceError("Please enter an account name")
        broker, note = str(params.get("broker", "")).strip(), str(params.get("note", "")).strip()
        if params.get("id") is not None:
            aid = self.account_id(params["id"], single=True)
            self.db.update_account(aid, name, broker, note)
        else:
            opening = []
            start = parse_date(params.get("date") or today())
            cash = to_decimal(params.get("cash", ""))
            if cash:
                opening.append(Txn(date=start, type="DEPOSIT" if cash > 0 else "WITHDRAW",
                                   amount=abs(cash), note=i18n.tr("Opening cash")))
            for pos in params.get("positions", []):
                opening.append(self.parse_txn({**pos, "date": start, "type": "SHARES_IN",
                                                "note": i18n.tr("Opening position")}, None))
            replay(opening)
            aid = self.db.create_account(name, broker, note, opening)
        self.db.set_setting("last_account", str(aid))
        return self.snapshot({"account_id": aid})

    def save_transaction(self, params, *, preview=False):
        aid = self.account_id(params.get("account_id"), single=True)
        existing = self.db.list_txns(aid)
        txn_id = int(params["id"]) if params.get("id") is not None else None
        if txn_id is not None and not any(t.id == txn_id for t in existing):
            raise ServiceError("Transaction not found", "NOT_FOUND")
        t = self.parse_txn(params, aid, txn_id)
        result = replay([x for x in existing if x.id != txn_id] + [t])
        index = next(i for i, row in enumerate(result.rows) if row.txn is t)
        low = min(row.cash_after for row in result.rows[index:])
        negative = low < 0 and t.cash_change < 0
        if preview:
            row = result.rows[index]
            return {"cash_change": usd(t.cash_change, True), "cash_after": usd(row.cash_after),
                    "shares_after": fmt_qty(row.qty_after), "avg_after": usd(row.avg_cost_after),
                    "negative_cash": negative, "lowest": usd(low)}
        if negative and params.get("allow_negative_cash") is not True:
            raise ServiceError(i18n.tr("Insufficient Cash"), "NEGATIVE_CASH", {"lowest": usd(low)})
        self.db.update_txn(t) if txn_id is not None else self.db.add_txn(t)
        return self.snapshot({"account_id": aid})

    def save_settings(self, params):
        choices = {"theme": {"dark", "light"}, "language": {"en", "zh"},
                   "text_size": {"Small", "Standard", "Large", "Extra large"}}
        for key, allowed in choices.items():
            if key in params and params[key] not in allowed:
                raise ServiceError(f"Invalid {key}")
        for key in choices:
            if key in params:
                self.db.set_setting(key, params[key])
        i18n.set_language(self.db.get_setting("language", "zh"))
        if "live" in params:
            self.db.set_setting("live_prices", "1" if params["live"] else "0")
            if not params["live"]:
                self.quotes.clear()
        if "finance" in params:
            self.db.set_finance_enabled(bool(params["finance"]))
            if params["finance"]:
                self.db.seed_finance_defaults([i18n.tr("Salary"), i18n.tr("Other income")],
                                              [i18n.tr("Housing"), i18n.tr("Food"), i18n.tr("Other expenses")])
        i18n.set_language(self.db.get_setting("language", "zh"))
        return self.snapshot(params)

    def finance_snapshot(self, params):
        if not self.db.finance_enabled():
            raise ServiceError("Finance is disabled")
        categories = self.db.list_finance_categories()
        rows = finance_rows(self.db.list_finance_months(), categories)
        code = str(params.get("period", "ALL"))
        first, last = month_range(code, month_of(today()))
        if code == "CUSTOM":
            first = parse_month(params["first"]) if params.get("first") else None
            last = parse_month(params["last"]) if params.get("last") else None
            if first and last and first > last:
                raise ServiceError("Start month must precede end month")
        chosen = period_months(rows, first, last)
        total = summarize(chosen)
        return {"categories": [dataclasses.asdict(c) for c in categories],
                "usage": self.db.finance_entry_counts(),
                "months": [{"month": r.month.month, "opening_raw": str(r.month.opening) if r.month.opening is not None else "",
                            "opening": usd(r.opening), "income": usd(r.income), "expenses": usd(r.expenses),
                            "ending": usd(r.ending), "net": usd(r.net, True),
                            "entries": {cid: {"amount": usd(e.amount), "raw": e.expr or str(e.amount),
                                              "comment": e.comment} for cid, e in r.month.entries.items()}}
                           for r in chosen],
                "all_months": [r.month.month for r in rows],
                "summary": {"income": usd(total.income), "expenses": usd(total.expenses),
                            "net": usd(total.net, True), "ending": usd(total.ending) if total.ending is not None else "-",
                            "categories": {cid: usd(v) for cid, v in total.by_category.items()}}}

    def save_month(self, params):
        if not self.db.finance_enabled():
            raise ServiceError("Finance is disabled")
        month = parse_month(params.get("month", ""))
        original = params.get("original_month")
        if original and parse_month(original) != month:
            raise ServiceError("An existing month's date cannot be changed")
        if not original and any(m.month == month for m in self.db.list_finance_months()):
            raise ServiceError("This month already exists")
        opening = to_decimal(params["opening"]) if str(params.get("opening", "")).strip() else None
        ids = {c.id for c in self.db.list_finance_categories()}
        entries = {}
        for cid, value in params.get("entries", {}).items():
            if int(cid) not in ids:
                raise ServiceError("Category not found")
            entries[int(cid)] = entry_from_text(str(value.get("raw", "")), str(value.get("comment", "")))
        self.db.save_finance_month(FinMonth(month, opening, entries))
        return self.finance_snapshot({})

    def save_categories(self, params):
        if not self.db.finance_enabled():
            raise ServiceError("Finance is disabled")
        existing = {c.id: c for c in self.db.list_finance_categories()}
        groups = {}
        for kind in (INCOME, EXPENSE):
            items, names, seen = [], set(), set()
            for item in params.get(kind, []):
                cid, name = item.get("id"), str(item.get("name", "")).strip()
                if not name or name in names or (cid is not None and cid in seen):
                    raise ServiceError("Category names must be nonempty and unique")
                if cid is not None and (cid not in existing or existing[cid].kind != kind):
                    raise ServiceError("Category not found")
                names.add(name)
                seen.add(cid)
                items.append((cid, name))
            groups[kind] = items
        for kind, items in groups.items():
            self.db.set_finance_categories(kind, items)
        return self.finance_snapshot({})

    def history_key(self, params):
        aid = self.account_id(params.get("account_id"))
        symbol = str(params.get("symbol", "")).upper()
        rng = params.get("range", "1D")
        ranges = STOCK_RANGES if symbol else RANGES
        if rng not in ranges:
            raise ServiceError("Unknown chart range")
        period, interval = ranges[rng]
        if symbol:
            return period, interval, (symbol,)

        result = self.result(aid)
        if rng == "ALL" and result.rows:
            first = result.rows[0].txn.date
            days = (date.today() - date.fromisoformat(first)).days
            period, interval = next(((r, i) for d, r, i in
                                     ((90, "3mo", "1d"), (365, "1y", "1d"), (730, "2y", "1d"),
                                      (1825, "5y", "1wk")) if days <= d), (period, interval))
        return period, interval, tuple(sorted(result.positions))

    def chart(self, params):
        aid = self.account_id(params.get("account_id"))
        symbol, rng = str(params.get("symbol", "")).upper(), params.get("range", "1D")
        prices = self.prices()
        key = self.history_key(params)
        data = self.quotes if rng == "1D" else self.history.get(key, (0, {}))[1]
        baseline, change = None, None
        points, live = [], False
        if symbol:
            current = prices.get(symbol)
            q, hq = self.quotes.get(symbol), data.get(symbol)
            if self.live and hq:
                points = [(t, c, 0.) for t, c in hq.points]
            if rng == "1D" and q:
                baseline = float(q.prev_close) if q.prev_close else None
                live = is_live(symbol, q)
            if rng in {"1D", "1W"} and len(points) > 1 and current is not None:
                points.append((int(time.time()), float(current), 0.))
        else:
            result = self.result(aid)
            current = result.cash + valuation(result, prices).market_value
            series = {s: q.points for s, q in data.items() if s in result.positions and q.points}
            if self.live and series:
                if aid == ALL_ACCOUNTS:
                    values = combine_series([value_series(self.result(a["id"]).rows, series, prices) for a in self.accounts()])
                else:
                    values = value_series(result.rows, series, prices)
                points = [(p.time, p.value, p.net_deposits) for p in values]
                points.append((int(time.time()), float(current), float(result.net_deposits)))
            if rng == "1D":
                day, _ = self.day_change(result)
                baseline, change = float(current - day), float(day)
                live = any(q and is_live(p.symbol, q) for p in result.open_positions for q in [self.quotes.get(p.symbol)])
        has_return = baseline is not None or len(points) > 1
        formatted = []
        for ts, value, net in points:
            base = baseline if baseline is not None else points[0][1] + net - points[0][2]
            delta = value - base
            formatted.append({"time": ts, "value": value, "text": usd(value),
                              "change": usd(delta, True) if has_return else "",
                              "percent": fmt_pct(Decimal(str(delta / base))) if has_return and base else ""})
        if change is None and has_return and points:
            change = points[-1][1] - (baseline if baseline is not None else points[0][1] + points[-1][2] - points[0][2])
        base = baseline if baseline is not None else (points[0][1] + points[-1][2] - points[0][2] if points else 0)
        return {"points": formatted, "baseline": baseline, "slots": 79 if rng == "1D" else 0,
                "live": live and self.live and rng == "1D",
                "value": usd(current) if current is not None and aid is not None else "-",
                "change": usd(change, True) if change is not None else "",
                "percent": fmt_pct(Decimal(str(change / base))) if change is not None and base else "",
                "message": i18n.tr("Turn on Live prices to see the chart") if not self.live else
                           i18n.tr("No chart data") if not points else
                           i18n.tr("Only one price point is available") if len(points) == 1 else ""}

    def local_suggestions(self, query):
        result = self.result(ALL_ACCOUNTS)
        names = {p.symbol: self.quotes[p.symbol].name if p.symbol in self.quotes else p.symbol for p in result.open_positions}
        return [{"symbol": s, "name": names[s], "holding": fmt_qty(result.positions[s].quantity)}
                for s in match_local(query, names)]

    def prepare_network(self, method, params):
        """Capture request state on the SQLite thread; only the returned job runs elsewhere."""
        if method == "quotes.refresh":
            if not self.live:
                return None
            result = self.result(self.account_id(params.get("account_id")))
            symbols = [p.symbol for p in result.open_positions]
            if not symbols:
                return None
            def finish(got):
                if self.live:
                    changed = {}
                    prices = self.prices()
                    for symbol, quote in got.items():
                        timestamp = quote.time.timestamp() if quote.time else None
                        previous = self.quote_times.get(symbol)
                        if previous is not None and (timestamp is None or timestamp < previous):
                            continue
                        if timestamp is not None:
                            self.quote_times[symbol] = timestamp
                        self.quotes[symbol] = quote
                        if prices.get(symbol) != quote.price:
                            changed[symbol] = quote.price
                    self.db.set_prices(changed)
                    self.updated_at = datetime.now().strftime("%H:%M:%S")
                return self.snapshot(params)
            return lambda: fetch_quotes(symbols), finish
        if method == "chart" and self.live and params.get("range", "1D") != "1D":
            key = self.history_key(params)
            period, interval, symbols = key
            fetched, _ = self.history.get(key, (0, None))
            if time.time() - fetched > 600 and symbols:
                def finish(got):
                    self.history[key] = (time.time(), got)
                    return self.chart(params)
                if params.get("symbol"):
                    return lambda: fetch_stock_history(symbols[0], period, interval), finish
                return lambda: fetch_quotes(symbols, period, interval), finish
        if method == "symbols.search" and self.live and str(params.get("query", "")).strip():
            def finish(got):
                items = self.local_suggestions(params["query"])
                seen = {item["symbol"] for item in items}
                return items + [{"symbol": s.symbol, "name": s.name, "holding": ""} for s in got if s.symbol not in seen]
            return lambda: search_symbols(str(params["query"])[:120]), finish
        return None

    def dispatch(self, method, params):
        if method == "snapshot" or method == "quotes.refresh":
            return self.snapshot(params)
        if method == "account.select":
            aid = self.account_id(params.get("account_id"))
            self.db.set_setting("last_account", "all" if aid == -1 else str(aid))
            return self.snapshot({"account_id": aid})
        if method == "account.save":
            return self.save_account(params)
        if method == "account.delete":
            aid = self.account_id(params.get("account_id"), single=True)
            self.db.delete_account(aid)
            self.db.set_setting("last_account", "")
            return self.snapshot({})
        if method in ("transaction.save", "transaction.preview"):
            return self.save_transaction(params, preview=method.endswith("preview"))
        if method == "transaction.delete":
            aid = self.account_id(params.get("account_id"), single=True)
            txns = self.db.list_txns(aid)
            tid = int(params["id"])
            if not any(t.id == tid for t in txns):
                raise ServiceError("Transaction not found", "NOT_FOUND")
            replay(t for t in txns if t.id != tid)
            self.db.delete_txn(tid)
            return self.snapshot({"account_id": aid})
        if method == "prices.save":
            prices = {}
            for symbol, text in params.get("prices", {}).items():
                symbol = symbol.strip().upper()
                if not symbol:
                    raise ServiceError("Please enter a symbol")
                value = to_decimal(text) if str(text).strip() else None
                if value is not None and value < 0:
                    raise ServiceError("Price cannot be negative")
                prices[symbol] = value
            self.db.set_prices(prices)
            for symbol in prices:
                self.quotes.pop(symbol, None)
            return self.snapshot(params)
        if method == "settings.save":
            return self.save_settings(params)
        if method == "chart":
            return self.chart(params)
        if method == "symbols.search":
            return self.local_suggestions(str(params.get("query", "")))
        if method == "finance.snapshot":
            return self.finance_snapshot(params)
        if method == "finance.month.save":
            return self.save_month(params)
        if method == "finance.month.delete":
            self.db.delete_finance_month(parse_month(params["month"]))
            return self.finance_snapshot({})
        if method == "finance.categories.save":
            return self.save_categories(params)
        if method == "backup":
            path = Path(params["path"]).resolve()
            if path == self.db.path:
                raise ServiceError("Choose a different backup file")
            self.db.backup_to(path)
            return str(path)
        if method == "export":
            kind = params.get("kind", "stock")
            if kind not in ("stock", "finance"):
                raise ServiceError("Invalid export type")
            period = str(params.get("period", "ALL"))
            if period not in ("ALL", "CUSTOM", "3M", "6M", "1Y") and not (
                    kind == "stock" and period == "1M") and not re.fullmatch(r"[0-9]{4}", period):
                raise ServiceError("Invalid export period")
            if period == "CUSTOM":
                parse = parse_month if kind == "finance" else parse_date
                first = parse(params["first"]) if params.get("first") else None
                last = parse(params["last"]) if params.get("last") else None
            elif kind == "finance":
                first, last = month_range(period, month_of(today()))
            else:
                first, last = period_range(period)
            if first and last and first > last:
                raise ServiceError("Start must precede end")
            if kind == "finance":
                cats = self.db.list_finance_categories()
                rows = finance_rows(self.db.list_finance_months(), cats)
                tables, base = finance_tables(period_months(rows, first, last), cats), "finance"
            else:
                aid = self.account_id(params.get("account_id"), single=True)
                account = next(a for a in self.accounts() if a["id"] == aid)
                base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", account["name"]).strip(". ") or "account"
                # Replay the complete history through the end date before filtering activity.
                # A sale in the selected period can depend on purchases from earlier periods.
                result = replay(t for t in self.db.list_txns(aid) if not last or t.date <= last)
                as_of = last or today()
                prices = self.prices() if as_of == today() else {}
                tables = stock_tables(account["name"], result, prices, as_of, first, last)
            if first or last:
                base += f"_{first or 'start'}_to_{last or 'latest'}"
            return [str(p) for p in write_tables(params["folder"], base, today(), tables)]
        raise ServiceError("Unknown service method", "METHOD_NOT_FOUND")


def serve(path):
    # Redirected Windows pipes otherwise inherit the local ANSI code page.
    # The JSON-lines protocol is UTF-8 regardless of the desktop locale.
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    service = LedgerService(path)
    messages = queue.Queue()
    workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ledger-network")

    def read():
        for line in sys.stdin:
            messages.put(("request", line))
        messages.put(("eof", None))

    def reply(rid, result=None, error=None):
        payload = {"id": rid}
        if error is None:
            payload["result"] = result
        else:
            payload["error"] = {"message": str(error), "code": getattr(error, "code", "SERVICE_ERROR"),
                                "details": getattr(error, "details", None)}
        sys.stdout.write(json.dumps(payload, default=encode, ensure_ascii=False, allow_nan=False) + "\n")
        sys.stdout.flush()

    threading.Thread(target=read, daemon=True).start()
    try:
        while True:
            kind, item = messages.get()
            if kind == "eof":
                break
            rid = None
            try:
                if kind == "finish":
                    rid, finish, future = item
                    reply(rid, finish(future.result()))
                    continue
                request = json.loads(item)
                if not isinstance(request, dict) or not isinstance(request.get("method"), str):
                    raise ServiceError("Invalid request", "BAD_REQUEST")
                rid = request.get("id")
                method, params = request["method"], request.get("params", {})
                if not isinstance(params, dict):
                    raise ServiceError("Invalid parameters", "BAD_REQUEST")
                network = service.prepare_network(method, params)
                if network:
                    job, finish = network
                    future = workers.submit(job)
                    future.add_done_callback(lambda f, rid=rid, finish=finish: messages.put(("finish", (rid, finish, f))))
                else:
                    reply(rid, service.dispatch(method, params))
            except (ValueError, KeyError, TypeError, sqlite3.Error, OSError, ArithmeticError) as error:
                reply(rid, error=error)
            except Exception as error:
                print(f"Desktop service error: {type(error).__name__}", file=sys.stderr)
                reply(rid, error=ServiceError("The request could not be completed", "INTERNAL_ERROR"))
    finally:
        workers.shutdown(wait=False, cancel_futures=True)
        service.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    serve(parser.parse_args().db)
