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
from app.analysis.paper_trading_report import (
    build_paper_trading_report,
    format_paper_trading_report,
)
from app.analysis.signal_analysis import (
    build_signal_analysis,
    format_signal_analysis,
)
from app.analysis.strategy_performance import (
    build_strategy_performance_report,
    format_strategy_performance_report,
)
from app.binance.client import BinancePublicClient
from app.binance.market_filter import select_scan_universe
from app.binance.symbols import get_active_usdt_symbols
from app.diagnostics import diagnose_symbol, format_diagnostic_report
from app.reporting import (
    format_alert_message,
    format_opportunity_table,
    format_top_opportunity_detail,
)
from app.scanner import get_alert_candidates, get_best_setups, scan_symbols
from app.trading.paper_trading import (
    create_paper_trades_from_alerts,
    load_all_paper_trades,
    update_open_paper_trades,
)
from app.trading.strategy_config import get_strategy_by_name

TELEGRAM_TEST_MESSAGE = "✅ Crypto Radar Agent Telegram test message."
ALERT_THRESHOLD = 60


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
    parser.add_argument(
        "--signal-analysis",
        action="store_true",
        help="Print a saved alert outcome signal performance analysis and exit.",
    )
    parser.add_argument(
        "--update-paper-trades",
        action="store_true",
        help="Update open paper trades using public market candles and exit.",
    )
    parser.add_argument(
        "--paper-trading-report",
        action="store_true",
        help="Print a simulated paper trading performance report and exit.",
    )
    parser.add_argument(
        "--strategy-performance-report",
        action="store_true",
        help="Print a strategy performance comparison report and exit.",
    )
    parser.add_argument(
        "--send-strategy-performance-report",
        action="store_true",
        help="Send a strategy performance comparison report to Telegram and exit.",
    )
    parser.add_argument(
        "--diagnose-symbol",
        default=None,
        help="Diagnose why one Binance symbol would or would not alert.",
    )
    parser.add_argument(
        "--paper-strategy",
        default=None,
        help=(
            "Paper trading strategy for newly created simulated trades "
            "(default, conservative, aggressive)."
        ),
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

    if args.signal_analysis:
        outcomes = load_alert_outcomes()
        analysis = build_signal_analysis(outcomes)
        print(format_signal_analysis(analysis))
        return

    if args.update_paper_trades:
        client = BinancePublicClient()
        summary = update_open_paper_trades(client)

        print("Paper trade update completed.")
        print(f"Open trades checked: {summary['open_trades_checked']}")
        print(f"Closed trades: {summary['closed_trades']}")
        print(f"Still open: {summary['still_open']}")
        return

    if args.paper_trading_report:
        paper_trades = load_all_paper_trades()
        report = build_paper_trading_report(paper_trades)
        print(format_paper_trading_report(report))
        return

    if args.strategy_performance_report:
        paper_trades = load_all_paper_trades()
        report = build_strategy_performance_report(paper_trades)
        print(format_strategy_performance_report(report))
        return

    if args.send_strategy_performance_report:
        paper_trades = load_all_paper_trades()
        report = build_strategy_performance_report(paper_trades)
        message = format_strategy_performance_report(report)
        message_sent = send_telegram_message(message)

        if message_sent:
            print("Strategy performance report sent to Telegram.")
        else:
            print("Failed to send strategy performance report to Telegram.")

        return

    if args.diagnose_symbol:
        client = BinancePublicClient()
        result = diagnose_symbol(
            client,
            args.diagnose_symbol,
            alert_threshold=ALERT_THRESHOLD,
        )
        print(format_diagnostic_report(result, alert_threshold=ALERT_THRESHOLD))
        return

    paper_strategy = get_strategy_by_name(args.paper_strategy)

    client = BinancePublicClient()
    exchange_info = client.get_exchange_info()
    active_symbols = get_active_usdt_symbols(exchange_info)
    tickers_24hr = client.get_24hr_tickers()
    scan_universe = select_scan_universe(
        active_symbols,
        tickers_24hr,
        max_priority_symbols=50,
        max_universe_symbols=150,
    )

    print(f"Total active USDT symbols: {len(active_symbols)}")
    print(f"Total scan universe selected: {len(scan_universe)}")
    print(f"First 30 scan universe symbols: {scan_universe[:30]}")
    print(f"Scanning {len(scan_universe)} symbols...")

    opportunities = scan_symbols(
        client,
        scan_universe,
        interval="15m",
        limit=100,
        max_symbols=len(scan_universe),
        tickers_24hr=tickers_24hr,
    )

    alert_candidates = get_alert_candidates(
        opportunities,
        minimum_score=ALERT_THRESHOLD,
    )

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
        paper_trade_candidates = []

        for candidate in candidates_to_send:
            history_record = append_alert_history(candidate, telegram_sent=telegram_sent)

            if isinstance(history_record, dict):
                paper_trade_candidates.append(
                    {
                        **candidate,
                        "alert_id": history_record.get("id"),
                    }
                )
            else:
                paper_trade_candidates.append(candidate)

            if telegram_sent:
                record_alert(candidate["symbol"], _get_opportunity_score(candidate))

        paper_trades = create_paper_trades_from_alerts(
            paper_trade_candidates,
            strategy=paper_strategy,
        )
        if any(
            candidate.get("alert_type") == "Parabolic Watch Alert"
            for candidate in paper_trade_candidates
        ):
            print("Paper trade skipped: parabolic watch alerts are monitoring-only.")
        print(f"Paper trades created: {len(paper_trades)}")
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
