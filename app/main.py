"""Application entry point for the Crypto Radar Agent."""

from app.binance.client import BinancePublicClient, klines_to_dataframe
from app.indicators.breakout import calculate_breakout_strength
from app.indicators.momentum import calculate_price_momentum
from app.indicators.volume import calculate_volume_spike
from app.scoring.opportunity_score import calculate_opportunity_score


def main() -> None:
    """Start the MVP application."""
    print("Crypto Radar Agent started")

    client = BinancePublicClient()
    klines = client.get_klines("BTCUSDT", interval="15m", limit=100)
    candles = klines_to_dataframe(klines)

    print(f"Candles returned: {len(candles)}")

    if candles.empty:
        print("No BTCUSDT candles returned")
        return

    latest_candle = candles.iloc[-1]

    print(f"Latest BTCUSDT close price: {latest_candle['close']}")
    print(f"Latest BTCUSDT candle volume: {latest_candle['volume']}")
    print(f"Latest candle open_time: {latest_candle['open_time']}")
    print(f"Latest candle close_time: {latest_candle['close_time']}")

    volume_signal = calculate_volume_spike(candles)
    momentum_signal = calculate_price_momentum(candles)
    breakout_signal = calculate_breakout_strength(candles)

    print("Volume indicator:")
    print(volume_signal)
    print("Momentum indicator:")
    print(momentum_signal)
    print("Breakout indicator:")
    print(breakout_signal)

    opportunity_result = calculate_opportunity_score(
        volume_signal,
        momentum_signal,
        breakout_signal,
    )

    print("Opportunity score:")
    print(opportunity_result)


if __name__ == "__main__":
    main()
