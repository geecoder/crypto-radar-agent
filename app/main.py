"""Application entry point for the Crypto Radar Agent."""

from app.binance.client import BinancePublicClient


def main() -> None:
    """Start the MVP application."""
    print("Crypto Radar Agent started")

    client = BinancePublicClient()
    tickers = client.get_24hr_tickers()
    ticker_symbols = [ticker["symbol"] for ticker in tickers[:5]]

    print(f"24hr tickers returned: {len(tickers)}")
    print(f"First 5 ticker symbols: {ticker_symbols}")


if __name__ == "__main__":
    main()
