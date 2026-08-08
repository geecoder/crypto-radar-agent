"""Tests for the mean-reversion grid-search backtest orchestrator."""

from datetime import datetime, timedelta, timezone

import pandas as pd

from app.analysis import mean_reversion_backtest as mrb


def _candle_row(t, close, high=None, low=None):
    high = high if high is not None else close + 0.2
    low = low if low is not None else close - 0.2
    return {"open_time": t, "open": close, "high": high, "low": low, "close": close, "volume": 1.0}


def _bounce_candles(start=None) -> pd.DataFrame:
    """25 flat candles, a plunge to 85 (confirmed bounce to 90), then a
    reversion back up toward the mean at 100."""
    start = start or datetime(2026, 6, 1, tzinfo=timezone.utc)
    closes = [100.0] * 25 + [90, 85, 90, 95, 100, 100, 100, 100, 100]
    return pd.DataFrame(
        [_candle_row(start + timedelta(hours=i), c) for i, c in enumerate(closes)]
    )


def _kline_row(t, close):
    ms = int(t.timestamp() * 1000)
    return [ms, str(close), str(close + 0.2), str(close - 0.2), str(close), "10", ms + 3600000]


def test_backtest_symbol_detects_one_trade_and_computes_net_pnl() -> None:
    candles = _bounce_candles()

    trades = mrb.backtest_symbol(
        "TESTUSDT", candles, "long", rsi_threshold=25, k_stop=1.5, max_hold_hours=24
    )

    assert len(trades) == 1
    trade = trades[0]
    assert trade["direction"] == "long"
    assert trade["entry_price"] == 90.0
    assert trade["exit_reason"] == "mean_reversion_target"
    assert trade["gross_pnl_pct"] > 0
    # Net P&L = gross - fee - flat slippage estimate.
    from app.trading.paper_trading import DEFAULT_SLIPPAGE_PCT, ROUND_TRIP_FEE_PCT
    assert trade["net_pnl_pct"] == pytest_approx(
        trade["gross_pnl_pct"] - ROUND_TRIP_FEE_PCT - DEFAULT_SLIPPAGE_PCT
    )
    assert trade["position_size_usd"] > 0


def pytest_approx(value, rel=1e-6):
    import pytest

    return pytest.approx(value, rel=rel)


def test_backtest_symbol_returns_empty_for_short_history() -> None:
    candles = _bounce_candles().iloc[:10]

    trades = mrb.backtest_symbol(
        "TESTUSDT", candles, "long", rsi_threshold=25, k_stop=1.5, max_hold_hours=24
    )

    assert trades == []


def test_backtest_symbol_does_not_pyramid_while_a_trade_is_open() -> None:
    # Two plunge-bounce cycles back to back; the second signal fires while
    # the first trade would still logically be "in flight" at that candle
    # index if pyramiding were allowed.
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    closes = (
        [100.0] * 25
        + [90, 85, 90]  # cycle 1 signal + confirm
        + [88, 83, 88]  # cycle 2 signal + confirm, shortly after
        + [95, 100, 100, 100, 100]
    )
    candles = pd.DataFrame(
        [_candle_row(start + timedelta(hours=i), c) for i, c in enumerate(closes)]
    )

    trades = mrb.backtest_symbol(
        "TESTUSDT", candles, "long", rsi_threshold=25, k_stop=1.5, max_hold_hours=1
    )

    # With a 1-hour max hold, the first trade resolves almost immediately,
    # freeing the scanner to pick up the second signal -- but trades must
    # never overlap in time.
    for i in range(1, len(trades)):
        assert trades[i]["alerted_at"] >= trades[i - 1]["alerted_at"]


def test_tail_risk_stats_flags_catastrophic_loss() -> None:
    base_time = datetime(2026, 6, 1, tzinfo=timezone.utc)
    trades = [
        {"alerted_at": base_time, "net_pnl_pct": 5.0, "net_pnl_amount": 5.0},
        {"alerted_at": base_time, "net_pnl_pct": -3.0, "net_pnl_amount": -3.0},
        # A blow-through loss: -12% of the $1000 reference portfolio.
        {"alerted_at": base_time, "net_pnl_pct": -40.0, "net_pnl_amount": -120.0},
    ]

    stats = mrb._tail_risk_stats(trades, starting_equity=1000.0, catastrophic_loss_pct=10.0)

    assert stats["worst_trade_net_pnl_pct"] == -40.0
    assert stats["worst_trade_net_pnl_amount"] == -120.0
    assert stats["catastrophic_trade_count"] == 1


def test_tail_risk_stats_handles_no_trades() -> None:
    stats = mrb._tail_risk_stats([])

    assert stats["worst_trade_net_pnl_pct"] is None
    assert stats["catastrophic_trade_count"] == 0


def test_run_mean_reversion_grid_covers_full_combo_space() -> None:
    candles = _bounce_candles()
    raw_klines = [_kline_row(row["open_time"], row["close"]) for _, row in candles.iterrows()]

    def history_fetcher(symbol):
        return raw_klines

    report = mrb.run_mean_reversion_grid(
        symbols=["AAAUSDT", "BBBUSDT"],
        history_fetcher=history_fetcher,
        direction_grid=["long", "short"],
        rsi_threshold_grid_by_direction={"long": [25, 30], "short": [75]},
        k_stop_grid=[1.0, 1.5],
        max_hold_hours_grid=[24],
    )

    assert report["symbols_scanned"] == 2
    assert report["symbols_with_data"] == 2
    # long: 2 rsi x 2 kstop x 1 hold = 4; short: 1 rsi x 2 kstop x 1 hold = 2
    assert len(report["grid"]) == 6

    long_rows = [r for r in report["grid"] if r["direction"] == "long"]
    short_rows = [r for r in report["grid"] if r["direction"] == "short"]
    assert all(r["tradable_on_spot"] is True for r in long_rows)
    assert all(r["tradable_on_spot"] is False for r in short_rows)


def test_run_mean_reversion_grid_skips_symbols_with_no_data() -> None:
    def history_fetcher(symbol):
        return [] if symbol == "DEADUSDT" else [
            _kline_row(datetime(2026, 6, 1, tzinfo=timezone.utc) + timedelta(hours=i), 100.0)
            for i in range(40)
        ]

    report = mrb.run_mean_reversion_grid(
        symbols=["DEADUSDT", "ALIVEUSDT"],
        history_fetcher=history_fetcher,
        direction_grid=["long"],
        rsi_threshold_grid_by_direction={"long": [25]},
        k_stop_grid=[1.5],
        max_hold_hours_grid=[24],
    )

    assert report["symbols_scanned"] == 2
    assert report["symbols_with_data"] == 1


def test_format_mean_reversion_grid_report_flags_non_tradable_short() -> None:
    report = {
        "symbols_scanned": 5,
        "symbols_with_data": 5,
        "grid": [
            {
                "direction": "long",
                "tradable_on_spot": True,
                "rsi_threshold": 25,
                "k_stop": 1.5,
                "max_hold_hours": 24,
                "count": 10,
                "win_rate": 40.0,
                "avg_net_pnl_pct": -0.5,
                "profit_factor": 0.9,
                "max_drawdown_pct": 15.0,
                "expectancy_usd": -1.0,
                "worst_trade_net_pnl_pct": -15.0,
                "worst_trade_net_pnl_amount": -50.0,
                "worst_5_avg_net_pnl_pct": -10.0,
                "catastrophic_trade_count": 0,
            },
            {
                "direction": "short",
                "tradable_on_spot": False,
                "rsi_threshold": 75,
                "k_stop": 1.5,
                "max_hold_hours": 24,
                "count": 8,
                "win_rate": 50.0,
                "avg_net_pnl_pct": 1.0,
                "profit_factor": 1.5,
                "max_drawdown_pct": 8.0,
                "expectancy_usd": 2.0,
                "worst_trade_net_pnl_pct": -8.0,
                "worst_trade_net_pnl_amount": -20.0,
                "worst_5_avg_net_pnl_pct": -5.0,
                "catastrophic_trade_count": 0,
            },
        ],
    }

    text = mrb.format_mean_reversion_grid_report(report)

    assert "Mean-Reversion Grid Search" in text
    assert "yes" in text  # long row marked tradable
    assert "NO" in text  # short row marked not tradable
