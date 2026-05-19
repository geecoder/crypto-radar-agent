"""Tests for advisory trade-plan generation."""

from app.trading.trade_plan import generate_trade_plan, round_price


def _base_result(alert_type: str = "Continuation Alert") -> dict:
    return {
        "symbol": "BTCUSDT",
        "alert_type": alert_type,
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


def test_round_price_preserves_sensible_precision() -> None:
    assert round_price(1234.567) == 1234.57
    assert round_price(12.34567) == 12.3457
    assert round_price(0.1234567) == 0.123457
    assert round_price(0.00123456789) == 0.00123457


def test_generate_trade_plan_for_early_pump_alert() -> None:
    plan = generate_trade_plan(_base_result("Early Pump Alert"))

    assert plan["trade_plan_type"] == "early_momentum_continuation"
    assert plan["recommended_action"] == "Monitor for confirmation or pullback"
    assert plan["entry_approach"] == "Wait for 15m candle confirmation or shallow pullback"
    assert plan["entry_zone_low"] == 97.0
    assert plan["entry_zone_high"] == 100.0
    assert plan["stop_loss_price"] == 95.0
    assert plan["stop_loss_pct"] == -5
    assert plan["take_profit_1_price"] == 108.0
    assert plan["take_profit_1_pct"] == 8
    assert plan["take_profit_2_price"] == 115.0
    assert plan["take_profit_2_pct"] == 15
    assert plan["take_profit_3_price"] == 120.0
    assert plan["take_profit_3_pct"] == 20
    assert plan["max_hold_hours"] == 48
    assert plan["should_paper_trade"] is True


def test_generate_trade_plan_for_active_breakout_alert() -> None:
    plan = generate_trade_plan(_base_result("Active Breakout Alert"))

    assert plan["trade_plan_type"] == "active_breakout_continuation"
    assert (
        plan["recommended_action"]
        == "Monitor breakout continuation; avoid chasing large candle tops"
    )
    assert (
        plan["entry_approach"]
        == "Prefer retest of breakout zone or 15m close above resistance"
    )
    assert plan["entry_zone_low"] == 96.0
    assert plan["stop_loss_price"] == 94.0
    assert plan["stop_loss_pct"] == -6
    assert plan["take_profit_1_price"] == 110.0
    assert plan["take_profit_1_pct"] == 10
    assert plan["take_profit_2_price"] == 120.0
    assert plan["take_profit_2_pct"] == 20
    assert plan["take_profit_3_price"] == 135.0
    assert plan["take_profit_3_pct"] == 35
    assert plan["should_paper_trade"] is True


def test_generate_trade_plan_for_continuation_alert() -> None:
    plan = generate_trade_plan(_base_result("Continuation Alert"))

    assert plan["trade_plan_type"] == "standard_continuation"
    assert plan["recommended_action"] == "Monitor for continuation setup"
    assert plan["entry_approach"] == "Use confirmation candle or pullback entry"
    assert plan["entry_zone_low"] == 98.0
    assert plan["entry_zone_high"] == 100.0
    assert plan["stop_loss_price"] == 95.0
    assert plan["take_profit_1_price"] == 108.0
    assert plan["take_profit_2_price"] == 115.0
    assert plan["take_profit_3_price"] == 120.0
    assert plan["max_hold_hours"] == 48
    assert plan["should_paper_trade"] is True
    assert plan["reason"] == "Paper trade eligible."


def test_generate_trade_plan_for_parabolic_watch_is_monitoring_only() -> None:
    plan = generate_trade_plan(_base_result("Parabolic Watch Alert"))

    assert plan["trade_plan_type"] == "parabolic_watch_only"
    assert plan["recommended_action"] == "Watch only; do not chase"
    assert (
        plan["entry_approach"]
        == "Wait for pullback, consolidation, or retest. No clean entry currently."
    )
    assert plan["entry_zone_low"] is None
    assert plan["entry_zone_high"] is None
    assert plan["stop_loss_price"] is None
    assert plan["take_profit_1_price"] is None
    assert plan["take_profit_2_price"] is None
    assert plan["take_profit_3_price"] is None
    assert plan["max_hold_hours"] is None
    assert plan["should_paper_trade"] is False
    assert (
        plan["risk_note"]
        == "Very high risk. This is a market activity alert, not a clean entry signal."
    )


def test_generate_trade_plan_rejects_thin_liquidity_for_paper_trade() -> None:
    result = _base_result("Early Pump Alert")
    result["liquidity_signal"]["label"] = "Thin"

    plan = generate_trade_plan(result)

    assert plan["should_paper_trade"] is False


def test_generate_trade_plan_rejects_high_exhaustion_for_paper_trade() -> None:
    result = _base_result("Active Breakout Alert")
    result["exhaustion_signal"]["risk_level"] = "High"

    plan = generate_trade_plan(result)

    assert plan["should_paper_trade"] is False
