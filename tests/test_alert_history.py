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
        "continuation_target": {"target_bucket": "+20% continuation watch"},
        "move_stage_signal": {
            "stage": "Stage 3 - Confirmed early momentum",
            "move_from_recent_low_pct": 8.5,
        },
        "liquidity_signal": {"label": "Strong"},
        "exhaustion_signal": {"risk_level": "Medium"},
        "recent_price_changes": {"change_1h_pct": 2.5},
        "volume_acceleration": {"volume_acceleration_1h_ratio": 1.5},
        "trade_plan": {
            "trade_plan_type": "standard_continuation",
            "should_paper_trade": True,
        },
        "scan_run_id": "scan-1",
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

    assert record["id"] == f"BTCUSDT-{record['alerted_at']}"
    assert record["symbol"] == "BTCUSDT"
    assert record["latest_close"] == 100.0
    assert record["opportunity_score"] == 72
    assert record["classification"] == "Watchlist"
    assert record["target_bucket"] == "+20% momentum setup"
    assert record["continuation_target"] == "+20% continuation watch"
    assert record["move_stage"] == "Stage 3 - Confirmed early momentum"
    assert record["move_from_recent_low_pct"] == 8.5
    assert record["liquidity_label"] == "Strong"
    assert record["exhaustion_risk_level"] == "Medium"
    assert record["alert_type"] == "Continuation Alert"
    assert record["recent_price_changes"] == {"change_1h_pct": 2.5}
    assert record["volume_acceleration"] == {"volume_acceleration_1h_ratio": 1.5}
    assert record["trade_plan_type"] == "standard_continuation"
    assert record["should_paper_trade"] is True
    assert record["scan_run_id"] == "scan-1"
    assert record["source"] == "scanner"
    assert record["component_scores"] == result["opportunity"]["component_scores"]
    assert record["volume_signal"] == result["volume_signal"]
    assert record["momentum_signal"] == result["momentum_signal"]
    assert record["breakout_signal"] == result["breakout_signal"]
    assert record["trend_signal"] == result["trend_signal"]
    assert record["volatility_signal"] == result["volatility_signal"]
    assert record["telegram_sent"] is True
    assert record["paper_trade_created"] is False
    assert datetime.fromisoformat(record["alerted_at"])


def test_append_alert_history_loads_appends_and_saves(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(alert_history, "USE_SUPABASE", False)
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
    monkeypatch.setattr(alert_history, "USE_SUPABASE", False)
    history_file = tmp_path / "data" / "alert_history.json"
    monkeypatch.setattr(alert_history, "ALERT_HISTORY_FILE", str(history_file))

    assert alert_history.load_alert_history() == []

    history_file.parent.mkdir(parents=True)
    history_file.write_text("{not-json", encoding="utf-8")

    assert alert_history.load_alert_history() == []


def test_load_alert_history_uses_supabase_when_enabled(monkeypatch) -> None:
    supabase_history = [{"id": "BTCUSDT-1", "symbol": "BTCUSDT"}]

    monkeypatch.setattr(alert_history, "USE_SUPABASE", True)
    monkeypatch.setattr(
        alert_history.supabase_store,
        "load_alert_history",
        lambda limit=None: supabase_history,
    )

    assert alert_history.load_alert_history(limit=10) == supabase_history


def test_append_alert_history_inserts_supabase_when_enabled(monkeypatch) -> None:
    inserted_records = []

    monkeypatch.setattr(alert_history, "USE_SUPABASE", True)
    monkeypatch.setattr(
        alert_history.supabase_store,
        "insert_alert_history",
        inserted_records.append,
    )

    record = alert_history.append_alert_history(
        _sample_result(),
        telegram_sent=True,
    )

    assert inserted_records == [record]
    assert record["symbol"] == "BTCUSDT"
