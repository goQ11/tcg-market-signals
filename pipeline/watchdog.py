#!/usr/bin/env python3
"""Free daily watchdog for the published Market Signals feed. No secrets, no paid services.
Fails (exit 1) if the live signals.json is unreachable, has a broken schema, or generated_at is older than MAX_AGE_DAYS
(default 8). A failed scheduled workflow makes GitHub email the repo owner.
Usage: watchdog.py [URL_OR_PATH]  (default: the live raw GitHub URL)"""
import sys, os, json, time, urllib.request, datetime as dt
SRC = sys.argv[1] if len(sys.argv) > 1 else "https://raw.githubusercontent.com/goQ11/tcg-market-signals/main/signals.json"
MAX_AGE = float(os.environ.get("MAX_AGE_DAYS", "8"))
def get(src):
    if not src.startswith("http"): return open(src).read()
    last = None
    for n in range(4):
        try: return urllib.request.urlopen(urllib.request.Request(src, headers={"User-Agent": "tcg-market-signals-watchdog"}), timeout=30).read().decode()
        except Exception as e: last = e; time.sleep(2 * 2 ** n)
    raise SystemExit(f"FAIL: could not download {src}: {last}")
errs = []
try: S = json.loads(get(SRC))
except json.JSONDecodeError as e: raise SystemExit(f"FAIL: signals.json is not valid JSON: {e}")
TYPES = dict(schema_version=str, generated_at=str, run_id=str, window=dict, ban_announcements=dict, counts=dict, disclaimers=list,
             ban_alerts=list, impact_pairs=list, card_vibes=list, potential_risers=list, sources=list)
for k, t in TYPES.items():
    if not isinstance(S.get(k), t): errs.append(f"field {k} missing or not {t.__name__}")
if str(S.get("schema_version", "")).split(".")[0] != "1": errs.append(f"unexpected schema major version {S.get('schema_version')}")
for sec in ("ban_alerts", "card_vibes", "potential_risers"):
    for x in S.get(sec) or []:
        if not isinstance(x, dict) or not x.get("card") or not x.get("sources"): errs.append(f"{sec}: entry without card/sources"); break
age = None
try:
    age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(S["generated_at"])).total_seconds() / 86400
    if age > MAX_AGE: errs.append(f"STALE: generated_at {S['generated_at']} is {age:.1f} days old (limit {MAX_AGE:g}); the Monday update did not publish")
    if age < -1: errs.append(f"generated_at {S['generated_at']} is in the future")
except Exception as e: errs.append(f"generated_at unparsable: {e}")
calls = sum(len(S.get(k) or []) for k in ("ban_alerts", "impact_pairs", "card_vibes"))
print(json.dumps(dict(ok=not errs, source=SRC, generated_at=S.get("generated_at"), age_days=round(age, 2) if age is not None else None,
                      videos=(S.get("counts") or {}).get("videos"), calls=calls, errors=errs), indent=1))
for e in errs: print(f"::error::{e}")
sys.exit(1 if errs else 0)
