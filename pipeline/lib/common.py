"""Shared helpers: paths, logging (never logs secrets), Scryfall client with cache."""
import json, os, time, urllib.request, urllib.parse, urllib.error, datetime as dt, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def p(*a): return os.path.join(ROOT, *a)
def load(path, default=None):
    path = path if os.path.isabs(path) else p(path)
    return json.load(open(path)) if os.path.exists(path) else default
def save(path, obj):
    path = path if os.path.isabs(path) else p(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"; json.dump(obj, open(tmp, "w"), indent=1, ensure_ascii=False); os.replace(tmp, path)
SETTINGS = load("config/settings.json")
_SECRET = os.environ.get("APIFY_TOKEN") or "\x00never\x00"
def log(*a):
    msg = " ".join(str(x) for x in a).replace(_SECRET, "***")
    for x in (os.environ.get("YOUTUBE_API_KEY"), os.environ.get("LLM_API_KEY")):
        if x: msg = msg.replace(x, "***")
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)
def current_run():
    s = load("state/state.json", {})
    if not s.get("current_run"): raise SystemExit("No current run. Run 01_discover.py first.")
    return s["current_run"]
def run_dir(run_id): return p("runs", run_id)
def norm(s): return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower().replace("'", "").replace("\u2019", ""))).strip()

# ---- Scryfall (card data cached forever; prices cached per day) ----
UA = {"User-Agent": "TCGSellerHub-MarketSignals/1.0", "Accept": "application/json"}
_CF = p("cache/scry_cache.json"); _C = load(_CF, {}); _last = [0.0]
def scry_get(url, fresh_key=None):
    key = url if not fresh_key else f"{fresh_key}|{url}"
    if key in _C: return _C[key]
    wait = 0.11 - (time.time() - _last[0])
    if wait > 0: time.sleep(wait)
    _last[0] = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r: d = json.load(r)
    except urllib.error.HTTPError as e: d = {"object": "error", "status": e.code}
    _C[key] = d; return d
def scry_save(): save(_CF, _C)
def scry_named(name): return scry_get("https://api.scryfall.com/cards/named?exact=" + urllib.parse.quote(name.split(" // ")[0]))
def scry_first_printed(name):
    q = scry_get("https://api.scryfall.com/cards/search?" + urllib.parse.urlencode({"q": f'!"{name}"', "unique": "prints", "order": "released", "dir": "asc"}))
    return (q.get("data") or [{}])[0].get("released_at")
EXCLUDE_SET_TYPES = {"promo", "token", "memorabilia", "minigame", "alchemy", "treasure_chest", "vanguard"}
def scry_prints(name):
    """All printings of a card (oldest first), cached forever except the first page is refreshed weekly
    so newly released reprints show up. Follows pagination."""
    week = dt.date.today().strftime("%G-W%V")
    url = "https://api.scryfall.com/cards/search?" + urllib.parse.urlencode({"q": f'!"{name}" include:extras', "unique": "prints", "order": "released", "dir": "asc"})
    out = []
    while url:
        d = scry_get(url, fresh_key=week)
        out += d.get("data", []); url = d.get("next_page") if d.get("has_more") else None
    return out
EXCLUDE_SET_CODES = {"plst", "list", "ulst", "mb2", "mb1"}  # The List / Mystery Booster "list" style printings
def eligible_paper(c):
    """A real paper set printing: not digital-only (Arena/MTGO), not a promo, The List, token, art series or other extra.
    Commander, Masters, Special Guests, Secret Lair etc. count."""
    return ("paper" in c.get("games", [])) and not c.get("digital") and not c.get("promo") \
        and c.get("set_type") not in EXCLUDE_SET_TYPES and c.get("set") not in EXCLUDE_SET_CODES \
        and c.get("layout") not in ("art_series", "token", "double_faced_token", "emblem")
def print_info(name, cutoff, today=None):
    """first_printed (any real printing), plus is_reprint: printed in more than one distinct
    paper set at any time. reprint_count = number of distinct paper sets; latest_reprint_* = most recent one."""
    today = today or dt.date.today().isoformat()
    ps = [c for c in scry_prints(name) if c.get("released_at") and c["released_at"] <= today]
    if not ps: return None
    real = [c for c in ps if c.get("set_type") not in ("memorabilia", "token") and c.get("layout") not in ("art_series", "token", "double_faced_token", "emblem")] or ps
    first = min(real, key=lambda c: (c["released_at"], bool(c.get("promo") or c.get("set_type") == "promo"), bool(c.get("digital"))))
    sets = {}
    for c in sorted((c for c in ps if eligible_paper(c)), key=lambda c: c["released_at"]):
        sets.setdefault(c["set"], c)
    n = len(sets); latest = max(sets.values(), key=lambda c: c["released_at"]) if sets else None
    rp = latest if n > 1 else None
    ls = dict(code=rp["set"], name=rp["set_name"]) if rp else None
    return dict(first_printed=first["released_at"], first_printed_set=dict(code=first["set"], name=first["set_name"]),
                is_reprint=n > 1, reprint_count=n, paper_sets=list(dict.fromkeys(c["set_name"] for c in sets.values())),
                latest_reprint_set=ls, latest_reprint_date=rp["released_at"] if rp else None,
                reprint_set=ls, reprint_released=rp["released_at"] if rp else None)  # 1.1.0 names kept as aliases
def scry_cheapest_today(name):
    today = dt.date.today().isoformat()
    d = scry_get("https://api.scryfall.com/cards/search?" + urllib.parse.urlencode({"q": f'!"{name}" game:paper', "unique": "prints", "order": "usd", "dir": "asc"}), fresh_key=today)
    for c in d.get("data", []):
        if c.get("prices", {}).get("usd"): return c
    return None

# ---- HTTP with retries + exponential backoff (used by discovery/transcripts) ----
_SECRETS = [s for s in (os.environ.get("YOUTUBE_API_KEY"), os.environ.get("APIFY_TOKEN"), os.environ.get("LLM_API_KEY")) if s]
def redact(s):
    s = str(s)
    for x in _SECRETS: s = s.replace(x, "***")
    return s
def fetch(url, headers=None, data=None, method=None, timeout=30, tries=4, base=2.0, secret=False):
    """GET/POST with retries on network errors, 429 and 5xx (backoff base*2^n s + jitter). 4xx other than 429 fail fast."""
    import random
    last = None
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"}, data=data, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r: return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code != 429 and e.code < 500: break
        except Exception as e: last = e
        if n < tries - 1: time.sleep(base * (2 ** n) + random.random())
    raise RuntimeError(redact(f"{type(last).__name__}: {last}" + ("" if secret else f" ({url[:120]})")))
