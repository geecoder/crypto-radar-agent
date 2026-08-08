"""Volatility-adaptive exit models — ATR-based stops/targets and trailing exits.

The current live paper-trading engine (app/trading/paper_trading.py) uses
fixed-percentage stop-loss/take-profit/trailing levels. The 60-day backtest
(app/analysis/backtest.py) showed that model has no positive edge: 65% of
trades hit a fixed -10% stop, only 11.6% reached the fixed take-profit, and
the win rate (37.7%) doesn't clear the loss/win ratio.

This module implements two alternative, volatility-sized exit models, pure
functions operating on a candle DataFrame (see
app.binance.client.klines_to_dataframe) so they can be grid-searched by
app.analysis.exit_model_backtest BEFORE any of this touches live trading.
Nothing here is wired into app/trading/paper_trading.py — only a config that
the grid search confirms actually wins should ever get deployed.

- `simulate_atr_fixed_target_exit` (Block 1): stop = entry - k_stop*ATR,
  target = entry + k_target*ATR. Sizes both levels to the coin's own recent
  volatility instead of a one-size-fits-all percentage.
- `simulate_atr_trailing_exit` (Block 2): same ATR stop, but once price is
  up 1 ATR the stop trails k_trail*ATR behind the peak instead of exiting at
  a fixed target — lets a HEIUSDT-style +52% run instead of capping at +12.5%.
"""

from datetime import datetime
from typing import Any

import pandas as pd

# ATR period and timeframe: 14 periods of the same 15m candles the live
# scanner and exit monitoring already use, so this doesn't introduce a
# second timeframe convention into the codebase. 14x15m = 3.5h of lookback.
ATR_PERIOD = 14
# How many ATRs of profit unlock the trailing stop in the Block 2 model.
TRAILING_ACTIVATION_ATR_MULTIPLE = 1.0


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def compute_true_range_series(candles: pd.DataFrame) -> pd.Series:
    """Return the True Range for each candle (needs the prior candle's close)."""
    prev_close = candles["close"].astype(float).shift(1)
    high = candles["high"].astype(float)
    low = candles["low"].astype(float)

    high_low = high - low
    high_prev_close = (high - prev_close).abs()
    low_prev_close = (low - prev_close).abs()

    return pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)


def compute_atr(candles: pd.DataFrame, period: int = ATR_PERIOD) -> float | None:
    """Return the simple-average ATR over the last `period` candles.

    A plain average of true ranges (not Wilder's exponential smoothing) —
    simpler and auditable, at the cost of being slightly more reactive to
    a single large candle. Returns None without enough candle history.
    """
    if candles is None or candles.empty:
        return None

    true_range = compute_true_range_series(candles)
    valid_true_range = true_range.dropna()

    if len(valid_true_range) < period:
        return None

    return float(valid_true_range.iloc[-period:].mean())


def _row_high_low(row) -> tuple[float | None, float | None]:
    return _safe_float(row.get("high")), _safe_float(row.get("low"))


def _row_time(row) -> datetime | None:
    value = row.get("open_time")
    if value is None:
        return None
    try:
        return pd.to_datetime(value, utc=True)
    except (TypeError, ValueError):
        return None


def _exit(exit_reason: str, entry_price: float, exit_price: float, exit_time) -> dict:
    gross_pnl_pct = (exit_price - entry_price) / entry_price * 100
    return {
        "exit_reason": exit_reason,
        "exit_price": exit_price,
        "exit_time": exit_time,
        "gross_pnl_pct": gross_pnl_pct,
    }


def simulate_atr_fixed_target_exit(
    entry_price: float,
    atr: float,
    k_stop: float,
    k_target: float,
    forward_candles: pd.DataFrame,
    expires_at: datetime,
) -> dict | None:
    """BLOCK 1 model: stop = entry - k_stop*ATR, target = entry + k_target*ATR.

    Walks `forward_candles` (oldest first) and exits on whichever of
    target/stop/max-hold-expiry is hit first. Optimistic same-candle
    ordering (target checked before stop), matching the convention already
    used by evaluate_open_paper_trade for the live fixed-percentage model.
    Returns None if the trade never resolves within `forward_candles`.
    """
    if entry_price <= 0 or atr is None or atr <= 0:
        return None

    stop_price = entry_price - k_stop * atr
    target_price = entry_price + k_target * atr
    last_row = None

    for _, candle in forward_candles.iterrows():
        candle_time = _row_time(candle)

        if candle_time is not None and candle_time > expires_at:
            break

        last_row = candle
        high, low = _row_high_low(candle)

        if high is not None and high >= target_price:
            return _exit("take_profit", entry_price, target_price, candle_time)

        if low is not None and low <= stop_price:
            return _exit("stop_loss", entry_price, stop_price, candle_time)

    if last_row is None:
        return None

    latest_close = _safe_float(last_row.get("close"))
    if latest_close is None:
        return None

    return _exit("max_hold_expired", entry_price, latest_close, _row_time(last_row))


def simulate_atr_trailing_exit(
    entry_price: float,
    atr: float,
    k_stop: float,
    k_trail: float,
    forward_candles: pd.DataFrame,
    expires_at: datetime,
    activation_atr_multiple: float = TRAILING_ACTIVATION_ATR_MULTIPLE,
) -> dict | None:
    """BLOCK 2 model: ATR stop, no fixed target — trails once in profit.

    Stop starts at entry - k_stop*ATR. Once the running peak is
    `activation_atr_multiple` ATRs above entry, the stop trails at
    k_trail*ATR below the peak instead of staying fixed. Lets a big mover
    keep running instead of capping at a fixed take-profit.
    Returns None if the trade never resolves within `forward_candles`.
    """
    if entry_price <= 0 or atr is None or atr <= 0:
        return None

    initial_stop = entry_price - k_stop * atr
    activation_price = entry_price + activation_atr_multiple * atr
    current_stop = initial_stop
    peak = entry_price
    last_row = None

    for _, candle in forward_candles.iterrows():
        candle_time = _row_time(candle)

        if candle_time is not None and candle_time > expires_at:
            break

        last_row = candle
        high, low = _row_high_low(candle)

        if high is not None and high > peak:
            peak = high

            if peak >= activation_price:
                trailing_stop = peak - k_trail * atr
                if trailing_stop > current_stop:
                    current_stop = trailing_stop

        if low is not None and low <= current_stop:
            reason = "trailing_stop" if current_stop > initial_stop else "stop_loss"
            return _exit(reason, entry_price, current_stop, candle_time)

    if last_row is None:
        return None

    latest_close = _safe_float(last_row.get("close"))
    if latest_close is None:
        return None

    return _exit("max_hold_expired", entry_price, latest_close, _row_time(last_row))
