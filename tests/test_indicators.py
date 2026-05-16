"""Tests for basic signal indicators."""

import pandas as pd
import pytest

from app.indicators.breakout import calculate_breakout_strength
from app.indicators.continuation import calculate_continuation_target
from app.indicators.exhaustion import calculate_exhaustion_risk
from app.indicators.liquidity import calculate_liquidity_quality
from app.indicators.momentum import calculate_price_momentum
from app.indicators.move_stage import calculate_move_stage
from app.indicators.trend import calculate_trend_alignment
from app.indicators.volatility import calculate_volatility_potential
from app.indicators.volume import calculate_volume_spike


def test_calculate_volume_spike_scores_latest_volume_against_previous_average() -> None:
    candles = pd.DataFrame({"volume": [10.0] * 20 + [25.0]})

    result = calculate_volume_spike(candles)

    assert result["name"] == "volume_spike"
    assert result["latest_volume"] == 25.0
    assert result["average_volume"] == 10.0
    assert result["volume_ratio"] == 2.5
    assert result["score"] == 60


def test_calculate_price_momentum_scores_percentage_change() -> None:
    candles = pd.DataFrame({"close": [100.0] + [101.0] * 19 + [106.0]})

    result = calculate_price_momentum(candles)

    assert result["name"] == "price_momentum"
    assert result["lookback"] == 20
    assert result["start_price"] == 100.0
    assert result["latest_price"] == 106.0
    assert result["percentage_change"] == pytest.approx(6.0)
    assert result["score"] == 60


def test_calculate_breakout_strength_scores_close_above_previous_high() -> None:
    candles = pd.DataFrame(
        {
            "high": [100.0] * 20 + [103.0],
            "close": [95.0] * 20 + [102.0],
        }
    )

    result = calculate_breakout_strength(candles)

    assert result["name"] == "breakout_strength"
    assert result["lookback"] == 20
    assert result["latest_close"] == 102.0
    assert result["previous_high"] == 100.0
    assert result["is_breakout"] is True
    assert result["breakout_percentage"] == pytest.approx(2.0)
    assert result["score"] == 60


def test_calculate_trend_alignment_scores_bullish_moving_average_alignment() -> None:
    candles = pd.DataFrame({"close": list(range(1, 22))})

    result = calculate_trend_alignment(candles)

    assert result["name"] == "trend_alignment"
    assert result["short_window"] == 9
    assert result["long_window"] == 21
    assert result["latest_close"] == 21.0
    assert result["short_sma"] == pytest.approx(17.0)
    assert result["long_sma"] == pytest.approx(11.0)
    assert result["score"] == 100


def test_calculate_volatility_potential_scores_recent_range() -> None:
    candles = pd.DataFrame(
        {
            "high": [110.0] * 20,
            "low": [90.0] * 20,
            "close": [100.0] * 20,
        }
    )

    result = calculate_volatility_potential(candles)

    assert result["name"] == "volatility_potential"
    assert result["lookback"] == 20
    assert result["average_candle_range_pct"] == pytest.approx(20.0)
    assert result["recent_range_pct"] == pytest.approx(20.0)
    assert result["score"] == 100


def test_calculate_move_stage_identifies_confirmed_early_move() -> None:
    candles = pd.DataFrame(
        {
            "low": [100.0] * 96,
            "close": [101.0] * 95 + [108.0],
        }
    )

    result = calculate_move_stage(candles)

    assert result["name"] == "move_stage"
    assert result["lookback"] == 96
    assert result["latest_close"] == 108.0
    assert result["recent_low"] == 100.0
    assert result["move_from_recent_low_pct"] == pytest.approx(8.0)
    assert result["stage"] == "Stage 3 - Confirmed early momentum"
    assert result["score"] == 90


def test_calculate_exhaustion_risk_scores_overextended_move() -> None:
    candles = pd.DataFrame(
        {
            "open": [100.0] * 20 + [140.0],
            "high": [100.0] * 20 + [150.0],
            "low": [99.0] * 21,
            "close": [100.0] * 20 + [135.0],
        }
    )

    result = calculate_exhaustion_risk(candles)

    assert result["name"] == "exhaustion_risk"
    assert result["recent_change_pct"] == pytest.approx(35.0)
    assert result["upper_wick_pct"] == pytest.approx(7.407407)
    assert result["distance_above_sma_pct"] > 10
    assert result["risk_score"] == 100
    assert result["risk_level"] == "High"


def test_calculate_liquidity_quality_scores_24hr_ticker() -> None:
    result = calculate_liquidity_quality(
        {"quoteVolume": "150000000", "count": "300000"}
    )

    assert result["name"] == "liquidity_quality"
    assert result["quote_volume"] == 150_000_000.0
    assert result["trade_count"] == 300_000
    assert result["score"] == 80
    assert result["label"] == "Strong"


def test_calculate_continuation_target_returns_plus_100_watch() -> None:
    result = calculate_continuation_target(
        opportunity_score=88,
        move_stage_signal={"score": 90, "move_from_recent_low_pct": 8.0},
        volume_signal={"score": 80},
        momentum_signal={"score": 80},
        breakout_signal={"score": 80},
        trend_signal={"score": 80},
        volatility_signal={"score": 100},
        liquidity_signal={"score": 60},
        exhaustion_signal={"risk_level": "Low", "risk_score": 10},
    )

    assert result["name"] == "continuation_target"
    assert result["target_bucket"] == "+100% speculative momentum watch"
    assert result["confidence"] == "High"


def test_indicators_return_zero_score_when_data_is_insufficient() -> None:
    candles = pd.DataFrame({"volume": [10.0], "close": [100.0], "high": [100.0]})

    volume_result = calculate_volume_spike(candles)
    momentum_result = calculate_price_momentum(candles)
    breakout_result = calculate_breakout_strength(candles)
    trend_result = calculate_trend_alignment(candles)
    volatility_result = calculate_volatility_potential(candles)

    assert volume_result["score"] == 0
    assert momentum_result["score"] == 0
    assert breakout_result["score"] == 0
    assert trend_result["score"] == 0
    assert volatility_result["score"] == 0
    assert "Not enough candle data" in volume_result["reason"]
    assert "Not enough candle data" in momentum_result["reason"]
    assert "Not enough candle data" in breakout_result["reason"]
    assert "Not enough candle data" in trend_result["reason"]
    assert "Not enough candle data" in volatility_result["reason"]
