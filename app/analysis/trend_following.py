"""Trend-following entry signals — the classic approach for liquid majors.

Three strategy families were falsified on the alt universe (momentum
fixed-exit, momentum ATR-exit, mean-reversion both directions) — all
net-negative after real costs, with a consistent pattern: cost drag on
illiquid small/mid-cap alts destroys any edge before it can show up. This
module implements the one untested cheap hypothesis: classic trend-following
on liquid majors (BTC, ETH, SOL, ...), where spread/slippage is structurally
near-zero and trends are historically cleaner than on alts.

Two well-established, simple entry rules — deliberately not novel, since the
point is testing whether well-known technicals have any edge here at all
before inventing anything new:

- `detect_ma_crossover_signals`: golden-cross entry (fast EMA crosses above
  slow EMA) — classic trend-following, long-only (spot can't easily short).
- `detect_donchian_breakout_signals`: enter when price closes above the
  highest high of the prior N periods — the Turtle Trading entry rule.

Both are long-only, no-lookahead (the breakout/crossover level is always
computed from candles strictly before the entry candle), and pair with the
existing ATR trailing-stop exit (app.analysis.exit_models.simulate_atr_trailing_exit)
in app.analysis.liquid_majors_backtest — trend-following's whole premise is
letting a winner run, which is exactly what that exit already does.

Nothing here is wired into live trading.
"""

import pandas as pd


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    """Return the exponential moving average of `series`."""
    return series.astype(float).ewm(span=period, adjust=False).mean()


def detect_ma_crossover_signals(
    candles: pd.DataFrame,
    fast_period: int,
    slow_period: int,
) -> list[dict]:
    """Return a long entry signal at every bullish EMA crossover.

    Entry is priced at the crossover candle's own close — by the time that
    candle closes, both EMAs are known, matching the entry-pricing
    convention already used throughout this analysis suite.
    """
    close = candles["close"].astype(float)
    fast = compute_ema(close, fast_period)
    slow = compute_ema(close, slow_period)
    open_time = candles["open_time"]

    signals = []

    for i in range(max(1, slow_period), len(candles)):
        crossed_up = fast.iloc[i - 1] <= slow.iloc[i - 1] and fast.iloc[i] > slow.iloc[i]

        if crossed_up:
            signals.append(
                {
                    "entry_index": i,
                    "entry_time": open_time.iloc[i],
                    "entry_price": float(close.iloc[i]),
                    "direction": "long",
                    "strategy": "ma_crossover",
                }
            )

    return signals


def detect_donchian_breakout_signals(
    candles: pd.DataFrame,
    breakout_period: int,
) -> list[dict]:
    """Return a long entry signal whenever price closes above the highest
    high of the prior `breakout_period` candles (the Turtle entry rule).

    The breakout level is read from the PRIOR candle's rolling high (i.e.
    excludes the entry candle's own high), so there is no lookahead — the
    level was fully known before the entry candle closed.
    """
    high = candles["high"].astype(float)
    close = candles["close"].astype(float)
    open_time = candles["open_time"]
    rolling_high = high.rolling(window=breakout_period).max()

    signals = []

    for i in range(breakout_period, len(candles)):
        prior_high = rolling_high.iloc[i - 1]

        if pd.isna(prior_high):
            continue

        if close.iloc[i] > prior_high:
            signals.append(
                {
                    "entry_index": i,
                    "entry_time": open_time.iloc[i],
                    "entry_price": float(close.iloc[i]),
                    "direction": "long",
                    "strategy": "donchian_breakout",
                }
            )

    return signals
