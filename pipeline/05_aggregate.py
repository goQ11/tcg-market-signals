#!/usr/bin/env python3
"""Steps (e)+(f): aggregate judged items in the signals window, check legality (Scryfall + config/official_bans.json),
attach prices (Scryfall today + MTGJSON history if available) and TCGplayer links, write out/signals.json.
Usage: 05_aggregate.py [--as-of YYYY-MM-DD] [--no-history]"""
import sys, os, argparse, collections, datetime as dt, urllib.parse, shutil
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from common import *
import prices, anchor
ALIASES = anchor.load_aliases()
REVIEW = []  # claims/sources dropped because the transcript doesn't support them
SCHEMA_VERSION = "1.4.0"  # 1.4: paper_sets (distinct paper set names, oldest first); 1.3: removed is_new/new_card_verified_new; added reserved (Wizards Reserved List); 1.2: generic reprint (reprint_count, latest_reprint_set/date);  # 1.1: additive printing fields (first_printed, is_reprint, reprint_set, reprint_released)
ap = argparse.ArgumentParser(); ap.add_argument("--as-of"); ap.add_argument("--no-history", action="store_true"); a = ap.parse_args()
as_of = dt.date.fromisoformat(a.as_of) if a.as_of else dt.date.today()
start = as_of - dt.timedelta(days=SETTINGS["signals_window_days"])
J = load("state/judged_all.json", {}); V = load("state/videos_all.json", {}); OB = load(SETTINGS["official_bans"])
CH = {c["handle"]: c["name"] for c in load("config/channels.json")["channels"]}
J = {k: j for k, j in J.items() if start.isoformat() <= V.get(j["_item"]["video_id"], {}).get("published", "")[:10] <= as_of.isoformat()}
def url(vid, t): return f"https://www.youtube.com/watch?v={vid}" + (f"&t={int(t)}s" if t else "")
def q19(s): return " ".join((s or "").split()[:19])
def src(j, cards, quote=None, section=""):
    """Source citation anchored in the transcript: verbatim caption quote (<20 words) and a link a few
    seconds before it. Returns None (and records it for review) when the captions don't support the claim."""
    it = j["_item"]; v = V[it["video_id"]]
    judged = q19(quote or j.get("quote"))
    a = anchor.anchor(it["video_id"], cards, judged, it["t"], it["stream"], ALIASES)
    if not a["ok"]:
        REVIEW.append(dict(section=section, cards=cards, video_id=it["video_id"], channel=it["channel"], judged_quote=judged, item_t=it["t"], why=a["why"]))
        return None
    return {"channel": it["channel"], "channel_name": CH.get(it["channel"], it["channel"]), "video_id": it["video_id"], "video_title": v["title"],
            "published": v["published"][:10], "t": a["t"], "url": url(it["video_id"], a["t"]), "quote": a["quote"], "judge_note": judged, "anchored_by": a["how"]}
CARD = {}
def printing(n):
    """Additive printing fields shared by vibes, risers and impact-pair cards."""
    c = card(n); pi = (c or {}).get("printing") or {}
    return dict(reserved=bool(pi.get("reserved")), first_printed=pi.get("first_printed"), first_printed_set=pi.get("first_printed_set"), is_reprint=bool(pi.get("is_reprint")), reprint_count=pi.get("reprint_count", 0), paper_sets=pi.get("paper_sets") or [],
                latest_reprint_set=pi.get("latest_reprint_set"), latest_reprint_date=pi.get("latest_reprint_date"),
                reprint_set=pi.get("reprint_set"), reprint_released=pi.get("reprint_released"))
def card(n):
    if n in CARD: return CARD[n]
    d = scry_named(n)
    if d.get("object") != "card": CARD[n] = None; return None
    pi = print_info(d["name"], SETTINGS["new_card_since"], as_of.isoformat()) or dict(first_printed=scry_first_printed(d["name"]), first_printed_set=None, is_reprint=False, reprint_count=0, reprint_set=None, reprint_released=None)
    pi.pop("is_new", None); pi["reserved"] = bool(d.get("reserved"))
    first = pi["first_printed"]; ch = scry_cheapest_today(d["name"])
    CARD[n] = dict(name=d["name"], scryfall_id=d["id"], legal=d["legalities"], first=first, printing=pi,
                   image=(d.get("image_uris") or (d.get("card_faces") or [{}])[0].get("image_uris") or {}).get("small"),
                   cheapest=dict(set=ch["set"], id=ch["id"], usd=ch["prices"].get("usd"), usd_foil=ch["prices"].get("usd_foil")) if ch else None)
    return CARD[n]
def tcg(n):
    u = SETTINGS["tcgplayer_search_url"].format(q=urllib.parse.quote_plus(n))
    return u + ("&" + SETTINGS["affiliate_param"] if SETTINGS.get("affiliate_param") else "")
FMT_SCRY = {"cedh": "commander", "oldschool": None, "other": None}
RECENT = {(r["card"], r["format"]): r for r in OB["recent_changes"]}
def verdict(c, b):
    f = b["format"]; sf = FMT_SCRY.get(f, f); st = c["legal"].get(sf) if sf else None
    r = RECENT.get((c["name"], sf))
    if r and r["action"] == ("restrict" if b["action"] == "restrict" else "ban") and b["action"] != "unban":
        return "confirmed", f"Official: {r['action']} on {r['date']}", st
    if b["action"] == "unban":
        if st == "legal": return "confirmed", "Already legal (previously banned)", st
        if st == "banned": return "speculation", f"Currently banned; next B&R {OB['next_announcement']}", st
    if b["action"] in ("ban", "restrict", "dont_ban"):
        if st == "banned" and b["action"] == "ban": return "already_banned", "Already banned", st
        if st == "not_legal": return "not_applicable", "Card is not legal in this format", st
        if st is None: return "unofficial_format", "Format has no official ban list", st
    return "speculation", f"No official action; next B&R {OB['next_announcement']}", st
bans = collections.OrderedDict(); pairs = collections.OrderedDict()
vib = collections.defaultdict(lambda: dict(pos=[], neu=[], neg=[], pot=[], ch=set()))
for j in J.values():
    it = j["_item"]
    for b in j.get("bans") or []:
        c = card(b["card"])
        if not c: continue
        k = (c["name"], b["format"], b["action"], b["stance"])
        sc = src(j, [c["name"]], b.get("quote"), "ban_alerts")
        if sc: bans.setdefault(k, []).append(sc)
    for pr in j.get("pairs") or []:
        n, o = card(pr["new_card"]), card(pr["existing_card"])
        if not n or not o: continue
        sc = src(j, [n["name"], o["name"]], None, "impact_pairs")
        if sc: pairs.setdefault((n["name"], o["name"], pr["effect"]), dict(format=pr.get("format"), s=[]))["s"].append(sc)
    if it["kind"] != "mention" or not j["card_ok"] or j["vibe"] == "none": continue
    c = card(j.get("card") or it["card"])
    if not c: continue
    a_ = vib[c["name"]]; a_["ch"].add(it["channel"])
    a_[{"positive": "pos", "neutral": "neu", "negative": "neg"}[j["vibe"]]].append(j)
    if (j.get("potential") or {}).get("rise"): a_["pot"].append(j)
ban_alerts = []
for (n, f, act, stance), ss in bans.items():
    c = card(n); status, detail, st = verdict(c, dict(format=f, action=act))
    ban_alerts.append(dict(card=n, scryfall_id=c["scryfall_id"], image=c["image"], **printing(n), format=f, action=act, stance=stance, status=status,
                           status_detail=detail, current_legality=st, channels=len({s["channel"] for s in ss}), sources=ss[:5]))
ban_alerts.sort(key=lambda b: (b["status"] != "speculation", -b["channels"], b["card"]))
impact = []
for (n, o, eff), d in pairs.items():
    impact.append(dict(new_card=n, existing_card=o, effect=eff, format=d["format"], new_card_released=card(n)["first"],
                       channels=len({s["channel"] for s in d["s"]}), sources=d["s"][:5], tcgplayer_url_existing=tcg(o), tcgplayer_url_new=tcg(n),
                       new_card_info=printing(n), existing_card_info=printing(o)))
impact.sort(key=lambda x: -x["channels"])
# prices
hist = {} if a.no_history else prices.history({CARD[n]["cheapest"]["id"]: CARD[n]["cheapest"]["set"] for n in vib if CARD.get(n) and CARD[n]["cheapest"]})
def price(c):
    ch = c["cheapest"]
    if not ch: return None
    h = hist.get(ch["id"], {})
    return dict(usd=float(ch["usd"]) if ch["usd"] else None, usd_foil=float(ch["usd_foil"]) if ch["usd_foil"] else None, printing_set=ch["set"].upper(),
                source="Scryfall (TCGplayer market, cheapest paper printing)", as_of=as_of.isoformat(),
                change_7d_pct=prices.change(h, 7), change_30d_pct=prices.change(h, 30), history_as_of=max(h) if h else None)
vibes = []
for n, a_ in vib.items():
    c = card(n); P, N, Z = len(a_["pos"]), len(a_["neg"]), len(a_["neu"]); tot = P + N + Z
    net = (P - N) / tot
    lab = "positive" if net >= 0.34 else "negative" if net <= -0.34 else "neutral"
    cands = a_["pot"] + a_["pos"] + a_["neg"] + a_["neu"]
    seen_ids = set(); srcs = []
    for j in cands:
        if id(j) in seen_ids: continue
        seen_ids.add(id(j)); sc = src(j, [n], None, "card_vibes")
        if sc: srcs.append(sc)
        if len(srcs) == 3: break
    if not srcs: continue
    vibes.append(dict(card=n, scryfall_id=c["scryfall_id"], image=c["image"], **printing(n), vibe=lab, score=round(net, 2), positive=P, neutral=Z, negative=N,
                      channels=len(a_["ch"]), potential_to_rise=bool(a_["pot"]) and lab != "negative",
                      potential_reasons=sorted({(j.get("potential") or {}).get("reason") for j in a_["pot"] if (j.get("potential") or {}).get("reason")})[:3],
                      price=price(c), tcgplayer_url=tcg(n), sources=srcs))
vibes.sort(key=lambda v: (-v["channels"], -(v["positive"] + v["negative"] + v["neutral"]), v["card"]))
risers = [dict(card=v["card"], reasons=v["potential_reasons"], vibe=v["vibe"], **{k: v[k] for k in ("reserved", "paper_sets", "first_printed", "first_printed_set", "is_reprint", "reprint_count", "latest_reprint_set", "latest_reprint_date", "reprint_set", "reprint_released")}, channels=v["channels"], price=v["price"], tcgplayer_url=v["tcgplayer_url"], sources=v["sources"])
          for v in vibes if v["potential_to_rise"]]
save("out/needs_review.json", REVIEW)
log(f"{len(REVIEW)} sources dropped (not supported by captions) -> out/needs_review.json")
used = {s["video_id"] for x in ban_alerts + impact + vibes for s in x["sources"]}
win_vids = sorted({j["_item"]["video_id"] for j in J.values()})
out = dict(schema_version=SCHEMA_VERSION, generated_at=dt.datetime.now().astimezone().isoformat(timespec="seconds"), run_id=load("state/state.json", {}).get("current_run"),
           window=dict(start=start.isoformat(), end=as_of.isoformat(), days=SETTINGS["signals_window_days"]),
           ban_announcements=dict(last=OB["last_announcement"], next=OB["next_announcement"]),
           counts=dict(videos=len(win_vids), channels=len({V[v]["channel"] for v in win_vids}), ban_alerts=len(ban_alerts), impact_pairs=len(impact), card_vibes=len(vibes), potential_risers=len(risers)),
           disclaimers=["Not financial advice. Signals summarize opinions from YouTube creators and can be wrong.",
                        "Ban alerts marked 'speculation' are creator opinions, not official Wizards of the Coast announcements.",
                        "Prices are Scryfall's TCGplayer market prices for the cheapest paper printing and may be out of date."],
           affiliate_disclosure="",
           ban_alerts=ban_alerts, impact_pairs=impact, card_vibes=vibes, potential_risers=risers,
           sources=[dict(video_id=v, channel=V[v]["channel"], channel_name=CH.get(V[v]["channel"], V[v]["channel"]), title=V[v]["title"], published=V[v]["published"][:10],
                         url=url(v, 0), cited=v in used) for v in win_vids])
scry_save()
save("out/signals.json", out); os.makedirs(p("out/archive"), exist_ok=True)
shutil.copy(p("out/signals.json"), p("out/archive", f"signals-{as_of.isoformat()}.json"))
log(f"signals.json: {out['counts']}")
