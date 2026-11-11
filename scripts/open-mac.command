#!/bin/bash
set -eu
cd "$(dirname "$0")/.."
if curl --max-time 2 -fsS http://127.0.0.1:8010/api/ready >/dev/null 2>&1; then
  open http://127.0.0.1:8010
  exit 0
fi
if curl --max-time 2 -fsS http://127.0.0.1:8010/api/health >/dev/null 2>&1; then
  echo 'AgentProof is responding but not ready. Check its server log and http://127.0.0.1:8010/api/ready.'
  exit 1
fi
echo 'Starting AgentProof. Leave this Terminal window open while using the application.'
./scripts/start.sh &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT INT TERM
for attempt in {1..120}; do
  if curl --max-time 2 -fsS http://127.0.0.1:8010/api/ready >/dev/null 2>&1; then
    open http://127.0.0.1:8010
    wait "$server_pid"
    exit 0
  fi
  kill -0 "$server_pid" 2>/dev/null || { wait "$server_pid"; exit 1; }
  sleep 1
done
echo 'Startup is taking longer than expected; check the log above.'
wait "$server_pid"
