"""Tests for alert outcome performance reporting."""

from app.analysis.performance_report import (
    build_performance_report,
    format_performance_report,
)


def test_build_performance_report_calculates_completed_metrics() -> None:
    outcomes = {
        "BTCUSDT-1": {
            "alert_id": "BTCUSDT-1",
            "symbol": "BTCUSDT",
            "checkpoints": {"+5%": {"status": "completed"}},
            "max_upside_pct": 25,
            "max_drawdown_pct": -5,
            "opportunity_score": 80,
            "classification": "Watchlist",
            "target_bucket": "+20% momentum setup",
            "hit_5_pct": True,
            "hit_10_pct": True,
            "hit_20_pct": True,
            "hit_50_pct": False,
            "hit_100_pct": False,
        },
        "ETHUSDT-1": {
            "alert_id": "ETHUSDT-1",
            "symbol": "ETHUSDT",
            "checkpoints": [{"status": "completed"}],
            "highest_return_pct": 8,
            "max_drawdown_pct": -12,
            "opportunity_score": 60,
            "classification": "Early signal",
            "target_bucket": "Early +20% watch",
            "hit_5pct": True,
            "hit_10pct": False,
            "hit_20pct": False,
            "hit_50pct": False,
            "hit_100pct": False,
        },
        "SOLUSDT-1": {
            "alert_id": "SOLUSDT-1",
            "symbol": "SOLUSDT",
            "checkpoints": {"+5%": {"status": "pending"}},
            "max_upside_pct": 100,
            "max_drawdown_pct": -1,
            "opportunity_score": 95,
            "hit_100_pct": True,
        },
    }

    report = build_performance_report(outcomes)

    assert report["total_outcomes"] == 3
    assert report["completed_outcomes"] == 2
    assert report["pending_outcomes"] == 1
    assert report["hit_5_count"] == 2
    assert report["hit_10_count"] == 1
    assert report["hit_20_count"] == 1
    assert report["hit_50_count"] == 0
    assert report["hit_100_count"] == 0
    assert report["hit_5_rate_pct"] == 100.0
    assert report["hit_10_rate_pct"] == 50.0
    assert report["hit_20_rate_pct"] == 50.0
    assert report["average_max_upside_pct"] == 16.5
    assert report["average_max_drawdown_pct"] == -8.5
    assert report["best_symbol_by_max_upside"]["symbol"] == "BTCUSDT"
    assert report["worst_symbol_by_drawdown"]["symbol"] == "ETHUSDT"
    assert [item["symbol"] for item in report["top_5_symbols_by_max_upside"]] == [
        "BTCUSDT",
        "ETHUSDT",
    ]
    assert [
        item["symbol"]
        for item in report["top_5_symbols_by_opportunity_score"]
    ] == ["BTCUSDT", "ETHUSDT"]
    assert report["average_opportunity_score"] == 70.0
    assert report["average_upside_by_classification"] == {
        "Early signal": 8.0,
        "Watchlist": 25.0,
    }
    assert report["average_upside_by_target_bucket"] == {
        "+20% momentum setup": 25.0,
        "Early +20% watch": 8.0,
    }


def test_build_performance_report_handles_empty_outcomes() -> None:
    report = build_performance_report({})

    assert report["total_outcomes"] == 0
    assert report["completed_outcomes"] == 0
    assert report["pending_outcomes"] == 0
    assert report["hit_20_rate_pct"] == 0.0
    assert report["average_max_upside_pct"] == 0.0
    assert report["best_symbol_by_max_upside"] is None
    assert report["top_5_symbols_by_max_upside"] == []


def test_format_performance_report_returns_readable_sections() -> None:
    report = build_performance_report({})

    text = format_performance_report(report)

    assert "Overview" in text
    assert "Hit Rates" in text
    assert "Upside and Drawdown" in text
    assert "Best/Worst Symbols" in text
    assert "By Classification" in text
    assert "By Target Bucket" in text
    assert "Notes" in text
    assert (
        "No outcome data available yet. Let the bot run until alerts are "
        "generated and checked."
    ) in text
    assert "Sample size is still small. Avoid drawing strong conclusions yet." in text
    assert "No +20% moves have been confirmed yet." in text
