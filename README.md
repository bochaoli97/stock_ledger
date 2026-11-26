# Stock Ledger

**English** | [简体中文](README.zh-CN.md)

A local investment ledger built with **React, TypeScript, and Electron**, backed by the existing Python Decimal calculations and SQLite storage.

## Windows application

Download the [Windows x64 archive](desktop/release/StockLedger-Windows-x64.zip), extract the entire folder, and open `Stock Ledger.exe`. No separate Python or Node.js installation is required.

To use an existing ledger, copy its `data` folder beside the executable. The database is `data/stock_ledger.db`; daily backups are in `data/backups/`.

## Features

- Multiple accounts, opening cash and positions, combined account view.
- Twelve transaction types, editing and deletion, exact cost and profit calculations.
- Stocks and cryptocurrencies, live quotes, historical charts, portfolio and stock detail pages.
- Independent numeric reels with continuous retargeting and animated width changes; amounts support text selection and copying.
- Optional monthly income and expenses, formulas, carried balances, categories, and multiline comments.
- Dark/light themes, English/Chinese, text size, CSV exports, database backups, and actual GPU diagnostics.

## Development

Requires Node.js 24 LTS and Python 3.12+. The Python runtime uses only the standard library.

```bash
npm --prefix desktop ci
npm --prefix desktop run dev
```

Alternatively, run `run_desktop.bat` on Windows or `bash run_desktop.sh` on Linux/WSL. Development uses the existing repository database. Set `STOCK_LEDGER_DB` for another database and `STOCK_LEDGER_PYTHON` for another interpreter.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
npm --prefix desktop test
npm --prefix desktop run build
npm --prefix desktop run test:browser
```

Install PyInstaller on the target OS, then run `npm --prefix desktop run package` to build a standalone application. See [desktop/README.md](desktop/README.md) for architecture, animation contracts, packaging, and native Windows GPU validation.

The obsolete Qt frontend and its build scripts have been removed. Business tests remain headless; frozen animation reference data retain the original scroll behavior without a Qt dependency.
