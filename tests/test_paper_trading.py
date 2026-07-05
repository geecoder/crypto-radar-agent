"""Tests for the simulated paper trading engine."""

import json
from datetime import datetime, timedelta, timezone

import pandas as pd

from app.trading import paper_trading
from app.trading.paper_trading import (
    build_paper_trade_from_alert,
    evaluate_open_paper_trade,
    should_create_paper_trade,
)


def _eligible_alert() -> dict:
    """Return a scan result eligible for paper trading."""
    return {
        "id": "alert-1",
        "symbol": "BTCUSDT",
        "latest_close": 100.0,
        "opportunity": {
            "opportunity_score": 72,
            "classification": "Watchlist",
            "target_bucket": "+20% momentum setup",
        },
        "continuation_target": {
            "target_bucket": "+20% continuation watch",
        },
        "move_stage_signal": {
            "stage": "Stage 3 - Confirmed early momentum",
            "move_from_recent_low_pct": 8.5,
        },
        "liquidity_signal": {
            "label": "Strong",
        },
        "tradability_signal": {
            "score": 80,
        },
        "exhaustion_signal": {
            "risk_level": "Medium",
        },
    }


def _open_trade(opened_at: datetime) -> dict:
    """Return a basic open paper trade."""
    return {
        "id": "paper_BTCUSDT_test",
        "symbol": "BTCUSDT",
        "opened_at": opened_at.isoformat(),
        "entry_price": 100.0,
        "status": "open",
        "direction": "long",
        "stop_loss_pct": -5,
        "take_profit_1_pct": 8,
        "take_profit_2_pct": 15,
        "take_profit_3_pct": 20,
        "max_hold_hours": 48,
        "simulated_position_size": 100,
    }


def _candles(opened_at: datetime, rows: list[dict]) -> pd.DataFrame:
    """Build a candle DataFrame relative to the opened time."""
    return pd.DataFrame(
        [
            {
                "open_time": opened_at + timedelta(hours=row["hours_after_open"]),
                "open": row.get("open", 100.0),
                "high": row.get("high", 100.0),
                "low": row.get("low", 100.0),
                "close": row.get("close", 100.0),
                "volume": row.get("volume", 1.0),
            }
            for row in rows
        ]
    )


def test_should_create_paper_trade_true_case() -> None:
    should_create, reason = should_create_paper_trade(_eligible_alert())

    assert should_create is True
    assert reason == "Paper trade eligible."


def test_should_create_paper_trade_rejects_low_score() -> None:
    alert = _eligible_alert()
    alert["opportunity"]["opportunity_score"] = 54  # below default min of 55

    should_create, reason = should_create_paper_trade(alert)

    assert should_create is False
    assert "below 55" in reason


def test_should_create_paper_trade_rejects_very_thin_liquidity() -> None:
    from app.trading.strategy_config import get_conservative_paper_trading_strategy

    alert = _eligible_alert()
    alert["liquidity_signal"]["label"] = "Very thin"
    alert["opportunity"]["opportunity_score"] = 80  # meets conservative min of 75

    # Conservative strategy has allow_thin_liquidity=False → rejects "Very thin"
    should_create, reason = should_create_paper_trade(alert, strategy=get_conservative_paper_trading_strategy())

    assert should_create is False
    assert "Very thin" in reason


def test_should_create_paper_trade_rejects_high_exhaustion() -> None:
    alert = _eligible_alert()
    alert["exhaustion_signal"]["risk_level"] = "High"

    should_create, reason = should_create_paper_trade(alert)

    assert should_create is False
    assert "High" in reason


def test_build_paper_trade_from_alert() -> None:
    trade = build_paper_trade_from_alert(_eligible_alert())

    assert trade["id"].startswith("paper_BTCUSDT_")
    assert trade["alert_id"] == "alert-1"
    assert trade["strategy_name"] == "default_momentum_continuation"
    assert trade["symbol"] == "BTCUSDT"
    assert trade["alert_type"] == "Continuation Alert"
    assert trade["entry_price"] == 100.0
    assert trade["status"] == "open"
    assert trade["direction"] == "long"
    assert trade["opportunity_score"] == 72
    assert trade["classification"] == "Watchlist"
    assert trade["target_bucket"] == "+20% momentum setup"
    assert trade["continuation_target"] == "+20% continuation watch"
    assert trade["move_stage"] == "Stage 3 - Confirmed early momentum"
    assert trade["move_from_recent_low_pct"] == 8.5
    assert trade["liquidity_label"] == "Strong"
    assert trade["exhaustion_risk_level"] == "Medium"
    assert trade["stop_loss_pct"] == -10
    assert trade["take_profit_1_pct"] == 8
    assert trade["take_profit_2_pct"] == 15
    assert trade["take_profit_3_pct"] == 20
    # score=72 >= high_score_threshold=60 → gets extended 48h hold
    assert trade["max_hold_hours"] == 48
    assert trade["simulated_position_size"] == 50


def test_build_paper_trade_uses_trade_plan_risk_targets() -> None:
    alert = _eligible_alert()
    alert["trade_plan"] = {
        "should_paper_trade": True,
        "stop_loss_pct": -6,
        "take_profit_1_pct": 10,
        "take_profit_2_pct": 20,
        "take_profit_3_pct": 35,
        "max_hold_hours": 72,
    }

    trade = build_paper_trade_from_alert(alert)

    assert trade["stop_loss_pct"] == -6
    assert trade["take_profit_1_pct"] == 10
    assert trade["take_profit_2_pct"] == 20
    assert trade["take_profit_3_pct"] == 35
    assert trade["max_hold_hours"] == 72


def test_should_create_paper_trade_allows_when_trade_plan_absent() -> None:
    alert = _eligible_alert()
    alert.pop("trade_plan", None)

    should_create, reason = should_create_paper_trade(alert)

    # Trade plan is not required — eligibility is based on score, move %, etc.
    assert should_create is True


def test_create_paper_trades_from_alerts_saves_json_fallback(
    monkeypatch,
    tmp_path,
) -> None:
    trades_file = tmp_path / "paper_trades.json"
    events_file = tmp_path / "paper_trade_events.json"

    monkeypatch.setattr(paper_trading, "USE_SUPABASE", False)
    monkeypatch.setattr(paper_trading, "PAPER_TRADES_FILE", str(trades_file))
    monkeypatch.setattr(paper_trading, "PAPER_TRADE_EVENTS_FILE", str(events_file))

    decisions = paper_trading.create_paper_trades_from_alerts([_eligible_alert()])

    saved_trades = json.loads(trades_file.read_text(encoding="utf-8"))
    saved_events = json.loads(events_file.read_text(encoding="utf-8"))

    assert len(decisions) == 1
    assert decisions[0]["decision"] == "created"
    assert decisions[0]["paper_trade_created"] is True
    assert saved_trades[0]["id"] == decisions[0]["paper_trade_id"]
    assert saved_events[0]["trade_id"] == decisions[0]["paper_trade_id"]
    assert saved_events[0]["type"] == "opened"


def test_create_paper_trades_persists_created_and_skipped_decisions(
    monkeypatch,
) -> None:
    inserted_trades = []
    inserted_events = []
    inserted_decisions = []
    updated_alerts = []
    eligible = {
        **_eligible_alert(),
        "alert_history_id": "alert-history-1",
        "source_alert_id": "source-alert-1",
    }
    rejected = {
        **_eligible_alert(),
        "id": "source-alert-2",
        "alert_history_id": "alert-history-2",
    }
    rejected["opportunity"] = {
        **rejected["opportunity"],
        "opportunity_score": 10,
    }

    monkeypatch.setattr(paper_trading, "USE_SUPABASE", True)
    monkeypatch.setattr(paper_trading, "_get_open_paper_trades", lambda: [])
    monkeypatch.setattr(
        paper_trading.supabase_store,
        "insert_paper_trade",
        inserted_trades.append,
    )
    monkeypatch.setattr(
        paper_trading.supabase_store,
        "insert_paper_trade_event",
        inserted_events.append,
    )
    monkeypatch.setattr(
        paper_trading.supabase_store,
        "insert_paper_trade_decision",
        inserted_decisions.append,
    )
    monkeypatch.setattr(
        paper_trading.supabase_store,
        "update_alert_paper_trade_status",
        lambda alert_id, created, paper_trade_id, skip_reason: updated_alerts.append(
            (alert_id, created, paper_trade_id, skip_reason)
        ),
    )

    decisions = paper_trading.create_paper_trades_from_alerts([eligible, rejected])

    assert [decision["decision"] for decision in decisions] == [
        "created",
        "ineligible",
    ]
    assert len(inserted_trades) == 1
    assert inserted_trades[0]["alert_history_id"] == "alert-history-1"
    assert inserted_trades[0]["source_alert_id"] == "source-alert-1"
    assert len(inserted_events) == 1
    assert len(inserted_decisions) == 2
    assert inserted_decisions[0]["decision"] == "created"
    assert inserted_decisions[0]["paper_trade_id"] == inserted_trades[0]["id"]
    assert inserted_decisions[1]["decision"] == "ineligible"
    assert updated_alerts[0] == (
        "alert-history-1",
        True,
        inserted_trades[0]["id"],
        None,
    )
    assert updated_alerts[1][0] == "alert-history-2"
    assert updated_alerts[1][1] is False
    assert "below 55" in updated_alerts[1][3]


def test_create_paper_trades_blocks_thin_liquidity_despite_strategy_allowance(
    monkeypatch,
    tmp_path,
) -> None:
    """PAPER_MIN_LIQUIDITY is a hard floor that overrides allow_thin_liquidity."""
    trades_file = tmp_path / "paper_trades.json"
    events_file = tmp_path / "paper_trade_events.json"
    alert = _eligible_alert()
    alert["liquidity_signal"] = {"label": "Thin"}

    monkeypatch.setattr(paper_trading, "USE_SUPABASE", False)
    monkeypatch.setattr(paper_trading, "PAPER_TRADES_FILE", str(trades_file))
    monkeypatch.setattr(paper_trading, "PAPER_TRADE_EVENTS_FILE", str(events_file))

    decisions = paper_trading.create_paper_trades_from_alerts([alert])

    assert decisions[0]["decision"] == "ineligible"
    assert decisions[0]["paper_trade_created"] is False
    assert "PAPER_MIN_LIQUIDITY" in decisions[0]["reason"]


def test_create_paper_trades_blocks_low_tradability_score(
    monkeypatch,
    tmp_path,
) -> None:
    trades_file = tmp_path / "paper_trades.json"
    events_file = tmp_path / "paper_trade_events.json"
    alert = _eligible_alert()
    alert["tradability_signal"] = {"score": 10}

    monkeypatch.setattr(paper_trading, "USE_SUPABASE", False)
    monkeypatch.setattr(paper_trading, "PAPER_TRADES_FILE", str(trades_file))
    monkeypatch.setattr(paper_trading, "PAPER_TRADE_EVENTS_FILE", str(events_file))

    decisions = paper_trading.create_paper_trades_from_alerts([alert])

    assert decisions[0]["decision"] == "ineligible"
    assert decisions[0]["paper_trade_created"] is False
    assert "PAPER_MIN_TRADABILITY_SCORE" in decisions[0]["reason"]


def test_create_paper_trades_logs_shadow_trade_on_open(
    monkeypatch,
    tmp_path,
) -> None:
    trades_file = tmp_path / "paper_trades.json"
    events_file = tmp_path / "paper_trade_events.json"
    shadow_calls = []

    class FakeExecutor:
        def place_market_buy(self, symbol, quantity, price=None, metadata=None):
            shadow_calls.append((symbol, quantity, price, metadata))
            return {}

    monkeypatch.setattr(paper_trading, "USE_SUPABASE", False)
    monkeypatch.setattr(paper_trading, "PAPER_TRADES_FILE", str(trades_file))
    monkeypatch.setattr(paper_trading, "PAPER_TRADE_EVENTS_FILE", str(events_file))
    monkeypatch.setattr(paper_trading, "BinanceExecutor", FakeExecutor)

    paper_trading.create_paper_trades_from_alerts([_eligible_alert()])

    assert len(shadow_calls) == 1
    symbol, quantity, price, metadata = shadow_calls[0]
    assert symbol == "BTCUSDT"
    assert price == 100.0
    assert quantity == 50 / 100.0
    assert metadata["liquidity_label"] == "Strong"


def test_evaluate_open_paper_trade_stop_loss() -> None:
    opened_at = datetime(2026, 5, 17, tzinfo=timezone.utc)
    updates = evaluate_open_paper_trade(
        _open_trade(opened_at),
        _candles(
            opened_at,
            [
                {
                    "hours_after_open": 1,
                    "high": 103.0,
                    "low": 94.0,
                    "close": 96.0,
                },
            ],
        ),
    )

    assert updates["status"] == "closed"
    assert updates["exit_reason"] == "stop_loss"
    assert updates["exit_price"] == 95.0
    assert updates["pnl_pct"] == -5.0
    assert updates["pnl_amount"] == -5.0
    # No liquidity_label on the fixture -> worst-case default slippage (1.5%).
    assert updates["gross_pnl_pct"] == -5.0
    assert updates["net_pnl_pct"] == -6.7
    assert updates["net_pnl_amount"] == -6.7


def test_evaluate_open_paper_trade_take_profit() -> None:
    opened_at = datetime(2026, 5, 17, tzinfo=timezone.utc)
    updates = evaluate_open_paper_trade(
        _open_trade(opened_at),
        _candles(
            opened_at,
            [
                {
                    "hours_after_open": 1,
                    "high": 121.0,
                    "low": 99.0,
                    "close": 118.0,
                },
            ],
        ),
    )

    assert updates["status"] == "closed"
    assert updates["exit_reason"] == "take_profit_3"
    assert updates["exit_price"] == 120.0
    # Blended P&L: 50% × 8% (TP1) + 30% × 15% (TP2) + 20% × 20% (TP3) = 12.5%
    assert updates["pnl_pct"] == 12.5
    assert updates["pnl_amount"] == 12.5   # position_size=100 × 12.5%
    assert updates["partial_tp1_hit"] is True
    assert updates["partial_tp2_hit"] is True
    assert updates["blended_pnl_pct"] == 12.5
    assert updates["gross_pnl_pct"] == 12.5
    assert updates["net_pnl_pct"] == 10.8
    assert updates["net_pnl_amount"] == 10.8


def test_evaluate_open_paper_trade_max_hold_expiry() -> None:
    opened_at = datetime(2026, 5, 17, tzinfo=timezone.utc)
    updates = evaluate_open_paper_trade(
        _open_trade(opened_at),
        _candles(
            opened_at,
            [
                {
                    "hours_after_open": 49,
                    "high": 104.0,
                    "low": 98.0,
                    "close": 103.0,
                },
            ],
        ),
    )

    assert updates["status"] == "closed"
    assert updates["exit_reason"] == "max_hold_expired"
    assert updates["exit_price"] == 103.0
    assert updates["pnl_pct"] == 3.0
    assert updates["pnl_amount"] == 3.0
    assert updates["gross_pnl_pct"] == 3.0
    assert updates["net_pnl_pct"] == 1.3
    assert updates["net_pnl_amount"] == 1.3


def test_evaluate_open_paper_trade_net_pnl_scales_with_liquidity() -> None:
    """Net P&L subtracts fees + liquidity-scaled slippage (Good=0.3%, Thin=0.8%)."""
    opened_at = datetime(2026, 5, 17, tzinfo=timezone.utc)
    trade = _open_trade(opened_at)
    trade["liquidity_label"] = "Good"

    updates = evaluate_open_paper_trade(
        trade,
        _candles(
            opened_at,
            [{"hours_after_open": 1, "high": 103.0, "low": 94.0, "close": 96.0}],
        ),
    )

    assert updates["gross_pnl_pct"] == -5.0
    # Good liquidity: -5.0 - 0.2 (fee) - 0.3 (slippage) = -5.5
    assert updates["net_pnl_pct"] == -5.5
