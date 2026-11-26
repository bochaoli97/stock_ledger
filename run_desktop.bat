@echo off
setlocal
pushd "%~dp0desktop"
if errorlevel 1 exit /b 1
set ledger_exit=0
where node >nul 2>nul
if errorlevel 1 (
  echo Please install Node.js 24 LTS first.
  pause
  set ledger_exit=1
  goto finish
)
if not exist node_modules\vite (
  call npm ci
  if errorlevel 1 (
    set ledger_exit=1
    goto finish
  )
)
rem A checkout copied from WSL must install Windows-native dependencies.
node -e "const fs=require('fs');const p='node_modules/electron/path.txt';if(fs.existsSync(p)&&!fs.readFileSync(p,'utf8').trim().toLowerCase().endsWith('electron.exe'))process.exit(1)"
if errorlevel 1 (
  call npm ci
  if errorlevel 1 (
    set ledger_exit=1
    goto finish
  )
)
set ELECTRON_RUN_AS_NODE=
call npm run dev
set ledger_exit=%errorlevel%
:finish
popd
exit /b %ledger_exit%
