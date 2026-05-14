"""Tests for local alert history logging."""

from datetime import datetime

from app.alerts import alert_history


def _sample_result() -> dict:
    return {
        "symbol": "BTCUSDT",
        "latest_close": 100.0,
        "volume_signal": {"score": 80, "reason": "Volume expanded."},
        "momentum_signal": {"score": 70, "reason": "Price momentum improved."},
        "breakout_signal": {"score": 65, "reason": "Testing resistance."},
        "trend_signal": {"score": 75, "reason": "Trend is aligned."},
        "volatility_signal": {"score": 60, "reason": "Volatility is rising."},
        "opportunity": {
            "opportunity_score": 72,
            "classification": "Watchlist",
            "target_bucket": "+20% momentum setup",
            "risk_level": "Medium",
            "summary": "Watchlist. Some signals are improving.",
            "component_scores": {
                "volume": 80,
                "momentum": 70,
                "breakout": 65,
                "trend": 75,
                "volatility": 60,
            },
        },
    }


def test_build_alert_history_record_includes_scan_fields() -> None:
    result = _sample_result()

    record = alert_history.build_alert_history_record(result, telegram_sent=True)

    assert record == {
        "id": f"BTCUSDT-{record['alerted_at']}",
        "symbol": "BTCUSDT",
        "alerted_at": record["alerted_at"],
        "latest_close": 100.0,
        "opportunity_score": 72,
        "classification": "Watchlist",
        "target_bucket": "+20% momentum setup",
        "risk_level": "Medium",
        "summary": "Watchlist. Some signals are improving.",
        "component_scores": result["opportunity"]["component_scores"],
        "volume_signal": result["volume_signal"],
        "momentum_signal": result["momentum_signal"],
        "breakout_signal": result["breakout_signal"],
        "trend_signal": result["trend_signal"],
        "volatility_signal": result["volatility_signal"],
        "telegram_sent": True,
    }
    assert datetime.fromisoformat(record["alerted_at"])


def test_append_alert_history_loads_appends_and_saves(monkeypatch, tmp_path) -> None:
    history_file = tmp_path / "data" / "alert_history.json"
    monkeypatch.setattr(alert_history, "ALERT_HISTORY_FILE", str(history_file))

    first_record = alert_history.append_alert_history(
        _sample_result(),
        telegram_sent=False,
    )
    second_record = alert_history.append_alert_history(
        _sample_result(),
        telegram_sent=True,
    )

    assert history_file.exists()
    assert alert_history.load_alert_history() == [first_record, second_record]


def test_load_alert_history_returns_empty_list_for_missing_or_invalid_file(
    monkeypatch,
    tmp_path,
) -> None:
    history_file = tmp_path / "data" / "alert_history.json"
    monkeypatch.setattr(alert_history, "ALERT_HISTORY_FILE", str(history_file))

    assert alert_history.load_alert_history() == []

    history_file.parent.mkdir(parents=True)
    history_file.write_text("{not-json", encoding="utf-8")

    assert alert_history.load_alert_history() == []
