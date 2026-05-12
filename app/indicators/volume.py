"""Volume-based signal indicators."""


def calculate_volume_spike(df) -> dict:
    """Compare the latest volume to the previous 20-candle average."""
    lookback = 20

    if df.empty or len(df) < lookback + 1:
        return {
            "name": "volume_spike",
            "latest_volume": 0.0,
            "average_volume": 0.0,
            "volume_ratio": 0.0,
            "score": 0,
            "reason": "Not enough candle data to calculate volume spike.",
        }

    latest_volume = float(df["volume"].iloc[-1])
    average_volume = float(df["volume"].iloc[-lookback - 1 : -1].mean())

    if average_volume <= 0:
        return {
            "name": "volume_spike",
            "latest_volume": latest_volume,
            "average_volume": average_volume,
            "volume_ratio": 0.0,
            "score": 0,
            "reason": "Average volume is zero, so volume ratio cannot be calculated.",
        }

    volume_ratio = latest_volume / average_volume

    if volume_ratio >= 5.0:
        score = 100
    elif volume_ratio >= 3.0:
        score = 80
    elif volume_ratio >= 2.0:
        score = 60
    elif volume_ratio >= 1.5:
        score = 40
    else:
        score = 10

    return {
        "name": "volume_spike",
        "latest_volume": latest_volume,
        "average_volume": average_volume,
        "volume_ratio": volume_ratio,
        "score": score,
        "reason": f"Latest volume is {volume_ratio:.2f}x the previous 20-candle average.",
    }
