#!/usr/bin/env bash
# Weekly run, part 1 (before judging). Usage: ./run_weekly.sh   (needs APIFY_TOKEN in env)
set -euo pipefail
cd "$(dirname "$0")"
PY=${PY:-/workspace/venv/bin/python}
$PY 01_discover.py ${DISCOVER_ARGS:-}
$PY 02_transcripts.py ${TRANSCRIPT_ARGS:-}
$PY 03_candidates.py
echo "Judge queue ready: runs/$($PY -c 'import json;print(json.load(open("state/state.json"))["current_run"])')/judge_queue.json  -> write judgments.json, then ./finish_weekly.sh"
