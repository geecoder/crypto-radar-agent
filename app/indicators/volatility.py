"""Volatility potential signal indicators."""


def calculate_volatility_potential(df, lookback: int = 20) -> dict:
    """Measure recent candle range and high-low range volatility."""
    if df.empty or len(df) < lookback:
        return {
            "name": "volatility_potential",
            "lookback": lookback,
            "average_candle_range_pct": 0.0,
            "recent_range_pct": 0.0,
            "score": 0,
            "reason": "Not enough candle data to calculate volatility potential.",
        }

    recent_candles = df.iloc[-lookback:]
    latest_close = float(recent_candles["close"].iloc[-1])

    if latest_close <= 0 or (recent_candles["close"] <= 0).any():
        return {
            "name": "volatility_potential",
            "lookback": lookback,
            "average_candle_range_pct": 0.0,
            "recent_range_pct": 0.0,
            "score": 0,
            "reason": "Close price is zero, so volatility cannot be calculated.",
        }

    candle_range_pct = (
        (recent_candles["high"] - recent_candles["low"]) / recent_candles["close"]
    ) * 100
    average_candle_range_pct = float(candle_range_pct.mean())
    recent_high = float(recent_candles["high"].max())
    recent_low = float(recent_candles["low"].min())
    recent_range_pct = ((recent_high - recent_low) / latest_close) * 100

    if recent_range_pct >= 20:
        score = 100
    elif recent_range_pct >= 12:
        score = 80
    elif recent_range_pct >= 8:
        score = 60
    elif recent_range_pct >= 5:
        score = 40
    elif recent_range_pct >= 3:
        score = 20
    else:
        score = 0

    return {
        "name": "volatility_potential",
        "lookback": lookback,
        "average_candle_range_pct": average_candle_range_pct,
        "recent_range_pct": recent_range_pct,
        "score": score,
        "reason": f"Recent {lookback}-candle range is {recent_range_pct:.2f}%.",
    }
