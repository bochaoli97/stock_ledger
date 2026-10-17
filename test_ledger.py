"""
test_ledger.py -- checks that the bookkeeping math is correct. Run: python test_ledger.py
(also runs under pytest)

No test touches the internet: the Yahoo calls are replaced by canned responses.
"""

import ast
import io
import json
import string
import sqlite3
import tempfile
from datetime import date, datetime
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ledger import (
    TXN_TYPES,
    LedgerError,
    LedgerResult,
    Position,
    Txn,
    fmt_money,
    fmt_pct,
    fmt_price,
    fmt_qty,
    parse_date,
    replay,
    sort_key,
    to_decimal,
    valuation,
    value_series,
)
from quotes import (
    QuoteError,
    Suggestion,
    fetch_quotes,
    is_crypto,
    ledger_symbol,
    match_local,
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
        assert len(Storage(Path(tmp) / "copy.db").list_txns(acc)) == 12
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
        assert Storage(Path(tmp) / "t.db").get_setting("theme") == "dark"  # persisted on disk


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
        assert [r["name"] for r in Storage(target).list_accounts()] == ["A"]

        # a second run on the same day keeps the first backup of the day
        db = Storage(db_path)
        db.create_account("B")
        db.close()
        assert daily_backup(db_path, backups, keep=2) == target
        assert [r["name"] for r in Storage(target).list_accounts()] == ["A"]


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
    import app

    assert app.holding_text("BTC-USD", D("0.5")) == "0.5 coins" and app.holding_text("AAPL", D(1)) == "1 share"
    assert app.symbol_text(Txn(date="2026-01-01", type="SYMBOL_CHANGE", symbol="A", symbol2="B")) == "A → B"
    assert app.price_text(distribution("12.5")) == "12.5%" and app.price_text(distribution(0)) == "0%"
    assert app.price_text(Txn(date="2026-01-01", type="BUY", price=D(5))) == "5.00"
    assert app.price_text(Txn(date="2026-01-01", type="SHARES_OUT", price=D(5))) == ""


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


def test_symbol_search_suggestions():
    """The app's search helper: account holdings first, online results after, nothing online when live is off."""
    import app

    def run_now(fn, args, done):  # App.run_bg without the thread: errors are handed to `done` too
        try:
            res = fn(*args)
        except Exception as e:
            res = e
        done(res)

    scheduled = []
    stub = SimpleNamespace(
        result=replay(txns(
            ("2026-01-01", "BUY", "AAPL", 10, 1, 0, 0),
            ("2026-01-01", "BUY", "AMD", 1, 1, 0, 0),
            ("2026-01-02", "SELL", "AMD", 1, 1, 0, 0),
        )),
        quotes={"AAPL": SimpleNamespace(name="Apple Inc.")},
        v_live=SimpleNamespace(get=lambda: live),
        root=SimpleNamespace(after=lambda ms, fn: scheduled.append(fn) or "job", after_cancel=lambda job: None),
        run_bg=run_now,
    )
    search = app.SymbolSearch(stub)
    shown = []

    def show(query, items):
        shown.append((query, items))

    live = False
    search("a", show)
    assert shown == [("a", [("AAPL", "Apple Inc.", "10 shares"), ("AMD", "", "Closed")])]
    assert scheduled == []  # live prices off: nothing typed leaves the computer

    live = True
    shown.clear()
    online = [Suggestion("AMD", "Advanced Micro Devices", "NASDAQ"), Suggestion("A", "Agilent", "NYSE", "Equity"),
              Suggestion("ABNB", "Airbnb", "", "Equity")]
    with mock.patch.object(app, "search_symbols", lambda q, limit: online) as fake:
        search("a", show)
        assert len(shown) == 1 and len(scheduled) == 1  # local matches now, the online search after a pause
        scheduled.pop()()
    assert shown[-1] == ("a", [
        ("AAPL", "Apple Inc.", "10 shares"),
        ("AMD", "Advanced Micro Devices", "Closed"),  # the name learned online fills in the held one
        ("A", "Agilent", "NYSE"),
        ("ABNB", "Airbnb", "Equity"),
    ])
    shown.clear()
    search(" A ", show)  # same query again: answered from the cache, no new search
    assert len(shown) == 1 and scheduled == [] and shown[0][1][2] == ("A", "Agilent", "NYSE")

    def offline(q, limit):
        raise QuoteError("offline")

    shown.clear()
    with mock.patch.object(app, "search_symbols", offline):
        search("zz", show)
        scheduled.pop()()
    assert shown == [("zz", [])]  # a failed search leaves the local results as they were


# ----------------------------------------------------------------------
# Main window (needs a display; skipped where there is none, e.g. over plain SSH)
# ----------------------------------------------------------------------
def _gui_window():
    """(tk root, app.App) with one account holding SKYD and AAPL and live prices off, or None without a display."""
    import tkinter as tk
    import app

    try:
        root = tk.Tk()
    except tk.TclError:
        return None
    root.withdraw()
    folder = Path(tempfile.mkdtemp())
    db = Storage(folder / "gui.db")
    db.set_setting("live_prices", "0")  # no network in tests
    acc = db.create_account("Test")
    for kw in (dict(date="2026-01-02", type="DEPOSIT", amount=D(20000)),
               dict(date="2026-01-05", type="BUY", symbol="SKYD", quantity=D(1000), price=D(10)),
               dict(date="2026-01-06", type="BUY", symbol="AAPL", quantity=D(10), price=D(150))):
        db.add_txn(Txn(account_id=acc, **kw))
    app.set_theme("light")
    app.UI.setup(root)
    root.deiconify()
    return root, app.App(root, db, folder)


def _close_gui(root):
    """Destroy a test window; its pending timers (background polling) must not fire later in another one."""
    for job in root.tk.splitlist(root.tk.call("after", "info")):
        root.after_cancel(job)
    root.destroy()


def test_tables_scroll_sideways_when_narrow():
    import tkinter as tk
    import app
    from ui import make_tree

    win = _gui_window()
    if win is None:
        return
    root, _ = win
    try:
        frame, tree = make_tree(root, app.columns(app.App.HOLD_COLUMNS))
        frame.place(x=0, y=0, width=600, height=300)  # narrower than the columns need
        bar = next(w for w in frame.winfo_children() if w.winfo_class() == "TScrollbar" and str(w.cget("orient")) == "horizontal")
        root.update()
        assert tree.xview()[1] < 1 and bar.winfo_ismapped()  # columns keep their width; the rest is reached by scrolling
        assert all(tree.column(c, "width") >= app.UI.px(w) for c, (_, _, w, _) in zip(tree["columns"], app.App.HOLD_COLUMNS))
        total = sum(tree.column(c, "width") for c in tree["columns"])
        for widget, seq, kw in ((tree, "<Shift-MouseWheel>", dict(delta=-120)), (tree, "<Shift-Button-5>", {}),
                                (bar, "<MouseWheel>", dict(delta=-120)), (bar, "<Button-5>", {})):
            tree.xview_moveto(0)
            widget.event_generate(seq, x=5, y=3, **kw)  # one notch of the wheel moves a useful distance, not 1-5 pixels
            root.update()
            assert round(tree.xview()[0] * total) == app.UI.px(80), seq
        tree.event_generate("<Shift-MouseWheel>", x=5, y=3, delta=120)  # wheel up goes back left
        root.update()
        assert tree.xview()[0] == 0
        frame.place_configure(width=1800)
        root.update()
        assert tree.xview() == (0.0, 1.0) and not bar.winfo_ismapped()  # room to spare: stretched, no scroll bar
    finally:
        _close_gui(root)


def test_stock_page_opens_inside_the_window():
    win = _gui_window()
    if win is None:
        return
    root, a = win
    try:
        root.update()
        assert a.detail is None and a.overview.winfo_ismapped()
        a.open_symbol("SKYD")
        root.update()
        assert a.detail.symbol == "SKYD" and a.detail.winfo_ismapped() and not a.overview.winfo_ismapped()
        assert a.detail.winfo_toplevel() is root  # not a window of its own
        assert root.title().startswith("SKYD") and len(a.detail.tree.get_children()) == 1
        a.open_symbol("SKYD")  # already open: nothing changes
        a.open_symbol("AAPL")  # picking another stock switches the page
        root.update()
        assert a.detail.symbol == "AAPL" and root.title().startswith("AAPL")
        a.open_symbol("NOPE")  # unknown symbol: ignored
        assert a.detail.symbol == "AAPL"
        a.rebuild()  # a theme / language / text size change keeps you on the same stock
        root.update()
        assert a.detail.symbol == "AAPL" and not a.overview.winfo_ismapped()
        root.event_generate("<Escape>")  # Esc goes back
        root.update()
        assert a.detail is None and a.overview.winfo_ismapped() and root.title() == i18n.tr("Stock Ledger")
        a.open_symbol("SKYD")
        a.db.delete_txn(next(t.id for t in a.txns if t.symbol == "SKYD"))
        a.refresh()  # the stock no longer exists: back to the overview instead of an empty page
        root.update()
        assert a.detail is None and a.overview.winfo_ismapped()
    finally:
        _close_gui(root)


def test_pages_scroll_up_and_down_when_the_window_is_short():
    win = _gui_window()
    if win is None:
        return
    root, a = win
    try:
        def check(page, tree):
            root.update()
            return page.sb.winfo_ismapped(), tree.winfo_ismapped(), tree.winfo_height()

        for open_stock in (False, True):
            if open_stock:
                a.open_symbol("SKYD")
            page, tree = (a.detail, a.detail.tree) if open_stock else (a.overview, a.hold_tree)
            hero = (a.detail if open_stock else a).hero
            root.geometry("1440x1000")  # plenty of room: no scroll bar, the table takes what is left
            scrolls, shown, tall = check(page, tree)
            assert not scrolls and shown
            root.geometry("1000x640")  # short: the table keeps its rows and the page scrolls instead
            scrolls, shown, short = check(page, tree)
            assert scrolls and shown and 100 <= short < tall  # still at least a few rows tall
            top = page.canvas.yview()[0]
            hero.value.event_generate("<MouseWheel>", delta=-120, x=5, y=5)  # the wheel scrolls the page...
            root.update()
            assert page.canvas.yview()[0] > top
            moved = page.canvas.yview()[0]
            hero.value.event_generate("<Shift-MouseWheel>", delta=-120, x=5, y=5)  # ...but Shift is for tables
            root.update()
            assert page.canvas.yview()[0] == moved
            side = next(w for w in tree.master.winfo_children()
                        if w.winfo_class() == "TScrollbar" and str(w.cget("orient")) == "horizontal")
            side.event_generate("<MouseWheel>", delta=-120, x=5, y=3)  # on the sideways bar the wheel goes sideways
            root.update()
            assert page.canvas.yview()[0] == moved and tree.xview()[0] > 0
            tree.xview_moveto(0)
            root.geometry("1440x1000")
            scrolls, _, _ = check(page, tree)
            assert not scrolls and page.canvas.yview()[0] == 0  # back to the top once everything fits
    finally:
        _close_gui(root)


def test_reset_filters_button_only_shows_while_filtering():
    win = _gui_window()
    if win is None:
        return
    root, a = win
    try:
        a._show_page("Transactions")
        root.update()
        assert not a.reset_btn.winfo_ismapped()
        a.v_filter_symbol.set("AAPL")
        root.update()
        assert a.reset_btn.winfo_ismapped() and len(a.txn_tree.get_children()) == 1
        a._clear_filters()  # only the view changes; no transaction is deleted
        root.update()
        assert not a.reset_btn.winfo_ismapped()
        assert len(a.txn_tree.get_children()) == 3 and len(a.db.list_txns(a.account_id)) == 3
    finally:
        _close_gui(root)


# ----------------------------------------------------------------------
# Interface language
# ----------------------------------------------------------------------
def _translated_texts() -> set[str]:
    """Every English text the code shows through tr(): literal tr("...") and plural() calls (including
    tr("a" if x else "b")), loops like `for h in ("Date", ...): tr(h)`, and the tables of text kept in
    constants (transaction types, chart ranges, column titles, dialog hints, text sizes)."""
    import app
    import ui

    def literals(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {node.value}
        if isinstance(node, ast.IfExp):
            return literals(node.body) | literals(node.orelse)
        return set()

    found = set()
    for fname in ("app.py", "ledger.py", "ui.py", "quotes.py", "storage.py"):
        tree = ast.parse(Path(fname).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "tr" and node.args:
                found |= literals(node.args[0])
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "plural":  # plural(n, one, many)
                found |= {t for arg in node.args[1:] for t in literals(arg)}
            if isinstance(node, (ast.For, ast.comprehension)):
                it = node.iter
                if isinstance(it, ast.Call) and getattr(it.func, "id", None) == "enumerate":
                    it = it.args[0]
                names = {n.id for n in ast.walk(node.target) if isinstance(n, ast.Name)}
                scope = node if isinstance(node, ast.For) else tree
                uses_tr = any(isinstance(c, ast.Call) and getattr(c.func, "id", None) == "tr" and c.args
                              and isinstance(c.args[0], ast.Name) and c.args[0].id in names for c in ast.walk(scope))
                if isinstance(it, ast.Tuple) and uses_tr:
                    found |= {e.value for e in it.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    found |= set(TXN_TYPES.values())
    found |= set(app.RANGES) | {wording for _, _, wording in app.RANGES.values()}
    for cols in (app.App.HOLD_COLUMNS, app.App.TXN_COLUMNS, app.SymbolDetail.COLUMNS):
        found |= {title for _, title, _, _ in cols}
    found |= set(app.TxnDialog.AMOUNT_LABELS.values()) | set(app.TxnDialog.HINTS.values()) | {"Amount"}
    found |= set(ui.TEXT_SIZES) | {app.APP_NAME, app.ALL, "Holdings", "Transactions"}
    return found


def test_every_text_has_a_chinese_translation():
    texts = _translated_texts()
    missing = sorted(t for t in texts if t not in i18n.ZH)
    assert not missing, f"no Chinese for: {missing}"
    unused = sorted(k for k in i18n.ZH if k not in texts)
    assert not unused, f"translations nothing uses (a typo in the English?): {unused}"


def test_translations_keep_their_placeholders():
    def fields(text):
        return sorted(name for _, name, _, _ in string.Formatter().parse(text) if name is not None)

    for en, zh in i18n.ZH.items():
        assert fields(en) == fields(zh), f"{en!r} has {fields(en)} but the Chinese has {fields(zh)}"
        assert zh.strip(), en


def test_switching_language():
    import app

    try:
        assert i18n.tr("Cash") == "Cash" and i18n.tr("{n} transactions", n=3) == "3 transactions"
        i18n.set_language("zh")
        assert i18n.language() == "zh"
        assert i18n.tr("Cash") == "现金" and i18n.tr("{n} transactions", n=3) == "3 笔交易"
        assert i18n.tr("Some text with no translation") == "Some text with no translation"  # falls back to English
        assert Txn(date="2026-01-01", type="BUY").type_label == "买入"
        assert app.plural("1", "{n} share", "{n} shares") == "1 股"
        raises(ValueError, to_decimal, "abc", match="不是有效的数字")
        raises(ValueError, Txn(date="2026-01-01", type="DEPOSIT").validate, match="金额必须大于 0")
        raises(LedgerError, replay, txns(("2026-01-01", "SELL", "X", 2, 10, 0, 0)), match="当时只持有 0 股")
        stamp = int(datetime(2026, 9, 30, 15, 5).timestamp())  # a Wednesday
        assert [app.time_label(stamp, r) for r in ("1D", "1W", "1Y")] == ["15:05", "周三 15:05", "2026年9月30日"]
        i18n.set_language("klingon")
        assert i18n.language() == "en"  # unknown codes fall back to English
        assert [app.time_label(stamp, r) for r in ("1D", "1W", "1Y")] == ["3:05 PM", "Wed 3:05 PM", "Sep 30, 2026"]
        assert app.plural("2", "{n} share", "{n} shares") == "2 shares"
    finally:
        i18n.set_language("en")


def test_saved_language():
    import app

    with tempfile.TemporaryDirectory() as tmp:
        db = Storage(Path(tmp) / "t.db")
        assert app.saved_language(db) == "zh"  # first run: Chinese
        db.set_setting("language", "en")
        assert app.saved_language(db) == "en"  # afterwards: the user's choice
        db.set_setting("language", "xx")
        assert app.saved_language(db) == "zh"
        db.close()


# ----------------------------------------------------------------------
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
