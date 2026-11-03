#!/usr/bin/env python3
"""Matcher tests: a bare short name shared with a new-set card. Run: python tests_matcher.py (needs cache/cardnames.json + cache/recent_names.json)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import matcher
from common import norm
def cards(text): return [c for (_, _, c, _) in matcher.find(norm(text).split())]
def check(text, want):
    got = cards(text); assert got == want, f"{text!r}: got {got}, want {want}"
# resolve_short rules
R = {"New A", "New B", "New C"}
assert matcher.resolve_short(["Old X"], R) == "Old X"
assert matcher.resolve_short(["Old X", "New A"], R) == "New A"          # single current-set card wins over older prefix
assert matcher.resolve_short(["Old X", "New A", "New B"], R) is None    # two new cards: ambiguous, never the old card
assert matcher.resolve_short(["Old X", "Old Y"], R) == "Old X"          # no new card: unchanged behaviour
# Reality Fracture (fra): two new Danithas / Vraskas / Saheelis -> bare name is not credited to an older card
for short in ("danitha", "vraska", "saheeli"):
    assert short in matcher.AMBIG, short
assert "Danitha, Benalia's Hope" not in cards("good danitha good")
assert "Vraska, Betrayal's Sting" not in cards("vraska is a very good magic card")
assert "Saheeli, Consul of Oversight" not in cards("ill play the saheeli")
assert cards("danithas also really good here") == []                    # fuzzy plural of an ambiguous name
# ambiguous hits are reported with every new candidate (03 queues them as one 'could be any of these' item)
matcher.find(norm("good danitha good").split())
assert [(L, s) for _, L, s in matcher.AMBIGUOUS_HITS] == [(1, "danitha")], matcher.AMBIGUOUS_HITS
assert matcher.AMBIG["danitha"] == ["Danitha, Spear of Agony", "Danitha, Sword of Hope"]
assert matcher.AMBIG["vraska"] == ["Vraska, Soul of Stone", "Vraska, the Cutting Glare"]
assert matcher.AMBIG["saheeli"] == ["Saheeli, Consul of Oversight", "Saheeli, Jewel of Avishkar"]
assert "Danitha, Benalia's Hope" not in matcher.AMBIG["danitha"]          # older card not offered by default
matcher.find(norm("danithas also good").split()); assert [s for _, _, s in matcher.AMBIGUOUS_HITS] == ["danitha"]
matcher.find(norm("danitha sword of hope").split()); assert matcher.AMBIGUOUS_HITS == []
# full names still win (longest n-gram first)
check("danitha sword of hope is good", ["Danitha, Sword of Hope"])
check("danitha spear of agony", ["Danitha, Spear of Agony"])
check("danitha benalias hope in commander", ["Danitha, Benalia's Hope"])
check("vraska soul of stone", ["Vraska, Soul of Stone"])
check("vraska the cutting glare", ["Vraska, the Cutting Glare"])
check("saheeli jewel of avishkar", ["Saheeli, Jewel of Avishkar"])
check("vraska betrayals sting", ["Vraska, Betrayal's Sting"])
# one new card shares the prefix -> bare name goes to the new card; old full name still works
check("whats great about a free emrakul", ["Emrakul, the Exigent Doom"])
check("emrakul the aeons torn", ["Emrakul, the Aeons Torn"])
check("dont need the yargle", ["Yargle, Goliath of Otaria"])
# unrelated short names unchanged
check("ragavan is great", ["Ragavan, Nimble Pilferer"])
# ambiguous grouping (lib/ambiguous.py)
import ambiguous, versions
def it(short, vibe, ch="@a"): return {"card_ok": True, "vibe": vibe, "_item": {"kind": "mention", "card": None, "short_name": short, "candidates": ["X1", "X2"], "channel": ch}}
J = {"1": it("x", "positive"), "2": it("x", "negative", "@b"), "3": it("x", "none"), "4": {"card_ok": True, "vibe": "positive", "_item": {"kind": "mention", "card": "Y", "channel": "@a"}}}
G = ambiguous.collect(J)
assert list(G) == ["x"] and len(G["x"]["pos"]) == 1 and len(G["x"]["neg"]) == 1 and G["x"]["ch"] == {"@a", "@b"}
fake = lambda n: dict(name=n, scryfall_id=n, image=None)
out = ambiguous.build(G, fake, lambda n: {}, lambda c: {"display": "unavailable"}, lambda n: "u", lambda j, cs, q, s: {"video_id": "v"})
assert out[0]["options"][0]["card"] == "X1" and out[0]["positive"] == 1 and out[0]["negative"] == 1 and out[0]["label"] == "Could be any of these"
# version groups come only from Scryfall fields
assert versions.treatment({"promo": True}) == "Promo" and versions.treatment({"border_color": "borderless"}) == "Borderless"
assert versions.treatment({"frame_effects": ["showcase"]}) == "Showcase" and versions.treatment({"frame_effects": ["extendedart"]}) == "Extended Art"
assert versions.treatment({}) == "Regular"
print("tests_matcher: ok")
