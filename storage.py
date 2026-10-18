"""
storage.py -- persistence with SQLite (built into Python; one .db file holds all data)

Tables:
  accounts      accounts
  transactions  transactions (amounts and share counts stored as text and read back
                as Decimal, so they stay exact)
  prices        manually entered prices (shared by all accounts)
  settings      a few settings, e.g. the last opened account
  finance_categories, finance_months, finance_entries
                income and expenses outside the brokerage accounts (see finance.py): the categories
                (columns), the months (rows) and what each category came to in each month, with its comment.
                Only made once the optional Finance page is turned on (set_finance_enabled); a database whose
                owner never uses it does not get them.

Older databases are upgraded in place when opened (see _upgrade); existing records are never changed.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from finance import EXPENSE, INCOME, FinCategory, FinEntry, FinMonth
from ledger import Txn, to_decimal

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    broker     TEXT NOT NULL DEFAULT '',
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS transactions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    date       TEXT NOT NULL,
    type       TEXT NOT NULL,
    symbol     TEXT NOT NULL DEFAULT '',
    quantity   TEXT NOT NULL DEFAULT '0',
    price      TEXT NOT NULL DEFAULT '0',
    fee        TEXT NOT NULL DEFAULT '0',
    amount     TEXT NOT NULL DEFAULT '0',
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    symbol2    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_txn_account ON transactions(account_id, date, id);

CREATE TABLE IF NOT EXISTS prices (
    symbol     TEXT PRIMARY KEY,
    price      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

FINANCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS finance_categories (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    kind     TEXT NOT NULL CHECK (kind IN ('income', 'expense')),
    name     TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    UNIQUE (kind, name)
);

CREATE TABLE IF NOT EXISTS finance_months (
    month   TEXT PRIMARY KEY,
    opening TEXT
);

CREATE TABLE IF NOT EXISTS finance_entries (
    month       TEXT NOT NULL REFERENCES finance_months(month) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES finance_categories(id) ON DELETE CASCADE,
    amount      TEXT NOT NULL DEFAULT '0',
    expr        TEXT NOT NULL DEFAULT '',
    comment     TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (month, category_id)
);
"""


def _s(d: Decimal) -> str:
    """Decimal -> text without scientific notation."""
    return format(d, "f")


class Storage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._upgrade()
        if self.get_setting("finance_enabled") == "1":
            self.conn.executescript(FINANCE_SCHEMA)

    def _upgrade(self) -> None:
        """Bring a database made by an older version up to date by adding what is missing."""
        columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(transactions)")}
        if "symbol2" not in columns:  # added for Symbol Change (the new symbol)
            with self.conn:
                self.conn.execute("ALTER TABLE transactions ADD COLUMN symbol2 TEXT NOT NULL DEFAULT ''")

    def close(self) -> None:
        self.conn.close()

    # ---------------- Accounts ----------------
    def list_accounts(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()

    def create_account(self, name: str, broker: str = "", note: str = "", opening: list[Txn] = ()) -> int:
        """Create an account and write its opening cash/positions in the same transaction."""
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO accounts(name, broker, note) VALUES (?, ?, ?)", (name, broker, note)
            )
            account_id = cur.lastrowid
            for t in opening:
                t.account_id = account_id
                self._insert_txn(t)
        return account_id

    def update_account(self, account_id: int, name: str, broker: str, note: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE accounts SET name = ?, broker = ?, note = ? WHERE id = ?",
                (name, broker, note, account_id),
            )

    def delete_account(self, account_id: int) -> None:
        with self.conn:  # transactions are removed too via ON DELETE CASCADE
            self.conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))

    # ---------------- Transactions ----------------
    def list_txns(self, account_id: int) -> list[Txn]:
        rows = self.conn.execute(
            "SELECT * FROM transactions WHERE account_id = ? ORDER BY date, id", (account_id,)
        ).fetchall()
        return [
            Txn(
                id=r["id"],
                account_id=r["account_id"],
                date=r["date"],
                type=r["type"],
                symbol=r["symbol"],
                quantity=to_decimal(r["quantity"]),
                price=to_decimal(r["price"]),
                fee=to_decimal(r["fee"]),
                amount=to_decimal(r["amount"]),
                note=r["note"],
                symbol2=r["symbol2"],
            )
            for r in rows
        ]

    def _insert_txn(self, t: Txn) -> int:
        cur = self.conn.execute(
            "INSERT INTO transactions(account_id, date, type, symbol, quantity, price, fee, amount, note, symbol2)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (t.account_id, t.date, t.type, t.symbol, _s(t.quantity), _s(t.price), _s(t.fee), _s(t.amount), t.note,
             t.symbol2),
        )
        t.id = cur.lastrowid
        return t.id

    def add_txn(self, t: Txn) -> int:
        with self.conn:
            return self._insert_txn(t)

    def update_txn(self, t: Txn) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE transactions SET date = ?, type = ?, symbol = ?, quantity = ?, price = ?,"
                " fee = ?, amount = ?, note = ?, symbol2 = ? WHERE id = ?",
                (t.date, t.type, t.symbol, _s(t.quantity), _s(t.price), _s(t.fee), _s(t.amount), t.note, t.symbol2,
                 t.id),
            )

    def delete_txn(self, txn_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))

    # ---------------- Prices ----------------
    def get_prices(self) -> dict[str, tuple[Decimal, str]]:
        """Return {symbol: (price, date updated)}"""
        rows = self.conn.execute("SELECT * FROM prices").fetchall()
        return {r["symbol"]: (to_decimal(r["price"]), r["updated_at"]) for r in rows}

    def set_price(self, symbol: str, price: Decimal | None) -> None:
        self.set_prices({symbol: price})

    def set_prices(self, prices: dict[str, Decimal | None]) -> None:
        """Save several prices in one transaction; None removes that symbol's price."""
        with self.conn:
            for symbol, price in prices.items():
                if price is None:
                    self.conn.execute("DELETE FROM prices WHERE symbol = ?", (symbol,))
                else:
                    self.conn.execute(
                        "INSERT INTO prices(symbol, price, updated_at) VALUES (?, ?, ?)"
                        " ON CONFLICT(symbol) DO UPDATE SET price = excluded.price, updated_at = excluded.updated_at",
                        (symbol, _s(price), date.today().isoformat()),
                    )

    # ---------------- Settings ----------------
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # ---------------- Finance (income and expenses outside the brokerage accounts) ----------------
    def list_finance_categories(self) -> list[FinCategory]:
        rows = self.conn.execute(  # income first, then expenses, each in the order the user arranged
            "SELECT * FROM finance_categories ORDER BY kind = 'expense', position, id").fetchall()
        return [FinCategory(r["id"], r["kind"], r["name"]) for r in rows]

    def _add_finance_category(self, kind: str, name: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO finance_categories(kind, name, position)"
            " VALUES (?, ?, (SELECT COALESCE(MAX(position), 0) + 1 FROM finance_categories WHERE kind = ?))",
            (kind, name, kind),
        )
        return cur.lastrowid

    def set_finance_categories(self, kind: str, items: list[tuple[int | None, str]]) -> None:
        """Make the categories of one kind exactly `items`, in this order: (id, name), with id None for a new one.
        A category left out is deleted together with its amounts and comments."""
        keep = {i for i, _ in items if i is not None}
        with self.conn:
            for row in self.conn.execute("SELECT id FROM finance_categories WHERE kind = ?", (kind,)).fetchall():
                if row["id"] not in keep:
                    self.conn.execute("DELETE FROM finance_categories WHERE id = ?", (row["id"],))
            for cid, _ in items:  # names may be swapped or reused, so free them all first
                if cid is not None:
                    self.conn.execute("UPDATE finance_categories SET name = ? WHERE id = ?", (f"\x01{cid}", cid))
            for position, (cid, name) in enumerate(items, start=1):
                if cid is None:
                    cid = self._add_finance_category(kind, name)
                self.conn.execute("UPDATE finance_categories SET name = ?, position = ? WHERE id = ?",
                                  (name, position, cid))

    def finance_entry_counts(self) -> dict[int, int]:
        """{category id: number of months that have an amount or comment for it}"""
        rows = self.conn.execute("SELECT category_id, COUNT(*) AS n FROM finance_entries GROUP BY category_id")
        return {r["category_id"]: r["n"] for r in rows}

    def seed_finance_defaults(self, income: list[str], expenses: list[str]) -> None:
        """Start the finance page with a few categories -- once, so they do not come back after being deleted."""
        if self.get_setting("finance_seeded") == "1":
            return
        with self.conn:
            if not self.conn.execute("SELECT 1 FROM finance_categories").fetchone():
                for kind, names in ((INCOME, income), (EXPENSE, expenses)):
                    for name in names:
                        self._add_finance_category(kind, name)
        self.set_setting("finance_seeded", "1")

    def list_finance_months(self) -> list[FinMonth]:
        months = {
            r["month"]: FinMonth(r["month"], None if r["opening"] is None else to_decimal(r["opening"]))
            for r in self.conn.execute("SELECT * FROM finance_months ORDER BY month")
        }
        for r in self.conn.execute("SELECT * FROM finance_entries"):
            months[r["month"]].entries[r["category_id"]] = FinEntry(to_decimal(r["amount"]), r["expr"], r["comment"])
        return list(months.values())

    def _save_finance_month(self, m: FinMonth) -> None:
        self.conn.execute(
            "INSERT INTO finance_months(month, opening) VALUES (?, ?)"
            " ON CONFLICT(month) DO UPDATE SET opening = excluded.opening",
            (m.month, None if m.opening is None else _s(m.opening)),
        )
        self.conn.execute("DELETE FROM finance_entries WHERE month = ?", (m.month,))
        for cid, e in m.entries.items():
            if not e.is_empty:
                self.conn.execute(
                    "INSERT INTO finance_entries(month, category_id, amount, expr, comment) VALUES (?, ?, ?, ?, ?)",
                    (m.month, cid, _s(e.amount), e.expr, e.comment),
                )

    def save_finance_month(self, m: FinMonth) -> None:
        """Add a month, or replace the opening balance and all amounts of one that exists."""
        with self.conn:
            self._save_finance_month(m)

    def delete_finance_month(self, month: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM finance_months WHERE month = ?", (month,))

    def finance_enabled(self) -> bool:
        return self.get_setting("finance_enabled") == "1"

    def set_finance_enabled(self, on: bool) -> None:
        """Turn the optional Finance page on (making its tables the first time) or off. Turning it off only hides
        the page: what was entered stays in the database."""
        if on:
            self.conn.executescript(FINANCE_SCHEMA)
        self.set_setting("finance_enabled", "1" if on else "0")

    # ---------------- Backup ----------------
    def backup_to(self, dest: str | Path) -> None:
        """Copy the full database using SQLite's built-in backup API."""
        target = sqlite3.connect(dest)
        try:
            self.conn.backup(target)
        finally:
            target.close()


def daily_backup(db_path: Path, backup_dir: Path, keep: int = 30) -> Path | None:
    """Back up automatically the first time the app opens each day; keep only the latest `keep` copies."""
    if not db_path.exists() or db_path.stat().st_size == 0:
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"stock_ledger_{datetime.now():%Y-%m-%d}.db"
    if not target.exists():
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    old = sorted(backup_dir.glob("stock_ledger_*.db"))
    for f in old[:-keep]:
        f.unlink(missing_ok=True)
    return target
