"""Application entry point for the Crypto Radar Agent."""

from app.binance.client import BinancePublicClient
from app.binance.market_filter import select_priority_symbols
from app.binance.symbols import get_active_usdt_symbols
from app.scanner import get_alert_candidates, get_best_setups, scan_symbols


def print_opportunity_table(results: list[dict]) -> None:
    """Print opportunity scan results in a simple table."""
    print("Symbol | Score | Classification | Target Bucket | Risk | Latest Close")
    print("-" * 78)

    for result in results:
        opportunity = result["opportunity"]
        print(
            f"{result['symbol']} | "
            f"{opportunity['opportunity_score']} | "
            f"{opportunity['classification']} | "
            f"{opportunity['target_bucket']} | "
            f"{opportunity['risk_level']} | "
            f"{result['latest_close']}"
        )


def main() -> None:
    """Start the MVP application."""
    print("Crypto Radar Agent started")

    client = BinancePublicClient()
    exchange_info = client.get_exchange_info()
    active_symbols = get_active_usdt_symbols(exchange_info)
    tickers_24hr = client.get_24hr_tickers()
    priority_symbols = select_priority_symbols(
        active_symbols,
        tickers_24hr,
        max_symbols=50,
    )

    print(f"Total active USDT symbols: {len(active_symbols)}")
    print(f"Total priority symbols selected: {len(priority_symbols)}")
    print(f"First 20 priority symbols: {priority_symbols[:20]}")
    print("Scanning first 50 priority symbols...")

    opportunities = scan_symbols(
        client,
        priority_symbols,
        interval="15m",
        limit=100,
        max_symbols=50,
    )

    alert_candidates = get_alert_candidates(opportunities, minimum_score=60)

    if alert_candidates:
        print("🚨 Alert candidates:")
        print_opportunity_table(alert_candidates)
        return

    print("No strong opportunities detected right now.")
    print("Best weak setups:")
    print_opportunity_table(get_best_setups(opportunities, limit=10))


if __name__ == "__main__":
    main()
