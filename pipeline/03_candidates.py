#!/usr/bin/env python3
"""Step (c)+(d): find card candidates and every ban/restrict line; write runs/<run>/judge_queue.json.
See JUDGING.md for the handoff contract."""
import sys, os, re, hashlib, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from common import *
import matcher
run = current_run(); vids = load(f"runs/{run}/videos.json")
SIG = re.compile(r"\b(ban\w*|restrict\w*|good|great|best|busted|broken|strong|powerful|insane|amazing|bad|worse|worst|weak|overrated|underrated|sleeper|pick (it|them|these) up|buy|spik\w*|price|combo|synergy|infinite|better than|replace\w*|instead of|outclass\w*|new card|upgrade|cut|love|hate|favorite|nuts|absurd|cracked|unplayable|mediocre|staple|bomb|enables?|payoff|up \d+|down \d+|sick|solid|cheap|cheaper|cheapest|expensive|worth|cents|dollars|bucks|recommend\w*|auto ?include|reprint\w*|steal|bargain|undervalued|overvalued|excellent|fantastic|incredible|bonkers|terrible|awful)\b")
EN = {"the", "and", "you", "is", "that", "this", "to", "a", "it", "of"}
def is_english(tr, segs):
    """Non-English captions (e.g. a YouTube auto-dub track) make the English SIG gate drop almost everything."""
    if tr and tr.get("source") == "description": return True  # chapter titles only; too short to detect language
    if tr and tr.get("language"): return str(tr["language"]).lower().startswith("en")
    w = " ".join(s["text"] for s in segs[:200]).lower().split()
    return not w or sum(x in EN for x in w) / len(w) >= 0.08
BANLINE = re.compile(r"\b(unban\w*|banned|ban|bans|banning|ban ?list|restricted|restrict|restriction)\b", re.I)
def iid(*a): return hashlib.sha1("|".join(map(str, a)).encode()).hexdigest()[:12]
skipped = []; queue = []; stats = {"mentions": 0}
for v in vids:
    tr = load(f"cache/transcripts/{v['id']}.json")
    segs = tr["segments"] if tr else []
    meta = norm(v["title"] + " . " + v["desc"][:600])
    if tr and not is_english(tr, segs):
        lang = tr.get("language") or "non-en (detected)"
        skipped.append(dict(video_id=v["id"], channel=v["channel"], title=v["title"], language=lang))
        log(f"skip {v['id']} ({v['channel']}): transcript is not English ({lang})"); continue
    for stream, toks in (("transcript", matcher.tokens_from_segments(segs)), ("metadata", [(w, 0) for w in meta.split()])):
        words = [w for w, _ in toks]
        for (i, L, card, how) in matcher.find(words):
            stats["mentions"] += 1
            if not SIG.search(" ".join(words[max(0, i - 7):i]) + " | " + " ".join(words[i + L:i + L + 7])): continue  # exclude the name itself ("Price of Freedom")
            queue.append(dict(item_id=iid(v["id"], stream, i, card), kind="mention", video_id=v["id"], channel=v["channel"], card=card, match=how,
                              t=toks[i][1] if stream == "transcript" else 0, stream=stream, context=" ".join(words[max(0, i - 16):i + L + 16])))
    for k, s in enumerate(segs):
        if BANLINE.search(s["text"]):
            ctx = " ".join(x["text"] for x in segs[max(0, k - 3):k + 4]).replace("\n", " ")
            cards = sorted({c for (_, _, c, _) in matcher.find(norm(ctx).split())})
            queue.append(dict(item_id=iid(v["id"], "ban", k), kind="ban_line", video_id=v["id"], channel=v["channel"], card=None,
                              cards_in_context=cards, t=int(s["start"]), stream="transcript", context=ctx))
rep = load(f"runs/{run}/transcripts_report.json", {}); rep["skipped_non_english"] = skipped; save(f"runs/{run}/transcripts_report.json", rep)
matcher_cards = {q["card"] for q in queue if q["card"]}
save(f"runs/{run}/judge_queue.json", {"schema": "msp.judge_queue/1", "run_id": run, "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
     "videos": {v["id"]: {"channel": v["channel"], "title": v["title"], "published": v["published"]} for v in vids},
     "instructions": "See JUDGING.md. Write runs/<run_id>/judgments.json with one entry per item_id.",
     "items": queue})
log(f"{stats['mentions']} raw mentions -> {sum(q['kind']=='mention' for q in queue)} mention items + {sum(q['kind']=='ban_line' for q in queue)} ban lines, {len(matcher_cards)} cards")
