#!/usr/bin/env python3
"""Step (a): find new videos per channel since the last run.
Source order per channel: YouTube Data API v3 (if env YOUTUBE_API_KEY is set) -> RSS feed -> channel page scrape.
Incremental: already-seen video ids are skipped; each channel's last successful check is kept in state.channels.
Polite: a pause between channels (DISCOVER_PAUSE_S, default 1.5 s) and retries with backoff on every request.
Usage: 01_discover.py [--since YYYY-MM-DD] [--run-id ID]
Creates runs/<run_id>/videos.json and sets state.current_run."""
import sys, os, argparse, datetime as dt, urllib.request, xml.etree.ElementTree as ET
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from common import *
ap = argparse.ArgumentParser(); ap.add_argument("--since"); ap.add_argument("--run-id")
ap.add_argument("--dry-run", action="store_true", help="list videos only; do not write runs/ or state")
ap.add_argument("--include-seen", action="store_true", help="(testing) also list already-seen videos")
ap.add_argument("--channels", help="comma-separated handles to limit discovery to"); a = ap.parse_args()
state = load("state/state.json", {"seen_video_ids": [], "last_run_at": None, "runs": []})
since = a.since or (state["last_run_at"] or (dt.datetime.utcnow() - dt.timedelta(days=SETTINGS["lookback_days_first_run"])).isoformat())[:10]
run_id = a.run_id or dt.datetime.now().strftime("%Y-%m-%d_%H%M")
seen = set() if a.include_seen else set(state["seen_video_ids"])
import re, time, urllib.parse, json as _json
H = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en"}
def _get(u): return fetch(u, headers=H).decode()
def page_list(ch, since, limit):
    """Fallback when RSS fails: video ids from the channel's Videos + Live tabs, publish date from each watch page.
    Skips Shorts (<=60s, or <=180s tagged #shorts), live/upcoming streams, other channels' videos, and seen ids."""
    ids = []
    for tab in ("videos", "streams"):
        try: ids += re.findall(r'"videoId":"([\w-]{11})"', _get(f"https://www.youtube.com/channel/{ch['channel_id']}/{tab}"))
        except Exception as e: log("page list failed", ch["handle"], tab, e)
    out = []; older = 0
    for vid in dict.fromkeys(ids):
        if len(out) >= limit or older >= 6: break
        if vid in seen: continue
        try:
            d = _json.loads(re.search(r"var ytInitialPlayerResponse = (\{.*?\});(?:var|</script>)", _get(f"https://www.youtube.com/watch?v={vid}")).group(1))
            vd = d["videoDetails"]; mf = d["microformat"]["playerMicroformatRenderer"]
        except Exception as e: log("watch page failed", vid, e); continue
        if vd.get("channelId") != ch["channel_id"]: continue
        pub = dt.datetime.fromisoformat(mf["publishDate"]).astimezone(dt.timezone.utc)
        if pub.date().isoformat() < since: older += 1; continue
        n = int(vd.get("lengthSeconds") or 0); txt = (vd["title"] + " " + vd.get("shortDescription", "")).lower()
        if SETTINGS["skip_shorts"] and (n <= 60 or (n <= 180 and "#shorts" in txt)): continue
        if vd.get("isLive") or vd.get("isUpcoming") or (mf.get("liveBroadcastDetails") or {}).get("isLiveNow"): continue
        out.append(dict(id=vid, channel=ch["handle"], channel_name=ch["name"], title=vd["title"], published=pub.isoformat(),
                        desc=vd.get("shortDescription", ""), url=f"https://www.youtube.com/watch?v={vid}"))
    return sorted(out, key=lambda v: v["published"], reverse=True)
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015", "m": "http://search.yahoo.com/mrss/"}
YT_KEY = os.environ.get("YOUTUBE_API_KEY") or None
PAUSE = float(os.environ.get("DISCOVER_PAUSE_S", "1.5"))
def iso_dur(s):
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    d, h, mi, se = (int(x or 0) for x in m.groups()) if m else (0, 0, 0, 0)
    return d * 86400 + h * 3600 + mi * 60 + se
def api_list(ch, since, limit):
    """YouTube Data API v3: uploads playlist (1 unit/page) + videos.list for duration/live state (1 unit). ~2-4 units per channel."""
    base = "https://www.googleapis.com/youtube/v3/"
    upl = "UU" + ch["channel_id"][2:]
    ids, page = [], None
    for _ in range(3):
        q = dict(part="contentDetails", playlistId=upl, maxResults=50, key=YT_KEY)
        if page: q["pageToken"] = page
        d = _json.loads(fetch(base + "playlistItems?" + urllib.parse.urlencode(q), secret=True))
        stop = False
        for it in d.get("items", []):
            pub = it["contentDetails"].get("videoPublishedAt") or ""
            if pub and pub[:10] < since: stop = True; break
            ids.append(it["contentDetails"]["videoId"])
        page = d.get("nextPageToken")
        if stop or not page: break
    ids = [i for i in dict.fromkeys(ids) if i not in seen]
    out = []
    for k in range(0, len(ids), 50):
        d = _json.loads(fetch(base + "videos?" + urllib.parse.urlencode(dict(part="snippet,contentDetails,liveStreamingDetails", id=",".join(ids[k:k + 50]), key=YT_KEY)), secret=True))
        for v in d.get("items", []):
            sn = v["snippet"]; n = iso_dur(v["contentDetails"].get("duration"))
            if sn.get("channelId") != ch["channel_id"] or sn["publishedAt"][:10] < since: continue
            if sn.get("liveBroadcastContent") in ("live", "upcoming"): continue
            txt = (sn["title"] + " " + sn.get("description", "")).lower()
            if SETTINGS["skip_shorts"] and (n <= 60 or (n <= 180 and "#shorts" in txt)): continue
            out.append(dict(id=v["id"], channel=ch["handle"], channel_name=ch["name"], title=sn["title"], published=sn["publishedAt"],
                            desc=sn.get("description", ""), url=f"https://www.youtube.com/watch?v={v['id']}"))
    return sorted(out, key=lambda v: v["published"], reverse=True)[:limit]
def rss_list(ch, since, limit):
    xml = fetch(f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['channel_id']}", headers={"User-Agent": "Mozilla/5.0"})
    out = []
    for e in ET.fromstring(xml).findall("a:entry", NS):
        vid = e.find("yt:videoId", NS).text; link = e.find("a:link", NS).get("href")
        pub = e.find("a:published", NS).text
        if pub[:10] < since or vid in seen: continue
        if SETTINGS["skip_shorts"] and "/shorts/" in link: continue
        if len(out) >= limit: break
        g = e.find("m:group", NS)
        out.append(dict(id=vid, channel=ch["handle"], channel_name=ch["name"], title=e.find("a:title", NS).text, published=pub,
                        desc=(g.find("m:description", NS).text or "") if g is not None else "", url=f"https://www.youtube.com/watch?v={vid}"))
    return out
vids = []; report = {}
only = set(a.channels.split(",")) if a.channels else None
chstate = state.setdefault("channels", {})
for k, ch in enumerate(load("config/channels.json")["channels"]):
    if only and ch["handle"] not in only: continue
    if k: time.sleep(PAUSE)
    limit = ch.get("max_videos_per_run", SETTINGS["max_videos_per_channel"])
    # incremental: per channel, look back from its own last good check (minus 2 days overlap); seen ids prevent repeats
    cs = chstate.get(ch["channel_id"], {})
    ch_since = since if a.since or not cs.get("last_ok") else min(since, (dt.date.fromisoformat(cs["last_ok"][:10]) - dt.timedelta(days=2)).isoformat())
    got, how = None, None
    for how, fn in (("api", api_list) if YT_KEY else (None, None), ("rss", rss_list), ("page", page_list)):
        if not fn: continue
        try: got = fn(ch, ch_since, limit); break
        except Exception as e: log(f"{ch['handle']}: {how} failed ({type(e).__name__}: {e}) -> next source")
    if got is None:
        report[ch["handle"]] = "failed"; log(f"{ch['handle']}: ALL sources failed"); continue
    vids += got; report[ch["handle"]] = f"{len(got)} via {how}"
    if not a.dry_run: chstate[ch["channel_id"]] = dict(handle=ch["handle"], last_ok=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), via=how)
    log(f"{ch['handle']}: {len(got)} new ({how})")
failed = [h for h, r in report.items() if r == "failed"]
if a.dry_run:
    for v in vids: log("  ", v["published"][:10], v["channel"], v["id"], v["title"][:70])
    log(f"dry run: {len(vids)} new videos since {since}; {len(failed)} channels failed; nothing written"); raise SystemExit(0)
save(f"runs/{run_id}/videos.json", vids); save(f"runs/{run_id}/discover_report.json", dict(source="api" if YT_KEY else "rss", channels=report))
state["current_run"] = run_id; save("state/state.json", state)
log(f"run {run_id}: {len(vids)} new videos since {since}; {len(failed)} channels failed")
if len(failed) > len(report) // 2: raise SystemExit(f"discovery failed for {len(failed)}/{len(report)} channels")
