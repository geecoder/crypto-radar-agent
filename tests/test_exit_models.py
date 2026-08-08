"""Tests for the volatility-adaptive (ATR-based) exit models."""

from datetime import datetime, timedelta, timezone

import pandas as pd

from app.analysis import exit_models


def _candles(rows: list[dict], start: datetime | None = None) -> pd.DataFrame:
    """Build a candle DataFrame; each row advances open_time by 15 minutes."""
    start = start or datetime(2026, 6, 1, tzinfo=timezone.utc)
    return pd.DataFrame(
        [
            {
                "open_time": start + timedelta(minutes=15 * i),
                "open": row.get("open", row["close"]),
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row.get("volume", 1.0),
            }
            for i, row in enumerate(rows)
        ]
    )


def test_compute_atr_averages_true_range_over_period() -> None:
    # Flat series: each candle's true range is exactly high-low=2.0 (no gap
    # component since close never moves) -> ATR(3) over the last 3 = 2.0.
    candles = _candles(
        [
            {"high": 101, "low": 99, "close": 100},
            {"high": 101, "low": 99, "close": 100},
            {"high": 101, "low": 99, "close": 100},
            {"high": 101, "low": 99, "close": 100},
        ]
    )

    atr = exit_models.compute_atr(candles, period=3)

    assert atr == 2.0


def test_compute_atr_returns_none_without_enough_history() -> None:
    candles = _candles([{"high": 101, "low": 99, "close": 100}])

    assert exit_models.compute_atr(candles, period=14) is None


def test_compute_atr_returns_none_for_empty_dataframe() -> None:
    assert exit_models.compute_atr(pd.DataFrame(), period=14) is None


def test_fixed_target_exit_hits_target_first() -> None:
    entry_price = 100.0
    atr = 2.0  # stop=100-1.5*2=97, target=100+3*2=106
    candles = _candles(
        [
            {"high": 101, "low": 98, "close": 100},
            {"high": 106.5, "low": 99, "close": 106},
        ]
    )
    expires_at = candles["open_time"].iloc[-1] + timedelta(hours=1)

    result = exit_models.simulate_atr_fixed_target_exit(
        entry_price, atr, k_stop=1.5, k_target=3.0, forward_candles=candles, expires_at=expires_at
    )

    assert result["exit_reason"] == "take_profit"
    assert result["exit_price"] == 106.0
    assert result["gross_pnl_pct"] == 6.0


def test_fixed_target_exit_hits_stop_first() -> None:
    entry_price = 100.0
    atr = 2.0  # stop=97, target=106
    candles = _candles(
        [
            {"high": 101, "low": 96.5, "close": 97},
        ]
    )
    expires_at = candles["open_time"].iloc[-1] + timedelta(hours=1)

    result = exit_models.simulate_atr_fixed_target_exit(
        entry_price, atr, k_stop=1.5, k_target=3.0, forward_candles=candles, expires_at=expires_at
    )

    assert result["exit_reason"] == "stop_loss"
    assert result["exit_price"] == 97.0
    assert result["gross_pnl_pct"] == -3.0


def test_fixed_target_exit_expires_at_max_hold() -> None:
    entry_price = 100.0
    atr = 2.0  # stop=97, target=106 -- neither touched
    candles = _candles(
        [
            {"high": 101, "low": 99, "close": 100.5},
            {"high": 102, "low": 100, "close": 101},
        ]
    )
    expires_at = candles["open_time"].iloc[-1]

    result = exit_models.simulate_atr_fixed_target_exit(
        entry_price, atr, k_stop=1.5, k_target=3.0, forward_candles=candles, expires_at=expires_at
    )

    assert result["exit_reason"] == "max_hold_expired"
    assert result["exit_price"] == 101.0


def test_fixed_target_exit_returns_none_when_nothing_resolves() -> None:
    entry_price = 100.0
    atr = 2.0
    candles = _candles([{"high": 101, "low": 99, "close": 100}])
    # Expiry before the only candle -> loop breaks immediately, no last_row set.
    expires_at = candles["open_time"].iloc[0] - timedelta(minutes=1)

    result = exit_models.simulate_atr_fixed_target_exit(
        entry_price, atr, k_stop=1.5, k_target=3.0, forward_candles=candles, expires_at=expires_at
    )

    assert result is None


def test_fixed_target_exit_returns_none_for_invalid_atr() -> None:
    candles = _candles([{"high": 101, "low": 99, "close": 100}])
    expires_at = candles["open_time"].iloc[-1] + timedelta(hours=1)

    assert exit_models.simulate_atr_fixed_target_exit(
        100.0, 0, k_stop=1.5, k_target=3.0, forward_candles=candles, expires_at=expires_at
    ) is None
    assert exit_models.simulate_atr_fixed_target_exit(
        100.0, None, k_stop=1.5, k_target=3.0, forward_candles=candles, expires_at=expires_at
    ) is None


def test_trailing_exit_locks_in_profit_above_initial_stop() -> None:
    entry_price = 100.0
    # initial stop=100-1.5*2=97, activation at 100+1*2=102, trail 4*ATR=8 below peak.
    atr = 2.0
    candles = _candles(
        [
            # peak->103 (>=activation) -> trailing_stop=103-8=95, stays at 97 (95<97)
            {"high": 103, "low": 100, "close": 102},
            # peak->110 -> trailing_stop=110-8=102, updates (102>97)
            {"high": 110, "low": 105, "close": 108},
            # peak->111 -> trailing_stop=111-8=103, updates (103>102); low=101<=103 -> exit
            {"high": 111, "low": 101, "close": 103},
        ]
    )
    expires_at = candles["open_time"].iloc[-1] + timedelta(hours=1)

    result = exit_models.simulate_atr_trailing_exit(
        entry_price, atr, k_stop=1.5, k_trail=4.0, forward_candles=candles, expires_at=expires_at
    )

    assert result["exit_reason"] == "trailing_stop"
    assert result["exit_price"] == 103.0
    assert result["gross_pnl_pct"] == 3.0  # locked in a gain, not a loss


def test_trailing_exit_hits_initial_stop_before_activation() -> None:
    entry_price = 100.0
    atr = 2.0  # initial stop=97, activation at 102 -- never reached
    candles = _candles(
        [
            {"high": 101, "low": 96.5, "close": 97},
        ]
    )
    expires_at = candles["open_time"].iloc[-1] + timedelta(hours=1)

    result = exit_models.simulate_atr_trailing_exit(
        entry_price, atr, k_stop=1.5, k_trail=4.0, forward_candles=candles, expires_at=expires_at
    )

    assert result["exit_reason"] == "stop_loss"
    assert result["exit_price"] == 97.0


def test_trailing_exit_expires_at_max_hold_while_running() -> None:
    entry_price = 100.0
    atr = 2.0
    candles = _candles(
        [
            {"high": 103, "low": 100, "close": 102},
            {"high": 108, "low": 104, "close": 107},
        ]
    )
    expires_at = candles["open_time"].iloc[-1]

    result = exit_models.simulate_atr_trailing_exit(
        entry_price, atr, k_stop=1.5, k_trail=4.0, forward_candles=candles, expires_at=expires_at
    )

    assert result["exit_reason"] == "max_hold_expired"
    assert result["exit_price"] == 107.0
