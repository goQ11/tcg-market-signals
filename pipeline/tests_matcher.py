#!/usr/bin/env python3
"""Matcher tests: bare short names shared by several cards. Run: python tests_matcher.py
(needs cache/cardnames.json + cache/recent_names.json)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import matcher
from common import norm
def cards(text): return [c for (_, _, c, _) in matcher.find(norm(text).split())]
def amb(text): matcher.find(norm(text).split()); return [s for _, _, s in matcher.AMBIGUOUS_HITS]
def check(text, want):
    got = cards(text); assert got == want, f"{text!r}: got {got}, want {want}"
# rules
R = {"New A"}
assert matcher.resolve_short(["Old X"], R) == "Old X"                    # one card -> it
assert matcher.resolve_short(["Old X", "New A"], R) is None             # one new + older -> ambiguous now
assert matcher.resolve_short(["Old X", "Old Y"], R) is None             # any age -> ambiguous
assert matcher.resolve_short(["Old X", "A-Old X"], R) == "Old X"        # Alchemy 'A-' names don't count
assert matcher.order_candidates(["Old X", "New A", "A-New A"], R) == ["New A", "Old X"]   # new first, no A- names
assert matcher.canon("Krark, the Thumbless // Krark, the Thumbless") == "Krark, the Thumbless"
# Ajani: bare name is ambiguous; full name or unique subtitle -> the card
for t in ("this is when the ajani becomes insane", "ajani uncounterable", "another ajani sick"):
    assert cards(t) == [] and amb(t) == ["ajani"], t
assert "Ajani, Adversary of Tyrants" in matcher.AMBIG["ajani"] and len(matcher.AMBIG["ajani"]) > 8
check("ajani adversary of tyrants is great", ["Ajani, Adversary of Tyrants"])
check("adversary of tyrants is great", ["Ajani, Adversary of Tyrants"])
# Reality Fracture names: new cards listed first, older ones included
assert matcher.AMBIG["danitha"][:2] == ["Danitha, Spear of Agony", "Danitha, Sword of Hope"] and "Danitha, Benalia's Hope" in matcher.AMBIG["danitha"]
assert matcher.AMBIG["vraska"][:2] == ["Vraska, Soul of Stone", "Vraska, the Cutting Glare"]
assert matcher.AMBIG["emrakul"][0] == "Emrakul, the Exigent Doom" and "Emrakul, the Aeons Torn" in matcher.AMBIG["emrakul"]
assert matcher.AMBIG["yargle"] == ["Yargle, Goliath of Otaria", "Yargle, Glutton of Urborg"]
for t, s in (("good danitha good", "danitha"), ("vraska is a very good magic card", "vraska"), ("ill play the saheeli", "saheeli"),
             ("whats great about a free emrakul", "emrakul"), ("dont need the yargle", "yargle"), ("danithas also really good", "danitha")):
    assert cards(t) == [] and amb(t) == [s], (t, cards(t), amb(t))
# full names still win; only one card with that name -> it
check("danitha sword of hope is good", ["Danitha, Sword of Hope"])
check("vraska betrayals sting", ["Vraska, Betrayal's Sting"])
check("emrakul the aeons torn", ["Emrakul, the Aeons Torn"])
check("saheeli jewel of avishkar", ["Saheeli, Jewel of Avishkar"])
check("ragavan is great", ["Ragavan, Nimble Pilferer"])
check("krark is great", ["Krark, the Thumbless"])
assert amb("danitha sword of hope") == []
# grouping (lib/ambiguous.py): sentiment on the group, options capped with more_options
import ambiguous, versions
ambiguous.is_paper = lambda n: n != "Digital"
versions.prints_today = lambda n: ([] if n == "Digital" else [{}], False)
def it(short, vibe, ch="@a", cands=("X1", "X2")): return {"card_ok": True, "vibe": vibe, "_item": {"kind": "mention", "card": None, "short_name": short, "candidates": list(cands), "channel": ch}}
J = {"1": it("x", "positive"), "2": it("x", "negative", "@b"), "3": it("x", "none"), "4": {"card_ok": True, "vibe": "positive", "_item": {"kind": "mention", "card": "Y", "channel": "@a"}}}
G = ambiguous.collect(J)
assert list(G) == ["x"] and len(G["x"]["pos"]) == 1 and len(G["x"]["neg"]) == 1 and G["x"]["ch"] == {"@a", "@b"}
fake = lambda n: dict(name=n, scryfall_id=n, image=None)
prn = lambda n: {"first_printed": "2020-01-%02d" % int(n[1:]) if n[1:].isdigit() else "2000-01-01"}
args = (fake, prn, lambda c: {"display": "unavailable"}, lambda n: "u", lambda j, cs, q, s: {"video_id": "v"})
out = ambiguous.build(G, *args)
assert [o["card"] for o in out[0]["options"]] == ["X2", "X1"] and out[0]["positive"] == 1 and out[0]["negative"] == 1   # newest first
assert out[0]["more_options"] == 0 and out[0]["options_total"] == 2
big = ambiguous.collect({"1": it("b", "positive", cands=[f"X{i}" for i in range(1, 12)] + ["A-X1", "Digital"])})
o = ambiguous.build(big, *args)[0]
assert len(o["options"]) == 8 and o["options_total"] == 11 and o["more_options"] == 3 and o["options"][0]["card"] == "X11"
# version groups come only from Scryfall fields
assert versions.treatment({"promo": True}) == "Promo" and versions.treatment({"border_color": "borderless"}) == "Borderless"
assert versions.treatment({"frame_effects": ["showcase"]}) == "Showcase" and versions.treatment({"frame_effects": ["extendedart"]}) == "Extended Art"
assert versions.treatment({}) == "Regular"
print("tests_matcher: ok")
