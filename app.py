"""
app.py -- Stock Ledger (GUI)

Uses only the Python standard library (tkinter + sqlite3); nothing to pip install.
Run:    python app.py
Build:  run build_exe.bat on Windows to get dist\\StockLedger\\StockLedger.exe (a folder build)

Files:
  ledger.py   bookkeeping math (cash, positions, average cost, P/L, value over time)
  storage.py  persistence (SQLite database)
  quotes.py   live stock quotes and price history (Yahoo Finance)
  ui.py       look and feel (themes, fonts, custom widgets)
  app.py      windows and dialogs (this file)
"""

from __future__ import annotations

import csv
import os
import platform
import queue
import re
import sqlite3
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from i18n import DEFAULT_LANGUAGE, LANGUAGES, language, set_language, tr
from finance import (
    EXPENSE,
    FINANCE_PERIODS,
    INCOME,
    FinCategory,
    FinEntry,
    FinMonth,
    FinRow,
    FinSummary,
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
    TYPE_FIELDS,
    ZERO,
    LedgerError,
    LedgerResult,
    Txn,
    combine_results,
    combine_series,
    fmt_money,
    fmt_pct,
    fmt_price,
    fmt_qty,
    parse_date,
    period_range,
    replay,
    to_decimal,
    today,
    valuation,
    value_series,
)
from quotes import Quote, Suggestion, fetch_quotes, is_crypto, match_local, search_symbols
from storage import Storage, daily_backup
from ui import (
    C,
    DEFAULT_TEXT_SIZE,
    TEXT_SIZES,
    UI,
    LineChart,
    PageScroll,
    PillButton,
    ScrollFrame,
    SymbolEntry,
    TabBar,
    Toggle,
    color_for,
    configure_columns,
    label,
    logo,
    make_tree,
    round_rect,
    separator,
    set_theme,
    sort_tree,
    style_menu,
)

APP_NAME = "Stock Ledger"  # shown through tr(), like all UI text
APP_VERSION = "2.0"
LIVE_INTERVAL = 10  # seconds between live price updates
HISTORY_TTL = 600  # seconds to reuse fetched price history before fetching again
DAY_SLOTS = 79  # 5-minute bars in a US trading day (+ the close), so today's line fills the chart as the day goes on
PULSE_FRESH = 20 * 60  # seconds: the 1D chart's dot pulses while its latest price is at most this old (market open)

ALL = "All"  # the "no filter" choice (shown translated)
CUSTOM_PERIOD = "Custom range…"  # the period choice that takes two typed dates (shown translated)
ALL_ACCOUNTS = -1  # account_id of the combined view of every account (read-only)
# chart range -> (Yahoo range, bar interval, wording for the change line); None = computed / intraday
RANGES = {
    "1D": (None, None, "Today"),
    "1W": ("5d", "30m", "Past week"),
    "1M": ("1mo", "1d", "Past month"),
    "3M": ("3mo", "1d", "Past 3 months"),
    "YTD": ("ytd", "1d", "Year to date"),
    "1Y": ("1y", "1d", "Past year"),
    "ALL": (None, None, "All time"),
}


# ======================================================================
# Paths: during development data lives in a data folder next to the source; in the exe, next to the exe
# ======================================================================
def app_dir() -> Path:
    if getattr(sys, "frozen", False):  # exe built by PyInstaller
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_path(name: str) -> Path:
    """Location of resources bundled into the exe (e.g. the icon)."""
    return Path(getattr(sys, "_MEIPASS", app_dir())) / name


def data_dir() -> Path:
    folder = app_dir() / "data"
    try:
        folder.mkdir(exist_ok=True)
        probe = folder / ".write_test"
        probe.write_text("ok")
        probe.unlink()
        return folder
    except OSError:
        # if the exe sits somewhere without write access (e.g. Program Files), use the user profile
        fallback = Path(os.environ.get("APPDATA", Path.home())) / "StockLedger"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def open_folder(path: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif "microsoft" in platform.release().lower():  # WSL: open with Windows Explorer
            win_path = subprocess.check_output(["wslpath", "-w", str(path)], text=True).strip()
            subprocess.Popen(["explorer.exe", win_path])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        messagebox.showinfo(tr(APP_NAME), tr("Data folder location:\n{path}", path=path))


def saved_language(db: Storage) -> str:
    """The chosen interface language; Chinese until one is picked."""
    code = db.get_setting("language")
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def columns(cols):
    """Table column specs with translated titles."""
    return [(key, tr(title), width, anchor) for key, title, width, anchor in cols]


def plural(n: str, one: str, many: str) -> str:
    """tr(one) or tr(many) with {n} filled in; English needs the plural, Chinese does not care."""
    return tr(one if n == "1" else many, n=n)


def holding_text(symbol: str, qty: Decimal) -> str:
    """'10 shares', or '0.5 coins' for crypto."""
    n = fmt_qty(qty)
    return plural(n, "{n} coin", "{n} coins") if is_crypto(symbol) else plural(n, "{n} share", "{n} shares")


def symbol_text(t: Txn) -> str:
    """The symbol column: 'PSKY → NEW' for a symbol change."""
    return f"{t.symbol} → {t.symbol2}" if t.symbol2 else t.symbol


def price_text(t: Txn) -> str:
    """The price column: blank for types without a price; the share of cost moved for a distribution."""
    if "price" not in TYPE_FIELDS[t.type]:
        return ""
    return f"{fmt_qty(t.price)}%" if t.type == "DISTRIBUTION" else fmt_price(t.price)


WEEKDAYS_ZH = "一二三四五六日"


def text_size(db: Storage) -> str:
    """The saved text size choice (a key of TEXT_SIZES)."""
    name = db.get_setting("text_size", DEFAULT_TEXT_SIZE)
    return name if name in TEXT_SIZES else DEFAULT_TEXT_SIZE


def safe_filename(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", text).strip() or "account"


def usd(d: Decimal | float | None, sign: bool = False) -> str:
    """$1,234.56, -$8.80, or +$27.40 with sign=True."""
    if d is None:
        return "-"
    d = Decimal(str(d))
    text = fmt_money(abs(d))
    if text == "0.00":
        return "$0.00"
    if d < 0:
        return "-$" + text
    return ("+$" if sign else "$") + text


def change_text(change, base) -> str:
    """'+$27.40 (+0.64%)'"""
    pct = f" ({fmt_pct(Decimal(str(change)) / Decimal(str(base)))})" if base else ""
    return usd(change, sign=True) + pct


def time_label(ts: int, rng: str) -> str:
    t = datetime.fromtimestamp(ts)
    if language() == "zh":
        if rng == "1D":
            return f"{t:%H:%M}"
        if rng == "1W":
            return f"周{WEEKDAYS_ZH[t.weekday()]} {t:%H:%M}"
        return f"{t.year}年{t.month}月{t.day}日"
    clock = t.strftime("%I:%M %p").lstrip("0")
    if rng == "1D":
        return clock
    if rng == "1W":
        return f"{t:%a} {clock}"
    return f"{t:%b} {t.day}, {t:%Y}"


def all_range(first_date: str) -> tuple[str, str]:
    """Yahoo range/interval covering everything since the first transaction."""
    days = (date.today() - date.fromisoformat(first_date)).days
    for limit, rng, interval in ((90, "3mo", "1d"), (365, "1y", "1d"), (730, "2y", "1d"), (1825, "5y", "1wk")):
        if days <= limit:
            return rng, interval
    return "max", "1mo"


# ======================================================================
# Dialog base class
# ======================================================================
class Dialog(tk.Toplevel):
    def __init__(self, parent, title: str):
        super().__init__(parent, bg=C["bg"])
        self.withdraw()
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.parent = parent
        self.result = None
        self.initial_focus = None
        label(self, title, font=UI.h2).pack(anchor="w", padx=UI.px(20), pady=(UI.px(18), 0))
        self.body = ttk.Frame(self, padding=(UI.px(20), UI.px(12), UI.px(20), UI.px(16)))
        self.body.pack(fill="both", expand=True)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda e: self.cancel())

    def add_buttons(self, ok_text: str | None = None) -> None:
        bar = tk.Frame(self, bg=C["bg"])
        bar.pack(fill="x", padx=UI.px(20), pady=(0, UI.px(18)))
        PillButton(bar, ok_text or tr("Save"), self.ok, "primary").pack(side="right")
        PillButton(bar, tr("Cancel"), self.cancel, "secondary").pack(side="right", padx=(0, UI.px(8)))
        # Enter = save (except inside a multi-line text box)
        self.bind("<Return>", lambda e: None if isinstance(e.widget, tk.Text) else self.ok())

    def show(self, focus=None):
        self.update_idletasks()
        p = self.parent.winfo_toplevel()
        x = p.winfo_rootx() + (p.winfo_width() - self.winfo_reqwidth()) // 2
        y = p.winfo_rooty() + (p.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.deiconify()
        self.grab_set()
        (focus or self.initial_focus or self).focus_set()
        self.wait_window()
        return self.result

    def ok(self) -> None:
        try:
            result = self.build_result()
        except ValueError as e:
            messagebox.showerror(tr("Invalid input"), str(e), parent=self)
            return
        if result is None:
            return
        self.result = result
        self.destroy()

    def cancel(self) -> None:
        self.result = None
        self.destroy()

    def build_result(self):  # implemented by subclasses; returning None keeps the dialog open
        raise NotImplementedError


# ======================================================================
# Add / edit transaction
# ======================================================================
class TxnDialog(Dialog):
    # English text, translated with tr() when shown
    AMOUNT_LABELS = {
        "DEPOSIT": "Deposit amount",
        "WITHDRAW": "Withdrawal amount",
        "DIVIDEND": "Dividend amount",
        "INTEREST": "Interest amount",
        "FEE": "Fee amount",
    }
    HINTS = {
        "DEPOSIT": "Cash transferred in from a bank (also use this for opening cash).",
        "WITHDRAW": "Cash transferred out to a bank.",
        "BUY": "Cash decreases by quantity × price + fee.",
        "SELL": "Cash increases by quantity × price − fee; realized P/L uses average cost.",
        "DIVIDEND": "Cash dividend. If it is reinvested, also record a separate Buy.",
        "INTEREST": "Interest earned on cash (e.g. money market fund income).",
        "FEE": "Other fees, such as account maintenance or ADR fees.",
        "SHARES_IN": "Shares transferred in from elsewhere or held at account opening. Does not affect cash.",
        "SHARES_OUT": "Shares transferred to another account; reduces the position at average cost. Does not affect cash.",
        "SPLIT": "Enter the change in shares: 10 shares split 4-for-1 become 40, so enter 30. "
                 "Use a negative number for a reverse split.",
        "SYMBOL_CHANGE": "Ticker change or merger conversion: the whole position moves to the new symbol with its "
                         "cost basis (no gain or loss). Enter the new shares received; for 1-for-1, press All.",
        "DISTRIBUTION": "Spin-off, warrants or rights handed out on a stock you hold: the new security becomes its own "
                        "position and takes the given percent of the stock's cost basis (0 moves none). Your shares "
                        "of the stock stay the same. Does not affect cash.",
    }

    def __init__(self, parent, title, *, suggest, positions, check, initial: Txn | None = None,
                 default_type="BUY", default_symbol="", default_date=None):
        super().__init__(parent, title)
        self.positions = positions  # {symbol: Position}, for showing current holdings and estimated P/L
        self.check = check  # whole-ledger check before saving (provided by App)
        self.initial = initial

        t = initial
        self.v_date = tk.StringVar(value=t.date if t else (default_date or today()))
        self.type_by_label = {tr(text): code for code, text in TXN_TYPES.items()}
        self.v_type = tk.StringVar(value=tr(TXN_TYPES[t.type if t else default_type]))
        self.v_symbol = tk.StringVar(value=t.symbol if t else default_symbol)
        self.v_symbol2 = tk.StringVar(value=t.symbol2 if t else "")
        self.v_qty = tk.StringVar(value=self._num(t.quantity) if t else "")
        self.v_price = tk.StringVar(value=self._num(t.price) if t else "")
        self.v_fee = tk.StringVar(value=self._num(t.fee) if t else "")
        self.v_amount = tk.StringVar(value=self._num(t.amount) if t else "")
        self.v_note = tk.StringVar(value=t.note if t else "")

        b = self.body
        pad = {"padx": (0, UI.px(14)), "pady": UI.px(5)}
        self.rows: dict[str, list[tk.Widget]] = {}
        self.labels: dict[str, ttk.Label] = {}

        def add_row(key, r, text, widget, extra=None):
            lbl = ttk.Label(b, text=text, style="Muted.TLabel")
            lbl.grid(row=r, column=0, sticky="w", **pad)
            widget.grid(row=r, column=1, sticky="we", pady=UI.px(5))
            widgets = [lbl, widget]
            if extra is not None:
                extra.grid(row=r, column=2, sticky="w", padx=(UI.px(6), 0))
                widgets.append(extra)
            self.rows[key] = widgets
            self.labels[key] = lbl

        add_row("date", 0, tr("Date"), ttk.Entry(b, textvariable=self.v_date, width=24),
                ttk.Button(b, text=tr("Today"), width=6, command=lambda: self.v_date.set(today())))
        self.type_box = ttk.Combobox(b, textvariable=self.v_type, values=list(self.type_by_label),
                                     state="readonly", width=22)
        add_row("type", 1, tr("Type"), self.type_box)
        self.symbol_box = SymbolEntry(b, self.v_symbol, suggest, width=24)
        add_row("symbol", 2, tr("Symbol"), self.symbol_box)
        self.symbol2_box = SymbolEntry(b, self.v_symbol2, suggest, width=24)
        add_row("symbol2", 3, tr("New symbol"), self.symbol2_box)
        self.qty_entry = ttk.Entry(b, textvariable=self.v_qty, width=24, justify="right")
        self.all_btn = ttk.Button(b, text=tr("All"), width=6, command=self._fill_all)
        add_row("quantity", 4, tr("Quantity (shares)"), self.qty_entry, self.all_btn)
        add_row("price", 5, tr("Price"), ttk.Entry(b, textvariable=self.v_price, width=24, justify="right"))
        add_row("fee", 6, tr("Fee"), ttk.Entry(b, textvariable=self.v_fee, width=24, justify="right"))
        self.amount_entry = ttk.Entry(b, textvariable=self.v_amount, width=24, justify="right")
        add_row("amount", 7, tr("Amount"), self.amount_entry)
        add_row("note", 8, tr("Note"), ttk.Entry(b, textvariable=self.v_note, width=24))

        self.hint = ttk.Label(b, style="Muted.TLabel", wraplength=UI.px(380), justify="left")
        self.hint.grid(row=9, column=0, columnspan=3, sticky="w", pady=(UI.px(10), 0))
        self.preview = ttk.Label(b, wraplength=UI.px(380), justify="left")
        self.preview.grid(row=10, column=0, columnspan=3, sticky="w", pady=(UI.px(6), 0))
        b.columnconfigure(1, weight=1)

        self.type_box.bind("<<ComboboxSelected>>", lambda e: self._on_type())
        for box in (self.symbol_box, self.symbol2_box):
            box.bind("<<SymbolPicked>>", lambda e: e.widget.tk_focusNext().focus_set())
        for v in (self.v_symbol, self.v_symbol2, self.v_qty, self.v_price, self.v_fee, self.v_amount):
            v.trace_add("write", lambda *a: self._update_preview())
        self.add_buttons()
        self._on_type()
        self.initial_focus = self.symbol_box if "symbol" in TYPE_FIELDS[self.type_code] else self.amount_entry

    @staticmethod
    def _num(d: Decimal) -> str:
        return "" if d == 0 else format(d.normalize(), "f")

    @property
    def type_code(self) -> str:
        return self.type_by_label[self.v_type.get()]

    def _on_type(self) -> None:
        code = self.type_code
        need = TYPE_FIELDS[code]
        for key in ("symbol", "symbol2", "quantity", "price", "fee", "amount"):
            for w in self.rows[key]:
                w.grid() if key in need else w.grid_remove()
        if code not in ("SELL", "SHARES_OUT", "SYMBOL_CHANGE"):
            self.all_btn.grid_remove()
        self.labels["symbol2"].configure(text=tr("Received symbol" if code == "DISTRIBUTION" else "New symbol"))
        self.labels["quantity"].configure(text=tr("Share change" if code == "SPLIT" else
                                                  "New shares received" if code == "SYMBOL_CHANGE" else
                                                  "Quantity received" if code == "DISTRIBUTION" else
                                                  "Quantity (shares)"))
        self.labels["price"].configure(text=tr("Cost per share" if code == "SHARES_IN" else
                                               "Cost basis moved (%)" if code == "DISTRIBUTION" else "Price"))
        self.labels["amount"].configure(text=tr(self.AMOUNT_LABELS.get(code, "Amount")))
        self.hint.configure(text=tr(self.HINTS[code]) if code in self.HINTS else "")
        self._update_preview()

    def _fill_all(self) -> None:
        pos = self.positions.get(self.v_symbol.get().strip().upper())
        if pos and pos.is_open:
            self.v_qty.set(format(pos.quantity.normalize(), "f"))

    def _current_txn(self) -> Txn:
        return Txn(
            date=parse_date(self.v_date.get()),
            type=self.type_code,
            symbol=self.v_symbol.get(),
            symbol2=self.v_symbol2.get(),
            quantity=to_decimal(self.v_qty.get()),
            price=to_decimal(self.v_price.get()),
            fee=to_decimal(self.v_fee.get()),
            amount=to_decimal(self.v_amount.get()),
            note=self.v_note.get(),
            id=self.initial.id if self.initial else None,
            account_id=self.initial.account_id if self.initial else None,
        ).normalized()

    def _update_preview(self) -> None:
        code = self.type_code
        lines = []
        sym = self.v_symbol.get().strip().upper()
        pos = self.positions.get(sym) if sym else None
        if code in TYPE_FIELDS and "symbol" in TYPE_FIELDS[code] and sym:
            if pos and pos.is_open:
                lines.append(tr("Currently holding {qty} shares of {symbol}, average cost {avg}",
                                qty=fmt_qty(pos.quantity), symbol=sym, avg=fmt_price(pos.avg_cost)))
            else:
                lines.append(tr("No shares of {symbol} currently held", symbol=sym))
        try:
            t = Txn(date=today(), type=code, symbol=sym, quantity=to_decimal(self.v_qty.get()),
                    price=to_decimal(self.v_price.get()), fee=to_decimal(self.v_fee.get()),
                    amount=to_decimal(self.v_amount.get())).normalized()
        except ValueError:
            t = None
        if t is not None:
            if code in ("BUY", "SELL") and t.quantity and t.price:
                lines.append(tr("Trade value {value}", value=fmt_money(t.quantity * t.price)))
            if t.cash_change:
                lines.append(tr("Cash change {value}", value=fmt_money(t.cash_change, sign=True)))
            sym2 = self.v_symbol2.get().strip().upper()
            if code == "SYMBOL_CHANGE" and pos and pos.is_open and t.quantity and sym2 and sym2 != sym:
                lines.append(tr("{old_qty} shares of {symbol} become {qty} shares of {new}; cost basis {cost} carries over",
                                old_qty=fmt_qty(pos.quantity), symbol=sym, qty=fmt_qty(t.quantity), new=sym2,
                                cost=fmt_money(pos.cost)))
            if (code == "DISTRIBUTION" and pos and pos.is_open and t.quantity and sym2 and sym2 != sym
                    and 0 <= t.price <= 100):
                moved = pos.cost * t.price / 100
                lines.append(tr("{pct}% of {symbol}'s cost basis ({moved}) goes to {qty} {new}; "
                                "{symbol} average cost becomes {avg}",
                                pct=fmt_qty(t.price), symbol=sym, moved=fmt_money(moved), qty=fmt_qty(t.quantity),
                                new=sym2, avg=fmt_price((pos.cost - moved) / pos.quantity)))
            if code == "SELL" and pos and pos.is_open and t.quantity and t.price and t.quantity <= pos.quantity:
                est = t.quantity * t.price - t.fee - pos.avg_cost * t.quantity
                lines.append(tr("Estimated realized P/L {value}", value=fmt_money(est, sign=True)))
        self.preview.configure(text="\n".join(lines))

    def build_result(self):
        t = self._current_txn()
        t.validate()
        if not self.check(t, self):
            return None
        return t


# ======================================================================
# New / edit account
# ======================================================================
class AccountDialog(Dialog):
    def __init__(self, parent, title, *, suggest, initial=None):
        super().__init__(parent, title)
        self.is_new = initial is None
        self.v_name = tk.StringVar(value=initial["name"] if initial else "")
        self.v_broker = tk.StringVar(value=initial["broker"] if initial else "Fidelity")
        self.v_note = tk.StringVar(value=initial["note"] if initial else "")
        self.v_date = tk.StringVar(value=today())
        self.v_cash = tk.StringVar()

        b = self.body
        pad = {"padx": (0, UI.px(14)), "pady": UI.px(5), "sticky": "w"}
        ttk.Label(b, text=tr("Account name *"), style="Muted.TLabel").grid(row=0, column=0, **pad)
        self.name_entry = ttk.Entry(b, textvariable=self.v_name, width=34)
        self.name_entry.grid(row=0, column=1, sticky="we", pady=UI.px(4))
        ttk.Label(b, text=tr("Broker"), style="Muted.TLabel").grid(row=1, column=0, **pad)
        ttk.Entry(b, textvariable=self.v_broker, width=34).grid(row=1, column=1, sticky="we", pady=UI.px(4))
        ttk.Label(b, text=tr("Note"), style="Muted.TLabel").grid(row=2, column=0, **pad)
        ttk.Entry(b, textvariable=self.v_note, width=34).grid(row=2, column=1, sticky="we", pady=UI.px(4))

        if self.is_new:
            separator(b).grid(row=3, column=0, columnspan=2, sticky="we", pady=UI.px(14))
            label(b, tr("Opening balances"), font=UI.bold).grid(row=4, column=0, columnspan=2, sticky="w")
            ttk.Label(b, text=tr("Optional, can be added later"), style="Muted.TLabel").grid(
                row=5, column=0, columnspan=2, sticky="w", pady=(0, UI.px(6)))
            ttk.Label(b, text=tr("Opening date"), style="Muted.TLabel").grid(row=6, column=0, **pad)
            ttk.Entry(b, textvariable=self.v_date, width=34).grid(row=6, column=1, sticky="we", pady=UI.px(4))
            ttk.Label(b, text=tr("Opening cash"), style="Muted.TLabel").grid(row=7, column=0, **pad)
            ttk.Entry(b, textvariable=self.v_cash, width=34, justify="right").grid(row=7, column=1, sticky="we", pady=UI.px(4))
            ttk.Label(b, text=tr("Opening positions"), style="Muted.TLabel").grid(
                row=8, column=0, padx=(0, UI.px(14)), pady=(UI.px(22), 0), sticky="nw")
            self._build_position_editor(b, suggest).grid(row=8, column=1, sticky="we", pady=UI.px(5))
        b.columnconfigure(1, weight=1)
        self.add_buttons(tr("Create Account") if self.is_new else None)
        self.initial_focus = self.name_entry

    # --- opening positions: fill in the cells, press + (or Enter) to add a row to the list
    def _build_position_editor(self, parent, suggest) -> tk.Frame:
        ed = tk.Frame(parent, bg=C["bg"])
        self.v_pos_sym, self.v_pos_qty, self.v_pos_cost = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.opening_positions: list[tuple[str, Decimal, Decimal]] = []  # (symbol, shares, cost per share)
        for col, text in enumerate(("SYMBOL", "SHARES", "COST / SHARE")):
            label(ed, tr(text), font=UI.small_bold, color=C["muted"]).grid(row=0, column=col, sticky="w",
                                                                     padx=(0, UI.px(6)), pady=(0, UI.px(3)))
        self.pos_sym_entry = SymbolEntry(ed, self.v_pos_sym, suggest, width=9)
        entries = (self.pos_sym_entry,
                   ttk.Entry(ed, textvariable=self.v_pos_qty, width=10, justify="right"),
                   ttk.Entry(ed, textvariable=self.v_pos_cost, width=11, justify="right"))
        for col, e in enumerate(entries):
            e.grid(row=1, column=col, sticky="we", padx=(0, UI.px(6)))
            e.bind("<Return>", lambda ev: (self._add_position(), "break")[1])  # Enter adds the row, not save
        self.pos_sym_entry.bind("<<SymbolPicked>>", lambda ev: entries[1].focus_set())
        PillButton(ed, "+", self._add_position, "primary", font=UI.h2, padx=10, pady=2).grid(row=1, column=3)
        self.pos_list = ScrollFrame(ed)
        self.pos_list.grid(row=2, column=0, columnspan=4, sticky="we", pady=(UI.px(10), 0))
        self.pos_summary = label(ed, "", font=UI.small, color=C["muted"], justify="left", anchor="w")
        self.pos_summary.grid(row=3, column=0, columnspan=4, sticky="w", pady=(UI.px(6), 0))
        self._render_positions()
        return ed

    def _parse_position(self) -> tuple[str, Decimal, Decimal]:
        t = Txn(date=today(), type="SHARES_IN", symbol=self.v_pos_sym.get(), quantity=to_decimal(self.v_pos_qty.get()),
                price=to_decimal(self.v_pos_cost.get())).normalized()
        t.validate()
        return t.symbol, t.quantity, t.price

    def _add_position(self):
        try:
            self.opening_positions.append(self._parse_position())
        except ValueError as e:
            messagebox.showerror(tr("Invalid input"), str(e), parent=self)
            return
        for v in (self.v_pos_sym, self.v_pos_qty, self.v_pos_cost):
            v.set("")
        self._render_positions()
        self.pos_sym_entry.focus_set()

    def _remove_position(self, index: int):
        del self.opening_positions[index]
        self._render_positions()

    def _render_positions(self):
        inner = self.pos_list.inner
        for w in inner.winfo_children():
            w.destroy()
        for i, (sym, qty, cost) in enumerate(self.opening_positions):
            pady = UI.px(3)
            label(inner, sym, font=UI.bold).grid(row=i, column=0, sticky="w", pady=pady)
            label(inner, holding_text(sym, qty)).grid(row=i, column=1, sticky="e", padx=UI.px(10), pady=pady)
            label(inner, f"@ {usd(cost)}", color=C["muted"]).grid(row=i, column=2, sticky="e", pady=pady)
            label(inner, usd(qty * cost)).grid(row=i, column=3, sticky="e", padx=UI.px(10), pady=pady)
            PillButton(inner, "×", lambda i=i: self._remove_position(i), "ghost", font=UI.h2,
                       padx=7, pady=0).grid(row=i, column=4, pady=pady)
        inner.columnconfigure(0, weight=1)
        inner.columnconfigure(3, weight=1)
        n = len(self.opening_positions)
        if n:
            total = sum((q * c for _, q, c in self.opening_positions), ZERO)
            self.pos_summary.configure(text=tr("{n} position · {total} total cost" if n == 1 else
                                               "{n} positions · {total} total cost", n=n, total=usd(total)))
            inner.update_idletasks()
            self.pos_list.canvas.configure(height=min(inner.winfo_reqheight(), UI.px(170)))
            self.pos_list.grid()
        else:
            self.pos_summary.configure(text=tr("Fill in the cells and press + (or Enter) to add each stock."))
            self.pos_list.grid_remove()

    def build_result(self):
        name = self.v_name.get().strip()
        if not name:
            raise ValueError(tr("Please enter an account name"))
        result = {"name": name, "broker": self.v_broker.get().strip(), "note": self.v_note.get().strip()}
        if self.is_new:
            start = parse_date(self.v_date.get())
            cash = to_decimal(self.v_cash.get())
            if cash < 0:
                raise ValueError(tr("Opening cash cannot be negative"))
            opening = []
            if cash > 0:
                opening.append(Txn(date=start, type="DEPOSIT", amount=cash, note=tr("Opening cash")))
            if any(v.get().strip() for v in (self.v_pos_sym, self.v_pos_qty, self.v_pos_cost)):
                # a row typed into the cells but not added yet: include it rather than silently dropping it
                try:
                    self.opening_positions.append(self._parse_position())
                except ValueError as e:
                    raise ValueError(tr("Opening position not added yet: {error}", error=e)) from None
                for v in (self.v_pos_sym, self.v_pos_qty, self.v_pos_cost):
                    v.set("")
                self._render_positions()
            for sym, qty, cost in self.opening_positions:
                opening.append(Txn(date=start, type="SHARES_IN", symbol=sym, quantity=qty, price=cost,
                                   note=tr("Opening position")))
            result["opening"] = opening
        return result


# ======================================================================
# Update prices
# ======================================================================
class PriceDialog(Dialog):
    def __init__(self, parent, positions, prices: dict[str, tuple[Decimal, str]], live: bool = False):
        super().__init__(parent, tr("Update Prices"))
        b = self.body
        text = tr("Live prices are on: prices here are replaced automatically for symbols that have a live quote. "
                  "Use this for holdings without one (e.g. CDs or private funds). Leave blank to clear.") if live else \
            tr("Live prices are off, so prices are entered by hand. They are used to compute market value "
               "and unrealized P/L. Leave blank to clear.")
        ttk.Label(b, style="Muted.TLabel", justify="left", wraplength=UI.px(420), text=text).pack(
            anchor="w", pady=(0, UI.px(10)))

        scroll = ScrollFrame(b)
        scroll.pack(fill="both", expand=True)
        inner = scroll.inner
        for col, text in enumerate(("SYMBOL", "SHARES", "PRICE", "LAST UPDATED")):
            label(inner, tr(text), font=UI.small_bold, color=C["muted"]).grid(row=0, column=col, sticky="w",
                                                                        padx=UI.px(6), pady=UI.px(4))
        self.vars: dict[str, tk.StringVar] = {}
        self.first_entry = None
        for r, p in enumerate(positions, start=1):
            old = prices.get(p.symbol)
            var = tk.StringVar(value=format(old[0].normalize(), "f") if old else "")
            self.vars[p.symbol] = var
            label(inner, p.symbol, font=UI.bold).grid(row=r, column=0, sticky="w", padx=UI.px(6))
            label(inner, fmt_qty(p.quantity)).grid(row=r, column=1, sticky="e", padx=UI.px(6))
            e = ttk.Entry(inner, textvariable=var, width=14, justify="right")
            e.grid(row=r, column=2, padx=UI.px(6), pady=UI.px(3))
            self.first_entry = self.first_entry or e
            label(inner, old[1] if old else "-", color=C["muted"]).grid(row=r, column=3, sticky="w", padx=UI.px(6))
        inner.update_idletasks()
        scroll.canvas.configure(width=inner.winfo_reqwidth(), height=min(inner.winfo_reqheight(), UI.px(420)))
        self.add_buttons()
        self.initial_focus = self.first_entry

    def build_result(self):
        result = {}
        for sym, var in self.vars.items():
            text = var.get().strip()
            if text == "":
                result[sym] = None
                continue
            price = to_decimal(text)
            if price <= 0:
                raise ValueError(tr("Price for {symbol} must be greater than 0", symbol=sym))
            result[sym] = price
        return result


# ======================================================================
# Shared pieces of the main window and the stock page
# ======================================================================
class StatGrid(tk.Frame):
    """Grid of small 'LABEL / value / note' stats."""

    def __init__(self, parent, specs: list[tuple[str, str]], columns: int = 4, notes: bool = True):
        super().__init__(parent, bg=C["bg"])
        self.cells: dict[str, tuple[tk.Label, tk.Label]] = {}
        for i, (key, title) in enumerate(specs):
            cell = tk.Frame(self, bg=C["bg"])
            cell.grid(row=i // columns, column=i % columns, sticky="nw", pady=(0, UI.px(12)))
            label(cell, title.upper(), font=UI.small_bold, color=C["muted"]).pack(anchor="w")
            value = label(cell, "-", font=UI.stat)
            value.pack(anchor="w", pady=(UI.px(2), 0))
            note = label(cell, "", font=UI.small, color=C["muted"])
            if notes:  # without the line under each value the grid is shorter (the note label is then never shown)
                note.pack(anchor="w")
            self.cells[key] = (value, note)
        for c in range(columns):
            self.columnconfigure(c, weight=1, uniform="stat")

    def set(self, key, value: str, note: str = "", color: str | None = None):
        v, n = self.cells[key]
        v.configure(text=value, fg=color or C["text"])
        n.configure(text=note)


class Hero(tk.Frame):
    """Big number, the change under it, a line chart and range tabs -- the top of a Robinhood page."""

    def __init__(self, parent, title: str, on_range, chart_height=210, slots_1d=DAY_SLOTS):
        super().__init__(parent, bg=C["bg"])
        self.title = label(self, title, font=UI.bold, color=C["muted"])
        self.title.pack(anchor="w")
        self.value = label(self, "-", font=UI.hero)
        self.value.pack(anchor="w")
        row = tk.Frame(self, bg=C["bg"])
        row.pack(anchor="w", pady=(0, UI.px(8)))
        self.change = label(row, "", font=UI.bold)
        self.change.pack(side="left")
        self.period = label(row, "", font=UI.body, color=C["muted"])
        self.period.pack(side="left", padx=(UI.px(6), 0))
        self.chart = LineChart(self, height=UI.px(chart_height), on_hover=self._hover)
        self.chart.pack(fill="x")
        self.tabs = TabBar(self, list(RANGES), on_range, font=UI.small_bold, gap=22,
                           labels={key: tr(key) for key in RANGES})
        self.tabs.pack(anchor="w", pady=(UI.px(6), 0))
        self.slots_1d = slots_1d
        self.rng = "1D"
        self.points: list[tuple[int, float, float]] = []  # (time, value, net deposits)
        self.baseline: float | None = None
        self.now: tuple[str, str, str, str] = ("-", "", "", "")  # value, change, color, period

    def show(self, rng, now_value: str, points, *, baseline=None, now_change=None, now_base=None, message=""):
        """points: [(unix time, value, net deposits)]; change is measured against `baseline` if given
        (1D: previous close), otherwise against the first point with deposits/withdrawals taken out."""
        self.rng = rng
        self.points = points
        self.baseline = baseline
        if now_change is None and len(points) >= 2:
            now_change, now_base = self._change(len(points) - 1)
        color = color_for(now_change) if now_change else C["gain"]
        self.now = (now_value, change_text(now_change, now_base) if now_change is not None else "",
                    color, tr(RANGES[rng][2]) if now_change is not None else "")
        # like Robinhood, the end of today's line pulses while prices are coming in
        live = rng == "1D" and bool(points) and time.time() - points[-1][0] < PULSE_FRESH
        self.chart.set_data([p[1] for p in points], color=color, baseline=baseline,
                            labels=[time_label(p[0], rng) for p in points],
                            slots=self.slots_1d if rng == "1D" else 0, message=message, pulse=live)
        self.tabs.set_accent(color)
        self._hover(None)

    def _change(self, i):
        t, v, n = self.points[i]
        if self.baseline is not None:
            return v - self.baseline, self.baseline
        t0, v0, n0 = self.points[0]
        flows = n - n0
        return (v - v0) - flows, (v0 + flows if v0 + flows > 0 else None)

    def _hover(self, i):
        if i is None:
            value, change, color, period = self.now
        else:
            ch, base = self._change(i)
            value, change, color, period = usd(self.points[i][1]), change_text(ch, base), color_for(ch), ""
        self.value.configure(text=value)
        self.change.configure(text=change, fg=color)
        self.period.configure(text=period)


# ======================================================================
# Per-stock page
# ======================================================================
class SymbolDetail(PageScroll):
    """One stock's page. It takes the place of the overview in the main window (Back or Esc returns)."""

    COLUMNS = [
        ("date", "Date", 95, "w"), ("type", "Type", 90, "w"), ("qty", "Quantity", 80, "e"),
        ("price", "Price", 80, "e"), ("fee", "Fee", 65, "e"), ("cash", "Cash Change", 100, "e"),
        ("hold", "Shares After", 95, "e"), ("avg", "Avg Cost After", 110, "e"),
        ("realized", "Realized P/L", 100, "e"), ("note", "Note", 140, "w"),
    ]
    ACCOUNT_COLUMN = ("account", "Account", 110, "w")  # first column in the all-accounts view

    def __init__(self, app: "App", parent, symbol: str):
        super().__init__(parent)
        self.app = app
        self.symbol = symbol
        self.combined = app.combined  # all accounts added up: read-only, and the history says which account
        self.history: dict[str, tuple[float, Quote | None]] = {}  # range -> (fetched at, quote with history)
        self.rng = "1D"

        page = self.inner
        top = tk.Frame(page, bg=C["bg"])
        top.pack(fill="x")
        PillButton(top, tr("Back"), app.close_detail, "ghost", icon="back", padx=12, pady=5).pack(side="left")
        for code, kind in (() if self.combined else (("BUY", "primary"), ("SELL", "outline"), ("DIVIDEND", "secondary"))):
            PillButton(top, tr(TXN_TYPES[code]), lambda c=code: app.add_txn(default_type=c, default_symbol=symbol),
                       kind).pack(side="right", padx=(UI.px(8), 0))

        self.hero = Hero(page, symbol, self._on_range, chart_height=180)
        self.hero.title.configure(font=UI.h1, fg=C["text"])
        self.hero.pack(fill="x", pady=(UI.px(6), 0))

        separator(page).pack(fill="x", pady=UI.px(12))
        label(page, tr("Your position"), font=UI.h2).pack(anchor="w", pady=(0, UI.px(10)))
        self.stats = StatGrid(page, [
            ("shares", tr("Shares")), ("avg", tr("Average cost")), ("value", tr("Market value")),
            ("cost", tr("Cost basis")), ("day", tr("Today's return")), ("unreal", tr("Total return")),
            ("realized", tr("Realized P/L")), ("div", tr("Dividends")),
        ], notes=False)
        self.stats.pack(fill="x")
        separator(page).pack(fill="x", pady=(UI.px(4), UI.px(12)))
        label(page, tr("History"), font=UI.h2).pack(anchor="w", pady=(0, UI.px(6)))
        frame, self.tree = make_tree(page, columns(([self.ACCOUNT_COLUMN] if self.combined else []) + self.COLUMNS))
        frame.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self._on_double)
        self.reload()
        self.bind_wheel()

    def _on_double(self, event):
        if not self.combined and self.tree.identify_region(event.x, event.y) == "cell" and self.tree.focus():
            self.app.edit_txn(int(self.tree.focus()))

    def _on_range(self, rng):
        self.rng = rng
        self.update_chart()

    def update_chart(self):
        app, sym = self.app, self.symbol
        q = app.quotes.get(sym)
        price = app.prices.get(sym)
        if q and q.name:
            self.hero.title.configure(text=f"{q.name} ({sym})" if q.name.upper() != sym else sym)
        now_value = usd(price) if price is not None else "-"
        if not app.v_live.get():
            self.hero.show(self.rng, now_value, [], message=tr("Turn on Live prices to see the chart"))
            return
        if self.rng == "1D":
            if not q or len(q.points) < 2:
                self.hero.show(self.rng, now_value, [], message=tr("Loading…" if app._fetching else "No chart data"))
                return
            points = [(t, c, 0.0) for t, c in q.points] + [(int(time.time()), float(q.price), 0.0)]
            self.hero.show("1D", now_value, points, baseline=float(q.prev_close) if q.prev_close else None)
            return
        fetched, hq = self.history.get(self.rng, (0, None))
        if time.time() - fetched > HISTORY_TTL:
            if self.rng == "ALL":
                first = next((r.txn.date for r in app.result.rows if sym in (r.txn.symbol, r.txn.symbol2)), today())
                yr, iv = all_range(first)
            else:
                yr, iv = RANGES[self.rng][:2]
            rng = self.rng
            self.history[rng] = (time.time(), hq)  # don't start a second fetch meanwhile
            app.run_bg(fetch_quotes, ([sym], yr, iv), lambda res: self._got_history(rng, res))
        if not hq or len(hq.points) < 2:
            self.hero.show(self.rng, now_value, [], message=tr("Loading…"))
            return
        points = [(t, c, 0.0) for t, c in hq.points]
        if q:
            points.append((int(time.time()), float(q.price), 0.0))
        self.hero.show(self.rng, now_value, points)

    def _got_history(self, rng, res):
        if self.app.detail is not self:  # the page was left while the chart was loading
            return
        if isinstance(res, Exception):
            self.history[rng] = (0, None)
            self.hero.show(rng, self.hero.now[0], [], message=tr("Couldn't load the chart (offline?)"))
            return
        self.history[rng] = (time.time(), res.get(self.symbol))
        if rng == self.rng:
            self.update_chart()

    def reload(self):
        res = self.app.result
        pos = res.positions.get(self.symbol)
        if pos is None:  # no transactions left for this stock
            self.app.close_detail()
            return
        price = self.app.prices.get(self.symbol)
        q = self.app.quotes.get(self.symbol)
        st = self.stats
        st.set("shares", fmt_qty(pos.quantity))
        st.set("avg", usd(pos.avg_cost) if pos.is_open else "-")
        st.set("cost", usd(pos.cost) if pos.is_open else "-")
        if pos.is_open and price is not None:
            mv = pos.quantity * price
            st.set("value", usd(mv))
            st.set("unreal", change_text(mv - pos.cost, pos.cost), color=color_for(mv - pos.cost))
        else:
            st.set("value", "-")
            st.set("unreal", "-")
        if pos.is_open and q and q.change is not None:
            day = pos.quantity * q.change
            st.set("day", change_text(day, pos.quantity * q.prev_close), color=color_for(day))
        else:
            st.set("day", "-")
        st.set("realized", usd(pos.realized, sign=True), color=color_for(pos.realized))
        st.set("div", usd(pos.dividends))
        self.update_chart()

        self.tree.delete(*self.tree.get_children())
        names = {a["id"]: a["name"] for a in self.app.accounts}
        for row in (r for r in reversed(res.rows) if self.symbol in (r.txn.symbol, r.txn.symbol2)):
            t = row.txn
            need = TYPE_FIELDS[t.type]
            if t.symbol2 and t.symbol == self.symbol:  # this stock became another one, or handed one out
                qty_after, avg_after = row.source_after
            else:
                qty_after, avg_after = row.qty_after, row.avg_cost_after
            tags = [] if t.type != "SELL" else ["gain" if row.realized > 0 else "loss" if row.realized < 0 else ""]
            values = (
                t.date, f"{t.type_label} ({symbol_text(t)})" if t.symbol2 else t.type_label,
                fmt_qty(t.quantity, sign=t.type == "SPLIT") if "quantity" in need else "",
                price_text(t),
                fmt_money(t.fee) if t.fee else "",
                fmt_money(t.cash_change, sign=True) if t.cash_change else "",
                fmt_qty(qty_after),
                fmt_price(avg_after) if qty_after else "-",
                fmt_money(row.realized, sign=True) if t.type == "SELL" else "",
                t.note,
            )
            if self.combined:  # the running shares and average cost are those of that account
                values = (names.get(t.account_id, ""), *values)
            self.tree.insert("", "end", iid=str(t.id), tags=[x for x in tags if x], values=values)


# ======================================================================
# Finance: income and expenses outside the brokerage accounts, month by month
# ======================================================================
def cell_text(entry: FinEntry | None) -> str:
    """What a category came to in a month; a • in front marks a cell that has a comment."""
    text = fmt_money(entry.amount) if entry is not None and entry.amount else "-"
    return f"• {text}" if entry is not None and entry.comment else text


def comment_box(parent, width: int, text: str = "", rows: tuple[int, int] = (2, 6)) -> tk.Text:
    """A multi-line text box that looks like the entry boxes, as tall as what is written in it (between the
    fewest and most lines in `rows`). Tab moves on instead of typing a tab."""
    box = tk.Text(parent, width=width, height=rows[0], wrap="word", font=UI.body, bg=C["chip"], fg=C["text"],
                  insertbackground=C["text"], relief="flat", bd=0, highlightthickness=1, undo=True,
                  highlightbackground=C["chip"], highlightcolor=C["accent"], padx=UI.px(6), pady=UI.px(4))
    box.insert("1.0", text)

    def fit(event=None):
        lines = sum(max(1, -(-len(line) // width)) for line in box.get("1.0", "end-1c").split("\n"))
        box.configure(height=min(max(lines, rows[0]), rows[1]))

    box.bind("<KeyRelease>", fit, add="+")
    box.bind("<Tab>", lambda e: (e.widget.tk_focusNext().focus_set(), "break")[1])
    fit()
    return box


class FinanceMonthDialog(Dialog):
    """Add or edit one month: an amount and a comment for every category, like a row of a spreadsheet."""

    def __init__(self, parent, title, *, categories: list[FinCategory], initial: FinMonth | None, month: str,
                 existing: set[str], carried, focus: int | None = None):
        super().__init__(parent, title)
        self.categories = categories
        self.existing = existing  # months that are in the table already
        self.carried = carried  # month -> the ending balance of the month before it
        self.is_new = initial is None
        self.v_month = tk.StringVar(value=month)
        self.v_opening = tk.StringVar(
            value=format(initial.opening, "f") if initial and initial.opening is not None else "")
        self.v_amount: dict[int, tk.StringVar] = {}  # category id -> what is typed in its amount box
        self.sums: dict[int, tk.Label] = {}  # category id -> the "= 2,501.00" next to a sum
        self.comments: dict[int, tk.Text] = {}
        self.amount_entries: dict[int, ttk.Entry] = {}

        top = tk.Frame(self.body, bg=C["bg"])
        top.pack(fill="x")
        ttk.Label(top, text=tr("Month"), style="Muted.TLabel").grid(row=0, column=0, sticky="w",
                                                                    padx=(0, UI.px(14)), pady=UI.px(5))
        self.month_entry = ttk.Entry(top, textvariable=self.v_month, width=12)
        self.month_entry.grid(row=0, column=1, sticky="w")
        if not self.is_new:
            self.month_entry.state(["readonly"])
        ttk.Label(top, text=tr("Opening balance"), style="Muted.TLabel").grid(row=1, column=0, sticky="w",
                                                                              padx=(0, UI.px(14)), pady=UI.px(5))
        ttk.Entry(top, textvariable=self.v_opening, width=16, justify="right").grid(row=1, column=1, sticky="w")
        self.opening_hint = ttk.Label(top, style="Muted.TLabel")
        self.opening_hint.grid(row=1, column=2, sticky="w", padx=(UI.px(10), 0))

        self.scroll = ScrollFrame(self.body)
        self.scroll.pack(fill="both", expand=True, pady=(UI.px(10), 0))
        inner = self.scroll.inner
        for col, text in enumerate(("CATEGORY", "AMOUNT", "COMMENT")):
            label(inner, tr(text), font=UI.small_bold, color=C["muted"]).grid(
                row=0, column=(0, 1, 3)[col], sticky="w", padx=(0, UI.px(10)), pady=(0, UI.px(3)))
        row, kind = 1, None
        for c in categories:
            if c.kind != kind:
                kind = c.kind
                label(inner, tr("Income" if kind == INCOME else "Expenses"), font=UI.bold).grid(
                    row=row, column=0, columnspan=4, sticky="w", pady=(UI.px(10), UI.px(2)))
                row += 1
            entry = initial.entries.get(c.id) if initial else None
            typed = (entry.expr or format(entry.amount.normalize(), "f")) if entry and entry.amount else ""
            self.v_amount[c.id] = var = tk.StringVar(value=typed)
            label(inner, c.name, anchor="w", justify="left", wraplength=UI.px(170)).grid(
                row=row, column=0, sticky="nw", padx=(0, UI.px(10)), pady=(UI.px(8), 0))
            self.amount_entries[c.id] = ttk.Entry(inner, textvariable=var, width=28, justify="right")
            self.amount_entries[c.id].grid(row=row, column=1, sticky="nw", padx=(0, UI.px(6)), pady=UI.px(4))
            self.sums[c.id] = label(inner, "", font=UI.small, color=C["muted"], anchor="w", width=13)
            self.sums[c.id].grid(row=row, column=2, sticky="nw", padx=(0, UI.px(10)), pady=(UI.px(10), 0))
            self.comments[c.id] = comment_box(inner, 34, entry.comment if entry else "")
            self.comments[c.id].grid(row=row, column=3, sticky="we", pady=UI.px(4))
            var.trace_add("write", lambda *a, cid=c.id: (self._update_row(cid), self._update_summary()))
            self._update_row(c.id)
            row += 1
        inner.update_idletasks()
        self.scroll.canvas.configure(width=inner.winfo_reqwidth(),
                                     height=min(inner.winfo_reqheight(), int(self.winfo_screenheight() * 0.5)))

        self.summary = label(self.body, "", font=UI.bold, anchor="w")
        self.summary.pack(anchor="w", pady=(UI.px(12), 0))
        ttk.Label(self.body, style="Muted.TLabel", wraplength=UI.px(560), justify="left",
                  text=tr("An amount can be a sum, like 1250.50+1250.50; the parts are kept so you can see them later.")
                  ).pack(anchor="w", pady=(UI.px(4), 0))
        for v in (self.v_month, self.v_opening):
            v.trace_add("write", lambda *a: self._update_summary())
        self._update_summary()
        self.add_buttons()
        first = self.amount_entries.get(focus) or next(iter(self.amount_entries.values()), None)
        self.initial_focus = first or self.month_entry
        self.after(60, lambda: self._reveal(self.initial_focus))

    def _reveal(self, widget) -> None:
        """Scroll the list of categories so that the box with the focus is in view."""
        try:
            total, shown = self.scroll.inner.winfo_height(), self.scroll.canvas.winfo_height()
            if widget in self.amount_entries.values() and total > shown:
                self.scroll.canvas.yview_moveto(min(max((widget.winfo_y() - UI.px(40)) / total, 0), 1))
        except tk.TclError:  # the dialog was closed meanwhile
            pass

    def _update_row(self, cid: int) -> None:
        try:
            entry = entry_from_text(self.v_amount[cid].get())
        except ValueError:
            self.sums[cid].configure(text=tr("Invalid"), fg=C["loss"])
        else:
            self.sums[cid].configure(text=f"= {fmt_money(entry.amount)}" if entry.expr else "", fg=C["muted"])

    def _update_summary(self) -> None:
        income = expenses = ZERO
        for c in self.categories:
            try:
                amount = eval_amount(self.v_amount[c.id].get())
            except ValueError:
                continue
            if c.kind == INCOME:
                income += amount
            else:
                expenses += amount
        try:
            carried = self.carried(parse_month(self.v_month.get()))
        except ValueError:
            carried = None
        try:
            typed = eval_amount(self.v_opening.get()) if self.v_opening.get().strip() else None
        except ValueError:
            typed = None
        opening = typed if typed is not None else carried
        self.opening_hint.configure(
            text=tr("Leave blank to continue from the previous month's ending balance ({value})",
                    value=fmt_money(carried)) if carried is not None else "")
        self.summary.configure(text=tr("Income {income} · Expenses {expenses} · Ending balance {ending}",
                                       income=fmt_money(income), expenses=fmt_money(expenses),
                                       ending=fmt_money(opening + income - expenses) if opening is not None else "-"))

    def build_result(self):
        month = parse_month(self.v_month.get())
        if self.is_new and month in self.existing:
            raise ValueError(tr("{month} already exists. Double-click it in the table to edit it.", month=month))
        opening = eval_amount(self.v_opening.get()) if self.v_opening.get().strip() else None
        entries = {}
        for c in self.categories:
            try:
                entry = entry_from_text(self.v_amount[c.id].get(), self.comments[c.id].get("1.0", "end"))
            except ValueError as e:
                raise ValueError(tr("{category}: {error}", category=c.name, error=e)) from None
            if not entry.is_empty:
                entries[c.id] = entry
        return FinMonth(month, opening, entries)


class FinanceCategoriesDialog(Dialog):
    """Add, rename, reorder and delete the income and expense categories -- the columns of the finance table."""

    def __init__(self, parent, categories: list[FinCategory], used: dict[int, int]):
        super().__init__(parent, tr("Income and Expense Categories"))
        self.used = used  # category id -> in how many months it has an amount or a comment
        self.items = {kind: [(c.id, c.name) for c in categories if c.kind == kind] for kind in (INCOME, EXPENSE)}
        self.removed: list[int] = []  # ids of existing categories taken out of the lists
        self.boxes: dict[str, tk.Listbox] = {}
        self.v_name = {kind: tk.StringVar() for kind in (INCOME, EXPENSE)}

        b = self.body
        ttk.Label(b, style="Muted.TLabel", wraplength=UI.px(560), justify="left",
                  text=tr("Type a name and press Add. To change a name, select it, edit the text and press Rename."),
                  ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, UI.px(10)))
        for col, kind in enumerate((INCOME, EXPENSE)):
            panel = tk.Frame(b, bg=C["bg"])
            panel.grid(row=1, column=col, sticky="n", padx=(0, UI.px(24)) if col == 0 else 0)
            label(panel, tr("Income" if kind == INCOME else "Expenses"), font=UI.bold).pack(anchor="w", pady=(0, UI.px(4)))
            box = tk.Listbox(panel, height=9, width=24, exportselection=False, activestyle="none", bd=0, relief="flat",
                             highlightthickness=1, highlightbackground=C["border"], highlightcolor=C["accent"],
                             bg=C["chip"], fg=C["text"], selectbackground=C["chip_hover"],
                             selectforeground=C["text"], font=UI.body)
            box.pack(fill="x")
            box.bind("<<ListboxSelect>>", lambda e, k=kind: self._picked(k))
            self.boxes[kind] = box
            entry = ttk.Entry(panel, textvariable=self.v_name[kind], width=24)
            entry.pack(fill="x", pady=(UI.px(8), UI.px(6)))
            entry.bind("<Return>", lambda e, k=kind: (self._add(k), "break")[1])  # Enter adds, it does not save
            bar = tk.Frame(panel, bg=C["bg"])
            bar.pack(anchor="w")
            for text, fn in ((tr("Add"), self._add), (tr("Rename"), self._rename), (tr("Delete"), self._delete),
                             (tr("Up"), lambda k: self._move(k, -1)), (tr("Down"), lambda k: self._move(k, 1))):
                ttk.Button(bar, text=text, width=6, command=lambda fn=fn, k=kind: fn(k)).pack(
                    side="left", padx=(0, UI.px(4)))
            self._render(kind)
        self.add_buttons()
        self.initial_focus = next(iter(self.boxes.values()))

    def _render(self, kind: str, select: int | None = None) -> None:
        box = self.boxes[kind]
        box.delete(0, "end")
        for _, name in self.items[kind]:
            box.insert("end", name)
        if select is not None:
            box.selection_set(select)
            box.see(select)

    def _selected(self, kind: str) -> int | None:
        chosen = self.boxes[kind].curselection()
        return chosen[0] if chosen else None

    def _picked(self, kind: str) -> None:
        i = self._selected(kind)
        if i is not None:
            self.v_name[kind].set(self.items[kind][i][1])

    def _typed_name(self, kind: str, skip: int | None = None) -> str | None:
        """The typed name, if it is usable (not empty, not already in the list); else say why and give None."""
        name = self.v_name[kind].get().strip()
        if not name:
            messagebox.showerror(tr("Invalid input"), tr("Please enter a name"), parent=self)
        elif any(n.casefold() == name.casefold() for i, (_, n) in enumerate(self.items[kind]) if i != skip):
            messagebox.showerror(tr("Invalid input"), tr('"{name}" is already in the list', name=name), parent=self)
        else:
            return name
        return None

    def _add(self, kind: str) -> None:
        name = self._typed_name(kind)
        if name:
            self.items[kind].append((None, name))
            self.v_name[kind].set("")
            self._render(kind, len(self.items[kind]) - 1)

    def _rename(self, kind: str) -> None:
        i = self._selected(kind)
        if i is None:
            messagebox.showinfo(tr(APP_NAME), tr("Please select a category first."), parent=self)
            return
        name = self._typed_name(kind, skip=i)
        if name:
            self.items[kind][i] = (self.items[kind][i][0], name)
            self._render(kind, i)

    def _delete(self, kind: str) -> None:
        i = self._selected(kind)
        if i is None:
            messagebox.showinfo(tr(APP_NAME), tr("Please select a category first."), parent=self)
            return
        cid, _ = self.items[kind].pop(i)
        if cid is not None:
            self.removed.append(cid)
        self.v_name[kind].set("")
        self._render(kind, min(i, len(self.items[kind]) - 1) if self.items[kind] else None)

    def _move(self, kind: str, step: int) -> None:
        i = self._selected(kind)
        if i is not None and 0 <= i + step < len(self.items[kind]):
            items = self.items[kind]
            items[i], items[i + step] = items[i + step], items[i]
            self._render(kind, i + step)

    def build_result(self):
        lost = sum(self.used.get(cid, 0) for cid in self.removed)
        if lost and not messagebox.askyesno(
            tr("Delete Categories"),
            tr("Deleting these categories also deletes their {n} amounts and comments in the months already "
               "entered.\n\nContinue?", n=lost),
            parent=self, icon="warning",
        ):
            return None
        return self.items


class FinancePage(PageScroll):
    """Income and expenses outside the brokerage accounts: one row per month, like the spreadsheet it replaces.
    It takes the place of the whole stock view in the main window (Back or Esc returns)."""

    def __init__(self, app: "App", parent):
        super().__init__(parent)
        self.app = app
        self.db = app.db
        self.db.seed_finance_defaults(
            [tr("Salary income"), tr("Interest income"), tr("Other income")],
            [tr("Credit card payments"), tr("Other expenses")])
        self.categories: list[FinCategory] = self.db.list_finance_categories()
        self.months: list[FinMonth] = []
        self.rows: list[FinRow] = []  # every month with its totals
        self.shown: list[FinRow] = []  # the months of the chosen period
        self.v_period = tk.StringVar(value=tr(FINANCE_PERIODS["ALL"]))
        self.v_from = tk.StringVar()  # the first and last month of a custom range; blank = no limit on that side
        self.v_to = tk.StringVar()
        self.period_codes: dict[str, str] = {}  # the period choices as shown -> their codes (see refresh)
        self._loading = False

        page = self.inner
        top = tk.Frame(page, bg=C["bg"])
        top.pack(fill="x")
        PillButton(top, tr("Back"), app.close_finance, "ghost", icon="back", padx=12, pady=5).pack(side="left")
        PillButton(top, tr("+ Add month"), self.add_month, "primary").pack(side="right", padx=(UI.px(8), 0))
        PillButton(top, tr("Categories…"), self.edit_categories, "secondary").pack(side="right", padx=(UI.px(8), 0))
        label(page, tr("Finance"), font=UI.h1).pack(anchor="w", pady=(UI.px(6), 0))
        label(page, tr("Income and expenses outside your brokerage accounts, month by month"), color=C["muted"]).pack(
            anchor="w", pady=(0, UI.px(10)))

        self.stats = StatGrid(page, [("balance", tr("Balance")), ("income", tr("Income")),
                                     ("expenses", tr("Expenses")), ("net", tr("Net change"))])
        self.stats.pack(fill="x")
        separator(page).pack(fill="x", pady=(UI.px(4), UI.px(12)))

        bar = tk.Frame(page, bg=C["bg"])
        bar.pack(fill="x", pady=(0, UI.px(6)))
        label(bar, tr("Period"), font=UI.small, color=C["muted"]).pack(side="left")
        self.period_box = ttk.Combobox(bar, textvariable=self.v_period, state="readonly", width=14)
        self.period_box.pack(side="left", padx=(UI.px(6), UI.px(14)))
        label(bar, tr("Double-click a month to edit it · a • marks a cell with a comment"), font=UI.small,
              color=C["muted"]).pack(side="left")
        PillButton(bar, tr("Delete"), self.delete_selected, "secondary", font=UI.small_bold, padx=12, pady=4).pack(
            side="right")
        PillButton(bar, tr("Edit"), self.edit_selected, "secondary", font=UI.small_bold, padx=12, pady=4).pack(
            side="right", padx=UI.px(6))
        for v in (self.v_period, self.v_from, self.v_to):
            v.trace_add("write", lambda *a: None if self._loading else self.show())
        # the first and last month of a custom range, in a row of their own that is only shown for that choice
        self.range_bar = tk.Frame(page, bg=C["bg"])
        label(self.range_bar, tr("From"), font=UI.small, color=C["muted"]).pack(side="left")
        self.from_entry = ttk.Entry(self.range_bar, textvariable=self.v_from, width=10)
        self.from_entry.pack(side="left", padx=(UI.px(6), UI.px(14)))
        label(self.range_bar, tr("To"), font=UI.small, color=C["muted"]).pack(side="left")
        self.to_entry = ttk.Entry(self.range_bar, textvariable=self.v_to, width=10)
        self.to_entry.pack(side="left", padx=UI.px(6))
        label(self.range_bar, tr("e.g. 2026-01; leave one blank for no limit"), font=UI.small,
              color=C["muted"]).pack(side="left", padx=(UI.px(8), 0))

        frame, self.tree = make_tree(page, self._table_columns(), sortable=False)
        self.table_frame = frame
        frame.pack(fill="both", expand=True)
        self.tree.tag_configure("total", font=UI.bold)
        self.tree.bind("<Double-1>", self._on_double)
        self.tree.bind("<Return>", lambda e: self.edit_selected())
        self.tree.bind("<Delete>", lambda e: self.delete_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_detail())
        self.signature = self._signature()

        bottom = tk.Frame(page, bg=C["bg"])
        bottom.pack(fill="x", pady=(UI.px(10), 0))
        self.totals = tk.Frame(bottom, bg=C["chip"])  # what every category came to over the chosen period
        self.totals.pack(side="left", fill="y")
        side = tk.Frame(bottom, bg=C["chip"])
        side.pack(side="left", fill="both", expand=True, padx=(UI.px(10), 0))
        self.detail = tk.Text(side, height=8, wrap="word", font=UI.body, bg=C["chip"], fg=C["text"], relief="flat",
                              bd=0, highlightthickness=0, padx=UI.px(12), pady=UI.px(8), cursor="arrow",
                              state="disabled")
        bar_y = ttk.Scrollbar(side, orient="vertical", command=self.detail.yview, style="Slim.Vertical.TScrollbar")

        def on_scroll(first, last):  # the scroll bar only shows when the text does not fit
            bar_y.set(first, last)
            if float(first) <= 0 and float(last) >= 1:
                bar_y.pack_forget()
            elif not bar_y.winfo_ismapped():
                bar_y.pack(side="right", fill="y")

        self.detail.configure(yscrollcommand=on_scroll)
        self.detail.pack(side="left", fill="both", expand=True)
        self.detail.tag_configure("head", font=UI.bold)
        self.detail.tag_configure("muted", foreground=C["muted"])
        self.detail.tag_configure("note", lmargin1=UI.px(18), lmargin2=UI.px(18))
        self.refresh()
        self.bind_wheel()

    # ---- the table
    def _signature(self) -> tuple:
        return tuple((c.id, c.kind, c.name) for c in self.categories)

    def _table_columns(self) -> list[tuple[str, str, int, str]]:
        def width(name: str) -> int:  # room for the name (a Chinese character is twice as wide), at least an amount's
            return max(100, 24 + 8 * sum(2 if ord(ch) > 0x2E7F else 1 for ch in name))

        cols = [("month", tr("Month"), 90, "w"), ("opening", tr("Opening"), 110, "e")]
        cols += [(f"c{c.id}", c.name, width(c.name), "e") for c in self.categories if c.kind == INCOME]
        cols.append(("income", tr("Total income"), 115, "e"))
        cols += [(f"c{c.id}", c.name, width(c.name), "e") for c in self.categories if c.kind == EXPENSE]
        cols += [("expenses", tr("Total expenses"), 120, "e"), ("ending", tr("Ending balance"), 125, "e")]
        return cols

    def _values(self, month: str, opening, income, expenses, ending, cell) -> list[str]:
        """One row of the table; `cell(category)` gives the text of a category's cell."""
        return [month, fmt_money(opening),
                *(cell(c) for c in self.categories if c.kind == INCOME), fmt_money(income),
                *(cell(c) for c in self.categories if c.kind == EXPENSE), fmt_money(expenses), fmt_money(ending)]

    def period_choices(self) -> dict[str, str]:
        """The choices of the Period box as shown -> their codes: the ready-made periods, each year that has
        months (newest first), and the custom range."""
        choices = {tr(text): code for code, text in FINANCE_PERIODS.items()}
        choices.update({y: y for y in sorted({r.month.month[:4] for r in self.rows}, reverse=True)})
        choices[tr(CUSTOM_PERIOD)] = "CUSTOM"
        return choices

    def month_bounds(self) -> tuple[str | None, str | None]:
        """First and last month the page is narrowed to (None = no limit), from the Period box and, for a custom
        range, the two month boxes -- which turn red while their text is not a usable month."""
        code = self.period_codes.get(self.v_period.get(), "ALL")
        if code != "CUSTOM":
            return month_range(code, today()[:7])
        bounds, bad = [], []
        for var in (self.v_from, self.v_to):
            text = var.get().strip()
            try:
                bounds.append(month_of(text) if text else None)
                bad.append(False)
            except ValueError:
                bounds.append(None)
                bad.append(True)
        if bounds[0] and bounds[1] and bounds[0] > bounds[1]:  # "from" after "to" can never match anything
            bad = [True, True]
        for entry, flag in zip((self.from_entry, self.to_entry), bad):
            entry.state(["invalid"] if flag else ["!invalid"])
        return bounds[0], bounds[1]

    def refresh(self, select: str | None = None) -> None:
        """Read everything from the database again."""
        self.categories = self.db.list_finance_categories()
        self.months = self.db.list_finance_months()
        self.rows = finance_rows(self.months, self.categories)
        self._loading = True  # the Period box is rebuilt below; showing is done once, at the end
        self.period_codes = self.period_choices()
        self.period_box.configure(values=list(self.period_codes))
        if self.v_period.get() not in self.period_codes:  # a year that no longer has any month
            self.v_period.set(tr(FINANCE_PERIODS["ALL"]))
        self._loading = False
        self.show(select)

    def show(self, select: str | None = None) -> None:
        """Fill the table, the numbers above it and the details below it for the chosen period."""
        tree = self.tree
        keep = select or tree.focus() or None
        custom = self.period_codes.get(self.v_period.get()) == "CUSTOM"
        if custom and not self.range_bar.winfo_ismapped():
            self.range_bar.pack(fill="x", pady=(0, UI.px(6)), before=self.table_frame)
        elif not custom:
            self.range_bar.pack_forget()
        first, last_month = self.month_bounds()
        self.shown = period_months(self.rows, first, last_month)
        if self._signature() != self.signature:  # categories were added, renamed, moved or deleted
            configure_columns(tree, self._table_columns(), sortable=False)
            self.signature = self._signature()
        tree.delete(*tree.get_children())
        tree.hover_row = ""
        for r in self.shown:
            tree.insert("", "end", iid=r.month.month, values=self._values(
                r.month.month, r.opening, r.income, r.expenses, r.ending, lambda c: cell_text(r.month.entries.get(c.id))))
        total = summarize(self.shown)
        if self.shown:
            tree.insert("", "end", iid="total", tags=["total"], values=self._values(
                tr("Total"), total.opening, total.income, total.expenses, total.ending,
                lambda c: fmt_money(total.by_category[c.id]) if total.by_category.get(c.id) else "-"))
        if keep and tree.exists(keep):
            tree.selection_set(keep)
            tree.focus(keep)
        last = self.shown[-1].month.month if self.shown else None
        if keep and tree.exists(keep):
            tree.see(keep)
        elif last:  # the newest month is the one that matters
            tree.see(last)

        n = total.months
        month_count = plural(str(n), "{n} month", "{n} months")
        self.stats.set("balance", usd(total.ending) if n else "-", tr("as of {month}", month=last) if n else "")
        self.stats.set("income", usd(total.income), tr("{avg} / month", avg=usd(total.income / n)) if n else "")
        self.stats.set("expenses", usd(total.expenses), tr("{avg} / month", avg=usd(total.expenses / n)) if n else "")
        self.stats.set("net", usd(total.net, sign=True) if n else "-", month_count if n else "", color_for(total.net))
        self.show_totals(total)
        self.show_detail()

    def show_totals(self, total: FinSummary) -> None:
        """Next to the details: what each category came to over the chosen months, income on the left and expenses
        on the right -- the figures to check against a tax return."""
        panel = self.totals
        for w in panel.winfo_children():
            w.destroy()
        pad = UI.px(12)
        bg = C["chip"]
        label(panel, tr("Totals for the period"), font=UI.bold, bg=bg).grid(
            row=0, column=0, columnspan=5, sticky="w", padx=pad, pady=(UI.px(8), 0))
        if not self.shown:
            label(panel, tr("No months in this period."), color=C["muted"], bg=bg).grid(
                row=1, column=0, columnspan=5, sticky="w", padx=pad, pady=(0, UI.px(8)))
            return
        span = tr("{first} to {last} · {months}", first=self.shown[0].month.month, last=self.shown[-1].month.month,
                  months=plural(str(total.months), "{n} month", "{n} months"))
        label(panel, span, font=UI.small, color=C["muted"], bg=bg).grid(
            row=1, column=0, columnspan=5, sticky="w", padx=pad, pady=(0, UI.px(6)))
        groups = ((INCOME, "Income", total.income, "Total income", 0), (EXPENSE, "Expenses", total.expenses,
                                                                       "Total expenses", 3))
        longest = max(sum(1 for c in self.categories if c.kind == kind) for kind in (INCOME, EXPENSE))
        for kind, title, grand, grand_title, col in groups:
            label(panel, tr(title), font=UI.small_bold, color=C["muted"], bg=bg).grid(
                row=2, column=col, columnspan=2, sticky="w", padx=pad)
            for i, c in enumerate(c for c in self.categories if c.kind == kind):
                amount = total.by_category.get(c.id)
                label(panel, c.name, bg=bg).grid(row=3 + i, column=col, sticky="w", padx=(pad, UI.px(16)))
                label(panel, fmt_money(amount) if amount else "-", color=None if amount else C["muted"], bg=bg).grid(
                    row=3 + i, column=col + 1, sticky="e", padx=(0, pad if col else 0))
            tk.Frame(panel, height=1, bg=C["border"]).grid(row=3 + longest, column=col, columnspan=2, sticky="we",
                                                           padx=pad, pady=UI.px(4))
            label(panel, tr(grand_title), font=UI.bold, bg=bg).grid(row=4 + longest, column=col, sticky="w",
                                                                    padx=(pad, UI.px(16)), pady=(0, UI.px(8)))
            label(panel, fmt_money(grand), font=UI.bold, bg=bg).grid(row=4 + longest, column=col + 1, sticky="e",
                                                                     padx=(0, pad if col else 0), pady=(0, UI.px(8)))
        panel.columnconfigure(2, minsize=UI.px(24))

    def scroll_to_latest(self) -> None:
        """Show the newest month (called once the page has its size, so the table knows how much fits)."""
        if self.shown:
            self.tree.see(self.shown[-1].month.month)

    def show_detail(self) -> None:
        """Below the table: the sums and comments of the selected month."""
        row = next((r for r in self.shown if r.month.month == self.tree.focus()), None)
        box = self.detail
        box.configure(state="normal")
        box.delete("1.0", "end")
        if row is None:
            hint = tr("Select a month to see the sums and comments in it.") if self.rows else \
                tr("No months yet. Click + Add month to enter the first one.")
            box.insert("end", hint, "muted")
        else:
            box.insert("end", row.month.month, "head")
            box.insert("end", "   " + tr("Opening {opening} · Income {income} · Expenses {expenses} · Ending {ending}",
                                         opening=fmt_money(row.opening), income=fmt_money(row.income),
                                         expenses=fmt_money(row.expenses), ending=fmt_money(row.ending)), "muted")
            for c in self.categories:
                e = row.month.entries.get(c.id)
                if e is None or not (e.comment or e.expr):
                    continue
                box.insert("end", "\n" + c.name, "head")
                box.insert("end", f"   {fmt_money(e.amount)}" + (f" = {e.expr}" if e.expr else ""), "muted")
                if e.comment:
                    box.insert("end", "\n" + e.comment, "note")
        box.configure(state="disabled")

    # ---- editing
    def carried(self, month: str):
        """The balance a month would start from: the ending balance of the latest month before it."""
        return next((r.ending for r in reversed(self.rows) if r.month.month < month), ZERO)

    def _on_double(self, event) -> None:
        tree = self.tree
        if tree.identify_region(event.x, event.y) != "cell":
            return
        month = tree.identify_row(event.y)
        if not month or month == "total":
            return
        key = tree["columns"][int(tree.identify_column(event.x)[1:]) - 1]  # "c12" = category 12
        self.edit_month(month, int(key[1:]) if key[1:].isdigit() and key[0] == "c" else None)

    def edit_selected(self) -> None:
        month = self.tree.focus()
        if month and month != "total":
            self.edit_month(month)
        else:
            messagebox.showinfo(tr(APP_NAME), tr("Please select a month in the table first."))

    def add_month(self) -> None:
        if not self.categories:
            messagebox.showinfo(tr(APP_NAME), tr("Add some categories first (Categories…)."))
            return
        self.edit_month(None)

    def edit_month(self, month: str | None, focus: int | None = None) -> None:
        """Edit a month in the table, or (month=None) add the one after the latest."""
        initial = next((m for m in self.months if m.month == month), None)
        if month is None:
            month = add_month(self.rows[-1].month.month) if self.rows else today()[:7]
        title = tr("Edit Month" if initial else "Add Month")
        result = FinanceMonthDialog(self.app.root, title, categories=self.categories, initial=initial, month=month,
                                    existing={m.month for m in self.months}, carried=self.carried, focus=focus).show()
        if result:
            self.db.save_finance_month(result)
            self.refresh(select=result.month)

    def delete_selected(self) -> None:
        month = self.tree.focus()
        if not month or month == "total":
            messagebox.showinfo(tr(APP_NAME), tr("Please select a month in the table first."))
            return
        if messagebox.askyesno(tr("Delete Month"), tr("Delete {month} with all its amounts and comments?", month=month)):
            self.db.delete_finance_month(month)
            self.refresh()

    def edit_categories(self) -> None:
        result = FinanceCategoriesDialog(self.app.root, self.categories, self.db.finance_entry_counts()).show()
        if result:
            for kind, items in result.items():
                self.db.set_finance_categories(kind, items)
            self.refresh()


# ======================================================================
# Sidebar row: symbol, shares, today's sparkline and a price pill
# ======================================================================
class StockRow(tk.Frame):
    def __init__(self, parent, symbol: str, on_click):
        super().__init__(parent, bg=C["bg"], cursor="hand2")
        self.symbol = symbol
        self.sym_label = label(self, symbol, font=UI.bold)
        self.sym_label.grid(row=0, column=0, sticky="sw")
        self.sub = label(self, "", font=UI.small, color=C["muted"])
        self.sub.grid(row=1, column=0, sticky="nw")
        self.spark = LineChart(self, height=UI.px(34), width=UI.px(70), interactive=False, pad=2, line_width=1.5)
        self.spark.grid(row=0, column=1, rowspan=2, padx=UI.px(10))
        self.pill = tk.Canvas(self, width=UI.px(84), height=UI.px(30), bg=C["bg"], highlightthickness=0, bd=0)
        self.pill.grid(row=0, column=2, rowspan=2)
        self.columnconfigure(0, weight=1)
        for w in (self, self.sym_label, self.sub, self.spark, self.pill):
            w.bind("<Button-1>", lambda e: on_click(symbol))
            w.bind("<Enter>", lambda e: self._hover(True))
            w.bind("<Leave>", lambda e: self._hover(False))

    def _hover(self, on):
        bg = C["hover"] if on else C["bg"]
        for w in (self, self.sym_label, self.sub, self.spark, self.pill):
            w.configure(bg=bg)

    def show(self, pos, quote: Quote | None, price: Decimal | None):
        self.sub.configure(text=holding_text(pos.symbol, pos.quantity))
        change = quote.change if quote else None
        color = color_for(change) if change else C["muted"]
        if quote and len(quote.points) >= 2:
            self.spark.set_data([c for _, c in quote.points] + [float(quote.price)], color=color,
                                baseline=float(quote.prev_close) if quote.prev_close else None, slots=DAY_SLOTS)
        else:
            self.spark.set_data([])
        c = self.pill
        c.delete("all")
        w, h = int(c["width"]), int(c["height"])
        fill = color if change else C["chip"]
        round_rect(c, 1, 1, w - 1, h - 1, UI.px(6), fill=fill, outline=fill)
        c.create_text(w / 2, h / 2, text=usd(price) if price is not None else "-", font=UI.small_bold,
                      fill=C["on_accent"] if change else C["text"])


# ======================================================================
# Symbol type-ahead: feeds the SymbolEntry boxes in the dialogs
# ======================================================================
class SymbolSearch:
    """Called as the user types a symbol. Shows matching symbols from the current account right
    away (works offline), then adds Yahoo's search results once typing pauses -- only while live
    prices are on, so turning them off keeps everything you type on this computer."""

    DELAY = 250  # ms of no typing before searching online
    LIMIT = 8

    def __init__(self, app: "App"):
        self.app = app
        self.cache: dict[str, list[Suggestion]] = {}  # query -> results, for this session
        self.names: dict[str, str] = {}  # symbol -> company name learned from searches
        self._job = None

    def __call__(self, query: str, show):
        if self._job:
            self.app.root.after_cancel(self._job)
            self._job = None
        q = query.strip().upper()
        if q in self.cache:
            show(query, self._items(q, self.cache[q]))
            return
        show(query, self._items(q, []))
        if q and self.app.v_live.get():
            self._job = self.app.root.after(self.DELAY, lambda: self._search(query, q, show))

    def _search(self, query, q, show):
        self._job = None
        self.app.run_bg(search_symbols, (q, self.LIMIT), lambda res: self._got(query, q, res, show))

    def _got(self, query, q, res, show):
        if isinstance(res, Exception):
            return  # offline: the local matches already shown are all we have
        self.cache[q] = res
        for s in res:
            self.names.setdefault(s.symbol, s.name)
        show(query, self._items(q, res))

    def _name(self, sym: str) -> str:
        q = self.app.quotes.get(sym)
        return (q.name if q else "") or self.names.get(sym, "")

    def _items(self, q: str, online: list[Suggestion]) -> list[tuple[str, str, str]]:
        """Symbols from this account first (with shares held), then online results not already listed."""
        positions = self.app.result.positions
        local = match_local(q, {sym: self._name(sym) for sym in positions}, self.LIMIT)
        local.sort(key=lambda sym: (sym != q, not positions[sym].is_open))  # exact match, then what is still held
        items = []
        for sym in local:
            pos = positions[sym]
            items.append((sym, self._name(sym), holding_text(sym, pos.quantity) if pos.is_open else tr("Closed")))
        for s in online:
            if s.symbol not in local:
                items.append((s.symbol, s.name, s.exchange or s.kind))
        return items[: self.LIMIT]


# ======================================================================
# Main window
# ======================================================================
class App:
    HOLD_COLUMNS = [
        ("symbol", "Symbol", 75, "w"), ("qty", "Shares", 80, "e"), ("avg", "Avg Cost", 85, "e"),
        ("cost", "Cost Basis", 100, "e"), ("price", "Price", 80, "e"), ("day", "Day Change", 135, "e"),
        ("value", "Market Value", 105, "e"),
        ("unreal", "Unrealized P/L", 110, "e"), ("pct", "P/L %", 70, "e"),
        ("realized", "Realized P/L", 100, "e"), ("div", "Dividends", 85, "e"),
    ]
    ACCOUNT_COLUMNS = [
        ("name", "Account", 150, "w"), ("cash", "Cash", 105, "e"), ("value", "Market Value", 110, "e"),
        ("total", "Total", 110, "e"), ("share", "% of Total", 85, "e"), ("unreal", "Unrealized P/L", 120, "e"),
        ("realized", "Realized P/L", 105, "e"), ("net", "Net Deposits", 110, "e"),
    ]
    TXN_COLUMNS = [
        ("date", "Date", 95, "w"), ("type", "Type", 90, "w"), ("symbol", "Symbol", 70, "w"),
        ("qty", "Quantity", 80, "e"), ("price", "Price", 80, "e"), ("fee", "Fee", 65, "e"),
        ("cash", "Cash Change", 105, "e"), ("balance", "Cash Balance", 110, "e"), ("note", "Note", 160, "w"),
    ]

    def __init__(self, root: tk.Tk, db: Storage, folder: Path):
        self.root = root
        self.db = db
        self.folder = folder
        self.accounts: list[sqlite3.Row] = []
        self.account_id: int | None = None
        self.txns: list[Txn] = []
        self.result = LedgerResult()
        self.account_results: dict[int, LedgerResult] = {}  # all-accounts view: each account's own result
        self.prices: dict[str, Decimal] = {}
        self.price_info: dict[str, tuple[Decimal, str]] = {}
        self.quotes: dict[str, Quote] = {}  # live quotes (with today's intraday prices) fetched this session
        self.history: dict[tuple, tuple[float, dict[str, Quote] | None]] = {}  # chart data per range
        self._bg_queue: queue.Queue = queue.Queue()  # results from background threads
        self._fetching = False
        self._live_job = None
        self.detail: SymbolDetail | None = None  # the open stock page, if any
        self.finance: FinancePage | None = None  # the open finance page, if any (it replaces the whole stock view)
        self._tabs_combined = False
        self.symbol_search = SymbolSearch(self)
        self.stock_rows: dict[str, StockRow] = {}
        self.last_date: str | None = None
        self.last_type = "BUY"
        self.range = "1D"

        self.v_show_closed = tk.BooleanVar(value=False)
        self.v_filter_symbol = tk.StringVar(value=tr(ALL))
        self.v_filter_type = tk.StringVar(value=tr(ALL))
        self.v_filter_period = tk.StringVar(value=tr(PERIODS["ALL"]))
        self.v_from = tk.StringVar()  # the dates of a custom range; blank = no limit on that side
        self.v_to = tk.StringVar()
        self.period_codes: dict[str, str] = {}  # the period choices as shown -> their codes (see refresh)
        self.v_live = tk.BooleanVar(value=db.get_setting("live_prices", "1") == "1")
        self.v_dark = tk.BooleanVar(value=db.get_setting("theme", "dark") == "dark")
        self.v_finance = tk.BooleanVar(value=db.finance_enabled())  # the optional Finance page (off until turned on)
        self.v_text_size = tk.StringVar(value=text_size(db))
        self.v_language = tk.StringVar(value=language())
        for v in (self.v_filter_symbol, self.v_filter_type, self.v_filter_period, self.v_from, self.v_to):
            v.trace_add("write", lambda *a: self.refresh_txn_list())

        root.title(tr(APP_NAME))
        root.geometry(UI.fit(root, 1440, 920))
        root.minsize(min(UI.px(1000), root.winfo_screenwidth()), min(UI.px(640), root.winfo_screenheight()))
        self._build_ui()
        root.bind_all("<Control-n>", lambda e: self.add_txn())
        root.bind("<Escape>", lambda e: self._on_escape())
        root.bind_all("<F5>", lambda e: self.refresh())
        root.protocol("WM_DELETE_WINDOW", self.quit)

        last = self.db.get_setting("last_account")
        self.load_accounts(select_id=ALL_ACCOUNTS if last == "all" else int(last) if last and last.isdigit() else None)
        if not self.accounts:
            root.after(300, self.first_run)
        self._poll_bg()
        if self.v_live.get():
            self._live_tick()

    def _on_escape(self):
        if self.root.grab_current() is not None:  # a dialog is open: it takes the key itself
            return
        if self.finance:
            self.close_finance()
        else:
            self.close_detail()

    # ------------------------------------------------------------ UI construction
    def _build_ui(self):
        self._build_topbar()
        self.status = label(self.root, "", font=UI.small, color=C["muted"], anchor="w")
        self.status.pack(side="bottom", fill="x", padx=UI.px(28), pady=(0, UI.px(8)))
        body = self.body = tk.Frame(self.root, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=UI.px(28), pady=(UI.px(18), UI.px(8)))
        self._build_sidebar(body)
        self.main = tk.Frame(body, bg=C["bg"])  # holds the overview, or a stock's page in its place
        self.main.pack(side="left", fill="both", expand=True)
        self.overview = PageScroll(self.main)
        self.overview.pack(fill="both", expand=True)
        main = self.overview.inner
        self.hero = Hero(main, tr("Total assets"), self._on_range)
        self.hero.pack(fill="x")
        self.hero.tabs.select(self.range)
        separator(main).pack(fill="x", pady=(UI.px(10), UI.px(14)))
        self.stats = StatGrid(main, [
            ("cash", tr("Cash")), ("value", tr("Market value")), ("cost", tr("Cost basis")),
            ("unreal", tr("Unrealized P/L")), ("realized", tr("Realized P/L")), ("income", tr("Dividends + interest")),
            ("net", tr("Net deposits")), ("fees", tr("Fees & commissions")),
        ])
        self.stats.pack(fill="x")
        # with the Finance page on, the all-accounts view also adds up the finance cash balance (see refresh_net_summary)
        self.net_summary = self._build_net_summary(main) if self.v_finance.get() else None
        self._build_tabs(main)
        self.overview.bind_wheel()

    def _build_net_summary(self, main) -> tuple[tk.Frame, "StatGrid"]:
        """The block above the chart of the all-accounts view that shows the net worth including the finance cash
        balance, next to its parts. It is packed (above the chart) only while there is something to show."""
        frame = tk.Frame(main, bg=C["bg"])
        grid = StatGrid(frame, [("total", tr("Net worth (all accounts)")), ("stock", tr("Stock accounts net worth")),
                                ("cash", tr("Stock accounts cash")), ("finance", tr("Finance cash balance"))])
        grid.pack(fill="x")
        grid.cells["total"][0].configure(font=UI.h1)  # the sum is the headline; the three tiles after it are its parts
        separator(frame).pack(fill="x", pady=(0, UI.px(14)))
        return frame, grid

    def _build_topbar(self):
        bar = tk.Frame(self.root, bg=C["bg"])
        bar.pack(fill="x", padx=UI.px(28), pady=(UI.px(14), UI.px(10)))
        logo(bar, tr(APP_NAME)).pack(side="left")
        self.stock_left = tk.Frame(bar, bg=C["bg"])  # the stock-only controls, hidden while the finance page is open
        self.stock_left.pack(side="left")
        self.account_btn = PillButton(self.stock_left, tr("No account"), self._account_menu, "secondary", padx=14, pady=6,
                                      caret=True)
        self.account_btn.pack(side="left", padx=(UI.px(20), 0))
        if self.v_finance.get():
            PillButton(self.stock_left, tr("Finance"), self.open_finance, "secondary", padx=14, pady=6).pack(
                side="left", padx=(UI.px(8), 0))

        self.more_btn = PillButton(bar, "", self._more_menu, "ghost", padx=10, pady=6, icon="more")
        self.more_btn.pack(side="right")
        self.stock_right = tk.Frame(bar, bg=C["bg"])
        self.stock_right.pack(side="right")
        PillButton(self.stock_right, tr("+ Add transaction"), self.add_txn, "primary", padx=16, pady=6).pack(
            side="right", padx=(UI.px(8), UI.px(4)))
        PillButton(self.stock_right, tr("Update prices"), self.update_prices, "secondary", padx=14, pady=6).pack(
            side="right")
        live = tk.Frame(self.stock_right, bg=C["bg"])
        live.pack(side="right", padx=UI.px(16))
        self.live_status = label(live, "", font=UI.small, color=C["muted"])
        self.live_status.pack(side="left", padx=(0, UI.px(10)))
        label(live, tr("Live"), font=UI.small_bold, color=C["muted"]).pack(side="left", padx=(0, UI.px(6)))
        Toggle(live, self.v_live, self.toggle_live).pack(side="left")
        separator(self.root).pack(fill="x")

    def _build_sidebar(self, body):
        side = tk.Frame(body, bg=C["bg"], highlightthickness=1, highlightbackground=C["border"],
                        width=UI.px(310))
        side.pack(side="right", fill="y", padx=(UI.px(28), 0))
        side.pack_propagate(False)
        head = tk.Frame(side, bg=C["bg"])
        head.pack(fill="x", padx=UI.px(16), pady=(UI.px(14), UI.px(8)))
        label(head, tr("Stocks"), font=UI.h2).pack(side="left")
        self.side_count = label(head, "", font=UI.small, color=C["muted"])
        self.side_count.pack(side="right")
        separator(side).pack(fill="x")
        self.side_list = ScrollFrame(side)
        self.side_list.pack(fill="both", expand=True, padx=UI.px(6), pady=UI.px(6))
        self.side_empty = label(self.side_list.inner, tr("No holdings yet"), color=C["muted"])
        self.stock_rows = {}

    def _build_tabs(self, main):
        separator(main).pack(fill="x", pady=(0, UI.px(12)))
        head = tk.Frame(main, bg=C["bg"])
        head.pack(fill="x")
        self.pages: dict[str, tk.Frame] = {}
        self.tabs_head = head
        self.page_tabs: TabBar | None = None
        tools = tk.Frame(head, bg=C["bg"])
        tools.pack(side="right", fill="x")
        stack = tk.Frame(main, bg=C["bg"])
        stack.pack(fill="both", expand=True, pady=(UI.px(8), 0))

        # --- Accounts (all-accounts view only) ---
        page = tk.Frame(stack, bg=C["bg"])
        self.pages["Accounts"] = page
        bar = tk.Frame(page, bg=C["bg"])
        bar.pack(fill="x", pady=(0, UI.px(6)))
        label(bar, tr("Double-click an account to open it"), font=UI.small, color=C["muted"]).pack(side="left")
        frame, self.acct_tree = make_tree(page, columns(self.ACCOUNT_COLUMNS))
        frame.pack(fill="both", expand=True)
        self.acct_tree.bind("<Double-1>", self._on_account_double)

        # --- Holdings ---
        page = tk.Frame(stack, bg=C["bg"])
        self.pages["Holdings"] = page
        bar = tk.Frame(page, bg=C["bg"])
        bar.pack(fill="x", pady=(0, UI.px(6)))
        label(bar, tr("Double-click a stock to open its page"), font=UI.small, color=C["muted"]).pack(side="left")
        PillButton(bar, tr("View details"), self.open_selected_symbol, "secondary", font=UI.small_bold,
                   padx=12, pady=4).pack(side="right")
        Toggle(bar, self.v_show_closed, self.refresh_holdings).pack(side="right", padx=(UI.px(6), UI.px(16)))
        label(bar, tr("Show closed"), font=UI.small, color=C["muted"]).pack(side="right")
        frame, self.hold_tree = make_tree(page, columns(self.HOLD_COLUMNS))
        frame.pack(fill="both", expand=True)
        self.hold_tree.bind("<Double-1>", self._on_hold_double)

        # --- Transactions ---
        page = tk.Frame(stack, bg=C["bg"])
        self.pages["Transactions"] = page
        bar = tk.Frame(page, bg=C["bg"])
        bar.pack(fill="x", pady=(0, UI.px(6)))
        label(bar, tr("Symbol"), font=UI.small, color=C["muted"]).pack(side="left")
        self.filter_symbol_box = ttk.Combobox(bar, textvariable=self.v_filter_symbol, state="readonly", width=10)
        self.filter_symbol_box.pack(side="left", padx=(UI.px(6), UI.px(14)))
        label(bar, tr("Type"), font=UI.small, color=C["muted"]).pack(side="left")
        self.filter_type_box = ttk.Combobox(bar, textvariable=self.v_filter_type, state="readonly", width=12,
                                            values=[tr(ALL), *(tr(text) for text in TXN_TYPES.values())])
        self.filter_type_box.pack(side="left", padx=(UI.px(6), UI.px(14)))
        label(bar, tr("Period"), font=UI.small, color=C["muted"]).pack(side="left")
        self.filter_period_box = ttk.Combobox(bar, textvariable=self.v_filter_period, state="readonly", width=14)
        self.filter_period_box.pack(side="left", padx=UI.px(6))
        # only shown while a filter is on; it resets the filters and deletes nothing
        self.reset_btn = PillButton(bar, tr("Reset filters"), self._clear_filters, "ghost", font=UI.small_bold,
                                    padx=10, pady=4)
        PillButton(bar, tr("Delete"), self.delete_selected_txn, "secondary", font=UI.small_bold, padx=12, pady=4).pack(
            side="right")
        PillButton(bar, tr("Edit"), self.edit_selected_txn, "secondary", font=UI.small_bold, padx=12, pady=4).pack(
            side="right", padx=UI.px(6))
        self.txn_count = label(bar, "", font=UI.small, color=C["muted"])
        self.txn_count.pack(side="right", padx=UI.px(12))
        # the two dates of a custom range, in a row of their own that is only shown for that choice
        self.range_bar = tk.Frame(page, bg=C["bg"])
        label(self.range_bar, tr("From"), font=UI.small, color=C["muted"]).pack(side="left")
        self.from_entry = ttk.Entry(self.range_bar, textvariable=self.v_from, width=12)
        self.from_entry.pack(side="left", padx=(UI.px(6), UI.px(14)))
        label(self.range_bar, tr("To"), font=UI.small, color=C["muted"]).pack(side="left")
        self.to_entry = ttk.Entry(self.range_bar, textvariable=self.v_to, width=12)
        self.to_entry.pack(side="left", padx=UI.px(6))
        label(self.range_bar, tr("e.g. 2026-09-30; leave one blank for no limit"), font=UI.small,
              color=C["muted"]).pack(side="left", padx=(UI.px(8), 0))
        frame, self.txn_tree = make_tree(page, columns(self.TXN_COLUMNS))
        self.txn_frame = frame
        frame.pack(fill="both", expand=True)
        self.txn_tree.bind("<Double-1>", self._on_txn_double)
        self.txn_tree.bind("<Return>", lambda e: self.edit_selected_txn())
        self.txn_tree.bind("<Delete>", lambda e: self.delete_selected_txn())
        self._make_page_tabs()

    def _make_page_tabs(self):
        """The tabs under the numbers: Accounts + Holdings for the all-accounts view, else Holdings + Transactions."""
        if self.page_tabs:
            self.page_tabs.destroy()
        items = ["Accounts", "Holdings"] if self.combined else ["Holdings", "Transactions"]
        self.page_tabs = TabBar(self.tabs_head, items, self._show_page, font=UI.h2, gap=26,
                                labels={"Accounts": tr("Accounts"), "Holdings": tr("Holdings"),
                                        "Transactions": tr("Transactions")})
        self.page_tabs.pack(side="left")
        self._tabs_combined = self.combined
        self._show_page(items[0])

    def _show_page(self, name):
        for key, page in self.pages.items():
            if key == name:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()
        self.overview.refit()

    def _popup(self, menu: tk.Menu, widget: tk.Widget):
        menu.tk_popup(widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height() + UI.px(4))

    def _account_menu(self):
        m = style_menu(tk.Menu(self.root, tearoff=False))
        current = tk.IntVar(value=self.account_id or 0)
        if len(self.accounts) >= 2:
            m.add_radiobutton(label=tr("All accounts"), variable=current, value=ALL_ACCOUNTS,
                              command=lambda: self._select_account(ALL_ACCOUNTS))
            m.add_separator()
        for a in self.accounts:
            m.add_radiobutton(label=a["name"], variable=current, value=a["id"],
                              command=lambda i=a["id"]: self._select_account(i))
        if self.accounts:
            m.add_separator()
        m.add_command(label=tr("New account…"), command=self.new_account)
        single = "disabled" if self.combined else "normal"  # these act on one account
        m.add_command(label=tr("Edit account…"), command=self.edit_account, state=single)
        m.add_command(label=tr("Delete account…"), command=self.delete_account, state=single)
        self._popup(m, self.account_btn)

    def _more_menu(self):
        m = style_menu(tk.Menu(self.root, tearoff=False))
        stock = "disabled" if self.finance else "normal"  # these act on the stock accounts
        m.add_command(label=tr("Add transaction"), accelerator="Ctrl+N", command=self.add_txn, state=stock)
        m.add_command(label=tr("Update prices…"), command=self.update_prices, state=stock)
        m.add_separator()
        m.add_command(label=tr("Export current account to CSV…"), command=self.export_csv,
                      state="disabled" if self.combined or self.finance else "normal")
        m.add_command(label=tr("Back up database…"), command=self.backup)
        m.add_command(label=tr("Open data folder"), command=lambda: open_folder(self.folder))
        m.add_separator()
        m.add_checkbutton(label=tr("Dark mode"), variable=self.v_dark, command=self.toggle_theme)
        sizes = style_menu(tk.Menu(m, tearoff=False))
        for name in TEXT_SIZES:
            sizes.add_radiobutton(label=tr(name), value=name, variable=self.v_text_size, command=self.change_text_size)
        m.add_cascade(label=tr("Text size"), menu=sizes)
        langs = style_menu(tk.Menu(m, tearoff=False))
        for code, name in LANGUAGES.items():
            langs.add_radiobutton(label=name, value=code, variable=self.v_language, command=self.change_language)
        m.add_cascade(label="Language / 语言", menu=langs)  # in both languages, so it can always be found
        m.add_checkbutton(label=tr("Finance page"), variable=self.v_finance, command=self.toggle_finance)
        m.add_separator()
        m.add_command(label=tr("User guide"), command=self.show_help)
        m.add_command(label=tr("About"), command=self.show_about)
        m.add_separator()
        m.add_command(label=tr("Exit"), command=self.quit)
        self._popup(m, self.more_btn)

    def toggle_theme(self):
        self.db.set_setting("theme", "dark" if self.v_dark.get() else "light")
        self.rebuild()

    def toggle_finance(self):
        """Turn the optional Finance page on or off: its button in the top bar, and (the first time) its tables in
        the database. Turning it off only hides it; what was entered is kept."""
        self.db.set_finance_enabled(self.v_finance.get())
        self.rebuild()

    def change_text_size(self):
        self.db.set_setting("text_size", self.v_text_size.get())
        self.rebuild()

    def change_language(self):
        self.db.set_setting("language", self.v_language.get())
        set_language(self.v_language.get())
        self.v_filter_symbol.set(tr(ALL))  # the filters hold the old language's "All"
        self.v_filter_type.set(tr(ALL))
        self.v_filter_period.set(tr(PERIODS["ALL"]))
        self.rebuild()

    def rebuild(self):
        """Apply a new theme, text size or language: rebuild every widget with the new colors, fonts and text."""
        open_sym = self.detail.symbol if self.detail else None  # stay on the same stock page afterwards
        was_finance = self.finance is not None and self.v_finance.get()  # ... or on the finance page (if still on)
        self.detail = self.finance = None
        for child in self.root.winfo_children():
            child.destroy()
        set_theme("dark" if self.v_dark.get() else "light")
        UI.setup(self.root, TEXT_SIZES[self.v_text_size.get()], cjk=language() == "zh")
        self.root.title(tr(APP_NAME))
        self._build_ui()
        self.load_accounts(select_id=self.account_id)
        if open_sym:
            self.open_symbol(open_sym)
        if was_finance:
            self.open_finance()

    # ------------------------------------------------------------ Accounts
    def load_accounts(self, select_id: int | None = None):
        self.accounts = self.db.list_accounts()
        ids = [a["id"] for a in self.accounts]
        if select_id == ALL_ACCOUNTS and len(ids) >= 2:
            pass  # the combined view only makes sense with two or more accounts
        elif select_id not in ids:
            select_id = ids[0] if ids else None
        self._select_account(select_id)

    def _select_account(self, account_id):
        if account_id != self.account_id:
            self.v_filter_symbol.set(tr(ALL))
            self.close_detail()
        self.account_id = account_id
        acc = self.current_account()
        self.account_btn.set_text(tr("All accounts") if self.combined else acc["name"] if acc else tr("No account"))
        self.hero.title.configure(text=tr("Net worth (all accounts)" if self.combined else "Total assets"))
        if self.combined != self._tabs_combined:
            self._make_page_tabs()
        self.refresh()

    @property
    def combined(self) -> bool:
        """True in the all-accounts view: every account added up, read-only."""
        return self.account_id == ALL_ACCOUNTS

    def current_account(self):
        return next((a for a in self.accounts if a["id"] == self.account_id), None)

    def _on_account_double(self, event):
        if self.acct_tree.identify_region(event.x, event.y) == "cell" and self.acct_tree.focus():
            self._select_account(int(self.acct_tree.focus()))

    def require_account(self) -> bool:
        if self.account_id is None:
            if messagebox.askyesno(tr(APP_NAME), tr("There are no accounts yet. Create one now?")):
                self.new_account()
            return self.account_id is not None
        return True

    def first_run(self):
        messagebox.showinfo(tr(APP_NAME), tr("Welcome! Start by creating an account and entering its opening cash and positions "
                                             "(both optional; you can add them later)."))
        self.new_account()

    def new_account(self):
        data = AccountDialog(self.root, tr("New Account"), suggest=self.symbol_search).show()
        if not data:
            return
        try:
            new_id = self.db.create_account(data["name"], data["broker"], data["note"], data["opening"])
        except sqlite3.IntegrityError:
            messagebox.showerror(tr(APP_NAME), tr('An account named "{name}" already exists. Please choose another name.',
                                                  name=data["name"]))
            return
        self.load_accounts(select_id=new_id)

    def edit_account(self):
        acc = self.current_account()
        if not acc:
            return
        data = AccountDialog(self.root, tr("Edit Account"), suggest=self.symbol_search, initial=acc).show()
        if not data:
            return
        try:
            self.db.update_account(acc["id"], data["name"], data["broker"], data["note"])
        except sqlite3.IntegrityError:
            messagebox.showerror(tr(APP_NAME), tr('An account named "{name}" already exists.', name=data["name"]))
            return
        self.load_accounts(select_id=acc["id"])

    def delete_account(self):
        acc = self.current_account()
        if not acc:
            return
        if not messagebox.askyesno(
            tr("Delete Account"),
            tr('Delete the account "{name}" and its {n} transactions?\n\n'
               "This cannot be undone (daily automatic backups are in the data\\backups folder).",
               name=acc["name"], n=len(self.txns)),
            icon="warning",
        ):
            return
        self.db.delete_account(acc["id"])
        self.account_id = None
        self.load_accounts()

    # ------------------------------------------------------------ Transactions
    def _check_txn(self, t: Txn, parent) -> bool:
        """Before saving, replay the full history with the new transaction to make sure nothing conflicts."""
        others = [x for x in self.txns if x.id != t.id]
        try:
            res = replay(others + [t])
        except LedgerError as e:
            messagebox.showerror(tr("Cannot Save"), tr("Saving this would make the books inconsistent:\n{error}", error=e),
                                 parent=parent)
            return False
        if t.cash_change < 0:
            idx = next(i for i, r in enumerate(res.rows) if r.txn is t)
            low = min(r.cash_after for r in res.rows[idx:])
            if low < 0 and not messagebox.askyesno(
                tr("Insufficient Cash"),
                tr("After this transaction the cash balance goes negative (lowest {low}).\n"
                   "If this is margin or a deposit you have not recorded yet, you can still save. Save anyway?",
                   low=fmt_money(low)),
                parent=parent, icon="warning",
            ):
                return False
        return True

    def _positions_without(self, txn_id: int | None):
        """When editing a transaction, the position hints should exclude that transaction itself."""
        if txn_id is None:
            return self.result.positions
        try:
            return replay([x for x in self.txns if x.id != txn_id]).positions
        except LedgerError:
            return self.result.positions

    def add_txn(self, default_type: str | None = None, default_symbol: str = "", parent=None):
        if self.root.grab_current() is not None or self.finance or not self.require_account():
            return
        if self.combined:
            messagebox.showinfo(tr(APP_NAME), tr("This is the combined view of all accounts. "
                                                 "Choose one account to add a transaction."))
            return
        t = TxnDialog(parent or self.root, tr("Add Transaction"), suggest=self.symbol_search, positions=self.result.positions,
                      check=self._check_txn, default_type=default_type or self.last_type,
                      default_symbol=default_symbol, default_date=self.last_date).show()
        if not t:
            return
        t.account_id = self.account_id
        self.db.add_txn(t)
        self.last_date, self.last_type = t.date, t.type
        self.refresh(select_txn=t.id)

    def edit_txn(self, txn_id: int, parent=None):
        old = next((x for x in self.txns if x.id == txn_id), None)
        if not old:
            return
        t = TxnDialog(parent or self.root, tr("Edit Transaction"), suggest=self.symbol_search, positions=self._positions_without(txn_id),
                      check=self._check_txn, initial=old).show()
        if not t:
            return
        self.db.update_txn(t)
        self.refresh(select_txn=t.id)

    def edit_selected_txn(self):
        sel = self.txn_tree.focus()
        if sel:
            self.edit_txn(int(sel))
        else:
            messagebox.showinfo(tr(APP_NAME), tr("Please select a transaction in the Transactions tab first."))

    def delete_selected_txn(self):
        sel = self.txn_tree.focus()
        if not sel:
            messagebox.showinfo(tr(APP_NAME), tr("Please select a transaction in the Transactions tab first."))
            return
        t = next(x for x in self.txns if x.id == int(sel))
        desc = f"{t.date}  {t.type_label}  {t.symbol}  {fmt_money(t.cash_change, sign=True) if t.cash_change else ''}"
        try:
            replay([x for x in self.txns if x.id != t.id])
        except LedgerError as e:
            messagebox.showerror(tr("Cannot Delete"), tr("Deleting this would make the books inconsistent:\n{error}\n\n"
                                                        "Edit or delete the later related transactions first.", error=e))
            return
        if messagebox.askyesno(tr("Delete Transaction"), tr("Delete this transaction?\n\n{desc}", desc=desc)):
            self.db.delete_txn(t.id)
            self.refresh()

    def _on_txn_double(self, event):
        if self.txn_tree.identify_region(event.x, event.y) == "cell" and self.txn_tree.focus():
            self.edit_txn(int(self.txn_tree.focus()))

    def _clear_filters(self):
        self.v_filter_symbol.set(tr(ALL))
        self.v_filter_type.set(tr(ALL))
        self.v_filter_period.set(tr(PERIODS["ALL"]))
        self.v_from.set("")
        self.v_to.set("")

    def _sync_reset_button(self):
        filtering = (tr(ALL) != self.v_filter_symbol.get() or tr(ALL) != self.v_filter_type.get()
                     or tr(PERIODS["ALL"]) != self.v_filter_period.get())
        if filtering and not self.reset_btn.winfo_ismapped():
            self.reset_btn.pack(side="left", padx=UI.px(6), after=self.filter_period_box)
        elif not filtering:
            self.reset_btn.pack_forget()

    def period_choices(self) -> dict[str, str]:
        """The choices of the Period box as shown -> their codes: the ready-made periods, each year that has
        transactions (newest first), and the custom range."""
        choices = {tr(text): code for code, text in PERIODS.items()}
        choices.update({year: year for year in sorted({t.date[:4] for t in self.txns}, reverse=True)})
        choices[tr(CUSTOM_PERIOD)] = "CUSTOM"
        return choices

    def date_bounds(self) -> tuple[str | None, str | None]:
        """First and last date the transaction list is narrowed to (None = no limit), from the Period box and,
        for a custom range, the two date boxes -- which turn red while their text is not a usable date."""
        code = self.period_codes.get(self.v_filter_period.get(), "ALL")
        if code != "CUSTOM":
            return period_range(code)
        bounds, bad = [], []
        for var in (self.v_from, self.v_to):
            text = var.get().strip()
            try:
                bounds.append(parse_date(text) if text else None)
                bad.append(False)
            except ValueError:
                bounds.append(None)
                bad.append(True)
        if bounds[0] and bounds[1] and bounds[0] > bounds[1]:  # "from" after "to" can never match anything
            bad = [True, True]
        for entry, flag in zip((self.from_entry, self.to_entry), bad):
            entry.state(["invalid"] if flag else ["!invalid"])
        return bounds[0], bounds[1]

    # ------------------------------------------------------------ Holdings
    def _on_hold_double(self, event):
        if self.hold_tree.identify_region(event.x, event.y) == "cell":
            self.open_symbol(self.hold_tree.focus())

    def open_selected_symbol(self):
        sym = self.hold_tree.focus()
        if not sym:
            messagebox.showinfo(tr(APP_NAME), tr("Please select a stock first."))
            return
        self.open_symbol(sym)

    def open_symbol(self, sym: str):
        """Show a stock's page in place of the overview (from the Stocks list or the Holdings table)."""
        if not sym or sym not in self.result.positions:
            return
        if self.detail and self.detail.symbol == sym:
            return
        if self.detail:
            self.detail.destroy()
        else:
            self.overview.pack_forget()
        self.detail = SymbolDetail(self, self.main, sym)
        self.detail.pack(fill="both", expand=True)
        self.root.title(f"{sym} · {tr(APP_NAME)}")

    def close_detail(self):
        """Back to the overview."""
        if not self.detail:
            return
        self.detail.destroy()
        self.detail = None
        self.overview.pack(fill="both", expand=True)
        self.root.title(tr(APP_NAME))

    def open_finance(self):
        """Show the finance page in place of the whole stock view."""
        if self.finance or not self.v_finance.get() or self.root.grab_current() is not None:
            return
        self.body.pack_forget()
        self.stock_left.pack_forget()
        self.stock_right.pack_forget()
        self.finance = FinancePage(self, self.root)
        self.finance.pack(fill="both", expand=True, padx=UI.px(28), pady=(UI.px(18), UI.px(8)))
        self.finance.refit()
        self.finance.scroll_to_latest()
        self.root.title(f"{tr('Finance')} · {tr(APP_NAME)}")

    def close_finance(self):
        """Back to the stock view (on the stock page that was open, if any)."""
        if not self.finance:
            return
        self.finance.destroy()
        self.finance = None
        self.body.pack(fill="both", expand=True, padx=UI.px(28), pady=(UI.px(18), UI.px(8)))
        self.stock_left.pack(side="left")
        self.stock_right.pack(side="right")
        self.refresh_net_summary()  # the finance balance may have changed
        self.root.title(f"{self.detail.symbol} · {tr(APP_NAME)}" if self.detail else tr(APP_NAME))

    def update_prices(self):
        if not self.require_account():
            return
        positions = self.result.open_positions
        if not positions:
            messagebox.showinfo(tr(APP_NAME), tr("The current account has no open positions."))
            return
        data = PriceDialog(self.root, positions, self.price_info, live=self.v_live.get()).show()
        if data is None:
            return
        self.db.set_prices(data)
        self.refresh()

    # ------------------------------------------------------------ Background work and live prices
    def run_bg(self, fn, args, done):
        """Run fn(*args) in a background thread; done(result or exception) is then called on the UI thread."""
        def work():
            try:
                res = fn(*args)
            except Exception as e:  # handed to `done`, which decides what to show
                res = e
            self._bg_queue.put((done, res))
        threading.Thread(target=work, daemon=True).start()

    def _poll_bg(self):
        try:
            while True:
                done, res = self._bg_queue.get_nowait()
                try:
                    done(res)
                except tk.TclError:
                    pass  # the window it was meant for was closed meanwhile
        except queue.Empty:
            pass
        self.root.after(150, self._poll_bg)

    def toggle_live(self):
        self.db.set_setting("live_prices", "1" if self.v_live.get() else "0")
        if self._live_job:
            self.root.after_cancel(self._live_job)
            self._live_job = None
        if self.v_live.get():
            self._live_tick()
        else:
            self.quotes.clear()
            self.live_status.configure(text="", fg=C["muted"])
        self.refresh_view()

    def _live_tick(self):
        self._live_job = None
        if not self.v_live.get():
            return
        self._fetch_quotes()
        self._live_job = self.root.after(LIVE_INTERVAL * 1000, self._live_tick)

    def _fetch_quotes(self):
        symbols = [p.symbol for p in self.result.open_positions]
        if self._fetching or not symbols:
            return
        self._fetching = True
        self.run_bg(fetch_quotes, (symbols,), lambda res: self._apply_quotes(symbols, res))

    def _apply_quotes(self, symbols, got):
        self._fetching = False
        if not self.v_live.get():
            return
        if isinstance(got, Exception):
            self.live_status.configure(text=tr("Offline, retrying…"), fg=C["loss"])
            return
        self.quotes.update(got)
        # save prices that changed, so the last known price is still there when offline
        changed = {s: q.price for s, q in got.items() if self.prices.get(s) != q.price}
        if changed:
            self.db.set_prices(changed)
            self.price_info.update({s: (price, today()) for s, price in changed.items()})
            self.prices.update(changed)
        missing = [s for s in symbols if s not in got]
        note = tr(" · no quote: {symbols}", symbols=", ".join(missing)) if missing else ""
        self.live_status.configure(text=tr("Updated {time}", time=f"{datetime.now():%H:%M:%S}") + note, fg=C["muted"])
        self.refresh_view()

    def _day_change(self) -> tuple[Decimal, Decimal]:
        """Today's change in value of the holdings that have a live quote, and their value at yesterday's close."""
        change = base = ZERO
        for p in self.result.open_positions:
            q = self.quotes.get(p.symbol)
            if q and q.change is not None:
                change += p.quantity * q.change
                base += p.quantity * q.prev_close
        return change, base

    # ------------------------------------------------------------ Chart
    def _on_range(self, rng):
        self.range = rng
        self.refresh_chart()

    def refresh_chart(self):
        r = self.result
        total = r.cash + valuation(r, self.prices).market_value
        now = usd(total) if self.account_id is not None else "-"
        hero = self.hero
        if self.account_id is None or not r.rows:
            hero.show(self.range, now, [], message=tr("No transactions yet"))
            return
        if not self.v_live.get():
            hero.show(self.range, now, [], message=tr("Turn on Live prices to see the chart"))
            return
        end = (int(time.time()), float(total), float(r.net_deposits))
        if self.range == "1D":
            series = {s: q.points for s, q in self.quotes.items() if s in r.positions and q.points}
            if not series:
                msg = tr("Loading…" if self._fetching else ("No chart data" if r.open_positions else "No holdings"))
                hero.show("1D", now, [], message=msg)
                return
            day, _ = self._day_change()
            points = [(p.time, p.value, p.net_deposits) for p in self._value_points(series)] + [end]
            prev = float(total - day)
            hero.show("1D", now, points, baseline=prev, now_change=float(day), now_base=prev)
            return
        if self.range == "ALL":
            yr, iv = all_range(r.rows[0].txn.date)
        else:
            yr, iv = RANGES[self.range][:2]
        symbols = tuple(sorted(r.positions))
        key = (yr, iv, symbols)
        fetched, data = self.history.get(key, (0, None))
        if time.time() - fetched > HISTORY_TTL:
            self.history[key] = (time.time(), data)  # don't start a second fetch meanwhile
            self.run_bg(fetch_quotes, (list(symbols), yr, iv), lambda res: self._got_history(key, res))
        if data is None:
            hero.show(self.range, now, [], message=tr("Loading…"))
            return
        series = {s: q.points for s, q in data.items() if q.points}
        points = [(p.time, p.value, p.net_deposits) for p in self._value_points(series)] + [end]
        hero.show(self.range, now, points)

    def _value_points(self, series):
        """Account value over time from the price series; the all-accounts view adds up every account's."""
        if self.combined:
            return combine_series([value_series(res.rows, series, self.prices) for res in self.account_results.values()])
        return value_series(self.result.rows, series, self.prices)

    def _got_history(self, key, res):
        if isinstance(res, Exception):
            self.history[key] = (0, None)
            self.hero.show(self.range, self.hero.now[0], [], message=tr("Couldn't load the chart (offline?)"))
            return
        self.history[key] = (time.time(), res)
        self.refresh_chart()

    # ------------------------------------------------------------ Refresh
    def refresh(self, select_txn: int | None = None):
        self.account_results = {}
        if self.combined:
            self.txns = []
            for a in self.accounts:
                txns = self.db.list_txns(a["id"])
                self.txns += txns
                self.account_results[a["id"]] = self._replay(txns)
            self.result = combine_results(self.account_results.values())
        elif self.account_id is not None:
            self.txns = self.db.list_txns(self.account_id)
            self.result = self._replay(self.txns)
        else:
            self.txns, self.result = [], LedgerResult()
        self.price_info = self.db.get_prices()
        self.prices = {s: p for s, (p, _) in self.price_info.items()}

        symbols = [tr(ALL), *sorted({s for t in self.txns for s in (t.symbol, t.symbol2) if s})]
        self.filter_symbol_box.configure(values=symbols)
        if self.v_filter_symbol.get() not in symbols:
            self.v_filter_symbol.set(tr(ALL))
        self.period_codes = self.period_choices()
        self.filter_period_box.configure(values=list(self.period_codes))
        if self.v_filter_period.get() not in self.period_codes:  # a year this account has no transactions in
            self.v_filter_period.set(tr(PERIODS["ALL"]))
        self.refresh_view()
        self.refresh_txn_list(select_txn)

        acc = self.current_account()
        if self.combined:
            self.status.configure(text=f"{tr('All accounts')} · {plural(str(len(self.accounts)), '{n} account', '{n} accounts')}"
                                       f" · {tr('{n} transactions', n=len(self.txns))}"
                                       f"        {tr('Data file: {path}', path=self.db.path)}")
        elif acc:
            broker = f" · {acc['broker']}" if acc["broker"] else ""
            note = f" · {acc['note']}" if acc["note"] else ""
            self.status.configure(text=f"{acc['name']}{broker}{note} · {tr('{n} transactions', n=len(self.txns))}"
                                       f"        {tr('Data file: {path}', path=self.db.path)}")
        else:
            self.status.configure(text=tr("Data file: {path}", path=self.db.path))
        if self.v_live.get() and any(p.symbol not in self.quotes for p in self.result.open_positions):
            self._fetch_quotes()  # new account or new stock: don't wait for the next tick

    def _replay(self, txns: list[Txn]) -> LedgerResult:
        try:
            return replay(txns)
        except LedgerError as e:  # only happens if the database was edited by hand
            messagebox.showerror(tr(APP_NAME), tr("Error replaying the ledger: {error}", error=e))
            return LedgerResult()

    def refresh_view(self):
        """Redraw everything that depends on prices."""
        self.refresh_chart()
        self.refresh_stats()
        self.refresh_net_summary()
        self.refresh_sidebar()
        self.refresh_accounts()
        self.refresh_holdings()
        if self.detail:
            self.detail.reload()

    def finance_balance(self) -> tuple[Decimal, str] | None:
        """The latest month-end balance of the Finance page (all the bank money outside the brokerage accounts) and
        its month, or None when the page is off or has no month yet."""
        if not self.v_finance.get():
            return None
        rows = finance_rows(self.db.list_finance_months(), self.db.list_finance_categories())
        return (rows[-1].ending, rows[-1].month.month) if rows else None

    def refresh_net_summary(self):
        """All-accounts view, Finance page on and in use: the net worth of everything -- the stock accounts plus the
        finance cash balance -- with its parts side by side: stock net worth, the cash inside it, and the finance cash.
        The chart under it stays about the stock accounts only, so its title says so."""
        if self.net_summary is None:
            return
        frame, grid = self.net_summary
        balance = self.finance_balance() if self.combined else None
        if balance is None:
            frame.pack_forget()
            if self.combined:
                self.hero.title.configure(text=tr("Net worth (all accounts)"))
            return
        finance, month = balance
        r = self.result
        stock = r.cash + valuation(r, self.prices).market_value
        grid.set("total", usd(stock + finance), tr("= stock accounts net worth + finance cash balance"))
        grid.set("stock", usd(stock), plural(str(len(self.accounts)), "{n} account", "{n} accounts"))
        grid.set("cash", usd(r.cash), tr("Part of stock accounts net worth"), C["loss"] if r.cash < 0 else None)
        grid.set("finance", usd(finance), tr("Outside brokerage accounts, as of {month}", month=month),
                 C["loss"] if finance < 0 else None)
        if not frame.winfo_manager():
            frame.pack(fill="x", before=self.hero)
        self.hero.title.configure(text=tr("Stock accounts net worth"))

    def refresh_stats(self):
        r = self.result
        st = self.stats
        if self.account_id is None:
            for key in st.cells:
                st.set(key, "-")
            return
        v = valuation(r, self.prices)
        total = r.cash + v.market_value
        st.set("cash", usd(r.cash), tr("{pct}% of total", pct=f"{r.cash / total * 100:.1f}") if total > 0 else "",
               C["loss"] if r.cash < 0 else None)
        n_open = len(r.open_positions)
        if v.missing:
            note = tr("{symbols} etc. at cost" if len(v.missing) > 2 else "{symbols} at cost",
                      symbols=", ".join(v.missing[:2]))
        else:
            note = plural(str(n_open), "{n} stock", "{n} stocks")
        st.set("value", usd(v.market_value), note)
        st.set("cost", usd(r.total_cost), tr("Incl. commissions"))
        priced = n_open - len(v.missing)
        if priced:
            priced_cost = sum((p.cost for p in r.open_positions if p.symbol in self.prices), ZERO)
            st.set("unreal", usd(v.unrealized, sign=True),
                   fmt_pct(v.unrealized / priced_cost) if priced_cost else "", color_for(v.unrealized))
        else:
            st.set("unreal", "-", tr("Needs prices"))
        st.set("realized", usd(r.realized, sign=True), "", color_for(r.realized))
        st.set("income", usd(r.dividends + r.interest),
               tr("Div {div} · Int {int}", div=fmt_money(r.dividends), int=fmt_money(r.interest)))
        st.set("net", usd(r.net_deposits), tr("In {deposits} · Out {withdrawals}", deposits=fmt_money(r.deposits),
                                              withdrawals=fmt_money(r.withdrawals)))
        st.set("fees", usd(r.fees))

    def refresh_sidebar(self):
        positions = self.result.open_positions
        syms = [p.symbol for p in positions]
        if list(self.stock_rows) != syms:  # holdings changed: rebuild the rows
            for row in self.stock_rows.values():
                row.destroy()
            self.stock_rows = {}
            for s in syms:
                row = StockRow(self.side_list.inner, s, self.open_symbol)
                row.pack(fill="x", padx=UI.px(10), pady=UI.px(6))
                self.stock_rows[s] = row
        if syms:
            self.side_empty.pack_forget()
        else:
            self.side_empty.pack(pady=UI.px(20))
        for p in positions:
            self.stock_rows[p.symbol].show(p, self.quotes.get(p.symbol), self.prices.get(p.symbol))
        self.side_count.configure(text=plural(str(len(syms)), "{n} holding", "{n} holdings") if syms else "")

    def refresh_accounts(self):
        """The Accounts tab of the all-accounts view: one row per account."""
        tree = self.acct_tree
        selected = tree.focus()
        tree.delete(*tree.get_children())
        tree.hover_row = ""
        if not self.combined:
            return
        grand = self.result.cash + valuation(self.result, self.prices).market_value
        for a in self.accounts:
            res = self.account_results.get(a["id"])
            if res is None:
                continue
            v = valuation(res, self.prices)
            total = res.cash + v.market_value
            priced = any(p.symbol in self.prices for p in res.open_positions)
            tree.insert("", "end", iid=str(a["id"]), values=(
                a["name"],
                fmt_money(res.cash),
                fmt_money(v.market_value),
                fmt_money(total),
                f"{total / grand * 100:.1f}%" if grand > 0 else "-",
                fmt_money(v.unrealized, sign=True) if priced else "-",
                fmt_money(res.realized, sign=True),
                fmt_money(res.net_deposits),
            ))
        if tree.sort_state:
            sort_tree(tree, *next(iter(tree.sort_state.items())))
        if selected and tree.exists(selected):
            tree.selection_set(selected)
            tree.focus(selected)

    def refresh_holdings(self):
        tree = self.hold_tree
        selected = tree.focus()
        scroll = tree.yview()[0]
        tree.delete(*tree.get_children())
        tree.hover_row = ""
        positions = self.result.all_positions if self.v_show_closed.get() else self.result.open_positions
        for p in positions:
            price = self.prices.get(p.symbol)
            mv = unreal = pct = None
            if p.is_open and price is not None:
                mv = p.quantity * price
                unreal = mv - p.cost
                pct = unreal / p.cost if p.cost else None
            q = self.quotes.get(p.symbol) if p.is_open else None
            day = "-"
            if q and q.change is not None:
                day = f"{fmt_money(p.quantity * q.change, sign=True)} ({fmt_pct(q.change / q.prev_close)})"
            tags = [] if p.is_open else ["muted"]
            tree.insert("", "end", iid=p.symbol, tags=tags, values=(
                p.symbol,
                fmt_qty(p.quantity),
                fmt_price(p.avg_cost) if p.is_open else "-",
                fmt_money(p.cost) if p.is_open else "-",
                fmt_price(price) if (price is not None and p.is_open) else "-",
                day,
                fmt_money(mv),
                fmt_money(unreal, sign=True) if unreal is not None else "-",
                fmt_pct(pct),
                fmt_money(p.realized, sign=True),
                fmt_money(p.dividends),
            ))
        if tree.sort_state:  # keep the user's column sort across live updates
            sort_tree(tree, *next(iter(tree.sort_state.items())))
        if selected and tree.exists(selected):
            tree.selection_set(selected)
            tree.focus(selected)
        tree.yview_moveto(scroll)

    def refresh_txn_list(self, select_txn: int | None = None):
        tree = self.txn_tree
        keep = select_txn or (int(tree.focus()) if tree.focus() else None)
        tree.delete(*tree.get_children())
        tree.hover_row = ""
        if self.combined:  # the transaction list belongs to one account
            return
        sym = self.v_filter_symbol.get()
        typ = self.v_filter_type.get()
        custom = self.period_codes.get(self.v_filter_period.get()) == "CUSTOM"
        if custom and not self.range_bar.winfo_ismapped():
            self.range_bar.pack(fill="x", pady=(0, UI.px(6)), before=self.txn_frame)
        elif not custom:
            self.range_bar.pack_forget()
        first, last = self.date_bounds()
        shown = 0
        for row in reversed(self.result.rows):  # newest first
            t = row.txn
            if sym != tr(ALL) and sym not in (t.symbol, t.symbol2):
                continue
            if typ != tr(ALL) and t.type_label != typ:
                continue
            if (first and t.date < first) or (last and t.date > last):
                continue
            need = TYPE_FIELDS[t.type]
            tree.insert("", "end", iid=str(t.id), values=(
                t.date,
                t.type_label,
                symbol_text(t),
                fmt_qty(t.quantity, sign=t.type == "SPLIT") if "quantity" in need else "",
                price_text(t),
                fmt_money(t.fee) if t.fee else "",
                fmt_money(t.cash_change, sign=True) if t.cash_change else "-",
                fmt_money(row.cash_after),
                t.note,
            ))
            shown += 1
        self._sync_reset_button()
        total = len(self.result.rows)
        self.txn_count.configure(text=tr("Showing {shown} of {total}", shown=shown, total=total) if shown != total
                                 else tr("{total} total", total=total))
        if keep and tree.exists(str(keep)):
            tree.selection_set(str(keep))
            tree.focus(str(keep))
            tree.see(str(keep))

    # ------------------------------------------------------------ File
    def export_csv(self):
        acc = self.current_account()
        if not acc:
            return
        folder = filedialog.askdirectory(title=tr("Choose a folder to export to"))
        if not folder:
            return
        stamp = datetime.now().strftime("%Y%m%d")
        base = safe_filename(acc["name"])
        txn_file = Path(folder) / f"{base}_transactions_{stamp}.csv"
        hold_file = Path(folder) / f"{base}_holdings_{stamp}.csv"
        # utf-8-sig: lets Excel display non-ASCII text (e.g. notes) correctly
        with open(txn_file, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow([tr(h) for h in ("Date", "Type", "Symbol", "Quantity", "Price", "Fee", "Amount", "Cash Change",
                                        "Cash Balance", "Note", "New Symbol")])
            for row in self.result.rows:
                t = row.txn
                w.writerow([t.date, t.type_label, t.symbol, format(t.quantity, "f"), format(t.price, "f"),
                            format(t.fee, "f"), format(t.amount, "f"), fmt_money(t.cash_change).replace(",", ""),
                            fmt_money(row.cash_after).replace(",", ""), t.note, t.symbol2])
        with open(hold_file, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow([tr(h) for h in ("Symbol", "Shares", "Avg Cost", "Cost Basis", "Price", "Market Value",
                                        "Realized P/L", "Dividends")])
            for p in self.result.all_positions:
                price = self.prices.get(p.symbol)
                mv = p.quantity * price if (price is not None and p.is_open) else None
                w.writerow([p.symbol, format(p.quantity, "f"), fmt_price(p.avg_cost).replace(",", ""),
                            fmt_money(p.cost).replace(",", ""), format(price, "f") if price is not None else "",
                            fmt_money(mv).replace(",", "") if mv is not None else "",
                            fmt_money(p.realized).replace(",", ""), fmt_money(p.dividends).replace(",", "")])
            w.writerow([])
            w.writerow([tr("Cash Balance"), fmt_money(self.result.cash).replace(",", "")])
        messagebox.showinfo(tr(APP_NAME), tr("Exported:\n{files}", files=f"{txn_file.name}\n{hold_file.name}"))

    def backup(self):
        path = filedialog.asksaveasfilename(
            title=tr("Back Up Database"), defaultextension=".db",
            initialfile=f"stock_ledger_backup_{datetime.now():%Y%m%d_%H%M}.db",
            filetypes=[(tr("SQLite database"), "*.db"), (tr("All files"), "*.*")],
        )
        if path:
            self.db.backup_to(path)
            messagebox.showinfo(tr(APP_NAME), tr("Backup complete:\n{path}", path=path))

    def show_help(self):
        messagebox.showinfo(tr("User Guide"), tr(
            "1. When creating an account you can enter opening cash and positions.\n"
            "2. For every buy, sell, dividend, deposit or withdrawal, click \"+ Add transaction\" (Ctrl+N).\n"
            "   In the Symbol box, type a ticker or a company name and pick from the list.\n"
            "3. Cash balance, shares, average cost and P/L are all calculated from the transactions.\n"
            "   To fix a mistake, double-click it in the Transactions tab, or select it and press Delete.\n"
            "4. With \"Live\" on, prices update every {seconds} seconds from Yahoo Finance.\n"
            "   Turn it off to work offline and enter prices by hand with \"Update prices\".\n"
            "5. Hover over the chart to see your total assets at any point; pick a range below it.\n"
            "   Changes for ranges other than 1D leave out deposits and withdrawals.\n"
            "6. Click a stock in the Stocks list for its own page with chart and history.\n"
            "7. Dividend reinvestment: record a Dividend, then a Buy.\n"
            "8. Stock split: record a Split with the number of shares added (total cost is unchanged).\n"
            "9. Cost basis uses the average cost method.\n"
            "10. With two or more accounts, \"All accounts\" in the account menu adds them up (read-only).\n"
            "11. In the Transactions tab, the Period box narrows the list to the past month, 3 or 6 months, a year,\n"
            "   a calendar year, or dates you type.\n"
            "12. Optional: ⋯ → Finance page adds a Finance button with a monthly income and expense sheet for money\n"
            "   outside your brokerage accounts. Double-click a month to edit it; every amount can carry a comment.\n"
            "   The All accounts view then also shows the net worth including that cash balance.\n\n"
            "Data is stored in:\n{path}\nIt is backed up to the backups folder the first time you open the app each day.",
            seconds=LIVE_INTERVAL, path=self.db.path,
        ))

    def show_about(self):
        messagebox.showinfo(tr("About"), tr(
            "{app} {version}\n\nA local bookkeeping tool. Your data stays on your own computer;\n"
            "only stock symbols (and what you type into a symbol box) are sent to Yahoo Finance\n"
            "for live prices and suggestions.", app=tr(APP_NAME), version=APP_VERSION))

    def quit(self):
        if self.account_id is not None:
            self.db.set_setting("last_account", "all" if self.combined else str(self.account_id))
        self.db.close()
        self.root.destroy()


# ======================================================================
def main():
    if sys.platform == "win32":
        try:  # crisp text on high-DPI screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    folder = data_dir()
    db_path = folder / "stock_ledger.db"
    try:
        daily_backup(db_path, folder / "backups")
    except Exception:
        pass  # a failed backup should not block the app

    db = Storage(db_path)
    set_language(saved_language(db))
    set_theme(db.get_setting("theme", "dark"))
    root = tk.Tk()
    if sys.platform == "win32":
        try:
            root.iconbitmap(default=str(resource_path("icon.ico")))
        except tk.TclError:
            pass
    UI.setup(root, TEXT_SIZES[text_size(db)], cjk=language() == "zh")
    App(root, db, folder)
    root.mainloop()


if __name__ == "__main__":
    main()
