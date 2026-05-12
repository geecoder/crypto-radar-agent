"""Tests for basic signal indicators."""

import pandas as pd
import pytest

from app.indicators.breakout import calculate_breakout_strength
from app.indicators.momentum import calculate_price_momentum
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
