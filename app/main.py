"""Application entry point for the Crypto Radar Agent."""

from app.binance.client import BinancePublicClient, klines_to_dataframe


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


if __name__ == "__main__":
    main()
