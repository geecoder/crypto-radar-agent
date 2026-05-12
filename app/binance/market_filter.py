"""Market selection helpers for Binance public ticker data."""


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


def select_priority_symbols(
    active_symbols: list[str],
    tickers_24hr: list[dict],
    max_symbols: int = 50,
) -> list[str]:
    """Select high-priority USDT symbols using 24hr liquidity and movement."""
    active_symbol_set = set(active_symbols)
    scored_symbols = []

    for ticker in tickers_24hr:
        symbol = ticker.get("symbol", "")

        if symbol not in active_symbol_set:
            continue

        if not symbol.endswith("USDT"):
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
