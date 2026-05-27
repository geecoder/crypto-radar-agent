"""Application entry point for the Crypto Radar Agent."""

import argparse
from datetime import datetime, timezone
import os

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
from app.config import BINANCE_BASE_URL_ORDER, USE_SUPABASE, settings
from app.diagnostics import diagnose_symbol, format_diagnostic_report
from app.reporting import (
    format_alert_message,
    format_opportunity_table,
    format_top_opportunity_detail,
)
from app.scanner import get_alert_candidates, get_best_setups, scan_symbols
from app.storage.supabase_store import (
    complete_scan_run,
    create_scan_run,
    fail_scan_run,
    format_persistence_health_check,
    insert_paper_trade_decision,
    persistence_health_check,
    update_alert_paper_trade_status,
    update_alert_telegram_status,
)
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
        "--persistence-health-check",
        action="store_true",
        help="Print persistence backend health and recent stored records, then exit.",
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
            "(default, conservative, aggressive, parabolic, speculative)."
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


def _run_source() -> str:
    """Return the likely source for this scanner run."""
    return "github_actions" if os.getenv("GITHUB_ACTIONS") == "true" else "local"


def _start_scan_run(args: argparse.Namespace, paper_strategy) -> str | None:
    """Create a Supabase scan run when Supabase persistence is enabled."""
    if not USE_SUPABASE:
        return None

    return create_scan_run(
        {
            "run_source": _run_source(),
            "binance_base_url_order": BINANCE_BASE_URL_ORDER,
            "paper_strategy": args.paper_strategy or paper_strategy.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


def _complete_scan_run(scan_run_id: str | None, summary: dict) -> None:
    """Complete a Supabase scan run when one was created."""
    if not scan_run_id:
        return

    complete_scan_run(scan_run_id, summary)


def _fail_scan_run(scan_run_id: str | None, error: Exception) -> None:
    """Fail a Supabase scan run when one was created."""
    if not scan_run_id:
        return

    fail_scan_run(scan_run_id, str(error))


def _telegram_error(telegram_sent: bool) -> str | None:
    """Return a concise Telegram persistence error when delivery failed."""
    if telegram_sent:
        return None

    if not settings.telegram_alerts_enabled:
        return "Telegram disabled"

    return "Telegram send failed"


def _created_paper_trade_count(decisions: list[dict]) -> int:
    """Count created paper trades from structured decision rows."""
    return sum(1 for decision in decisions if decision.get("paper_trade_created"))


def _persist_suppressed_paper_decision(candidate: dict, reason: str) -> None:
    """Persist a skipped paper decision for cooldown-suppressed alerts."""
    if not USE_SUPABASE:
        return

    decision = {
        "symbol": candidate.get("symbol"),
        "alert_type": _candidate_alert_type(candidate),
        "alert_history_id": candidate.get("alert_history_id"),
        "paper_trade_created": False,
        "paper_trade_id": None,
        "decision": "skipped",
        "eligible": False,
        "reason": f"Alert suppressed by cooldown: {reason}",
        "strategy_name": None,
        "trade_plan_type": (
            candidate.get("trade_plan", {}).get("trade_plan_type")
            if isinstance(candidate.get("trade_plan"), dict)
            else None
        ),
        "metadata": {
            "scan_run_id": candidate.get("scan_run_id"),
            "source_alert_id": candidate.get("source_alert_id") or candidate.get("id"),
        },
    }
    insert_paper_trade_decision(decision)
    update_alert_paper_trade_status(
        candidate.get("alert_history_id"),
        False,
        None,
        decision["reason"],
    )


def _candidate_alert_type(candidate: dict) -> str:
    """Read an alert type for persistence-only paths."""
    explosive_mover = candidate.get("explosive_mover")

    if isinstance(explosive_mover, dict) and explosive_mover.get("should_alert"):
        return str(explosive_mover.get("alert_type") or "Explosive Mover Alert")

    return str(candidate.get("alert_type") or "Continuation Alert")


def _persisted_alert_candidate(candidate: dict, scan_run_id: str | None) -> dict:
    """Persist an alert candidate and return it with storage linkage."""
    candidate_with_run = {
        **candidate,
        "scan_run_id": scan_run_id,
        "source": "scanner",
    }
    source_alert_id = candidate.get("id")
    history_record = append_alert_history(candidate_with_run, telegram_sent=False)

    if not isinstance(history_record, dict):
        return candidate_with_run

    alert_history_id = history_record.get("id")
    linked_candidate = {
        **candidate_with_run,
        "alert_history_id": alert_history_id,
        "alert_id": alert_history_id,
    }

    if source_alert_id:
        linked_candidate["source_alert_id"] = source_alert_id

    return linked_candidate


def _update_telegram_status_for_candidates(
    candidates: list[dict],
    telegram_sent: bool,
    error: str | None,
) -> None:
    """Persist Telegram status for alert candidates when Supabase is enabled."""
    if not USE_SUPABASE:
        return

    for candidate in candidates:
        update_alert_telegram_status(
            candidate.get("alert_history_id"),
            telegram_sent,
            error,
        )


def _run_normal_scan(args: argparse.Namespace, paper_strategy, scan_run_id: str | None) -> None:
    """Run the normal scanner flow."""
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

    scan_summary = {
        "total_active_symbols": len(active_symbols),
        "total_scan_universe": len(scan_universe),
        "total_alert_candidates": len(alert_candidates),
        "total_telegram_sent": 0,
        "total_paper_trades_created": 0,
        "total_paper_trades_skipped": 0,
        "status": "completed",
    }

    if alert_candidates:
        print("Alert candidates:")
        print(format_opportunity_table(alert_candidates))
        print()
        print(format_top_opportunity_detail(alert_candidates[0]))

        candidates_to_send = []
        suppressed_candidates = []

        for candidate in alert_candidates:
            persisted_candidate = _persisted_alert_candidate(candidate, scan_run_id)
            symbol = persisted_candidate.get("symbol", "")
            score = _get_opportunity_score(persisted_candidate)
            should_send, reason = should_send_alert(symbol, score)

            if should_send:
                candidates_to_send.append(persisted_candidate)
            else:
                print(f"{symbol}: {reason}")
                suppressed_candidates.append((persisted_candidate, reason))
                _update_telegram_status_for_candidates(
                    [persisted_candidate],
                    False,
                    f"Suppressed by cooldown: {reason}",
                )
                _persist_suppressed_paper_decision(persisted_candidate, reason)

        if not candidates_to_send:
            print("Alert candidates found, but all were suppressed by cooldown.")
            scan_summary["total_paper_trades_skipped"] = len(suppressed_candidates)
            _complete_scan_run(scan_run_id, scan_summary)
            return

        telegram_sent = send_telegram_message(format_alert_message(candidates_to_send))
        telegram_error = _telegram_error(telegram_sent)
        _update_telegram_status_for_candidates(
            candidates_to_send,
            telegram_sent,
            telegram_error,
        )
        scan_summary["total_telegram_sent"] = 1 if telegram_sent else 0

        for candidate in candidates_to_send:
            if telegram_sent:
                record_alert(candidate["symbol"], _get_opportunity_score(candidate))

        paper_decisions = create_paper_trades_from_alerts(
            candidates_to_send,
            strategy=paper_strategy,
        )
        for candidate in candidates_to_send:
            if candidate.get("alert_type") == "Speculative Early Runner Alert":
                trade_plan = candidate.get("trade_plan", {})
                reason = (
                    trade_plan.get("speculative_paper_reason")
                    or trade_plan.get("reason")
                    or "Not available"
                )

                if trade_plan.get("speculative_paper_eligible"):
                    print(
                        "Speculative early runner paper trade eligible: "
                        "small high-risk paper simulation may be created."
                    )
                else:
                    print(f"Paper trade skipped: {reason}")

                continue

            if candidate.get("alert_type") != "Parabolic Watch Alert":
                continue

            trade_plan = candidate.get("trade_plan", {})
            reason = (
                trade_plan.get("parabolic_paper_reason")
                or trade_plan.get("reason")
                or "Not available"
            )

            if trade_plan.get("parabolic_paper_eligible"):
                print(
                    "Parabolic paper trade eligible: "
                    "high-risk paper simulation may be created."
                )
            else:
                print(f"Paper trade skipped: {reason}")

        created_count = _created_paper_trade_count(paper_decisions)
        skipped_count = len(paper_decisions) - created_count + len(suppressed_candidates)
        scan_summary["total_paper_trades_created"] = created_count
        scan_summary["total_paper_trades_skipped"] = skipped_count
        print(f"Paper trades created: {created_count}")
        _complete_scan_run(scan_run_id, scan_summary)
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

    _complete_scan_run(scan_run_id, scan_summary)


def main() -> None:
    """Start the MVP application."""
    print("Crypto Radar Agent started")

    args = parse_args()

    if args.persistence_health_check:
        print(format_persistence_health_check(persistence_health_check()))
        return

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
    scan_run_id = None

    try:
        scan_run_id = _start_scan_run(args, paper_strategy)
        _run_normal_scan(args, paper_strategy, scan_run_id)
    except Exception as error:
        _fail_scan_run(scan_run_id, error)
        print(f"Scanner run failed: {error}")
        return


if __name__ == "__main__":
    main()
