"""Printings of a card grouped into version groups, each printing with its own TCGplayer Market Price (Scryfall prices).
Groups come only from Scryfall fields: promo, border_color, frame_effects (showcase, extendedart), full_art, and the
finish (nonfoil -> prices.usd, foil -> prices.usd_foil, etched -> prices.usd_etched). Missing price -> 'unavailable'."""
import datetime as dt, urllib.parse
from common import scry_get
FIN = {"nonfoil": ("", "usd"), "foil": ("Foil", "usd_foil"), "etched": ("Etched Foil", "usd_etched")}
def treatment(c):
    fe = set(c.get("frame_effects") or [])
    if c.get("promo") or c.get("set_type") == "promo": return "Promo"
    if c.get("border_color") == "borderless": return "Borderless"
    if "showcase" in fe: return "Showcase"
    if "extendedart" in fe: return "Extended Art"
    if c.get("full_art"): return "Full Art"
    return "Regular"
def prints_today(name):
    """Same Scryfall search (and daily cache entry) the cheapest-price lookup already uses."""
    today = dt.date.today().isoformat()
    d = scry_get("https://api.scryfall.com/cards/search?" + urllib.parse.urlencode({"q": f'!"{name}" game:paper', "unique": "prints", "order": "usd", "dir": "asc"}), fresh_key=today)
    return d.get("data", []) if d.get("object") == "list" else [], bool(d.get("has_more"))
ORDER = ["Regular", "Foil", "Etched Foil", "Showcase", "Borderless", "Extended Art", "Full Art", "Promo"]
def groups(name):
    ps, more = prints_today(name)
    g = {}
    for c in ps:
        t = treatment(c); pr = c.get("prices") or {}
        for f in c.get("finishes") or ["nonfoil"]:
            if f not in FIN: continue
            lab, key = FIN[f]
            gname = (t if t != "Regular" else "") + (" " if t != "Regular" and lab else "") + lab or "Regular"
            v = pr.get(key)
            g.setdefault(gname, []).append(dict(set=c["set"].upper(), set_name=c.get("set_name"), collector_number=c.get("collector_number"),
                released=c.get("released_at"), finish=f, usd=float(v) if v else None, display=f"${float(v):,.2f}" if v else "unavailable",
                scryfall_id=c["id"]))
    def rank(k): return min([i for i, o in enumerate(ORDER) if k.startswith(o) or k == o] or [99]), k
    out = []
    for k in sorted(g, key=rank):
        items = sorted(g[k], key=lambda x: (x["usd"] is None, x["usd"] or 0, x["released"] or ""))
        out.append(dict(group=k, label="TCGplayer Market", collapsed=k != "Regular", printings=items))
    return dict(version_groups=out, version_groups_complete=not more)
