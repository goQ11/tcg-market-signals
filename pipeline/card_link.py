"""Deep link to one card on the Market Signals page."""
from urllib.parse import urlencode

RADAR_URL = "https://tcguardian-us.com/radar"
GAMES = {"magic", "pokemon", "one-piece", "yugioh", "lorcana"}


def card_href(game, card):
    """Public Radar URL. The app root forwards view=market-signals.

    An unknown game opens Magic. A blank card opens Market Signals with no card.
    """
    chosen = str(game or "").strip()
    if chosen not in GAMES:
        chosen = "magic"
    params = {"view": "market-signals", "game": chosen}
    name = str(card or "").strip()
    if name:
        params["card"] = name
    return f"{RADAR_URL}?{urlencode(params)}"
