"""Grid-search backtest: does anything work on liquid majors?

Four strategy tests on the alt universe (momentum fixed-exit, momentum
ATR-exit, mean-reversion long, mean-reversion short) all failed after real
costs, with a consistent pattern: cost drag on illiquid small/mid-cap alts
destroys any edge before it can show up. This tests the one cheap untested
hypothesis: restrict to liquid majors (BTC, ETH, SOL, ...), where spread and
slippage are structurally near-zero, and test classic trend-following
(app.analysis.trend_following) plus the same mean-reversion model
(app.analysis.mean_reversion) already built — on slower 4h/1d timeframes,
over as much history as Binance will serve, with REAL measured order-book
spread standing in for slippage instead of the alt backtests' conservative
flat estimate.

Nothing here is wired into live trading — only a config this grid search
confirms wins should ever get deployed to app/trading/paper_trading.py.
"""

from datetime import timedelta
from typing import Any, Callable

import pandas as pd

from app.analysis.exit_model_backtest import _bucket_stats
from app.analysis.exit_models import ATR_PERIOD, compute_atr, simulate_atr_trailing_exit
from app.analysis.mean_reversion_backtest import _tail_risk_stats, backtest_symbol as backtest_mean_reversion_symbol
from app.analysis.trend_following import detect_donchian_breakout_signals, detect_ma_crossover_signals
from app.risk.risk_manager import compute_position_size
from app.trading.paper_trading import ROUND_TRIP_FEE_PCT

# Stablecoin/fiat base assets excluded from the "liquid majors" universe --
# a stablecoin-USDT pair isn't a trading opportunity in the sense this test
# cares about (no real price trend or reversion to exploit).
STABLE_BASE_ASSETS = {
    "USDC", "FDUSD", "TUSD", "DAI", "USDP", "PAX", "USTC", "BUSD", "EUR", "GBP", "AEUR",
}

# Deliberately tight -- real majors typically show well under this; anything
# wider suggests the "liquid" assumption doesn't hold for that symbol today.
DEFAULT_MAX_SPREAD_PCT = 0.05
HistoryFetcher = Callable[[str, str], list]  # (symbol, interval) -> raw klines


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _base_asset(symbol: str) -> str:
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def select_liquid_majors_universe(
    client,
    top_n: int = 25,
    max_spread_pct: float = DEFAULT_MAX_SPREAD_PCT,
    order_book_limit: int = 20,
) -> list[dict]:
    """Rank USDT pairs by 24h quote volume, then confirm each candidate's
    CURRENT order book has a tight spread and real depth before including it.

    Returns a list of dicts (symbol, quote_volume_24h, spread_pct,
    top10_ask_depth_usd), best-volume-first, capped at `top_n` entries that
    pass the spread check.
    """
    tickers = client.get_24hr_tickers()
    usdt_pairs = [
        ticker
        for ticker in tickers
        if str(ticker.get("symbol") or "").endswith("USDT")
        and _base_asset(str(ticker.get("symbol"))) not in STABLE_BASE_ASSETS
    ]
    ranked = sorted(
        usdt_pairs,
        key=lambda t: _safe_float(t.get("quoteVolume"), default=0.0) or 0.0,
        reverse=True,
    )

    universe = []

    for ticker in ranked:
        if len(universe) >= top_n:
            break

        symbol = ticker.get("symbol")

        try:
            book = client.get_order_book(symbol, limit=order_book_limit)
        except Exception:
            continue

        bids = book.get("bids") or []
        asks = book.get("asks") or []

        if not bids or not asks:
            continue

        best_bid = _safe_float(bids[0][0], default=None)
        best_ask = _safe_float(asks[0][0], default=None)

        if not best_bid or not best_ask or best_ask <= 0:
            continue

        spread_pct = max(0.0, (best_ask - best_bid) / best_ask * 100)

        if spread_pct > max_spread_pct:
            continue

        depth_usd = sum(
            _safe_float(price, 0.0) * _safe_float(qty, 0.0) for price, qty in asks[:10]
        )

        universe.append(
            {
                "symbol": symbol,
                "quote_volume_24h": _safe_float(ticker.get("quoteVolume")),
                "spread_pct": round(spread_pct, 4),
                "top10_ask_depth_usd": round(depth_usd, 2),
            }
        )

    return universe


def _net_pnl_pct(gross_pnl_pct: float, spread_pct: float) -> float:
    """Net P&L using the symbol's REAL measured spread as the slippage
    estimate (crossing the spread once on entry, once on exit ≈ one full
    spread round trip) instead of the alt backtests' flat worst-tier guess.
    """
    return gross_pnl_pct - ROUND_TRIP_FEE_PCT - spread_pct


def simulate_trend_symbol(
    symbol: str,
    candles: pd.DataFrame,
    signals: list[dict],
    k_stop: float,
    k_trail: float,
    max_hold_hours: int,
    spread_pct: float,
) -> list[dict]:
    """Simulate a pre-detected list of trend-following signals against one
    symbol's candles, with the ATR trailing-stop exit shared by both
    trend-following variants (MA crossover and Donchian breakout) — the
    entry rule differs, but "let the trend run" is the same exit philosophy
    either way.

    Enforces no-pyramiding: a new signal is skipped while an earlier trade
    for this symbol is still open.
    """
    if not signals:
        return []

    # exit_models._row_time() always reads candle timestamps as UTC-aware
    # (via pd.to_datetime(..., utc=True)), regardless of whether the source
    # column is tz-naive (klines_to_dataframe) or already tz-aware (tests /
    # other callers). Normalize open_time the same way once here so every
    # comparison against exit_models' output compares like with like.
    open_times_utc = pd.to_datetime(candles["open_time"], utc=True)
    trades = []
    next_available_index = 0

    for signal in signals:
        entry_index = signal["entry_index"]

        if entry_index < next_available_index:
            continue

        atr = compute_atr(candles.iloc[: entry_index + 1], period=ATR_PERIOD)

        if atr is None or atr <= 0:
            continue

        entry_price = signal["entry_price"]
        entry_time = signal["entry_time"]
        expires_at = open_times_utc.iloc[entry_index] + timedelta(hours=max_hold_hours)

        close = simulate_atr_trailing_exit(
            entry_price, atr, k_stop, k_trail, candles.iloc[entry_index:], expires_at
        )

        if close is None:
            continue

        stop_distance_pct = k_stop * atr / entry_price * 100
        position_size_usd = compute_position_size(-stop_distance_pct)
        net_pnl_pct = _net_pnl_pct(close["gross_pnl_pct"], spread_pct)

        trades.append(
            {
                "symbol": symbol,
                "alerted_at": entry_time,
                "strategy": signal.get("strategy"),
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
            if open_times_utc.iloc[i] >= exit_time:
                next_available_index = i + 1
                break

    return trades


def run_liquid_majors_grid(
    universe: list[dict],
    history_fetcher: HistoryFetcher,
    ma_crossover_pairs: list[tuple[int, int]],
    donchian_periods: list[int],
    trend_k_stop_grid: list[float],
    trend_k_trail_grid: list[float],
    trend_timeframes: list[str],
    trend_max_hold_days: int,
    mr_rsi_threshold_grid: list[float],
    mr_k_stop_grid: list[float],
    mr_max_hold_days_grid: list[int],
    mr_timeframe: str = "1d",
) -> dict:
    """Grid-search trend-following (MA crossover + Donchian, both timeframes)
    and mean-reversion (long only — the short side was already found
    catastrophic on alts and isn't worth re-testing) across the liquid
    majors universe. Fetches each symbol's candle history once per
    timeframe and reuses it across every combination on that timeframe.
    """
    from app.binance.client import klines_to_dataframe

    candles_cache: dict[tuple[str, str], pd.DataFrame] = {}

    def get_candles(symbol: str, interval: str) -> pd.DataFrame | None:
        key = (symbol, interval)
        if key in candles_cache:
            return candles_cache[key]

        raw = history_fetcher(symbol, interval)

        if not raw:
            candles_cache[key] = None
            return None

        candles = klines_to_dataframe(raw)
        candles_cache[key] = candles if not candles.empty else None
        return candles_cache[key]

    grid_results = []
    trend_max_hold_hours = trend_max_hold_days * 24

    for timeframe in trend_timeframes:
        for entry in universe:
            symbol = entry["symbol"]
            candles = get_candles(symbol, timeframe)

            if candles is None:
                continue

            for fast_period, slow_period in ma_crossover_pairs:
                signals = detect_ma_crossover_signals(candles, fast_period, slow_period)

                for k_stop in trend_k_stop_grid:
                    for k_trail in trend_k_trail_grid:
                        trades = simulate_trend_symbol(
                            symbol, candles, signals, k_stop, k_trail,
                            trend_max_hold_hours, entry["spread_pct"],
                        )
                        grid_results.append(
                            _grid_row(
                                "ma_crossover", timeframe, trades,
                                fast_period=fast_period, slow_period=slow_period,
                                k_stop=k_stop, k_trail=k_trail,
                            )
                        )

            for breakout_period in donchian_periods:
                signals = detect_donchian_breakout_signals(candles, breakout_period)

                for k_stop in trend_k_stop_grid:
                    for k_trail in trend_k_trail_grid:
                        trades = simulate_trend_symbol(
                            symbol, candles, signals, k_stop, k_trail,
                            trend_max_hold_hours, entry["spread_pct"],
                        )
                        grid_results.append(
                            _grid_row(
                                "donchian_breakout", timeframe, trades,
                                breakout_period=breakout_period,
                                k_stop=k_stop, k_trail=k_trail,
                            )
                        )

    # Mean-reversion, long only, on its own (typically daily) timeframe.
    for entry in universe:
        symbol = entry["symbol"]
        candles = get_candles(symbol, mr_timeframe)

        if candles is None:
            continue

        for rsi_threshold in mr_rsi_threshold_grid:
            for k_stop in mr_k_stop_grid:
                for max_hold_days in mr_max_hold_days_grid:
                    trades = backtest_mean_reversion_symbol(
                        symbol, candles, "long", rsi_threshold, k_stop,
                        max_hold_days * 24, slippage_pct_override=entry["spread_pct"],
                    )
                    grid_results.append(
                        _grid_row(
                            "mean_reversion_long", mr_timeframe, trades,
                            rsi_threshold=rsi_threshold, k_stop=k_stop,
                            max_hold_days=max_hold_days,
                        )
                    )

    # Aggregate results computed per-symbol above need one more pass: combine
    # same-combo rows across symbols into a single grid row each.
    combined = _combine_by_combo(grid_results)

    return {
        "universe_size": len(universe),
        "universe": universe,
        "grid": combined,
    }


def _grid_row(strategy: str, timeframe: str, trades: list[dict], **params) -> dict:
    """One symbol's trades for one combo, tagged for later aggregation."""
    return {"strategy": strategy, "timeframe": timeframe, "params": params, "trades": trades}


def _combine_by_combo(rows: list[dict]) -> list[dict]:
    """Merge per-symbol trade lists into one row per (strategy, timeframe, params) combo."""
    combos: dict[tuple, list[dict]] = {}

    for row in rows:
        key = (row["strategy"], row["timeframe"], tuple(sorted(row["params"].items())))
        combos.setdefault(key, []).extend(row["trades"])

    combined = []

    for (strategy, timeframe, params_items), trades in combos.items():
        combined.append(
            {
                "strategy": strategy,
                "timeframe": timeframe,
                "params": dict(params_items),
                **_bucket_stats(trades),
                **_tail_risk_stats(trades),
            }
        )

    return combined


def format_liquid_majors_grid_report(report: dict) -> str:
    """Format a run_liquid_majors_grid() report as a human-readable table."""
    lines = [
        "Liquid Majors Grid Search",
        "=" * 100,
        f"Universe ({report['universe_size']} symbols):",
    ]

    for entry in report["universe"]:
        lines.append(
            f"  {entry['symbol']:<12} spread={entry['spread_pct']:.4f}%  "
            f"vol24h=${entry['quote_volume_24h']:,.0f}  "
            f"top10 ask depth=${entry['top10_ask_depth_usd']:,.0f}"
        )

    lines += [
        "",
        f"{'strategy':<20}{'tf':>5}{'params':<32}{'trades':>7}{'win%':>7}"
        f"{'avgNet%':>9}{'PF':>7}{'maxDD%':>8}{'exp$':>8}{'worst%':>8}{'worst5%':>9}{'catN':>6}",
    ]

    for row in sorted(report["grid"], key=lambda r: -(r["expectancy_usd"] or -999999)):
        pf = row["profit_factor"]
        pf_str = f"{pf:.2f}" if pf is not None else "n/a"
        worst_pct = row["worst_trade_net_pnl_pct"]
        worst5_pct = row["worst_5_avg_net_pnl_pct"]
        params_str = ",".join(f"{k}={v}" for k, v in row["params"].items())
        lines.append(
            f"{row['strategy']:<20}{row['timeframe']:>5}{params_str:<32}"
            f"{row['count']:>7}{row['win_rate']:>7.1f}{row['avg_net_pnl_pct']:>9.2f}"
            f"{pf_str:>7}{row['max_drawdown_pct']:>8.1f}{row['expectancy_usd']:>8.2f}"
            f"{(worst_pct if worst_pct is not None else float('nan')):>8.1f}"
            f"{(worst5_pct if worst5_pct is not None else float('nan')):>9.1f}"
            f"{row['catastrophic_trade_count']:>6}"
        )

    return "\n".join(lines)
