"""Symbol helpers for Binance public market data."""

DEFAULT_WATCHLIST = ("BTCUSDT", "ETHUSDT", "BNBUSDT")

LEVERAGED_TOKEN_KEYWORDS = ("UP", "DOWN", "BULL", "BEAR")
STABLECOIN_OR_FIAT_ASSETS = {
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
}


def get_active_usdt_symbols(exchange_info: dict) -> list[str]:
    """Return active Spot USDT symbols from Binance exchange info.

    The filter keeps regular USDT-quoted Spot markets and removes inactive
    symbols, leveraged tokens, and stablecoin or fiat-like base assets.
    """
    active_symbols = []

    for symbol_info in exchange_info.get("symbols", []):
        symbol = symbol_info.get("symbol", "")
        base_asset = symbol_info.get("baseAsset", "")

        if symbol_info.get("quoteAsset") != "USDT":
            continue

        if symbol_info.get("status") != "TRADING":
            continue

        if not symbol_info.get("isSpotTradingAllowed", True):
            continue

        if any(keyword in symbol for keyword in LEVERAGED_TOKEN_KEYWORDS):
            continue

        if base_asset in STABLECOIN_OR_FIAT_ASSETS:
            continue

        active_symbols.append(symbol)

    return sorted(active_symbols)
