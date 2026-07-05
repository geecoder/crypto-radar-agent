"""Liquidity-quality signal indicators."""

LIQUIDITY_RANK = {
    "very thin": 0,
    "thin": 1,
    "good": 2,
    "strong": 3,
    "excellent": 4,
}


def liquidity_rank(label) -> int:
    """Return the ordinal rank of a liquidity label, or -1 when unknown."""
    return LIQUIDITY_RANK.get(str(label or "").strip().lower(), -1)


def meets_liquidity_floor(label, minimum_label: str) -> bool:
    """Return whether a liquidity label is at or above a minimum liquidity floor."""
    return liquidity_rank(label) >= liquidity_rank(minimum_label)


def calculate_liquidity_quality(ticker_24hr: dict) -> dict:
    """Score market liquidity from Binance 24-hour ticker data."""
    quote_volume = _safe_float(ticker_24hr.get("quoteVolume"))
    trade_count = _safe_int(ticker_24hr.get("count"))

    if quote_volume >= 500_000_000 and trade_count >= 1_000_000:
        score = 100
        label = "Excellent"
    elif quote_volume >= 100_000_000 and trade_count >= 250_000:
        score = 80
        label = "Strong"
    elif quote_volume >= 20_000_000 and trade_count >= 50_000:
        score = 60
        label = "Good"
    elif quote_volume >= 5_000_000 and trade_count >= 5_000:
        score = 40
        label = "Thin"
    else:
        score = 10
        label = "Very thin"

    return {
        "name": "liquidity_quality",
        "quote_volume": quote_volume,
        "trade_count": trade_count,
        "score": score,
        "label": label,
        "reason": (
            f"{label} liquidity: 24h quote volume is {quote_volume:.2f} "
            f"with {trade_count} trades."
        ),
    }


def _safe_float(value) -> float:
    """Read a float from Binance ticker data safely."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value) -> int:
    """Read an integer from Binance ticker data safely."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
