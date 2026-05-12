"""Trend alignment signal indicators."""


def calculate_trend_alignment(
    df,
    short_window: int = 9,
    long_window: int = 21,
) -> dict:
    """Measure whether price is aligned above short and long moving averages."""
    required_rows = max(short_window, long_window)

    if df.empty or len(df) < required_rows:
        return {
            "name": "trend_alignment",
            "short_window": short_window,
            "long_window": long_window,
            "latest_close": 0.0,
            "short_sma": 0.0,
            "long_sma": 0.0,
            "score": 0,
            "reason": "Not enough candle data to calculate trend alignment.",
        }

    latest_close = float(df["close"].iloc[-1])
    short_sma = float(df["close"].rolling(window=short_window).mean().iloc[-1])
    long_sma = float(df["close"].rolling(window=long_window).mean().iloc[-1])

    if latest_close > short_sma > long_sma:
        score = 100
        reason = "Price is above both moving averages with bullish alignment."
    elif latest_close > short_sma and short_sma >= long_sma:
        score = 80
        reason = "Price is above the short moving average and trend is supportive."
    elif latest_close > long_sma:
        score = 60
        reason = "Price is above the long moving average."
    elif latest_close > short_sma:
        score = 40
        reason = "Price is above the short moving average, but trend is mixed."
    else:
        score = 0
        reason = "Price is not above key moving averages."

    return {
        "name": "trend_alignment",
        "short_window": short_window,
        "long_window": long_window,
        "latest_close": latest_close,
        "short_sma": short_sma,
        "long_sma": long_sma,
        "score": score,
        "reason": reason,
    }
