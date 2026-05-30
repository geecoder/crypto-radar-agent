"""Tests for stale paper trade repair behavior."""

from datetime import datetime, timedelta, timezone

import pandas as pd

from app.trading import paper_trading


def _open_trade(
    trade_id: str,
    symbol: str,
    opened_at: datetime,
    max_hold_hours: int | None = 1,
) -> dict:
    trade = {
        "id": trade_id,
        "symbol": symbol,
        "opened_at": opened_at.isoformat(),
        "entry_price": 100.0,
        "status": "open",
        "direction": "long",
        "stop_loss_pct": -5,
        "take_profit_1_pct": 8,
        "take_profit_2_pct": 15,
        "take_profit_3_pct": 20,
        "simulated_position_size": 25,
    }

    if max_hold_hours is not None:
        trade["max_hold_hours"] = max_hold_hours

    return trade


def _patch_market_data(monkeypatch, latest_close_by_symbol: dict[str, float]) -> None:
    def fake_klines_to_dataframe(klines):
        symbol = klines[0]["symbol"]
        latest_time = datetime.now(timezone.utc)
        latest_close = latest_close_by_symbol[symbol]

        return pd.DataFrame(
            [
                {
                    "open_time": latest_time,
                    "open": latest_close,
                    "high": latest_close,
                    "low": latest_close,
                    "close": latest_close,
                    "volume": 1.0,
                }
            ]
        )

    monkeypatch.setattr(paper_trading, "klines_to_dataframe", fake_klines_to_dataframe)


class FakeClient:
    def get_klines(self, symbol: str, interval: str, limit: int):
        return [{"symbol": symbol}]


def test_open_trade_older_than_max_hold_closes_with_max_hold_expired(
    monkeypatch,
) -> None:
    trade = _open_trade(
        "paper-stale",
        "STALEUSDT",
        datetime.now(timezone.utc) - timedelta(hours=2),
        max_hold_hours=1,
    )
    updates = []
    events = []

    monkeypatch.setattr(paper_trading, "_get_open_paper_trades", lambda: [trade])
    monkeypatch.setattr(
        paper_trading,
        "_update_paper_trade",
        lambda trade_id, update: updates.append((trade_id, update)),
    )
    monkeypatch.setattr(paper_trading, "_insert_paper_trade_event", events.append)
    _patch_market_data(monkeypatch, {"STALEUSDT": 110.0})

    summary = paper_trading.update_open_paper_trades(FakeClient())

    assert summary["closed_max_hold"] == 1
    assert updates[0][1]["status"] == "closed"
    assert updates[0][1]["exit_reason"] == "max_hold_expired"
    assert updates[0][1]["exit_price"] == 110.0
    assert updates[0][1]["pnl_pct"] == 10.0
    assert updates[0][1]["pnl_amount"] == 2.5
    assert events[0]["type"] == "max_hold_expired"
    assert (
        events[0]["notes"]
        == "Closed stale paper trade because max_hold_hours was reached."
    )


def test_non_stale_trade_remains_open(monkeypatch) -> None:
    trade = _open_trade(
        "paper-fresh",
        "FRESHUSDT",
        datetime.now(timezone.utc) - timedelta(minutes=30),
        max_hold_hours=1,
    )
    updates = []
    events = []

    monkeypatch.setattr(paper_trading, "_get_open_paper_trades", lambda: [trade])
    monkeypatch.setattr(
        paper_trading,
        "_update_paper_trade",
        lambda trade_id, update: updates.append((trade_id, update)),
    )
    monkeypatch.setattr(paper_trading, "_insert_paper_trade_event", events.append)
    _patch_market_data(monkeypatch, {"FRESHUSDT": 100.0})

    summary = paper_trading.update_open_paper_trades(FakeClient())

    assert summary["still_open"] == 1
    assert summary["closed_max_hold"] == 0
    assert updates == []
    assert events == []


def test_missing_max_hold_hours_defaults_to_48_hours(monkeypatch) -> None:
    trade = _open_trade(
        "paper-default-max-hold",
        "DEFAULTUSDT",
        datetime.now(timezone.utc) - timedelta(hours=49),
        max_hold_hours=None,
    )
    updates = []

    monkeypatch.setattr(paper_trading, "_get_open_paper_trades", lambda: [trade])
    monkeypatch.setattr(
        paper_trading,
        "_update_paper_trade",
        lambda trade_id, update: updates.append((trade_id, update)),
    )
    monkeypatch.setattr(paper_trading, "_insert_paper_trade_event", lambda event: None)
    _patch_market_data(monkeypatch, {"DEFAULTUSDT": 95.0})

    summary = paper_trading.update_open_paper_trades(FakeClient())

    assert summary["closed_max_hold"] == 1
    assert updates[0][1]["exit_reason"] == "max_hold_expired"
    assert updates[0][1]["pnl_pct"] == -5.0
