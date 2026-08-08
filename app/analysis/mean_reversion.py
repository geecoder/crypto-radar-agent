"""Mean-reversion entry/exit signals — the opposite hypothesis to momentum-chasing.

Two independent backtests (app.analysis.backtest, app.analysis.exit_model_backtest)
confirmed the momentum entry (buy breakouts/pumps already in progress) has no edge
on 60 days of real data, with or without volatility-adaptive exits. This module
tests the opposite: enter when a coin is statistically OVER-extended (RSI + Bollinger
Bands) and a reversal confirms, targeting a snap back to the mean rather than a
continuation.

Long-the-bounce (buy oversold) is the primary, actually-tradable-on-spot direction.
Short-the-extension is implemented too, purely for informational comparison — it is
NOT tradable on Binance spot and is clearly labeled as such everywhere it appears.

Pure, deterministic signal-detection and exit-simulation functions here; the
per-symbol historical scan and grid search live in
app.analysis.mean_reversion_backtest. Nothing in this module is wired into live
trading — see that module's docstring for the same rule the momentum backtests
followed: backtest first, deploy only what wins.
"""

from typing import Any

import pandas as pd

from app.analysis.exit_models import compute_true_range_series

RSI_PERIOD = 14
BOLLINGER_PERIOD = 20
BOLLINGER_NUM_STD = 2.0


def compute_rsi(candles: pd.DataFrame, period: int = RSI_PERIOD) -> pd.Series:
    """Return Wilder's RSI for each candle (NaN until `period` candles of history)."""
    close = candles["close"].astype(float)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))

    return rsi.where(avg_loss != 0, 100.0)


def compute_bollinger_bands(
    candles: pd.DataFrame,
    period: int = BOLLINGER_PERIOD,
    num_std: float = BOLLINGER_NUM_STD,
) -> pd.DataFrame:
    """Return a DataFrame with sma/upper/lower Bollinger Band columns."""
    close = candles["close"].astype(float)
    sma = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()

    return pd.DataFrame(
        {
            "sma": sma,
            "upper": sma + num_std * std,
            "lower": sma - num_std * std,
        }
    )


def detect_signals(
    candles: pd.DataFrame,
    direction: str,
    rsi_threshold: float,
    rsi_period: int = RSI_PERIOD,
    bb_period: int = BOLLINGER_PERIOD,
    bb_num_std: float = BOLLINGER_NUM_STD,
) -> list[dict]:
    """Return every confirmed mean-reversion signal in `candles`.

    `direction` is "long" (oversold bounce: RSI < rsi_threshold, close below the
    lower Bollinger Band, confirmed by the next candle closing higher) or "short"
    (overbought fade: RSI > rsi_threshold, close above the upper band, confirmed
    by the next candle closing lower — informational only, not tradable on spot).

    No lookahead: the signal candle must fully close before its indicators are
    read, and entry is priced at the confirmation candle's close, one candle
    after the signal was visible.
    """
    if direction not in {"long", "short"}:
        raise ValueError(f"Unknown direction: {direction!r}")

    rsi = compute_rsi(candles, period=rsi_period)
    bands = compute_bollinger_bands(candles, period=bb_period, num_std=bb_num_std)
    close = candles["close"].astype(float)
    open_time = candles["open_time"]

    signals = []
    n = len(candles)

    for i in range(n - 1):
        if pd.isna(rsi.iloc[i]) or pd.isna(bands["lower"].iloc[i]):
            continue

        signal_close = close.iloc[i]
        confirm_close = close.iloc[i + 1]

        if direction == "long":
            triggered = rsi.iloc[i] < rsi_threshold and signal_close < bands["lower"].iloc[i]
            confirmed = confirm_close > signal_close
        else:
            triggered = rsi.iloc[i] > rsi_threshold and signal_close > bands["upper"].iloc[i]
            confirmed = confirm_close < signal_close

        if triggered and confirmed:
            signals.append(
                {
                    "signal_index": i,
                    "entry_index": i + 1,
                    "entry_time": open_time.iloc[i + 1],
                    "entry_price": float(confirm_close),
                    "direction": direction,
                }
            )

    return signals


def _row_high_low(row) -> tuple[float | None, float | None]:
    try:
        return float(row.get("high")), float(row.get("low"))
    except (TypeError, ValueError):
        return None, None


def simulate_mean_reversion_exit(
    entry_price: float,
    direction: str,
    atr: float,
    k_stop: float,
    candles: pd.DataFrame,
    sma_series: pd.Series,
    entry_index: int,
    expires_at,
) -> dict | None:
    """Simulate one mean-reversion trade's exit.

    Target is the CURRENT (evolving) moving-average midline, not a static level
    from entry time — the "mean" being reverted to keeps moving. Stop is
    entry -/+ k_stop*ATR. A stop-loss fill uses the worse of the computed stop
    price or the candle's actual high/low, so a gap-through move isn't
    optimistically priced at the stop level — mean-reversion's real failure
    mode is a coin that keeps running through the stop, and this should show
    up as a worse fill, not a clean one.

    Returns None if the trade never resolves within `expires_at`.
    """
    if entry_price <= 0 or atr is None or atr <= 0:
        return None

    if direction == "long":
        stop_price = entry_price - k_stop * atr
    else:
        stop_price = entry_price + k_stop * atr

    last_row = None
    last_index = None

    for i in range(entry_index, len(candles)):
        row = candles.iloc[i]
        candle_time = row.get("open_time")

        if candle_time is not None and candle_time > expires_at:
            break

        last_row = row
        last_index = i
        high, low = _row_high_low(row)
        target_price = sma_series.iloc[i] if i < len(sma_series) else None

        if direction == "long":
            if target_price is not None and not pd.isna(target_price) and high is not None and high >= target_price:
                return _exit("mean_reversion_target", entry_price, float(target_price), candle_time, direction)

            if low is not None and low <= stop_price:
                fill_price = min(stop_price, low)
                return _exit("stop_loss", entry_price, fill_price, candle_time, direction)
        else:
            if target_price is not None and not pd.isna(target_price) and low is not None and low <= target_price:
                return _exit("mean_reversion_target", entry_price, float(target_price), candle_time, direction)

            if high is not None and high >= stop_price:
                fill_price = max(stop_price, high)
                return _exit("stop_loss", entry_price, fill_price, candle_time, direction)

    if last_row is None:
        return None

    try:
        latest_close = float(last_row.get("close"))
    except (TypeError, ValueError):
        return None

    return _exit(
        "time_stop_expired", entry_price, latest_close, last_row.get("open_time"), direction
    )


def _exit(
    exit_reason: str, entry_price: float, exit_price: float, exit_time, direction: str
) -> dict:
    """Build an exit result. `direction` determines the P&L sign convention:
    long profits when price rises, short profits when price falls."""
    if direction == "long":
        gross_pnl_pct = (exit_price - entry_price) / entry_price * 100
    else:
        gross_pnl_pct = (entry_price - exit_price) / entry_price * 100

    return {
        "exit_reason": exit_reason,
        "exit_price": exit_price,
        "exit_time": exit_time,
        "gross_pnl_pct": gross_pnl_pct,
    }
