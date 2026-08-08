"""Grid-search backtest: does an ATR-based exit model beat the fixed-% one?

Reuses the Block 1-4 eligibility, classification, and conviction-sizing
logic from app.analysis.backtest (that 60-day backtest confirmed the
architecture is sound — HEIUSDT-style movers now clear eligibility; the
problem is the fixed -stop/+target exit model itself) and swaps ONLY the
exit simulation for the two volatility-adaptive models in
app.analysis.exit_models. Each alert's candles are fetched once (ATR
lookback + full forward hold window) and that single fetch is reused across
every grid combination — no re-fetching per parameter combo.

Nothing here is wired into live trading. Only a config this grid search
confirms wins (positive expectancy, profit factor > 1.3, acceptable
drawdown) should ever get deployed to app/trading/paper_trading.py.
"""

from datetime import timedelta
from typing import Any, Callable

import pandas as pd

from app.analysis.backtest import (
    classify_under_new_rules,
    estimate_conviction_position_size,
    evaluate_new_eligibility,
)
from app.analysis.exit_models import (
    ATR_PERIOD,
    compute_atr,
    simulate_atr_fixed_target_exit,
    simulate_atr_trailing_exit,
)
from app.trading.paper_trading import (
    DEFAULT_SLIPPAGE_PCT,
    ROUND_TRIP_FEE_PCT,
    SLIPPAGE_PCT_BY_LIQUIDITY,
    _score_based_max_hold_hours,
    evaluate_open_paper_trade,
)

CANDLE_INTERVAL = "15m"
CANDLES_PER_HOUR = 4

KlinesFetcher = Callable[[str, int, int], list]


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _net_pnl_pct_flat(gross_pnl_pct: float, liquidity_label: Any) -> float:
    """Same flat liquidity-tiered slippage estimate app.analysis.backtest uses
    — no historical order-book data exists to measure real slippage."""
    slippage_pct = SLIPPAGE_PCT_BY_LIQUIDITY.get(
        str(liquidity_label or "").strip().lower(), DEFAULT_SLIPPAGE_PCT
    )
    return gross_pnl_pct - ROUND_TRIP_FEE_PCT - slippage_pct


def prepare_candidate(alert_row: dict, klines_fetcher: KlinesFetcher) -> dict | None:
    """Classify, gate, size, and fetch candles for one historical alert.

    Returns None for anything the Block 1-3 eligibility already rejects, or
    where there isn't enough candle history to compute ATR — same
    fail-closed convention as the rest of this analysis suite. Otherwise
    returns a dict with everything every grid combo needs, so candles are
    fetched exactly once per alert regardless of grid size.
    """
    new_alert_type = classify_under_new_rules(alert_row)
    eligible, _reason, strategy = evaluate_new_eligibility(alert_row, new_alert_type)

    if not eligible:
        return None

    entry_price = _safe_float(alert_row.get("latest_close"), default=None)
    alerted_at = alert_row.get("alerted_at")

    if entry_price is None or entry_price <= 0 or alerted_at is None:
        return None

    position_size_usd, _slippage = estimate_conviction_position_size(alert_row, strategy)
    max_hold_hours = _score_based_max_hold_hours(
        alert_row.get("opportunity_score"), strategy
    )

    lookback_start = alerted_at - timedelta(minutes=15 * (ATR_PERIOD + 1))
    start_time_ms = int(lookback_start.timestamp() * 1000)
    num_candles = (ATR_PERIOD + 1) + max_hold_hours * CANDLES_PER_HOUR + 4

    klines = klines_fetcher(alert_row.get("symbol"), start_time_ms, num_candles)

    if not klines:
        return None

    from app.binance.client import klines_to_dataframe

    candles = klines_to_dataframe(klines)

    if candles.empty:
        return None

    candle_times = pd.to_datetime(candles["open_time"], utc=True, errors="coerce")
    pre_alert = candles[candle_times < alerted_at]
    post_alert = candles[candle_times >= alerted_at].sort_values("open_time")

    if post_alert.empty:
        return None

    atr = compute_atr(pre_alert, period=ATR_PERIOD)

    if atr is None or atr <= 0:
        return None

    expires_at = alerted_at + timedelta(hours=max_hold_hours)

    return {
        "symbol": alert_row.get("symbol"),
        "alerted_at": alerted_at,
        "entry_price": entry_price,
        "atr": atr,
        "post_alert_candles": post_alert,
        "expires_at": expires_at,
        "liquidity_label": alert_row.get("liquidity_label"),
        "position_size_usd": position_size_usd,
        "strategy": strategy,
        "new_alert_type": new_alert_type,
    }


def _trade_result(candidate: dict, close: dict | None) -> dict | None:
    """Turn a raw exit-model close dict into a net-P&L trade record."""
    if close is None:
        return None

    net_pnl_pct = _net_pnl_pct_flat(close["gross_pnl_pct"], candidate["liquidity_label"])
    position_size_usd = candidate["position_size_usd"]

    return {
        "symbol": candidate["symbol"],
        "alerted_at": candidate["alerted_at"],
        "exit_reason": close["exit_reason"],
        "gross_pnl_pct": close["gross_pnl_pct"],
        "net_pnl_pct": net_pnl_pct,
        "net_pnl_amount": position_size_usd * (net_pnl_pct / 100),
        "position_size_usd": position_size_usd,
    }


def simulate_baseline_fixed_pct(candidate: dict) -> dict | None:
    """Run the CURRENT live exit model (fixed %, from evaluate_open_paper_trade)
    against this candidate's own candles, for an apples-to-apples baseline
    row in the grid report — same universe of trades as every ATR combo."""
    strategy = candidate["strategy"]
    trade = {
        "entry_price": candidate["entry_price"],
        "opened_at": candidate["alerted_at"].isoformat(),
        "stop_loss_pct": strategy.stop_loss_pct,
        "take_profit_1_pct": strategy.take_profit_1_pct,
        "take_profit_2_pct": strategy.take_profit_2_pct,
        "take_profit_3_pct": strategy.take_profit_3_pct,
        "max_hold_hours": int(
            (candidate["expires_at"] - candidate["alerted_at"]).total_seconds() // 3600
        ),
        "liquidity_label": candidate["liquidity_label"],
        "simulated_position_size": candidate["position_size_usd"],
    }
    updates = evaluate_open_paper_trade(trade, candidate["post_alert_candles"])

    if updates.get("status") != "closed":
        return None

    return {
        "symbol": candidate["symbol"],
        "alerted_at": candidate["alerted_at"],
        "exit_reason": updates.get("exit_reason"),
        "gross_pnl_pct": updates.get("gross_pnl_pct"),
        "net_pnl_pct": updates.get("net_pnl_pct"),
        "net_pnl_amount": updates.get("net_pnl_amount"),
        "position_size_usd": candidate["position_size_usd"],
    }


def _bucket_stats(trades: list[dict], starting_equity: float = 1000.0) -> dict:
    """Return count/win-rate/avg-net-pnl/profit-factor/max-drawdown/expectancy."""
    count = len(trades)

    if count == 0:
        return {
            "count": 0,
            "win_rate": 0.0,
            "avg_net_pnl_pct": 0.0,
            "profit_factor": None,
            "max_drawdown_pct": 0.0,
            "expectancy_usd": 0.0,
        }

    wins = [t for t in trades if t["net_pnl_pct"] > 0]
    losses = [t for t in trades if t["net_pnl_pct"] <= 0]
    win_rate = len(wins) / count * 100
    avg_net_pnl_pct = sum(t["net_pnl_pct"] for t in trades) / count

    gross_profit = sum(t["net_pnl_amount"] for t in wins)
    gross_loss = abs(sum(t["net_pnl_amount"] for t in losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

    # Equity curve in chronological (alerted_at) order for drawdown.
    ordered = sorted(trades, key=lambda t: t["alerted_at"])
    equity = starting_equity
    peak = starting_equity
    max_drawdown_pct = 0.0

    for trade in ordered:
        equity += trade["net_pnl_amount"]
        peak = max(peak, equity)
        drawdown_pct = (peak - equity) / peak * 100 if peak > 0 else 0.0
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

    expectancy_usd = sum(t["net_pnl_amount"] for t in trades) / count

    return {
        "count": count,
        "win_rate": round(win_rate, 1),
        "avg_net_pnl_pct": round(avg_net_pnl_pct, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "max_drawdown_pct": round(max_drawdown_pct, 1),
        "expectancy_usd": round(expectancy_usd, 2),
    }


def run_exit_model_grid(
    alert_rows: list[dict],
    klines_fetcher: KlinesFetcher,
    k_stop_grid: list[float],
    k_target_grid: list[float],
    k_trail_grid: list[float],
) -> dict:
    """Prepare every eligible candidate once, then grid-search both exit models.

    Returns a dict with the shared candidate count, a "baseline_fixed_pct"
    row (current live exit model, same candidate universe), and one row per
    (model, k_stop, k_target_or_trail) combination.
    """
    candidates = [
        candidate
        for candidate in (prepare_candidate(row, klines_fetcher) for row in alert_rows)
        if candidate is not None
    ]

    baseline_trades = [
        trade
        for trade in (simulate_baseline_fixed_pct(c) for c in candidates)
        if trade is not None
    ]

    grid_results = []

    for k_stop in k_stop_grid:
        for k_target in k_target_grid:
            trades = [
                trade
                for trade in (
                    _trade_result(
                        c,
                        simulate_atr_fixed_target_exit(
                            c["entry_price"],
                            c["atr"],
                            k_stop,
                            k_target,
                            c["post_alert_candles"],
                            c["expires_at"],
                        ),
                    )
                    for c in candidates
                )
                if trade is not None
            ]
            grid_results.append(
                {
                    "model": "atr_fixed_target",
                    "k_stop": k_stop,
                    "k_target_or_trail": k_target,
                    **_bucket_stats(trades),
                }
            )

    for k_stop in k_stop_grid:
        for k_trail in k_trail_grid:
            trades = [
                trade
                for trade in (
                    _trade_result(
                        c,
                        simulate_atr_trailing_exit(
                            c["entry_price"],
                            c["atr"],
                            k_stop,
                            k_trail,
                            c["post_alert_candles"],
                            c["expires_at"],
                        ),
                    )
                    for c in candidates
                )
                if trade is not None
            ]
            grid_results.append(
                {
                    "model": "atr_trailing",
                    "k_stop": k_stop,
                    "k_target_or_trail": k_trail,
                    **_bucket_stats(trades),
                }
            )

    return {
        "candidate_count": len(candidates),
        "baseline_fixed_pct": _bucket_stats(baseline_trades),
        "grid": grid_results,
    }


def format_exit_model_grid_report(report: dict) -> str:
    """Format a run_exit_model_grid() report as a human-readable table."""
    lines = [
        "Exit Model Grid Search — ATR-based vs fixed-% (same candidate universe)",
        "=" * 78,
        f"Eligible candidates (Block 1-3 architecture, unchanged): {report['candidate_count']}",
        "",
        "Baseline (current live model — fixed % stop/target):",
        _format_row(report["baseline_fixed_pct"], label="fixed_pct (live)"),
        "",
        f"{'model':<18}{'k_stop':>7}{'k_tgt/trail':>12}{'trades':>8}{'win%':>7}"
        f"{'avgNet%':>9}{'PF':>7}{'maxDD%':>8}{'exp$':>8}",
    ]

    for row in report["grid"]:
        lines.append(
            f"{row['model']:<18}{row['k_stop']:>7.1f}{row['k_target_or_trail']:>12.1f}"
            f"{row['count']:>8}{row['win_rate']:>7.1f}{row['avg_net_pnl_pct']:>9.2f}"
            f"{(row['profit_factor'] if row['profit_factor'] is not None else float('nan')):>7.2f}"
            f"{row['max_drawdown_pct']:>8.1f}{row['expectancy_usd']:>8.2f}"
        )

    return "\n".join(lines)


def _format_row(stats: dict, label: str) -> str:
    pf = stats["profit_factor"]
    pf_str = f"{pf:.2f}" if pf is not None else "n/a"
    return (
        f"  {label}: {stats['count']} trades, {stats['win_rate']:.1f}% win rate, "
        f"{stats['avg_net_pnl_pct']:+.2f}% avg net P&L, PF={pf_str}, "
        f"max DD={stats['max_drawdown_pct']:.1f}%, expectancy=${stats['expectancy_usd']:+.2f}"
    )
