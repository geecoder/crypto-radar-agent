"""Telegram delivery monitoring for persisted alert history.

This module only reports delivery health. It does not expose bot tokens, chat
IDs, or any other secret configuration values.
"""

from datetime import datetime, timezone
import re
from typing import Any

SENSITIVE_PATTERNS = (
    re.compile(r"bot[0-9A-Za-z:_-]+"),
    re.compile(r"postgres(?:ql)?://\S+"),
)


def build_telegram_delivery_report(alert_history: list[dict]) -> dict:
    """Build a Telegram delivery report from alert history rows."""
    alerts = [alert for alert in alert_history if isinstance(alert, dict)]
    sent_true = sum(1 for alert in alerts if bool(alert.get("telegram_sent")))
    sent_false = len(alerts) - sent_true
    alerts_with_errors = [
        alert for alert in alerts if str(alert.get("telegram_error") or "").strip()
    ]

    return {
        "total_alerts": len(alerts),
        "telegram_sent_true": sent_true,
        "telegram_sent_false": sent_false,
        "telegram_error_count": len(alerts_with_errors),
        "delivery_success_rate_pct": _percentage(sent_true, len(alerts)),
        "latest_errors": _latest_errors(alerts_with_errors, limit=10),
        "errors_by_day": _errors_by_day(alerts_with_errors),
        "errors_by_alert_type": _errors_by_alert_type(alerts_with_errors),
        "recommendation": _recommendation(sent_true, len(alerts), alerts_with_errors),
    }


def format_telegram_delivery_report(report: dict) -> str:
    """Format a Telegram delivery report as readable plain text."""
    lines = [
        "Crypto Radar Telegram Delivery Report",
        "",
        "Overview",
        f"Total alerts reviewed: {report.get('total_alerts', 0)}",
        f"Successful Telegram sends: {report.get('telegram_sent_true', 0)}",
        (
            "Failed/disabled Telegram sends: "
            f"{report.get('telegram_sent_false', 0)}"
        ),
        f"Telegram error count: {report.get('telegram_error_count', 0)}",
        (
            "Delivery success rate: "
            f"{_format_pct(report.get('delivery_success_rate_pct', 0))}%"
        ),
        "",
        "Latest Telegram Errors",
        *_format_latest_errors(report.get("latest_errors", [])),
        "",
        "Errors by Day",
        *_format_counts(report.get("errors_by_day", {})),
        "",
        "Errors by Alert Type",
        *_format_counts(report.get("errors_by_alert_type", {})),
        "",
        "Recommendation",
        f"- {report.get('recommendation') or 'No recommendation available.'}",
    ]

    return "\n".join(lines)


def _latest_errors(alerts: list[dict], limit: int) -> list[dict]:
    """Return the latest error rows with sensitive text redacted."""
    sorted_alerts = sorted(
        alerts,
        key=lambda alert: _parse_timestamp(
            alert.get("created_at")
            or alert.get("alerted_at")
            or alert.get("updated_at")
        )
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    return [
        {
            "symbol": alert.get("symbol") or "Unknown",
            "alert_type": alert.get("alert_type") or "Unknown",
            "alerted_at": (
                alert.get("alerted_at")
                or alert.get("created_at")
                or alert.get("updated_at")
                or "Unknown"
            ),
            "telegram_error": _redact(str(alert.get("telegram_error") or "")),
        }
        for alert in sorted_alerts[:limit]
    ]


def _errors_by_day(alerts: list[dict]) -> dict:
    """Count Telegram errors by UTC calendar day."""
    counts: dict[str, int] = {}

    for alert in alerts:
        timestamp = _parse_timestamp(
            alert.get("alerted_at")
            or alert.get("created_at")
            or alert.get("updated_at")
        )
        day = timestamp.date().isoformat() if timestamp else "Unknown"
        counts[day] = counts.get(day, 0) + 1

    return dict(sorted(counts.items()))


def _errors_by_alert_type(alerts: list[dict]) -> dict:
    """Count Telegram errors by alert type."""
    counts: dict[str, int] = {}

    for alert in alerts:
        alert_type = str(alert.get("alert_type") or "Unknown")
        counts[alert_type] = counts.get(alert_type, 0) + 1

    return dict(sorted(counts.items()))


def _recommendation(sent_true: int, total_alerts: int, alerts_with_errors: list[dict]) -> str:
    """Return a concise operational recommendation."""
    success_rate = _percentage(sent_true, total_alerts)

    if total_alerts == 0:
        return "No alert history is available yet."

    if alerts_with_errors or success_rate < 95:
        return "Investigate Telegram delivery before relying on alerts."

    return "Telegram delivery looks healthy."


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse common ISO timestamps as UTC datetimes."""
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


def _percentage(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0

    return round((numerator / denominator) * 100, 2)


def _format_latest_errors(errors: list[dict]) -> list[str]:
    if not errors:
        return ["- None"]

    return [
        (
            f"- {error.get('alerted_at')}: {error.get('symbol')} "
            f"({error.get('alert_type')}) - {error.get('telegram_error')}"
        )
        for error in errors
    ]


def _format_counts(counts: dict) -> list[str]:
    if not counts:
        return ["- None"]

    return [f"- {group}: {count}" for group, count in counts.items()]


def _format_pct(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0

    return f"{number:.2f}".rstrip("0").rstrip(".")


def _redact(value: str) -> str:
    """Redact obvious secret-bearing fragments from error strings."""
    redacted = value

    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)

    return redacted
