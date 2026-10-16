"""Card-name matcher: exact n-grams against Scryfall names, blocklist, idiom gate,
gated common single words, caption aliases, fuzzy + phonetic (Metaphone) fallback."""
import re, json
from wordfreq import zipf_frequency as zf
from rapidfuzz import process, fuzz
import jellyfish
from common import p, load, norm
names = load("cache/cardnames.json")["data"]
KW = {norm(x) for f in ["kw.json", "ka.json", "aw.json"] for x in load("cache/" + f)["data"]}
SHARDS = set("esper grixis jund naya bant abzan jeskai sultai mardu temur azorius dimir rakdos gruul selesnya orzhov izzet golgari boros simic lorehold prismari quandrix silverquill witherbloom".split())
EXTRA = load("config/blocklist.json", {"phrases": []})["phrases"]
BLOCK = KW | SHARDS | {norm(x) for x in EXTRA}
ALIAS = {norm(k): v for k, v in load("config/aliases.json", {}).items() if not k.startswith("_")}
lex = {}
for n in names:
    for part in n.split(" // "):
        q = norm(part); toks = q.split()
        if not q or q in BLOCK: continue
        if len(toks) == 1:
            if len(q) >= 5 and zf(q, "en") < 2.8: lex[q] = n
        else:
            if len(toks) == 2 and all(zf(t, "en") > 4.5 for t in toks): continue
            lex[q] = n
        if "," in part:
            s = norm(part.split(",")[0])
            if len(s) >= 4 and len(s.split()) <= 2 and s not in BLOCK and zf(s.split()[0], "en") < 2.5: lex.setdefault(s, n)
COMMON1 = {}
for n in names:
    q = norm(n.split(" // ")[0])
    if " " not in q and len(q) >= 5 and q not in lex and q not in BLOCK and zf(q, "en") >= 2.8: COMMON1[q] = n
IDIOM = {k for k in lex if all(zf(t, "en") >= 3.5 for t in k.split())}
CTX = re.compile(r"\b(cast|casting|play|playing|copies|copy|card|cards|deck|resolve|target|sideboard|maindeck|exile|counter|activate|ban\w*|unban\w*|restrict\w*|spec|specs|buy|buying|pick up|foil|printing|reprint\w*|price|bucks|dollars|cents)\b")
GATE1 = re.compile(r"\b(ban\w*|restrict\w*|copies of|cast(ing)?|play(ing)?|card)\b")
single = [k for k in lex if " " not in k and len(k) >= 7]
PHON = {}
for k in single: PHON.setdefault(jellyfish.metaphone(k), []).append(k)
_fz = {}
def fuzzy_tok(w):
    """Unknown, non-English token -> card via fuzzy ratio>=86 (same first letter), else exact Metaphone code match."""
    if w in _fz: return _fz[w]
    r = None
    if len(w) >= 7 and zf(w, "en") < 1.5:
        m = process.extractOne(w, single, scorer=fuzz.ratio, score_cutoff=86)
        if m and m[0][0] == w[0]: r = (lex[m[0]], "fuzzy")
        else:
            c = PHON.get(jellyfish.metaphone(w))
            if c and len(c) == 1 and fuzz.ratio(w, c[0]) >= 70: r = (lex[c[0]], "phonetic")
    _fz[w] = r; return r
maxlen = max(len(k.split()) for k in lex)
def find(words):
    """Return [(index, length, card_name, how)] for a list of normalized words."""
    hits = []; i = 0
    while i < len(words):
        got = None
        for L in range(min(maxlen, len(words) - i), 0, -1):
            q = " ".join(words[i:i + L])
            if q in ALIAS: got = (L, ALIAS[q], "alias"); break
            if L == 1 and q in COMMON1 and zf(q, "en") < 4.2 and GATE1.search(" ".join(words[max(0, i - 5):i + 6])):
                got = (1, COMMON1[q], "common-gated"); break
            if q in lex:
                if q in IDIOM and not CTX.search(" ".join(words[max(0, i - 8):i + L + 8])): break
                got = (L, lex[q], "exact"); break
        if not got:
            f = fuzzy_tok(words[i])
            if f: got = (1, f[0], f[1])
        if got: hits.append((i,) + got); i += got[0]
        else: i += 1
    return hits
def tokens_from_segments(segs):
    out = []
    for s in segs:
        for w in norm(s["text"]).split(): out.append((w, int(s["start"])))
    return out
