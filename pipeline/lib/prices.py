"""MTGJSON TCGplayer retail price history for given Scryfall printing ids (optional; needs AllPrices.json.xz)."""
import os, json, lzma, subprocess, datetime as dt
from common import p, load, save, log, SETTINGS
def history(printings):
    """printings: {scryfall_id: set_code}. Returns {scryfall_id: {date: price}}. Empty if AllPrices missing."""
    ap = p(SETTINGS["mtgjson_allprices"])
    if not os.path.exists(ap) or not printings: return {}
    import ijson
    os.makedirs(p("cache/mtgjson_sets"), exist_ok=True)
    sid2uuid = {}
    for sid, s in printings.items():
        f = p("cache/mtgjson_sets", s.upper() + ".json")
        if not os.path.exists(f): subprocess.run(["curl", "-s", "-f", "-o", f, f"https://mtgjson.com/api/v5/{s.upper()}.json"])
        try: cards = json.load(open(f))["data"]["cards"]
        except Exception: continue
        for c in cards:
            if c.get("identifiers", {}).get("scryfallId") == sid: sid2uuid[sid] = c["uuid"]
    want = {u: s for s, u in sid2uuid.items()}; out = {}
    with lzma.open(ap, "rb") as fh:
        for k, v in ijson.kvitems(fh, "data"):
            if k in want:
                r = v.get("paper", {}).get("tcgplayer", {}).get("retail", {})
                out[want[k]] = {d: float(x) for d, x in (r.get("normal") or r.get("foil") or {}).items()}
                if len(out) == len(want): break
    log(f"MTGJSON history for {len(out)}/{len(printings)} printings")
    return out
def change(hist, days):
    if not hist: return None
    ds = sorted(hist); last = ds[-1]
    target = (dt.date.fromisoformat(last) - dt.timedelta(days=days)).isoformat()
    prev = [d for d in ds if d <= target]
    if not prev or not hist[prev[-1]]: return None
    return round(100 * (hist[last] - hist[prev[-1]]) / hist[prev[-1]], 1)
