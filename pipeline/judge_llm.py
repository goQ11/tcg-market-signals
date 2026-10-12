#!/usr/bin/env python3
"""Automated judge for runs/<run>/judge_queue.json -> runs/<run>/judgments.json (contract: JUDGING.md, msp.judgments/1).
Replaces the manual "assistant judges in its routine" step so the pipeline can run unattended in GitHub Actions.
Calls any OpenAI-compatible /chat/completions endpoint:
  env LLM_API_KEY (secret), LLM_BASE_URL (e.g. the provider's .../v1), LLM_MODEL (model name).
Items are judged in batches with retries; an item that still fails is left out (04 runs with --allow-partial),
and the run aborts if more than 10% of items are missing. Exit code 3 = judge not configured."""
import sys, os, json, time, random
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from common import *
KEY, BASE, MODEL = os.environ.get("LLM_API_KEY"), os.environ.get("LLM_BASE_URL"), os.environ.get("LLM_MODEL")
if not (KEY and BASE and MODEL):
    log("judge not configured (need LLM_API_KEY secret + LLM_BASE_URL and LLM_MODEL variables)"); sys.exit(3)
run = current_run(); Q = load(f"runs/{run}/judge_queue.json")
RULES = open(p("JUDGING.md")).read()
SYSTEM = ("You judge Magic: The Gathering YouTube caption snippets for a price-signals feed. Follow these rules exactly and answer with "
          "JSON only: {\"judgments\": [ ... one object per input item_id ... ]}. Each object has item_id, card_ok, card (optional), vibe, "
          "potential{rise,reason}, bans[], pairs[], quote, confidence. Quotes must be 3-19 words copied verbatim from the item's context.\n\n" + RULES +
          f"\n\nnew_card_since = {SETTINGS['new_card_since']}")
BATCH = int(os.environ.get("JUDGE_BATCH", "25"))
def call(items):
    body = {"model": MODEL, "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": json.dumps({"videos": {i["video_id"]: Q["videos"].get(i["video_id"]) for i in items}, "items": items}, ensure_ascii=False)}]}
    r = json.loads(fetch(BASE.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), method="POST", timeout=180, tries=4, base=5, secret=True,
                         headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"}))
    txt = r["choices"][0]["message"]["content"].strip()
    if txt.startswith("```"): txt = txt.strip("`").split("\n", 1)[1]
    return json.loads(txt)["judgments"]
out = {}; items = Q["items"]
for k in range(0, len(items), BATCH):
    chunk = items[k:k + BATCH]; want = {i["item_id"] for i in chunk}
    for attempt in range(3):
        try:
            for j in call([i for i in chunk if i["item_id"] not in out]):
                if j.get("item_id") in want:
                    j.setdefault("potential", {"rise": False, "reason": None}); j.setdefault("bans", []); j.setdefault("pairs", []); j.setdefault("quote", "")
                    if not (j.get("bans") or j.get("pairs")) or len(j["quote"].split()) >= 3: out[j["item_id"]] = j
            if want <= set(out): break
        except Exception as e: log(f"batch {k // BATCH}: attempt {attempt + 1} failed: {redact(e)[:200]}")
        time.sleep(3 * 2 ** attempt + random.random())
    log(f"judged {len(out)}/{len(items)}")
missing = len(items) - len(out)
save(f"runs/{run}/judgments.json", {"schema": "msp.judgments/1", "run_id": run, "judge": f"llm:{MODEL}", "judgments": list(out.values())})
if items and missing / len(items) > 0.10: raise SystemExit(f"{missing}/{len(items)} items unjudged (>10%)")
log(f"wrote judgments.json ({missing} items unjudged)")
