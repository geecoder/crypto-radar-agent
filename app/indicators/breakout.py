"""Breakout signal indicators."""


def calculate_breakout_strength(df, lookback: int = 20) -> dict:
    """Measure whether the latest close broke above the previous lookback high."""
    if df.empty or len(df) < lookback + 1:
        return {
            "name": "breakout_strength",
            "lookback": lookback,
            "latest_close": 0.0,
            "previous_high": 0.0,
            "is_breakout": False,
            "breakout_percentage": 0.0,
            "score": 0,
            "reason": "Not enough candle data to calculate breakout strength.",
        }

    latest_close = float(df["close"].iloc[-1])
    previous_high = float(df["high"].iloc[-lookback - 1 : -1].max())

    if previous_high <= 0:
        return {
            "name": "breakout_strength",
            "lookback": lookback,
            "latest_close": latest_close,
            "previous_high": previous_high,
            "is_breakout": False,
            "breakout_percentage": 0.0,
            "score": 0,
            "reason": "Previous high is zero, so breakout strength cannot be calculated.",
        }

    is_breakout = latest_close > previous_high
    breakout_percentage = ((latest_close - previous_high) / previous_high) * 100

    if not is_breakout:
        score = 0
        reason = f"Latest close is not above the previous {lookback}-candle high."
    elif breakout_percentage >= 5:
        score = 100
        reason = f"Latest close broke out by {breakout_percentage:.2f}%."
    elif breakout_percentage >= 3:
        score = 80
        reason = f"Latest close broke out by {breakout_percentage:.2f}%."
    elif breakout_percentage >= 1:
        score = 60
        reason = f"Latest close broke out by {breakout_percentage:.2f}%."
    else:
        score = 40
        reason = f"Latest close broke out by {breakout_percentage:.2f}%."

    return {
        "name": "breakout_strength",
        "lookback": lookback,
        "latest_close": latest_close,
        "previous_high": previous_high,
        "is_breakout": is_breakout,
        "breakout_percentage": breakout_percentage,
        "score": score,
        "reason": reason,
    }
