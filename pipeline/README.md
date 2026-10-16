# Market Signals pipeline

A weekly job that turns MTG YouTube videos from 16 creators into one public `signals.json`. Every copy of TCG Seller Hub downloads that file. This folder is outside the private app repo on purpose.

## Setup (once)
```bash
python3 -m venv /workspace/venv && /workspace/venv/bin/pip install -r requirements.txt
curl -s -A "TCGSellerHub/1.0" https://api.scryfall.com/catalog/card-names -o cache/cardnames.json
for f in keyword-abilities:kw keyword-actions:ka ability-words:aw; do curl -s -A "TCGSellerHub/1.0" https://api.scryfall.com/catalog/${f%%:*} -o cache/${f##*:}.json; done
# optional, enables 7- and 30-day price change (~1 GB, refresh weekly):
curl -s -o cache/AllPrices.json.xz https://mtgjson.com/api/v5/AllPrices.json.xz
export APIFY_TOKEN=...   # never commit, print, or log it
```

## Weekly run
```bash
./run_weekly.sh        # 01 discover new videos -> 02 Apify transcripts -> 03 judge_queue.json
# AI judge writes runs/<run_id>/judgments.json  (format in JUDGING.md)
./finish_weekly.sh     # 04 validate + merge judgments -> 05 aggregate -> out/signals.json
```

| Step | Script | Reads | Writes |
|---|---|---|---|
| a | `01_discover.py [--since D] [--run-id ID]` | config/channels.json, YouTube RSS, state/state.json | runs/<id>/videos.json, state.current_run |
| b | `02_transcripts.py` | APIFY_TOKEN (header only), cache/transcripts/ | cache/transcripts/<video>.json, runs/<id>/transcripts_report.json (coverage, real cost) |
| c, d | `03_candidates.py` | lib/matcher.py, config/blocklist.json, config/aliases.json | runs/<id>/judge_queue.json |
| d | `04_merge_judgments.py [--allow-partial]` | runs/<id>/judgments.json | state/judged_all.json, state/videos_all.json, marks videos as seen |
| g | `06_validate.py [out/signals.json] [--report F]` | out/signals.json, cache/transcripts | exit 1 if any source has t=0 (quote not at start), an empty/short quote, a quote not said within ±15 s of t, or the card not said near t |
| e, f | `05_aggregate.py [--as-of D] [--no-history]` | state/*, Scryfall, config/official_bans.json, cache/AllPrices.json.xz | out/signals.json, out/archive/signals-<date>.json |

- **Spend:** the Apify actor `automationnation~youtube-transcript-scraper` costs $0.0015 per transcript. Each run is hard-capped at `apify_max_charge_usd_per_run` (passed to Apify as `maxTotalChargeUsd`). About 80 videos a week costs about $0.12.
- **After each Wizards ban announcement:** update `config/official_bans.json`. Scryfall legality is checked automatically.
- **Matcher:** new caption mangles go in `config/aliases.json`; new false-positive words go in `config/blocklist.json`.
- **Affiliate link:** set `affiliate_param` in `config/settings.json`. The placeholder is `partner=__TCGPLAYER_AFFILIATE_ID__`.
- **First run:** `tools_bootstrap_from_v3.py prepare|convert` seeded run `2026-10-09_bootstrap` from the v3 prototype.

## signals.json (schema_version 1.4.0)
Top-level fields: `schema_version`, `generated_at`, `run_id`, `window{start,end,days}`, `ban_announcements{last,next}`, `counts`, `disclaimers[]`, `affiliate_disclosure`,
`ban_alerts[]`, `impact_pairs[]`, `card_vibes[]`, `potential_risers[]`, `sources[]`.
- **Each source citation:** `{channel, channel_name, video_id, video_title, published, t, url (with &t=), quote (<20 words)}`.
- **ban_alerts status values:** `speculation`, `confirmed`, `already_banned`, `not_applicable`, or `unofficial_format`.
- **Printing fields (additive; 1.1.0, reprint logic changed in 1.2.0; 1.3.0 removed `is_new`, added `reserved`; 1.4.0 added `paper_sets`):** on every `ban_alerts[]`, `card_vibes[]` and
  `potential_risers[]` entry, and inside `impact_pairs[].new_card_info` / `existing_card_info`:
  `reserved` (bool), `first_printed` (YYYY-MM-DD), `first_printed_set {code,name}`, `is_reprint` (bool), `reprint_count` (int), `paper_sets` (distinct paper set names, oldest first),
  `latest_reprint_set {code,name}|null`, `latest_reprint_date` (YYYY-MM-DD|null). `reprint_set`/`reprint_released` are
  kept as aliases of the latest_* fields for 1.1 readers.
  - **Reserved List (`reserved`):** Scryfall's `reserved` flag: the card is on Wizards' Reserved List and will never be reprinted.
  - **Reprint (`is_reprint`):** printed in more than one distinct paper set, at any time. `reprint_count` = number of distinct
    paper sets. Counted: expansions, core sets, Commander, Masters, Special Guests, Secret Lair, etc. Not counted
    (`lib/common.py: eligible_paper`): digital-only (Arena/MTGO), promos, The List / Mystery Booster list printings, tokens,
    art series. A card can be both New and Reprint (new card already reprinted).
  - Data comes from Scryfall `unique=prints` searches (paginated, rate-limited, cached in `cache/scry_cache.json`, refreshed weekly).
- **Versioning:** breaking changes bump the major version. The app ignores files whose major version is newer than it supports.

## Timestamps and quotes
`05_aggregate.py` never copies the judge's quote straight into signals.json. For every source it calls
`lib/anchor.py`, which finds where the claim is said in the cached captions (judge quote fuzzy-matched near the
item's time, else the card mention nearest it; for description-only items, the place both cards are said together),
then emits a verbatim caption quote (<20 words) and `t = segment_start - 3` (min 0). The judge's wording is kept as
`judge_note`. If the captions don't support the claim, the source is dropped and logged to `out/needs_review.json`;
a claim with no remaining sources is dropped. Spoken forms used only for locating cards (e.g. "lily", "her as a saga")
live in `config/anchor_aliases.json`. `finish_weekly.sh` runs `06_validate.py` last, so a bad link fails the run.
