"""Price momentum signal indicators."""


def calculate_price_momentum(df, lookback: int = 20) -> dict:
    """Compare the latest close price to the close price from lookback candles ago."""
    if df.empty or len(df) < lookback + 1:
        return {
            "name": "price_momentum",
            "lookback": lookback,
            "start_price": 0.0,
            "latest_price": 0.0,
            "percentage_change": 0.0,
            "score": 0,
            "reason": "Not enough candle data to calculate price momentum.",
        }

    start_price = float(df["close"].iloc[-lookback - 1])
    latest_price = float(df["close"].iloc[-1])

    if start_price <= 0:
        return {
            "name": "price_momentum",
            "lookback": lookback,
            "start_price": start_price,
            "latest_price": latest_price,
            "percentage_change": 0.0,
            "score": 0,
            "reason": "Start price is zero, so momentum cannot be calculated.",
        }

    percentage_change = ((latest_price - start_price) / start_price) * 100

    if percentage_change >= 15:
        score = 100
    elif percentage_change >= 10:
        score = 80
    elif percentage_change >= 5:
        score = 60
    elif percentage_change >= 2:
        score = 40
    elif percentage_change > 0:
        score = 20
    else:
        score = 0

    return {
        "name": "price_momentum",
        "lookback": lookback,
        "start_price": start_price,
        "latest_price": latest_price,
        "percentage_change": percentage_change,
        "score": score,
        "reason": f"Price changed {percentage_change:.2f}% over {lookback} candles.",
    }
