#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")/.."
if ! command -v uv >/dev/null && [ -x "$HOME/.local/bin/uv" ]; then
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null || { echo 'Install uv from https://docs.astral.sh/uv/ first.'; exit 1; }
command -v node >/dev/null || { echo 'Install Node.js 22 or later first.'; exit 1; }
uv sync --frozen
if [ ! -d web/node_modules ]; then (cd web && npm ci); fi
(cd web && npm run build)
echo 'AgentProof is available at http://127.0.0.1:8010'
exec .venv/bin/uvicorn agentproof.api:app --host 127.0.0.1 --port 8010
