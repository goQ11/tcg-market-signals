#!/usr/bin/env python3
"""Step (d, return leg): validate runs/<run>/judgments.json against the schema in JUDGING.md
and merge into state/judged_all.json (keyed by item_id; later judgments overwrite earlier ones).
Usage: 04_merge_judgments.py [--run-id ID] [--allow-partial]"""
import sys, os, argparse
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from common import *
ap = argparse.ArgumentParser(); ap.add_argument("--run-id"); ap.add_argument("--allow-partial", action="store_true"); a = ap.parse_args()
run = a.run_id or current_run()
Q = load(f"runs/{run}/judge_queue.json"); J = load(f"runs/{run}/judgments.json")
if not J: raise SystemExit(f"missing runs/{run}/judgments.json")
items = {q["item_id"]: q for q in Q["items"]}
VIBES = {"positive", "neutral", "negative", "none"}; ACTIONS = {"ban", "unban", "restrict", "dont_ban"}
STANCES = {"for", "against", "predicts", "reports"}; EFFECTS = {"stronger", "weaker"}
FORMATS = {"standard", "pioneer", "modern", "legacy", "vintage", "pauper", "commander", "cedh", "historic", "timeless", "brawl", "alchemy", "oldschool", "other"}
errs = []; ok = {}
def need(c, msg): 
    if not c: errs.append(msg)
if J.get("schema") != "msp.judgments/1": errs.append("schema must be 'msp.judgments/1'")
for k, j in enumerate(J.get("judgments", [])):
    w = f"judgments[{k}]"
    iid = j.get("item_id"); need(iid in items, f"{w}: unknown item_id {iid}")
    need(j.get("vibe") in VIBES, f"{w}: vibe must be one of {sorted(VIBES)}")
    need(isinstance(j.get("card_ok"), bool), f"{w}: card_ok must be bool")
    pot = j.get("potential", {"rise": False}); need(isinstance(pot.get("rise"), bool), f"{w}: potential.rise must be bool")
    q = j.get("quote", ""); need(len(q.split()) < 20, f"{w}: quote must be under 20 words")
    if j.get("bans") or j.get("pairs"):
        need(len(q.split()) >= 3, f"{w}: ban/impact claims need a quote (3-19 words copied from the snippet) so the timestamp can be anchored")
    for b in j.get("bans", []) or []:
        need(b.get("card"), f"{w}: ban.card required"); need(b.get("action") in ACTIONS, f"{w}: ban.action invalid")
        need(b.get("stance") in STANCES, f"{w}: ban.stance invalid"); need(b.get("format") in FORMATS, f"{w}: ban.format invalid")
    for pr in j.get("pairs", []) or []:
        need(pr.get("new_card") and pr.get("existing_card"), f"{w}: pair cards required"); need(pr.get("effect") in EFFECTS, f"{w}: pair.effect invalid")
    if iid in items: ok[iid] = dict(j, _item=items[iid], _run=run)
missing = set(items) - set(ok)
if missing and not a.allow_partial: errs.append(f"{len(missing)} queue items have no judgment (use --allow-partial to accept)")
if errs:
    for e in errs[:40]: log("ERROR", e)
    raise SystemExit(f"{len(errs)} validation errors; nothing merged")
allj = load("state/judged_all.json", {}); allj.update(ok); save("state/judged_all.json", allj)
vids = load("state/videos_all.json", {}); vids.update({v["id"]: v for v in load(f"runs/{run}/videos.json")}); save("state/videos_all.json", vids)
st = load("state/state.json", {}); st["seen_video_ids"] = sorted(set(st.get("seen_video_ids", [])) | {v["id"] for v in load(f"runs/{run}/videos.json")})
st["last_run_at"] = max([st.get("last_run_at") or ""] + [Q["generated_at"][:10]]); st.setdefault("runs", []).append(run) if run not in st.get("runs", []) else None; save("state/state.json", st)
log(f"merged {len(ok)} judgments from {run} ({len(missing)} unjudged); store now {len(allj)}")
