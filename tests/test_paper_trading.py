"""Tests for the simulated paper trading engine."""

import json
from datetime import datetime, timedelta, timezone

import pandas as pd

from app.trading import paper_trading
from app.trading.paper_trading import (
    build_paper_trade_from_alert,
    evaluate_open_paper_trade,
    should_create_paper_trade,
)


def _eligible_alert() -> dict:
    """Return a scan result eligible for paper trading."""
    return {
        "id": "alert-1",
        "symbol": "BTCUSDT",
        "latest_close": 100.0,
        "opportunity": {
            "opportunity_score": 72,
            "classification": "Watchlist",
            "target_bucket": "+20% momentum setup",
        },
        "continuation_target": {
            "target_bucket": "+20% continuation watch",
        },
        "move_stage_signal": {
            "stage": "Stage 3 - Confirmed early momentum",
            "move_from_recent_low_pct": 8.5,
        },
        "liquidity_signal": {
            "label": "Strong",
        },
        "exhaustion_signal": {
            "risk_level": "Medium",
        },
    }


def _open_trade(opened_at: datetime) -> dict:
    """Return a basic open paper trade."""
    return {
        "id": "paper_BTCUSDT_test",
        "symbol": "BTCUSDT",
        "opened_at": opened_at.isoformat(),
        "entry_price": 100.0,
        "status": "open",
        "direction": "long",
        "stop_loss_pct": -5,
        "take_profit_1_pct": 8,
        "take_profit_2_pct": 15,
        "take_profit_3_pct": 20,
        "max_hold_hours": 48,
        "simulated_position_size": 100,
    }


def _candles(opened_at: datetime, rows: list[dict]) -> pd.DataFrame:
    """Build a candle DataFrame relative to the opened time."""
    return pd.DataFrame(
        [
            {
                "open_time": opened_at + timedelta(hours=row["hours_after_open"]),
                "open": row.get("open", 100.0),
                "high": row.get("high", 100.0),
                "low": row.get("low", 100.0),
                "close": row.get("close", 100.0),
                "volume": row.get("volume", 1.0),
            }
            for row in rows
        ]
    )


def test_should_create_paper_trade_true_case() -> None:
    should_create, reason = should_create_paper_trade(_eligible_alert())

    assert should_create is True
    assert reason == "Paper trade eligible."


def test_should_create_paper_trade_rejects_low_score() -> None:
    alert = _eligible_alert()
    alert["opportunity"]["opportunity_score"] = 64

    should_create, reason = should_create_paper_trade(alert)

    assert should_create is False
    assert "below 65" in reason


def test_should_create_paper_trade_rejects_thin_liquidity() -> None:
    alert = _eligible_alert()
    alert["liquidity_signal"]["label"] = "Thin"

    should_create, reason = should_create_paper_trade(alert)

    assert should_create is False
    assert "thin" in reason.lower()


def test_should_create_paper_trade_rejects_high_exhaustion() -> None:
    alert = _eligible_alert()
    alert["exhaustion_signal"]["risk_level"] = "High"

    should_create, reason = should_create_paper_trade(alert)

    assert should_create is False
    assert "High" in reason


def test_build_paper_trade_from_alert() -> None:
    trade = build_paper_trade_from_alert(_eligible_alert())

    assert trade["id"].startswith("paper_BTCUSDT_")
    assert trade["alert_id"] == "alert-1"
    assert trade["symbol"] == "BTCUSDT"
    assert trade["entry_price"] == 100.0
    assert trade["status"] == "open"
    assert trade["direction"] == "long"
    assert trade["opportunity_score"] == 72
    assert trade["classification"] == "Watchlist"
    assert trade["target_bucket"] == "+20% momentum setup"
    assert trade["continuation_target"] == "+20% continuation watch"
    assert trade["move_stage"] == "Stage 3 - Confirmed early momentum"
    assert trade["move_from_recent_low_pct"] == 8.5
    assert trade["liquidity_label"] == "Strong"
    assert trade["exhaustion_risk_level"] == "Medium"
    assert trade["stop_loss_pct"] == -5
    assert trade["take_profit_1_pct"] == 8
    assert trade["take_profit_2_pct"] == 15
    assert trade["take_profit_3_pct"] == 20
    assert trade["max_hold_hours"] == 48
    assert trade["simulated_position_size"] == 100


def test_create_paper_trades_from_alerts_saves_json_fallback(
    monkeypatch,
    tmp_path,
) -> None:
    trades_file = tmp_path / "paper_trades.json"
    events_file = tmp_path / "paper_trade_events.json"

    monkeypatch.setattr(paper_trading, "USE_SUPABASE", False)
    monkeypatch.setattr(paper_trading, "PAPER_TRADES_FILE", str(trades_file))
    monkeypatch.setattr(paper_trading, "PAPER_TRADE_EVENTS_FILE", str(events_file))

    created = paper_trading.create_paper_trades_from_alerts([_eligible_alert()])

    saved_trades = json.loads(trades_file.read_text(encoding="utf-8"))
    saved_events = json.loads(events_file.read_text(encoding="utf-8"))

    assert len(created) == 1
    assert saved_trades[0]["id"] == created[0]["id"]
    assert saved_events[0]["trade_id"] == created[0]["id"]
    assert saved_events[0]["type"] == "opened"


def test_evaluate_open_paper_trade_stop_loss() -> None:
    opened_at = datetime(2026, 5, 17, tzinfo=timezone.utc)
    updates = evaluate_open_paper_trade(
        _open_trade(opened_at),
        _candles(
            opened_at,
            [
                {
                    "hours_after_open": 1,
                    "high": 103.0,
                    "low": 94.0,
                    "close": 96.0,
                },
            ],
        ),
    )

    assert updates["status"] == "closed"
    assert updates["exit_reason"] == "stop_loss"
    assert updates["exit_price"] == 95.0
    assert updates["pnl_pct"] == -5.0
    assert updates["pnl_amount"] == -5.0


def test_evaluate_open_paper_trade_take_profit() -> None:
    opened_at = datetime(2026, 5, 17, tzinfo=timezone.utc)
    updates = evaluate_open_paper_trade(
        _open_trade(opened_at),
        _candles(
            opened_at,
            [
                {
                    "hours_after_open": 1,
                    "high": 121.0,
                    "low": 99.0,
                    "close": 118.0,
                },
            ],
        ),
    )

    assert updates["status"] == "closed"
    assert updates["exit_reason"] == "take_profit_3"
    assert updates["exit_price"] == 120.0
    assert updates["pnl_pct"] == 20.0
    assert updates["pnl_amount"] == 20.0


def test_evaluate_open_paper_trade_max_hold_expiry() -> None:
    opened_at = datetime(2026, 5, 17, tzinfo=timezone.utc)
    updates = evaluate_open_paper_trade(
        _open_trade(opened_at),
        _candles(
            opened_at,
            [
                {
                    "hours_after_open": 49,
                    "high": 104.0,
                    "low": 98.0,
                    "close": 103.0,
                },
            ],
        ),
    )

    assert updates["status"] == "closed"
    assert updates["exit_reason"] == "max_hold_expired"
    assert updates["exit_price"] == 103.0
    assert updates["pnl_pct"] == 3.0
    assert updates["pnl_amount"] == 3.0
