"""Tests for the ATR exit-model grid-search backtest."""

from datetime import datetime, timedelta, timezone

from app.analysis import exit_model_backtest as emb


def _alert_row(**overrides) -> dict:
    row = {
        "symbol": "HEIUSDT",
        "alerted_at": datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        "latest_close": 100.0,
        "alert_type": "Parabolic Watch Alert",
        "opportunity_score": 58,
        "move_from_recent_low_pct": 116.5,
        "liquidity_label": "Good",
        "exhaustion_risk_level": "Medium",
        "recent_price_changes": {
            "change_1h_pct": 2.5,
            "change_2h_pct": 5.5,
            "change_4h_pct": 11.0,
            "change_24h_pct": 75.0,
        },
        "volume_acceleration": {
            "volume_acceleration_1h_ratio": 1.4,
            "volume_acceleration_2h_ratio": 2.1,
        },
        "breakout_signal": {"score": 60},
        "trend_signal": {"score": 60},
        "volatility_signal": {"score": 60},
        "paper_trade_created": False,
    }
    row.update(overrides)
    return row


def _kline_row(open_time_ms: int, high: float, low: float, close: float) -> list:
    return [open_time_ms, str(close), str(high), str(low), str(close), "10", open_time_ms + 15 * 60 * 1000]


def _flat_klines(start_ms: int, count: int, price: float = 100.0, wobble: float = 1.0) -> list:
    """Candles with a constant +/-`wobble` high/low band around `price`."""
    return [
        _kline_row(start_ms + i * 15 * 60 * 1000, price + wobble, price - wobble, price)
        for i in range(count)
    ]


def test_prepare_candidate_returns_none_when_ineligible() -> None:
    row = _alert_row(
        move_from_recent_low_pct=214.0,
        recent_price_changes={
            "change_1h_pct": 1.0,
            "change_2h_pct": 1.0,
            "change_4h_pct": 1.0,
            "change_24h_pct": 10.0,  # below the 50% parabolic gate
        },
    )

    def fetcher(symbol, start_time_ms, num_candles):
        raise AssertionError("klines_fetcher should not be called for ineligible alerts")

    assert emb.prepare_candidate(row, fetcher) is None


def test_prepare_candidate_returns_none_without_enough_atr_lookback() -> None:
    row = _alert_row()
    alerted_at_ms = int(row["alerted_at"].timestamp() * 1000)

    def fetcher(symbol, start_time_ms, num_candles):
        # Only 2 candles total -- nowhere near ATR_PERIOD=14 of lookback.
        return _flat_klines(start_time_ms, 2)

    assert emb.prepare_candidate(row, fetcher) is None


def test_prepare_candidate_builds_full_candidate_with_atr() -> None:
    row = _alert_row()
    alerted_at_ms = int(row["alerted_at"].timestamp() * 1000)
    lookback_start_ms = alerted_at_ms - 15 * 15 * 60 * 1000

    def fetcher(symbol, start_time_ms, num_candles):
        assert symbol == "HEIUSDT"
        assert start_time_ms == lookback_start_ms
        return _flat_klines(start_time_ms, num_candles, price=100.0, wobble=1.0)

    candidate = emb.prepare_candidate(row, fetcher)

    assert candidate is not None
    assert candidate["symbol"] == "HEIUSDT"
    assert candidate["entry_price"] == 100.0
    assert candidate["atr"] == 2.0  # wobble=1.0 -> high-low=2.0 flat series
    assert not candidate["post_alert_candles"].empty
    assert candidate["position_size_usd"] > 0
    assert candidate["strategy"].name == "parabolic_continuation_paper"


def test_simulate_baseline_fixed_pct_matches_live_exit_logic() -> None:
    row = _alert_row()
    alerted_at_ms = int(row["alerted_at"].timestamp() * 1000)
    lookback_start_ms = alerted_at_ms - 15 * 15 * 60 * 1000

    def fetcher(symbol, start_time_ms, num_candles):
        return _flat_klines(start_time_ms, num_candles, price=100.0, wobble=1.0)

    candidate = emb.prepare_candidate(row, fetcher)
    trade = emb.simulate_baseline_fixed_pct(candidate)

    # Flat candles never touch stop_loss_pct=-8/take_profit -> resolves at
    # max_hold_expired with ~0% gross P&L.
    assert trade is not None
    assert trade["exit_reason"] == "max_hold_expired"
    assert abs(trade["gross_pnl_pct"]) < 0.1


def test_bucket_stats_computes_profit_factor_and_drawdown() -> None:
    base_time = datetime(2026, 6, 1, tzinfo=timezone.utc)
    trades = [
        {
            "alerted_at": base_time,
            "net_pnl_pct": 10.0,
            "net_pnl_amount": 10.0,
        },
        {
            "alerted_at": base_time + timedelta(hours=1),
            "net_pnl_pct": -5.0,
            "net_pnl_amount": -5.0,
        },
        {
            "alerted_at": base_time + timedelta(hours=2),
            "net_pnl_pct": -5.0,
            "net_pnl_amount": -5.0,
        },
    ]

    stats = emb._bucket_stats(trades, starting_equity=100.0)

    assert stats["count"] == 3
    assert stats["win_rate"] == pytest_approx(33.3)
    assert stats["profit_factor"] == 1.0  # 10 gross profit / 10 gross loss
    assert stats["expectancy_usd"] == 0.0
    # Equity: 100 -> 110 (peak) -> 105 -> 100. Drawdown from peak 110 to 100 = 9.09%.
    assert stats["max_drawdown_pct"] == pytest_approx(9.1, abs=0.1)


def pytest_approx(value, abs=0.05):
    import pytest

    return pytest.approx(value, abs=abs)


def test_bucket_stats_handles_zero_trades() -> None:
    stats = emb._bucket_stats([])

    assert stats["count"] == 0
    assert stats["profit_factor"] is None


def test_run_exit_model_grid_produces_baseline_and_all_combos() -> None:
    row = _alert_row()

    def fetcher(symbol, start_time_ms, num_candles):
        return _flat_klines(start_time_ms, num_candles, price=100.0, wobble=1.0)

    report = emb.run_exit_model_grid(
        [row],
        fetcher,
        k_stop_grid=[1.0, 1.5],
        k_target_grid=[2.0, 3.0],
        k_trail_grid=[2.0, 3.0],
    )

    assert report["candidate_count"] == 1
    assert report["baseline_fixed_pct"]["count"] == 1
    # 2 k_stop x 2 k_target (fixed_target) + 2 k_stop x 2 k_trail (trailing) = 8
    assert len(report["grid"]) == 8
    models = {(r["model"], r["k_stop"], r["k_target_or_trail"]) for r in report["grid"]}
    assert ("atr_fixed_target", 1.0, 2.0) in models
    assert ("atr_trailing", 1.5, 3.0) in models


def test_format_exit_model_grid_report_is_readable() -> None:
    report = {
        "candidate_count": 5,
        "baseline_fixed_pct": {
            "count": 5,
            "win_rate": 40.0,
            "avg_net_pnl_pct": -1.0,
            "profit_factor": 0.8,
            "max_drawdown_pct": 12.0,
            "expectancy_usd": -1.5,
        },
        "grid": [
            {
                "model": "atr_fixed_target",
                "k_stop": 1.5,
                "k_target_or_trail": 3.0,
                "count": 5,
                "win_rate": 45.0,
                "avg_net_pnl_pct": 0.5,
                "profit_factor": 1.1,
                "max_drawdown_pct": 10.0,
                "expectancy_usd": 0.8,
            }
        ],
    }

    text = emb.format_exit_model_grid_report(report)

    assert "Exit Model Grid Search" in text
    assert "fixed_pct (live)" in text
    assert "atr_fixed_target" in text
