"""Regression tests for the headless bridge; never open the user's database."""
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

from desktop_backend import LedgerService, ServiceError
from quotes import Quote


class DesktopServiceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.service = LedgerService(Path(self.folder.name) / "ledger.db", backup=False)
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(self.service.close)
        self.service.dispatch("settings.save", {"live": False, "language": "en"})

    def account(self, name="Brokerage", cash="10000", **kw):
        return self.service.dispatch("account.save", {"name": name, "cash": cash, "date": "2026-01-01", **kw})["account_id"]

    def txn(self, aid, **kw):
        return self.service.dispatch("transaction.save", {"account_id": aid, "date": "2026-01-02", "type": "BUY",
                                                           "symbol": "AAPL", "quantity": "2", "price": "100", **kw})

    def test_snapshot_keeps_decimal_precision_and_existing_schema(self):
        aid = self.account(cash="9007199254740992.01")
        state = self.txn(aid, quantity="0.00000001", price="0.01")
        self.assertEqual(state["summary"]["total"], "$9,007,199,254,740,992.01")
        self.assertEqual(state["holdings"][0]["quantity_raw"], "0.00000001")
        stored = self.service.db.list_txns(aid)
        self.assertEqual(stored[1].quantity, D("0.00000001"))
        self.assertEqual(self.service.db.conn.execute("SELECT typeof(quantity) FROM transactions LIMIT 1").fetchone()[0], "text")

    def test_account_openings_and_combined_view(self):
        a = self.account(positions=[{"symbol": "aapl", "quantity": "2", "price": "100"}])
        b = self.account("IRA", "2000", positions=[{"symbol": "AAPL", "quantity": "3", "price": "200"}])
        state = self.service.dispatch("account.select", {"account_id": -1})
        self.assertEqual(state["summary"]["total"], "$12,800.00")
        self.assertEqual(state["holdings"][0]["quantity"], "5")
        self.assertEqual(state["holdings"][0]["avg_cost"], "$160.00")
        self.assertEqual({row["account_id"] for row in state["transactions"]}, {a, b})
        self.assertEqual(self.service.db.get_setting("last_account"), "all")

    def test_invalid_edits_and_deletions_are_atomic(self):
        aid = self.account()
        state = self.txn(aid)
        buy_id = state["transactions"][0]["id"]
        self.txn(aid, type="SELL", quantity="1", date="2026-01-03")
        before = self.service.db.list_txns(aid)
        with self.assertRaises(ValueError):
            self.txn(aid, id=buy_id, quantity="0.5")
        with self.assertRaises(ValueError):
            self.service.dispatch("transaction.delete", {"account_id": aid, "id": buy_id})
        self.assertEqual(self.service.db.list_txns(aid), before)
        b = self.account("Other")
        with self.assertRaises(ServiceError):
            self.txn(b, id=buy_id)
        self.assertEqual(self.service.db.list_txns(aid), before)

    def test_negative_cash_requires_explicit_confirmation(self):
        aid = self.account(cash="1")
        with self.assertRaises(ServiceError) as raised:
            self.txn(aid)
        self.assertEqual(raised.exception.code, "NEGATIVE_CASH")
        self.assertEqual(len(self.service.db.list_txns(aid)), 1)
        preview = self.service.dispatch("transaction.preview", {"account_id": aid, "date": "2026-01-02", "type": "BUY",
                                                                  "symbol": "AAPL", "quantity": "2", "price": "100"})
        self.assertTrue(preview["negative_cash"])
        self.assertEqual(self.txn(aid, allow_negative_cash=True)["summary"]["cash"], "-$199.00")

    def test_finance_formulas_carry_categories_and_filters(self):
        self.service.dispatch("settings.save", {"finance": True})
        initial = self.service.dispatch("finance.snapshot", {})
        salary = next(c["id"] for c in initial["categories"] if c["kind"] == "income")
        rent = next(c["id"] for c in initial["categories"] if c["kind"] == "expense")
        self.service.dispatch("finance.month.save", {"month": "2026-01", "opening": "100", "entries": {
            str(salary): {"raw": "1250.50+1250.50", "comment": "First payment\nSecond payment"}, str(rent): {"raw": "1000"}}})
        result = self.service.dispatch("finance.month.save", {"month": "2026-02", "entries": {}})
        self.assertEqual(result["months"][1]["opening"], "$1,601.00")
        self.assertEqual(result["months"][0]["entries"][salary]["comment"], "First payment\nSecond payment")
        selected = self.service.dispatch("finance.snapshot", {"period": "CUSTOM", "first": "2026-02", "last": "2026-02"})
        self.assertEqual(len(selected["months"]), 1)
        with self.assertRaises(ServiceError):
            self.service.dispatch("finance.month.save", {"month": "2026-02"})
        with self.assertRaises(ServiceError):
            self.service.dispatch("finance.categories.save", {"income": [{"id": rent, "name": "Invalid"}], "expense": []})
        self.assertEqual(len(self.service.db.list_finance_categories()), len(initial["categories"]))

    def test_quotes_reject_stale_responses_and_do_not_run_when_offline(self):
        aid = self.account(positions=[{"symbol": "AAPL", "quantity": "2", "price": "100"}])
        with mock.patch("desktop_backend.fetch_quotes", side_effect=AssertionError("network")):
            self.assertIsNone(self.service.prepare_network("quotes.refresh", {"account_id": aid}))
            self.assertIsNone(self.service.prepare_network("symbols.search", {"query": "aap"}))
        self.service.dispatch("settings.save", {"live": True})
        _, finish = self.service.prepare_network("quotes.refresh", {"account_id": aid})
        q = lambda price, stamp: Quote(D(price), D("100"), datetime.fromtimestamp(stamp, timezone.utc))
        finish({"AAPL": q("120", 2000)})
        finish({"AAPL": q("110", 1000)})
        self.assertEqual(self.service.prices()["AAPL"], D("120"))
        self.service.dispatch("settings.save", {"live": False})
        finish({"AAPL": q("130", 3000)})
        self.assertEqual(self.service.prices()["AAPL"], D("120"))

    def test_chart_uses_real_quote_points_and_returns_preformatted_scrub_values(self):
        aid = self.account(cash="1000", positions=[{"symbol": "AAPL", "quantity": "2", "price": "100"}])
        self.service.dispatch("settings.save", {"live": True})
        timestamp = int(datetime(2026, 1, 5, 15, tzinfo=timezone.utc).timestamp())
        q = Quote(D("102"), D("100"), None, points=[(timestamp, 100.), (timestamp + 300, 102.)])
        _, finish = self.service.prepare_network("quotes.refresh", {"account_id": aid})
        finish({"AAPL": q})
        result = self.service.dispatch("chart", {"account_id": aid, "range": "1D"})
        self.assertEqual(result["points"][0]["text"], "$1,200.00")
        self.assertEqual(result["points"][1]["text"], "$1,204.00")
        self.assertEqual(result["change"], "+$4.00")

    def test_export_backup_and_finance_toggle_preserve_data(self):
        aid = self.account()
        exported = self.service.dispatch("export", {"folder": self.folder.name, "account_id": aid})
        self.assertEqual(len(exported), 3)
        self.assertTrue(all(Path(p).read_bytes().startswith(b"\xef\xbb\xbf") for p in exported))
        backup = Path(self.folder.name) / "backup.db"
        self.service.dispatch("backup", {"path": str(backup)})
        other = LedgerService(backup, backup=False)
        self.addCleanup(other.close)
        self.assertEqual(other.snapshot({})["summary"]["total"], "$10,000.00")
        self.service.dispatch("settings.save", {"finance": True})
        self.service.dispatch("finance.month.save", {"month": "2026-01", "opening": "22"})
        self.service.dispatch("settings.save", {"finance": False})
        self.service.dispatch("settings.save", {"finance": True})
        self.assertEqual(self.service.finance_snapshot({})["summary"]["ending"], "$22.00")

    def exported_tables(self, **params):
        files = self.service.dispatch("export", {"folder": self.folder.name, **params})
        tables = {}
        for filename in files:
            with Path(filename).open(encoding="utf-8-sig", newline="") as stream:
                table = next(name for name in ("transactions", "holdings", "yearly", "monthly", "entries")
                             if f"_{name}_" in Path(filename).name)
                tables[table] = list(csv.DictReader(stream))
        return tables

    def test_stock_export_filters_activity_after_replaying_earlier_costs_and_balances(self):
        aid = self.account(cash="1000")
        self.txn(aid)
        self.txn(aid, type="SELL", quantity="1", price="150", fee="2", date="2026-02-15")
        self.txn(aid, quantity="1", price="200", date="2026-03-01")
        before = self.service.db.list_txns(aid)
        tables = self.exported_tables(account_id=aid, period="CUSTOM", first="2026-02-01", last="2026-02-28")
        self.assertEqual(len(tables["transactions"]), 1)
        sale = tables["transactions"][0]
        self.assertEqual(sale["Date"], "2026-02-15")
        self.assertEqual(sale["Cash Balance"], "948.00")
        self.assertEqual(sale["Cost Sold"], "100.00")
        self.assertEqual(sale["Realized P/L"], "48.00")
        holding, cash = tables["holdings"]
        self.assertEqual((holding["As Of"], holding["Shares"], holding["Cost Basis"]),
                         ("2026-02-28", "1", "100.00"))
        self.assertEqual((holding["Price"], holding["Market Value"]), ("", ""))
        self.assertEqual(cash["Market Value"], "948.00")
        self.assertEqual(tables["yearly"][0]["Deposits"], "0.00")
        self.assertEqual(tables["yearly"][0]["Realized P/L"], "48.00")
        self.assertEqual(self.service.db.list_txns(aid), before)

    def test_stock_export_inclusive_bounds_open_bounds_empty_range_and_year(self):
        aid = self.account(cash="1000")
        self.txn(aid)
        self.txn(aid, date="2026-02-02")
        for bounds, expected in [
            ({"first": "2026-01-02", "last": "2026-01-02"}, ["2026-01-02"]),
            ({"last": "2026-01-01"}, ["2026-01-01"]),
            ({"first": "2026-02-01"}, ["2026-02-02"]),
            ({"first": "2026-04-01", "last": "2026-04-02"}, []),
        ]:
            with self.subTest(bounds=bounds):
                tables = self.exported_tables(account_id=aid, period="CUSTOM", **bounds)
                self.assertEqual([row["Date"] for row in tables["transactions"]], expected)
        tables = self.exported_tables(account_id=aid, period="2026")
        self.assertEqual(len(tables["transactions"]), 3)

    def test_finance_export_carries_opening_before_filtering_months_and_yearly_totals(self):
        self.service.dispatch("settings.save", {"finance": True})
        cats = self.service.db.list_finance_categories()
        salary = next(c.id for c in cats if c.kind == "income")
        rent = next(c.id for c in cats if c.kind == "expense")
        for month, income, expense in [("2026-01", "1000", "200"), ("2026-02", "500", "300"),
                                        ("2026-03", "700", "100")]:
            self.service.dispatch("finance.month.save", {"month": month, "opening": "100" if month.endswith("01") else "",
                "entries": {str(salary): {"raw": income, "comment": "工资\n第二行"}, str(rent): {"raw": expense}}})
        tables = self.exported_tables(kind="finance", period="CUSTOM", first="2026-02", last="2026-02")
        monthly = tables["monthly"]
        self.assertEqual(len(monthly), 1)
        self.assertEqual((monthly[0]["Month"], monthly[0]["Opening"], monthly[0]["Ending balance"]),
                         ("2026-02", "900.00", "1100.00"))
        year = tables["yearly"][0]
        self.assertEqual((year["Months"], year["Total income"], year["Total expenses"]), ("1", "500.00", "300.00"))
        self.assertEqual([row["Month"] for row in tables["entries"]], ["2026-02", "2026-02"])
        self.assertEqual(tables["entries"][0]["Comment"], "工资\n第二行")
        with mock.patch("desktop_backend.today", return_value="2026-03-31"):
            recent = self.exported_tables(kind="finance", period="3M")
        self.assertEqual([row["Month"] for row in recent["monthly"]], ["2026-01", "2026-02", "2026-03"])

    def test_export_rejects_invalid_ranges_before_writing_and_names_ranges_separately(self):
        aid = self.account()
        for params in [
            {"period": "CUSTOM", "first": "2026-02-30"},
            {"period": "CUSTOM", "first": "2026-02-01", "last": "2026-01-01"},
            {"kind": "finance", "period": "CUSTOM", "first": "2026-13"},
            {"kind": "finance", "period": "CUSTOM", "first": "2026-02", "last": "2026-01"},
            {"period": "invalid"}, {"kind": "invalid"},
        ]:
            with self.subTest(params=params), self.assertRaises(ValueError):
                self.exported_tables(account_id=aid, **params)
        self.assertEqual(list(Path(self.folder.name).glob("*.csv")), [])
        self.exported_tables(account_id=aid, period="2025")
        self.exported_tables(account_id=aid, period="2026")
        self.assertEqual(len(list(Path(self.folder.name).glob("*.csv"))), 6)

    def test_stdio_protocol_has_no_qt_dependency_and_survives_bad_request(self):
        path = Path(self.folder.name) / "stdio.db"
        requests = ["not json", json.dumps({"id": 2, "method": "snapshot"}),
                    json.dumps({"id": 3, "method": "unknown"})]
        proc = subprocess.run([sys.executable, "desktop_backend.py", "--db", str(path)],
                              input="\n".join(requests) + "\n", text=True, encoding="utf-8", capture_output=True,
                              env={**os.environ, "PYTHONIOENCODING": "ascii"}, check=True)
        messages = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(messages[1]["id"], 2)
        self.assertIn("accounts", messages[1]["result"])
        self.assertEqual(messages[2]["error"]["code"], "METHOD_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
