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
- Dark/light themes, English/Chinese, text size, database backups, and actual GPU diagnostics.
- CSV export on account and Finance pages, with all-time, recent, yearly, and custom date/month ranges. Activity and Finance exports inherit the page's time filter. Opening balances and costs still include earlier history; historical holdings leave unavailable market prices blank.

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

## Build Windows from WSL

Install **Windows Python 3.12+** with pip and venv, enable WSL Windows interoperability, and run from the repository root:

```bash
bash build_windows.sh
```

The script calls native Windows PowerShell and Python, copies only source files into a Windows temporary directory, creates an isolated Python environment, installs dependencies, runs the tests, builds the Python service and Electron app, and smoke-tests the resulting exe. A suitable Windows Node.js 24+ is used if available; otherwise an official portable Node.js download is checksum-verified. Linux `node_modules` and ledger data are excluded from the build copy.

The verified archive is `desktop/release/StockLedger-Windows-x64.zip` (or `-arm64.zip` on ARM64). Extract the entire archive and open `StockLedger/Stock Ledger.exe`; the destination computer needs neither Node.js nor Python. Keep all bundled files beside the exe. Copy an existing `data` folder beside it to reuse your ledger.

```bash
# Explicit Windows Python, accepting a Windows path or WSL-mounted path
bash build_windows.sh --python '/mnt/c/path/to/python.exe'

# Reuse a dedicated build directory and download caches
bash build_windows.sh --work-dir 'C:\Users\your-name\AppData\Local\Temp\StockLedgerBuild'

# Skip unit/development-window tests; the packaged exe is still smoke-tested
bash build_windows.sh --skip-tests

# Also require hardware GPU compositing
bash build_windows.sh --require-gpu
```

Build reports, per-step logs and screenshots are saved to `desktop/test-results/windows-native/`; `report.json` includes the executable path and archive SHA-256. A reusable work directory must be empty or already marked by this build script. Failures return a nonzero exit code. If Windows Python is not found, use `--python`; if `powershell.exe` cannot start, check WSL interoperability. Initial dependency downloads require Windows network access.

This uses [WSL Windows interoperability](https://learn.microsoft.com/en-us/windows/wsl/filesystems) because [PyInstaller requires the target operating system](https://www.pyinstaller.org/en/stable/). For NSIS/portable installers, install PyInstaller on Windows and run `npm --prefix desktop ci` followed by `npm --prefix desktop run package`. Linux and macOS bundles are built on their respective operating systems. See [README.zh-CN.md](README.zh-CN.md) for the detailed Chinese build guide and [desktop/README.md](desktop/README.md) for architecture and native Windows validation.

The obsolete Qt frontend and its build scripts have been removed. Business tests remain headless; frozen animation reference data retain the original scroll behavior without a Qt dependency.
