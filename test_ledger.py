"""
test_ledger.py -- checks that the bookkeeping math is correct. Run: python test_ledger.py
(also runs under pytest)

No test touches the internet: the Yahoo calls are replaced by canned responses.
"""

import ast
import csv
import io
import json
import string
import sqlite3
import tempfile
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from csv_export import (
    ENTRY_HEADERS,
    FINANCE_YEARLY_HEADERS,
    HOLDING_HEADERS,
    MONTHLY_HEADERS,
    TXN_HEADERS,
    YEARLY_HEADERS,
    entry_table,
    finance_tables,
    finance_yearly_table,
    holding_table,
    monthly_table,
    stock_tables,
    transaction_table,
    write_tables,
    yearly_table,
)
from finance import (
    FINANCE_PERIODS,
    FinCategory,
    FinEntry,
    FinMonth,
    add_month,
    entry_from_text,
    eval_amount,
    finance_rows,
    month_of,
    month_range,
    parse_month,
    period_months,
    summarize,
)
from ledger import (
    PERIODS,
    TXN_TYPES,
    LedgerError,
    LedgerResult,
    Position,
    Txn,
    ValuePoint,
    add_months,
    combine_results,
    combine_series,
    fmt_money,
    fmt_pct,
    fmt_price,
    fmt_qty,
    parse_date,
    period_range,
    replay,
    sort_key,
    to_decimal,
    valuation,
    value_series,
)
from quotes import (
    Quote,
    QuoteError,
    Suggestion,
    fetch_quotes,
    is_crypto,
    is_live,
    ledger_symbol,
    match_local,
    new_york_time,
    parse_search,
    parse_spark,
    search_symbols,
    yahoo_symbol,
)
from storage import Storage, daily_backup
import i18n


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def raises(exc, fn, *args, match: str = "", **kw):
    """Assert that fn(*args, **kw) raises exc with `match` somewhere in the message."""
    try:
        fn(*args, **kw)
    except exc as e:
        assert match in str(e), f"{match!r} not in {str(e)!r}"
        return e
    raise AssertionError(f"expected {exc.__name__}" + (f" mentioning {match!r}" if match else ""))


def txns(*rows):
    """Build transactions from (date, type, symbol, quantity, price, fee, amount); ids follow the order given."""
    return [
        Txn(date=d, type=t, symbol=s, quantity=D(str(q)), price=D(str(p)), fee=D(str(f)), amount=D(str(a)), id=i)
        for i, (d, t, s, q, p, f, a) in enumerate(rows, start=1)
    ]


def ts(day: str, hour: int = 12) -> int:
    return int(datetime.fromisoformat(f"{day} {hour:02d}:00").timestamp())


def utc(stamp: str) -> float:
    """Unix time of a UTC clock reading such as '2026-10-27 14:00', so the market-hours tests need no time zone database."""
    return datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc).timestamp()


def quote_with_bars(*stamps: str) -> Quote:
    """A quote whose chart has one bar at each of the UTC times given."""
    return Quote(price=D(10), prev_close=D(9), time=None, points=[(int(utc(s)), 10.0) for s in stamps])


def fake_urlopen(responses, calls=None):
    """Stand-in for urllib.request.urlopen: returns each canned JSON response in turn (an exception is raised)."""
    responses = iter(responses)

    def urlopen(req, timeout=None):
        if calls is not None:
            calls.append(req.full_url)
        r = next(responses)
        if isinstance(r, Exception):
            raise r
        return io.BytesIO(r if isinstance(r, bytes) else json.dumps(r).encode())

    return urlopen


def sample_txns():
    return txns(
        ("2026-01-02", "DEPOSIT", "", 0, 0, 0, 10000),
        ("2026-01-02", "SHARES_IN", "AAPL", 10, 150, 0, 0),
        ("2026-01-05", "BUY", "AAPL", 10, 170, 1, 0),
        ("2026-01-06", "BUY", "MSFT", 5, 400, 0, 0),
        ("2026-02-01", "SELL", "AAPL", 5, 200, 1, 0),
        ("2026-02-15", "DIVIDEND", "AAPL", 0, 0, 0, "3.75"),
        ("2026-03-01", "SPLIT", "AAPL", 45, 0, 0, 0),
        ("2026-03-10", "SELL", "MSFT", 5, 380, 0, 0),
        ("2026-04-01", "WITHDRAW", "", 0, 0, 0, 1000),
        ("2026-04-30", "INTEREST", "", 0, 0, 0, "1.23"),
        ("2026-05-01", "FEE", "", 0, 0, 0, 10),
        ("2026-06-01", "SHARES_OUT", "AAPL", 10, 0, 0, 0),
    )


# ----------------------------------------------------------------------
# Input parsing
# ----------------------------------------------------------------------
def test_to_decimal():
    assert to_decimal("1,234.5") == D("1234.5")
    assert to_decimal("  $12 ") == 12
    assert to_decimal("1，234") == 1234  # full-width comma from a Chinese input method
    assert to_decimal("-3.25") == D("-3.25")
    assert to_decimal("") == 0 and to_decimal("   ") == 0 and to_decimal(None) == 0
    assert to_decimal(7) == 7 and to_decimal(D("0.1")) == D("0.1")
    assert to_decimal("0.1") + to_decimal("0.2") == D("0.3")  # exact, unlike float
    for bad in ("abc", "1.2.3", "12$3x", "NaN", "Infinity", "-inf"):
        raises(ValueError, to_decimal, bad, match="not a valid number")


def test_parse_date():
    for text in ("2026-09-03", "2026/9/3", "2026.09.03", "20260903", "  2026-9-3  "):
        assert parse_date(text) == "2026-09-03", text
    assert parse_date("2028-02-29") == "2028-02-29"  # leap day
    for bad in ("", None, "2026-02-30", "2027-02-29", "2026-13-01", "09/03/2026", "yesterday"):
        raises(ValueError, parse_date, bad, match="Invalid date")


# ----------------------------------------------------------------------
# Single transactions: validation, normalization, cash effect
# ----------------------------------------------------------------------
def test_validate_accepts_good_transactions():
    for t in sample_txns():
        t.validate()
    Txn(date="2026-01-01", type="SHARES_IN", symbol="X", quantity=D(1), price=D(0)).validate()  # gifted shares
    Txn(date="2026-01-01", type="SPLIT", symbol="X", quantity=D(-9)).validate()  # reverse split
    Txn(date="2026-01-01", type="BUY", symbol="X", quantity=D("0.001"), price=D("0.0001")).validate()


def test_validate_rejects_bad_transactions():
    cases = [
        (Txn(date="2026-01-01", type="BOGUS"), "Unknown transaction type"),
        (Txn(date="2026-02-30", type="DEPOSIT", amount=D(1)), "Invalid date"),
        (Txn(date="2026-01-01", type="DEPOSIT"), "Amount must be greater than 0"),
        (Txn(date="2026-01-01", type="WITHDRAW", amount=D(-5)), "Amount must be greater than 0"),
        (Txn(date="2026-01-01", type="DIVIDEND", amount=D(5)), "Please enter a symbol"),
        (Txn(date="2026-01-01", type="DIVIDEND", symbol="  ", amount=D(5)), "Please enter a symbol"),
        (Txn(date="2026-01-01", type="BUY", symbol="X", price=D(1)), "Quantity must be greater than 0"),
        (Txn(date="2026-01-01", type="SELL", symbol="X", quantity=D(-1), price=D(1)), "Quantity must be greater than 0"),
        (Txn(date="2026-01-01", type="BUY", symbol="X", quantity=D(1)), "Price must be greater than 0"),
        (Txn(date="2026-01-01", type="SELL", symbol="X", quantity=D(1), price=D(-2)), "Price must be greater than 0"),
        (Txn(date="2026-01-01", type="BUY", symbol="X", quantity=D(1), price=D(1), fee=D(-1)), "Fee cannot be negative"),
        (Txn(date="2026-01-01", type="SHARES_IN", symbol="X", quantity=D(1), price=D(-1)), "cannot be negative"),
        (Txn(date="2026-01-01", type="SHARES_OUT", symbol="X"), "Quantity must be greater than 0"),
        (Txn(date="2026-01-01", type="SPLIT", symbol="X"), "Share change cannot be 0"),
    ]
    for t, msg in cases:
        raises(ValueError, t.validate, match=msg)


def test_normalized_clears_unused_fields():
    t = Txn(date="2026-01-01", type="DEPOSIT", symbol="AAPL", quantity=D(3), price=D(4), fee=D(1), amount=D(100),
            note="  paycheck  ").normalized()
    assert (t.symbol, t.quantity, t.price, t.fee, t.amount, t.note) == ("", 0, 0, 0, 100, "paycheck")
    t = Txn(date="2026-01-01", type="BUY", symbol=" brk.b ", quantity=D(1), price=D(2), fee=D(0), amount=D(99)).normalized()
    assert t.symbol == "BRK.B" and t.amount == 0 and t.price == 2
    t = Txn(date="2026-01-01", type="SHARES_OUT", symbol="x", quantity=D(1), price=D(5), fee=D(1)).normalized()
    assert t.price == 0 and t.fee == 0  # transfers out carry no price or fee
    t = Txn(date="2026-01-01", type="DIVIDEND", symbol="ko", quantity=D(5), amount=D(2)).normalized()
    assert t.symbol == "KO" and t.quantity == 0


def test_cash_change_per_type():
    def cash(type_, **kw):
        return Txn(date="2026-01-01", type=type_, **kw).cash_change

    assert cash("DEPOSIT", amount=D(100)) == 100
    assert cash("WITHDRAW", amount=D(100)) == -100
    assert cash("DIVIDEND", symbol="X", amount=D("1.5")) == D("1.5")
    assert cash("INTEREST", amount=D("0.42")) == D("0.42")
    assert cash("FEE", amount=D(3)) == -3
    assert cash("BUY", symbol="X", quantity=D(2), price=D("10.5"), fee=D(1)) == -22
    assert cash("SELL", symbol="X", quantity=D(2), price=D("10.5"), fee=D(1)) == 20
    assert cash("SHARES_IN", symbol="X", quantity=D(5), price=D(10)) == 0
    assert cash("SHARES_OUT", symbol="X", quantity=D(5)) == 0
    assert cash("SPLIT", symbol="X", quantity=D(5)) == 0


def test_type_label_and_position_basics():
    assert Txn(date="2026-01-01", type="WITHDRAW").type_label == "Withdrawal"
    assert Txn(date="2026-01-01", type="XYZ").type_label == "XYZ"
    p = Position("X")
    assert p.avg_cost == 0 and not p.is_open
    p = Position("X", quantity=D(4), cost=D(10))
    assert p.avg_cost == D("2.5") and p.is_open


# ----------------------------------------------------------------------
# Replay: the whole ledger
# ----------------------------------------------------------------------
def test_replay():
    r = replay(sample_txns())
    aapl, msft = r.positions["AAPL"], r.positions["MSFT"]

    # Cash: 10000 -1701 -2000 +999 +3.75 +1900 -1000 +1.23 -10
    assert r.cash == D("8192.98"), r.cash
    # AAPL: cost 1500+1701=3201; selling 5 shares removes 800.25, leaving 15 shares at 2400.75; 4-for-1 split -> 60 shares; 10 transferred out
    assert aapl.quantity == 50
    assert aapl.cost == D("2000.625")
    assert aapl.realized == D("198.75")  # 999 - 800.25
    assert aapl.dividends == D("3.75")
    assert fmt_price(aapl.avg_cost) == "40.0125"
    # MSFT: fully sold at a loss of 100; cost goes to zero
    assert msft.quantity == 0 and msft.cost == 0 and msft.realized == -100
    assert [p.symbol for p in r.open_positions] == ["AAPL"]
    assert r.net_deposits == 9000 and r.interest == D("1.23") and r.fees == 12
    assert r.realized == D("98.75")

    v = valuation(r, {"AAPL": D("45")})
    assert v.market_value == 2250 and v.unrealized == D("249.375") and v.missing == []


def test_replay_empty():
    r = replay([])
    assert r.cash == 0 and r.positions == {} and r.rows == [] and r.open_positions == []
    assert r.total_cost == 0 and r.realized == 0 and r.dividends == 0 and r.net_deposits == 0
    v = valuation(r, {})
    assert v.market_value == 0 and v.unrealized == 0 and v.missing == []


def test_running_rows():
    r = replay(txns(
        ("2026-01-01", "DEPOSIT", "", 0, 0, 0, 1000),
        ("2026-01-02", "BUY", "X", 10, 20, 0, 0),
        ("2026-01-03", "BUY", "X", 10, 30, 0, 0),
        ("2026-01-04", "SELL", "X", 5, 40, 0, 0),
        ("2026-01-05", "INTEREST", "", 0, 0, 0, 1),
    ))
    assert [row.cash_after for row in r.rows] == [1000, 800, 500, 700, 701]
    assert [row.qty_after for row in r.rows] == [0, 10, 20, 15, 0]  # non-stock rows report 0 shares
    assert [row.avg_cost_after for row in r.rows] == [0, 20, 25, 25, 0]
    assert [row.realized for row in r.rows] == [0, 0, 0, 75, 0]  # 5 x (40 - 25)
    assert [row.txn.id for row in r.rows] == [1, 2, 3, 4, 5]


def test_fees_on_both_sides_of_a_trade():
    r = replay(txns(
        ("2026-01-01", "BUY", "X", 3, 10, "1.5", 0),
        ("2026-01-02", "SELL", "X", 1, 12, "0.5", 0),
    ))
    x = r.positions["X"]
    # buy cost 31.5 (fee included); selling 1 of 3 removes 10.5; realized = 12 - 0.5 - 10.5
    assert x.realized == 1 and x.cost == 21 and x.quantity == 2 and x.avg_cost == D("10.5")
    assert r.fees == 2 and r.cash == D("-20")


def test_sell_everything_then_buy_again():
    r = replay(txns(
        ("2026-01-01", "BUY", "X", 10, 100, 0, 0),
        ("2026-01-02", "SELL", "X", 10, 120, 5, 0),
        ("2026-01-03", "BUY", "X", 5, 90, 1, 0),
    ))
    x = r.positions["X"]
    assert x.realized == 195  # 1200 - 5 - 1000
    assert x.quantity == 5 and x.cost == 451 and x.avg_cost == D("90.2")  # the old cost does not carry over


def test_several_round_trips_bought_and_sold_in_batches():
    r = replay(txns(
        # round 1: two buys, then sold off in two batches
        ("2026-01-10", "BUY", "X", 10, 100, 0, 0),
        ("2026-02-10", "BUY", "X", 10, 120, 0, 0),  # 20 shares, average 110
        ("2026-03-01", "SELL", "X", 5, 130, 0, 0),  # +100
        ("2026-04-01", "SELL", "X", 15, 90, 0, 0),  # -300, position closed
        # round 2, some months later: a fresh average from the new buys only
        ("2026-06-01", "BUY", "X", 10, 80, 0, 0),
        ("2026-07-01", "BUY", "X", 10, 100, 0, 0),  # 20 shares, average 90 (the old 110 is forgotten)
        ("2026-08-01", "SELL", "X", 5, 110, 0, 0),  # +100
    ))
    x = r.positions["X"]
    assert [row.realized for row in r.rows if row.txn.type == "SELL"] == [100, -300, 100]
    assert [row.avg_cost_after for row in r.rows] == [100, 110, 110, 0, 80, 90, 90]
    assert x.realized == -100  # lifetime total across both rounds
    assert x.quantity == 15 and x.cost == 1350 and x.avg_cost == 90
    assert valuation(r, {"X": D(105)}).unrealized == 225  # only the shares still held: 15 x (105 - 90)
    assert r.cash == -1000 - 1200 + 650 + 1350 - 800 - 1000 + 550


def test_symbol_change_moves_the_position():
    r = replay(txns(
        ("2026-01-02", "DEPOSIT", "", 0, 0, 0, 2000),
        ("2026-01-05", "BUY", "PSKY", 100, 11, 1, 0),
        ("2026-02-01", "SELL", "PSKY", 20, 13, 0, 0),  # +39.80 realized while still PSKY (260 - 20 x 11.01)
        ("2026-03-01", "DIVIDEND", "PSKY", 0, 0, 0, 4),
    ) + [Txn(date="2026-04-01", type="SYMBOL_CHANGE", symbol="PSKY", symbol2="NEWT", quantity=D(80), id=5),
         Txn(date="2026-04-01", type="SHARES_IN", symbol="NEWTW", quantity=D(80), price=D(0), id=6),  # free warrants
         Txn(date="2026-05-01", type="SELL", symbol="NEWT", quantity=D(30), price=D(15), id=7)])
    old, new, warrants = r.positions["PSKY"], r.positions["NEWT"], r.positions["NEWTW"]
    assert old.quantity == 0 and old.cost == 0 and not old.is_open
    assert old.realized == D("39.80") and old.dividends == 4  # history stays with the old symbol
    # 80 shares carried over at cost 880.80 (avg 11.01); then 30 sold at 15
    assert new.quantity == 50 and new.cost == D("550.50") and new.realized == D("119.70")
    assert warrants.quantity == 80 and warrants.cost == 0
    change = r.rows[4]
    assert change.qty_after == 80 and change.avg_cost_after == D("11.01") and change.txn.cash_change == 0
    assert [p.symbol for p in r.open_positions] == ["NEWT", "NEWTW"]
    assert r.realized == D("39.80") + D("119.70")


def test_symbol_change_with_an_exchange_ratio():
    r = replay(txns(("2026-01-05", "BUY", "OLD", 10, 30, 0, 0)) + [
        Txn(date="2026-02-01", type="SYMBOL_CHANGE", symbol="OLD", symbol2="NEW", quantity=D(5), id=2)])  # 2 old -> 1 new
    assert r.positions["NEW"].quantity == 5 and r.positions["NEW"].avg_cost == 60  # same total cost


def test_symbol_change_checks():
    def change(**kw):
        return Txn(date="2026-02-01", type="SYMBOL_CHANGE", **{"symbol": "OLD", "symbol2": "NEW", "quantity": D(1), **kw})

    change().validate()
    raises(ValueError, change(symbol2=" ").validate, match="Please enter the new symbol")
    raises(ValueError, change(symbol2="old").validate, match="must differ")
    raises(ValueError, change(quantity=D(0)).validate, match="Quantity must be greater than 0")
    assert change(symbol2=" new ", price=D(5)).normalized().symbol2 == "NEW"
    assert Txn(date="2026-01-01", type="BUY", symbol2="X").normalized().symbol2 == ""  # only kept where it belongs
    raises(LedgerError, replay, [change(id=1)], match="no shares held to change into NEW")


def distribution(pct, qty=1000, **kw):
    return Txn(date="2026-02-01", type="DISTRIBUTION",
               **{"symbol": "SKYD", "symbol2": "SKYD.WT", "quantity": D(qty), "price": D(str(pct)), **kw})


def test_distribution_moves_part_of_the_cost():
    r = replay(txns(("2026-01-05", "BUY", "SKYD", 1000, 10, 0, 0)) + [
        distribution(10, id=2),  # 1 warrant per share; 10% of the cost goes to the warrants
        Txn(date="2026-03-01", type="SELL", symbol="SKYD.WT", quantity=D(1000), price=D("1.5"), id=3)])
    stock, warrants = r.positions["SKYD"], r.positions["SKYD.WT"]
    assert stock.quantity == 1000 and stock.cost == 9000 and stock.avg_cost == 9  # shares unchanged
    assert warrants.quantity == 0 and warrants.realized == 500  # 1500 proceeds - 1000 cost
    row = r.rows[1]
    assert row.qty_after == 1000 and row.avg_cost_after == 1 and row.txn.cash_change == 0
    assert row.source_after == (1000, 9)
    assert r.cash == -10000 + 1500


def test_distribution_at_zero_cost():
    r = replay(txns(("2026-01-05", "BUY", "SKYD", 10, 10, 1, 0)) + [distribution(0, qty=5, id=2)])
    assert r.positions["SKYD"].cost == 101 and r.positions["SKYD.WT"].cost == 0
    assert r.positions["SKYD.WT"].quantity == 5 and r.total_cost == 101


def test_distribution_checks():
    distribution(0).validate()
    distribution(100).validate()
    raises(ValueError, distribution(-1).validate, match="between 0 and 100%")
    raises(ValueError, distribution("100.01").validate, match="between 0 and 100%")
    raises(ValueError, distribution(10, symbol2="").validate, match="Please enter the new symbol")
    raises(ValueError, distribution(10, symbol2="skyd").validate, match="must differ")
    raises(ValueError, distribution(10, qty=0).validate, match="Quantity must be greater than 0")
    assert distribution(10, fee=D(1), amount=D(2)).normalized().price == 10  # the percent is kept
    raises(LedgerError, replay, [distribution(10, id=1)], match="no shares held at the time of the distribution")


def test_combine_results_adds_accounts_up():
    one = replay(txns(
        ("2026-01-02", "DEPOSIT", "", 0, 0, 0, 1000),
        ("2026-01-05", "BUY", "X", 10, 10, 1, 0),  # cash 899, X: 10 shares cost 101
        ("2026-01-06", "DIVIDEND", "X", 0, 0, 0, 5),
        ("2026-01-07", "INTEREST", "", 0, 0, 0, 2),
    ))
    two = replay(txns(
        ("2026-01-03", "DEPOSIT", "", 0, 0, 0, 500),
        ("2026-01-04", "BUY", "X", 30, 20, 0, 0),
        ("2026-01-04", "BUY", "Y", 1, 100, 0, 0),
        ("2026-02-01", "SELL", "X", 10, 25, 2, 0),  # cost out 200, realized 250 - 2 - 200 = 48; 20 shares cost 400 left
        ("2026-02-02", "WITHDRAW", "", 0, 0, 0, 50),
    ))
    total = combine_results([one, two])
    assert total.cash == 906 + -2 and (total.deposits, total.withdrawals, total.interest, total.fees) == (1500, 50, 2, 3)
    x = total.positions["X"]  # held in both accounts: one position, average cost = total cost / total shares
    assert (x.quantity, x.cost, x.realized, x.dividends) == (30, 501, 48, 5) and x.avg_cost == D("16.7")
    assert total.positions["Y"].quantity == 1 and [p.symbol for p in total.open_positions] == ["X", "Y"]
    assert total.net_deposits == 1450 and total.realized == 48 and total.total_cost == 601
    assert len(total.rows) == 9 and [r.txn.date for r in total.rows] == sorted(r.txn.date for r in total.rows)
    assert one.positions["X"].quantity == 10 and two.positions["X"].quantity == 20  # the accounts are left alone
    empty = combine_results([])
    assert empty.cash == 0 and not empty.positions and not empty.rows


def test_combine_series_adds_accounts_up():
    first = [ValuePoint(1, 10.0, 10.0), ValuePoint(2, 11.0, 10.0), ValuePoint(3, 12.0, 10.0)]
    later = [ValuePoint(2, 5.0, 4.0), ValuePoint(3, 6.0, 4.0)]  # opened after the first point: adds nothing before that
    out = combine_series([first, later])
    assert [(p.time, p.value, p.net_deposits) for p in out] == [(1, 10, 10), (2, 16, 14), (3, 18, 14)]
    assert first[1].value == 11.0 and combine_series([]) == []  # inputs untouched


def test_crypto_amounts():
    r = replay(txns(
        ("2026-01-02", "DEPOSIT", "", 0, 0, 0, 100),
        ("2026-01-03", "BUY", "BTC-USD", "0.00012345", "84792.74", 0, 0),
        ("2026-01-04", "SELL", "BTC-USD", "0.00002345", 90000, 0, 0),
    ))
    btc = r.positions["BTC-USD"]
    assert btc.quantity == D("0.0001") and fmt_qty(btc.quantity) == "0.0001"
    assert r.cash == 100 - D("0.00012345") * D("84792.74") + D("0.00002345") * 90000
    assert btc.cost + (D("0.00012345") * D("84792.74") - btc.cost) == D("0.00012345") * D("84792.74")


def test_average_cost_rounding_stays_exact():
    r = replay(txns(
        ("2026-01-01", "BUY", "X", 3, 10, 0, 0),
        ("2026-01-02", "BUY", "X", 3, 11, 0, 0),
        ("2026-01-03", "SELL", "X", 1, 12, 0, 0),
        ("2026-01-04", "SELL", "X", 1, 12, 0, 0),
        ("2026-01-05", "SELL", "X", 4, 12, 0, 0),
    ))
    x = r.positions["X"]
    # whatever the intermediate thirds, closing the position realizes exactly proceeds - total cost
    assert x.quantity == 0 and x.cost == 0
    assert x.realized == 72 - 63


def test_gifted_shares_have_zero_cost():
    r = replay(txns(
        ("2026-01-01", "SHARES_IN", "X", 4, 0, 0, 0),
        ("2026-01-02", "SELL", "X", 4, 25, 0, 0),
    ))
    assert r.positions["X"].realized == 100 and r.cash == 100


def test_shares_out_moves_cost_without_realizing():
    r = replay(txns(
        ("2026-01-01", "DEPOSIT", "", 0, 0, 0, 100),
        ("2026-01-02", "BUY", "X", 4, 25, 0, 0),
        ("2026-01-03", "SHARES_OUT", "X", 1, 0, 0, 0),
    ))
    x = r.positions["X"]
    assert x.quantity == 3 and x.cost == 75 and x.realized == 0
    assert r.cash == 0  # the transfer does not touch cash


def test_split_and_reverse_split():
    r = replay(txns(
        ("2026-01-01", "BUY", "X", 10, 5, 0, 0),
        ("2026-02-01", "SPLIT", "X", -8, 0, 0, 0),  # 1-for-5 reverse split: 10 -> 2 shares
    ))
    x = r.positions["X"]
    assert x.quantity == 2 and x.cost == 50 and x.avg_cost == 25 and r.cash == -50

    r = replay(txns(
        ("2026-01-01", "BUY", "X", 3, 90, 0, 0),
        ("2026-02-01", "SPLIT", "X", 6, 0, 0, 0),  # 3-for-1
    ))
    assert r.positions["X"].quantity == 9 and r.positions["X"].avg_cost == 30


def test_inconsistent_ledgers_are_rejected():
    raises(LedgerError, replay, sample_txns() + [Txn(date="2026-07-01", type="SELL", symbol="AAPL", quantity=D(51), price=D(50))],
           match="only 50 shares were held")
    raises(LedgerError, replay, txns(("2026-01-01", "SELL", "X", 1, 10, 0, 0)), match="only 0 shares")
    raises(LedgerError, replay, txns(
        ("2026-01-01", "BUY", "X", 2, 10, 0, 0),
        ("2026-01-02", "SHARES_OUT", "X", 3, 0, 0, 0),
    ), match="Shares Out 3 shares of X")
    raises(LedgerError, replay, txns(("2026-01-01", "SPLIT", "X", 2, 0, 0, 0)), match="no shares held")
    raises(LedgerError, replay, txns(
        ("2026-01-01", "BUY", "X", 10, 5, 0, 0),
        ("2026-02-01", "SPLIT", "X", -10, 0, 0, 0),
    ), match="reverse split removes 10 shares")
    # a sale dated before the purchase is caught even when it was entered later
    raises(LedgerError, replay, txns(
        ("2026-01-05", "BUY", "X", 10, 5, 0, 0),
        ("2026-01-04", "SELL", "X", 1, 5, 0, 0),
    ), match="2026-01-04")


def test_same_day_order_follows_entry_order():
    a, b = txns(("2026-01-01", "BUY", "X", 1, 10, 0, 0), ("2026-01-01", "SELL", "X", 1, 11, 0, 0))
    assert replay([b, a]).positions["X"].realized == 1  # sorted back to buy (id 1), then sell (id 2)
    a.id, b.id = 2, 1
    raises(LedgerError, replay, [a, b])  # now the sell comes first that day
    unsaved = Txn(date="2026-01-01", type="SELL", symbol="X", quantity=D(1), price=D(12))
    late = Txn(date="2026-01-01", type="BUY", symbol="X", quantity=D(1), price=D(10), id=999)
    assert sort_key(unsaved) > sort_key(late)  # a transaction being added goes last that day
    assert replay([unsaved, late]).rows[-1].txn is unsaved


def test_dividends_and_closed_positions():
    r = replay(txns(
        ("2026-01-01", "BUY", "B", 1, 10, 0, 0),
        ("2026-01-01", "BUY", "A", 1, 10, 0, 0),
        ("2026-01-02", "SELL", "A", 1, 12, 0, 0),
        ("2026-01-20", "DIVIDEND", "A", 0, 0, 0, "0.30"),  # paid after the sale (record date earlier)
        ("2026-01-21", "DIVIDEND", "B", 0, 0, 0, "0.20"),
    ))
    assert r.positions["A"].dividends == D("0.30") and not r.positions["A"].is_open
    assert r.dividends == D("0.50") and r.realized == 2
    assert [p.symbol for p in r.all_positions] == ["B", "A"]  # open first, then closed
    assert [p.symbol for p in r.open_positions] == ["B"]
    assert r.total_cost == 10  # closed positions are left out


def test_cash_can_go_negative():
    r = replay(txns(("2026-01-01", "BUY", "X", 1, 100, 0, 0)))  # margin, or a deposit not yet entered
    assert r.cash == -100


def test_fractional_shares_close_exactly():
    r = replay(txns(
        ("2026-01-01", "DEPOSIT", "", 0, 0, 0, 100),
        ("2026-01-02", "BUY", "VOO", "0.1", 500, 0, 0),
        ("2026-01-03", "BUY", "VOO", "0.2", 510, 0, 0),
        ("2026-01-04", "SELL", "VOO", "0.3", 520, 0, 0),
    ))
    assert r.positions["VOO"].quantity == 0 and r.positions["VOO"].cost == 0
    assert r.open_positions == []
    assert r.cash == D("104.00")


def test_totals_by_category():
    r = replay(sample_txns())
    assert r.deposits == 10000 and r.withdrawals == 1000 and r.net_deposits == 9000
    assert isinstance(r, LedgerResult) and len(r.rows) == 12


# ----------------------------------------------------------------------
# Valuation
# ----------------------------------------------------------------------
def test_valuation_with_missing_prices():
    r = replay(txns(
        ("2026-01-01", "BUY", "B", 2, 50, 0, 0),
        ("2026-01-01", "BUY", "A", 10, 10, 0, 0),
        ("2026-01-01", "BUY", "C", 1, 7, 0, 0),
    ))
    v = valuation(r, {"A": D(12), "Z": D(999)})  # Z is not held and is ignored
    assert v.market_value == 120 + 100 + 7  # B and C counted at cost
    assert v.unrealized == 20  # only A has a price
    assert v.missing == ["B", "C"]
    v = valuation(r, {"A": D(8), "B": D(40), "C": D(7)})
    assert v.unrealized == -20 - 20 + 0 and v.missing == []


# ----------------------------------------------------------------------
# Value over time (the chart)
# ----------------------------------------------------------------------
def test_value_series():
    rows = replay(txns(
        ("2026-01-02", "DEPOSIT", "", 0, 0, 0, 1000),
        ("2026-01-05", "BUY", "XYZ", 10, 40, 0, 0),
        ("2026-01-07", "SPLIT", "XYZ", 10, 0, 0, 0),  # 2-for-1
    )).rows
    # Yahoo's split-adjusted closes: real price 42 on the 6th shows as 21
    prices = {"XYZ": [(ts("2026-01-01"), 19.0), (ts("2026-01-06"), 21.0), (ts("2026-01-08"), 22.0)]}
    pts = value_series(rows, prices)
    assert [p.time for p in pts] == [ts("2026-01-06"), ts("2026-01-08")]  # nothing before the first transaction
    assert pts[0].value == 600 + 10 * 2 * 21.0  # 10 pre-split shares, worth 42 each
    assert pts[1].value == 600 + 20 * 22.0
    assert pts[1].net_deposits == 1000


def test_value_series_reverse_split():
    rows = replay(txns(
        ("2026-01-02", "BUY", "X", 10, 5, 0, 0),
        ("2026-01-04", "SPLIT", "X", -8, 0, 0, 0),  # 1-for-5
    )).rows
    prices = {"X": [(ts("2026-01-03"), 25.0), (ts("2026-01-05"), 26.0)]}  # adjusted: real 5 shows as 25
    pts = value_series(rows, prices)
    assert pts[0].value == -50 + 10 * 0.2 * 25.0
    assert pts[1].value == -50 + 2 * 26.0


def test_value_series_empty_and_before_start():
    assert value_series([], {"X": [(ts("2026-01-01"), 1.0)]}) == []
    rows = replay(txns(("2026-03-01", "DEPOSIT", "", 0, 0, 0, 5))).rows
    assert value_series(rows, {"X": [(ts("2026-01-01"), 1.0)]}) == []
    assert value_series(rows, {}) == []  # no timestamps to value at


def test_value_series_cash_flows_and_fallbacks():
    rows = replay(txns(
        ("2026-01-02", "DEPOSIT", "", 0, 0, 0, 1000),
        ("2026-01-02", "BUY", "A", 2, 100, 0, 0),
        ("2026-01-02", "BUY", "B", 3, 10, 0, 0),
        ("2026-01-02", "BUY", "C", 1, 50, 0, 0),
        ("2026-01-03", "WITHDRAW", "", 0, 0, 0, 100),
    )).rows
    # A has a series; B and C do not; B has a manual price; C falls back to its average cost
    prices = {"A": [(ts("2026-01-02"), 110.0), (ts("2026-01-03"), 120.0)]}
    pts = value_series(rows, prices, fallback={"B": D(12)})
    cash_day1 = 1000 - 200 - 30 - 50
    assert pts[0].value == cash_day1 + 2 * 110 + 3 * 12 + 50  # same-day trades all count by that day
    assert pts[0].net_deposits == 1000
    assert pts[1].value == cash_day1 - 100 + 2 * 120 + 3 * 12 + 50
    assert pts[1].net_deposits == 900


def test_value_series_carries_last_close_forward():
    rows = replay(txns(
        ("2026-01-02", "BUY", "A", 1, 10, 0, 0),
        ("2026-01-02", "BUY", "B", 1, 20, 0, 0),
    )).rows
    prices = {
        "A": [(ts("2026-01-05", 10), 11.0), (ts("2026-01-05", 12), 12.0)],
        "B": [(ts("2026-01-05", 11), 21.0)],  # B trades at different times from A
    }
    pts = value_series(rows, prices)
    assert [p.value for p in pts] == [-30 + 11 + 20, -30 + 11 + 21, -30 + 12 + 21]


def test_value_series_symbol_change():
    rows = replay(txns(("2026-01-02", "BUY", "OLD", 10, 10, 0, 0)) + [
        Txn(date="2026-01-04", type="SYMBOL_CHANGE", symbol="OLD", symbol2="NEW", quantity=D(10), id=2)]).rows
    prices = {"OLD": [(ts("2026-01-03"), 11.0), (ts("2026-01-05"), 99.0)],  # old ticker's stale last print
              "NEW": [(ts("2026-01-05"), 12.0)]}
    pts = value_series(rows, prices)
    assert [p.value for p in pts] == [-100 + 10 * 11.0, -100 + 10 * 12.0]  # valued by the symbol held that day


def test_value_series_distribution():
    rows = replay(txns(("2026-01-02", "BUY", "SKYD", 1000, 10, 0, 0)) + [distribution(20, id=2)]).rows
    prices = {"SKYD": [(ts("2026-01-05"), 9.0), (ts("2026-02-05"), 8.0)]}
    pts = value_series(rows, prices)
    # warrants have no price: valued at their average cost, 2000 / 1000 = 2
    assert [p.value for p in pts] == [-10000 + 1000 * 9.0, -10000 + 1000 * 8.0 + 1000 * 2.0]
    pts = value_series(rows, {**prices, "SKYD.WT": [(ts("2026-02-05"), 1.5)]})
    assert pts[-1].value == -10000 + 1000 * 8.0 + 1000 * 1.5


def test_value_series_after_position_closed():
    rows = replay(txns(
        ("2026-01-02", "DEPOSIT", "", 0, 0, 0, 100),
        ("2026-01-02", "BUY", "A", 1, 100, 0, 0),
        ("2026-01-03", "SELL", "A", 1, 110, 0, 0),
    )).rows
    pts = value_series(rows, {"A": [(ts("2026-01-02"), 105.0), (ts("2026-01-04"), 200.0)]})
    assert [p.value for p in pts] == [105.0, 110.0]  # once sold, later prices no longer matter


# ----------------------------------------------------------------------
# Display formatting
# ----------------------------------------------------------------------
def test_formatting_and_dates():
    assert fmt_money(D("1234567.891")) == "1,234,567.89"
    assert fmt_money(D("-0.001")) == "0.00"
    assert fmt_money(D("5"), sign=True) == "+5.00"
    assert fmt_qty(D("100.000")) == "100"
    assert fmt_qty(D("0.123456789")) == "0.12345679"  # 8 places, enough for bitcoin
    assert fmt_price(D("12.5")) == "12.50"
    assert parse_date("2026/9/3") == "2026-09-03"


def test_fmt_money():
    assert fmt_money(None) == "-"
    assert fmt_money(D("0.005")) == "0.01"  # half up, not banker's rounding
    assert fmt_money(D("0.015")) == "0.02"
    assert fmt_money(D("-1234.5")) == "-1,234.50"
    assert fmt_money(D("-5"), sign=True) == "-5.00"
    assert fmt_money(D("0"), sign=True) == "0.00"
    assert fmt_money(D("-0.004"), sign=True) == "0.00"


def test_fmt_qty_price_pct():
    assert fmt_qty(None) == "-"
    assert fmt_qty(D("1234.5")) == "1,234.5"
    assert fmt_qty(D("0.000000001")) == "0"
    assert fmt_qty(D("0.00012345")) == "0.00012345"
    assert fmt_qty(D("3"), sign=True) == "+3" and fmt_qty(D("-3"), sign=True) == "-3"
    assert fmt_qty(D("1E+3")) == "1,000"  # no scientific notation
    assert fmt_price(None) == "-"
    assert fmt_price(D("3")) == "3.00"
    assert fmt_price(D("0.1")) == "0.10"
    assert fmt_price(D("1234.56789")) == "1,234.5679"
    assert fmt_price(D("0.00005")) == "0.0001"
    assert fmt_pct(None) == "-"
    assert fmt_pct(D("0.1234")) == "+12.34%"
    assert fmt_pct(D("-0.05")) == "-5.00%"
    assert fmt_pct(D("0")) == "+0.00%"


# ----------------------------------------------------------------------
# Periods (the time filter of the transaction list)
# ----------------------------------------------------------------------
def test_add_months():
    assert add_months(date(2026, 10, 18), -1) == date(2026, 9, 18)
    assert add_months(date(2026, 1, 15), -1) == date(2025, 12, 15)  # across a year
    assert add_months(date(2026, 3, 31), -1) == date(2026, 2, 28)  # a day the month lacks becomes its last
    assert add_months(date(2028, 3, 31), -1) == date(2028, 2, 29)  # leap year
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2024, 2, 29), -12) == date(2023, 2, 28)
    assert add_months(date(2026, 5, 31), -12) == date(2025, 5, 31)


def test_period_range():
    on = date(2026, 10, 18)
    assert period_range("ALL", on) == (None, None)
    assert period_range("1M", on) == ("2026-09-18", "2026-10-18")  # both ends included
    assert period_range("3M", on) == ("2026-07-18", "2026-10-18")
    assert period_range("6M", on) == ("2026-04-18", "2026-10-18")
    assert period_range("1Y", on) == ("2025-10-18", "2026-10-18")
    assert period_range("2025", on) == ("2025-01-01", "2025-12-31")  # a calendar year, whatever today is
    assert period_range("CUSTOM", on) == (None, None)  # its dates come from the boxes
    assert period_range("1M")[1] == date.today().isoformat()  # counted from today by default
    assert list(PERIODS) == ["ALL", "1M", "3M", "6M", "1Y"]


# ----------------------------------------------------------------------
# Finance (income and expenses outside the brokerage accounts)
# ----------------------------------------------------------------------
def test_parse_month_and_add_month():
    for text in ("2026-09", "2026/9", "2026.09", "202609", " 2026-9 "):
        assert parse_month(text) == "2026-09", text
    for bad in ("", None, "2026-13", "2026-00", "26-09", "2026", "September", "2026-09-30", "2026091"):
        raises(ValueError, parse_month, bad, match="Invalid month")
    assert add_month("2026-09") == "2026-10" and add_month("2026-12") == "2027-01"
    assert add_month("2026-01", -1) == "2025-12" and add_month("2026-03", 12) == "2027-03"


def test_eval_amount():
    assert eval_amount("") == 0 and eval_amount(None) == 0 and eval_amount("   ") == 0
    assert eval_amount("12") == 12 and eval_amount("-5") == -5 and eval_amount("+5") == 5
    assert eval_amount("1250.50+1250.50") == D("2501.00")
    assert eval_amount("120.40 + 85.25 + 40.5 - 10.15") == D("236.00")  # a refund taken off
    assert eval_amount("1500+100-400") == 1200
    assert eval_amount("1,234.5+$2") == D("1236.50")  # thousands separators and $ are ignored
    assert eval_amount("（1＋2）×3") == 9  # full-width characters from a Chinese input method
    assert eval_amount("2*(3+4)") == 14 and eval_amount("2*-3") == -6 and eval_amount("-(1+2)") == -3
    assert eval_amount("0.1+0.2") == D("0.30")  # exact, unlike float
    assert eval_amount(".5") == D("0.5") and eval_amount("5.") == 5
    assert eval_amount("10/4") == D("2.50") and eval_amount("1/3") == D("0.33") and eval_amount("2/3") == D("0.67")
    assert eval_amount("0.005") == D("0.01") and eval_amount("0.004") == 0  # rounded to cents, halves up
    assert str(eval_amount("5")) == "5.00"
    for bad in ("abc", "1+", "+", "(1", "1)", "()", "1..2", "1+*2", "5%", "1e3", "=1+2", "9" * 40):
        raises(ValueError, eval_amount, bad, match="not a valid number")
    raises(ValueError, eval_amount, "1/0", match="divide by zero")
    raises(ValueError, eval_amount, "(1+1)/(2-2)", match="divide by zero")


def test_entry_from_text():
    e = entry_from_text("1250.50 + 1250.50", " bonus included \n")
    assert (e.amount, e.expr, e.comment) == (D("2501.00"), "1250.50+1250.50", "bonus included")
    e = entry_from_text("1,234.50")
    assert (e.amount, e.expr, e.comment) == (D("1234.50"), "", "")  # a plain number keeps no sum
    assert entry_from_text("-5").expr == "" and entry_from_text("(5)").expr == "(5)"
    assert entry_from_text("").is_empty and entry_from_text("5-5").is_empty  # nothing to store
    assert not entry_from_text("", "only a comment").is_empty and not entry_from_text("3").is_empty
    raises(ValueError, entry_from_text, "x", match="not a valid number")


def _finance_fixture():
    cats = [FinCategory(1, "income", "Salary"), FinCategory(2, "income", "Interest"),
            FinCategory(3, "expense", "Card"), FinCategory(4, "expense", "Tax")]
    months = [  # out of order on purpose
        FinMonth("2025-02", None, {1: FinEntry(D(500)), 3: FinEntry(D(100), comment="x")}),
        FinMonth("2025-01", D(1000), {1: FinEntry(D(300), "100+200"), 2: FinEntry(D(5)), 4: FinEntry(D(50))}),
        FinMonth("2025-04", None, {2: FinEntry(D(7))}),
        FinMonth("2025-03", D(2000), {}),  # a typed opening balance breaks the chain
    ]
    return cats, months


def test_finance_rows_carry_balances_forward():
    cats, months = _finance_fixture()
    jan, feb, mar, apr = finance_rows(months, cats)
    assert [r.month.month for r in (jan, feb, mar, apr)] == ["2025-01", "2025-02", "2025-03", "2025-04"]
    assert (jan.opening, jan.income, jan.expenses, jan.ending) == (1000, 305, 50, 1255)
    assert (feb.opening, feb.income, feb.expenses, feb.ending) == (1255, 500, 100, 1655)  # carried from January
    assert (mar.opening, mar.ending) == (2000, 2000)  # the typed figure replaces the carried 1655
    assert (apr.opening, apr.ending, apr.net) == (2000, 2007, 7)
    months[1].entries[1] = FinEntry(D(400))  # editing January changes every balance up to the next typed one
    jan, feb, mar, apr = finance_rows(months, cats)
    assert (jan.ending, feb.opening, feb.ending, mar.opening) == (1355, 1355, 1755, 2000)
    assert finance_rows([], cats) == []
    ghost = FinMonth("2025-01", D(0), {99: FinEntry(D(1000)), 1: FinEntry(D(1))})  # a category that is gone
    assert finance_rows([ghost], cats)[0].ending == 1


def test_month_periods():
    assert month_of("2026-09") == "2026-09" and month_of("2026/9") == "2026-09" and month_of("202609") == "2026-09"
    assert month_of("2026-09-30") == "2026-09" and month_of("2026.9.3") == "2026-09"  # a whole date means its month
    for bad in ("", "2026", "2026-13", "2026-02-30", "soon"):
        raises(ValueError, month_of, bad, match="Invalid month")
    assert list(FINANCE_PERIODS) == ["ALL", "3M", "6M", "1Y"]
    assert month_range("ALL", "2026-10") == (None, None) and month_range("CUSTOM", "2026-10") == (None, None)
    assert month_range("3M", "2026-10") == ("2026-08", "2026-10")  # this month and the two before it
    assert month_range("6M", "2026-10") == ("2026-05", "2026-10")
    assert month_range("1Y", "2026-10") == ("2025-11", "2026-10")
    assert month_range("1Y", "2026-03") == ("2025-04", "2026-03")  # across a year
    assert month_range("2025", "2026-10") == ("2025-01", "2025-12")
    cats, months = _finance_fixture()
    rows = finance_rows(months, cats)
    pick = lambda first, last: [r.month.month for r in period_months(rows, first, last)]
    assert pick(None, None) == ["2025-01", "2025-02", "2025-03", "2025-04"]
    assert pick("2025-02", "2025-03") == ["2025-02", "2025-03"]  # both ends included
    assert pick("2025-03", None) == ["2025-03", "2025-04"] and pick(None, "2025-01") == ["2025-01"]
    assert pick("2026-01", None) == [] and pick("2025-04", "2025-02") == []
    part = summarize(period_months(rows, "2025-02", "2025-03"))  # what a tax return would be checked against
    assert (part.months, part.income, part.expenses) == (2, 500, 100)
    assert (part.opening, part.ending) == (1255, 2000)  # the balance the period began and ended with


def test_summarize_months():
    cats, months = _finance_fixture()
    s = summarize(finance_rows(months, cats))
    assert (s.months, s.income, s.expenses, s.net) == (4, 812, 150, 662)
    assert (s.opening, s.ending) == (1000, 2007)
    assert s.by_category == {1: 800, 2: 12, 3: 100, 4: 50}
    empty = summarize([])
    assert (empty.months, empty.income, empty.opening, empty.ending, empty.by_category) == (0, 0, None, None, {})


# ----------------------------------------------------------------------
# CSV files
# ----------------------------------------------------------------------
def _records(table):
    """A table as (header, [{title: cell}, ...])."""
    header, rows = table
    assert all(len(r) == len(header) for r in rows)  # a plain rectangle: nothing a spreadsheet would misplace
    return header, [dict(zip(header, r)) for r in rows]


def test_csv_transactions_table():
    res = replay(sample_txns())
    header, rows = _records(transaction_table("Main", res))
    assert header == list(TXN_HEADERS) and len(rows) == len(res.rows)
    assert [r["Account"] for r in rows] == ["Main"] * len(rows) and rows[0]["Year"] == "2026"
    deposit, shares_in, buy, _, sell = rows[0], rows[1], rows[2], rows[3], rows[4]
    # a type leaves out what it does not use, instead of writing zeros
    assert (deposit["Date"], deposit["Type"], deposit["Symbol"], deposit["Quantity"], deposit["Price"], deposit["Fee"]) == (
        "2026-01-02", "Deposit", "", "", "", "")
    assert (deposit["Amount"], deposit["Cash Change"], deposit["Cash Balance"], deposit["Net Proceeds"]) == (
        "10000.00", "10000.00", "10000.00", "")
    assert (shares_in["Quantity"], shares_in["Price"], shares_in["Cash Change"]) == ("10", "150", "0.00")
    assert (buy["Quantity"], buy["Price"], buy["Fee"], buy["Amount"], buy["Cash Change"], buy["Cash Balance"]) == (
        "10", "170", "1.00", "", "-1701.00", "8299.00")
    assert (buy["Net Proceeds"], buy["Cost Sold"], buy["Realized P/L"]) == ("", "", "")  # only a sale has these
    # a sale: 5 x 200 - 1 fee; 5 of the 20 shares held at an average cost of 160.05
    assert (sell["Net Proceeds"], sell["Cost Sold"], sell["Realized P/L"]) == ("999.00", "800.25", "198.75")
    assert (sell["Cash Change"], sell["Fee"]) == ("999.00", "1.00")
    for r in rows:
        if r["Type"] == "Sell":
            assert D(r["Net Proceeds"]) - D(r["Cost Sold"]) == D(r["Realized P/L"])
    assert rows[-1]["Cash Balance"] == f"{res.cash:.2f}"
    split = next(r for r in rows if r["Type"] == "Split")
    assert (split["Quantity"], split["Cash Change"]) == ("45", "0.00")
    dividend = next(r for r in rows if r["Type"] == "Dividend")
    assert (dividend["Symbol"], dividend["Amount"], dividend["Quantity"]) == ("AAPL", "3.75", "")


def test_csv_transactions_table_special_types():
    t = [Txn(date="2026-01-02", type="SHARES_IN", symbol="OLD", quantity=D(100), price=D(10), id=1),
         Txn(date="2026-02-01", type="DISTRIBUTION", symbol="OLD", symbol2="NEW", quantity=D(25), price=D(20), id=2),
         Txn(date="2026-03-01", type="SYMBOL_CHANGE", symbol="NEW", symbol2="NEWER", quantity=D(25), id=3,
             note='renamed, "quoted"')]
    _, rows = _records(transaction_table("A", replay(t)))
    shares_in, dist, change = rows
    assert (shares_in["Price"], shares_in["Cost Moved %"]) == ("10", "")
    # the percent of cost a distribution hands over is not a price
    assert (dist["Symbol"], dist["New Symbol"], dist["Quantity"], dist["Price"], dist["Cost Moved %"]) == (
        "OLD", "NEW", "25", "", "20")
    assert (change["Symbol"], change["New Symbol"], change["Quantity"], change["Cost Moved %"], change["Note"]) == (
        "NEW", "NEWER", "25", "", 'renamed, "quoted"')


def test_csv_holdings_table():
    res = replay(sample_txns())
    header, rows = _records(holding_table("Main", res, {"AAPL": D("210.5"), "MSFT": D(400)}, "2026-07-01"))
    assert header == list(HOLDING_HEADERS)
    aapl, msft, cash = rows  # open positions first, closed ones after; the cash is the last row
    assert (aapl["Account"], aapl["As Of"], aapl["Symbol"], aapl["Shares"]) == ("Main", "2026-07-01", "AAPL", "50")
    assert (aapl["Avg Cost"], aapl["Cost Basis"], aapl["Price"]) == ("40.0125", "2000.63", "210.5")
    assert (aapl["Market Value"], aapl["Unrealized P/L"], aapl["Realized P/L"], aapl["Dividends"]) == (
        "10525.00", "8524.38", "198.75", "3.75")
    # a closed position keeps what it earned, has no price or average cost
    assert (msft["Shares"], msft["Avg Cost"], msft["Cost Basis"], msft["Price"], msft["Market Value"]) == (
        "0", "", "0.00", "", "")
    assert (msft["Unrealized P/L"], msft["Realized P/L"]) == ("", "-100.00")
    assert (cash["Symbol"], cash["Market Value"], cash["Shares"], cash["Cost Basis"]) == ("Cash", "8192.98", "", "")
    assert f"{res.cash:.2f}" == "8192.98"
    _, unpriced = _records(holding_table("Main", res, {}, "2026-07-01"))
    assert (unpriced[0]["Price"], unpriced[0]["Market Value"], unpriced[0]["Unrealized P/L"]) == ("", "", "")


def test_csv_yearly_table_adds_up_by_year():
    res = replay(txns(
        ("2025-12-30", "DEPOSIT", "", 0, 0, 0, 5000),
        ("2025-12-31", "BUY", "X", 10, 100, 2, 0),
        ("2026-01-10", "SELL", "X", 4, 120, 1, 0),
        ("2026-02-01", "DIVIDEND", "X", 0, 0, 0, 5),
        ("2026-03-01", "INTEREST", "", 0, 0, 0, 2),
        ("2026-04-01", "FEE", "", 0, 0, 0, 7),
        ("2026-05-01", "WITHDRAW", "", 0, 0, 0, 100),
        ("2026-06-01", "SELL", "X", 6, 90, 1, 0),
    ))
    header, rows = _records(yearly_table("Main", res))
    assert header == list(YEARLY_HEADERS)
    y25, y26 = rows  # oldest year first
    assert (y25["Account"], y25["Year"], y25["Deposits"], y25["Commissions"], y25["Realized P/L"]) == (
        "Main", "2025", "5000.00", "2.00", "0.00")
    assert (y26["Year"], y26["Deposits"], y26["Withdrawals"], y26["Dividends"], y26["Interest"], y26["Fees"]) == (
        "2026", "0.00", "100.00", "5.00", "2.00", "7.00")
    # sold 4 (cost 400.80) and 6 (cost 601.20): proceeds 479 and 539
    assert (y26["Commissions"], y26["Net Proceeds"], y26["Cost Sold"], y26["Realized P/L"]) == (
        "2.00", "1018.00", "1002.00", "16.00")
    assert D(y26["Net Proceeds"]) - D(y26["Cost Sold"]) == D(y26["Realized P/L"]) == res.realized
    assert _records(yearly_table("Main", replay([])))[1] == []


def test_csv_stock_tables_follow_the_language():
    res = replay(sample_txns())
    try:
        i18n.set_language("zh")
        tables = stock_tables("主账户", res, {}, "2026-07-01")
        assert list(tables) == ["transactions", "holdings", "yearly"]
        assert tables["transactions"][0][:5] == ["账户", "日期", "年度", "类型", "代码"]
        assert tables["transactions"][1][0][3] == "存入" and tables["holdings"][1][-1][2] == "现金"
        assert tables["yearly"][0][:4] == ["账户", "年度", "存入", "取出"]
    finally:
        i18n.set_language("en")


def test_csv_finance_tables():
    cats, months = _finance_fixture()
    months.append(FinMonth("2026-01", None, {1: FinEntry(D(10))}))
    rows = finance_rows(months, cats)
    header, monthly = _records(monthly_table(rows, cats))
    assert header == ["Year", "Month", "Opening", "Salary", "Interest", "Total income", "Card", "Tax", "Total expenses",
                      "Ending balance"]
    assert [list(r.values()) for r in monthly] == [
        ["2025", "2025-01", "1000.00", "300.00", "5.00", "305.00", "", "50.00", "50.00", "1255.00"],
        ["2025", "2025-02", "1255.00", "500.00", "", "500.00", "100.00", "", "100.00", "1655.00"],
        ["2025", "2025-03", "2000.00", "", "", "0.00", "", "", "0.00", "2000.00"],  # a typed opening balance
        ["2025", "2025-04", "2000.00", "", "7.00", "7.00", "", "", "0.00", "2007.00"],
        ["2026", "2026-01", "2007.00", "10.00", "", "10.00", "", "", "0.00", "2017.00"],
    ]
    header, yearly = _records(finance_yearly_table(rows, cats))
    assert header == ["Year", "Months", "Opening", "Salary", "Interest", "Total income", "Card", "Tax", "Total expenses",
                      "Ending balance"]
    assert [list(r.values()) for r in yearly] == [
        ["2025", "4", "1000.00", "800.00", "12.00", "812.00", "100.00", "50.00", "150.00", "2007.00"],
        ["2026", "1", "2007.00", "10.00", "", "10.00", "", "", "0.00", "2017.00"],
    ]
    # a year's row is the sum of its months, and carries the first opening and last ending balance
    jan_to_apr = summarize(rows[:4])
    assert (D(yearly[0]["Total income"]), D(yearly[0]["Total expenses"])) == (jan_to_apr.income, jan_to_apr.expenses)
    header, entries = _records(entry_table(rows, cats))
    assert header == list(ENTRY_HEADERS)
    assert [(r["Month"], r["Type"], r["Category"], r["Amount"]) for r in entries] == [
        ("2025-01", "Income", "Salary", "300.00"), ("2025-01", "Income", "Interest", "5.00"),
        ("2025-01", "Expense", "Tax", "50.00"), ("2025-02", "Income", "Salary", "500.00"),
        ("2025-02", "Expense", "Card", "100.00"), ("2025-04", "Income", "Interest", "7.00"),
        ("2026-01", "Income", "Salary", "10.00")]
    assert (entries[0]["Year"], entries[0]["Calculation"], entries[4]["Comment"], entries[1]["Comment"]) == (
        "2025", "100+200", "x", "")
    assert list(finance_tables(rows, cats)) == ["monthly", "yearly", "entries"]
    assert _records(monthly_table([], cats))[1] == [] and _records(entry_table([], cats))[1] == []
    assert MONTHLY_HEADERS == ("Year", "Month") and FINANCE_YEARLY_HEADERS == ("Year", "Months")


def test_csv_files_open_in_excel():
    header, rows = ["Name", "Note"], [["a", "line one\nline two"], ["中文, \"quoted\"", ""]]
    with tempfile.TemporaryDirectory() as tmp:
        files = write_tables(tmp, "base", "20261022", {"one": (header, rows), "two": (["C"], [])})
        assert [f.name for f in files] == ["base_one_20261022.csv", "base_two_20261022.csv"]
        assert files[0].read_bytes().startswith(b"\xef\xbb\xbf")  # a BOM, so Excel reads it as UTF-8
        with open(files[0], newline="", encoding="utf-8-sig") as f:
            assert list(csv.reader(f)) == [header, *rows]
        with open(files[1], newline="", encoding="utf-8-sig") as f:
            assert list(csv.reader(f)) == [["C"]]


# ----------------------------------------------------------------------
# Storage
# ----------------------------------------------------------------------
def test_storage_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "t.db"
        db = Storage(db_path)
        opening = [Txn(date="2026-01-02", type="DEPOSIT", amount=D("10000.10"))]
        acc = db.create_account("Fidelity Individual", "Fidelity", "", opening)
        for t in sample_txns()[1:]:
            t.id = None
            t.account_id = acc
            db.add_txn(t)
        loaded = db.list_txns(acc)
        assert len(loaded) == 12
        assert replay(loaded).cash == D("8193.08")
        db.set_price("AAPL", D("45.5"))
        assert db.get_prices()["AAPL"][0] == D("45.5")
        db.set_prices({"AAPL": None, "MSFT": D("401.25")})
        assert set(db.get_prices()) == {"MSFT"}
        db.backup_to(Path(tmp) / "copy.db")
        with closing(Storage(Path(tmp) / "copy.db")) as backup:
            assert len(backup.list_txns(acc)) == 12
        db.delete_account(acc)
        assert db.list_txns(acc) == []
        db.close()
        assert daily_backup(db_path, Path(tmp) / "backups").exists()


def test_storage_edit_and_delete_transactions():
    with tempfile.TemporaryDirectory() as tmp:
        db = Storage(Path(tmp) / "t.db")
        acc = db.create_account("A")
        t = Txn(date="2026-01-05", type="BUY", symbol="X", quantity=D(1), price=D(10), account_id=acc, note="first")
        new_id = db.add_txn(t)
        assert t.id == new_id
        t.quantity, t.price, t.note, t.date = D(2), D("10.25"), "fixed", "2026-01-06"
        db.update_txn(t)
        (back,) = db.list_txns(acc)
        assert (back.id, back.date, back.quantity, back.price, back.note) == (new_id, "2026-01-06", 2, D("10.25"), "fixed")
        assert back.account_id == acc
        db.delete_txn(new_id)
        assert db.list_txns(acc) == []
        db.close()


def test_storage_symbol_change_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        db = Storage(Path(tmp) / "t.db")
        acc = db.create_account("A")
        t = Txn(date="2026-01-01", type="SYMBOL_CHANGE", symbol="PSKY", symbol2="NEWT", quantity=D(5), account_id=acc)
        db.add_txn(t)
        assert db.list_txns(acc)[0].symbol2 == "NEWT"
        t.symbol2 = "NEWU"
        db.update_txn(t)
        assert db.list_txns(acc)[0].symbol2 == "NEWU"
        db.close()


def test_storage_upgrades_an_old_database():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "old.db"
        old = sqlite3.connect(path)  # the transactions table as earlier versions made it (no symbol2)
        old.executescript("""
            CREATE TABLE accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
                broker TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')));
            CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE, date TEXT NOT NULL,
                type TEXT NOT NULL, symbol TEXT NOT NULL DEFAULT '', quantity TEXT NOT NULL DEFAULT '0',
                price TEXT NOT NULL DEFAULT '0', fee TEXT NOT NULL DEFAULT '0', amount TEXT NOT NULL DEFAULT '0',
                note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')));
            INSERT INTO accounts(name) VALUES ('Old');
            INSERT INTO transactions(account_id, date, type, symbol, quantity, price) VALUES (1, '2026-01-02', 'BUY', 'X', '3', '10.5');
        """)
        old.commit()
        old.close()
        db = Storage(path)
        (t,) = db.list_txns(1)
        assert (t.symbol, t.quantity, t.price, t.symbol2) == ("X", 3, D("10.5"), "")  # old record untouched
        db.add_txn(Txn(date="2026-02-01", type="SYMBOL_CHANGE", symbol="X", symbol2="Y", quantity=D(3), account_id=1))
        assert replay(db.list_txns(1)).positions["Y"].cost == D("31.5")
        db.close()
        Storage(path).close()  # opening again: nothing left to upgrade


def test_storage_keeps_decimals_exact():
    with tempfile.TemporaryDirectory() as tmp:
        db = Storage(Path(tmp) / "t.db")
        acc = db.create_account("A")
        db.add_txn(Txn(date="2026-01-01", type="BUY", symbol="X", quantity=D("0.00000001"), price=D("1E+3"),
                       fee=D("0.1"), account_id=acc))
        raw = db.conn.execute("SELECT quantity, price, fee FROM transactions").fetchone()
        assert tuple(raw) == ("0.00000001", "1000", "0.1")  # stored as plain text, no scientific notation
        (t,) = db.list_txns(acc)
        assert t.quantity == D("0.00000001") and t.price == 1000 and t.fee + D("0.2") == D("0.3")
        db.close()


def test_storage_orders_and_separates_accounts():
    with tempfile.TemporaryDirectory() as tmp:
        db = Storage(Path(tmp) / "t.db")
        a = db.create_account("A", "Fidelity", "main")
        b = db.create_account("B", opening=[Txn(date="2026-01-01", type="DEPOSIT", amount=D(5))])
        for day in ("2026-03-01", "2026-01-01", "2026-02-01"):  # entered out of order
            db.add_txn(Txn(date=day, type="DEPOSIT", amount=D(1), account_id=a))
        assert [t.date for t in db.list_txns(a)] == ["2026-01-01", "2026-02-01", "2026-03-01"]
        assert len(db.list_txns(b)) == 1
        assert [r["name"] for r in db.list_accounts()] == ["A", "B"]
        db.update_account(a, "A2", "Schwab", "renamed")
        row = db.list_accounts()[0]
        assert (row["name"], row["broker"], row["note"]) == ("A2", "Schwab", "renamed")
        raises(sqlite3.IntegrityError, db.create_account, "B")  # names are unique
        assert len(db.list_accounts()) == 2
        db.delete_account(a)
        assert db.list_txns(a) == [] and len(db.list_txns(b)) == 1  # only A's transactions go
        db.close()


def test_storage_settings_and_prices():
    with tempfile.TemporaryDirectory() as tmp:
        db = Storage(Path(tmp) / "t.db")
        assert db.get_setting("theme") is None and db.get_setting("theme", "dark") == "dark"
        db.set_setting("theme", "light")
        db.set_setting("theme", "dark")
        assert db.get_setting("theme") == "dark"
        db.set_price("X", D(1))
        db.set_price("X", D("2.5"))
        price, updated = db.get_prices()["X"]
        assert price == D("2.5") and updated == date.today().isoformat()
        db.set_price("NOT_THERE", None)  # removing a missing price is harmless
        assert set(db.get_prices()) == {"X"}
        db.close()
        with closing(Storage(Path(tmp) / "t.db")) as reopened:
            assert reopened.get_setting("theme") == "dark"  # persisted on disk


def test_daily_backup():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        backups = tmp / "backups"
        assert daily_backup(tmp / "missing.db", backups) is None
        (tmp / "empty.db").touch()
        assert daily_backup(tmp / "empty.db", backups) is None

        db_path = tmp / "t.db"
        db = Storage(db_path)
        db.create_account("A")
        db.close()
        backups.mkdir()
        for day in ("2026-01-01", "2026-01-02", "2026-01-03"):
            (backups / f"stock_ledger_{day}.db").write_text("old")
        target = daily_backup(db_path, backups, keep=2)
        assert sorted(p.name for p in backups.iterdir()) == ["stock_ledger_2026-01-03.db", target.name]
        with closing(Storage(target)) as backup:
            assert [r["name"] for r in backup.list_accounts()] == ["A"]

        # a second run on the same day keeps the first backup of the day
        db = Storage(db_path)
        db.create_account("B")
        db.close()
        assert daily_backup(db_path, backups, keep=2) == target
        with closing(Storage(target)) as backup:
            assert [r["name"] for r in backup.list_accounts()] == ["A"]


def test_storage_finance_categories():
    with tempfile.TemporaryDirectory() as tmp:
        db = Storage(Path(tmp) / "t.db")
        db.set_finance_enabled(True)
        assert db.list_finance_categories() == []
        db.seed_finance_defaults(["Salary", "Interest"], ["Card"])
        salary, interest, card = db.list_finance_categories()
        assert [(c.kind, c.name) for c in (salary, interest, card)] == [
            ("income", "Salary"), ("income", "Interest"), ("expense", "Card")]
        db.seed_finance_defaults(["Other"], [])  # the starting set is only made once
        assert len(db.list_finance_categories()) == 3

        # rename, reorder, add and delete in one go -- here swapping two names
        db.set_finance_categories("income", [(interest.id, "Salary"), (salary.id, "Interest"), (None, "Bonus")])
        income = [c for c in db.list_finance_categories() if c.kind == "income"]
        assert [(c.id, c.name) for c in income[:2]] == [(interest.id, "Salary"), (salary.id, "Interest")]
        assert income[2].name == "Bonus"
        assert [c.name for c in db.list_finance_categories() if c.kind == "expense"] == ["Card"]  # untouched

        # income always comes before expenses, whatever order they were made in
        db.set_finance_categories("expense", [(card.id, "Card"), (None, "Rent")])
        assert [c.kind for c in db.list_finance_categories()] == ["income"] * 3 + ["expense"] * 2

        # deleting a category deletes its amounts and comments with it
        db.save_finance_month(FinMonth("2025-01", None, {salary.id: FinEntry(D(5)), card.id: FinEntry(D(2), "", "c")}))
        assert db.finance_entry_counts() == {salary.id: 1, card.id: 1}
        db.set_finance_categories("income", [(interest.id, "Salary")])  # "Interest" (salary.id) and "Bonus" go
        assert db.finance_entry_counts() == {card.id: 1}
        (month,) = db.list_finance_months()
        assert set(month.entries) == {card.id}

        # a name is unique within a kind (and a failed change leaves everything as it was)
        db.set_finance_categories("expense", [(card.id, "Card"), (None, "Salary")])  # but may repeat across kinds
        raises(sqlite3.IntegrityError, db.set_finance_categories, "expense", [(card.id, "Card"), (None, "Card")])
        assert [c.name for c in db.list_finance_categories() if c.kind == "expense"] == ["Card", "Salary"]

        # even with every category deleted, the starting set does not come back
        db.set_finance_categories("income", [])
        db.set_finance_categories("expense", [])
        db.seed_finance_defaults(["Salary"], ["Card"])
        assert db.list_finance_categories() == []
        db.close()


def test_storage_finance_months():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "t.db"
        db = Storage(path)
        db.set_finance_enabled(True)
        db.seed_finance_defaults(["Salary"], ["Card"])
        salary, card = db.list_finance_categories()
        db.save_finance_month(FinMonth("2025-01", D("12345.67"), {
            salary.id: FinEntry(D("2501.00"), "1250.50+1250.50", "两笔\n工资"), card.id: FinEntry(D(0))}))
        (back,) = db.list_finance_months()
        assert back.month == "2025-01" and back.opening == D("12345.67")
        assert set(back.entries) == {salary.id}  # an empty entry (no amount, no comment) is not stored
        e = back.entries[salary.id]
        assert (e.amount, e.expr, e.comment) == (D("2501.00"), "1250.50+1250.50", "两笔\n工资")
        assert db.conn.execute("SELECT amount, opening FROM finance_entries, finance_months").fetchone()[:] == (
            "2501.00", "12345.67")  # exact text, like transactions

        # saving a month again replaces it: no opening any more, a comment on a zero amount is kept
        db.save_finance_month(FinMonth("2025-01", None, {card.id: FinEntry(D(0), "", "only a comment")}))
        db.save_finance_month(FinMonth("2024-12"))
        first, second = db.list_finance_months()  # in order
        assert (first.month, first.entries) == ("2024-12", {})
        assert second.opening is None and second.entries == {card.id: FinEntry(D(0), "", "only a comment")}

        db.close()
        db = Storage(path)  # still there after reopening
        assert [m.month for m in db.list_finance_months()] == ["2024-12", "2025-01"]
        db.delete_finance_month("2025-01")
        db.delete_finance_month("1999-01")  # a month that is not there: harmless
        assert [m.month for m in db.list_finance_months()] == ["2024-12"]
        assert db.conn.execute("SELECT COUNT(*) FROM finance_entries").fetchone()[0] == 0  # its entries went too
        db.close()


def test_finance_tables_only_exist_once_the_page_is_turned_on():
    def tables(db):
        return {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "old.db"
        old = sqlite3.connect(path)  # a database from before the finance page: accounts only
        old.executescript("""
            CREATE TABLE accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
                broker TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')));
            INSERT INTO accounts(name) VALUES ('Old');
        """)
        old.commit()
        old.close()
        db = Storage(path)  # opening it, as often as you like, leaves it without finance tables
        assert not db.finance_enabled() and not {t for t in tables(db) if t.startswith("finance")}
        db.close()
        db = Storage(path)
        assert not {t for t in tables(db) if t.startswith("finance")}
        db.set_finance_enabled(True)  # turning the page on makes them
        assert {"finance_categories", "finance_months", "finance_entries"} <= tables(db)
        assert db.finance_enabled() and db.list_finance_categories() == [] and db.list_finance_months() == []
        assert [a["name"] for a in db.list_accounts()] == ["Old"]  # what was there is untouched
        db.save_finance_month(FinMonth("2025-01", D(5)))
        db.set_finance_enabled(False)  # turning it off only hides it
        db.close()
        db = Storage(path)
        assert not db.finance_enabled() and "finance_months" in tables(db)
        db.set_finance_enabled(True)
        assert [m.month for m in db.list_finance_months()] == ["2025-01"]  # still there
        db.close()


# ----------------------------------------------------------------------
# Quotes
# ----------------------------------------------------------------------
def test_parse_quotes():
    data = {"spark": {"result": [
        {"symbol": "AAPL", "response": [{"meta": {
            "regularMarketPrice": 333.02, "chartPreviousClose": 329.4, "regularMarketTime": 1790798401}}]},
        {"symbol": "SPAXX", "response": [{"meta": {"regularMarketPrice": 1.0}}]},
        {"symbol": "BAD", "response": [{"meta": {}}]},
    ], "error": None}}
    q = parse_spark(data)
    assert set(q) == {"AAPL", "SPAXX"}
    assert q["AAPL"].price == D("333.02") and q["AAPL"].change == D("3.62")
    assert q["SPAXX"].prev_close is None and q["SPAXX"].change is None
    assert yahoo_symbol("BRK.B") == "BRK-B"


def test_parse_spark_details():
    data = {"spark": {"result": [
        {"symbol": "X", "response": [{
            "meta": {"regularMarketPrice": 10, "previousClose": 8, "longName": "X Corp", "regularMarketTime": 1790798401},
            "timestamp": [1, 2, 3, 4],
            "indicators": {"quote": [{"close": [9.5, None, 10.25, 10]}]},  # gaps in the bars are skipped
        }]},
        {"symbol": "ZERO", "response": [{"meta": {"regularMarketPrice": 0}}]},  # no real price
        {"symbol": "NAN", "response": [{"meta": {"regularMarketPrice": float("nan")}}]},
    ]}}
    q = parse_spark(data)
    assert set(q) == {"X"}
    x = q["X"]
    assert x.points == [(1, 9.5), (3, 10.25), (4, 10.0)]
    assert x.prev_close == 8 and x.change == 2 and x.name == "X Corp"
    assert x.time == datetime.fromtimestamp(1790798401)
    assert parse_spark({}) == {} and parse_spark({"spark": None}) == {}
    assert parse_spark({"spark": {"result": [{"symbol": "Y", "response": None}]}}) == {}


def test_crypto_symbols():
    assert is_crypto("BTC-USD") and is_crypto("eth-usd") and not is_crypto("BTC") and not is_crypto("BRK.B")
    assert ledger_symbol("BTC-USD") == "BTC-USD" and yahoo_symbol("BTC-USD") == "BTC-USD"


def test_symbol_conversion():
    assert yahoo_symbol("BRK/B") == "BRK-B" and yahoo_symbol("AAPL") == "AAPL"
    assert ledger_symbol("BRK-B") == "BRK.B"
    for sym in ("BRK.B", "BF.A", "AAPL", "SPAXX"):
        assert ledger_symbol(yahoo_symbol(sym)) == sym


def test_fetch_quotes_batches_and_maps_symbols():
    def spark(*symbols):
        return {"spark": {"result": [{"symbol": s, "response": [{"meta": {"regularMarketPrice": 5}}]} for s in symbols]}}

    symbols = ["BRK.B"] + [f"S{i:02d}" for i in range(24)]  # 25 symbols -> two requests of up to 20
    ysyms = sorted(yahoo_symbol(s) for s in symbols)
    calls = []
    with mock.patch("urllib.request.urlopen", fake_urlopen([spark(*ysyms[:20]), spark(*ysyms[20:-1], "UNASKED")], calls)):
        got = fetch_quotes(symbols, rng="1y", interval="1d")
    assert len(calls) == 2 and "range=1y" in calls[0] and "interval=1d" in calls[0]
    assert "BRK-B" in calls[0]  # asked for in Yahoo's spelling...
    assert "BRK.B" in got  # ...and handed back in ours
    assert "UNASKED" not in got and ysyms[-1] not in got  # extra symbols ignored, unknown ones simply missing
    assert len(got) == 24


def test_fetch_quotes_errors():
    with mock.patch("urllib.request.urlopen", fake_urlopen([OSError("no network")])):
        raises(QuoteError, fetch_quotes, ["AAPL"], match="no network")
    with mock.patch("urllib.request.urlopen", fake_urlopen([b"<html>not json</html>"])):
        raises(QuoteError, fetch_quotes, ["AAPL"])
    with mock.patch("urllib.request.urlopen", fake_urlopen([])):
        assert fetch_quotes([]) == {}  # nothing to ask for: no request at all


def test_new_york_time():
    ny = lambda stamp: new_york_time(utc(stamp)).strftime("%Y-%m-%d %H:%M")  # noqa: E731
    assert ny("2026-01-15 14:30") == "2026-01-15 09:30"  # winter: EST, 5 hours behind UTC
    assert ny("2026-07-15 13:30") == "2026-07-15 09:30"  # summer: EDT, 4 hours behind
    assert (ny("2026-03-08 06:59"), ny("2026-03-08 07:00")) == ("2026-03-08 01:59", "2026-03-08 03:00")  # spring forward
    assert (ny("2026-11-01 05:59"), ny("2026-11-01 06:00")) == ("2026-11-01 01:59", "2026-11-01 01:00")  # fall back
    try:
        from zoneinfo import ZoneInfo

        ref = ZoneInfo("America/New_York")
    except Exception:  # no time zone database here (Windows without tzdata): the fixed cases above will do
        return
    for year in range(2008, 2041):  # every hour of the first two weeks of March and November, when the clocks change
        for month in (3, 11):
            t = datetime(year, month, 1, tzinfo=timezone.utc)
            for _ in range(14 * 24):
                assert new_york_time(t.timestamp()) == t.astimezone(ref).replace(tzinfo=None), t
                t += timedelta(hours=1)


def test_market_hours():
    def live(symbol, now, *bars):
        return is_live(symbol, quote_with_bars(*bars), utc(now))

    # an ordinary Tuesday in summer time (EDT, 4 hours behind UTC): the session runs 13:30-20:00 UTC
    assert not live("AAPL", "2026-10-27 13:29:59", "2026-10-26 19:55")  # before the open
    assert live("AAPL", "2026-10-27 13:30:00", "2026-10-27 13:30")  # the open itself
    assert live("AAPL", "2026-10-27 14:00:00", "2026-10-27 13:55")
    assert live("AAPL", "2026-10-27 19:59:59", "2026-10-27 19:55")  # the last second
    assert not live("AAPL", "2026-10-27 20:00:00", "2026-10-27 19:55")  # closed at 16:00
    assert not live("AAPL", "2026-10-27 22:00:00", "2026-10-27 19:55")  # after hours do not count
    assert not live("AAPL", "2026-10-27 13:31:00", "2026-10-26 19:55")  # open, but no trade yet today
    assert live("AAPL", "2026-10-27 13:31:00", "2026-10-27 13:30")
    # weekends
    assert not live("AAPL", "2026-10-31 15:00", "2026-10-30 19:55")  # Saturday
    assert not live("AAPL", "2026-11-01 15:00", "2026-10-30 19:55")  # Sunday
    # a market holiday (Thanksgiving, Thursday 26 Nov 2026): the hours say open but the latest bar is Wednesday's
    assert not live("AAPL", "2026-11-26 16:00", "2026-11-25 20:55")
    # early closes at 13:00: the day after Thanksgiving, Christmas Eve and July 3; an ordinary Friday is open then
    assert live("AAPL", "2026-11-27 17:59", "2026-11-27 17:55") and not live("AAPL", "2026-11-27 18:00", "2026-11-27 17:55")
    assert live("AAPL", "2026-12-24 17:59", "2026-12-24 17:55") and not live("AAPL", "2026-12-24 18:00", "2026-12-24 17:55")
    assert live("AAPL", "2028-07-03 16:59", "2028-07-03 16:55") and not live("AAPL", "2028-07-03 17:00", "2028-07-03 16:55")
    assert live("AAPL", "2026-11-20 18:00", "2026-11-20 17:55")
    # the clocks change: EST from Sunday 1 Nov 2026, EDT from Sunday 8 Mar 2026
    assert not live("AAPL", "2026-11-02 13:31", "2026-11-02 13:30")  # Monday 8:31 EST
    assert live("AAPL", "2026-11-02 14:31", "2026-11-02 14:30")  # 9:31 EST
    assert live("AAPL", "2026-11-02 20:59", "2026-11-02 20:55") and not live("AAPL", "2026-11-02 21:00", "2026-11-02 20:55")
    assert not live("AAPL", "2026-03-06 13:31", "2026-03-06 13:30") and live("AAPL", "2026-03-06 14:31", "2026-03-06 14:30")
    assert not live("AAPL", "2026-03-09 12:31", "2026-03-09 12:30") and live("AAPL", "2026-03-09 13:31", "2026-03-09 13:30")
    # crypto never closes (even without bars); plain BTC is an ETF on the stock market
    assert live("BTC-USD", "2026-10-31 03:00", "2026-10-31 02:55") and live("eth-usd", "2026-11-01 15:00")
    assert is_live("BTC-USD", Quote(price=D(1), prev_close=None, time=None), utc("2026-11-01 15:00"))
    assert not live("BTC", "2026-10-31 03:00", "2026-10-30 19:55")
    # without bars, the time of the last trade is used; without either, nothing is known
    traded = lambda stamp: Quote(price=D(10), prev_close=D(9), time=datetime.fromtimestamp(utc(stamp)))  # noqa: E731
    assert is_live("AAPL", traded("2026-10-27 13:58"), utc("2026-10-27 14:00"))
    assert not is_live("AAPL", traded("2026-10-26 19:59"), utc("2026-10-27 14:00"))
    assert not is_live("AAPL", Quote(price=D(10), prev_close=D(9), time=None), utc("2026-10-27 14:00"))
    with mock.patch("quotes.time.time", return_value=utc("2026-10-27 14:00")):  # no time given: the clock decides
        assert is_live("AAPL", quote_with_bars("2026-10-27 13:55"))
        assert not is_live("AAPL", quote_with_bars("2026-10-26 19:55"))


# ----------------------------------------------------------------------
# Symbol search (type-ahead)
# ----------------------------------------------------------------------
SEARCH_RESPONSE = {"quotes": [
    {"symbol": "BRK-B", "shortname": "Berkshire Hathaway Inc. New", "quoteType": "EQUITY", "exchDisp": "NYSE", "typeDisp": "Equity"},
    {"symbol": "BRK-A", "longname": "Berkshire Hathaway Inc.", "quoteType": "EQUITY", "exchDisp": "NYSE"},
    {"symbol": "BRK-B", "shortname": "duplicate", "quoteType": "EQUITY"},
    {"symbol": "BRYN.F", "shortname": "Berkshire (Frankfurt)", "quoteType": "EQUITY"},  # non-US listing
    {"symbol": "OMAH", "shortname": "VistaShares Target 15 Berkshire", "quoteType": "ETF", "typeDisp": "ETF"},
    {"symbol": "SPAXX", "shortname": "Fidelity Government Money Marke", "quoteType": "MONEY_MARKET"},
    {"symbol": "BRK260116C00500000", "quoteType": "OPTION"},
    {"symbol": "BTC-USD", "shortname": "Bitcoin USD", "quoteType": "CRYPTOCURRENCY", "exchDisp": "CCC",
     "typeDisp": "Cryptocurrency"},
    {"symbol": "BTC-EUR", "quoteType": "CRYPTOCURRENCY"},  # not in dollars
    {"symbol": "^GSPC", "quoteType": "INDEX"},
    {"quoteType": "EQUITY"},  # no symbol
]}


def test_parse_search():
    got = parse_search(SEARCH_RESPONSE)
    assert [s.symbol for s in got] == ["BRK.B", "BRK.A", "OMAH", "SPAXX", "BTC-USD"]
    assert got[-1] == Suggestion("BTC-USD", "Bitcoin USD", "", "Cryptocurrency")  # crypto keeps its dash
    assert got[0] == Suggestion("BRK.B", "Berkshire Hathaway Inc. New", "NYSE", "Equity")
    assert got[1].name == "Berkshire Hathaway Inc." and got[1].kind == ""  # longname when no shortname
    assert parse_search({}) == [] and parse_search({"quotes": None}) == []


def test_search_symbols():
    calls = []
    with mock.patch("urllib.request.urlopen", fake_urlopen([SEARCH_RESPONSE], calls)):
        got = search_symbols("  berkshire ", limit=2)
    assert [s.symbol for s in got] == ["BRK.B", "BRK.A"]
    assert "q=berkshire" in calls[0] and "newsCount=0" in calls[0]
    with mock.patch("urllib.request.urlopen", fake_urlopen([])):
        assert search_symbols("   ") == []  # blank: no request
    with mock.patch("urllib.request.urlopen", fake_urlopen([TimeoutError("timed out")])):
        raises(QuoteError, search_symbols, "x", match="timed out")


def test_match_local():
    names = {"AAPL": "Apple Inc.", "AMZN": "Amazon.com, Inc.", "A": "Agilent Technologies", "MSFT": "Microsoft",
             "SPAXX": "", "PLTR": "Palantir"}
    assert match_local("a", names) == ["A", "AAPL", "AMZN", "PLTR", "SPAXX"]  # exact, prefixes, then anywhere
    assert match_local("AAPL", names) == ["AAPL"]
    assert match_local("apple", names) == ["AAPL"]  # by company name
    assert match_local("tech", names) == ["A"]  # a later word of the name
    assert match_local("soft", names) == ["MSFT"]  # inside a word
    assert match_local("zzz", names) == []
    assert match_local("", names) == sorted(names)  # empty: everything known
    assert match_local("", names, limit=2) == ["A", "AAPL"]
    assert match_local("a", {}) == []
    assert match_local("a", {"ACN": "", "AAPL": "", "ABBV": ""}) == ["AAPL", "ABBV", "ACN"]  # alphabetical, not by length

# ----------------------------------------------------------------------
# Shared core / CSV translations (the React UI also reads this dictionary).
# ----------------------------------------------------------------------
def _translated_texts() -> set[str]:
    found = set(TXN_TYPES.values()) | set(PERIODS.values()) | set(FINANCE_PERIODS.values())
    root = Path(__file__).resolve().parent
    for name in ("ledger.py", "quotes.py", "storage.py", "finance.py", "csv_export.py", "desktop_backend.py"):
        for node in ast.walk(ast.parse((root / name).read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and node.args and (getattr(node.func, "id", None) == "tr" or getattr(node.func, "attr", None) == "tr"):
                value = node.args[0]
                candidates = (value.body, value.orelse) if isinstance(value, ast.IfExp) else (value,)
                found.update(c.value for c in candidates if isinstance(c, ast.Constant) and isinstance(c.value, str))
    for headers in (TXN_HEADERS, HOLDING_HEADERS, YEARLY_HEADERS, MONTHLY_HEADERS, FINANCE_YEARLY_HEADERS, ENTRY_HEADERS):
        found.update(headers)
    return found


def test_every_core_text_has_a_chinese_translation():
    missing = sorted(_translated_texts() - i18n.ZH.keys())
    assert not missing, f"no Chinese for: {missing}"


def test_translations_keep_their_placeholders():
    def fields(text):
        return sorted(name for _, name, _, _ in string.Formatter().parse(text) if name is not None)

    for en, zh in i18n.ZH.items():
        assert fields(en) == fields(zh), f"{en!r} has {fields(en)} but the Chinese has {fields(zh)}"
        assert zh.strip(), en


def test_switching_language():
    try:
        i18n.set_language("en")
        assert i18n.tr("Cash") == "Cash"
        assert i18n.tr("{n} transactions", n=3) == "3 transactions"
        i18n.set_language("zh")
        assert i18n.language() == "zh"
        assert i18n.tr("Cash") == "现金"
        assert i18n.tr("{n} transactions", n=3) == "3 笔交易"
        assert i18n.tr("Some text with no translation") == "Some text with no translation"
        assert Txn(date="2026-01-01", type="BUY").type_label == "买入"
        raises(ValueError, to_decimal, "abc", match="不是有效的数字")
        raises(ValueError, Txn(date="2026-01-01", type="DEPOSIT").validate, match="金额必须大于 0")
        raises(LedgerError, replay, txns(("2026-01-01", "SELL", "X", 2, 10, 0, 0)), match="当时只持有 0 股")
        i18n.set_language("unknown")
        assert i18n.language() == "en"
    finally:
        i18n.set_language("en")


if __name__ == "__main__":
    import sys
    import traceback

    failed = []
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception:
                failed.append(name)
                print("FAILED", name)
                traceback.print_exc()
            else:
                print("passed", name)
    if failed:
        print(f"\n{len(failed)} test(s) failed: {', '.join(failed)}")
        sys.exit(1)
    print("all tests passed")
