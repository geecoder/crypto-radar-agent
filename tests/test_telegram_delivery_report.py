"""Tests for Telegram delivery monitoring reports."""

from app.analysis.telegram_delivery import (
    build_telegram_delivery_report,
    format_telegram_delivery_report,
)


def test_delivery_success_rate_calculation() -> None:
    report = build_telegram_delivery_report(
        [
            {"telegram_sent": True},
            {"telegram_sent": True},
            {"telegram_sent": False},
            {"telegram_sent": False, "telegram_error": "Telegram send failed"},
        ]
    )

    assert report["total_alerts"] == 4
    assert report["telegram_sent_true"] == 2
    assert report["telegram_sent_false"] == 2
    assert report["telegram_error_count"] == 1
    assert report["delivery_success_rate_pct"] == 50.0


def test_errors_grouped_by_day_and_alert_type() -> None:
    report = build_telegram_delivery_report(
        [
            {
                "telegram_sent": False,
                "telegram_error": "Telegram send failed",
                "alerted_at": "2026-05-01T00:00:00+00:00",
                "alert_type": "Continuation Alert",
            },
            {
                "telegram_sent": False,
                "telegram_error": "Telegram disabled",
                "alerted_at": "2026-05-01T01:00:00+00:00",
                "alert_type": "Speculative Early Runner Alert",
            },
            {
                "telegram_sent": False,
                "telegram_error": "Telegram send failed",
                "alerted_at": "2026-05-02T00:00:00+00:00",
                "alert_type": "Continuation Alert",
            },
        ]
    )

    assert report["errors_by_day"] == {
        "2026-05-01": 2,
        "2026-05-02": 1,
    }
    assert report["errors_by_alert_type"] == {
        "Continuation Alert": 2,
        "Speculative Early Runner Alert": 1,
    }


def test_formatter_includes_recommendations_and_redacts_secrets() -> None:
    report = build_telegram_delivery_report(
        [
            {
                "symbol": "BTCUSDT",
                "alert_type": "Continuation Alert",
                "telegram_sent": False,
                "telegram_error": (
                    "Request failed at "
                    "https://api.telegram.org/bot123456:SECRET/sendMessage"
                ),
                "alerted_at": "2026-05-01T00:00:00+00:00",
            }
        ]
    )

    formatted = format_telegram_delivery_report(report)

    assert "Crypto Radar Telegram Delivery Report" in formatted
    assert "Total alerts reviewed: 1" in formatted
    assert "Investigate Telegram delivery before relying on alerts." in formatted
    assert "SECRET" not in formatted
    assert "123456" not in formatted
