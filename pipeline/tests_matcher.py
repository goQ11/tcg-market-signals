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
print("tests_matcher: ok")
