"""
ledger.py -- core bookkeeping logic (independent of the UI and database, testable on its own)

Idea: the database stores only individual transactions. Cash balance, share counts,
cost basis and P/L are all recomputed (replayed) from the transactions from scratch.
So after editing or deleting any transaction, every number is recalculated correctly
and the books can never get out of sync.

Cost basis uses the average cost method (the same "Average Cost" Fidelity shows):
  Buy:  position cost += quantity x price + fee
  Sell: reduce position cost at the current average cost;
        realized P/L = sale proceeds - cost removed

All amounts and share counts are Decimal (exact decimal numbers) to avoid float error,
e.g. selling 0.1 + 0.2 shares never leaves 0.0000000001 shares behind.
"""

from __future__ import annotations

import calendar
from bisect import bisect_right
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from i18n import tr

ZERO = Decimal("0")

# Transaction types: internal code -> label shown in the UI (English; translated with tr() when shown)
TXN_TYPES: dict[str, str] = {
    "DEPOSIT": "Deposit",
    "WITHDRAW": "Withdrawal",
    "BUY": "Buy",
    "SELL": "Sell",
    "DIVIDEND": "Dividend",
    "INTEREST": "Interest",
    "FEE": "Fee",
    "SHARES_IN": "Shares In",
    "SHARES_OUT": "Shares Out",
    "SPLIT": "Split",
    "SYMBOL_CHANGE": "Symbol Change",
    "DISTRIBUTION": "Distribution",
}
TYPE_BY_LABEL = {label: code for code, label in TXN_TYPES.items()}

# Which fields each type requires
TYPE_FIELDS: dict[str, tuple[str, ...]] = {
    "DEPOSIT": ("amount",),
    "WITHDRAW": ("amount",),
    "INTEREST": ("amount",),
    "FEE": ("amount",),
    "DIVIDEND": ("symbol", "amount"),
    "BUY": ("symbol", "quantity", "price", "fee"),
    "SELL": ("symbol", "quantity", "price", "fee"),
    "SHARES_IN": ("symbol", "quantity", "price"),
    "SHARES_OUT": ("symbol", "quantity"),
    "SPLIT": ("symbol", "quantity"),
    "SYMBOL_CHANGE": ("symbol", "symbol2", "quantity"),  # old symbol -> new symbol; quantity = new shares
    # stock -> new security handed out on it (spin-off, warrants, rights); quantity = units received,
    # price = percent of the stock's cost basis that moves to the new security (0-100)
    "DISTRIBUTION": ("symbol", "symbol2", "quantity", "price"),
}

# Types tied to a specific stock
STOCK_TYPES = {"DIVIDEND", "BUY", "SELL", "SHARES_IN", "SHARES_OUT", "SPLIT", "SYMBOL_CHANGE", "DISTRIBUTION"}


class LedgerError(ValueError):
    """Transactions contradict each other, e.g. selling more shares than were held at the time."""


# ----------------------------------------------------------------------
# Input parsing
# ----------------------------------------------------------------------
def to_decimal(value) -> Decimal:
    """Convert user input to Decimal. Accepts forms like 1,234.5 / $12; blank means 0."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return ZERO
    text = str(value).strip().replace(",", "").replace("，", "").replace("$", "")
    if text == "":
        return ZERO
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise ValueError(tr('"{value}" is not a valid number', value=value)) from None
    if not number.is_finite():
        raise ValueError(tr('"{value}" is not a valid number', value=value))
    return number


def parse_date(text: str) -> str:
    """Accept 2026-09-30, 2026/9/30 or 20260930 and normalize to 2026-09-30."""
    text = (text or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(tr("Invalid date, please use a format like 2026-09-30"))


def today() -> str:
    return date.today().isoformat()


# Periods the transaction list can be narrowed to: code -> label (English; translated with tr() when shown).
# A calendar year is its own code ("2026"), and "CUSTOM" takes the two dates the user types.
PERIODS: dict[str, str] = {
    "ALL": "All time",
    "1M": "Past month",
    "3M": "Past 3 months",
    "6M": "Past 6 months",
    "1Y": "Past year",
}
PERIOD_MONTHS = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12}


def add_months(day: date, n: int) -> date:
    """`day` moved by n calendar months; a day the month does not have becomes its last (Mar 31 - 1 month = Feb 28)."""
    year, month = divmod(day.year * 12 + day.month - 1 + n, 12)
    month += 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def period_range(code: str, on: date | None = None) -> tuple[str | None, str | None]:
    """First and last date (YYYY-MM-DD, both included) of a period, counted back from `on` (default: today);
    None means no limit on that side."""
    on = on or date.today()
    if code in PERIOD_MONTHS:
        return add_months(on, -PERIOD_MONTHS[code]).isoformat(), on.isoformat()
    if len(code) == 4 and code.isdigit():
        return f"{code}-01-01", f"{code}-12-31"
    return None, None


# ----------------------------------------------------------------------
# Data structures
# ----------------------------------------------------------------------
@dataclass
class Txn:
    """A single transaction."""

    date: str  # YYYY-MM-DD
    type: str  # a key of TXN_TYPES
    symbol: str = ""
    quantity: Decimal = ZERO  # shares (for SPLIT: the change in shares, may be negative)
    price: Decimal = ZERO  # trade price; for SHARES_IN: cost per share; for DISTRIBUTION: percent of cost moved
    fee: Decimal = ZERO  # trade commission
    amount: Decimal = ZERO  # amount for deposit/withdrawal/dividend/interest/fee
    note: str = ""
    id: int | None = None
    symbol2: str = ""  # SYMBOL_CHANGE / DISTRIBUTION: the new symbol (ticker change, merger, or what was handed out)
    account_id: int | None = None

    @property
    def type_label(self) -> str:
        return tr(TXN_TYPES[self.type]) if self.type in TXN_TYPES else self.type

    @property
    def cash_change(self) -> Decimal:
        """How much this transaction increases (positive) or decreases (negative) cash."""
        t = self.type
        if t in ("DEPOSIT", "DIVIDEND", "INTEREST"):
            return self.amount
        if t in ("WITHDRAW", "FEE"):
            return -self.amount
        if t == "BUY":
            return -(self.quantity * self.price + self.fee)
        if t == "SELL":
            return self.quantity * self.price - self.fee
        return ZERO  # share transfers and splits do not touch cash

    def normalized(self) -> "Txn":
        """Clear fields this type does not use; uppercase the symbol."""
        need = TYPE_FIELDS.get(self.type, ())
        return replace(
            self,
            symbol=self.symbol.strip().upper() if "symbol" in need else "",
            symbol2=self.symbol2.strip().upper() if "symbol2" in need else "",
            quantity=self.quantity if "quantity" in need else ZERO,
            price=self.price if "price" in need else ZERO,
            fee=self.fee if "fee" in need else ZERO,
            amount=self.amount if "amount" in need else ZERO,
            note=self.note.strip(),
        )

    def validate(self) -> None:
        """Check that this single transaction makes sense; raise ValueError with a readable message if not."""
        if self.type not in TXN_TYPES:
            raise ValueError(tr("Unknown transaction type: {type}", type=self.type))
        parse_date(self.date)
        need = TYPE_FIELDS[self.type]
        if "symbol" in need and not self.symbol.strip():
            raise ValueError(tr("Please enter a symbol"))
        if "symbol2" in need:
            if not self.symbol2.strip():
                raise ValueError(tr("Please enter the new symbol"))
            if self.symbol2.strip().upper() == self.symbol.strip().upper():
                raise ValueError(tr("The new symbol must differ from the old one"))
        if "amount" in need and self.amount <= 0:
            raise ValueError(tr("Amount must be greater than 0"))
        if "quantity" in need:
            if self.type == "SPLIT":
                if self.quantity == 0:
                    raise ValueError(tr("Share change cannot be 0"))
            elif self.quantity <= 0:
                raise ValueError(tr("Quantity must be greater than 0"))
        if self.type in ("BUY", "SELL") and self.price <= 0:
            raise ValueError(tr("Price must be greater than 0"))
        if self.type == "SHARES_IN" and self.price < 0:
            raise ValueError(tr("Cost per share cannot be negative"))
        if self.type == "DISTRIBUTION" and not 0 <= self.price <= 100:
            raise ValueError(tr("Cost basis moved must be between 0 and 100%"))
        if self.fee < 0:
            raise ValueError(tr("Fee cannot be negative"))


@dataclass
class Position:
    """The position in one stock."""

    symbol: str
    quantity: Decimal = ZERO  # current shares
    cost: Decimal = ZERO  # total cost of the current position (incl. buy commissions)
    realized: Decimal = ZERO  # cumulative realized P/L
    dividends: Decimal = ZERO  # cumulative dividends

    @property
    def avg_cost(self) -> Decimal:
        return self.cost / self.quantity if self.quantity else ZERO

    @property
    def is_open(self) -> bool:
        return self.quantity != 0


@dataclass
class Row:
    """State after each transaction during replay; used for running balances and per-stock detail."""

    txn: Txn
    cash_after: Decimal  # cash balance after this transaction
    qty_after: Decimal  # shares of this stock held after this transaction (with symbol2: of the new symbol)
    avg_cost_after: Decimal  # average cost of this stock after this transaction
    realized: Decimal  # realized P/L from this transaction (sells only)
    # SYMBOL_CHANGE / DISTRIBUTION: (shares, average cost) of the original symbol after this transaction
    source_after: tuple[Decimal, Decimal] | None = None


@dataclass
class LedgerResult:
    cash: Decimal = ZERO
    positions: dict[str, Position] = field(default_factory=dict)
    rows: list[Row] = field(default_factory=list)
    deposits: Decimal = ZERO  # total deposits
    withdrawals: Decimal = ZERO  # total withdrawals
    interest: Decimal = ZERO  # total interest
    fees: Decimal = ZERO  # total fees (standalone fees + trade commissions)

    @property
    def open_positions(self) -> list[Position]:
        return sorted((p for p in self.positions.values() if p.is_open), key=lambda p: p.symbol)

    @property
    def all_positions(self) -> list[Position]:
        return sorted(self.positions.values(), key=lambda p: (not p.is_open, p.symbol))

    @property
    def total_cost(self) -> Decimal:
        return sum((p.cost for p in self.open_positions), ZERO)

    @property
    def realized(self) -> Decimal:
        return sum((p.realized for p in self.positions.values()), ZERO)

    @property
    def dividends(self) -> Decimal:
        return sum((p.dividends for p in self.positions.values()), ZERO)

    @property
    def net_deposits(self) -> Decimal:
        return self.deposits - self.withdrawals


# ----------------------------------------------------------------------
# Core: replay all transactions in chronological order
# ----------------------------------------------------------------------
def sort_key(t: Txn):
    # Same-day transactions in entry order; unsaved ones (id is None) go last that day
    return (t.date, t.id if t.id is not None else 10**18)


def replay(txns) -> LedgerResult:
    res = LedgerResult()
    for t in sorted(txns, key=sort_key):
        pos = None
        if t.type in STOCK_TYPES:
            pos = res.positions.setdefault(t.symbol, Position(t.symbol))
        realized = ZERO
        source_after = None

        if t.type == "DEPOSIT":
            res.deposits += t.amount
        elif t.type == "WITHDRAW":
            res.withdrawals += t.amount
        elif t.type == "INTEREST":
            res.interest += t.amount
        elif t.type == "FEE":
            res.fees += t.amount
        elif t.type == "DIVIDEND":
            pos.dividends += t.amount
        elif t.type == "BUY":
            pos.quantity += t.quantity
            pos.cost += t.quantity * t.price + t.fee
            res.fees += t.fee
        elif t.type == "SELL":
            cost_out = _take_shares(pos, t)
            realized = t.quantity * t.price - t.fee - cost_out
            pos.realized += realized
            res.fees += t.fee
        elif t.type == "SHARES_IN":
            pos.quantity += t.quantity
            pos.cost += t.quantity * t.price
        elif t.type == "SHARES_OUT":
            _take_shares(pos, t)
        elif t.type == "SPLIT":
            if pos.quantity <= 0:
                raise LedgerError(tr("{date} {symbol}: no shares held at the time of the split",
                                     date=t.date, symbol=t.symbol))
            if pos.quantity + t.quantity <= 0:
                raise LedgerError(tr(
                    "{date} {symbol}: reverse split removes {removed} shares, but only {held} shares were held",
                    date=t.date, symbol=t.symbol, removed=fmt_qty(-t.quantity), held=fmt_qty(pos.quantity),
                ))
            pos.quantity += t.quantity  # total cost unchanged; average cost adjusts automatically
        elif t.type == "SYMBOL_CHANGE":
            # the whole position becomes the new symbol, cost basis and all (no gain or loss);
            # past sales and dividends stay on the old symbol's record
            if pos.quantity <= 0:
                raise LedgerError(tr("{date} {symbol}: no shares held to change into {new}",
                                     date=t.date, symbol=t.symbol, new=t.symbol2))
            new = res.positions.setdefault(t.symbol2, Position(t.symbol2))
            new.quantity += t.quantity
            new.cost += pos.cost
            pos.quantity = pos.cost = ZERO
            source_after = (ZERO, ZERO)
            pos = new  # this row reports the new holding
        elif t.type == "DISTRIBUTION":
            # the stock is kept; the new security gets the given share of its cost basis (no gain or loss)
            if pos.quantity <= 0:
                raise LedgerError(tr("{date} {symbol}: no shares held at the time of the distribution",
                                     date=t.date, symbol=t.symbol))
            moved = pos.cost * t.price / 100
            pos.cost -= moved
            new = res.positions.setdefault(t.symbol2, Position(t.symbol2))
            new.quantity += t.quantity
            new.cost += moved
            source_after = (pos.quantity, pos.avg_cost)
            pos = new  # this row reports the new holding

        res.cash += t.cash_change
        res.rows.append(
            Row(
                txn=t,
                cash_after=res.cash,
                qty_after=pos.quantity if pos else ZERO,
                avg_cost_after=pos.avg_cost if pos else ZERO,
                realized=realized,
                source_after=source_after,
            )
        )
    return res


def combine_results(results) -> LedgerResult:
    """Add up several accounts (each already replayed) into one result, for the all-accounts view.

    Cash and totals are summed; a stock held in several accounts becomes one position (shares, cost, realized
    and dividends added, so its average cost is total cost / total shares). The rows are every account's rows
    in date order -- their running balances still belong to their own account."""
    total = LedgerResult()
    for r in results:
        total.cash += r.cash
        total.deposits += r.deposits
        total.withdrawals += r.withdrawals
        total.interest += r.interest
        total.fees += r.fees
        for symbol, p in r.positions.items():
            q = total.positions.setdefault(symbol, Position(symbol))
            q.quantity += p.quantity
            q.cost += p.cost
            q.realized += p.realized
            q.dividends += p.dividends
        total.rows.extend(r.rows)
    total.rows.sort(key=lambda row: sort_key(row.txn))
    return total


def _take_shares(pos: Position, t: Txn) -> Decimal:
    """Remove shares on sell/transfer out, reducing cost at average cost; return the cost removed."""
    if t.quantity > pos.quantity:
        raise LedgerError(tr(
            "{date} {type} {qty} shares of {symbol}, but only {held} shares were held",
            date=t.date, type=t.type_label, qty=fmt_qty(t.quantity), symbol=t.symbol, held=fmt_qty(pos.quantity),
        ))
    if t.quantity == pos.quantity:  # sold everything, cost goes to zero
        cost_out = pos.cost
        pos.quantity = ZERO
        pos.cost = ZERO
    else:
        cost_out = pos.cost * t.quantity / pos.quantity
        pos.quantity -= t.quantity
        pos.cost -= cost_out
    return cost_out


# ----------------------------------------------------------------------
# Market value (from manually entered prices)
# ----------------------------------------------------------------------
@dataclass
class Valuation:
    market_value: Decimal  # market value of holdings (at cost when no price entered)
    unrealized: Decimal  # unrealized P/L (only stocks with a price)
    missing: list[str]  # stocks without a price


def valuation(result: LedgerResult, prices: dict[str, Decimal]) -> Valuation:
    mv = unreal = ZERO
    missing = []
    for p in result.open_positions:
        price = prices.get(p.symbol)
        if price is None:
            mv += p.cost
            missing.append(p.symbol)
        else:
            value = p.quantity * price
            mv += value
            unreal += value - p.cost
    return Valuation(mv, unreal, missing)


# ----------------------------------------------------------------------
# Account value over time (for the chart)
# ----------------------------------------------------------------------
@dataclass
class ValuePoint:
    time: int  # unix time
    value: float  # cash + holdings at that time
    net_deposits: float  # cumulative deposits - withdrawals up to then, to separate returns from cash flows


def value_series(rows: list[Row], prices: dict[str, list[tuple[int, float]]],
                 fallback: dict[str, Decimal] | None = None) -> list[ValuePoint]:
    """Account value at every timestamp in `prices` ({symbol: [(unix time, close), ...]}).

    Holdings and cash are taken as of each timestamp's date, so trades show up on the day they happened.
    Yahoo's closes are split-adjusted, so shares held before a recorded split are scaled by that split.
    Stocks without a price yet use `fallback` (e.g. a manually entered price), else their average cost.
    Times before the first transaction are skipped.
    """
    fallback = fallback or {}
    # one snapshot per date: (date, cash, net deposits, {symbol: (shares, avg cost)})
    dates: list[str] = []
    snaps: list[tuple[float, float, dict[str, tuple[float, float]]]] = []
    holding: dict[str, tuple[float, float]] = {}
    net = 0.0
    splits: dict[str, list[tuple[str, float]]] = {}
    for r in rows:
        t = r.txn
        if t.type == "DEPOSIT":
            net += float(t.amount)
        elif t.type == "WITHDRAW":
            net -= float(t.amount)
        if r.source_after is not None:  # symbol change or distribution: both symbols' holdings change
            holding[t.symbol] = (float(r.source_after[0]), float(r.source_after[1]))
            holding[t.symbol2] = (float(r.qty_after), float(r.avg_cost_after))
        elif t.type in STOCK_TYPES:
            holding[t.symbol] = (float(r.qty_after), float(r.avg_cost_after))
        if t.type == "SPLIT":
            splits.setdefault(t.symbol, []).append((t.date, float(r.qty_after / (r.qty_after - t.quantity))))
        state = (float(r.cash_after), net, dict(holding))
        if dates and dates[-1] == t.date:
            snaps[-1] = state
        else:
            dates.append(t.date)
            snaps.append(state)
    if not dates:
        return []

    def split_factor(sym: str, day: str) -> float:
        f = 1.0
        for d, ratio in splits.get(sym, ()):
            if d > day:
                f *= ratio
        return f

    times = sorted({ts for series in prices.values() for ts, _ in series})
    pointer = {sym: 0 for sym in prices}
    last: dict[str, float] = {}
    out = []
    for ts in times:
        for sym, series in prices.items():  # carry each stock's latest close forward
            i = pointer[sym]
            while i < len(series) and series[i][0] <= ts:
                last[sym] = series[i][1]
                i += 1
            pointer[sym] = i
        day = datetime.fromtimestamp(ts).date().isoformat()
        idx = bisect_right(dates, day) - 1
        if idx < 0:
            continue
        cash, net_dep, hold = snaps[idx]
        value = cash
        for sym, (qty, avg) in hold.items():
            if not qty:
                continue
            if sym in last:
                value += qty * split_factor(sym, day) * last[sym]
            else:
                value += qty * float(fallback.get(sym, avg))
        out.append(ValuePoint(ts, value, net_dep))
    return out


def combine_series(series_list: list[list[ValuePoint]]) -> list[ValuePoint]:
    """Add up the value series of several accounts (made from the same prices) into one.

    An account has no points before its first transaction, so it simply adds nothing until then."""
    total: dict[int, ValuePoint] = {}
    for series in series_list:
        for p in series:
            if p.time in total:
                total[p.time].value += p.value
                total[p.time].net_deposits += p.net_deposits
            else:
                total[p.time] = ValuePoint(p.time, p.value, p.net_deposits)
    return [total[t] for t in sorted(total)]


# ----------------------------------------------------------------------
# Display formatting
# ----------------------------------------------------------------------
def fmt_money(d: Decimal | None, sign: bool = False) -> str:
    if d is None:
        return "-"
    q = d.quantize(Decimal("0.01"), ROUND_HALF_UP)
    if q == 0:
        q = abs(q)  # avoid showing -0.00
    text = f"{q:,.2f}"
    return "+" + text if sign and q > 0 else text


def fmt_qty(d: Decimal | None, sign: bool = False) -> str:
    if d is None:
        return "-"
    q = d.quantize(Decimal("0.00000001"), ROUND_HALF_UP)  # 8 places: whole satoshis for bitcoin
    if q == 0:
        return "0"
    text = f"{q.normalize():,f}"
    return "+" + text if sign and q > 0 else text


def fmt_price(d: Decimal | None) -> str:
    """Prices: at most 4 decimals, at least 2."""
    if d is None:
        return "-"
    whole, frac = f"{d.quantize(Decimal('0.0001'), ROUND_HALF_UP):,.4f}".split(".")
    return f"{whole}.{frac.rstrip('0').ljust(2, '0')}"


def fmt_pct(d: Decimal | None) -> str:
    if d is None:
        return "-"
    return f"{d * 100:+.2f}%"
