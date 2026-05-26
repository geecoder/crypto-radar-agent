"""Market selection helpers for Binance public ticker data."""

import re

from app.binance.symbols import (
    COMMODITY_OR_SYNTHETIC_BASE_ASSETS,
    STABLE_OR_FIAT_BASE_ASSETS,
)

SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]+$")


def _safe_float(value) -> float:
    """Convert a value to float, returning 0.0 if conversion fails."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value) -> int:
    """Convert a value to int, returning 0 if conversion fails."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _quote_volume_score(quote_volume: float) -> int:
    """Score a symbol by USDT quote volume."""
    if quote_volume >= 500_000_000:
        return 50
    if quote_volume >= 100_000_000:
        return 40
    if quote_volume >= 50_000_000:
        return 30
    if quote_volume >= 10_000_000:
        return 20
    return 10


def _movement_score(price_change_percent: float) -> int:
    """Score a symbol by absolute 24hr percentage movement."""
    absolute_change = abs(price_change_percent)

    if absolute_change >= 20:
        return 30
    if absolute_change >= 10:
        return 20
    if absolute_change >= 5:
        return 10
    return 0


def _activity_score(count: int) -> int:
    """Score a symbol by 24hr trade count."""
    if count >= 1_000_000:
        return 20
    if count >= 250_000:
        return 15
    if count >= 50_000:
        return 10
    return 5


def _is_uppercase_alphanumeric(value: str) -> bool:
    """Return True when a ticker symbol is strictly uppercase alphanumeric."""
    return isinstance(value, str) and SYMBOL_PATTERN.fullmatch(value) is not None


def _get_usdt_base_symbol(symbol: str) -> str:
    """Return the base symbol for a USDT pair."""
    return symbol[:-4]


def _is_excluded_base_symbol(base_symbol: str) -> bool:
    """Return True when a base symbol is stable, fiat, commodity, or synthetic."""
    return (
        base_symbol in STABLE_OR_FIAT_BASE_ASSETS
        or base_symbol in COMMODITY_OR_SYNTHETIC_BASE_ASSETS
    )


def _is_valid_active_usdt_symbol(symbol: str, active_symbol_set: set[str]) -> bool:
    """Return whether a symbol can be considered for USDT scanning."""
    if symbol not in active_symbol_set:
        return False

    if not _is_uppercase_alphanumeric(symbol):
        return False

    if not symbol.endswith("USDT"):
        return False

    base_symbol = _get_usdt_base_symbol(symbol)

    return not _is_excluded_base_symbol(base_symbol)


def _dedupe_preserve_order(symbols: list[str], max_symbols: int) -> list[str]:
    """Deduplicate symbols while preserving the first useful ordering."""
    seen = set()
    deduped = []

    for symbol in symbols:
        if symbol in seen:
            continue

        seen.add(symbol)
        deduped.append(symbol)

        if len(deduped) >= max_symbols:
            break

    return deduped


def select_priority_symbols(
    active_symbols: list[str],
    tickers_24hr: list[dict],
    max_symbols: int = 50,
) -> list[str]:
    """Select high-priority USDT symbols using 24hr liquidity and movement."""
    active_symbol_set = set(active_symbols)
    scored_symbols = []

    for ticker in tickers_24hr:
        symbol = ticker.get("symbol") or ""

        if not _is_valid_active_usdt_symbol(symbol, active_symbol_set):
            continue

        quote_volume = _safe_float(ticker.get("quoteVolume"))
        price_change_percent = _safe_float(ticker.get("priceChangePercent"))
        count = _safe_int(ticker.get("count"))

        if quote_volume < 5_000_000:
            continue

        if count < 5_000:
            continue

        priority_score = (
            _quote_volume_score(quote_volume)
            + _movement_score(price_change_percent)
            + _activity_score(count)
        )
        scored_symbols.append(
            {
                "symbol": symbol,
                "priority_score": priority_score,
                "quote_volume": quote_volume,
                "count": count,
            }
        )

    scored_symbols.sort(
        key=lambda item: (
            item["priority_score"],
            item["quote_volume"],
            item["count"],
            item["symbol"],
        ),
        reverse=True,
    )

    return [item["symbol"] for item in scored_symbols[:max_symbols]]


def select_scan_universe(
    active_symbols: list[str],
    tickers_24hr: list[dict],
    max_priority_symbols: int = 50,
    max_universe_symbols: int = 150,
) -> list[str]:
    """Select an expanded scan universe including liquid names and top movers."""
    active_symbol_set = set(active_symbols)
    priority_symbols = select_priority_symbols(
        active_symbols,
        tickers_24hr,
        max_symbols=max_priority_symbols,
    )
    eligible_tickers = []

    for ticker in tickers_24hr:
        symbol = ticker.get("symbol") or ""

        if not _is_valid_active_usdt_symbol(symbol, active_symbol_set):
            continue

        eligible_tickers.append(
            {
                "symbol": symbol,
                "quote_volume": _safe_float(ticker.get("quoteVolume")),
                "price_change_percent": _safe_float(
                    ticker.get("priceChangePercent")
                ),
                "count": _safe_int(ticker.get("count")),
            }
        )

    top_gainers = [
        item["symbol"]
        for item in sorted(
            (
                item
                for item in eligible_tickers
                if item["price_change_percent"] > 0
            ),
            key=lambda item: (
                item["price_change_percent"],
                item["quote_volume"],
                item["count"],
                item["symbol"],
            ),
            reverse=True,
        )[:50]
    ]
    high_movers = [
        item["symbol"]
        for item in eligible_tickers
        if item["price_change_percent"] >= 8
    ]
    liquid_movers = [
        item["symbol"]
        for item in eligible_tickers
        if item["quote_volume"] >= 5_000_000
        and item["price_change_percent"] >= 5
    ]
    speculative_early_runners = [
        item["symbol"]
        for item in eligible_tickers
        if item["quote_volume"] >= 1_000_000
        and item["price_change_percent"] >= 5
    ]

    return _dedupe_preserve_order(
        (
            priority_symbols
            + top_gainers
            + high_movers
            + liquid_movers
            + speculative_early_runners
        ),
        max_symbols=max_universe_symbols,
    )
