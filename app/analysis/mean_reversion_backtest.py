"""Grid-search backtest for the mean-reversion hypothesis.

Two independent momentum backtests (app.analysis.backtest,
app.analysis.exit_model_backtest) found no edge in buying breakouts/pumps
already in progress, with or without volatility-adaptive exits. This tests
the opposite hypothesis: scan raw historical price action for statistically
over-extended coins (RSI + Bollinger Bands, app.analysis.mean_reversion) and
simulate reverting to the mean, using real historical klines end to end —
same honesty standard as the momentum backtests: real historical price
action, a conservative real-slippage estimate, and risk_manager's own
per-trade position sizing formula.

Long-the-bounce is the primary, actually-tradable-on-spot direction. Short-
the-extension is reported for comparison only and flagged everywhere as NOT
tradable on Binance spot.

Nothing here is wired into live trading — only a config this grid search
confirms wins (positive expectancy, profit factor > 1.3, survivable tail
risk) should ever get deployed to app/trading/paper_trading.py.
"""

from datetime import timedelta
from typing import Callable

import pandas as pd

from app.analysis.exit_model_backtest import _bucket_stats
from app.analysis.exit_models import ATR_PERIOD, compute_atr
from app.analysis.mean_reversion import (
    BOLLINGER_PERIOD,
    compute_bollinger_bands,
    detect_signals,
    simulate_mean_reversion_exit,
)
from app.risk.risk_manager import compute_position_size
from app.trading.paper_trading import DEFAULT_SLIPPAGE_PCT, ROUND_TRIP_FEE_PCT

HistoryFetcher = Callable[[str], list]  # symbol -> full raw kline history (one fetch)

# Not tradable on Binance spot -- see the module docstring. Reported for
# comparison only; never treat a "short" row as a candidate for deployment.
NOT_TRADABLE_DIRECTIONS = {"short"}

# A trade losing this much of the reference $1,000 portfolio in one shot is
# flagged as a tail-risk event regardless of the combo's average expectancy.
CATASTROPHIC_LOSS_PCT_OF_PORTFOLIO = 10.0


def _net_pnl_pct(gross_pnl_pct: float, slippage_pct_override: float | None = None) -> float:
    """Conservative flat slippage estimate, or a real measured spread when given.

    Unlike the momentum backtests, there's no `liquidity_label` to key off
    here — these signals come from raw historical scanning, not the
    scanner's own ticker-based classification. Defaults to the same
    worst-tier (DEFAULT_SLIPPAGE_PCT) estimate the momentum backtests fall
    back to when liquidity is unknown. Callers with a real measured
    order-book spread (e.g. the liquid-majors backtest) pass it via
    `slippage_pct_override` instead of assuming the worst tier.
    """
    slippage_pct = (
        slippage_pct_override if slippage_pct_override is not None else DEFAULT_SLIPPAGE_PCT
    )
    return gross_pnl_pct - ROUND_TRIP_FEE_PCT - slippage_pct


def backtest_symbol(
    symbol: str,
    candles: pd.DataFrame,
    direction: str,
    rsi_threshold: float,
    k_stop: float,
    max_hold_hours: int,
    slippage_pct_override: float | None = None,
) -> list[dict]:
    """Backtest one symbol's full candle history for one grid combination.

    Scans chronologically; a new signal is only considered once any
    previously opened trade for this symbol has exited (no pyramiding).
    `slippage_pct_override` lets callers substitute a real measured spread
    (e.g. for liquid majors) instead of the flat worst-tier default.
    """
    if candles is None or len(candles) < ATR_PERIOD + BOLLINGER_PERIOD:
        return []

    signals = detect_signals(candles, direction=direction, rsi_threshold=rsi_threshold)

    if not signals:
        return []

    sma_series = compute_bollinger_bands(candles)["sma"]
    open_times = candles["open_time"]
    trades = []
    next_available_index = 0

    for signal in signals:
        entry_index = signal["entry_index"]

        if entry_index < next_available_index:
            continue  # still in a trade opened by an earlier signal

        atr = compute_atr(candles.iloc[: entry_index + 1], period=ATR_PERIOD)

        if atr is None or atr <= 0:
            continue

        entry_price = signal["entry_price"]
        entry_time = signal["entry_time"]
        expires_at = entry_time + timedelta(hours=max_hold_hours)

        close = simulate_mean_reversion_exit(
            entry_price, direction, atr, k_stop, candles, sma_series, entry_index, expires_at
        )

        if close is None:
            continue

        stop_distance_pct = k_stop * atr / entry_price * 100
        position_size_usd = compute_position_size(-stop_distance_pct)
        net_pnl_pct = _net_pnl_pct(close["gross_pnl_pct"], slippage_pct_override)

        trades.append(
            {
                "symbol": symbol,
                "alerted_at": entry_time,
                "direction": direction,
                "rsi_threshold": rsi_threshold,
                "k_stop": k_stop,
                "max_hold_hours": max_hold_hours,
                "entry_price": entry_price,
                "exit_reason": close["exit_reason"],
                "gross_pnl_pct": close["gross_pnl_pct"],
                "net_pnl_pct": net_pnl_pct,
                "position_size_usd": position_size_usd,
                "net_pnl_amount": position_size_usd * (net_pnl_pct / 100),
            }
        )

        exit_time = close["exit_time"]
        next_available_index = len(candles)
        for i in range(entry_index, len(candles)):
            if open_times.iloc[i] >= exit_time:
                next_available_index = i + 1
                break

    return trades


def _tail_risk_stats(
    trades: list[dict],
    starting_equity: float = 1000.0,
    catastrophic_loss_pct: float = CATASTROPHIC_LOSS_PCT_OF_PORTFOLIO,
) -> dict:
    """Return worst-trade and loss-distribution stats for one grid combo.

    Reported regardless of whether the combo looks good on average --
    mean-reversion's real failure mode is a coin that keeps running through
    the stop, and that shows up here, not in the average.
    """
    if not trades:
        return {
            "worst_trade_net_pnl_pct": None,
            "worst_trade_net_pnl_amount": None,
            "worst_5_avg_net_pnl_pct": None,
            "catastrophic_trade_count": 0,
        }

    ordered = sorted(trades, key=lambda t: t["net_pnl_pct"])
    worst = ordered[0]
    worst_5 = ordered[: min(5, len(ordered))]
    catastrophic_threshold_usd = -(catastrophic_loss_pct / 100 * starting_equity)
    catastrophic_count = sum(
        1 for t in trades if t["net_pnl_amount"] <= catastrophic_threshold_usd
    )

    return {
        "worst_trade_net_pnl_pct": round(worst["net_pnl_pct"], 2),
        "worst_trade_net_pnl_amount": round(worst["net_pnl_amount"], 2),
        "worst_5_avg_net_pnl_pct": round(
            sum(t["net_pnl_pct"] for t in worst_5) / len(worst_5), 2
        ),
        "catastrophic_trade_count": catastrophic_count,
    }


def run_mean_reversion_grid(
    symbols: list[str],
    history_fetcher: HistoryFetcher,
    direction_grid: list[str],
    rsi_threshold_grid_by_direction: dict[str, list[float]],
    k_stop_grid: list[float],
    max_hold_hours_grid: list[int],
) -> dict:
    """Fetch each symbol's full candle history once, then grid-search every
    (direction, rsi_threshold, k_stop, max_hold_hours) combination against it.
    """
    from app.binance.client import klines_to_dataframe

    candles_by_symbol: dict[str, pd.DataFrame] = {}

    for symbol in symbols:
        raw_klines = history_fetcher(symbol)

        if not raw_klines:
            continue

        candles = klines_to_dataframe(raw_klines)

        if not candles.empty:
            candles_by_symbol[symbol] = candles

    grid_results = []

    for direction in direction_grid:
        for rsi_threshold in rsi_threshold_grid_by_direction.get(direction, []):
            for k_stop in k_stop_grid:
                for max_hold_hours in max_hold_hours_grid:
                    trades = []

                    for symbol, candles in candles_by_symbol.items():
                        trades.extend(
                            backtest_symbol(
                                symbol,
                                candles,
                                direction,
                                rsi_threshold,
                                k_stop,
                                max_hold_hours,
                            )
                        )

                    grid_results.append(
                        {
                            "direction": direction,
                            "tradable_on_spot": direction not in NOT_TRADABLE_DIRECTIONS,
                            "rsi_threshold": rsi_threshold,
                            "k_stop": k_stop,
                            "max_hold_hours": max_hold_hours,
                            **_bucket_stats(trades),
                            **_tail_risk_stats(trades),
                        }
                    )

    return {
        "symbols_scanned": len(symbols),
        "symbols_with_data": len(candles_by_symbol),
        "grid": grid_results,
    }


def format_mean_reversion_grid_report(report: dict) -> str:
    """Format a run_mean_reversion_grid() report as a human-readable table."""
    lines = [
        "Mean-Reversion Grid Search",
        "=" * 100,
        (
            f"Symbols scanned: {report['symbols_scanned']}  "
            f"(with usable candle history: {report['symbols_with_data']})"
        ),
        "",
        f"{'dir':<6}{'spot?':<7}{'rsi':>5}{'kstop':>7}{'hold(h)':>8}{'trades':>8}"
        f"{'win%':>7}{'avgNet%':>9}{'PF':>7}{'maxDD%':>8}{'exp$':>8}"
        f"{'worst%':>8}{'worst5%':>9}{'catN':>6}",
    ]

    for row in report["grid"]:
        pf = row["profit_factor"]
        pf_str = f"{pf:.2f}" if pf is not None else "n/a"
        worst_pct = row["worst_trade_net_pnl_pct"]
        worst5_pct = row["worst_5_avg_net_pnl_pct"]
        lines.append(
            f"{row['direction']:<6}{('yes' if row['tradable_on_spot'] else 'NO'):<7}"
            f"{row['rsi_threshold']:>5.0f}{row['k_stop']:>7.1f}{row['max_hold_hours']:>8}"
            f"{row['count']:>8}{row['win_rate']:>7.1f}{row['avg_net_pnl_pct']:>9.2f}"
            f"{pf_str:>7}{row['max_drawdown_pct']:>8.1f}{row['expectancy_usd']:>8.2f}"
            f"{(worst_pct if worst_pct is not None else float('nan')):>8.1f}"
            f"{(worst5_pct if worst5_pct is not None else float('nan')):>9.1f}"
            f"{row['catastrophic_trade_count']:>6}"
        )

    return "\n".join(lines)
