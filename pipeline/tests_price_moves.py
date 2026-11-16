#!/usr/bin/env python3
"""Rules for the daily price-jump and price-drop posts.

Run: python3 pipeline/tests_price_moves.py
The file-parse cases need ijson (`pip install ijson`).
"""
import datetime as dt
import io
import json
import lzma
import os
import sys
import tempfile
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import price_moves as pm
from card_link import RADAR_URL

DATE = "2026-11-04"
PREV = "2026-11-03"
FORBIDDEN = ("mtgjson", "tcgplayer", "scryfall", "card kingdom", "cardkingdom", "http", "www.")


def card(uuid, name, release="2020-01-01", **extra):
    row = {
        "uuid": uuid,
        "name": name,
        "release": release,
        "set_code": "old",
        "language": "English",
        "finishes": ["nonfoil"],
        "layout": "normal",
        "set_type": "expansion",
        "online_only": False,
        "foil_only": False,
        "paper": True,
    }
    row.update(extra)
    return row


def hist(then_price, now_price, then_date=PREV, now_date=DATE):
    """Baseline plus enough earlier days that the history rule is satisfied."""
    out = {then_date: then_price, now_date: now_price}
    day = dt.date.fromisoformat(then_date)
    for i in range(1, pm.MIN_HISTORY_DAYS):
        out[(day - dt.timedelta(days=i)).isoformat()] = then_price
    return out


def names(rows):
    return [row["name"] for row in rows]


def assert_message(msg, title, up):
    assert msg.startswith(title)
    assert msg.endswith(pm.FOOTER)
    assert msg.splitlines()[-1] == "Not financial advice."
    assert msg.count("Not financial advice.") == 1
    arrow = "↑" if up else "↓"
    assert arrow in msg
    low = msg.lower().replace(RADAR_URL.lower(), "")
    for word in FORBIDDEN:
        assert word not in low, word
    assert len(msg) <= pm.MAX_CHARS


def test_thresholds_gap_and_price_date():
    cards = [
        card("jump", "Jump Card"),
        card("bare", "Barely Up"),
        card("cheap", "Too Cheap"),
        card("drop", "Drop Card"),
        card("small-drop", "Small Drop"),
        card("young-drop", "Cheap Then"),
        card("gap2", "Two Day Gap"),
        card("gap3", "Three Day Gap"),
        card("stale", "Stale Card"),
        card("flat", "Flat Card"),
    ]
    prices = {
        "jump": hist(5.00, 6.00),          # +20.0, now >= 5
        "bare": hist(5.00, 5.99),          # +19.8
        "cheap": hist(4.00, 4.90),         # +22.5 but now < 5
        "drop": hist(5.00, 4.00),          # -20.0, then >= 5
        "small-drop": hist(10.00, 8.10),   # -19.0
        "young-drop": hist(4.99, 1.00),    # then < 5
        "gap2": hist(5.00, 7.00, "2026-11-02", DATE),
        "gap3": hist(5.00, 9.00, "2026-11-01", DATE),
        "stale": hist(5.00, 8.00, "2026-11-02", "2026-11-03"),
        "flat": hist(8.00, 8.00),
    }
    got = pm.select_moves(cards, prices)
    assert got["price_date"] == DATE
    assert names(got["jumps"]) == ["Two Day Gap", "Jump Card"]
    assert names(got["drops"]) == ["Drop Card"]
    assert got["jumps"][1]["pct"] == 20.0
    assert got["drops"][0]["pct"] == -20.0
    assert got["jumps"][1]["price_then"] == 5.0
    assert got["jumps"][1]["price_now"] == 6.0


def test_cheapest_printing_and_new_sets():
    cards = [
        card("old-expensive", "Bolt", set_code="aaa", release="2010-01-01"),
        card("old-cheap", "Bolt", set_code="bbb", release="2020-01-01"),
        card("other-expensive", "Only Expensive"),
        card("other-cheap", "Only Expensive", set_code="zzz", release="2019-01-01"),
        card("brand-new", "Preview", release="2026-10-25"),  # 10 days before DATE
        card("day-14", "Just Old Enough", release="2026-10-21"),
        card("day-13", "Still New", release="2026-10-22"),
        card("future", "Future", release="2026-12-01"),
        card("undated", "Undated", release=None),
        card("ahead", "Ahead", release="2026-11-01"),  # 3 days old, later price date
    ]
    prices = {
        "old-expensive": hist(5.00, 10.00),   # +100, now 10
        "old-cheap": hist(5.00, 6.00),        # +20, now 6, this printing wins
        "other-expensive": hist(5.00, 10.00),
        "other-cheap": hist(3.00, 4.00),      # cheapest now is 4, so the card is out
        "brand-new": hist(5.00, 9.00),
        "day-14": hist(5.00, 8.00),
        "day-13": hist(5.00, 8.00),
        "future": hist(5.00, 8.00),
        "undated": hist(5.00, 8.00),
        # Newer than DATE, but the set is still inside 14 days, so it must not move the price date.
        "ahead": {"2026-11-04": 5.0, "2026-11-05": 8.0},
    }
    got = pm.select_moves(cards, prices)
    assert got["price_date"] == DATE
    assert names(got["jumps"]) == ["Just Old Enough", "Bolt"]
    bolt = next(row for row in got["jumps"] if row["name"] == "Bolt")
    assert bolt["price_now"] == 6.0 and bolt["pct"] == 20.0
    assert got["drops"] == []


def test_skipped_printings_and_top_15():
    cards = [
        card("jp", "Japanese", language="Japanese"),
        card("token", "Token", layout="token"),
        card("art", "Art", layout="art_series"),
        card("list", "List Slot", set_code="PLST"),
        card("mb", "Mystery List", set_code="mb1"),
        card("online", "Online", online_only=True),
        card("foilset", "Foil Set", foil_only=True),
        card("foilcard", "Foil Card", finishes=["foil"]),
        card("digital", "Digital", paper=False),
        card("sld", "Secret Lair Card", set_code="sld", set_type="box"),
        card("paper-unknown", "Unknown Paper", paper=None),
    ]
    prices = {c["uuid"]: hist(5.00, 8.00) for c in cards}
    kept = pm.select_moves(cards, prices)
    assert names(kept["jumps"]) == ["Unknown Paper"]

    many = []
    prices = {}
    for i in range(16):
        many.append(card(f"c{i:02d}", f"Card {i:02d}"))
        # 36% down to 21%, one point at a time. Card 00 is the largest move.
        prices[f"c{i:02d}"] = hist(5.00, round(5 * (1 + (36 - i) / 100), 2))
    got = pm.select_moves(many, prices)
    assert len(got["jumps"]) == 15
    assert names(got["jumps"])[0] == "Card 00"
    assert "Card 15" not in names(got["jumps"])
    assert got["jumps"][0]["pct"] >= got["jumps"][-1]["pct"]


def test_secret_lair_excluded():
    cards = [
        card("sld", "Drop", set_code="SLD", set_type="box", set_name="Secret Lair Drop"),
        card("slz", "Zeta", set_code="slz", set_type="box", set_name="The Zeta Set"),
        card("slc", "Countdown", set_code="SLC", set_type="box", set_name="Secret Lair Countdown"),
        card("slp", "Promo", set_code="slp", set_type="promo", set_name="Secret Lair Promo"),
        card("slu", "Ultimate", set_code="slu", set_type="box"),
        card("pssc", "Planes", set_code="pssc", set_type="memorabilia"),
        card("child", "Child Set", set_code="xx1", parent_code="SLD", set_name="Countdown Kit"),
        card("named", "Named Only", set_code="zz9", set_name="Secret Lair Showcase"),
        card("slx", "Universes Within", set_code="slx", set_type="masters", parent_code="SLD"),
        card("box", "Challenger Card", set_code="q06", set_type="box", set_name="Challenger Decks 2021"),
    ]
    prices = {c["uuid"]: hist(5.00, 8.00) for c in cards}
    got = pm.select_moves(cards, prices)
    assert names(got["jumps"]) == ["Challenger Card", "Universes Within"]
    assert got["drops"] == []


def test_short_history_skipped():
    # Six prices on or before the baseline, then today's move: still too new.
    day = dt.date.fromisoformat(PREV)
    short = {DATE: 8.00}
    for i in range(pm.MIN_HISTORY_DAYS - 1):
        short[(day - dt.timedelta(days=i)).isoformat()] = 20.00
    assert len([d for d in short if d <= PREV]) == pm.MIN_HISTORY_DAYS - 1

    ready = hist(10.00, 12.00)  # exactly MIN_HISTORY_DAYS points on or before the baseline
    assert len([d for d in ready if d <= PREV]) == pm.MIN_HISTORY_DAYS

    cards = [
        card("short", "New Printing", set_code="zzz", release="2010-01-01"),
        card("long", "New Printing", set_code="aaa", release="2000-01-01"),
        card("only-short", "Only Short", set_code="old", release="2015-01-01"),
        card("ready", "Established", release="2018-06-01"),
        card("ahead-short", "Future Spike", release="2010-01-01"),
    ]
    prices = {
        "short": short,                 # cheaper now, but not enough history to be the printing
        "long": ready,                  # +20, this printing is the one that can alert
        "only-short": {PREV: 20.00, DATE: 8.00},
        "ready": hist(5.00, 8.00),
        # Newer than DATE, but only two prices, so it must not move the price date.
        "ahead-short": {DATE: 5.00, "2026-11-05": 12.00},
    }
    got = pm.select_moves(cards, prices)
    assert got["price_date"] == DATE
    assert names(got["jumps"]) == ["Established", "New Printing"]
    chosen = next(row for row in got["jumps"] if row["name"] == "New Printing")
    assert chosen["price_now"] == 12.0 and chosen["set_code"] == "aaa"
    assert "Only Short" not in names(got["jumps"]) + names(got["drops"])


def test_direct_low_ignored():
    node = {"paper": {"tcgplayer": {
        "buylist": {"normal": {PREV: 1.0, DATE: 100.0}},
        "directLow": {"normal": {PREV: 5.0, DATE: 23.86}},
        "retail": {
            "normal": hist(17.65, 23.86),
            "foil": {PREV: 17.65, DATE: 40.0},
        },
    }}}
    series = pm._normal_retail(node)
    assert series[DATE] == 23.86
    assert series[PREV] == 17.65
    assert 100.0 not in series.values()
    assert 40.0 not in series.values()
    assert pm._normal_retail({"paper": {"tcgplayer": {
        "buylist": {"normal": {PREV: 5.0, DATE: 9.0}},
        "retail": {"foil": {PREV: 5.0, DATE: 9.0}},
    }}}) == {}

    # The retail series itself holds Direct Low for today. The market quote replaces it.
    retail = pm.select_moves(
        [card("bg", "Barbarian General", set_code="ptk", product_id=427, group_id=88)],
        {"bg": hist(17.65, 23.86)},
    )
    assert names(retail["jumps"]) == ["Barbarian General"]
    quotes = {427: {"market": 17.66, "direct": 23.86}}
    fixed = pm.apply_market_quotes(retail, quotes)
    assert fixed["jumps"] == []
    assert fixed["drops"] == []

    # A retail point that is already the market quote is kept, even if Direct Low differs.
    real = pm.select_moves(
        [card("djinn", "Serendib Djinn", set_code="arn", product_id=3238)],
        {"djinn": hist(148.75, 115.56)},
    )
    kept = pm.apply_market_quotes(real, {3238: {"market": 115.56, "direct": None}})
    assert names(kept["drops"]) == ["Serendib Djinn"]
    assert kept["drops"][0]["price_now"] == 115.56

    # No market quote: do not keep a point that is only the Direct Low.
    only_direct = pm.apply_market_quotes(retail, {427: {"market": None, "direct": 23.86}})
    assert only_direct["jumps"] == []


def test_tie_order_and_message():
    cards = [
        card("b", "Beta", release="2020-01-01", set_code="b"),
        card("a", "Alpha", release="2020-01-01", set_code="a"),
    ]
    prices = {"a": hist(5, 6), "b": hist(5, 6)}
    got = pm.select_moves(cards, prices)
    assert names(got["jumps"]) == ["Alpha", "Beta"]

    jumps = pm.build_message(pm.TITLES["jumps"], got["jumps"], True)
    drops = pm.build_message(pm.TITLES["drops"], [dict(name="Drop Card", price_then=8, price_now=5.2, pct=-35)], False)
    assert_message(jumps, "Price jumps (1-day)", True)
    assert_message(drops, "Price drops (1-day)", False)
    assert "- Card name: Alpha" in jumps
    assert "game=magic&card=Alpha" in jumps
    assert "game=magic&card=Drop+Card" in drops
    assert "- Then: $5.00 → Now: $6.00 (↑20.0%)" in jumps
    assert "- Then: $8.00 → Now: $5.20 (↓35.0%)" in drops
    assert pm.build_message(pm.TITLES["jumps"], [], True) is None

    huge = {"name": "H" * 3000, "price_then": 5, "price_now": 8, "pct": 60}
    short = {"name": "Short", "price_then": 5, "price_now": 7, "pct": 40}
    assert pm.build_message(pm.TITLES["jumps"], [huge], True) is None
    trimmed = pm.build_message(pm.TITLES["jumps"], [short, huge], True)
    assert trimmed and "Short" in trimmed and "HHH" not in trimmed
    assert trimmed.endswith(pm.FOOTER)


def test_settle_secrets_errors_and_same_date():
    result = {
        "price_date": DATE,
        "jumps": [dict(name="Jump Card", price_then=5, price_now=7, pct=40)],
        "drops": [dict(name="Drop Card", price_then=10, price_now=7, pct=-30)],
    }
    calls = []

    def record(url, content):
        calls.append((url, content))

    state, lines = pm.settle({"jumps": None, "drops": None}, result, {}, record, dry_run=True)
    assert state == {"jumps": None, "drops": None}
    assert calls == []
    assert any(line.startswith("dry-run jumps:\nPrice jumps (1-day)") for line in lines)
    blob = "\n".join(lines).lower().replace(RADAR_URL.lower(), "")
    for word in FORBIDDEN:
        assert word not in blob

    state, lines = pm.settle({"jumps": None, "drops": None}, result, {"jumps": "", "drops": "https://discord.example/drop"}, record, False)
    assert state["jumps"] is None and state["drops"] == DATE
    assert calls and calls[0][0] == "https://discord.example/drop"
    assert "DISCORD_JUMPS_WEBHOOK missing; skip" in lines
    assert "https://discord.example/drop" not in "\n".join(lines)

    def boom(url, content):
        raise pm.DiscordError("HTTP 500 " + url)

    calls.clear()
    state, lines = pm.settle({"jumps": None, "drops": None}, result, {"jumps": "https://discord.com/api/webhooks/1/secret-value", "drops": ""}, boom, False)
    assert state == {"jumps": None, "drops": None}
    assert "Discord post failed (ignored): HTTP 500" in "\n".join(lines)
    os.environ["DISCORD_JUMPS_WEBHOOK"] = "https://discord.com/api/webhooks/1/secret-value"
    try:
        state, lines = pm.settle(
            {"jumps": None, "drops": None},
            result,
            {"jumps": os.environ["DISCORD_JUMPS_WEBHOOK"], "drops": ""},
            boom,
            False,
        )
    finally:
        os.environ.pop("DISCORD_JUMPS_WEBHOOK", None)
    assert "secret-value" not in "\n".join(lines)
    assert "***" in "\n".join(lines)

    empty = {"price_date": DATE, "jumps": [], "drops": []}
    state, lines = pm.settle({"jumps": None, "drops": None}, empty, {"jumps": "https://discord.example/j"}, record, False)
    assert state == {"jumps": DATE, "drops": DATE}
    assert calls == []
    assert "no cards; no post" in "\n".join(lines)

    calls.clear()
    state, lines = pm.settle({"jumps": DATE, "drops": None}, result, {"jumps": "https://discord.example/j", "drops": "https://discord.example/d"}, record, False)
    assert state == {"jumps": DATE, "drops": DATE}
    assert len(calls) == 1 and calls[0][0].endswith("/d")
    assert "already settled" in lines[0]


def test_files_and_main(tmp):
    try:
        import ijson  # noqa: F401
    except ImportError:
        raise SystemExit("ijson is required for the price file test")

    printings = {
        "data": {
            "LEA": {
                "code": "LEA",
                "name": "Limited Edition Alpha",
                "releaseDate": "1993-08-05",
                "type": "core",
                "isOnlineOnly": False,
                "isFoilOnly": False,
                "cards": [{
                    "uuid": "u1",
                    "name": "Sol Ring",
                    "language": "English",
                    "finishes": ["nonfoil", "foil"],
                    "availability": ["paper"],
                    "layout": "normal",
                    "identifiers": {"tcgplayerProductId": 1001},
                }],
            },
            "SLD": {
                "code": "SLD",
                "name": "Secret Lair Drop",
                "releaseDate": "2019-12-02",
                "type": "box",
                "isOnlineOnly": False,
                "isFoilOnly": False,
                "cards": [{
                    "uuid": "u3",
                    "name": "Lair Ring",
                    "language": "English",
                    "finishes": ["nonfoil"],
                    "availability": ["paper"],
                    "layout": "normal",
                }],
            },
            "OLD": {
                "code": "OLD",
                "name": "Old Expansion",
                "releaseDate": "2010-01-01",
                "type": "expansion",
                "cards": [{
                    "uuid": "u4",
                    "name": "Short History",
                    "language": "English",
                    "finishes": ["nonfoil"],
                    "availability": ["paper"],
                    "layout": "normal",
                }],
            },
            "PLST": {
                "code": "PLST",
                "releaseDate": "2020-01-01",
                "type": "masters",
                "cards": [{
                    "uuid": "u2",
                    "name": "List Card",
                    "language": "English",
                    "finishes": ["nonfoil"],
                    "availability": ["paper"],
                    "layout": "normal",
                }],
            },
        }
    }
    prices = {
        "data": {
            "u1": {"paper": {"tcgplayer": {
                "buylist": {"normal": {PREV: 1.0, DATE: 100.0}},
                "directLow": {"normal": {PREV: 5.0, DATE: 80.0}},
                "retail": {
                    "normal": hist(5.0, 7.5),
                    "foil": {PREV: 5.0, DATE: 40.0},
                },
            }}},
            "u2": {"paper": {"tcgplayer": {"retail": {"normal": hist(5.0, 9.0)}}}},
            "u3": {"paper": {"tcgplayer": {"retail": {"normal": hist(5.0, 9.0)}}}},
            "u4": {"paper": {"tcgplayer": {"retail": {"normal": {PREV: 20.0, DATE: 5.0}}}}},
        }
    }
    printings_path = os.path.join(tmp, "printings.json")
    prices_path = os.path.join(tmp, "prices.json.xz")
    state_path = os.path.join(tmp, "state.json")
    with open(printings_path, "w", encoding="utf-8") as handle:
        json.dump(printings, handle)
    with lzma.open(prices_path, "wt", encoding="utf-8") as handle:
        json.dump(prices, handle)
    pm.save_state(state_path, {"jumps": None, "drops": None})

    got = pm.compute(prices_path, printings_path)
    assert got["price_date"] == DATE
    assert names(got["jumps"]) == ["Sol Ring"]
    assert got["jumps"][0]["price_now"] == 7.5
    assert got["jumps"][0]["product_id"] == 1001
    assert "Lair Ring" not in names(got["jumps"])
    assert "Short History" not in names(got["drops"])
    assert got["drops"] == []

    calls = []
    original = pm.post_discord
    pm.post_discord = lambda url, content: calls.append((url, content))
    os.environ["DISCORD_JUMPS_WEBHOOK"] = "https://discord.com/api/webhooks/9/jump-secret"
    os.environ["DISCORD_DROPS_WEBHOOK"] = "https://discord.com/api/webhooks/8/drop-secret"
    argv = ["--prices", prices_path, "--printings", printings_path, "--state", state_path]
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = pm.main(["--dry-run", *argv])
        assert code == 0 and calls == []
        assert json.load(open(state_path)) == {"jumps": None, "drops": None}
        text = buf.getvalue()
        assert "Price jumps (1-day)" in text and "Sol Ring" in text
        assert "jump-secret" not in text and "drop-secret" not in text
        visible = text.lower().replace(RADAR_URL.lower(), "")
        for word in FORBIDDEN:
            assert word not in visible

        buf = io.StringIO()
        with redirect_stdout(buf):
            code = pm.main(argv)
        assert code == 0
        saved = json.load(open(state_path))
        assert saved == {"jumps": DATE, "drops": DATE}
        assert len(calls) == 1  # drops list is empty, so only jumps posts
        assert calls[0][0].endswith("/jump-secret")
        assert "jump-secret" not in buf.getvalue()
        assert set(json.load(open(state_path))) == {"jumps", "drops"}

        with redirect_stdout(io.StringIO()):
            code = pm.main(argv)
        assert code == 0 and len(calls) == 1
    finally:
        pm.post_discord = original
        os.environ.pop("DISCORD_JUMPS_WEBHOOK", None)
        os.environ.pop("DISCORD_DROPS_WEBHOOK", None)

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = pm.main(["--prices", os.path.join(tmp, "missing.json"), "--printings", printings_path])
    assert code == 0 and "no post" in buf.getvalue()


def main():
    test_thresholds_gap_and_price_date()
    test_cheapest_printing_and_new_sets()
    test_skipped_printings_and_top_15()
    test_secret_lair_excluded()
    test_short_history_skipped()
    test_direct_low_ignored()
    test_tie_order_and_message()
    test_settle_secrets_errors_and_same_date()
    with tempfile.TemporaryDirectory() as tmp:
        test_files_and_main(tmp)
    print("ok")


if __name__ == "__main__":
    main()
