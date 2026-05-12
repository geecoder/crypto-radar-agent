"""Public Binance Spot REST market-data client.

This client uses public market-data endpoints only. It does not require API
keys and does not place trades.
"""

from typing import Any

import pandas as pd
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
        """Return candlestick data from Binance ``/api/v3/klines``.

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


def klines_to_dataframe(klines: list) -> pd.DataFrame:
    """Convert Binance kline rows into a simple candle DataFrame.

    The Binance kline endpoint returns each candle as a list. This helper keeps
    only the fields needed for the MVP and converts prices, volume, and times
    into easier-to-use pandas types.
    """
    columns = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
    ]
    rows = [
        {
            "open_time": kline[0],
            "open": kline[1],
            "high": kline[2],
            "low": kline[3],
            "close": kline[4],
            "volume": kline[5],
            "close_time": kline[6],
        }
        for kline in klines
    ]
    candles = pd.DataFrame(rows, columns=columns)

    if candles.empty:
        return candles

    candles["open_time"] = pd.to_datetime(candles["open_time"], unit="ms")
    candles["close_time"] = pd.to_datetime(candles["close_time"], unit="ms")

    for column in ["open", "high", "low", "close", "volume"]:
        candles[column] = candles[column].astype(float)

    return candles
