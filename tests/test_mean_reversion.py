"""Tests for the mean-reversion signal detection and exit simulation."""

import math
from datetime import datetime, timedelta, timezone

import pandas as pd

from app.analysis import mean_reversion as mr


def _candles(closes: list[float], highs=None, lows=None, start=None) -> pd.DataFrame:
    start = start or datetime(2026, 6, 1, tzinfo=timezone.utc)
    highs = highs or [c + 0.5 for c in closes]
    lows = lows or [c - 0.5 for c in closes]
    return pd.DataFrame(
        {
            "open_time": [start + timedelta(hours=i) for i in range(len(closes))],
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1.0] * len(closes),
        }
    )


def test_compute_rsi_is_zero_after_pure_decline() -> None:
    # 14 straight down candles -> all losses, no gains -> RSI = 0.
    closes = [100 - i for i in range(15)]
    candles = _candles(closes)

    rsi = mr.compute_rsi(candles, period=14)

    assert rsi.iloc[-1] == pytest_approx(0.0)


def test_compute_rsi_is_high_after_pure_rally() -> None:
    closes = [100 + i for i in range(15)]
    candles = _candles(closes)

    rsi = mr.compute_rsi(candles, period=14)

    assert rsi.iloc[-1] > 95


def test_compute_bollinger_bands_matches_manual_calculation() -> None:
    closes = [10.0, 10.0, 13.0]
    candles = _candles(closes)

    bands = mr.compute_bollinger_bands(candles, period=3, num_std=2.0)

    expected_mean = 11.0
    expected_std = math.sqrt(((10 - 11) ** 2 + (10 - 11) ** 2 + (13 - 11) ** 2) / 2)  # ddof=1
    assert bands["sma"].iloc[-1] == pytest_approx(expected_mean)
    assert bands["upper"].iloc[-1] == pytest_approx(expected_mean + 2 * expected_std)
    assert bands["lower"].iloc[-1] == pytest_approx(expected_mean - 2 * expected_std)


def pytest_approx(value, rel=1e-6):
    import pytest

    return pytest.approx(value, rel=rel)


def test_detect_signals_long_requires_confirmation_candle() -> None:
    # 13 flat candles (tight bands), then a sharp plunge (RSI -> 0, price well
    # under the lower band), then a bounce that confirms.
    flat = [100.0] * 13
    candles = _candles(flat + [90.0, 85.0, 90.0])

    signals = mr.detect_signals(candles, direction="long", rsi_threshold=25, bb_period=14)

    assert len(signals) == 1
    signal = signals[0]
    assert signal["direction"] == "long"
    assert signal["entry_price"] == 90.0
    # Signal candle is the plunge low (85), confirmed by the bounce back to 90.
    assert candles["close"].iloc[signal["signal_index"]] == 85.0


def test_detect_signals_long_finds_nothing_without_oversold_condition() -> None:
    candles = _candles([100.0] * 20)  # flat -- never triggers RSI/band conditions

    signals = mr.detect_signals(candles, direction="long", rsi_threshold=25)

    assert signals == []


def test_detect_signals_short_mirrors_long() -> None:
    flat = [100.0] * 13
    candles = _candles(flat + [110.0, 115.0, 110.0])

    signals = mr.detect_signals(candles, direction="short", rsi_threshold=75, bb_period=14)

    assert len(signals) == 1
    assert signals[0]["direction"] == "short"
    assert signals[0]["entry_price"] == 110.0


def test_simulate_mean_reversion_exit_long_hits_target() -> None:
    entry_price = 90.0
    atr = 2.0  # stop = 90 - 1.5*2 = 87
    candles = _candles([90, 95, 100])
    sma_series = pd.Series([95.0, 95.0, 95.0])  # target = 95
    expires_at = candles["open_time"].iloc[-1] + timedelta(hours=1)

    result = mr.simulate_mean_reversion_exit(
        entry_price, "long", atr, k_stop=1.5, candles=candles,
        sma_series=sma_series, entry_index=0, expires_at=expires_at,
    )

    assert result["exit_reason"] == "mean_reversion_target"
    assert result["exit_price"] == 95.0
    assert result["gross_pnl_pct"] == pytest_approx((95 - 90) / 90 * 100)


def test_simulate_mean_reversion_exit_long_stop_fills_at_worse_of_stop_or_low() -> None:
    entry_price = 90.0
    atr = 2.0  # stop = 90 - 1.5*2 = 87
    # A hard gap-down candle: low=80, way below the computed stop of 87.
    candles = _candles([90, 80], highs=[91, 81], lows=[89, 80])
    sma_series = pd.Series([200.0, 200.0])  # target far away, never hit
    expires_at = candles["open_time"].iloc[-1] + timedelta(hours=1)

    result = mr.simulate_mean_reversion_exit(
        entry_price, "long", atr, k_stop=1.5, candles=candles,
        sma_series=sma_series, entry_index=0, expires_at=expires_at,
    )

    assert result["exit_reason"] == "stop_loss"
    # Filled at the candle's low (80), not the nominal stop price (87) --
    # the tail-risk-realistic fill.
    assert result["exit_price"] == 80.0
    assert result["gross_pnl_pct"] == pytest_approx((80 - 90) / 90 * 100)


def test_simulate_mean_reversion_exit_expires_at_time_stop() -> None:
    entry_price = 90.0
    atr = 2.0
    candles = _candles([90, 91, 92])  # never touches stop(87) or target(200)
    sma_series = pd.Series([200.0, 200.0, 200.0])
    expires_at = candles["open_time"].iloc[-1]

    result = mr.simulate_mean_reversion_exit(
        entry_price, "long", atr, k_stop=1.5, candles=candles,
        sma_series=sma_series, entry_index=0, expires_at=expires_at,
    )

    assert result["exit_reason"] == "time_stop_expired"
    assert result["exit_price"] == 92.0


def test_simulate_mean_reversion_exit_short_profits_when_price_falls() -> None:
    entry_price = 100.0
    atr = 2.0  # stop = 100 + 1.5*2 = 103
    candles = _candles([100, 95, 90])
    sma_series = pd.Series([90.0, 90.0, 90.0])  # target = 90
    expires_at = candles["open_time"].iloc[-1] + timedelta(hours=1)

    result = mr.simulate_mean_reversion_exit(
        entry_price, "short", atr, k_stop=1.5, candles=candles,
        sma_series=sma_series, entry_index=0, expires_at=expires_at,
    )

    assert result["exit_reason"] == "mean_reversion_target"
    assert result["gross_pnl_pct"] == pytest_approx((100 - 90) / 100 * 100)


def test_simulate_mean_reversion_exit_returns_none_for_invalid_atr() -> None:
    candles = _candles([90, 91])
    sma_series = pd.Series([95.0, 95.0])
    expires_at = candles["open_time"].iloc[-1] + timedelta(hours=1)

    assert mr.simulate_mean_reversion_exit(
        90.0, "long", 0, k_stop=1.5, candles=candles,
        sma_series=sma_series, entry_index=0, expires_at=expires_at,
    ) is None
