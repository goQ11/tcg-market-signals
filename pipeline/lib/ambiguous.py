"""Ambiguous short-name mentions: a bare name ("danitha") shared by 2+ cards new since new_card_since.
The mention is shown as one 'could be any of these' group listing every option; sentiment stays on the group."""
import collections
def collect(J, card_ok_vibe=True):
    """{short_name: dict(options=[...], pos/neu/neg/pot lists, ch=set)} from judged mention items with candidates."""
    g = collections.OrderedDict()
    for j in J.values():
        it = j["_item"]
        if it.get("kind") != "mention" or it.get("card") or not it.get("candidates"): continue
        if not j["card_ok"] or j["vibe"] == "none": continue
        a = g.setdefault(it["short_name"], dict(options=list(it["candidates"]), pos=[], neu=[], neg=[], pot=[], ch=set()))
        for c in it["candidates"]:
            if c not in a["options"]: a["options"].append(c)
        a["ch"].add(it["channel"]); a[{"positive": "pos", "neutral": "neu", "negative": "neg"}[j["vibe"]]].append(j)
        if (j.get("potential") or {}).get("rise"): a["pot"].append(j)
    return g
def build(groups, card, printing, price, tcg, src):
    out = []
    for short, a in groups.items():
        P, N, Z = len(a["pos"]), len(a["neg"]), len(a["neu"]); tot = P + N + Z
        net = (P - N) / tot
        opts = []
        for n in a["options"]:
            c = card(n)
            if not c: continue
            opts.append(dict(card=c["name"], scryfall_id=c["scryfall_id"], image=c["image"], **printing(n), price=price(c), tcgplayer_url=tcg(c["name"])))
        if len(opts) < 2: continue
        srcs = []; seen = set()
        for j in a["pot"] + a["pos"] + a["neg"] + a["neu"]:
            if id(j) in seen: continue
            seen.add(id(j)); s = src(j, [opts[0]["card"]], None, "ambiguous_mentions")  # any option's short name anchors it
            if s: srcs.append(s)
            if len(srcs) == 5: break
        if not srcs: continue
        out.append(dict(short_name=short, label="Could be any of these", note="The creator said only the short name; it could be any of these new cards. Watch the video to check.",
                        options=opts, vibe="positive" if net >= 0.34 else "negative" if net <= -0.34 else "neutral", score=round(net, 2),
                        positive=P, neutral=Z, negative=N, channels=len(a["ch"]), sources=srcs))
    out.sort(key=lambda x: (-x["channels"], -(x["positive"] + x["neutral"] + x["negative"]), x["short_name"]))
    return out
