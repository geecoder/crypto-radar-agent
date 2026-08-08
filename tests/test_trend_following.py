"""Tests for trend-following entry signals (MA crossover, Donchian breakout)."""

from datetime import datetime, timedelta, timezone

import pandas as pd

from app.analysis import trend_following as tf


def _candles(closes: list[float], start=None) -> pd.DataFrame:
    start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    return pd.DataFrame(
        {
            "open_time": [start + timedelta(hours=i) for i in range(len(closes))],
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1.0] * len(closes),
        }
    )


def test_ma_crossover_detects_golden_cross() -> None:
    # Decline (fast EMA drags below slow), then a sharp rally forces a
    # bullish crossover.
    closes = [100] * 10 + [90] * 10 + [95, 100, 105, 110, 115, 120]
    candles = _candles(closes)

    signals = tf.detect_ma_crossover_signals(candles, fast_period=3, slow_period=8)

    assert len(signals) == 1
    assert signals[0]["direction"] == "long"
    assert signals[0]["strategy"] == "ma_crossover"
    assert signals[0]["entry_price"] == 95.0


def test_ma_crossover_finds_nothing_in_a_flat_series() -> None:
    candles = _candles([100.0] * 30)

    assert tf.detect_ma_crossover_signals(candles, fast_period=5, slow_period=20) == []


def test_donchian_breakout_detects_close_above_prior_high() -> None:
    closes = [100.0] * 20 + [110.0]
    candles = _candles(closes)

    signals = tf.detect_donchian_breakout_signals(candles, breakout_period=20)

    assert len(signals) == 1
    assert signals[0]["direction"] == "long"
    assert signals[0]["strategy"] == "donchian_breakout"
    assert signals[0]["entry_price"] == 110.0
    assert signals[0]["entry_index"] == 20


def test_donchian_breakout_has_no_lookahead_from_its_own_high() -> None:
    # A single-candle spike shouldn't trigger against itself -- only a CLOSE
    # above the PRIOR period's high counts.
    closes = [100.0] * 20 + [100.5]  # closes barely above the flat 100 high, no real breakout
    candles = _candles(closes)
    # Give the spike candle an enormous high so its OWN high would trivially
    # "break out" if the code incorrectly included it in the rolling window.
    candles.loc[20, "high"] = 500.0

    signals = tf.detect_donchian_breakout_signals(candles, breakout_period=20)

    assert signals == []


def test_donchian_breakout_finds_nothing_without_enough_history() -> None:
    candles = _candles([100.0] * 10)

    assert tf.detect_donchian_breakout_signals(candles, breakout_period=20) == []
