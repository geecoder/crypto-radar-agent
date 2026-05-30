"""Live readiness reporting for paper-trading governance.

This module only scores paper-trading maturity and operational health. It does
not connect to private exchange APIs, place orders, or enable live trading.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

NOT_READY = "NOT_READY"
PAPER_TESTING = "PAPER_TESTING"
READY_FOR_TESTNET_ONLY = "READY_FOR_TESTNET_ONLY"
READY_FOR_LIMITED_LIVE_REVIEW = "READY_FOR_LIMITED_LIVE_REVIEW"


def build_live_readiness_report(
    paper_trades: list[dict],
    paper_trade_decisions: list[dict],
    scan_runs: list[dict],
    alert_history: list[dict],
) -> dict:
    """Build a readiness report from paper trades and operational records."""
    trades = [trade for trade in paper_trades if isinstance(trade, dict)]
    decisions = [
        decision for decision in paper_trade_decisions if isinstance(decision, dict)
    ]
    scans = [scan for scan in scan_runs if isinstance(scan, dict)]
    alerts = [alert for alert in alert_history if isinstance(alert, dict)]
    open_trades = [trade for trade in trades if _is_status(trade, "open")]
    closed_trades = [trade for trade in trades if _is_status(trade, "closed")]
    stale_open_trades = [
        trade for trade in open_trades if _is_stale_open_trade(trade)
    ]
    recent_alerts = _recent_records(alerts, limit=50)
    winning_trades = [trade for trade in closed_trades if _pnl_pct(trade) > 0]
    losing_trades = [trade for trade in closed_trades if _pnl_pct(trade) < 0]
    pnl_pct_values = [
        pnl_pct
        for trade in closed_trades
        if (pnl_pct := _as_float(trade.get("pnl_pct"))) is not None
    ]
    pnl_amount_values = [
        pnl_amount
        for trade in closed_trades
        if (pnl_amount := _as_float(trade.get("pnl_amount"))) is not None
    ]
    scans_completed = sum(1 for scan in scans if _scan_completed(scan))
    scans_failed_or_stuck = sum(1 for scan in scans if _scan_failed_or_stuck(scan))
    telegram_failure_count = sum(
        1 for alert in recent_alerts if _telegram_failed(alert)
    )

    report = {
        "total_paper_trades": len(trades),
        "closed_trades": len(closed_trades),
        "open_trades": len(open_trades),
        "stale_open_trades": len(stale_open_trades),
        "winning_trades": len(winning_trades),
        "losing_trades": len(losing_trades),
        "win_rate_pct": _percentage(len(winning_trades), len(closed_trades)),
        "average_pnl_pct": _average(pnl_pct_values),
        "total_pnl_amount": _round(sum(pnl_amount_values)),
        "stop_loss_rate_pct": _exit_rate(closed_trades, "stop_loss"),
        "take_profit_rate_pct": _take_profit_rate(closed_trades),
        "max_hold_expired_rate_pct": _exit_rate(
            closed_trades,
            "max_hold_expired",
        ),
        "best_strategy": _ranked_strategy(closed_trades, reverse=True),
        "worst_strategy": _ranked_strategy(closed_trades, reverse=False),
        "scans_completed": scans_completed,
        "scans_failed_or_stuck": scans_failed_or_stuck,
        "telegram_failure_count": telegram_failure_count,
    }
    report["readiness_status"] = _readiness_status(
        report,
        decisions=decisions,
        scan_runs=scans,
    )
    report["recommendations"] = _build_recommendations(report)

    return report


def format_live_readiness_report(report: dict) -> str:
    """Format a live-readiness report as readable plain text."""
    lines = [
        "Crypto Radar Live Readiness Report",
        "",
        "Readiness",
        f"Status: {report.get('readiness_status', NOT_READY)}",
        "",
        "Paper Trading",
        f"Total paper trades: {report.get('total_paper_trades', 0)}",
        f"Closed trades: {report.get('closed_trades', 0)}",
        f"Open trades: {report.get('open_trades', 0)}",
        f"Stale open trades: {report.get('stale_open_trades', 0)}",
        f"Winning trades: {report.get('winning_trades', 0)}",
        f"Losing trades: {report.get('losing_trades', 0)}",
        f"Win rate: {_format_pct(report.get('win_rate_pct', 0))}%",
        f"Average P/L: {_format_pct(report.get('average_pnl_pct', 0))}%",
        f"Total P/L amount: {_format_currency(report.get('total_pnl_amount', 0))}",
        "",
        "Exit Controls",
        f"Stop-loss rate: {_format_pct(report.get('stop_loss_rate_pct', 0))}%",
        f"Take-profit rate: {_format_pct(report.get('take_profit_rate_pct', 0))}%",
        (
            "Max-hold expired rate: "
            f"{_format_pct(report.get('max_hold_expired_rate_pct', 0))}%"
        ),
        "",
        "Strategy Quality",
        f"Best strategy: {_format_strategy(report.get('best_strategy'))}",
        f"Worst strategy: {_format_strategy(report.get('worst_strategy'))}",
        "",
        "Operational Health",
        f"Scans completed: {report.get('scans_completed', 0)}",
        f"Scans failed or stuck: {report.get('scans_failed_or_stuck', 0)}",
        f"Telegram failures (recent): {report.get('telegram_failure_count', 0)}",
        "",
        "Recommendations",
        *_format_recommendations(report.get("recommendations", [])),
        "",
        "Notes",
        "- This is a paper-trading maturity report only.",
        "- No live trading is implemented or enabled by this command.",
    ]

    return "\n".join(lines)


def _readiness_status(
    report: dict,
    decisions: list[dict],
    scan_runs: list[dict],
) -> str:
    """Apply the maturity gate rules to report metrics."""
    if int(report.get("closed_trades", 0) or 0) < 100:
        return NOT_READY

    if _as_float(report.get("average_pnl_pct")) <= 0:
        return NOT_READY

    if _as_float(report.get("win_rate_pct")) < 45:
        return NOT_READY

    if int(report.get("stale_open_trades", 0) or 0) > 0:
        return NOT_READY

    if int(report.get("scans_failed_or_stuck", 0) or 0) > 0:
        return NOT_READY

    if int(report.get("telegram_failure_count", 0) or 0) > 0:
        return NOT_READY

    if _has_testnet_validation(decisions, scan_runs):
        return READY_FOR_LIMITED_LIVE_REVIEW

    return READY_FOR_TESTNET_ONLY


def _build_recommendations(report: dict) -> list[str]:
    """Build actionable recommendations for the readiness gate."""
    recommendations = []

    if int(report.get("closed_trades", 0) or 0) < 100:
        recommendations.append("Collect at least 100 closed paper trades.")

    if int(report.get("stale_open_trades", 0) or 0) > 0:
        recommendations.append("Fix stale paper trade closure.")

    if (
        _as_float(report.get("average_pnl_pct")) <= 0
        or _as_float(report.get("win_rate_pct")) < 45
    ):
        recommendations.append("Improve speculative early runner filters.")

    if int(report.get("scans_failed_or_stuck", 0) or 0) > 0:
        recommendations.append("Fix failed or stuck scan runs.")

    if int(report.get("telegram_failure_count", 0) or 0) > 0:
        recommendations.append("Fix recent Telegram delivery failures.")

    recommendations.append("Do not enable Binance trading permissions yet.")

    return _dedupe(recommendations)


def _is_status(trade: dict, status: str) -> bool:
    return str(trade.get("status", "")).strip().lower() == status


def _is_stale_open_trade(trade: dict) -> bool:
    opened_at = _parse_timestamp(trade.get("opened_at"))

    if opened_at is None:
        return False

    max_hold_hours = _as_float(trade.get("max_hold_hours"))

    if max_hold_hours is None:
        max_hold_hours = 48

    expires_at = opened_at + timedelta(hours=max_hold_hours)

    return datetime.now(timezone.utc) >= expires_at


def _scan_completed(scan: dict) -> bool:
    return str(scan.get("status", "")).strip().lower() in {"completed", "success"}


def _scan_failed_or_stuck(scan: dict) -> bool:
    status = str(scan.get("status", "")).strip().lower()

    if status in {"completed", "success"}:
        return False

    if status in {"failed", "error", "stuck"}:
        return True

    if status in {"running", "started", "in_progress", "pending"}:
        return True

    return bool(scan.get("error_message") or not scan.get("completed_at"))


def _telegram_failed(alert: dict) -> bool:
    return bool(str(alert.get("telegram_error") or "").strip())


def _recent_records(records: list[dict], limit: int) -> list[dict]:
    """Return the most recent records by common timestamp fields."""
    sortable_records = []

    for index, record in enumerate(records):
        timestamp = _parse_timestamp(
            record.get("created_at")
            or record.get("alerted_at")
            or record.get("updated_at")
        )
        sortable_records.append((timestamp, index, record))

    if any(timestamp is not None for timestamp, _index, _record in sortable_records):
        sortable_records = sorted(
            sortable_records,
            key=lambda item: item[0] or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return [record for _timestamp, _index, record in sortable_records[:limit]]

    return records[-limit:]


def _exit_rate(closed_trades: list[dict], exit_reason: str) -> float:
    count = sum(
        1
        for trade in closed_trades
        if str(trade.get("exit_reason", "")).strip().lower() == exit_reason
    )
    return _percentage(count, len(closed_trades))


def _take_profit_rate(closed_trades: list[dict]) -> float:
    count = sum(
        1
        for trade in closed_trades
        if str(trade.get("exit_reason", "")).strip().lower().startswith(
            "take_profit"
        )
    )
    return _percentage(count, len(closed_trades))


def _ranked_strategy(closed_trades: list[dict], reverse: bool) -> dict | None:
    grouped: dict[str, list[dict]] = {}

    for trade in closed_trades:
        if _as_float(trade.get("pnl_pct")) is None:
            continue

        strategy_name = str(trade.get("strategy_name") or "Unknown")
        grouped.setdefault(strategy_name, []).append(trade)

    if not grouped:
        return None

    ranked = [
        {
            "strategy_name": strategy_name,
            "closed_trades": len(strategy_trades),
            "win_rate_pct": _percentage(
                sum(1 for trade in strategy_trades if _pnl_pct(trade) > 0),
                len(strategy_trades),
            ),
            "average_pnl_pct": _average(
                [
                    pnl_pct
                    for trade in strategy_trades
                    if (pnl_pct := _as_float(trade.get("pnl_pct"))) is not None
                ]
            ),
        }
        for strategy_name, strategy_trades in grouped.items()
    ]

    return sorted(
        ranked,
        key=lambda strategy: strategy["average_pnl_pct"],
        reverse=reverse,
    )[0]


def _has_testnet_validation(decisions: list[dict], scan_runs: list[dict]) -> bool:
    records = [*decisions, *scan_runs]

    for record in records:
        if _record_has_testnet_validation(record):
            return True

        metadata = record.get("metadata")

        if isinstance(metadata, dict) and _record_has_testnet_validation(metadata):
            return True

    return False


def _record_has_testnet_validation(record: dict) -> bool:
    for key in (
        "testnet_validation",
        "testnet_validated",
        "testnet_validation_passed",
    ):
        if bool(record.get(key)):
            return True

    return False


def _pnl_pct(trade: dict) -> float:
    return _as_float(trade.get("pnl_pct")) or 0.0


def _average(values: list[float]) -> float:
    numeric_values = [
        value
        for value in (_as_float(value) for value in values)
        if value is not None
    ]

    if not numeric_values:
        return 0.0

    return _round(sum(numeric_values) / len(numeric_values))


def _percentage(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0

    return _round((numerator / denominator) * 100)


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _as_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _round(value: float) -> float:
    return round(value, 2)


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    deduped = []

    for item in items:
        if item in seen:
            continue

        seen.add(item)
        deduped.append(item)

    return deduped


def _format_strategy(strategy: dict | None) -> str:
    if not strategy:
        return "Not available"

    return (
        f"{strategy.get('strategy_name', 'Unknown')} "
        f"({_format_pct(strategy.get('average_pnl_pct', 0))}% avg, "
        f"{_format_pct(strategy.get('win_rate_pct', 0))}% win, "
        f"{strategy.get('closed_trades', 0)} closed)"
    )


def _format_recommendations(recommendations: list[str]) -> list[str]:
    if not recommendations:
        return ["- No readiness recommendations available."]

    return [f"- {recommendation}" for recommendation in recommendations]


def _format_pct(value: Any) -> str:
    number = _as_float(value) or 0.0
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _format_currency(value: Any) -> str:
    number = _as_float(value) or 0.0
    sign = "-" if number < 0 else ""
    return f"{sign}${abs(number):.2f}"
