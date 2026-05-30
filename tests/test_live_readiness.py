"""Tests for paper-trading maturity and readiness gates."""

from datetime import datetime, timedelta, timezone

import pandas as pd

from app.analysis.live_readiness import build_live_readiness_report
from app.trading import paper_trading


def _closed_trade(
    index: int,
    pnl_pct: float,
    strategy_name: str = "default_momentum_continuation",
    exit_reason: str = "take_profit_1",
) -> dict:
    return {
        "id": f"paper-{index}",
        "symbol": f"COIN{index}USDT",
        "status": "closed",
        "strategy_name": strategy_name,
        "opened_at": "2026-05-01T00:00:00+00:00",
        "closed_at": "2026-05-01T02:00:00+00:00",
        "pnl_pct": pnl_pct,
        "pnl_amount": pnl_pct,
        "exit_reason": exit_reason,
    }


def _good_closed_trades(count: int = 100) -> list[dict]:
    return [_closed_trade(index, 2.0) for index in range(count)]


def test_not_ready_when_closed_trades_below_100() -> None:
    report = build_live_readiness_report(
        _good_closed_trades(99),
        [],
        [{"status": "completed"}],
        [],
    )

    assert report["closed_trades"] == 99
    assert report["readiness_status"] == "NOT_READY"


def test_not_ready_when_average_pnl_is_negative() -> None:
    trades = [
        _closed_trade(index, 1.0 if index < 50 else -2.0)
        for index in range(100)
    ]

    report = build_live_readiness_report(trades, [], [{"status": "completed"}], [])

    assert report["average_pnl_pct"] < 0
    assert report["readiness_status"] == "NOT_READY"


def test_not_ready_when_win_rate_below_45_pct() -> None:
    trades = [
        _closed_trade(index, 2.0 if index < 44 else -0.1)
        for index in range(100)
    ]

    report = build_live_readiness_report(trades, [], [{"status": "completed"}], [])

    assert report["average_pnl_pct"] > 0
    assert report["win_rate_pct"] == 44.0
    assert report["readiness_status"] == "NOT_READY"


def test_not_ready_when_stale_open_trades_exist() -> None:
    stale_open_trade = {
        "id": "paper-stale",
        "symbol": "OLDUSDT",
        "status": "open",
        "opened_at": "2026-05-01T00:00:00+00:00",
        "max_hold_hours": 24,
        "entry_price": 100,
    }

    report = build_live_readiness_report(
        [*_good_closed_trades(), stale_open_trade],
        [],
        [{"status": "completed"}],
        [],
    )

    assert report["stale_open_trades"] == 1
    assert report["readiness_status"] == "NOT_READY"


def test_readiness_report_includes_recommendations() -> None:
    report = build_live_readiness_report(
        [_closed_trade(1, -5.0, exit_reason="stop_loss")],
        [],
        [{"status": "failed"}],
        [{"telegram_error": "Telegram send failed"}],
    )

    assert "Collect at least 100 closed paper trades." in report["recommendations"]
    assert "Improve speculative early runner filters." in report["recommendations"]
    assert "Fix failed or stuck scan runs." in report["recommendations"]
    assert "Fix recent Telegram delivery failures." in report["recommendations"]
    assert "Do not enable Binance trading permissions yet." in report["recommendations"]


def test_stale_paper_trades_are_closed_when_max_hold_is_exceeded(
    monkeypatch,
    caplog,
) -> None:
    caplog.set_level("INFO")
    opened_at = datetime.now(timezone.utc) - timedelta(hours=2)
    trade = {
        "id": "paper-stale",
        "symbol": "STALEUSDT",
        "opened_at": opened_at.isoformat(),
        "entry_price": 100.0,
        "status": "open",
        "direction": "long",
        "stop_loss_pct": -5,
        "take_profit_1_pct": 8,
        "take_profit_2_pct": 15,
        "take_profit_3_pct": 20,
        "max_hold_hours": 1,
        "simulated_position_size": 100,
    }
    updates = []
    events = []
    latest_time = datetime.now(timezone.utc)

    monkeypatch.setattr(paper_trading, "_get_open_paper_trades", lambda: [trade])
    monkeypatch.setattr(
        paper_trading,
        "_update_paper_trade",
        lambda trade_id, update: updates.append((trade_id, update)),
    )
    monkeypatch.setattr(paper_trading, "_insert_paper_trade_event", events.append)
    monkeypatch.setattr(
        paper_trading,
        "klines_to_dataframe",
        lambda klines: pd.DataFrame(
            [
                {
                    "open_time": latest_time,
                    "open": 100.0,
                    "high": 90.0,
                    "low": 90.0,
                    "close": 90.0,
                    "volume": 1.0,
                }
            ]
        ),
    )

    class FakeClient:
        def get_klines(self, symbol: str, interval: str, limit: int):
            return []

    summary = paper_trading.update_open_paper_trades(FakeClient())

    assert summary == {
        "open_trades_checked": 1,
        "closed_trades": 1,
        "still_open": 0,
    }
    assert updates[0][0] == "paper-stale"
    assert updates[0][1]["status"] == "closed"
    assert updates[0][1]["exit_reason"] == "max_hold_expired"
    assert updates[0][1]["exit_price"] == 90.0
    assert updates[0][1]["pnl_pct"] == -10.0
    assert events[0]["type"] == "closed"
    assert (
        "Closed stale paper trade due to max hold: STALEUSDT"
        in caplog.text
    )
