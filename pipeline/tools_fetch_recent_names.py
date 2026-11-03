#!/usr/bin/env python3
"""Write cache/recent_names.json: every card name first printed (not reprints) since settings.new_card_since (Scryfall search).
The matcher uses it so a bare short name ("Danitha") resolves to the new-set card, not an older card with the same prefix.
Refresh weekly with cardnames.json."""
import sys, os, urllib.parse
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from common import SETTINGS, save, log
import common
url = "https://api.scryfall.com/cards/search?unique=cards&q=" + urllib.parse.quote(f"game:paper not:reprint date>={SETTINGS['new_card_since']}")
names = set()
while url:
    d = common.scry_get(url, fresh_key="recent")  # not persisted: scry_save() is not called
    if d.get("object") != "list": raise SystemExit(f"Scryfall search failed: {d}")
    names.update(c["name"] for c in d["data"]); url = d.get("next_page") if d.get("has_more") else None
save("cache/recent_names.json", {"since": SETTINGS["new_card_since"], "data": sorted(names)})
log(f"{len(names)} recent card names since {SETTINGS['new_card_since']}")
