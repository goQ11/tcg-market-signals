#!/usr/bin/env python3
"""Post 1-day price jumps and price drops.

Separate from the Monday signals.json job. Downloads price history on the
runner, posts each list to its own Discord channel, and records only the
price date already settled in price_post_state.json.

A missing secret, an empty list, or a Discord error exits 0.
Saving the price date is the one failure that exits 1.

Usage:
  price_moves.py [--dry-run] [--prices F] [--printings F] [--setlist F] [--state F]
"""
import argparse
import datetime as dt
import json
import lzma
import os
import sys
import urllib.error
import urllib.request
from decimal import Decimal, ROUND_HALF_UP

from card_link import card_href
from discord_username import DISCORD_USERNAME

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STATE = os.path.join(ROOT, "price_post_state.json")
CACHE = os.path.join(ROOT, "cache")

MIN_PRICE = 5.0
MIN_PCT = 20.0
MAX_GAP_DAYS = 2
NEW_SET_DAYS = 14
# Daily TCGplayer retail prices required on or before the baseline.
MIN_HISTORY_DAYS = 7
TOP_N = 15
MAX_CHARS = 2000
FOOTER = "Not financial advice."
TITLES = {"jumps": "Price jumps (1-day)", "drops": "Price drops (1-day)"}
WEBHOOK_ENV = {"jumps": "DISCORD_JUMPS_WEBHOOK", "drops": "DISCORD_DROPS_WEBHOOK"}
# The List, plus Secret Lair. Type "box" is not skipped on its own: it also
# covers Challenger Decks, Game Night, and Guild Kits. A set whose name says
# Secret Lair, or whose parent is SLD or SLZ, is skipped too. SLX (Universes
# Within) is parented under SLD and is not a Secret Lair product.
SKIP_SET_CODES = {"plst", "list", "ulst", "mb1", "mb2", "sld", "slz", "slc", "slp", "slu", "pssc"}
SECRET_LAIR_PARENTS = {"sld", "slz"}
SKIP_LAYOUTS = {"token", "double_faced_token", "art_series"}

PRICES_URL = "https://mtgjson.com/api/v5/AllPrices.json.xz"
PRINTINGS_URL = "https://mtgjson.com/api/v5/AllPrintings.json.xz"
SETLIST_URL = "https://mtgjson.com/api/v5/SetList.json"


class DiscordError(Exception):
    pass


def redact(text):
    out = str(text)
    for key, val in os.environ.items():
        if not val or len(val) < 8:
            continue
        if any(part in key.upper() for part in ("WEBHOOK", "TOKEN", "SECRET", "PASSWORD", "API_KEY")):
            out = out.replace(val, "***")
    return out


def log(msg):
    print(redact(msg), flush=True)


def money_amount(value):
    """Nearest cent, half up."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _whole_number(value):
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_price(value):
    if value in (None, ""):
        return None
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    return price


def same_price(left, right):
    if left is None or right is None:
        return False
    try:
        return money_amount(left) == money_amount(right)
    except (ArithmeticError, ValueError):
        return False


def percent(then_price, now_price):
    return round((now_price - then_price) / then_price * 100, 1)


def _day(value):
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def structurally_ok(card):
    """Filters that do not depend on the price date."""
    name = str(card.get("name") or "").strip()
    if not name:
        return False
    if (card.get("language") or "English") != "English":
        return False
    if card.get("online_only") or card.get("foil_only"):
        return False
    if card.get("paper") is False:
        return False
    finishes = [str(f).lower() for f in (card.get("finishes") or [])]
    if "nonfoil" not in finishes:
        return False
    if str(card.get("layout") or "").lower() in SKIP_LAYOUTS:
        return False
    if str(card.get("set_type") or "").lower() == "token":
        return False
    if str(card.get("set_code") or "").lower() in SKIP_SET_CODES:
        return False
    if "secret lair" in str(card.get("set_name") or "").lower():
        return False
    code = str(card.get("set_code") or "").lower()
    parent = str(card.get("parent_code") or "").lower()
    if parent in SECRET_LAIR_PARENTS and code != "slx":
        return False
    return True


def release_ok(card, price_date):
    """False when the set is missing a date, not out yet, or still in its first 14 days."""
    released = _day(card.get("release"))
    current = _day(price_date)
    if not released or not current or released > current:
        return False
    return (current - released).days >= NEW_SET_DAYS


def clean_hist(raw):
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, value in raw.items():
        day = _day(key)
        if not day:
            continue
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        out[day.isoformat()] = price
    return out


def _baseline_date(hist, price_date):
    """Previous retail date, or None when it is missing or more than 2 days back."""
    if price_date not in hist:
        return None
    prev = [day for day in hist if day < price_date]
    if not prev:
        return None
    then_date = max(prev)
    if (_day(price_date) - _day(then_date)).days > MAX_GAP_DAYS:
        return None
    return then_date


def history_ok(hist, price_date):
    """True when the baseline already has MIN_HISTORY_DAYS retail prices.

    Today's point does not count. A set's release date does not count either.
    """
    then_date = _baseline_date(hist, price_date)
    if not then_date:
        return False
    return sum(1 for day in hist if day <= then_date) >= MIN_HISTORY_DAYS


def endpoints(hist, price_date):
    """Latest point and the previous one. None when the gap is more than 2 days."""
    then_date = _baseline_date(hist, price_date)
    if not then_date:
        return None
    try:
        then_price = money_amount(hist[then_date])
        now_price = money_amount(hist[price_date])
    except (ArithmeticError, ValueError):
        return None
    if then_price <= 0 or now_price <= 0:
        return None
    return then_price, now_price


def cheaper(new, old):
    """True when new is the printing to keep: lower price, else older set, else set code."""
    if new["price_now"] != old["price_now"]:
        return new["price_now"] < old["price_now"]
    if new["release"] != old["release"]:
        return new["release"] < old["release"]
    return new["set_code"] < old["set_code"]


def select_moves(cards, prices):
    """One row per card name: cheapest non-foil printing on the price date.

    The price date is the newest retail point among printings whose set is
    already at least 14 days old. A brand-new set cannot move that date.
    `prices` is a uuid -> {date: price} map, or an iterable of those pairs.
    """
    by_uuid = {}
    for card in cards:
        uuid = card.get("uuid")
        if uuid and structurally_ok(card):
            by_uuid[uuid] = card

    pairs = prices.items() if isinstance(prices, dict) else prices
    file_date = None
    best = {}
    for uuid, raw in pairs:
        card = by_uuid.get(uuid)
        hist = clean_hist(raw)
        if not card or not hist:
            continue
        own_now = max(hist)
        # A short series cannot set the price date or crowd out an older printing.
        if not release_ok(card, own_now) or not history_ok(hist, own_now):
            continue
        if file_date is None or own_now > file_date:
            file_date = own_now
            best = {}
        if own_now != file_date:
            continue
        ends = endpoints(hist, file_date)
        if not ends:
            continue
        then_price, now_price = ends
        cand = {
            "name": str(card.get("name") or "").strip(),
            "release": str(card.get("release") or ""),
            "set_code": str(card.get("set_code") or ""),
            "price_then": then_price,
            "price_now": now_price,
            "pct": percent(then_price, now_price),
        }
        product_id = _whole_number(card.get("product_id"))
        group_id = _whole_number(card.get("group_id"))
        if product_id is not None:
            cand["product_id"] = product_id
        if group_id is not None:
            cand["group_id"] = group_id
        prev = best.get(cand["name"])
        if prev is None or cheaper(cand, prev):
            best[cand["name"]] = cand

    jumps, drops = [], []
    for cand in best.values():
        if cand["price_now"] >= MIN_PRICE and cand["pct"] >= MIN_PCT:
            jumps.append(cand)
        elif cand["price_then"] >= MIN_PRICE and cand["pct"] <= -MIN_PCT:
            drops.append(cand)
    jumps = sorted(jumps, key=lambda r: (-abs(r["pct"]), r["name"]))[:TOP_N]
    drops = sorted(drops, key=lambda r: (-abs(r["pct"]), r["name"]))[:TOP_N]
    return {"price_date": file_date, "jumps": jumps, "drops": drops}


def _card_lines(row, up):
    arrow = "↑" if up else "↓"
    return [
        f"- Card name: {row['name']}",
        f"- Then: ${row['price_then']:.2f} → Now: ${row['price_now']:.2f} ({arrow}{abs(row['pct']):.1f}%)",
    ]


def _render(title, rows, up):
    parts = [title]
    for row in rows:
        parts.extend(_card_lines(row, up))
    parts.append("")
    if rows:
        parts.append(
            f"[Open this card in Market Signals]({card_href('magic', rows[0]['name'])})"
        )
    parts.append(FOOTER)
    return "\n".join(parts)


def build_message(title, rows, up):
    """Discord content, or None when there is nothing to say.

    Rows are already sorted by absolute percent. Cards that do not fit are
    dropped from the bottom. The footer is one line.
    """
    if not rows:
        return None
    chosen = list(rows)
    while chosen and len(_render(title, chosen, up)) > MAX_CHARS:
        chosen.pop()
    if not chosen:
        return None
    return _render(title, chosen, up)


def load_state(path):
    base = {"jumps": None, "drops": None}
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return base
    if not isinstance(raw, dict):
        return base
    for key in base:
        val = raw.get(key)
        base[key] = val if isinstance(val, str) and _day(val) else None
    return base


def save_state(path, state):
    """Write only the two settled price dates."""
    body = {"jumps": state.get("jumps"), "drops": state.get("drops")}
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(body, handle, indent=1)
        handle.write("\n")
    os.replace(tmp, path)


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
    except urllib.error.HTTPError as exc:
        raise DiscordError(f"HTTP {exc.code}")
    except Exception:
        raise DiscordError("request failed")


def settle(state, result, webhooks, post, dry_run):
    """Return (new_state, status lines). Dry-run does not post or change state."""
    new_state = {"jumps": state.get("jumps"), "drops": state.get("drops")}
    price_date = result.get("price_date")
    lines = []
    if not price_date:
        return new_state, ["no price date; no post"]
    for key in ("jumps", "drops"):
        rows = result.get(key) or []
        if new_state.get(key) == price_date:
            lines.append(f"{key}: price date {price_date} already settled; skip")
            continue
        msg = build_message(TITLES[key], rows, key == "jumps")
        if dry_run:
            lines.append(f"dry-run {key}:\n{msg}" if msg else f"dry-run {key}: no post")
            continue
        if not msg:
            new_state[key] = price_date
            lines.append(f"{key}: no cards; no post")
            continue
        hook = str((webhooks or {}).get(key) or "").strip()
        if not hook:
            lines.append(f"{WEBHOOK_ENV[key]} missing; skip")
            continue
        try:
            post(hook, msg)
        except DiscordError as exc:
            lines.append(f"{key}: Discord post failed (ignored): {redact(exc)}")
            continue
        new_state[key] = price_date
        posted = msg.count("- Card name:")
        lines.append(f"{key}: posted {posted} cards ({price_date})")
    return new_state, lines


def _open(path):
    if str(path).endswith(".xz"):
        return lzma.open(path, "rb")
    return open(path, "rb")


def _paper(card):
    availability = card.get("availability")
    if availability is None:
        return None
    if not isinstance(availability, list):
        return False
    return "paper" in {str(item).lower() for item in availability}


def _pick(primary, fallback, key):
    if key in primary and primary.get(key) not in (None, ""):
        return primary.get(key)
    return (fallback or {}).get(key)


def _flag(primary, fallback, key):
    if key in primary:
        return bool(primary.get(key))
    return bool((fallback or {}).get(key))


def _set_fields(set_obj, listed):
    primary = listed or {}
    return {
        "set_code": _pick(primary, set_obj, "code") or (set_obj or {}).get("code") or "",
        "set_name": _pick(primary, set_obj, "name") or "",
        "parent_code": _pick(primary, set_obj, "parentCode") or "",
        "release": _pick(primary, set_obj, "releaseDate"),
        "set_type": _pick(primary, set_obj, "type") or "",
        "group_id": _pick(primary, set_obj, "tcgplayerGroupId"),
        "online_only": _flag(primary, set_obj, "isOnlineOnly"),
        "foil_only": _flag(primary, set_obj, "isFoilOnly"),
    }


def read_setlist(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    rows = doc.get("data") if isinstance(doc, dict) else None
    out = {}
    for row in rows or []:
        if isinstance(row, dict) and row.get("code"):
            out[str(row["code"]).upper()] = row
    return out


def read_cards(printings_path, setlist_path=None):
    import ijson

    listed = read_setlist(setlist_path)
    cards = []
    with _open(printings_path) as handle:
        for code, set_obj in ijson.kvitems(handle, "data"):
            if not isinstance(set_obj, dict):
                continue
            meta = _set_fields(set_obj, listed.get(str(code).upper()))
            for card in set_obj.get("cards") or []:
                if not isinstance(card, dict) or not card.get("uuid"):
                    continue
                identifiers = card.get("identifiers") if isinstance(card.get("identifiers"), dict) else {}
                row = {
                    "uuid": card.get("uuid"),
                    "name": card.get("name"),
                    "release": meta["release"],
                    "set_code": meta["set_code"] or card.get("setCode") or code,
                    "set_name": meta["set_name"],
                    "parent_code": meta["parent_code"],
                    "language": card.get("language") or "English",
                    "finishes": card.get("finishes") or [],
                    "layout": card.get("layout") or "",
                    "set_type": meta["set_type"],
                    "group_id": meta["group_id"],
                    "product_id": identifiers.get("tcgplayerProductId"),
                    "online_only": meta["online_only"],
                    "foil_only": meta["foil_only"],
                    "paper": _paper(card),
                }
                if structurally_ok(row):
                    cards.append(row)
    return cards


def iter_prices(prices_path):
    import ijson

    with _open(prices_path) as handle:
        for uuid, node in ijson.kvitems(handle, "data"):
            yield uuid, _normal_retail(node)


def _normal_retail(node):
    """TCGplayer market history: paper.tcgplayer.retail.normal only.

    Buylist, foil, etched, and any Direct Low sibling are not market price.
    An empty normal series stays empty; it does not fall through to those.
    """
    if not isinstance(node, dict):
        return {}
    paper = node.get("paper")
    if not isinstance(paper, dict):
        return {}
    store = paper.get("tcgplayer")
    if not isinstance(store, dict):
        return {}
    retail = store.get("retail")
    if not isinstance(retail, dict):
        return {}
    normal = retail.get("normal")
    return normal if isinstance(normal, dict) else {}


def compute(prices_path, printings_path, setlist_path=None):
    cards = read_cards(printings_path, setlist_path)
    return select_moves(cards, iter_prices(prices_path))


def _use_market(row, quotes):
    """Replace a retail point that is Direct Low with the market price.

    MTGJSON stores one number per day at retail.normal. That number is meant
    to be TCGplayer marketPrice. On 2026-11-16 it was 23.86 for Barbarian
    General (PTK #100), which is the Direct Low quote; the market quote was
    17.66. AllPrices has no separate Direct Low series, so a current Normal
    quote is the check. A retail point that is not the Direct Low is left
    alone: it may be the market price from the price file's own snapshot.
    """
    product_id = _whole_number(row.get("product_id"))
    quote = quotes.get(product_id) if product_id is not None else None
    if not quote:
        return dict(row)
    market = quote.get("market")
    direct = quote.get("direct")
    now = row.get("price_now")
    if market is not None and same_price(now, direct) and not same_price(now, market):
        now = money_amount(market)
    elif market is None and same_price(now, direct):
        return None
    revised = dict(row)
    revised["price_now"] = now
    revised["pct"] = percent(row["price_then"], now)
    return revised


def apply_market_quotes(result, quotes):
    """Drop or reprice alerts whose latest retail point is Direct Low."""
    out = {"price_date": result.get("price_date"), "jumps": [], "drops": []}
    for key in ("jumps", "drops"):
        kept = []
        for row in result.get(key) or []:
            revised = _use_market(row, quotes or {})
            if not revised:
                continue
            if key == "jumps" and revised["price_now"] >= MIN_PRICE and revised["pct"] >= MIN_PCT:
                kept.append(revised)
            elif key == "drops" and revised["price_then"] >= MIN_PRICE and revised["pct"] <= -MIN_PCT:
                kept.append(revised)
        out[key] = sorted(kept, key=lambda r: (-abs(r["pct"]), r["name"]))[:TOP_N]
    return out


def _fetch_group_quotes(group_id):
    """Normal-subtype market and Direct Low for one TCGplayer group.

    Only marketPrice can replace a retail point. directLowPrice is never used
    as a price. low, mid, high, foil, and buylist rows are ignored.
    """
    url = f"https://tcgcsv.com/tcgplayer/1/{int(group_id)}/prices"
    req = urllib.request.Request(url, headers={"User-Agent": "tcg-market-signals/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        doc = json.load(resp)
    quotes = {}
    for row in (doc or {}).get("results") or []:
        if not isinstance(row, dict) or str(row.get("subTypeName") or "") != "Normal":
            continue
        product_id = _whole_number(row.get("productId"))
        if product_id is None:
            continue
        quotes[product_id] = {
            "market": _optional_price(row.get("marketPrice")),
            "direct": _optional_price(row.get("directLowPrice")),
        }
    return quotes


def fetch_market_quotes(group_ids):
    import time

    quotes = {}
    first = True
    for group_id in group_ids:
        if not first:
            time.sleep(0.1)
        first = False
        try:
            quotes.update(_fetch_group_quotes(group_id))
        except Exception as exc:
            log(f"market check skipped for one set: {exc.__class__.__name__}")
    return quotes


def correct_with_live_market(result):
    """Ask for a current market quote for each set that produced an alert."""
    groups = []
    seen = set()
    for key in ("jumps", "drops"):
        for row in result.get(key) or []:
            group_id = _whole_number(row.get("group_id"))
            if group_id is None or group_id in seen:
                continue
            seen.add(group_id)
            groups.append(group_id)
    if not groups:
        return result
    quotes = fetch_market_quotes(groups)
    if not quotes:
        return result
    updated = apply_market_quotes(result, quotes)
    removed = []
    for key in ("jumps", "drops"):
        before = {row.get("name") for row in result.get(key) or []}
        after = {row.get("name") for row in updated.get(key) or []}
        removed.extend(sorted(before - after))
    if removed:
        log("market check dropped Direct Low: " + ", ".join(removed))
    return updated


def download(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".partial"
    last = None
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "tcg-market-signals"})
            with urllib.request.urlopen(req, timeout=600) as resp, open(tmp, "wb") as out:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            os.replace(tmp, dest)
            return True
        except Exception as exc:
            last = exc.__class__.__name__
            try:
                os.remove(tmp)
            except OSError:
                pass
    log(f"download failed ({os.path.basename(dest)}): {last}")
    return False


def resolve_inputs(args):
    if args.prices or args.printings:
        if not args.prices or not args.printings:
            log("prices and printings must be passed together; no post")
            return None
        if not os.path.exists(args.prices) or not os.path.exists(args.printings):
            log("price files missing; no post")
            return None
        return args.prices, args.printings, args.setlist
    prices = os.path.join(CACHE, "AllPrices.json.xz")
    printings = os.path.join(CACHE, "AllPrintings.json.xz")
    setlist = os.path.join(CACHE, "SetList.json")
    log("downloading price files")
    if not download(PRICES_URL, prices) or not download(PRINTINGS_URL, printings):
        return None
    if not download(SETLIST_URL, setlist):
        setlist = None
    return prices, printings, setlist


def main(argv=None):
    parser = argparse.ArgumentParser(description="Post 1-day price jumps and drops")
    parser.add_argument("--dry-run", action="store_true", help="print the messages and do not post or save")
    parser.add_argument("--prices", help="price file (.json or .json.xz); skips the download")
    parser.add_argument("--printings", help="printings file (.json or .json.xz)")
    parser.add_argument("--setlist", help="optional set list JSON")
    parser.add_argument("--state", default=DEFAULT_STATE)
    args = parser.parse_args(argv)

    found = resolve_inputs(args)
    if not found:
        return 0
    prices_path, printings_path, setlist_path = found
    try:
        result = compute(prices_path, printings_path, setlist_path)
    except Exception as exc:
        log(f"could not read prices: {exc.__class__.__name__}; no post")
        return 0
    if not result.get("price_date"):
        log("no price date; no post")
        return 0
    result = correct_with_live_market(result)

    state = load_state(args.state)
    webhooks = {key: os.environ.get(env, "") for key, env in WEBHOOK_ENV.items()}
    new_state, lines = settle(state, result, webhooks, post_discord, args.dry_run)
    for line in lines:
        log(line)
    if args.dry_run or new_state == state:
        return 0
    try:
        save_state(args.state, new_state)
    except OSError as exc:
        log(f"could not save price date: {exc.__class__.__name__}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
