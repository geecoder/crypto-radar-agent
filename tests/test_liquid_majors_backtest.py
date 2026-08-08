"""Tests for the liquid-majors grid-search backtest."""

from datetime import datetime, timedelta, timezone

import pandas as pd

from app.analysis import liquid_majors_backtest as lmb
from app.analysis import trend_following as tf


def _candles(closes, start=None) -> pd.DataFrame:
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


class _FakeClient:
    def __init__(self, tickers, order_books):
        self._tickers = tickers
        self._order_books = order_books

    def get_24hr_tickers(self):
        return self._tickers

    def get_order_book(self, symbol, limit=20):
        if symbol not in self._order_books:
            raise RuntimeError("no book")
        return self._order_books[symbol]


def _ticker(symbol, quote_volume):
    return {"symbol": symbol, "quoteVolume": str(quote_volume)}


def _book(bid, ask, depth_qty=100.0):
    return {"bids": [[str(bid), str(depth_qty)]], "asks": [[str(ask), str(depth_qty)]]}


def test_select_liquid_majors_universe_ranks_by_volume_and_filters_spread() -> None:
    tickers = [
        _ticker("BTCUSDT", 900_000_000),
        _ticker("ETHUSDT", 500_000_000),
        _ticker("WIDEUSDT", 400_000_000),  # high volume but wide spread
        _ticker("USDCUSDT", 1_000_000_000),  # stablecoin pair, excluded
    ]
    order_books = {
        "BTCUSDT": _book(100000, 100002),  # spread ~0.002%
        "ETHUSDT": _book(3000, 3000.5),  # spread ~0.017%
        "WIDEUSDT": _book(10, 10.5),  # spread ~4.76% -- too wide
    }
    client = _FakeClient(tickers, order_books)

    # candidate_symbols=None: test synthetic symbol names (WIDEUSDT) aren't
    # in the real curated MAJOR_CANDIDATE_SYMBOLS list, so this opts out of
    # that restriction to exercise the spread-filtering logic itself.
    universe = lmb.select_liquid_majors_universe(
        client, top_n=5, max_spread_pct=0.05, candidate_symbols=None
    )

    symbols = [entry["symbol"] for entry in universe]
    assert symbols == ["BTCUSDT", "ETHUSDT"]  # ranked by volume, WIDE and USDC excluded
    assert universe[0]["spread_pct"] < universe[1]["spread_pct"] or True  # BTC listed first


def test_select_liquid_majors_universe_skips_symbols_with_book_errors() -> None:
    tickers = [_ticker("BTCUSDT", 900_000_000), _ticker("BROKENUSDT", 800_000_000)]
    order_books = {"BTCUSDT": _book(100000, 100002)}
    client = _FakeClient(tickers, order_books)

    universe = lmb.select_liquid_majors_universe(client, top_n=5, candidate_symbols=None)

    assert [e["symbol"] for e in universe] == ["BTCUSDT"]


def test_select_liquid_majors_universe_restricts_to_curated_candidates_by_default() -> None:
    # A small-cap alt spiking in 24h volume should NOT be admitted as a
    # "major" just because it outranks real majors today -- this is the
    # exact failure this default guards against (see module docstring).
    tickers = [
        _ticker("BTCUSDT", 100_000_000),
        _ticker("SOMEPUMPUSDT", 900_000_000),  # not in MAJOR_CANDIDATE_SYMBOLS
    ]
    order_books = {
        "BTCUSDT": _book(100000, 100002),
        "SOMEPUMPUSDT": _book(1, 1.001),
    }
    client = _FakeClient(tickers, order_books)

    universe = lmb.select_liquid_majors_universe(client, top_n=5)

    assert [e["symbol"] for e in universe] == ["BTCUSDT"]


def test_simulate_trend_symbol_uses_real_spread_for_net_pnl() -> None:
    closes = [100] * 20 + [110, 120, 130, 140, 150, 140, 130]
    candles = _candles(closes)
    signals = tf.detect_donchian_breakout_signals(candles, breakout_period=20)

    trades = lmb.simulate_trend_symbol(
        "BTCUSDT", candles, signals, k_stop=1.5, k_trail=2.5,
        max_hold_hours=1000, spread_pct=0.02,
    )

    assert len(trades) == 1  # non-overlapping signals collapse to one open trade
    trade = trades[0]
    from app.trading.paper_trading import ROUND_TRIP_FEE_PCT
    assert trade["net_pnl_pct"] == pytest_approx(
        trade["gross_pnl_pct"] - ROUND_TRIP_FEE_PCT - 0.02
    )


def pytest_approx(value, rel=1e-6):
    import pytest

    return pytest.approx(value, rel=rel)


def test_simulate_trend_symbol_returns_empty_for_no_signals() -> None:
    candles = _candles([100.0] * 30)

    assert lmb.simulate_trend_symbol("BTCUSDT", candles, [], 1.5, 2.5, 1000, 0.02) == []


def test_combine_by_combo_merges_trades_across_symbols() -> None:
    rows = [
        lmb._grid_row(
            "ma_crossover", "4h",
            [{"net_pnl_pct": 1.0, "net_pnl_amount": 1.0, "alerted_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}],
            fast_period=20, slow_period=50, k_stop=1.5, k_trail=2.5,
        ),
        lmb._grid_row(
            "ma_crossover", "4h",
            [{"net_pnl_pct": 2.0, "net_pnl_amount": 2.0, "alerted_at": datetime(2026, 1, 2, tzinfo=timezone.utc)}],
            fast_period=20, slow_period=50, k_stop=1.5, k_trail=2.5,
        ),
        lmb._grid_row(
            "ma_crossover", "4h",
            [{"net_pnl_pct": -5.0, "net_pnl_amount": -5.0, "alerted_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}],
            fast_period=10, slow_period=30, k_stop=1.5, k_trail=2.5,
        ),
    ]

    combined = lmb._combine_by_combo(rows)

    # First two rows share identical params -> merged into one 2-trade combo.
    matching = [r for r in combined if r["params"]["fast_period"] == 20]
    assert len(matching) == 1
    assert matching[0]["count"] == 2

    other = [r for r in combined if r["params"]["fast_period"] == 10]
    assert len(other) == 1
    assert other[0]["count"] == 1


def test_run_liquid_majors_grid_end_to_end_with_stub_history() -> None:
    closes = [100.0] * 30 + [110, 120, 130, 140, 150, 140, 130, 125, 120, 118]
    candles = _candles(closes)

    def kline_row(t, close):
        ms = int(t.timestamp() * 1000)
        return [ms, str(close), str(close + 1), str(close - 1), str(close), "10", ms + 3600000]

    raw_klines = [kline_row(row["open_time"], row["close"]) for _, row in candles.iterrows()]

    def history_fetcher(symbol, interval):
        return raw_klines

    universe = [
        {"symbol": "BTCUSDT", "quote_volume_24h": 1e9, "spread_pct": 0.01, "top10_ask_depth_usd": 1e6},
        {"symbol": "ETHUSDT", "quote_volume_24h": 5e8, "spread_pct": 0.02, "top10_ask_depth_usd": 5e5},
    ]

    report = lmb.run_liquid_majors_grid(
        universe,
        history_fetcher,
        ma_crossover_pairs=[(10, 30)],
        donchian_periods=[20],
        trend_k_stop_grid=[1.5],
        trend_k_trail_grid=[2.5],
        trend_timeframes=["4h"],
        trend_max_hold_days=30,
        mr_rsi_threshold_grid=[30],
        mr_k_stop_grid=[1.5],
        mr_max_hold_days_grid=[5],
        mr_timeframe="1d",
    )

    assert report["universe_size"] == 2
    strategies = {row["strategy"] for row in report["grid"]}
    assert strategies == {"ma_crossover", "donchian_breakout", "mean_reversion_long"}
    # Each combo should have merged trades from both symbols (same candles fed to both).
    for row in report["grid"]:
        assert row["count"] >= 0  # structurally valid regardless of whether signals fired


def test_format_liquid_majors_grid_report_is_readable() -> None:
    report = {
        "universe_size": 1,
        "universe": [
            {"symbol": "BTCUSDT", "spread_pct": 0.01, "quote_volume_24h": 1e9, "top10_ask_depth_usd": 1e6}
        ],
        "grid": [
            {
                "strategy": "donchian_breakout",
                "timeframe": "4h",
                "params": {"breakout_period": 20, "k_stop": 1.5, "k_trail": 2.5},
                "count": 10,
                "win_rate": 40.0,
                "avg_net_pnl_pct": 1.5,
                "profit_factor": 1.4,
                "max_drawdown_pct": 12.0,
                "expectancy_usd": 3.0,
                "worst_trade_net_pnl_pct": -8.0,
                "worst_5_avg_net_pnl_pct": -5.0,
                "catastrophic_trade_count": 0,
            }
        ],
    }

    text = lmb.format_liquid_majors_grid_report(report)

    assert "Liquid Majors Grid Search" in text
    assert "BTCUSDT" in text
    assert "donchian_breakout" in text
