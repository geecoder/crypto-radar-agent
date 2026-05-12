"""Public Binance Spot REST market-data client.

This client uses public market-data endpoints only. It does not require API
keys and does not place trades.
"""

from typing import Any

import requests

from app.config import settings


class BinancePublicClient:
    """Small client for Binance public Spot REST market-data endpoints."""

    def __init__(
        self,
        base_url: str = settings.binance_base_url,
        timeout: int = 10,
    ) -> None:
        """Create a public Binance client.

        Args:
            base_url: Binance REST API base URL.
            timeout: Request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_exchange_info(self) -> dict[str, Any]:
        """Return Binance Spot exchange metadata.

        The response includes symbol details, supported order types, filters,
        and exchange-level rate-limit metadata from the public exchange-info
        endpoint.
        """
        response = requests.get(
            f"{self.base_url}/api/v3/exchangeInfo",
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_24hr_tickers(self) -> list[dict[str, Any]]:
        """Return 24-hour ticker statistics for all Spot symbols."""
        response = requests.get(
            f"{self.base_url}/api/v3/ticker/24hr",
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_klines(
        self,
        symbol: str,
        interval: str = "15m",
        limit: int = 100,
    ) -> list[list[Any]]:
        """Return candlestick data for a Spot symbol.

        Args:
            symbol: Trading pair symbol, such as ``BTCUSDT``.
            interval: Candle interval, such as ``15m``, ``1h``, or ``1d``.
            limit: Maximum number of candles to return.
        """
        params = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": limit,
        }
        response = requests.get(
            f"{self.base_url}/api/v3/klines",
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
