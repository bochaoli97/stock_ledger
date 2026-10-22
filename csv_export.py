"""
csv_export.py -- the layout of the CSV files (independent of the UI and database, testable on its own)

Every file is one plain table that a spreadsheet can filter, pivot and add up as it is: a single header row, one
record per row, and no blank lines, titles or total rows in between. Dates are YYYY-MM-DD and amounts plain numbers
(1234.50: no thousands separator, no currency sign). A cell that does not apply to a row is left empty. Column titles
and type names follow the interface language. Files are saved as UTF-8 with a BOM, so Excel shows Chinese correctly.

A stock account  (<account>_<table>_<date>.csv)
  transactions  one row per transaction, oldest first
      Account, Date, Year, Type, Symbol, New Symbol, Quantity, Price, Cost Moved %, Fee, Amount,
      Cash Change, Cash Balance, Net Proceeds, Cost Sold, Realized P/L, Note
      Amount is what a deposit, withdrawal, dividend, interest or fee came to; Cash Change is how much the
      transaction moved the cash (negative = out) and Cash Balance what was left after it. A split's Quantity is the
      change in shares; a distribution's Cost Moved % is the share of the stock's cost handed to the new security.
      For a sale only: Net Proceeds = quantity x price - fee (the figure a 1099-B shows), Cost Sold = the average
      cost of the shares sold (a 1099-B's cost basis), and Realized P/L = Net Proceeds - Cost Sold.
  holdings      the positions as of the day of the export, closed ones too (they still carry realized P/L and dividends);
      Account, As Of, Symbol, Shares, Avg Cost, Cost Basis, Price, Market Value, Unrealized P/L, Realized P/L, Dividends
      The last row is the cash: its Market Value is the cash balance, so the Market Value column adds up to the
      account's value (stocks without a price are left out, as they have no value to add).
  yearly        one row per calendar year with transactions -- the totals to check against 1099-DIV, 1099-INT and 1099-B
      Account, Year, Deposits, Withdrawals, Dividends, Interest, Fees, Commissions, Net Proceeds, Cost Sold, Realized P/L
      Fees are account fees (Fee transactions); Commissions are the fees paid on buys and sells.

The Finance page  (finance_<table>_<date>.csv), expenses as positive numbers
  monthly       one row per month, like the page: the opening balance, a column for each category, the totals and the
                ending balance
      Year, Month, Opening, <income categories>, Total income, <expense categories>, Total expenses, Ending balance
  yearly        the same columns with one row per calendar year: what each category came to in the year, Months = the
                months entered (12 = the whole year), Opening = the first month's and Ending balance = the last month's
      Year, Months, Opening, <income categories>, Total income, <expense categories>, Total expenses, Ending balance
  entries       one row per amount, with its sum and comment -- for pivoting by category or looking up a comment
      Year, Month, Type, Category, Amount, Calculation, Comment
"""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from finance import EXPENSE, INCOME, FinCategory, FinRow, summarize
from i18n import tr
from ledger import TYPE_FIELDS, ZERO, LedgerResult, fmt_money, fmt_price

Table = tuple[list[str], list[list[str]]]  # the header row, then the data rows

# Column titles (English; translated with tr() when written)
TXN_HEADERS = ("Account", "Date", "Year", "Type", "Symbol", "New Symbol", "Quantity", "Price", "Cost Moved %", "Fee",
               "Amount", "Cash Change", "Cash Balance", "Net Proceeds", "Cost Sold", "Realized P/L", "Note")
HOLDING_HEADERS = ("Account", "As Of", "Symbol", "Shares", "Avg Cost", "Cost Basis", "Price", "Market Value",
                   "Unrealized P/L", "Realized P/L", "Dividends")
# the yearly totals of a stock account: column title -> the transaction type whose amount it adds up (None = worked out)
YEARLY_TOTALS = {"Deposits": "DEPOSIT", "Withdrawals": "WITHDRAW", "Dividends": "DIVIDEND", "Interest": "INTEREST",
                 "Fees": "FEE", "Commissions": None, "Net Proceeds": None, "Cost Sold": None, "Realized P/L": None}
YEARLY_HEADERS = ("Account", "Year", *YEARLY_TOTALS)
MONTHLY_HEADERS = ("Year", "Month")  # the first two columns of the finance sheets; the rest follow the categories
FINANCE_YEARLY_HEADERS = ("Year", "Months")
ENTRY_HEADERS = ("Year", "Month", "Type", "Category", "Amount", "Calculation", "Comment")


# ----------------------------------------------------------------------
# Cells
# ----------------------------------------------------------------------
def money(d: Decimal | None) -> str:
    """An amount rounded to cents, without a thousands separator; empty for None."""
    return "" if d is None else fmt_money(d).replace(",", "")


def plain(d: Decimal) -> str:
    """A share count, price or percent exactly as recorded: no trailing zeros, never scientific notation."""
    return format(d.normalize(), "f")


# ----------------------------------------------------------------------
# A stock account
# ----------------------------------------------------------------------
def stock_tables(account: str, result: LedgerResult, prices: dict[str, Decimal], as_of: str) -> dict[str, Table]:
    """The tables of one account, by name: transactions, holdings and yearly."""
    return {
        "transactions": transaction_table(account, result),
        "holdings": holding_table(account, result, prices, as_of),
        "yearly": yearly_table(account, result),
    }


def transaction_table(account: str, result: LedgerResult) -> Table:
    rows = []
    for row in result.rows:
        t = row.txn
        need = TYPE_FIELDS[t.type]
        sale = t.type == "SELL"
        proceeds = t.cash_change if sale else None  # quantity x price - fee
        rows.append([
            account, t.date, t.date[:4], t.type_label, t.symbol, t.symbol2,
            plain(t.quantity) if "quantity" in need else "",
            plain(t.price) if "price" in need and t.type != "DISTRIBUTION" else "",
            plain(t.price) if t.type == "DISTRIBUTION" else "",
            money(t.fee) if "fee" in need else "",
            money(t.amount) if "amount" in need else "",
            money(t.cash_change), money(row.cash_after),
            money(proceeds), money(proceeds - row.realized) if sale else "", money(row.realized) if sale else "",
            t.note,
        ])
    return [tr(h) for h in TXN_HEADERS], rows


def holding_table(account: str, result: LedgerResult, prices: dict[str, Decimal], as_of: str) -> Table:
    rows = []
    for p in result.all_positions:
        price = prices.get(p.symbol) if p.is_open else None
        value = p.quantity * price if price is not None else None
        rows.append([
            account, as_of, p.symbol, plain(p.quantity),
            fmt_price(p.avg_cost).replace(",", "") if p.is_open else "",
            money(p.cost), plain(price) if price is not None else "", money(value),
            money(value - p.cost) if value is not None else "", money(p.realized), money(p.dividends),
        ])
    rows.append([account, as_of, tr("Cash"), "", "", "", "", money(result.cash), "", "", ""])
    return [tr(h) for h in HOLDING_HEADERS], rows


def yearly_table(account: str, result: LedgerResult) -> Table:
    years: dict[str, dict[str, Decimal]] = {}  # year -> column title -> total
    for row in result.rows:
        t = row.txn
        totals = years.setdefault(t.date[:4], dict.fromkeys(YEARLY_TOTALS, ZERO))
        for title, code in YEARLY_TOTALS.items():
            if t.type == code:
                totals[title] += t.amount
        if t.type in ("BUY", "SELL"):
            totals["Commissions"] += t.fee
        if t.type == "SELL":
            totals["Net Proceeds"] += t.cash_change
            totals["Cost Sold"] += t.cash_change - row.realized
            totals["Realized P/L"] += row.realized
    rows = [[account, year, *(money(v) for v in totals.values())] for year, totals in sorted(years.items())]
    return [tr(h) for h in YEARLY_HEADERS], rows


# ----------------------------------------------------------------------
# The Finance page
# ----------------------------------------------------------------------
def finance_tables(rows: list[FinRow], categories: list[FinCategory]) -> dict[str, Table]:
    """The tables of the Finance page, by name: monthly, yearly and entries. `rows` come from finance_rows()."""
    return {
        "monthly": monthly_table(rows, categories),
        "yearly": finance_yearly_table(rows, categories),
        "entries": entry_table(rows, categories),
    }


def _sheet(lead: tuple[str, str], body: list[tuple], categories: list[FinCategory]) -> Table:
    """A table with the page's columns after two leading ones: the opening balance, income categories, total income,
    expense categories, total expenses and ending balance. Each of `body` is (leading cells, opening, total income,
    total expenses, ending, {category id: amount}); a category without an amount is left empty."""
    income = [c for c in categories if c.kind == INCOME]
    expense = [c for c in categories if c.kind == EXPENSE]
    header = [*(tr(h) for h in lead), tr("Opening"), *(c.name for c in income), tr("Total income"),
              *(c.name for c in expense), tr("Total expenses"), tr("Ending balance")]
    rows = [[*start, money(opening), *(money(amounts.get(c.id)) for c in income), money(total_in),
             *(money(amounts.get(c.id)) for c in expense), money(total_out), money(ending)]
            for start, opening, total_in, total_out, ending, amounts in body]
    return header, rows


def monthly_table(rows: list[FinRow], categories: list[FinCategory]) -> Table:
    body = [([r.month.month[:4], r.month.month], r.opening, r.income, r.expenses, r.ending,
             {cid: e.amount for cid, e in r.month.entries.items()}) for r in rows]
    return _sheet(MONTHLY_HEADERS, body, categories)


def finance_yearly_table(rows: list[FinRow], categories: list[FinCategory]) -> Table:
    years: dict[str, list[FinRow]] = {}
    for r in rows:
        years.setdefault(r.month.month[:4], []).append(r)
    body = []
    for year, months in sorted(years.items()):
        total = summarize(months)
        body.append(([year, str(total.months)], total.opening, total.income, total.expenses, total.ending,
                     total.by_category))
    return _sheet(FINANCE_YEARLY_HEADERS, body, categories)


def entry_table(rows: list[FinRow], categories: list[FinCategory]) -> Table:
    out = []
    for r in rows:
        month = r.month.month
        for c in categories:
            e = r.month.entries.get(c.id)
            if e is not None and not e.is_empty:
                out.append([month[:4], month, tr("Income" if c.kind == INCOME else "Expense"), c.name,
                            money(e.amount), e.expr, e.comment])
    return [tr(h) for h in ENTRY_HEADERS], out


# ----------------------------------------------------------------------
# Files
# ----------------------------------------------------------------------
def write_tables(folder: str | Path, base: str, stamp: str, tables: dict[str, Table]) -> list[Path]:
    """Save each table as <base>_<name>_<stamp>.csv in `folder`; returns the files made."""
    files = []
    for name, (header, rows) in tables.items():
        path = Path(folder) / f"{base}_{name}_{stamp}.csv"
        # utf-8-sig: lets Excel display non-ASCII text (e.g. notes) correctly
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        files.append(path)
    return files
