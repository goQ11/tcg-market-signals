"""Transcript anchoring: find where a quote / card is said, and return verbatim caption text + timestamp."""
import os, re
from rapidfuzz import fuzz
from common import p, load, norm
LEAD_S = 3          # start the link this many seconds before the quote
NEAR_S = 15         # a quote must be found within this many seconds of the link time (+LEAD_S)
MAX_WORDS = 19
_cache = {}
def words(video_id):
    """[(raw_word, norm_word, seg_start)] for the cached transcript, or None."""
    if video_id in _cache: return _cache[video_id]
    tr = load(f"cache/transcripts/{video_id}.json")
    out = None
    if tr and tr.get("segments"):
        out = []
        for s in tr["segments"]:
            for raw in re.sub(r"\s+", " ", s["text"].replace("\n", " ")).strip().split(" "):
                n = norm(raw)
                if raw and n: out.append((raw, n, float(s["start"])))
    _cache[video_id] = out
    return out
def load_aliases():
    """{card: [spoken forms]} from config/aliases.json + config/anchor_aliases.json."""
    out = {}
    for f in ("config/aliases.json", "config/anchor_aliases.json"):
        for k, v in (load(f) or {}).items():
            if not k.startswith("_"): out.setdefault(v, []).append(k)
    return out
def name_keys(card):
    """Normalized ways a card is said: full name, each face, the part before a comma, first long word."""
    keys = set()
    for face in card.split(" // "):
        f = norm(face); keys.add(f)
        if "," in face: keys.add(norm(face.split(",")[0]))
    return {k for k in keys if len(k) >= 4}
def mentions(W, card, aliases=()):
    """Word indices where the card (or an alias) is said; fuzzy per n-gram to survive caption errors."""
    keys = name_keys(card) | {norm(a) for a in aliases}
    hits = []
    for k in keys:
        L = len(k.split())
        for i in range(len(W) - L + 1):
            g = " ".join(w[1] for w in W[i:i + L])
            if g == k or (len(k) >= 6 and fuzz.ratio(g, k) >= 85): hits.append(i)
    return sorted(set(hits))
def best_span(W, quote, lo_t=None, hi_t=None):
    """Best fuzzy match of the quote's words in W (optionally within a time range). Returns (score, i, j)."""
    q = norm(quote).split()
    if not q: return (0, None, None)
    L = len(q); qs = " ".join(q); best = (0, None, None)
    for i in range(len(W)):
        if lo_t is not None and W[i][2] < lo_t: continue
        if hi_t is not None and W[i][2] > hi_t: break
        for LL in (L - 1, L, L + 1):
            if LL < 1 or i + LL > len(W): continue
            sc = fuzz.ratio(" ".join(w[1] for w in W[i:i + LL]), qs)
            if sc > best[0]: best = (sc, i, i + LL)
    return best
def snippet(W, i, j=None, card_idx=None):
    """Verbatim caption words (<20) covering [i, j) and, if given, the card mention."""
    j = j if j is not None else i + 1
    a, b = min(i, card_idx if card_idx is not None else i), max(j, (card_idx + 1) if card_idx is not None else j)
    while b - a < MAX_WORDS and (a > 0 or b < len(W)):
        if b < len(W): b += 1
        if b - a < MAX_WORDS and a > 0: a -= 1
    if b - a > MAX_WORDS: a, b = (i, min(j, i + MAX_WORDS)) if (j - i) <= MAX_WORDS else (i, i + MAX_WORDS)
    return " ".join(w[0] for w in W[a:b]).strip(" ,"), a, b
def tighten(W, s, a, k):
    """If the snippet starts >10s before the card's caption segment (long segments), restart it there."""
    if k is None or W[k][2] - W[a][2] <= 10: return s, a
    a2 = next(x for x in range(a, k + 1) if W[x][2] >= W[k][2] - 10)
    b2 = min(len(W), a2 + MAX_WORDS, max(k + 6, a2 + 12))
    return " ".join(w[0] for w in W[a2:b2]).strip(" ,"), a2
def link_t(W, idx): return max(0, int(W[idx][2]) - LEAD_S)
def quote_near(W, quote, t, need=80):
    """Validation: is the quote said within [t-NEAR_S, t+LEAD_S+NEAR_S]?"""
    sc, i, _ = best_span(W, quote, t - NEAR_S, t + LEAD_S + NEAR_S)
    return sc >= need, sc
def cards_near(W, cards, t, aliases=None, span_s=30):
    """Each card is mentioned within span_s seconds of t."""
    aliases = aliases or {}
    for c in cards:
        if not any(abs(W[k][2] - (t + LEAD_S)) <= span_s for k in mentions(W, c, aliases.get(c, ()))): return False
    return True
def anchor(video_id, cards, quote, hint_t, stream, aliases=None):
    """Find the best place for a claim. Returns dict(t, quote, ok, how) or dict(ok=False, why)."""
    W = words(video_id)
    if not W: return {"ok": False, "why": "no transcript"}
    aliases = aliases or {}
    m0 = mentions(W, cards[0], aliases.get(cards[0], ()))
    if len(cards) > 1:   # pair: places where both cards are said within ~40 words
        m1 = mentions(W, cards[1], aliases.get(cards[1], ()))
        m0 = [i for i in m0 if any(abs(i - k) <= 40 for k in m1)] or [k for k in m1 if any(abs(i - k) <= 40 for i in m0)]
    if not m0: return {"ok": False, "why": f"{' + '.join(cards)} not said in captions"}
    center = hint_t if (stream == "transcript" and hint_t) else None
    # 1) the judged quote, verbatim-ish, near the hint (or anywhere near a mention when no hint)
    if quote:
        lo, hi = (center - 25, center + 25) if center is not None else (None, None)
        sc, i, j = best_span(W, quote, lo, hi)
        if sc >= 75 and any(abs(k - i) <= 12 for k in m0):
            k = min(m0, key=lambda k: abs(k - i))
            s, a, _ = snippet(W, i, j, k); s, a = tighten(W, s, a, k)
            return {"ok": True, "t": link_t(W, a), "quote": s, "how": f"quote match {sc:.0f}"}
    # 2) otherwise the card mention nearest the hint (or the first co-mention)
    k = min(m0, key=lambda k: abs(W[k][2] - center)) if center is not None else m0[0]
    if center is not None and abs(W[k][2] - center) > 30: return {"ok": False, "why": "card not said near the judged moment"}
    s, a, _ = snippet(W, k); s, a = tighten(W, s, a, k)
    return {"ok": True, "t": link_t(W, a), "quote": s, "how": "card mention"}
