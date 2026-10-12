#!/usr/bin/env bash
# Weekly run, part 2 (after judgments.json exists). Usage: ./finish_weekly.sh [--allow-partial]
# Builds out/signals.json, validates every quote, then runs the publish gate against the live file.
# Nothing is published here; run ./publish.sh afterwards (it re-runs the gate).
set -euo pipefail
cd "$(dirname "$0")"
PY=${PY:-/workspace/venv/bin/python}
$PY 04_merge_judgments.py "$@"
$PY 05_aggregate.py
$PY 06_validate.py out/signals.json --report out/validation.json   # fails the run if any quote isn't near its timestamp
curl -sf --retry 4 https://raw.githubusercontent.com/goQ11/tcg-market-signals/main/signals.json -o out/published_prev.json
$PY gate.py out/signals.json out/published_prev.json --report out/gate.json
echo "out/signals.json passed validation + publish gate. Publish with ./publish.sh"
