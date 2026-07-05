"""Tradability scoring — can this position actually be entered/exited cleanly.

Separate from opportunity_score (which measures how good the setup looks).
tradability_score measures execution quality: order-book depth (reused from
the liquidity signal) plus bid/ask spread from the 24h ticker. A great setup
on an untradable book is not a trade.
"""

from app.indicators.liquidity import calculate_liquidity_quality

# Spread (%) upper bound -> score. First band the spread falls within wins.
SPREAD_SCORE_BANDS = (
    (0.05, 100),
    (0.10, 90),
    (0.20, 75),
    (0.35, 60),
    (0.50, 40),
    (1.00, 20),
)
DEPTH_WEIGHT = 0.6
SPREAD_WEIGHT = 0.4


def calculate_tradability_score(
    ticker_24hr: dict,
    liquidity_signal: dict | None = None,
) -> dict:
    """Score execution quality from order-book depth and bid/ask spread."""
    ticker_24hr = ticker_24hr or {}
    liquidity_signal = liquidity_signal or calculate_liquidity_quality(ticker_24hr)
    depth_score = _safe_int(liquidity_signal.get("score"))
    spread_pct = _spread_pct(ticker_24hr)
    spread_score = _spread_score(spread_pct)

    raw_score = (depth_score * DEPTH_WEIGHT) + (spread_score * SPREAD_WEIGHT)
    tradability_score = max(0, min(round(raw_score), 100))

    spread_text = f"{spread_pct:.3f}%" if spread_pct is not None else "unknown"

    return {
        "name": "tradability_score",
        "score": tradability_score,
        "depth_score": depth_score,
        "spread_pct": round(spread_pct, 4) if spread_pct is not None else None,
        "spread_score": spread_score,
        "reason": (
            f"Tradability {tradability_score}/100 "
            f"(depth {depth_score}, spread {spread_text} -> {spread_score})."
        ),
    }


def _spread_pct(ticker_24hr: dict) -> float | None:
    """Return the bid/ask spread as a percentage of the ask price."""
    bid = _safe_float(ticker_24hr.get("bidPrice"))
    ask = _safe_float(ticker_24hr.get("askPrice"))

    if bid is None or ask is None or ask <= 0 or bid <= 0:
        return None

    return max(0.0, (ask - bid) / ask * 100)


def _spread_score(spread_pct: float | None) -> int:
    """Return a 0-100 score for a bid/ask spread — tighter spreads score higher."""
    if spread_pct is None:
        return 0

    for band_limit, score in SPREAD_SCORE_BANDS:
        if spread_pct <= band_limit:
            return score

    return 0


def _safe_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
