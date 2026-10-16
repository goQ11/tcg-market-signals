#!/usr/bin/env bash
# Publish out/signals.json to goQ11/tcg-market-signals main ONLY if the publish gate passes against the live file.
# On gate failure the live signals.json is left untouched (last good list stays up). Usage: ./publish.sh
set -euo pipefail
cd "$(dirname "$0")"
PY=${PY:-/workspace/venv/bin/python}
REPO=${REPO:-/workspace/tcg-market-signals}
curl -sf --retry 4 https://raw.githubusercontent.com/goQ11/tcg-market-signals/main/signals.json -o out/published_prev.json
$PY gate.py out/signals.json out/published_prev.json --report out/gate.json || { echo "GATE FAILED: not publishing; live signals.json unchanged"; exit 1; }
WT=$(mktemp -d); git -C "$REPO" fetch -q origin main
git -C "$REPO" worktree add -q "$WT" origin/main
cp out/signals.json "$WT/signals.json"
RUN=$($PY -c 'import json;print(json.load(open("out/signals.json"))["run_id"])')
(cd "$WT" && git add signals.json && git commit -qm "Weekly Market Signals update $(date +%F) (run $RUN)" && git push -q origin HEAD:main)
git -C "$REPO" worktree remove --force "$WT"
echo "Published run $RUN"
