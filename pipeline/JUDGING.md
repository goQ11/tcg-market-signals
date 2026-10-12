# AI judging handoff (msp.judgments/1)

Step 03 writes `runs/<run_id>/judge_queue.json`. The judge (the assistant, in its scheduled routine) reads it and writes
`runs/<run_id>/judgments.json`. Step 04 validates that file and merges it.

## Input: judge_queue.json
```json
{ "schema": "msp.judge_queue/1", "run_id": "2026-10-16_0900", "generated_at": "...",
  "videos": { "<video_id>": {"channel": "@TogoresMTG", "title": "...", "published": "..."} },
  "items": [
    { "item_id": "a1b2c3d4e5f6", "kind": "mention", "video_id": "...", "channel": "@...", "card": "Exact Scryfall Name",
      "match": "exact|alias|fuzzy|phonetic|common-gated", "t": 1452, "stream": "transcript|metadata",
      "context": "about 35 normalized words around the card" },
    { "item_id": "...", "kind": "ban_line", "video_id": "...", "channel": "@...", "card": null,
      "cards_in_context": ["..."], "t": 57, "stream": "transcript", "context": "the raw caption lines around a ban/restrict word" }
  ] }
```

## Output: judgments.json (exactly one entry per item_id)
```json
{ "schema": "msp.judgments/1", "run_id": "<same run_id>", "judge": "Grok Bot",
  "judgments": [
    { "item_id": "a1b2c3d4e5f6",
      "card_ok": true,
      "card": null,
      "vibe": "positive",
      "potential": {"rise": false, "reason": null},
      "bans":  [ {"card": "Dispatch", "action": "ban", "stance": "predicts", "format": "pauper", "quote": "optional, <20 words"} ],
      "pairs": [ {"new_card": "Liliana the Faultless", "existing_card": "Mox Amber", "effect": "stronger", "format": "modern"} ],
      "quote": "short supporting quote, under 20 words",
      "confidence": "high" } ] }
```
| field | rule |
|---|---|
| card_ok | `false` if the matched words are not really that card (an idiom, a different card, or garbled text). Then use vibe `none`. |
| card | optional exact Scryfall name to replace a wrong but fixable match (for example the right Emrakul) |
| vibe | `positive`, `neutral`, `negative`, or `none`. It must be about **this card itself**, not a nearby card. Play-by-play narration ("I cast X, pass") is `none`. |
| potential.rise | `true` only if the speaker suggests demand or price will rise (spiking, pick it up, breakout, starting to see play). Give a reason under 15 words. |
| bans[] | action is `ban`, `unban`, `restrict`, or `dont_ban`. stance is `for`, `against`, `predicts`, or `reports`. format is one of standard, pioneer, modern, legacy, vintage, pauper, commander, cedh, historic, timeless, brawl, alchemy, oldschool, other. For `ban_line` items, name the card in `bans[].card`. If the line isn't a real call, leave it `[]`. |
| pairs[] | new_card is a card printed since `settings.new_card_since`. effect is `stronger` (synergy or combo) or `weaker` (replaced or outclassed). |
| quote | under 20 words. Taken from the context (light cleanup of caption errors allowed). |
| confidence | `high`, `medium`, or `low` |

Validate and merge: `python 04_merge_judgments.py`. Add `--allow-partial` if some items were skipped. If any entry is invalid, nothing is merged and the errors are listed.

Quotes: copy 3-19 words verbatim from the snippet. Ban and pair judgments without a quote are rejected by
04_merge_judgments.py, because the quote is what anchors the video timestamp.
