#!/usr/bin/env bash
# Build the Windows exe from WSL with one command:
#   1. copy the source to %USERPROFILE%\StockLedgerBuild on Windows
#   2. run build_exe.bat with the Windows Python
# Why not build inside WSL? PyInstaller cannot cross-compile: building on Linux produces
# a Linux program, so a .exe has to be built with the Windows version of Python.
set -euo pipefail
cd "$(dirname "$0")"

WIN_PROFILE=$(cd /mnt/c && cmd.exe /c "echo %USERPROFILE%" | tr -d '\r')
BUILD_DIR="$(wslpath "$WIN_PROFILE")/StockLedgerBuild"
mkdir -p "$BUILD_DIR"
cp app.py ledger.py finance.py csv_export.py storage.py quotes.py ui.py i18n.py icon.ico build_exe.bat "$BUILD_DIR/"
echo "Source copied to $WIN_PROFILE\\StockLedgerBuild"

cd "$BUILD_DIR"
cmd.exe /c build_exe.bat nopause

if [ -f "$BUILD_DIR/dist/StockLedger/StockLedger.exe" ]; then
    echo
    echo "Build complete: $WIN_PROFILE\\StockLedgerBuild\\dist\\StockLedger\\StockLedger.exe"
    explorer.exe "$(wslpath -w "$BUILD_DIR/dist/StockLedger")" || true
fi
