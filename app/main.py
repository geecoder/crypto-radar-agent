"""Application entry point for the Crypto Radar Agent."""

from app.binance.client import BinancePublicClient
from app.binance.symbols import get_active_usdt_symbols
from app.scanner import scan_symbols


def main() -> None:
    """Start the MVP application."""
    print("Crypto Radar Agent started")

    client = BinancePublicClient()
    exchange_info = client.get_exchange_info()
    active_symbols = get_active_usdt_symbols(exchange_info)

    print(f"Total active USDT symbols: {len(active_symbols)}")
    print("Scanning first 30 active USDT symbols...")

    opportunities = scan_symbols(
        client,
        active_symbols,
        interval="15m",
        limit=100,
        max_symbols=30,
    )

    print("Top 10 opportunities:")
    print("Symbol | Score | Classification | Target Bucket | Risk | Latest Close")
    print("-" * 78)

    for result in opportunities[:10]:
        opportunity = result["opportunity"]
        print(
            f"{result['symbol']} | "
            f"{opportunity['opportunity_score']} | "
            f"{opportunity['classification']} | "
            f"{opportunity['target_bucket']} | "
            f"{opportunity['risk_level']} | "
            f"{result['latest_close']}"
        )


if __name__ == "__main__":
    main()
