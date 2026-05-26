"""Tests for configurable paper trading strategies."""

from app.trading.paper_trading import (
    build_paper_trade_from_alert,
    should_create_paper_trade,
)
from app.trading.strategy_config import (
    get_aggressive_paper_trading_strategy,
    get_conservative_paper_trading_strategy,
    get_default_paper_trading_strategy,
    get_parabolic_paper_strategy,
    get_strategy_by_name,
)


def _eligible_alert(
    opportunity_score: int = 80,
    move_from_low_pct: float = 8.5,
) -> dict:
    return {
        "symbol": "BTCUSDT",
        "latest_close": 100.0,
        "opportunity": {
            "opportunity_score": opportunity_score,
            "classification": "Watchlist",
            "target_bucket": "+20% momentum setup",
        },
        "continuation_target": {
            "target_bucket": "+20% continuation watch",
        },
        "move_stage_signal": {
            "stage": "Stage 3 - Confirmed early momentum",
            "move_from_recent_low_pct": move_from_low_pct,
        },
        "liquidity_signal": {
            "label": "Strong",
        },
        "exhaustion_signal": {
            "risk_level": "Medium",
        },
    }


def test_default_strategy_values() -> None:
    strategy = get_default_paper_trading_strategy()

    assert strategy.name == "default_momentum_continuation"
    assert strategy.minimum_opportunity_score == 65
    assert strategy.min_move_from_recent_low_pct == 3
    assert strategy.max_move_from_recent_low_pct == 20
    assert strategy.allow_thin_liquidity is False
    assert strategy.allow_high_exhaustion is False
    assert strategy.stop_loss_pct == -5
    assert strategy.take_profit_1_pct == 8
    assert strategy.take_profit_2_pct == 15
    assert strategy.take_profit_3_pct == 20
    assert strategy.max_hold_hours == 48
    assert strategy.simulated_position_size == 100


def test_conservative_strategy_values() -> None:
    strategy = get_conservative_paper_trading_strategy()

    assert strategy.name == "conservative_momentum"
    assert strategy.minimum_opportunity_score == 75
    assert strategy.min_move_from_recent_low_pct == 3
    assert strategy.max_move_from_recent_low_pct == 15
    assert strategy.allow_thin_liquidity is False
    assert strategy.allow_high_exhaustion is False
    assert strategy.stop_loss_pct == -3
    assert strategy.take_profit_1_pct == 6
    assert strategy.take_profit_2_pct == 10
    assert strategy.take_profit_3_pct == 15
    assert strategy.max_hold_hours == 24
    assert strategy.simulated_position_size == 100


def test_aggressive_strategy_values() -> None:
    strategy = get_aggressive_paper_trading_strategy()

    assert strategy.name == "aggressive_high_volatility"
    assert strategy.minimum_opportunity_score == 65
    assert strategy.min_move_from_recent_low_pct == 5
    assert strategy.max_move_from_recent_low_pct == 30
    assert strategy.allow_thin_liquidity is False
    assert strategy.allow_high_exhaustion is False
    assert strategy.stop_loss_pct == -7
    assert strategy.take_profit_1_pct == 10
    assert strategy.take_profit_2_pct == 20
    assert strategy.take_profit_3_pct == 35
    assert strategy.max_hold_hours == 48
    assert strategy.simulated_position_size == 100


def test_parabolic_strategy_values() -> None:
    strategy = get_parabolic_paper_strategy()

    assert strategy.name == "parabolic_continuation_paper"
    assert strategy.minimum_opportunity_score == 25
    assert strategy.min_move_from_recent_low_pct == 50
    assert strategy.max_move_from_recent_low_pct == 150
    assert strategy.allow_thin_liquidity is True
    assert strategy.allow_high_exhaustion is False
    assert strategy.stop_loss_pct == -8
    assert strategy.take_profit_1_pct == 12
    assert strategy.take_profit_2_pct == 25
    assert strategy.take_profit_3_pct == 50
    assert strategy.max_hold_hours == 24
    assert strategy.simulated_position_size == 25


def test_get_strategy_by_name_fallback() -> None:
    assert get_strategy_by_name(None).name == "default_momentum_continuation"
    assert get_strategy_by_name("default").name == "default_momentum_continuation"
    assert get_strategy_by_name("conservative").name == "conservative_momentum"
    assert get_strategy_by_name("aggressive").name == "aggressive_high_volatility"
    assert get_strategy_by_name("parabolic").name == "parabolic_continuation_paper"
    assert get_strategy_by_name("unknown").name == "default_momentum_continuation"


def test_should_create_paper_trade_respects_minimum_score() -> None:
    strategy = get_conservative_paper_trading_strategy()

    should_create, reason = should_create_paper_trade(
        _eligible_alert(opportunity_score=74),
        strategy=strategy,
    )

    assert should_create is False
    assert "below 75" in reason


def test_should_create_paper_trade_respects_max_move_from_recent_low() -> None:
    strategy = get_conservative_paper_trading_strategy()

    should_create, reason = should_create_paper_trade(
        _eligible_alert(move_from_low_pct=16),
        strategy=strategy,
    )

    assert should_create is False
    assert "between 3% and 15%" in reason


def test_build_paper_trade_from_alert_uses_strategy_exit_values() -> None:
    strategy = get_aggressive_paper_trading_strategy()

    trade = build_paper_trade_from_alert(_eligible_alert(), strategy=strategy)

    assert trade["strategy_name"] == "aggressive_high_volatility"
    assert trade["stop_loss_pct"] == -7
    assert trade["take_profit_1_pct"] == 10
    assert trade["take_profit_2_pct"] == 20
    assert trade["take_profit_3_pct"] == 35
    assert trade["max_hold_hours"] == 48
    assert trade["simulated_position_size"] == 100
