#!/usr/bin/env bash
# Unattended weekly run (GitHub Actions or local). Never publishes unless PUBLISH=1.
#   01 discover -> 02 transcripts -> 03 candidates -> judge_llm -> 04 merge -> 05 aggregate -> 06 validate -> gate
# Output: pipeline/out/signals.json (+ out/gate.json). Exit codes: 0 ok, 3 judge not configured, other = failure.
# Env: YOUTUBE_API_KEY (optional), APIFY_TOKEN (optional), LLM_API_KEY/LLM_BASE_URL/LLM_MODEL (judge), PREV_SIGNALS (default ../signals.json)
set -euo pipefail
cd "$(dirname "$0")"
PY=${PY:-python3}
mkdir -p cache state
UA="TCGSellerHub-MarketSignals/1.0"
[ -s cache/cardnames.json ] || curl -sf --retry 4 -A "$UA" https://api.scryfall.com/catalog/card-names -o cache/cardnames.json
for f in keyword-abilities:kw keyword-actions:ka ability-words:aw; do
  [ -s "cache/${f##*:}.json" ] || { curl -sf --retry 4 -A "$UA" "https://api.scryfall.com/catalog/${f%%:*}" -o "cache/${f##*:}.json"; sleep 0.2; }
done
$PY 01_discover.py ${DISCOVER_ARGS:-}
$PY 02_transcripts.py ${TRANSCRIPT_ARGS:-}
$PY 03_candidates.py
set +e; $PY judge_llm.py; rc=$?; set -e
if [ $rc -eq 3 ]; then echo "::warning::Judge not configured; stopped before publishing. Queue is in runs/<run>/judge_queue.json"; [ "${ALLOW_NO_JUDGE:-0}" = 1 ] && exit 0; exit 3; fi
[ $rc -eq 0 ] || exit $rc
$PY 04_merge_judgments.py --allow-partial
$PY 05_aggregate.py ${AGGREGATE_ARGS:-}
$PY 06_validate.py out/signals.json --report out/validation.json
$PY gate.py out/signals.json "${PREV_SIGNALS:-../signals.json}" --report out/gate.json
echo "Candidate out/signals.json passed validation and the publish gate."
