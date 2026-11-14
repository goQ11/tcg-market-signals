"""Deep link to one card on the Market Signals page."""
from urllib.parse import urlencode

MARKET_SIGNALS_URL = "https://tcguardian-radar.vercel.app/market-signals"
GAMES = {"magic", "pokemon", "one-piece", "yugioh", "lorcana"}


def card_href(game, card):
    """Right game and card. An unknown game opens Magic. A blank card opens the page."""
    name = str(card or "").strip()
    if not name:
        return MARKET_SIGNALS_URL
    chosen = str(game or "").strip()
    if chosen not in GAMES:
        chosen = "magic"
    return f"{MARKET_SIGNALS_URL}?{urlencode({'game': chosen, 'card': name})}"
