"""Application entry point for the Crypto Radar Agent."""

import argparse

from app.alerts.alert_history import append_alert_history, load_alert_history
from app.alerts.alert_state import record_alert, should_send_alert
from app.alerts.telegram import send_telegram_message
from app.analysis.outcome_tracker import (
    check_alert_outcomes,
    load_alert_outcomes,
    save_alert_outcomes,
)
from app.analysis.performance_report import (
    build_performance_report,
    format_performance_report,
)
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
    parser.add_argument(
        "--check-outcomes",
        action="store_true",
        help="Check saved alert history outcomes and exit.",
    )
    parser.add_argument(
        "--performance-report",
        action="store_true",
        help="Print a saved alert outcome performance report and exit.",
    )
    parser.add_argument(
        "--send-performance-report",
        action="store_true",
        help="Send a saved alert outcome performance report to Telegram and exit.",
    )
    return parser.parse_args()


def _get_opportunity_score(result: dict) -> int:
    """Read the opportunity score from a scan result."""
    try:
        return int(result.get("opportunity", {}).get("opportunity_score", 0))
    except (TypeError, ValueError):
        return 0


def _count_hit(outcomes: list[dict], threshold: int) -> int:
    """Count outcomes that hit a target threshold."""
    return sum(1 for outcome in outcomes if outcome.get(f"hit_{threshold}pct"))


def main() -> None:
    """Start the MVP application."""
    print("Crypto Radar Agent started")

    args = parse_args()

    if args.test_telegram:
        send_telegram_message(TELEGRAM_TEST_MESSAGE)
        return

    if args.check_outcomes:
        alert_history = load_alert_history()
        client = BinancePublicClient()
        outcomes = check_alert_outcomes(alert_history, client)
        save_alert_outcomes(outcomes)

        print("Outcome check completed.")
        print(f"Alerts checked: {len(alert_history)}")
        print(f"Outcomes saved: {len(outcomes)}")
        print(f"Hit +5%: {_count_hit(outcomes, 5)}")
        print(f"Hit +10%: {_count_hit(outcomes, 10)}")
        print(f"Hit +20%: {_count_hit(outcomes, 20)}")
        print(f"Hit +50%: {_count_hit(outcomes, 50)}")
        print(f"Hit +100%: {_count_hit(outcomes, 100)}")
        return

    if args.performance_report:
        outcomes = load_alert_outcomes()
        report = build_performance_report(outcomes)
        print(format_performance_report(report))
        return

    if args.send_performance_report:
        outcomes = load_alert_outcomes()
        report = build_performance_report(outcomes)
        message = format_performance_report(report)
        message_sent = send_telegram_message(message)

        if message_sent:
            print("Performance report sent to Telegram.")
        else:
            print("Failed to send performance report to Telegram.")

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
        tickers_24hr=tickers_24hr,
    )

    alert_candidates = get_alert_candidates(opportunities, minimum_score=60)

    if alert_candidates:
        print("Alert candidates:")
        print(format_opportunity_table(alert_candidates))
        print()
        print(format_top_opportunity_detail(alert_candidates[0]))

        candidates_to_send = []

        for candidate in alert_candidates:
            symbol = candidate.get("symbol", "")
            score = _get_opportunity_score(candidate)
            should_send, reason = should_send_alert(symbol, score)

            if should_send:
                candidates_to_send.append(candidate)
            else:
                print(f"{symbol}: {reason}")

        if not candidates_to_send:
            print("Alert candidates found, but all were suppressed by cooldown.")
            return

        telegram_sent = send_telegram_message(format_alert_message(candidates_to_send))

        for candidate in candidates_to_send:
            append_alert_history(candidate, telegram_sent=telegram_sent)

            if telegram_sent:
                record_alert(candidate["symbol"], _get_opportunity_score(candidate))

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
