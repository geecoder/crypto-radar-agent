"""Tests for Supabase row-to-dict mapping helpers."""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

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


class MissingTableError(Exception):
    """Small exception double for missing-table health-check tests."""


class HealthCursor:
    """Cursor double for persistence health-check queries."""

    def __init__(self, connection) -> None:
        self.connection = connection
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def execute(self, query: str, params=None) -> None:
        self.connection.queries.append(query)
        self.connection.params.append(params)
        normalized_query = " ".join(query.lower().split())
        table_name = params[0] if params else None

        if "from scan_runs" in normalized_query:
            raise MissingTableError('relation "scan_runs" does not exist')

        if "from paper_trade_decisions" in normalized_query:
            raise MissingTableError(
                'relation "paper_trade_decisions" does not exist'
            )

        if "information_schema.columns" in normalized_query:
            if table_name == "alert_history":
                self.rows = [{"column_name": "created_at"}]
            else:
                self.rows = []
            return

        if "count(*)" in normalized_query:
            self.rows = [{"record_count": 2}]
            return

        if "from alert_history" in normalized_query:
            self.rows = [
                {
                    "id": "alert-1",
                    "symbol": "BTCUSDT",
                    "created_at": datetime(2026, 5, 27, tzinfo=timezone.utc),
                }
            ]
            return

        self.rows = []

    def fetchone(self):
        if not self.rows:
            return None

        return self.rows[0]

    def fetchall(self):
        return self.rows


class HealthConnection:
    """Connection double for persistence health-check queries."""

    def __init__(self) -> None:
        self.queries = []
        self.params = []
        self.closed = False
        self.rollback_count = 0

    def cursor(self, cursor_factory=None):
        return HealthCursor(self)

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.closed = True


def test_validate_supabase_database_url_rejects_missing() -> None:
    with pytest.raises(RuntimeError) as error:
        supabase_store._validate_supabase_database_url("")

    assert str(error.value) == supabase_store.INVALID_SUPABASE_DATABASE_URL_MESSAGE


def test_validate_supabase_database_url_rejects_invalid_non_uri() -> None:
    with pytest.raises(RuntimeError) as error:
        supabase_store._validate_supabase_database_url("***")

    assert str(error.value) == supabase_store.INVALID_SUPABASE_DATABASE_URL_MESSAGE
    assert "***" not in str(error.value)


def test_validate_supabase_database_url_rejects_key_value_secret() -> None:
    with pytest.raises(RuntimeError) as error:
        supabase_store._validate_supabase_database_url(
            "SUPABASE_DATABASE_URL=postgresql://user:password@example/db"
        )

    assert str(error.value) == supabase_store.INVALID_SUPABASE_DATABASE_URL_MESSAGE
    assert "password" not in str(error.value)


def test_validate_supabase_database_url_rejects_quoted_values() -> None:
    for value in (
        '"postgresql://user:password@example/db"',
        "'postgres://user:password@example/db'",
    ):
        with pytest.raises(RuntimeError) as error:
            supabase_store._validate_supabase_database_url(value)

        assert str(error.value) == supabase_store.INVALID_SUPABASE_DATABASE_URL_MESSAGE
        assert "password" not in str(error.value)


def test_validate_supabase_database_url_accepts_postgres_uris() -> None:
    supabase_store._validate_supabase_database_url(
        "postgresql://user:password@example/db"
    )
    supabase_store._validate_supabase_database_url(
        "postgres://user:password@example/db"
    )


def test_get_connection_validates_before_psycopg_connect(monkeypatch) -> None:
    connect_calls = []

    class FakePsycopg:
        @staticmethod
        def connect(database_url):
            connect_calls.append(database_url)
            raise AssertionError("connect should not be called for invalid DSN")

    monkeypatch.setattr(supabase_store, "SUPABASE_DATABASE_URL", "***")
    monkeypatch.setattr(supabase_store, "psycopg2", FakePsycopg)

    with pytest.raises(RuntimeError) as error:
        supabase_store.get_connection()

    assert str(error.value) == supabase_store.INVALID_SUPABASE_DATABASE_URL_MESSAGE
    assert connect_calls == []


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


def test_insert_alert_history_writes_stage37_columns(monkeypatch) -> None:
    fake_connection = FakeConnection([])

    monkeypatch.setattr(supabase_store, "get_connection", lambda: fake_connection)

    supabase_store.insert_alert_history(
        {
            "id": "alert-history-1",
            "symbol": "BTCUSDT",
            "alert_type": "Continuation Alert",
            "recent_price_changes": {"change_1h_pct": 2},
            "volume_acceleration": {"volume_acceleration_1h_ratio": 1.4},
            "trade_plan": {"trade_plan_type": "standard_continuation"},
            "trade_plan_type": "standard_continuation",
            "should_paper_trade": True,
            "scan_run_id": "scan-1",
            "source": "scanner",
        }
    )

    query = fake_connection.queries[0]
    params = fake_connection.params[0]

    assert "alert_type" in query
    assert "recent_price_changes" in query
    assert "volume_acceleration" in query
    assert "trade_plan" in query
    assert "trade_plan_type" in query
    assert "should_paper_trade" in query
    assert "scan_run_id" in query
    assert "Continuation Alert" in params
    assert "standard_continuation" in params
    assert "scan-1" in params
    assert fake_connection.closed is True


def test_insert_paper_trade_writes_alert_history_link(monkeypatch) -> None:
    fake_connection = FakeConnection([])

    monkeypatch.setattr(supabase_store, "get_connection", lambda: fake_connection)

    supabase_store.insert_paper_trade(
        {
            "id": "paper-1",
            "alert_id": "alert-history-1",
            "alert_history_id": "alert-history-1",
            "source_alert_id": "source-alert-1",
            "strategy_name": "default_momentum_continuation",
            "symbol": "BTCUSDT",
        }
    )

    query = fake_connection.queries[0]
    params = fake_connection.params[0]

    assert "alert_history_id" in query
    assert "source_alert_id" in query
    assert "alert-history-1" in params
    assert "source-alert-1" in params
    assert fake_connection.closed is True


def test_format_persistence_health_check_does_not_expose_secrets(monkeypatch) -> None:
    secret_url = "postgres://user:secret@example.supabase.co/db"
    monkeypatch.setattr(supabase_store, "SUPABASE_DATABASE_URL", secret_url)

    formatted = supabase_store.format_persistence_health_check(
        {
            "backend": "supabase",
            "supabase_url_configured": True,
            "connection_ok": True,
            "counts": {
                "alert_history": 1,
                "paper_trades": 0,
                "alert_outcomes": 0,
                "scan_runs": None,
                "paper_trade_decisions": None,
            },
            "latest_alert_history": [
                {
                    "id": "alert-1",
                    "symbol": "BTCUSDT",
                    "alert_type": "Continuation Alert",
                    "SUPABASE_DATABASE_URL": secret_url,
                }
            ],
            "latest_scan_runs": [],
            "latest_paper_trade_decisions": [],
            "warnings": [f"Connection retried with {secret_url}"],
        }
    )

    assert secret_url not in formatted
    assert "[REDACTED]" in formatted
    assert "BTCUSDT" in formatted


def test_persistence_health_check_reports_missing_stage37_tables(
    monkeypatch,
) -> None:
    fake_connection = HealthConnection()

    monkeypatch.setattr(supabase_store, "PERSISTENCE_BACKEND", "supabase")
    monkeypatch.setattr(supabase_store, "SUPABASE_DATABASE_URL", "postgres://secret")
    monkeypatch.setattr(supabase_store, "get_connection", lambda: fake_connection)

    report = supabase_store.persistence_health_check()

    assert report["backend"] == "supabase"
    assert report["supabase_url_configured"] is True
    assert report["connection_ok"] is True
    assert report["counts"]["alert_history"] == 2
    assert report["counts"]["scan_runs"] is None
    assert report["counts"]["paper_trade_decisions"] is None
    assert report["latest_alert_history"][0]["symbol"] == "BTCUSDT"
    assert (
        "Table missing: scan_runs. Run the Stage 37 Supabase SQL migration."
        in report["warnings"]
    )
    assert (
        "Table missing: paper_trade_decisions. Run the Stage 37 Supabase SQL migration."
        in report["warnings"]
    )
    assert fake_connection.rollback_count >= 2
    assert fake_connection.closed is True


def test_persistence_health_check_handles_connection_failure_gracefully(
    monkeypatch,
) -> None:
    secret_url = "postgres://user:secret@example.supabase.co/db"

    monkeypatch.setattr(supabase_store, "PERSISTENCE_BACKEND", "supabase")
    monkeypatch.setattr(supabase_store, "SUPABASE_DATABASE_URL", secret_url)

    def fail_connection():
        raise RuntimeError(f"could not connect to {secret_url}")

    monkeypatch.setattr(supabase_store, "get_connection", fail_connection)

    report = supabase_store.persistence_health_check()
    formatted = supabase_store.format_persistence_health_check(report)

    assert report["connection_ok"] is False
    assert report["counts"]["alert_history"] is None
    assert any("Supabase connection failed" in warning for warning in report["warnings"])
    assert secret_url not in formatted
    assert "[REDACTED]" in formatted


def test_health_check_formatter_uses_concise_rows() -> None:
    formatted = supabase_store.format_persistence_health_check(
        {
            "backend": "supabase",
            "supabase_url_configured": True,
            "connection_ok": True,
            "counts": {
                "alert_history": 1,
                "paper_trades": 1,
                "alert_outcomes": 0,
                "scan_runs": 1,
                "paper_trade_decisions": 1,
            },
            "latest_alert_history": [
                {
                    "created_at": "2026-05-27T12:00:00+00:00",
                    "symbol": "BTCUSDT",
                    "alert_type": "Continuation Alert",
                    "opportunity_score": 72,
                    "telegram_sent": True,
                    "paper_trade_created": False,
                    "paper_trade_skip_reason": "Score too low",
                    "scan_run_id": "scan-1",
                    "trade_plan": {"large": "json"},
                }
            ],
            "latest_scan_runs": [
                {
                    "started_at": "2026-05-27T12:00:00+00:00",
                    "status": "completed",
                    "total_scan_universe": 150,
                    "total_alert_candidates": 3,
                    "total_paper_trades_created": 1,
                    "total_paper_trades_skipped": 2,
                }
            ],
            "latest_paper_trade_decisions": [
                {
                    "created_at": "2026-05-27T12:01:00+00:00",
                    "symbol": "BTCUSDT",
                    "alert_type": "Continuation Alert",
                    "decision": "skipped",
                    "eligible": False,
                    "reason": "Score too low",
                }
            ],
            "warnings": [],
        }
    )

    assert "BTCUSDT | Continuation Alert | score=72" in formatted
    assert "status=completed | universe=150 | alerts=3" in formatted
    assert "decision=skipped | eligible=false | reason=Score too low" in formatted
    assert "trade_plan" not in formatted
    assert '{"large": "json"}' not in formatted


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
