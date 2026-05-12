"""Application entry point for the Crypto Radar Agent."""

import argparse

from app.alerts.telegram import send_telegram_message
from app.binance.client import BinancePublicClient
from app.binance.market_filter import select_priority_symbols
from app.binance.symbols import get_active_usdt_symbols
from app.reporting import (
    format_alert_message,
    format_opportunity_table,
    format_top_opportunity_detail,
)
from app.scanner import get_alert_candidates, get_best_setups, scan_symbols

TELEGRAM_TEST_MESSAGE = "✅ Crypto Radar Agent Telegram test message."


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Run the Crypto Radar Agent.")
    parser.add_argument(
        "--test-telegram",
        action="store_true",
        help="Send a Telegram test message and exit.",
    )
    return parser.parse_args()


def main() -> None:
    """Start the MVP application."""
    print("Crypto Radar Agent started")

    args = parse_args()

    if args.test_telegram:
        send_telegram_message(TELEGRAM_TEST_MESSAGE)
        return

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
        print("Alert candidates:")
        print(format_opportunity_table(alert_candidates))
        print()
        print(format_top_opportunity_detail(alert_candidates[0]))
        send_telegram_message(format_alert_message(alert_candidates))
        return

    best_setups = get_best_setups(opportunities, limit=10)

    print("No strong opportunities detected right now.")
    print("No Telegram alert sent.")
    print("Best weak setups:")
    print(format_opportunity_table(best_setups))

    if best_setups:
        print()
        print(format_top_opportunity_detail(best_setups[0]))
    else:
        print()
        print("No valid setups available for drill-down.")


if __name__ == "__main__":
    main()
