"""Tests for Supabase row-to-dict mapping helpers."""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.storage import supabase_store


class FakeCursor:
    """Small cursor double that captures SQL and returns preset rows."""

    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def execute(self, query: str, params=None) -> None:
        self.connection.queries.append(query)
        self.connection.params.append(params)

    def fetchall(self):
        return self.connection.rows


class FakeConnection:
    """Small connection double for Supabase storage tests."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.queries = []
        self.params = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def cursor(self, cursor_factory=None):
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True


def _paper_trade_row() -> dict:
    opened_at = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    updated_at = datetime(2026, 5, 17, 12, 1, tzinfo=timezone.utc)

    return {
        "id": "paper_BTCUSDT_20260517T120000Z",
        "alert_id": "alert-1",
        "strategy_name": "default_momentum_continuation",
        "alert_type": "Continuation Alert",
        "trade_plan_type": "standard_continuation",
        "symbol": "BTCUSDT",
        "opened_at": opened_at,
        "closed_at": None,
        "entry_price": Decimal("100.50"),
        "exit_price": None,
        "status": "open",
        "direction": "long",
        "opportunity_score": 72,
        "classification": "Watchlist",
        "target_bucket": "+20% momentum setup",
        "continuation_target": "+20% continuation watch",
        "move_stage": "Stage 3 - Confirmed early momentum",
        "move_from_recent_low_pct": Decimal("8.5"),
        "liquidity_label": "Strong",
        "exhaustion_risk_level": "Medium",
        "stop_loss_pct": Decimal("-5"),
        "take_profit_1_pct": Decimal("8"),
        "take_profit_2_pct": Decimal("15"),
        "take_profit_3_pct": Decimal("20"),
        "max_hold_hours": 48,
        "simulated_position_size": Decimal("100"),
        "pnl_pct": None,
        "pnl_amount": None,
        "exit_reason": None,
        "created_at": opened_at,
        "updated_at": updated_at,
    }


def test_alert_history_row_maps_to_app_record_shape() -> None:
    alerted_at = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    created_at = datetime(2026, 5, 14, 12, 1, tzinfo=timezone.utc)

    record = supabase_store._alert_history_row_to_record(
        {
            "id": "BTCUSDT-2026-05-14T12:00:00+00:00",
            "symbol": "BTCUSDT",
            "alerted_at": alerted_at,
            "latest_close": Decimal("100.25"),
            "opportunity_score": 72,
            "classification": "Watchlist",
            "target_bucket": "+20% momentum setup",
            "risk_level": "Medium",
            "summary": "Watchlist. Some signals are improving.",
            "component_scores": {"volume": 80},
            "volume_signal": {"score": 80},
            "momentum_signal": {"score": 70},
            "breakout_signal": {"score": 65},
            "trend_signal": {"score": 75},
            "volatility_signal": {"score": 60},
            "telegram_sent": True,
            "created_at": created_at,
        }
    )

    assert record["id"] == "BTCUSDT-2026-05-14T12:00:00+00:00"
    assert record["alerted_at"] == alerted_at.isoformat()
    assert record["latest_close"] == 100.25
    assert record["component_scores"] == {"volume": 80}
    assert record["telegram_sent"] is True
    assert record["created_at"] == created_at.isoformat()


def test_alert_outcome_row_maps_to_app_record_shape() -> None:
    checked_at = datetime(2026, 5, 14, 13, 0, tzinfo=timezone.utc)

    record = supabase_store._alert_outcome_row_to_record(
        {
            "alert_id": "BTCUSDT-2026-05-14T12:00:00+00:00",
            "symbol": "BTCUSDT",
            "alerted_at": "2026-05-14T12:00:00+00:00",
            "entry_price": Decimal("100"),
            "opportunity_score": 72,
            "classification": "Watchlist",
            "target_bucket": "+20% momentum setup",
            "risk_level": "Medium",
            "checkpoints": {"+5%": True},
            "max_high_after_alert": Decimal("121"),
            "max_upside_pct": Decimal("21"),
            "min_low_after_alert": Decimal("98"),
            "max_drawdown_pct": Decimal("-2"),
            "hit_5_pct": True,
            "hit_10_pct": True,
            "hit_20_pct": True,
            "hit_50_pct": False,
            "hit_100_pct": False,
            "last_checked_at": checked_at,
            "updated_at": checked_at,
        }
    )

    assert record["alert_id"] == "BTCUSDT-2026-05-14T12:00:00+00:00"
    assert record["checked_at"] == checked_at.isoformat()
    assert record["alert_latest_close"] == 100.0
    assert record["highest_price"] == 121.0
    assert record["highest_return_pct"] == 21.0
    assert record["hit_5pct"] is True
    assert record["hit_5_pct"] is True
    assert record["hit_50pct"] is False


def test_get_open_paper_trades_maps_structured_columns(monkeypatch) -> None:
    fake_connection = FakeConnection([_paper_trade_row()])

    monkeypatch.setattr(supabase_store, "get_connection", lambda: fake_connection)

    trades = supabase_store.get_open_paper_trades()

    query = fake_connection.queries[0]
    trade = trades[0]

    assert "FROM paper_trades" in query
    assert "WHERE status = %s" in query
    assert "record" not in query.lower()
    assert fake_connection.params == [("open",)]
    assert fake_connection.closed is True
    assert trade["id"] == "paper_BTCUSDT_20260517T120000Z"
    assert trade["strategy_name"] == "default_momentum_continuation"
    assert trade["alert_type"] == "Continuation Alert"
    assert trade["trade_plan_type"] == "standard_continuation"
    assert trade["opened_at"] == "2026-05-17T12:00:00+00:00"
    assert trade["entry_price"] == 100.5
    assert trade["move_from_recent_low_pct"] == 8.5
    assert trade["stop_loss_pct"] == -5.0
    assert trade["take_profit_3_pct"] == 20.0
    assert trade["simulated_position_size"] == 100.0
    assert trade["max_hold_hours"] == 48


def test_load_paper_trades_maps_structured_columns_and_limit(monkeypatch) -> None:
    fake_connection = FakeConnection([_paper_trade_row()])

    monkeypatch.setattr(supabase_store, "get_connection", lambda: fake_connection)

    trades = supabase_store.load_paper_trades(limit=5)

    query = fake_connection.queries[0]

    assert "FROM paper_trades" in query
    assert "ORDER BY opened_at DESC" in query
    assert "LIMIT %s" in query
    assert "record" not in query.lower()
    assert fake_connection.params == [(5,)]
    assert trades[0]["symbol"] == "BTCUSDT"
    assert trades[0]["created_at"] == "2026-05-17T12:00:00+00:00"
    assert trades[0]["updated_at"] == "2026-05-17T12:01:00+00:00"


def test_supabase_store_does_not_select_record_column() -> None:
    source = Path(supabase_store.__file__).read_text(encoding="utf-8")

    assert "SELECT record" not in source
    assert "SELECT alert_id, record" not in source
    assert "record" not in _paper_trade_selects(source)


def _paper_trade_selects(source: str) -> str:
    """Return SELECT statements that query paper_trades."""
    statements = []

    for statement in source.split("cursor.execute("):
        if "FROM paper_trades" in statement:
            statements.append(statement.split('"""', 2)[1])

    return "\n".join(statements).lower()
