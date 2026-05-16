"""Exhaustion-risk signal indicators."""


def calculate_exhaustion_risk(df, lookback: int = 20) -> dict:
    """Estimate whether a recent move is becoming overextended."""
    if df.empty or len(df) < lookback + 1:
        return {
            "name": "exhaustion_risk",
            "recent_change_pct": 0.0,
            "upper_wick_pct": 0.0,
            "distance_above_sma_pct": 0.0,
            "risk_score": 0,
            "risk_level": "Low",
            "reason": "Not enough candle data to calculate exhaustion risk.",
        }

    start_close = float(df["close"].iloc[-lookback - 1])
    latest_open = float(df["open"].iloc[-1])
    latest_high = float(df["high"].iloc[-1])
    latest_close = float(df["close"].iloc[-1])

    if start_close <= 0 or latest_close <= 0:
        return {
            "name": "exhaustion_risk",
            "recent_change_pct": 0.0,
            "upper_wick_pct": 0.0,
            "distance_above_sma_pct": 0.0,
            "risk_score": 0,
            "risk_level": "Low",
            "reason": "Close price is zero, so exhaustion risk cannot be calculated.",
        }

    recent_change_pct = ((latest_close - start_close) / start_close) * 100
    upper_wick = max(0.0, latest_high - max(latest_open, latest_close))
    upper_wick_pct = (upper_wick / latest_close) * 100
    distance_above_sma_pct = _distance_above_sma_pct(df, latest_close)
    latest_candle_is_red = latest_close < latest_open

    risk_score = 0

    if recent_change_pct >= 30:
        risk_score += 30
    if recent_change_pct >= 20:
        risk_score += 20
    if upper_wick_pct >= 3:
        risk_score += 20
    if distance_above_sma_pct > 10:
        risk_score += 20
    if latest_candle_is_red and recent_change_pct >= 20:
        risk_score += 10

    risk_score = min(risk_score, 100)
    risk_level = _risk_level(risk_score)

    return {
        "name": "exhaustion_risk",
        "recent_change_pct": recent_change_pct,
        "upper_wick_pct": upper_wick_pct,
        "distance_above_sma_pct": distance_above_sma_pct,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "reason": (
            f"{risk_level} exhaustion risk: price changed "
            f"{recent_change_pct:.2f}% over {lookback} candles."
        ),
    }


def _distance_above_sma_pct(df, latest_close: float) -> float:
    """Return how far the latest close is above the 21-candle SMA."""
    if len(df) < 21:
        return 0.0

    sma_21 = float(df["close"].rolling(window=21).mean().iloc[-1])

    if sma_21 <= 0:
        return 0.0

    return ((latest_close - sma_21) / sma_21) * 100


def _risk_level(risk_score: int) -> str:
    """Convert risk score into a plain-English level."""
    if risk_score >= 60:
        return "High"
    if risk_score >= 30:
        return "Medium"
    return "Low"
