"""
finance.py -- month-by-month income and expenses outside the brokerage accounts
(independent of the UI and database, testable on its own)

Each month holds one amount per category (salary, interest, credit card payments, ...), each with an optional
comment -- one row of a spreadsheet. Totals and balances are never stored; they are worked out from the amounts,
so editing any month updates every balance after it:
  ending balance  = opening balance + income - expenses
  opening balance = the previous month's ending balance (or a figure typed in for that month)
An amount may be typed as a sum such as 1250.50+1250.50; the sum is kept with it so the parts can still be seen.
A stretch of months (a tax year, a few quarters) is picked with month_range() / period_months() and added up
with summarize().
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from i18n import tr
from ledger import ZERO, parse_date

INCOME, EXPENSE = "income", "expense"
KINDS = (INCOME, EXPENSE)
CENT = Decimal("0.01")


# ----------------------------------------------------------------------
# Data structures
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class FinCategory:
    """A column of the sheet: one kind of income or expense."""

    id: int
    kind: str  # INCOME or EXPENSE
    name: str


@dataclass
class FinEntry:
    """What one category came to in one month."""

    amount: Decimal = ZERO
    expr: str = ""  # the sum as typed when it was one, e.g. "1250.50+1250.50"; "" for a plain number
    comment: str = ""

    @property
    def is_empty(self) -> bool:
        return self.amount == 0 and not self.comment


@dataclass
class FinMonth:
    month: str  # YYYY-MM
    opening: Decimal | None = None  # typed in for this month; None = the previous month's ending balance
    entries: dict[int, FinEntry] = field(default_factory=dict)  # category id -> entry


@dataclass
class FinRow:
    """A month with its totals worked out."""

    month: FinMonth
    opening: Decimal
    income: Decimal
    expenses: Decimal
    ending: Decimal

    @property
    def net(self) -> Decimal:
        return self.income - self.expenses


@dataclass
class FinSummary:
    """Several months added up."""

    months: int = 0
    income: Decimal = ZERO
    expenses: Decimal = ZERO
    opening: Decimal | None = None  # opening balance of the first month
    ending: Decimal | None = None  # ending balance of the last month
    by_category: dict[int, Decimal] = field(default_factory=dict)

    @property
    def net(self) -> Decimal:
        return self.income - self.expenses


# ----------------------------------------------------------------------
# Months
# ----------------------------------------------------------------------
def parse_month(text: str) -> str:
    """Accept 2026-09, 2026/9, 2026.09 or 202609 and normalize to 2026-09."""
    m = re.fullmatch(r"(\d{4})(?:[-/.](\d{1,2})|(\d{2}))", (text or "").strip())
    if m:
        year, month = int(m.group(1)), int(m.group(2) or m.group(3))
        if 1 <= month <= 12 and year >= 1900:
            return f"{year:04d}-{month:02d}"
    raise ValueError(tr("Invalid month, please use a format like 2026-09"))


def add_month(month: str, n: int = 1) -> str:
    """The month n months after (or, if negative, before) a YYYY-MM month."""
    year, mon = divmod(int(month[:4]) * 12 + int(month[5:7]) - 1 + n, 12)
    return f"{year:04d}-{mon + 1:02d}"


def month_of(text: str) -> str:
    """The month in a typed month or date: 2026-09, 2026/9, 202609, or a whole date such as 2026-09-30."""
    try:
        return parse_month(text)
    except ValueError:
        pass
    try:
        return parse_date(text)[:7]
    except ValueError:
        raise ValueError(tr("Invalid month, please use a format like 2026-09")) from None


# Periods of months the finance page can be narrowed to: code -> label (English; translated with tr() when shown).
# A calendar year is its own code ("2026"), and "CUSTOM" takes the first and last month the user types.
FINANCE_PERIODS: dict[str, str] = {
    "ALL": "All time",
    "3M": "Past 3 months",
    "6M": "Past 6 months",
    "1Y": "Past year",
}
_RECENT = {"3M": 3, "6M": 6, "1Y": 12}


def month_range(code: str, this_month: str) -> tuple[str | None, str | None]:
    """First and last month (YYYY-MM, both included) of a period; None means no limit on that side.
    "Past 3 months" is the last three calendar months up to and including `this_month`."""
    if code in _RECENT:
        return add_month(this_month, 1 - _RECENT[code]), this_month
    if len(code) == 4 and code.isdigit():
        return f"{code}-01", f"{code}-12"
    return None, None


def period_months(rows: list[FinRow], first: str | None, last: str | None) -> list[FinRow]:
    """The months of `rows` from month `first` to month `last`, both included (None = no limit)."""
    return [r for r in rows if (not first or r.month.month >= first) and (not last or r.month.month <= last)]


# ----------------------------------------------------------------------
# Typed amounts
# ----------------------------------------------------------------------
_FULL_WIDTH = str.maketrans({"＋": "+", "－": "-", "×": "*", "÷": "/", "（": "(", "）": ")", "，": ",", "．": "."})
_TOKEN = re.compile(r"\d+(?:\.\d*)?|\.\d+|[-+*/()]")


def _squash(text: str | None) -> str:
    """A typed amount without spaces, $ and thousands separators (full-width characters made ordinary)."""
    return "".join((text or "").translate(_FULL_WIDTH).replace(",", "").replace("$", "").split())


def eval_amount(text: str | None) -> Decimal:
    """The value of a typed amount, rounded to cents: a plain number or a sum such as 1250.50+1250.50
    (+ - * / and parentheses are understood). Blank is 0."""
    squashed = _squash(text)
    if not squashed:
        return ZERO
    bad = ValueError(tr('"{value}" is not a valid number', value=text))
    tokens = _TOKEN.findall(squashed)
    if "".join(tokens) != squashed:
        raise bad
    pos = 0

    def peek() -> str | None:
        return tokens[pos] if pos < len(tokens) else None

    def take() -> str:
        nonlocal pos
        pos += 1
        return tokens[pos - 1]

    def expression() -> Decimal:
        value = term()
        while peek() in ("+", "-"):
            sign = take()
            rhs = term()
            value = value + rhs if sign == "+" else value - rhs
        return value

    def term() -> Decimal:
        value = unary()
        while peek() in ("*", "/"):
            op = take()
            rhs = unary()
            if op == "*":
                value *= rhs
            elif rhs == 0:
                raise ValueError(tr("Cannot divide by zero"))
            else:
                value /= rhs
        return value

    def unary() -> Decimal:
        if peek() in ("+", "-"):
            sign = take()
            value = unary()
            return -value if sign == "-" else value
        return atom()

    def atom() -> Decimal:
        tok = peek()
        if tok == "(":
            take()
            value = expression()
            if peek() != ")":
                raise bad
            take()
            return value
        if tok is None or not (tok[0].isdigit() or tok[0] == "."):
            raise bad
        return Decimal(take())

    try:
        value = expression()
        if pos != len(tokens):
            raise bad
        return value.quantize(CENT, ROUND_HALF_UP)
    except InvalidOperation:  # a number too large to keep
        raise bad from None


def entry_from_text(text: str | None, comment: str = "") -> FinEntry:
    """An entry from what was typed in the amount box (a number or a sum) and the comment box."""
    squashed = _squash(text)
    plain = re.fullmatch(r"[+-]?(?:\d+\.?\d*|\.\d+)", squashed) or not squashed
    return FinEntry(eval_amount(text), "" if plain else squashed, (comment or "").strip())


# ----------------------------------------------------------------------
# Balances
# ----------------------------------------------------------------------
def finance_rows(months: list[FinMonth], categories: list[FinCategory]) -> list[FinRow]:
    """Every month in order with its totals; each opening balance carries over from the month before
    (unless one was typed in for it)."""
    kind_of = {c.id: c.kind for c in categories}
    rows = []
    carried = ZERO
    for m in sorted(months, key=lambda m: m.month):
        opening = carried if m.opening is None else m.opening
        income = sum((e.amount for cid, e in m.entries.items() if kind_of.get(cid) == INCOME), ZERO)
        expenses = sum((e.amount for cid, e in m.entries.items() if kind_of.get(cid) == EXPENSE), ZERO)
        carried = opening + income - expenses
        rows.append(FinRow(m, opening, income, expenses, carried))
    return rows


def summarize(rows: list[FinRow]) -> FinSummary:
    total = FinSummary(months=len(rows))
    for r in rows:
        total.income += r.income
        total.expenses += r.expenses
        for cid, e in r.month.entries.items():
            total.by_category[cid] = total.by_category.get(cid, ZERO) + e.amount
    if rows:
        total.opening, total.ending = rows[0].opening, rows[-1].ending
    return total
