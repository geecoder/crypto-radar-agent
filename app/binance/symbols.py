"""Symbol helpers for Binance public market data."""

import re

DEFAULT_WATCHLIST = ("BTCUSDT", "ETHUSDT", "BNBUSDT")

SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]+$")
LEVERAGED_TOKEN_KEYWORDS = (
    "UP",
    "DOWN",
    "BULL",
    "BEAR",
    "2L",
    "2S",
    "3L",
    "3S",
    "4L",
    "4S",
    "5L",
    "5S",
)
STABLE_OR_FIAT_BASE_ASSETS = {
    "USDT",
    "USDC",
    "FDUSD",
    "TUSD",
    "BUSD",
    "DAI",
    "EUR",
    "GBP",
    "TRY",
    "BRL",
    "AUD",
    "BIDR",
    "AEUR",
    "USD1",
    "USDP",
    "PAX",
    "USTC",
    "USDE",
    "EURC",
    "EURI",
    "XUSD",
    "RLUSD",
}
COMMODITY_OR_SYNTHETIC_BASE_ASSETS = {
    "PAXG",
    "XAUT",
}


def _is_uppercase_alphanumeric(value: str) -> bool:
    """Return True when a symbol value is strictly uppercase alphanumeric."""
    return isinstance(value, str) and SYMBOL_PATTERN.fullmatch(value) is not None


def get_active_usdt_symbols(exchange_info: dict) -> list[str]:
    """Return active Spot USDT symbols from Binance exchange info.

    The filter keeps regular USDT-quoted Spot markets and removes inactive
    symbols, low-quality names, leveraged tokens, and stablecoin or fiat-like
    base assets.
    """
    active_symbols = []

    for symbol_info in exchange_info.get("symbols", []):
        symbol = symbol_info.get("symbol") or ""
        base_asset = symbol_info.get("baseAsset") or ""

        if symbol_info.get("quoteAsset") != "USDT":
            continue

        if symbol_info.get("status") != "TRADING":
            continue

        if not symbol_info.get("isSpotTradingAllowed", True):
            continue

        if not _is_uppercase_alphanumeric(symbol):
            continue

        if not _is_uppercase_alphanumeric(base_asset):
            continue

        if any(
            keyword in symbol or keyword in base_asset
            for keyword in LEVERAGED_TOKEN_KEYWORDS
        ):
            continue

        if base_asset in STABLE_OR_FIAT_BASE_ASSETS:
            continue

        if base_asset in COMMODITY_OR_SYNTHETIC_BASE_ASSETS:
            continue

        active_symbols.append(symbol)

    return sorted(active_symbols)
