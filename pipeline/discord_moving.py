#!/usr/bin/env python3
"""Post #whats-moving after a new week's signals.json is published.

Runs from GitHub Actions on a push of signals.json to main (the box publish).
Reads DISCORD_MOVING_WEBHOOK. A missing secret, a same-week re-run, an empty
Potential Risers and New Card Impact pair, or any Discord/network error exits 0.

Usage: discord_moving.py NEW.json [PREV.json]
PREV defaults to the previous commit's signals.json (git show HEAD^:signals.json).
"""
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

from discord_username import DISCORD_USERNAME

MARKET_SIGNALS_URL = "https://tcguardian-radar.vercel.app/market-signals"
DISCLAIMER = (
    "⚠️ Signal, not fact. This is what TCG YouTubers said this week. "
    "It can be wrong. Not financial advice."
)
LINK_LINE = f"[Open Market Signals]({MARKET_SIGNALS_URL})"
MAX_CHARS = 2000


class DiscordError(Exception):
    pass


def week_key(doc):
    """ISO year and week of window.end, else the run_id date. None if neither parses."""
    if not isinstance(doc, dict):
        return None
    raw = (doc.get("window") or {}).get("end") if isinstance(doc.get("window"), dict) else None
    if not (isinstance(raw, str) and len(raw) >= 10):
        raw = doc.get("run_id") or ""
    try:
        day = dt.date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None
    iso = day.isocalendar()
    return (iso[0], iso[1])


def is_new_week(new, prev):
    """True only when both files have a week and the new file's week is different."""
    if not isinstance(prev, dict):
        return False
    new_week, prev_week = week_key(new), week_key(prev)
    return bool(new_week and prev_week and new_week != prev_week)


def _creator(item):
    sources = item.get("sources")
    if not isinstance(sources, list) or not sources or not isinstance(sources[0], dict):
        return ""
    src = sources[0]
    return str(src.get("channel_name") or src.get("channel") or "").strip()


def _bullet(card, creator, why):
    card = str(card or "").strip()
    if not card:
        return None
    line = f"- Card name: {card}"
    if creator:
        line += f" | Creator: {creator}"
    if why:
        line += f" | Why: {why}"
    return line


def _riser_line(item):
    reasons = item.get("reasons") if isinstance(item.get("reasons"), list) else []
    why = "; ".join(part for part in (str(r).strip() for r in reasons) if part)
    return _bullet(item.get("card"), _creator(item), why)


def _impact_line(item):
    effect = str(item.get("effect") or "").strip()
    existing = str(item.get("existing_card") or "").strip()
    why = f"makes {existing} {effect}" if effect and existing else ""
    return _bullet(item.get("new_card"), _creator(item), why)


def _lines(items, line_fn):
    out = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        line = line_fn(item)
        if line:
            out.append(line)
        if len(out) == 5:
            break
    return out


def _render(risers, impacts):
    parts = [DISCLAIMER, ""]
    if risers:
        parts.append("📈 Potential Risers")
        parts.extend(risers)
        parts.append("")
    if impacts:
        parts.append("💥 New Card Impact")
        parts.extend(impacts)
        parts.append("")
    parts.append(LINK_LINE)
    return "\n".join(parts)


def build_message(doc):
    """Discord content, or None when both sections have nothing to say.

    Uses potential_risers and impact_pairs only, in file order, at most five
    each. A line that would push the text past 2000 characters is skipped
    whole. Stored reasons and effects are copied; nothing is calculated.
    """
    if not isinstance(doc, dict):
        return None
    risers = _lines(doc.get("potential_risers"), _riser_line)
    impacts = _lines(doc.get("impact_pairs"), _impact_line)

    def fits(chosen_risers, chosen_impacts):
        return len(_render(chosen_risers, chosen_impacts)) <= MAX_CHARS

    # Keep higher-ranked lines. Skip a line that does not fit so a shorter
    # one under it can still be posted. Dropping a line never cuts it in half.
    chosen_risers, chosen_impacts = [], []
    for line in risers:
        if fits(chosen_risers + [line], chosen_impacts):
            chosen_risers.append(line)
    for line in impacts:
        if fits(chosen_risers, chosen_impacts + [line]):
            chosen_impacts.append(line)
    if not chosen_risers and not chosen_impacts:
        return None
    return _render(chosen_risers, chosen_impacts)


def post_discord(url, content):
    data = json.dumps({"content": content, "username": DISCORD_USERNAME}).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "tcg-market-signals"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
            if getattr(resp, "status", 200) >= 300:
                raise DiscordError(f"HTTP {resp.status}")
    except DiscordError:
        raise
    except urllib.error.HTTPError as e:
        raise DiscordError(f"HTTP {e.code}")
    except Exception:
        raise DiscordError("request failed")


def load_prev_git():
    try:
        raw = subprocess.check_output(
            ["git", "show", "HEAD^:signals.json"],
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return doc if isinstance(doc, dict) else None


def run(new, prev, webhook, post=post_discord):
    """Return (exit_code, status). Discord problems and skips are exit 0."""
    if not str(webhook or "").strip():
        return 0, "DISCORD_MOVING_WEBHOOK missing; skip"
    if not is_new_week(new, prev):
        why = "previous signals.json unavailable; skip" if not isinstance(prev, dict) else "same week; skip"
        return 0, why
    msg = build_message(new)
    if not msg:
        return 0, "Potential Risers and New Card Impact empty; skip"
    try:
        post(str(webhook).strip(), msg)
    except DiscordError as e:
        return 0, f"Discord post failed (ignored): {e}"
    return 0, f"posted {len(msg)} chars"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    new_path = argv[0] if argv else "signals.json"
    try:
        with open(new_path, encoding="utf-8") as f:
            new = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"could not read {new_path}: {e.__class__.__name__}; skip")
        return 0
    if len(argv) >= 2:
        try:
            with open(argv[1], encoding="utf-8") as f:
                prev = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"could not read previous file: {e.__class__.__name__}; skip")
            return 0
    else:
        prev = load_prev_git()
    code, status = run(new, prev, os.environ.get("DISCORD_MOVING_WEBHOOK", ""))
    print(status)
    return code


if __name__ == "__main__":
    sys.exit(main())
