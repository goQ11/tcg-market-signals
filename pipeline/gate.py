#!/usr/bin/env python3
"""Publish gate: compare a candidate signals.json with the currently published one. Exit 1 (do not publish) if
- required top-level fields/types are missing, schema major version changed, or generated_at is not newer;
- counts.videos or the number of calls (ban_alerts + impact_pairs + card_vibes) is outside sane bounds vs the previous file
  (below GATE_MIN_RATIO, default 0.4x, or above GATE_MAX_RATIO, default 4x) or below absolute floors.
Usage: gate.py NEW.json PREVIOUS.json [--report gate.json]"""
import sys, json, argparse, datetime as dt, os
ap = argparse.ArgumentParser(); ap.add_argument("new"); ap.add_argument("prev"); ap.add_argument("--report"); a = ap.parse_args()
N = json.load(open(a.new)); P = json.load(open(a.prev)) if os.path.exists(a.prev) else None
LO, HI = float(os.environ.get("GATE_MIN_RATIO", "0.4")), float(os.environ.get("GATE_MAX_RATIO", "4"))
MIN_VIDEOS, MIN_CALLS = int(os.environ.get("GATE_MIN_VIDEOS", "20")), int(os.environ.get("GATE_MIN_CALLS", "50"))
errs = []
TYPES = dict(schema_version=str, generated_at=str, run_id=str, window=dict, ban_announcements=dict, counts=dict, disclaimers=list,
             ban_alerts=list, impact_pairs=list, card_vibes=list, potential_risers=list, sources=list)
for k, t in TYPES.items():
    if not isinstance(N.get(k), t): errs.append(f"field {k} missing or not {t.__name__}")
def calls(S): return len(S.get("ban_alerts", [])) + len(S.get("impact_pairs", [])) + len(S.get("card_vibes", []))
for sec in ("ban_alerts", "card_vibes", "potential_risers"):
    for x in N.get(sec, []) if isinstance(N.get(sec), list) else []:
        if not x.get("card") or not x.get("sources"): errs.append(f"{sec}: entry without card/sources"); break
nv, nc = (N.get("counts") or {}).get("videos", 0), calls(N)
if nv < MIN_VIDEOS: errs.append(f"videos {nv} < floor {MIN_VIDEOS}")
if nc < MIN_CALLS: errs.append(f"calls {nc} < floor {MIN_CALLS}")
if "Not financial advice" not in " ".join(N.get("disclaimers") or []): errs.append("disclaimer missing")
if P:
    if str(N.get("schema_version", "")).split(".")[0] != str(P.get("schema_version", "")).split(".")[0]: errs.append("schema major version changed")
    try:
        if dt.datetime.fromisoformat(N["generated_at"]) <= dt.datetime.fromisoformat(P["generated_at"]): errs.append("generated_at not newer than published")
    except Exception as e: errs.append(f"generated_at unparsable: {e}")
    pv, pc = (P.get("counts") or {}).get("videos", 0), calls(P)
    for name, n, o in (("videos", nv, pv), ("calls", nc, pc)):
        if o and not (LO * o <= n <= HI * o): errs.append(f"{name} {n} outside {LO}x-{HI}x of previous {o}")
rep = dict(ok=not errs, errors=errs, new=dict(videos=nv, calls=nc, generated_at=N.get("generated_at")),
           previous=dict(videos=(P.get("counts") or {}).get("videos"), calls=calls(P), generated_at=P.get("generated_at")) if P else None)
if a.report: json.dump(rep, open(a.report, "w"), indent=1)
print(json.dumps(rep, indent=1)); sys.exit(0 if not errs else 1)
