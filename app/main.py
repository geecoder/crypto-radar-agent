"""Application entry point for the Crypto Radar Agent."""

import argparse
from datetime import datetime, timedelta, timezone
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
from app.analysis.live_readiness import (
    build_live_readiness_report,
    format_live_readiness_report,
)
from app.analysis.signal_analysis import (
    build_signal_analysis,
    format_signal_analysis,
)
from app.analysis.strategy_performance import (
    build_strategy_performance_report,
    format_strategy_performance_report,
)
from app.analysis.telegram_delivery import (
    build_telegram_delivery_report,
    format_telegram_delivery_report,
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
    insert_telegram_send_log,
    INVALID_SUPABASE_DATABASE_URL_MESSAGE,
    insert_paper_trade_decision,
    load_paper_trade_decisions,
    load_scan_runs,
    load_system_health_summary,
    load_unchecked_alert_history,
    persistence_health_check,
    update_alert_paper_trade_status,
    update_alert_telegram_status,
    write_system_health,
)
from app.trading.paper_trading import (
    create_paper_trades_from_alerts,
    load_all_paper_trades,
    update_open_paper_trades,
)
from app.trading.strategy_config import get_strategy_by_name

TELEGRAM_TEST_MESSAGE = "✅ Crypto Radar Agent Telegram test message."
ALERT_THRESHOLD = 60
GOOD_LIQUIDITY_LABELS = {"good", "strong", "excellent"}


def _net_pnl(trade: dict) -> float:
    """Return a trade's NET P&L (fees + slippage subtracted), falling back to
    gross pnl_pct for trades closed before Block B added net_pnl_pct."""
    net = trade.get("net_pnl_pct")

    if net is None:
        net = trade.get("pnl_pct")

    try:
        return float(net or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_good_liquidity(trade: dict) -> bool:
    """Return whether a trade's liquidity_label is Good or better."""
    return str(trade.get("liquidity_label") or "").strip().lower() in GOOD_LIQUIDITY_LABELS


def _good_liquidity_expectancy(closed_trades: list[dict]) -> tuple[int, float]:
    """Return (count, avg NET pnl_pct) for closed Good-liquidity-or-better trades."""
    good_liquidity_trades = [t for t in closed_trades if _is_good_liquidity(t)]

    if not good_liquidity_trades:
        return 0, 0.0

    avg_net = sum(_net_pnl(t) for t in good_liquidity_trades) / len(good_liquidity_trades)
    return len(good_liquidity_trades), avg_net


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
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Maximum number of unchecked outcomes to process per run "
            "(used with --check-outcomes; prioritises rows where "
            "last_checked_at IS NULL)."
        ),
    )
    parser.add_argument(
        "--max-minutes",
        type=float,
        default=None,
        metavar="M",
        help=(
            "Stop processing and save progress after M minutes "
            "(used with --check-outcomes to avoid GitHub Actions timeout)."
        ),
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
        "--repair-stale-paper-trades",
        action="store_true",
        help="Repair stale open paper trades using public market candles and exit.",
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
        "--live-readiness-report",
        action="store_true",
        help="Print paper-trading maturity and live-readiness governance report.",
    )
    parser.add_argument(
        "--telegram-delivery-report",
        action="store_true",
        help="Print Telegram delivery monitoring report and exit.",
    )
    parser.add_argument(
        "--send-telegram-delivery-report",
        action="store_true",
        help="Send Telegram delivery monitoring report to Telegram and exit.",
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
        "--daily-digest",
        action="store_true",
        help="Send a daily health digest to Telegram (scans, alerts, P&L, missed runs).",
    )
    parser.add_argument(
        "--go-live-check",
        action="store_true",
        help="Print PASS/FAIL for every live-trading precondition and exit.",
    )
    parser.add_argument(
        "--go-live-report",
        action="store_true",
        help="Send the weekly go-live readiness report to Telegram and exit.",
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


def _run_go_live_check() -> None:
    """Query the DB and print PASS/FAIL for all go-live preconditions."""
    from app.exchange.binance_executor import (
        check_go_live_preconditions,
        format_go_live_report,
    )

    if not USE_SUPABASE:
        print("Go-live check requires Supabase backend.")
        return

    print("Evaluating go-live preconditions…")
    paper_trades = load_all_paper_trades()
    closed = [t for t in paper_trades if t.get("status") == "closed"]
    last_100 = closed[-100:] if len(closed) >= 100 else closed

    wins = sum(1 for t in last_100 if _net_pnl(t) > 0)
    win_rate = (wins / len(last_100) * 100) if last_100 else 0.0
    avg_pnl = (
        sum(_net_pnl(t) for t in last_100) / len(last_100)
        if last_100
        else 0.0
    )
    good_liquidity_count, good_liquidity_net_avg = _good_liquidity_expectancy(closed)

    alert_history = load_alert_history(limit=None)
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    recent_alerts = [
        a for a in alert_history if str(a.get("created_at") or "") >= cutoff
    ]
    total_recent = len(recent_alerts)
    sent_recent = sum(1 for a in recent_alerts if a.get("telegram_sent"))
    tg_rate = (sent_recent / total_recent * 100) if total_recent else 0.0

    gates = check_go_live_preconditions(
        closed_paper_trade_count=len(closed),
        win_rate_last_100=win_rate,
        avg_pnl_last_100=avg_pnl,
        telegram_send_rate_7d=tg_rate,
        risk_manager_active=True,
        good_liquidity_closed_trade_count=good_liquidity_count,
        good_liquidity_net_avg_pnl_pct=good_liquidity_net_avg,
    )
    print(format_go_live_report(gates))


def _run_go_live_report() -> None:
    """Compute metrics and send the weekly go-live readiness report to Telegram."""
    from app.exchange.binance_executor import (
        check_go_live_preconditions,
        format_go_live_telegram_message,
    )

    # Block 3 was deployed 2026-06-18 — only trades closed after this date
    # use the new trailing-stop / partial-TP / wider-SL logic.
    BLOCK3_DATE = "2026-06-18"

    paper_trades = load_all_paper_trades()
    closed = [t for t in paper_trades if t.get("status") == "closed"]

    # Win rate over last 100 closed trades (NET of fees/slippage).
    last_100 = closed[-100:] if len(closed) >= 100 else closed
    wins_100 = sum(1 for t in last_100 if _net_pnl(t) > 0)
    win_rate_100 = (wins_100 / len(last_100) * 100) if last_100 else 0.0
    avg_pnl_100 = (
        sum(_net_pnl(t) for t in last_100) / len(last_100)
        if last_100 else 0.0
    )
    good_liquidity_count, good_liquidity_net_avg = _good_liquidity_expectancy(closed)

    # Win rate this week vs last week.
    now = datetime.now(timezone.utc)
    week_cutoff = (now - timedelta(days=7)).isoformat()
    two_weeks_cutoff = (now - timedelta(days=14)).isoformat()

    this_week = [
        t for t in closed
        if str(t.get("closed_at") or "") >= week_cutoff
    ]
    last_week_trades = [
        t for t in closed
        if two_weeks_cutoff <= str(t.get("closed_at") or "") < week_cutoff
    ]

    def _wr(trades: list[dict]) -> float:
        if not trades:
            return 0.0
        return sum(1 for t in trades if _net_pnl(t) > 0) / len(trades) * 100

    win_rate_this_week = _wr(this_week)
    win_rate_last_week = _wr(last_week_trades)

    # Post-Block 3 closed trade count.
    post_block3 = [
        t for t in closed
        if str(t.get("closed_at") or t.get("opened_at") or "") >= BLOCK3_DATE
    ]

    # Exit reason breakdown for this week.
    breakdown: dict[str, int] = {"stop_loss": 0, "take_profit": 0, "max_hold_expired": 0}
    for t in this_week:
        reason = str(t.get("exit_reason") or "")
        if reason == "stop_loss":
            breakdown["stop_loss"] += 1
        elif reason.startswith("take_profit"):
            breakdown["take_profit"] += 1
        elif reason == "max_hold_expired":
            breakdown["max_hold_expired"] += 1

    # Telegram send rate (7d).
    alert_history = load_alert_history(limit=None)
    recent_alerts = [
        a for a in alert_history
        if str(a.get("created_at") or "") >= week_cutoff
    ]
    total_recent = len(recent_alerts)
    sent_recent = sum(1 for a in recent_alerts if a.get("telegram_sent"))
    tg_rate = (sent_recent / total_recent * 100) if total_recent else 0.0

    gates = check_go_live_preconditions(
        closed_paper_trade_count=len(closed),
        win_rate_last_100=win_rate_100,
        avg_pnl_last_100=avg_pnl_100,
        telegram_send_rate_7d=tg_rate,
        risk_manager_active=True,
        good_liquidity_closed_trade_count=good_liquidity_count,
        good_liquidity_net_avg_pnl_pct=good_liquidity_net_avg,
    )

    message = format_go_live_telegram_message(
        gates=gates,
        win_rate_last_100=win_rate_100,
        win_rate_this_week=win_rate_this_week,
        win_rate_last_week=win_rate_last_week,
        post_block3_closed=len(post_block3),
        exit_breakdown_this_week=breakdown,
        total_closed=len(closed),
    )

    print(message)
    sent, _ = send_telegram_message(message)
    print("Go-live report sent." if sent else "Failed to send go-live report.")


def _send_daily_digest() -> None:
    """Build and send the daily health digest to Telegram."""
    if not USE_SUPABASE:
        print("Daily digest requires Supabase backend.")
        return

    try:
        summary = load_system_health_summary(hours=24)
    except Exception as exc:
        print(f"Failed to load system health: {exc}")
        return

    scans = summary.get("scans_completed", 0)
    alerts_total = summary.get("alerts_total", 0)
    alerts_sent = summary.get("alerts_sent", 0)
    send_rate = (
        round(alerts_sent / alerts_total * 100, 1) if alerts_total else 0
    )
    open_trades = summary.get("open_paper_trades", 0)
    pnl = summary.get("pnl_24h", 0)
    last_scan = summary.get("last_scan")
    missed_flag = ""

    if last_scan:
        try:
            from datetime import datetime, timezone
            last_dt = datetime.fromisoformat(str(last_scan).replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
            if age_hours > 3:
                missed_flag = f"\n⚠️ MISSED RUN: last scan was {age_hours:.1f}h ago."
        except Exception:
            pass

    pnl_sign = "+" if pnl >= 0 else ""
    message = (
        "📊 <b>Crypto Radar — Daily Digest</b>\n"
        f"Scans completed (24h): <b>{scans}</b>\n"
        f"Alerts sent/total: <b>{alerts_sent}/{alerts_total}</b> ({send_rate}%)\n"
        f"Open paper trades: <b>{open_trades}</b>\n"
        f"24h paper P&amp;L: <b>{pnl_sign}${pnl:.2f}</b>"
        f"{missed_flag}"
    )

    sent, _ = send_telegram_message(message)
    print("Daily digest sent." if sent else "Failed to send daily digest.")


def _telegram_selftest() -> bool:
    """Send a silent self-test ping to Telegram and return True only on HTTP 200.

    Called once at scan startup when Telegram is enabled. Hard-fails the run
    if the bot token or chat ID are broken so we never run blind.
    """
    print("Telegram self-test: sending startup ping…")
    sent, attempts = send_telegram_message("🔔 Crypto Radar startup self-test OK.")
    if sent:
        print("Telegram self-test passed.")
        return True

    statuses = [
        str(a.http_status) if a.http_status else "network error"
        for a in attempts
    ]
    print(f"Telegram self-test FAILED. Attempt statuses: {', '.join(statuses) or 'none'}")
    return False


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

    try:
        write_system_health("scan", {"scan_run_id": scan_run_id, **summary})
    except Exception as exc:
        print(f"Heartbeat write failed (non-fatal): {exc}")


def _fail_scan_run(scan_run_id: str | None, error: Exception) -> None:
    """Fail a Supabase scan run when one was created."""
    if not scan_run_id:
        return

    fail_scan_run(scan_run_id, str(error))


def _telegram_error(telegram_sent: bool, attempts: list) -> str | None:
    """Return a concise Telegram error string for alert_history persistence."""
    if telegram_sent:
        return None

    if not settings.telegram_alerts_enabled:
        return "Telegram disabled"

    # Surface the actual HTTP status from the last attempt if available.
    if attempts:
        last = attempts[-1]
        status = last.http_status
        if status is not None:
            return f"HTTP {status}"

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


def _print_paper_trade_update_summary(summary: dict) -> None:
    """Print a paper-trade update summary."""
    print(f"Open trades checked: {summary.get('open_trades_checked', 0)}")
    print(f"Closed trades: {summary.get('closed_trades', 0)}")
    print(f"Closed stop loss: {summary.get('closed_stop_loss', 0)}")
    print(f"Closed take profit: {summary.get('closed_take_profit', 0)}")
    print(f"Closed max hold: {summary.get('closed_max_hold', 0)}")
    print(f"Still open: {summary.get('still_open', 0)}")
    print(f"Errors: {summary.get('errors', 0)}")


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
    attempts: list | None = None,
) -> None:
    """Persist Telegram status for alert candidates when Supabase is enabled."""
    if not USE_SUPABASE:
        return

    for candidate in candidates:
        alert_history_id = candidate.get("alert_history_id")
        update_alert_telegram_status(alert_history_id, telegram_sent, error)

        if attempts:
            for attempt in attempts:
                try:
                    insert_telegram_send_log(
                        alert_id=alert_history_id,
                        attempt_number=attempt.attempt_number,
                        http_status=attempt.http_status,
                        response_body=attempt.response_body,
                    )
                except Exception as log_err:
                    print(f"Failed to write telegram_send_log: {log_err}")


def _run_normal_scan(args: argparse.Namespace, paper_strategy, scan_run_id: str | None) -> None:
    """Run the normal scanner flow."""
    client = BinancePublicClient()
    exchange_info = client.get_exchange_info()
    active_symbols = get_active_usdt_symbols(exchange_info)
    tickers_24hr = client.get_24hr_tickers()
    scan_universe = select_scan_universe(
        active_symbols,
        tickers_24hr,
        max_priority_symbols=75,
        max_universe_symbols=300,
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
            current_price = persisted_candidate.get("latest_close")
            should_send, reason = should_send_alert(
                symbol, score, current_price=current_price
            )

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

        telegram_sent, telegram_attempts = send_telegram_message(
            format_alert_message(candidates_to_send)
        )
        telegram_error = _telegram_error(telegram_sent, telegram_attempts)
        _update_telegram_status_for_candidates(
            candidates_to_send,
            telegram_sent,
            telegram_error,
            attempts=telegram_attempts,
        )
        scan_summary["total_telegram_sent"] = 1 if telegram_sent else 0

        for candidate in candidates_to_send:
            if telegram_sent:
                record_alert(
                    candidate["symbol"],
                    _get_opportunity_score(candidate),
                    price=candidate.get("latest_close"),
                )

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
        sent, _ = send_telegram_message(TELEGRAM_TEST_MESSAGE)
        print("Telegram test message sent." if sent else "Telegram test message FAILED.")
        return

    if args.check_outcomes:
        limit = args.limit
        max_minutes = args.max_minutes
        deadline = (
            datetime.now(timezone.utc) + timedelta(minutes=max_minutes)
            if max_minutes is not None
            else None
        )

        if deadline is not None:
            print(f"Time budget: {max_minutes} minutes (deadline {deadline.strftime('%H:%M:%S')} UTC).")

        try:
            if USE_SUPABASE:
                alert_history = load_unchecked_alert_history(limit=limit)
            else:
                alert_history = load_alert_history(limit=limit)

            if not alert_history:
                print("No unchecked outcomes found — nothing to process.")
                return

            print(f"Loaded {len(alert_history)} unchecked alert(s) to process.")
            client = BinancePublicClient()
            outcomes = check_alert_outcomes(alert_history, client, deadline=deadline)
            save_alert_outcomes(outcomes)
        except RuntimeError as error:
            if str(error) == INVALID_SUPABASE_DATABASE_URL_MESSAGE:
                print(INVALID_SUPABASE_DATABASE_URL_MESSAGE)
                return

            raise

        print("Outcome check completed.")
        print(f"Alerts checked: {len(outcomes)}")
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
        message_sent, _ = send_telegram_message(message)

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
        _print_paper_trade_update_summary(summary)
        return

    if args.repair_stale_paper_trades:
        client = BinancePublicClient()
        summary = update_open_paper_trades(client)

        print("Stale paper trade repair completed.")
        _print_paper_trade_update_summary(summary)
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

    if args.telegram_delivery_report:
        alert_history = load_alert_history()
        report = build_telegram_delivery_report(alert_history)
        print(format_telegram_delivery_report(report))
        return

    if args.send_telegram_delivery_report:
        alert_history = load_alert_history()
        report = build_telegram_delivery_report(alert_history)
        message = format_telegram_delivery_report(report)
        message_sent, _ = send_telegram_message(message)

        if message_sent:
            print("Telegram delivery report sent to Telegram.")
        else:
            print("Failed to send Telegram delivery report.")

        return

    if args.live_readiness_report:
        paper_trades = load_all_paper_trades()
        paper_trade_decisions = load_paper_trade_decisions() if USE_SUPABASE else []
        scan_runs = load_scan_runs() if USE_SUPABASE else []
        alert_history = load_alert_history()
        report = build_live_readiness_report(
            paper_trades,
            paper_trade_decisions,
            scan_runs,
            alert_history,
        )
        print(format_live_readiness_report(report))
        return

    if args.send_strategy_performance_report:
        paper_trades = load_all_paper_trades()
        report = build_strategy_performance_report(paper_trades)
        message = format_strategy_performance_report(report)
        message_sent, _ = send_telegram_message(message)

        if message_sent:
            print("Strategy performance report sent to Telegram.")
        else:
            print("Failed to send strategy performance report to Telegram.")

        return

    if args.daily_digest:
        _send_daily_digest()
        return

    if args.go_live_check:
        _run_go_live_check()
        return

    if args.go_live_report:
        _run_go_live_report()
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

    if settings.telegram_alerts_enabled and not _telegram_selftest():
        print(
            "FATAL: Telegram self-test failed. "
            "Fix bot token / chat ID before running. Aborting."
        )
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
