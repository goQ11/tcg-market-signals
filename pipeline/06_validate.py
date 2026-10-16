#!/usr/bin/env python3
"""Validate every source in a signals file against the cached transcripts. Exit 1 on any failure.
Checks: t>0 (unless the quote is in the first 15s), quote non-empty and <20 words, quote found within
±15s of t (fuzzy), and every card of the claim mentioned within 30s.
Usage: 06_validate.py [path] [--report out/validation.json]"""
import sys, os, json, argparse
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from common import *
import anchor
ap = argparse.ArgumentParser(); ap.add_argument("path", nargs="?", default="out/signals.json"); ap.add_argument("--report"); a = ap.parse_args()
S = load(a.path); AL = anchor.load_aliases()
def entries():
    for b in S["ban_alerts"]: yield "ban_alerts", [b["card"]], f"{b['action']} ({b['stance']}) in {b['format']}", b["sources"]
    for pr in S["impact_pairs"]: yield "impact_pairs", [pr["new_card"], pr["existing_card"]], f"makes existing {pr['effect']}", pr["sources"]
    for v in S["card_vibes"]: yield "card_vibes", [v["card"]], f"vibe {v['vibe']}", v["sources"]
    for r in S["potential_risers"]: yield "potential_risers", [r["card"]], "potential to rise: " + "; ".join(r.get("reasons") or []), r["sources"]
rows = []
for sec, cards, claim, srcs in entries():
    for s in srcs:
        W = anchor.words(s["video_id"]); errs = []
        q = (s.get("quote") or "").strip()
        if not q: errs.append("empty quote")
        elif len(q.split()) >= 20: errs.append("quote >= 20 words")
        elif len(q.split()) < 5: errs.append("quote too short to verify (<5 words)")
        if not W: errs.append("no transcript")
        else:
            ok, sc = anchor.quote_near(W, q, s["t"], need=85) if q else (False, 0)
            if q and not ok: errs.append(f"quote not near t (best {sc:.0f})")
            if s["t"] <= 0 and not (q and anchor.best_span(W, q, 0, 15)[0] >= 80): errs.append("t=0")
            if not anchor.cards_near(W, cards, s["t"], AL): errs.append("card not mentioned near t")
        rows.append(dict(section=sec, cards=cards, claim=claim, channel=s["channel_name"], video_id=s["video_id"], t=s["t"], url=s["url"], quote=q, errors=errs))
bad = [r for r in rows if r["errors"]]
if a.report: save(a.report, rows)
log(f"validated {len(rows)} sources: {len(rows) - len(bad)} pass, {len(bad)} fail")
for r in bad[:15]: log("  FAIL", r["section"], " + ".join(r["cards"]), r["url"], "|", "; ".join(r["errors"]))
sys.exit(1 if bad else 0)
