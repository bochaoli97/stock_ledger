#!/usr/bin/env bash
# Run Windows-native packaging from WSL without sharing Linux node_modules.
set -euo pipefail

usage() {
  cat <<'HELP'
Usage: bash build_windows.sh [options]

Build a standalone Windows application from WSL. The default runs all tests,
builds the bundled Python service and Electron app, smoke-tests the exe, and
creates desktop/release/StockLedger-Windows-<arch>.zip.

Options:
  --skip-tests       Skip unit and development-window tests (exe smoke test stays).
  --require-gpu      Require hardware GPU compositing during Windows validation.
  --python PATH      Use this Windows Python executable (Windows or WSL path).
  --work-dir PATH    Reuse an isolated Windows build directory (Windows path).
  -h, --help         Show this help.

Requires Windows Python 3.12+ and WSL Windows interoperability. Node.js 24 is
downloaded and checksum-verified automatically if a suitable version is missing.
HELP
}

arguments=()
while (($#)); do
  case "$1" in
    --skip-tests) arguments+=(-SkipTests); shift ;;
    --require-gpu) arguments+=(-RequireGpu); shift ;;
    --python|--work-dir)
      option="$1"
      if (($# < 2)) || [[ -z "$2" || "$2" == --* ]]; then
        printf 'Missing value for %s\n' "$option" >&2; exit 2
      fi
      value="$2"
      if [[ "$value" == /* ]]; then
        value="$(wslpath -w "$value")"
      fi
      if [[ "$option" == --python ]]; then arguments+=(-WindowsPython "$value")
      else arguments+=(-WorkDirectory "$value"); fi
      shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

if ! command -v wslpath >/dev/null 2>&1; then
  printf 'Run this script inside WSL with Windows interoperability enabled.\n' >&2
  exit 1
fi
powershell_path="$(command -v powershell.exe || true)"
if [[ -z "$powershell_path" ]]; then
  powershell_path=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
fi
if [[ ! -f "$powershell_path" ]]; then
  printf 'Windows PowerShell was not found. Enable WSL Windows interoperability.\n' >&2
  exit 1
fi
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
windows_script="$(wslpath -w "$project_root/desktop/scripts/build-windows.ps1")"
printf 'Building Windows app using native Windows tools…\n'
"$powershell_path" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass \
  -File "$windows_script" "${arguments[@]}"
printf '\nWindows archive: %s/desktop/release/StockLedger-Windows-<arch>.zip\n' "$project_root"
printf 'Build report: %s/desktop/test-results/windows-native/report.json\n' "$project_root"
