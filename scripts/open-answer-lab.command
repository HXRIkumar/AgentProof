#!/bin/zsh
set -eu
cd "$(dirname "$0")/.."
if ! command -v uv >/dev/null 2>&1; then
  print 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/'
  exit 1
fi
exec uv run --extra embeddings --with mlx-lm==0.32.2 python scripts/start_answer_lab.py
