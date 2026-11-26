#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/desktop"
ledger_node="$(command -v node || true)"
if [[ -z "$ledger_node" ]]; then
  for ledger_candidate in "$HOME"/.vscode-server/bin/*/node "$HOME"/.vscode-server/cli/servers/*/server/node; do
    if [[ -x "$ledger_candidate" ]]; then ledger_node="$ledger_candidate"; break; fi
  done
fi
if [[ -z "$ledger_node" ]]; then
  echo 'Install Node.js 24 LTS, then run npm --prefix desktop ci from the repository root.' >&2
  exit 1
fi
if [[ ! -d node_modules/vite ]]; then
  echo 'Install dependencies first: npm --prefix desktop ci' >&2
  exit 1
fi
unset ELECTRON_RUN_AS_NODE
exec "$ledger_node" scripts/dev.mjs
