"""Application entry point for the Crypto Radar Agent."""

from app.binance.client import BinancePublicClient
from app.binance.symbols import get_active_usdt_symbols


def main() -> None:
    """Start the MVP application."""
    print("Crypto Radar Agent started")

    client = BinancePublicClient()
    exchange_info = client.get_exchange_info()
    symbols = get_active_usdt_symbols(exchange_info)

    print(f"Active USDT symbols: {len(symbols)}")
    print(f"First 20 symbols: {symbols[:20]}")


if __name__ == "__main__":
    main()
