#!/usr/bin/env python3
"""Rules for the #whats-moving Discord post. Run: python3 pipeline/tests_discord_moving.py"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import discord_moving as d

URL = "https://tcguardian-radar.vercel.app/market-signals"


def doc(end, risers=None, impacts=None, **extra):
    out = {
        "window": {"end": end},
        "run_id": f"{end}_1313",
        "potential_risers": [] if risers is None else risers,
        "impact_pairs": [] if impacts is None else impacts,
        "card_vibes": [{"card": "Vibe Card", "vibe": "positive"}],
        "ban_alerts": [{"card": "Ban Guess", "status": "speculation"}],
    }
    out.update(extra)
    return out


def riser(card, creator, why="", handle="@hidden"):
    item = {
        "card": card,
        "reasons": [why] if why else [],
        "price": {"change_7d_pct": 82.2, "display": "$4.47"},
        "sources": [{"channel": handle, "channel_name": creator, "quote": "a long quote that must stay out"}],
    }
    return item


def impact(new, existing, effect, creator):
    return {
        "new_card": new,
        "existing_card": existing,
        "effect": effect,
        "sources": [{"channel": "@hidden", "channel_name": creator}],
    }


def test_week():
    monday = doc("2026-11-02")
    sunday = doc("2026-11-08")
    next_monday = doc("2026-11-09")
    assert d.week_key(monday) == d.week_key(sunday)
    assert d.week_key(monday) != d.week_key(next_monday)
    assert d.is_new_week(sunday, monday) is False
    assert d.is_new_week(next_monday, monday) is True
    assert d.is_new_week(next_monday, None) is False
    assert d.is_new_week(next_monday, {}) is False
    # run_id date is the fallback when window.end is missing
    assert d.week_key({"run_id": "2026-11-09_1313"}) == d.week_key(next_monday)


def test_message_shape():
    new = doc(
        "2026-11-09",
        risers=[
            riser("Dark Matter Manipulator", "Mattcaster Mage MTG", "showcase foil up about 28%"),
            riser("Sphinx's Approach", "EugiGamez", ""),
            riser("", "Nobody", "no card name"),
        ],
        impacts=[impact("Troubling Tribbles", "Viscera Seer", "stronger", "Tolarian Community College")],
    )
    msg = d.build_message(new)
    assert msg.startswith(d.DISCLAIMER)
    assert msg.endswith(f"[Open Market Signals]({URL})")
    assert "- Card name: Dark Matter Manipulator | Creator: Mattcaster Mage MTG | Why: showcase foil up about 28%" in msg
    sphinx = next(line for line in msg.splitlines() if "Sphinx's Approach" in line)
    assert sphinx == "- Card name: Sphinx's Approach | Creator: EugiGamez"
    two = d._riser_line({"card": "Pair", "reasons": ["foil up about 20%", "foil up about 42%"], "sources": [{"channel_name": "Mattcaster Mage MTG"}]})
    assert two == "- Card name: Pair | Creator: Mattcaster Mage MTG | Why: foil up about 20%; foil up about 42%"
    assert "- Card name: Troubling Tribbles | Creator: Tolarian Community College | Why: makes Viscera Seer stronger" in msg
    assert "Vibe Card" not in msg and "Card Vibes" not in msg
    assert "Ban Guess" not in msg
    assert "82.2" not in msg and "$4.47" not in msg
    assert "@hidden" not in msg
    assert "a long quote" not in msg
    assert len(msg) <= 2000


def test_one_section_and_top_five():
    risers = [riser(f"Card {i}", f"Channel {i}", "reason") for i in range(8)]
    msg = d.build_message(doc("2026-11-09", risers=risers, impacts=[]))
    assert "📈 Potential Risers" in msg
    assert "💥 New Card Impact" not in msg
    assert msg.count("\n- ") == 5
    assert "Card 0" in msg and "Card 4" in msg and "Card 5" not in msg
    only_impact = d.build_message(doc("2026-11-09", impacts=[impact("New", "Old", "weaker", "Creator")]))
    assert "📈 Potential Risers" not in only_impact
    assert "Why: makes Old weaker" in only_impact
    assert d.build_message(doc("2026-11-09")) is None
    assert d.build_message(doc("2026-11-09", impacts=[{"new_card": "  ", "effect": "stronger", "existing_card": "X"}])) is None


def test_length_cap():
    huge = "word " * 800
    risers = [riser(f"Card {i}", "Channel", huge) for i in range(5)]
    impacts = [impact(f"New {i}", "Old Card", "stronger", "Channel") for i in range(5)]
    msg = d.build_message(doc("2026-11-09", risers=risers, impacts=impacts))
    assert msg is not None and len(msg) <= 2000
    assert msg.startswith(d.DISCLAIMER) and URL in msg
    assert "word word" not in msg
    assert "New 0" in msg and "💥 New Card Impact" in msg
    # a line that cannot fit is skipped; a later short line still posts
    mixed = d.build_message(doc("2026-11-09", risers=[riser("Huge", "Channel", "x" * 3000), riser("Short", "Channel", "fits")]))
    assert mixed and "Huge" not in mixed and "Short" in mixed and len(mixed) <= 2000
    assert d.build_message(doc("2026-11-09", risers=[riser("Only", "Channel", "x" * 3000)])) is None


def test_run_skips_and_swallows_discord_errors():
    calls = []
    new = doc("2026-11-09", risers=[riser("Card", "Channel", "reason")])
    prev = doc("2026-11-02", risers=[riser("Old", "Channel", "reason")])

    code, status = d.run(new, prev, "", post=lambda *a: calls.append(a))
    assert code == 0 and "missing" in status and calls == []

    code, status = d.run(new, prev, "https://discord.example/webhook", post=lambda *a: calls.append(a))
    assert code == 0 and status.startswith("posted ") and len(calls) == 1
    assert calls[0][0] == "https://discord.example/webhook"
    assert URL in calls[0][1] and len(calls[0][1]) <= 2000

    code, status = d.run(doc("2026-11-08", risers=[riser("Card", "Channel", "reason")]), prev, "https://discord.example/webhook", post=lambda *a: calls.append(a))
    assert code == 0 and status == "same week; skip" and len(calls) == 1

    code, status = d.run(new, None, "https://discord.example/webhook", post=lambda *a: (_ for _ in ()).throw(AssertionError("posted")))
    assert code == 0 and "unavailable" in status

    def boom(url, content):
        raise d.DiscordError("HTTP 400")

    code, status = d.run(new, prev, "https://discord.example/webhook", post=boom)
    assert code == 0 and status == "Discord post failed (ignored): HTTP 400"
    code, status = d.run(doc("2026-11-09"), prev, "https://discord.example/webhook", post=boom)
    assert code == 0 and "empty" in status


def test_live_file_stays_in_bounds():
    root = os.path.join(os.path.dirname(__file__), "..", "signals.json")
    with open(root, encoding="utf-8") as f:
        live = json.load(f)
    msg = d.build_message(live)
    assert msg and len(msg) <= 2000
    assert URL in msg and msg.startswith(d.DISCLAIMER)
    assert "Card Vibes" not in msg
    # file order, not a re-sort: first posted riser is the first named entry
    first = next(r["card"] for r in live["potential_risers"] if r.get("card"))
    assert f"- Card name: {first} |" in msg


def test_main_bad_file_does_not_raise():
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = d.main(["/tmp/does-not-exist-signals.json"])
    assert code == 0 and "skip" in buf.getvalue()


if __name__ == "__main__":
    test_week()
    test_message_shape()
    test_one_section_and_top_five()
    test_length_cap()
    test_run_skips_and_swallows_discord_errors()
    test_live_file_stays_in_bounds()
    test_main_bad_file_does_not_raise()
    print("ok")
