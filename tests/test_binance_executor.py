"""Tests for the Binance executor and go-live precondition gates."""

import pytest

from app.exchange import binance_executor
from app.exchange.binance_executor import (
    BinanceExecutor,
    GoLiveGate,
    all_go_live_gates_pass,
    check_go_live_preconditions,
    fetch_real_fill,
    format_go_live_report,
    walk_order_book,
)


def _gates(
    closed=100, win_rate=60.0, avg_pnl=2.5, tg_rate=95.0, risk=True,
    good_liq_closed=100, good_liq_net_avg=1.0,
) -> list[GoLiveGate]:
    return check_go_live_preconditions(
        closed_paper_trade_count=closed,
        win_rate_last_100=win_rate,
        avg_pnl_last_100=avg_pnl,
        telegram_send_rate_7d=tg_rate,
        risk_manager_active=risk,
        good_liquidity_closed_trade_count=good_liq_closed,
        good_liquidity_net_avg_pnl_pct=good_liq_net_avg,
    )


def test_all_gates_pass_when_criteria_met() -> None:
    gates = _gates()
    assert all_go_live_gates_pass(gates) is True


def test_fails_when_not_enough_paper_trades() -> None:
    gates = _gates(closed=99)
    assert all_go_live_gates_pass(gates) is False
    failing = [g for g in gates if not g.passed]
    assert any(g.name == "min_paper_trades" for g in failing)


def test_fails_when_win_rate_too_low() -> None:
    gates = _gates(win_rate=54.9)
    assert all_go_live_gates_pass(gates) is False
    failing = [g for g in gates if not g.passed]
    assert any(g.name == "min_win_rate" for g in failing)


def test_fails_when_avg_pnl_negative() -> None:
    gates = _gates(avg_pnl=-0.1)
    assert all_go_live_gates_pass(gates) is False
    failing = [g for g in gates if not g.passed]
    assert any(g.name == "positive_avg_pnl" for g in failing)


def test_fails_when_telegram_rate_low() -> None:
    gates = _gates(tg_rate=89.9)
    assert all_go_live_gates_pass(gates) is False
    failing = [g for g in gates if not g.passed]
    assert any(g.name == "telegram_send_rate" for g in failing)


def test_fails_when_risk_manager_not_active() -> None:
    gates = _gates(risk=False)
    assert all_go_live_gates_pass(gates) is False
    failing = [g for g in gates if not g.passed]
    assert any(g.name == "risk_manager_active" for g in failing)


def test_fails_when_good_liquidity_expectancy_not_met() -> None:
    gates = _gates(good_liq_closed=40, good_liq_net_avg=1.0)
    assert all_go_live_gates_pass(gates) is False
    failing = [g for g in gates if not g.passed]
    assert any(g.name == "good_liquidity_net_expectancy" for g in failing)


def test_fails_when_good_liquidity_net_expectancy_negative() -> None:
    gates = _gates(good_liq_closed=150, good_liq_net_avg=-0.5)
    assert all_go_live_gates_pass(gates) is False
    failing = [g for g in gates if not g.passed]
    assert any(g.name == "good_liquidity_net_expectancy" for g in failing)


def test_format_go_live_report_shows_pass_fail() -> None:
    gates = _gates(closed=50, win_rate=40.0)  # two failures
    report = format_go_live_report(gates)
    assert "PASS" in report
    assert "FAIL" in report
    assert "NOT READY" in report


def test_format_go_live_report_shows_ready_when_all_pass() -> None:
    gates = _gates()
    report = format_go_live_report(gates)
    assert "READY" in report
    assert "NOT READY" not in report


def test_walk_order_book_computes_vwap_across_levels() -> None:
    # 1 @ 100, 1 @ 101 -> buying 2 costs (100 + 101) / 2 = 100.5
    levels = [["100.0", "1.0"], ["101.0", "1.0"], ["102.0", "5.0"]]

    assert walk_order_book(levels, 2.0) == 100.5


def test_walk_order_book_returns_none_when_book_lacks_depth() -> None:
    levels = [["100.0", "1.0"]]

    assert walk_order_book(levels, 5.0) is None


def test_walk_order_book_returns_none_for_non_positive_quantity() -> None:
    assert walk_order_book([["100.0", "1.0"]], 0) is None


def test_fetch_real_fill_walks_asks_for_buy_and_reports_spread(monkeypatch) -> None:
    book = {
        "bids": [["99.0", "10.0"]],
        "asks": [["100.0", "1.0"], ["101.0", "10.0"]],
    }

    class FakePublicClient:
        def get_order_book(self, symbol):
            assert symbol == "BTCUSDT"
            return book

    monkeypatch.setattr(binance_executor, "BinancePublicClient", FakePublicClient)

    real_fill_price, spread_pct = fetch_real_fill("BTCUSDT", "buy", 2.0)

    assert real_fill_price == 100.5
    assert spread_pct == pytest.approx((100.0 - 99.0) / 100.0 * 100)


def test_fetch_real_fill_walks_bids_for_sell(monkeypatch) -> None:
    book = {
        "bids": [["99.0", "1.0"], ["98.0", "10.0"]],
        "asks": [["100.0", "10.0"]],
    }

    class FakePublicClient:
        def get_order_book(self, symbol):
            return book

    monkeypatch.setattr(binance_executor, "BinancePublicClient", FakePublicClient)

    real_fill_price, _ = fetch_real_fill("BTCUSDT", "sell", 2.0)

    assert real_fill_price == 98.5


def test_fetch_real_fill_returns_none_on_error(monkeypatch) -> None:
    class FakePublicClient:
        def get_order_book(self, symbol):
            raise RuntimeError("network down")

    monkeypatch.setattr(binance_executor, "BinancePublicClient", FakePublicClient)

    real_fill_price, spread_pct = fetch_real_fill("BTCUSDT", "buy", 2.0)

    assert real_fill_price is None
    assert spread_pct is None


def test_place_market_buy_shadow_logs_real_fill_and_metadata(monkeypatch) -> None:
    book = {
        "bids": [["99.0", "10.0"]],
        "asks": [["100.0", "1.0"], ["101.0", "10.0"]],
    }
    persisted = []

    class FakePublicClient:
        def get_order_book(self, symbol):
            return book

    monkeypatch.setattr(binance_executor, "BinancePublicClient", FakePublicClient)
    monkeypatch.setattr(
        binance_executor, "persist_shadow_trade", lambda trade: persisted.append(trade)
    )
    monkeypatch.setattr(binance_executor, "SHADOW_MODE_ENABLED", True)
    monkeypatch.setattr(binance_executor, "LIVE_TRADING_ENABLED", False)

    executor = BinanceExecutor()
    shadow = executor.place_market_buy(
        "BTCUSDT", 2.0, price=95.0, metadata={"paper_trade_id": "abc"}
    )

    assert shadow["price"] == 100.5
    assert shadow["metadata"]["signal_price"] == 95.0
    assert shadow["metadata"]["real_fill_price"] == 100.5
    assert shadow["metadata"]["order_book_spread_pct"] == pytest.approx(1.0)
    assert shadow["metadata"]["paper_trade_id"] == "abc"
    assert persisted == [shadow]


def test_place_market_sell_shadow_falls_back_to_signal_price_when_book_fetch_fails(
    monkeypatch,
) -> None:
    class FakePublicClient:
        def get_order_book(self, symbol):
            raise RuntimeError("network down")

    monkeypatch.setattr(binance_executor, "BinancePublicClient", FakePublicClient)
    monkeypatch.setattr(binance_executor, "persist_shadow_trade", lambda trade: None)
    monkeypatch.setattr(binance_executor, "SHADOW_MODE_ENABLED", True)
    monkeypatch.setattr(binance_executor, "LIVE_TRADING_ENABLED", False)

    executor = BinanceExecutor()
    shadow = executor.place_market_sell("BTCUSDT", 2.0, price=95.0, metadata=None)

    assert shadow["price"] == 95.0
    assert shadow["metadata"]["signal_price"] == 95.0
    assert shadow["metadata"]["real_fill_price"] is None
