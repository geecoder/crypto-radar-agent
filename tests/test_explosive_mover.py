"""Tests for explosive mover detection and alert typing."""

import pandas as pd

from app.indicators.explosive_mover import (
    calculate_recent_price_changes,
    calculate_volume_acceleration,
    classify_explosive_mover,
)
from app.trading.paper_trading import should_create_paper_trade


def _signal(score: int) -> dict:
    return {"score": score}


def _move_signal(move_pct: float) -> dict:
    return {"move_from_recent_low_pct": move_pct, "score": 70}


def _changes(
    change_1h: float = 0,
    change_2h: float = 0,
    change_4h: float = 0,
    change_24h: float = 0,
) -> dict:
    return {
        "change_15m_pct": 0,
        "change_30m_pct": 0,
        "change_1h_pct": change_1h,
        "change_2h_pct": change_2h,
        "change_4h_pct": change_4h,
        "change_24h_pct": change_24h,
    }


def test_calculate_recent_price_changes_uses_15m_candle_windows() -> None:
    candles = pd.DataFrame(
        {
            "close": [100.0] * 96 + [110.0],
            "volume": [1.0] * 97,
        }
    )

    changes = calculate_recent_price_changes(candles)

    assert changes["change_15m_pct"] == 10.0
    assert changes["change_1h_pct"] == 10.0
    assert changes["change_24h_pct"] == 10.0


def test_volume_acceleration_scoring() -> None:
    candles = pd.DataFrame(
        {
            "close": [1.0] * 16,
            "volume": [10.0] * 12 + [50.0] * 4,
        }
    )

    acceleration = calculate_volume_acceleration(candles)

    assert acceleration["latest_1h_volume"] == 200.0
    assert acceleration["previous_1h_volume"] == 40.0
    assert acceleration["latest_2h_volume"] == 240.0
    assert acceleration["previous_2h_volume"] == 80.0
    assert acceleration["volume_acceleration_1h_ratio"] == 5.0
    assert acceleration["volume_acceleration_2h_ratio"] == 3.0
    assert acceleration["score"] == 100


def test_classify_explosive_mover_returns_early_pump_alert() -> None:
    result = classify_explosive_mover(
        _move_signal(5),
        _changes(change_1h=3.5),
        _signal(40),
        _signal(40),
        {"risk_level": "Low", "risk_score": 10},
        _signal(40),
        _signal(60),
        _signal(40),
    )

    assert result["should_alert"] is True
    assert result["alert_type"] == "Early Pump Alert"
    assert result["potential_bucket"] == "+20% early continuation watch"


def test_classify_explosive_mover_returns_active_breakout_alert() -> None:
    result = classify_explosive_mover(
        _move_signal(15),
        _changes(change_1h=5),
        _signal(60),
        _signal(40),
        {"risk_level": "Medium", "risk_score": 30},
        _signal(60),
        _signal(60),
        _signal(60),
    )

    assert result["should_alert"] is True
    assert result["alert_type"] == "Active Breakout Alert"
    assert result["potential_bucket"] == "+50% high-volatility continuation watch"


def test_classify_explosive_mover_returns_parabolic_watch_alert() -> None:
    result = classify_explosive_mover(
        _move_signal(78),
        _changes(change_4h=35, change_24h=80),
        _signal(80),
        _signal(60),
        {"risk_level": "High", "risk_score": 80},
        _signal(0),
        _signal(40),
        _signal(80),
    )

    assert result["should_alert"] is True
    assert result["alert_type"] == "Parabolic Watch Alert"
    assert result["risk_level"] == "Very High"
    assert result["confidence"] == "High"
    assert "not a clean entry signal" in result["reason"]


def test_classify_explosive_mover_returns_no_alert_for_weak_movement() -> None:
    result = classify_explosive_mover(
        _move_signal(2),
        _changes(change_1h=1, change_2h=2),
        _signal(10),
        _signal(60),
        {"risk_level": "Low", "risk_score": 0},
        _signal(0),
        _signal(40),
        _signal(20),
    )

    assert result["should_alert"] is False
    assert result["alert_type"] == "No explosive mover alert"


def test_parabolic_watch_does_not_qualify_for_paper_trading() -> None:
    should_create, reason = should_create_paper_trade(
        {
            "alert_type": "Parabolic Watch Alert",
            "symbol": "EDENUSDT",
            "latest_close": 1.0,
            "opportunity": {"opportunity_score": 90},
            "continuation_target": {"target_bucket": "+100% speculative momentum watch"},
            "move_stage_signal": {"move_from_recent_low_pct": 8},
            "liquidity_signal": {"label": "Strong"},
            "exhaustion_signal": {"risk_level": "Low"},
        }
    )

    assert should_create is False
    assert "Parabolic Watch Alert" in reason
