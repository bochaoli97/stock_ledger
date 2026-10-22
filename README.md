# Stock Ledger

**English** | [简体中文](README.zh-CN.md)

A simple local bookkeeping app for a brokerage account: it tracks the cash balance, holdings, and the cost and profit/loss of every trade.
It uses only the Python standard library (tkinter UI + sqlite3 database) and keeps your data on your own computer.
The only things it sends over the internet are your stock symbols, to fetch live prices, and what you type into a
symbol box, to suggest matching stocks (both can be turned off).

## Features

- Robinhood-style design: dark mode (or light), your total assets in large type over a portfolio chart
  (1D / 1W / 1M / 3M / YTD / 1Y / ALL), hover the chart to see any point in time, and a Stocks list with
  today's sparkline and price for every holding

- Multiple accounts (e.g. a Fidelity individual account and a Roth IRA); opening cash and positions can be entered when creating one
- **All accounts** view: with two or more accounts, add them up into one net worth, with a per-account table
  and holdings merged across accounts
- Transaction types: Deposit, Withdrawal, Buy, Sell, Dividend, Interest, Fee, Shares In, Shares Out, Split, Symbol Change, Distribution
- Crypto as well as stocks: record bitcoin as `BTC-USD` (ether `ETH-USD`, …), with amounts down to 0.00000001
- Automatic calculation of cash balance (with the running balance after every transaction), shares held, average cost, cost basis, realized P/L and total dividends
- Per-stock detail: double-click a stock to see each of its transactions, with the shares held and average cost after each one
- Live prices from Yahoo Finance every 10 seconds: market value, unrealized P/L, day change and total assets update as the market moves;
  while the market is open, a pulsing dot marks the latest price at the end of today's line, as in Robinhood
- Turn live prices off to work fully offline and enter prices by hand instead
- Symbol search as you type, like Robinhood: enter a ticker or a company name ("apple", "berkshire") and pick from
  the list with the mouse or Up/Down + Enter. Stocks you hold are listed first with their share count; other matches
  come from Yahoo while live prices are on (offline, only the account's own symbols are suggested)
- **Period filter** in the Transactions tab: the past month, 3 or 6 months, the past year, any calendar year, or a start and end date you type
- **Finance page** (optional, off until you turn it on in the ⋯ menu) for money outside your brokerage accounts: a month-by-month
  income and expense sheet (like a spreadsheet) with a balance that carries forward, your own income and expense categories,
  amounts that can be written as sums (`1250.50+1250.50`), a comment on any amount, and totals for any period of months
  (a tax year, a custom range, ...) to check against a tax return
- Double-click to edit or delete a mistake and every number is recalculated; inconsistent entries (such as selling more than you hold) are rejected
- Adjustable text size (More menu → Text size: Small / Standard / Large / Extra large)
- English or Chinese interface (More menu → Language / 语言); Chinese on first launch
- CSV export (opens directly in Excel), manual database backup, and automatic daily backups

## Files

| File | Purpose |
|---|---|
| `app.py` | GUI and program entry point |
| `ledger.py` | Bookkeeping logic (independent of the UI, testable on its own) |
| `finance.py` | Monthly income and expenses outside the brokerage accounts: sums, balances, periods of months (independent of the UI, testable on its own) |
| `csv_export.py` | The layout of the CSV files: which columns, in which order (independent of the UI, testable on its own) |
| `storage.py` | Persistence (SQLite) |
| `quotes.py` | Live stock quotes and price history (Yahoo Finance, no API key needed) |
| `ui.py` | Look and feel: dark/light themes, fonts, chart and other custom widgets |
| `i18n.py` | Interface language: English / Chinese text |
| `test_ledger.py` | Tests for the bookkeeping logic, the finance page, storage, quotes, symbol search and translations (no internet needed) |
| `icon.ico` | App icon |
| `build_exe.bat` | Builds the exe on Windows |
| `build_from_wsl.sh` | Builds the exe from WSL with one command (calls the Windows Python) |

---

## 1. Set up the development environment in WSL

**1. Put the project in WSL** (in a WSL terminal, assuming the zip was downloaded to your Windows Downloads folder):

```bash
cd ~
cp /mnt/c/Users/<your Windows username>/Downloads/stock_ledger.zip .
unzip stock_ledger.zip
cd stock_ledger
```

**2. Create a conda environment** (with the `xft` build of Tk, which can use real, smooth fonts on Linux):

```bash
conda create -n stockledger -c conda-forge python=3.12 "tk=8.6.*=xft*" xorg-libxft -y
conda activate stockledger
python -c "import tkinter; tkinter._test()"   # a small window popping up means the GUI works
```

**3. Install CJK fonts** — needed for the Chinese interface, and for account names or notes in Chinese/Japanese/Korean,
which otherwise show as boxes in WSL:

```bash
sudo apt update && sudo apt install -y fonts-noto-cjk
```

**4. Open in VS Code**:

- In VS Code on Windows, install the **WSL** (by Microsoft) and **Python** extensions
- In a WSL terminal, go to the project folder and run `code .`; VS Code opens in WSL mode (`WSL: Ubuntu` in the bottom-left corner)
- After the first launch, install the Python extension for WSL as well from the Extensions view
- `Ctrl+Shift+P` → `Python: Select Interpreter` → pick the `stockledger` conda environment

## 2. Run and debug

```bash
conda activate stockledger
python app.py          # start the app (the window appears on the Windows desktop via WSLg)
python test_ledger.py  # run the tests to check the calculations
```

You can also open `app.py` in VS Code and press `F5` to run it with breakpoints.

During development, data is stored in `stock_ledger/data/stock_ledger.db`.

## 3. Build a Windows exe

> PyInstaller cannot cross-compile: building in WSL (Linux) produces a Linux program.
> So write the code in WSL, but **use the Windows Python for the build step**. This only needs to be set up once.

**1. Install Python on Windows** (one time)

Download Python 3.12 or newer from <https://www.python.org/downloads/windows/> and install it.
Tick **Add python.exe to PATH** in the installer and keep the other defaults (tkinter is included by default).

**2. Build**, using either method:

Option A: one command in a WSL terminal (the VS Code terminal works too):

```bash
bash build_from_wsl.sh
```

It copies the source to `C:\Users\<you>\StockLedgerBuild`, uses the Windows Python to install PyInstaller and build,
then opens the `dist\StockLedger` folder containing `StockLedger.exe`.

Option B: copy `app.py ledger.py finance.py csv_export.py storage.py quotes.py ui.py i18n.py icon.ico build_exe.bat` to a folder on Windows and double-click `build_exe.bat`.

The first build downloads PyInstaller and takes about 1–2 minutes; later builds are much faster.

**3. Use the exe**

The build is a folder, `dist\StockLedger`: `StockLedger.exe` plus an `_internal` folder it needs (Python and Tk
are inside, so the PC does not need Python installed). A folder build starts faster than a single-file exe, which
would unpack itself to `%TEMP%` on every launch, and antivirus flags it far less often.

Copy the whole `StockLedger` folder somewhere permanent, e.g. `D:\StockLedger\`, and double-click `StockLedger.exe`
(right-click → *Send to → Desktop (create shortcut)* for a desktop icon).
Data is saved in a `data` folder next to the exe. To update, delete `StockLedger.exe` and `_internal`, copy in the
new ones, and leave the `data` folder alone. (Rebuilding never touches a `data` folder inside `dist\StockLedger`.)

## 4. Data and backups

- All data lives in one file: `data\stock_ledger.db`. Copying that file is a complete backup.
- The first time you open the app each day, it backs up automatically to `data\backups\`, keeping the last 30 days.
- **⋯ → Back up database** backs up to any location at any time (e.g. a cloud-synced folder).
- **⋯ → Export current account to CSV** exports three tables for the account (transactions, holdings and yearly totals), and with the
  Finance page on, **⋯ → Export finance to CSV** exports three for the finance sheet. They open directly in Excel; see
  [CSV files](#csv-files-for-analysis-and-for-checking-a-tax-return) for the columns.
- To bring data entered while testing in WSL over to the exe, copy `data/stock_ledger.db` into the `data` folder next to the exe.

## 5. Live prices

- The **Live** switch in the top bar turns automatic updates on or off (remembered between runs).
- Prices refresh every 10 seconds (`LIVE_INTERVAL` in `app.py`). The time of the last update is shown next to the switch.
- The **Day Change** column and the "Today" line on the **Total Assets** card show today's move versus the previous close.
- Data comes from Yahoo Finance. US stocks are near real time; some other exchanges are delayed up to 15 minutes.
  Outside trading hours the last close is shown.
- Symbols Yahoo doesn't know (e.g. CDs, private funds) are listed as "no quote"; enter their price with **Update prices**.
- Write share classes either way: `BRK.B` and `BRK-B` both work.
- Crypto is written as coin-USD: `BTC-USD`, `ETH-USD`, `SOL-USD` (searching "bitcoin" or "btc" finds it).
  Plain `BTC` is a different thing: a bitcoin ETF that trades on the stock market. Crypto trades around the clock.
- A new symbol (after a ticker change, or a new listing such as warrants) gets live prices as soon as Yahoo lists it;
  until then it shows "no quote" and is counted at cost, or you can enter its price with **Update prices**.
- If the internet is down, the last fetched prices are kept and the app retries automatically.

**The chart**

- The big number is your total assets (cash + holdings). Hover the chart to see the value at any time.
- 1D compares with the previous close (the dotted line). Other ranges show the gain or loss over the period
  with deposits and withdrawals left out, so adding cash doesn't count as a return.
- Past values are rebuilt from your transactions and Yahoo's daily closes. Splits you've recorded are taken into account.
- With two or more accounts, **All accounts** at the top of the account menu adds them up: net worth and chart, an
  **Accounts** tab with each account's cash, market value, share of the total and P/L (double-click one to open it),
  and **Holdings** merged by symbol (a stock held in two accounts is one row; average cost = total cost / total shares).
  This view is read-only: to add or edit transactions, pick one account. All amounts are in dollars; there is no currency conversion.
- Click a stock in the **Stocks** list (or double-click it in Holdings) to open its own page in place of the overview,
  with a price chart, your position and its transaction history. Click another stock in the list to switch to it;
  **Back** or `Esc` returns to the overview.
- **⋯ → Dark mode** switches between dark and light themes; **⋯ → Language / 语言** switches English / Chinese.

## 6. How to record things

| Situation | Record as |
|---|---|
| Cash already in the account when you start | Opening cash when creating the account (or a Deposit) |
| Stocks already held when you start | Opening positions when creating the account (or Shares In with the cost per share) |
| Transfer in from / out to the bank | Deposit / Withdrawal |
| Buy / sell stock | Buy / Sell (enter quantity, price and fee; cash updates automatically) |
| Cash dividend | Dividend (enter the amount) |
| Dividend reinvestment (DRIP) | A Dividend followed by a Buy |
| Interest on cash (e.g. SPAXX income) | Interest |
| Account fees, ADR fees, etc. | Fee |
| Stock split (4-for-1: 10 shares become 40) | Split, enter **30** (the shares added); total cost is unchanged |
| Reverse split | Split, enter a negative number |
| Stock transferred to another account | Shares Out (reduces the position at average cost, no P/L) |
| Ticker change, or shares converted in a merger | Symbol Change: old symbol, new symbol and the new shares received (press **All** for 1-for-1); the cost basis carries over, no P/L |
| Spin-off, or free warrants / rights handed out (e.g. 1 warrant per share) | Distribution: the stock, the new security's symbol, the number received and the percent of the stock's cost basis that moves to it (**0** if unknown; see below); no P/L |
| Buy / sell crypto | Buy / Sell with the symbol `BTC-USD` etc. |

**Cost basis uses the average cost method**: buys add their cost (including commissions); sells remove cost at the current average cost,
and realized P/L = sale proceeds − cost removed. Fractional shares are supported.

**Cost basis moved by a Distribution**: at 0% your total P/L stays right, but the warrants' whole value shows as their
gain while the stock keeps its full cost. If the company publishes a cost basis split (IRS Form 8937, e.g. "x% to the
warrants"), edit the Distribution and enter that percent: the stock's cost goes down and the warrants get that share.

Tips:
- `Ctrl+N` adds a transaction; in the Transactions tab, select one and press `Enter` to edit or `Delete` to delete
- Click a column header to sort. If the window is too narrow for all the columns, the table scrolls sideways
  (scroll bar under the table, or `Shift` + mouse wheel); if it is too short, the whole page scrolls up and down
  (scroll bar on the right, or the mouse wheel)
- In the Transactions tab, **Period** narrows the list to the past month, 3 or 6 months, the past year, a calendar year
  (the years that have transactions are listed) or **Custom range…**: type a start and/or end date (e.g. `2026-01-01`;
  leave one blank for no limit; a box with a date that cannot be read turns red). It combines with the Symbol and Type filters,
  and the cash balance column still shows the running balance of the whole account
- **Reset filters** (shown while any filter is on) only clears the filters; it never deletes transactions
- When selling, click **All** to fill in the current number of shares held
- Transactions on the same day are processed in the order they were entered

## Finance page (money outside your brokerage accounts)

This page is **optional**. Until you tick **⋯ → Finance page** it does not exist: no button, no extra tables in the database, and the
stock side looks and works exactly as before. Untick it to hide the page again; what you entered is kept.

With it on, a **Finance** button next to the account menu opens a month-by-month sheet of income and expenses that have nothing to do
with your stock accounts (salary, bank interest, credit card payments, taxes, ...). It is laid out like a spreadsheet: one row per month
with **Opening**, your income categories, **Total income**, your expense categories, **Total expenses** and **Ending balance**
(ending = opening + income − expenses). Each month opens with the previous month's ending balance, so the balance is the total
of all your bank accounts; you never list the individual accounts. **Back** or `Esc` returns to the stock view.

- **+ Add month** (or double-click a month to edit it): one row per category with an **amount** and a **comment**.
  An amount may be a sum such as `1250.50+1250.50` or `120.40+85.25-10.15`; the parts are kept and shown under the table.
  The first month needs an **Opening balance**; for later months leave it blank to continue from the month before
  (type a figure to correct it to what your bank says).
- **Comments**: every amount can carry a comment (several lines are fine). A **•** in front of an amount marks a cell with a comment;
  select the month to read the comments and sums in the box under the table.
- **Categories…**: add, rename, reorder and delete income and expense categories. Deleting one also deletes its amounts and comments.
- **Period** picks the months to look at: all time, the past 3 or 6 months, the past year (counting this month), any calendar year
  (the years that have months are listed), or **Custom range…** with a first and last month (`2026-01`; a whole date such as
  `2026-03-31` counts as its month; leave one blank for no limit; a box with something that cannot be read turns red).
  The table, the **Total** row, the numbers above the table and the **Totals for the period** box all follow it.
- **Totals for the period** lists what every income and expense category came to over the chosen months, with total income and
  total expenses, and the first and last month it covers -- for example choose a year, then check total income, interest income or taxes paid
  against your tax return.
- **All accounts view**: with the Finance page on and at least one month entered, the net worth there also counts the finance cash
  balance (the latest month's ending balance). A block above the chart shows the parts side by side: **Net worth (all accounts)** =
  **Stock accounts net worth** + **Finance cash balance**, and the **Stock accounts cash** (which is already part of the stock net worth,
  not added again). The chart and the figures under it are about the stock accounts only. With the page off, or one account
  selected, nothing changes.

## CSV files (for analysis and for checking a tax return)

Every file is one plain table: a header row, one record per row, and no blank lines, titles or total rows in between, so a spreadsheet
can filter, pivot and add it up as it is. Dates are `YYYY-MM-DD`, amounts are plain numbers (`1234.50`, no thousands separator), a cell
that does not apply to a row is left empty, and the column titles follow the interface language. Files are named
`<name>_<table>_<date>.csv` and saved as UTF-8 with a BOM, so Excel shows Chinese correctly. Everything is exported, every year:
use the **Year** column to pick a tax year.

**⋯ → Export current account to CSV** (one stock account; not available in the all-accounts view)

| Table | One row per | Columns |
|---|---|---|
| `transactions` | transaction, oldest first | Account, Date, Year, Type, Symbol, New Symbol, Quantity, Price, Cost Moved %, Fee, Amount, Cash Change, Cash Balance, Net Proceeds, Cost Sold, Realized P/L, Note |
| `holdings` | position (closed ones too), then the cash | Account, As Of, Symbol, Shares, Avg Cost, Cost Basis, Price, Market Value, Unrealized P/L, Realized P/L, Dividends |
| `yearly` | calendar year with transactions | Account, Year, Deposits, Withdrawals, Dividends, Interest, Fees, Commissions, Net Proceeds, Cost Sold, Realized P/L |

- **Amount** is what a deposit, withdrawal, dividend, interest or fee came to. **Cash Change** is how much the transaction moved the cash
  (negative = out) and **Cash Balance** what was left. A split's **Quantity** is the change in shares; a distribution's **Cost Moved %**
  is the share of the stock's cost basis handed to the new security (it is not a price).
- Only a sale has **Net Proceeds** = quantity × price − fee (the figure a 1099-B shows), **Cost Sold** = the average cost of the shares sold
  (a 1099-B's cost basis) and **Realized P/L** = Net Proceeds − Cost Sold. In `holdings`, **Cost Basis** is the cost of what you hold now.
- The last row of `holdings` is the cash (its **Market Value** is the cash balance), so the Market Value column adds up to the account's
  value; stocks without a price have no market value. Prices are the ones the app has on **As Of**, the day of the export.
- `yearly` is what to check against 1099-DIV (**Dividends**), 1099-INT (**Interest**) and 1099-B (**Net Proceeds**, **Cost Sold**,
  **Realized P/L**). **Fees** are account fees (Fee transactions); **Commissions** are the fees paid on buys and sells.
  The average cost method has no per-lot purchase dates, so this is not a Form 8949 by itself.

**⋯ → Export finance to CSV** (shown when the Finance page is on; expenses are positive numbers)

| Table | One row per | Columns |
|---|---|---|
| `monthly` | month | Year, Month, Opening, *your income categories*, Total income, *your expense categories*, Total expenses, Ending balance |
| `yearly` | calendar year with months | Year, Months, Opening, *your income categories*, Total income, *your expense categories*, Total expenses, Ending balance |
| `entries` | amount entered | Year, Month, Type (Income / Expense), Category, Amount, Calculation, Comment |

- `monthly` is the sheet as it looks on the page. `yearly` has the same columns, summed over the year: **Months** is the number of months
  entered (12 = the whole year), **Opening** is the first month's and **Ending balance** the last month's. A category without any amount
  that year is left empty.
- `entries` is the same data one amount per row, with the sum you typed (`4000+4000`) and the comment -- for pivoting by category,
  or to look up what a comment said (for example every payment marked as tax).

## 7. FAQ

**No window appears when running `python app.py` in WSL**
You need WSLg (built into Windows 11; Windows 10 needs a recent build). Run `wsl --update` in Windows PowerShell, then `wsl --shutdown` to restart WSL and try again.

**Fonts look tiny / pixelated in WSL, or some symbols show as `\u25be`**
Your Tk is the `noxft` build, which can't use real fonts on Linux. Switch to the `xft` build:
`conda install -n stockledger -c conda-forge "tk=8.6.*=xft*" xorg-libxft`.
This only affects display during development; the exe uses Segoe UI on Windows (Microsoft YaHei in Chinese).

**Windows Defender / antivirus flags the exe**
Unsigned programs built by PyInstaller are occasionally false positives (much less often for folder builds like
this one). Add the `StockLedger` folder as an exclusion in Defender. On first launch, SmartScreen may say
"Windows protected your PC": click *More info → Run anyway*.

**I want red for gains and green for losses**
Open `ui.py`, set `RED_UP = True` near the top, and rebuild. (The theme colors are in `PALETTES` in the same file.)

**Adding or changing interface text**
Write the English text in the code wrapped in `tr()`, e.g. `tr("Cash")` or `tr("{n} transactions", n=count)`,
and add the Chinese to the `ZH` table in `i18n.py`. `python test_ledger.py` fails if any text is missing a translation
or a translation's `{placeholders}` don't match.
