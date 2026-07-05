"""Tests for the parabolic paper-only trading strategy."""

import json

from app.trading import paper_trading
from app.trading.paper_trading import (
    create_paper_trades_from_alerts,
    should_create_paper_trade,
    should_create_parabolic_paper_trade,
)
from app.trading.strategy_config import get_parabolic_paper_strategy


def _parabolic_alert() -> dict:
    return {
        "id": "alert-pond",
        "symbol": "PONDUSDT",
        "latest_close": 0.025,
        "alert_type": "Parabolic Watch Alert",
        "opportunity": {
            "opportunity_score": 35,
            "classification": "High-risk watch",
            "target_bucket": "No clean upside setup",
        },
        "move_stage_signal": {
            "stage": "Stage 6 - Parabolic / high risk",
            "move_from_recent_low_pct": 90,
        },
        "liquidity_signal": {
            "score": 60,
            "label": "Good",
            "quote_volume": 20_000_000,
        },
        "tradability_signal": {
            "score": 65,
        },
        "exhaustion_signal": {
            "risk_level": "Medium",
        },
        "recent_price_changes": {
            "change_1h_pct": 1,
            "change_2h_pct": 4,
            "change_4h_pct": 11,
            "change_24h_pct": 75,
        },
        "volume_acceleration": {
            "volume_acceleration_2h_ratio": 1.4,
        },
    }


def test_parabolic_watch_alert_eligible_case_creates_paper_trade(
    monkeypatch,
    tmp_path,
) -> None:
    trades_file = tmp_path / "paper_trades.json"
    events_file = tmp_path / "paper_trade_events.json"

    monkeypatch.setattr(paper_trading, "USE_SUPABASE", False)
    monkeypatch.setattr(paper_trading, "PAPER_TRADES_FILE", str(trades_file))
    monkeypatch.setattr(paper_trading, "PAPER_TRADE_EVENTS_FILE", str(events_file))

    should_create, reason = should_create_parabolic_paper_trade(_parabolic_alert())
    decisions = create_paper_trades_from_alerts([_parabolic_alert()])
    saved_trades = json.loads(trades_file.read_text(encoding="utf-8"))

    assert should_create is True
    assert reason == "Parabolic paper trade eligible."
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "created"
    assert saved_trades[0]["id"] == decisions[0]["paper_trade_id"]
    assert decisions[0]["strategy_name"] == "parabolic_continuation_paper"
    assert decisions[0]["alert_type"] == "Parabolic Watch Alert"
    assert decisions[0]["trade_plan_type"] == "parabolic_high_risk_paper"
    assert saved_trades[0]["simulated_position_size"] == 25
    assert saved_trades[0]["stop_loss_pct"] == -8
    assert saved_trades[0]["take_profit_1_pct"] == 12
    assert saved_trades[0]["take_profit_2_pct"] == 25
    assert saved_trades[0]["take_profit_3_pct"] == 50
    assert saved_trades[0]["max_hold_hours"] == 24


def test_parabolic_rejected_when_move_too_extended_above_150_pct() -> None:
    alert = _parabolic_alert()
    alert["move_stage_signal"]["move_from_recent_low_pct"] = 151

    should_create, reason = should_create_parabolic_paper_trade(alert)

    assert should_create is False
    assert "between 50% and 150%" in reason


def test_parabolic_rejected_when_24h_change_below_40_pct() -> None:
    alert = _parabolic_alert()
    alert["recent_price_changes"]["change_24h_pct"] = 39.9

    should_create, reason = should_create_parabolic_paper_trade(alert)

    assert should_create is False
    assert "24h change is below 40%" in reason


def test_parabolic_rejected_when_exhaustion_risk_is_high() -> None:
    alert = _parabolic_alert()
    alert["exhaustion_signal"]["risk_level"] = "High"

    should_create, reason = should_create_parabolic_paper_trade(alert)

    assert should_create is False
    assert "Exhaustion risk is High" in reason


def test_parabolic_thin_liquidity_requires_minimum_quote_volume() -> None:
    alert = _parabolic_alert()
    alert["liquidity_signal"] = {
        "score": 40,
        "label": "Thin",
        "quote_volume": 4_999_999,
    }

    should_create, reason = should_create_parabolic_paper_trade(alert)

    assert should_create is False
    assert "at least 5,000,000" in reason

    alert["liquidity_signal"]["quote_volume"] = 5_000_000

    should_create, reason = should_create_parabolic_paper_trade(alert)

    assert should_create is True
    assert reason == "Parabolic paper trade eligible."


def test_parabolic_strategy_risk_and_position_values() -> None:
    strategy = get_parabolic_paper_strategy()

    assert strategy.simulated_position_size == 25
    assert strategy.stop_loss_pct == -8
    assert strategy.take_profit_1_pct == 12
    assert strategy.take_profit_2_pct == 25
    assert strategy.take_profit_3_pct == 50
    assert strategy.max_hold_hours == 24


def test_standard_paper_rules_do_not_treat_parabolic_as_continuation() -> None:
    should_create, reason = should_create_paper_trade(_parabolic_alert())

    assert should_create is False
    assert "Parabolic Watch Alert" in reason
