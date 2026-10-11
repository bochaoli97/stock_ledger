@echo off
setlocal
cd /d "%~dp0"
echo === Stock Ledger: build Windows exe ===

rem --- find Windows Python (the python.org installer provides the "py" launcher) ---
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto :nopython
%PY% -c "import tkinter" >nul 2>nul || goto :nopython

rem --- separate virtual environment just for building ---
if not exist ".venv-win\Scripts\python.exe" (
    echo Creating virtual environment .venv-win ...
    %PY% -m venv .venv-win || goto :fail
)
echo Installing PyInstaller ...
".venv-win\Scripts\python.exe" -m pip install --upgrade --quiet pip pyinstaller || goto :fail

rem --- build as a folder (--onedir): starts faster than a single-file exe, which has to unpack
rem     itself to %TEMP% on every launch, and is flagged by antivirus far less often ---
rem PyInstaller wipes its output folder on every build, and the app keeps its data folder next to
rem the exe, so build into build\dist first and then sync into dist\StockLedger leaving data alone.
echo Building ...
".venv-win\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed ^
    --distpath build\dist --name StockLedger --icon icon.ico --add-data "icon.ico;." app.py || goto :fail

echo Updating dist\StockLedger (the data folder is kept) ...
robocopy "build\dist\StockLedger" "dist\StockLedger" /MIR /XD data /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :fail

echo.
echo Done: %cd%\dist\StockLedger\StockLedger.exe
echo Copy the whole StockLedger folder wherever you like; run StockLedger.exe inside it.
goto :end

:nopython
echo [ERROR] Windows Python with tkinter was not found.
echo         Install Python from https://www.python.org/downloads/windows/
echo         and tick "Add python.exe to PATH" in the installer.
goto :end

:fail
echo.
echo [ERROR] Build failed, see the messages above.

:end
if /i not "%~1"=="nopause" pause
endlocal
