"""Public Binance market-data client placeholder."""

from app.config import settings


class BinancePublicClient:
    """Client boundary for Binance public endpoints only."""

    def __init__(self, base_url: str = settings.binance_base_url) -> None:
        self.base_url = base_url.rstrip("/")
