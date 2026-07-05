"""Supabase Postgres persistence helpers."""

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from typing import Any
from uuid import uuid4

try:
    import psycopg2
    from psycopg2.extras import Json, RealDictCursor
except ModuleNotFoundError:
    psycopg2 = None
    Json = None
    RealDictCursor = None

from app.config import PERSISTENCE_BACKEND, SUPABASE_DATABASE_URL

HEALTH_CHECK_TABLES = (
    "alert_history",
    "paper_trades",
    "alert_outcomes",
    "scan_runs",
    "paper_trade_decisions",
)
HEALTH_CHECK_LATEST_TABLES = (
    "alert_history",
    "scan_runs",
    "paper_trade_decisions",
)
HEALTH_CHECK_ORDER_COLUMNS = (
    "created_at",
    "started_at",
    "alerted_at",
    "decided_at",
    "updated_at",
    "id",
)
SENSITIVE_KEY_PARTS = (
    "secret",
    "token",
    "password",
    "api_key",
    "apikey",
    "database_url",
    "supabase_database_url",
)
INVALID_SUPABASE_DATABASE_URL_MESSAGE = (
    "Invalid SUPABASE_DATABASE_URL. It must be a PostgreSQL URI beginning with "
    "postgresql:// or postgres://. Check GitHub Secrets."
)


def get_connection():
    """Return a Supabase Postgres connection and ensure tables exist."""
    _validate_supabase_database_url(SUPABASE_DATABASE_URL)

    if psycopg2 is None:
        raise RuntimeError("psycopg2-binary is required for Supabase storage.")

    connection = psycopg2.connect(SUPABASE_DATABASE_URL)
    _ensure_tables(connection)
    return connection


def _validate_supabase_database_url(database_url: str | None) -> None:
    """Validate the configured Supabase Postgres URI without exposing it."""
    if not database_url:
        raise RuntimeError(INVALID_SUPABASE_DATABASE_URL_MESSAGE)

    database_url = str(database_url).strip()

    if not database_url:
        raise RuntimeError(INVALID_SUPABASE_DATABASE_URL_MESSAGE)

    if database_url.startswith(("'", '"')) or database_url.endswith(("'", '"')):
        raise RuntimeError(INVALID_SUPABASE_DATABASE_URL_MESSAGE)

    if "SUPABASE_DATABASE_URL=" in database_url:
        raise RuntimeError(INVALID_SUPABASE_DATABASE_URL_MESSAGE)

    if not database_url.startswith(("postgresql://", "postgres://")):
        raise RuntimeError(INVALID_SUPABASE_DATABASE_URL_MESSAGE)


def _ensure_tables(connection) -> None:
    """Create the small persistence tables if they are missing."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_state (
                symbol TEXT PRIMARY KEY,
                last_score INTEGER NOT NULL,
                last_alerted_at TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_history (
                id TEXT PRIMARY KEY,
                symbol TEXT,
                alerted_at TIMESTAMPTZ,
                latest_close NUMERIC,
                opportunity_score INTEGER,
                classification TEXT,
                target_bucket TEXT,
                continuation_target TEXT,
                move_stage TEXT,
                move_from_recent_low_pct NUMERIC,
                liquidity_label TEXT,
                exhaustion_risk_level TEXT,
                risk_level TEXT,
                alert_type TEXT,
                confidence TEXT,
                potential_bucket TEXT,
                reason TEXT,
                summary TEXT,
                recent_price_changes JSONB,
                volume_acceleration JSONB,
                explosive_mover JSONB,
                trade_plan JSONB,
                trade_plan_type TEXT,
                should_paper_trade BOOLEAN NOT NULL DEFAULT FALSE,
                scan_run_id TEXT,
                source TEXT,
                component_scores JSONB,
                volume_signal JSONB,
                momentum_signal JSONB,
                breakout_signal JSONB,
                trend_signal JSONB,
                volatility_signal JSONB,
                telegram_sent BOOLEAN NOT NULL DEFAULT FALSE,
                telegram_error TEXT,
                paper_trade_created BOOLEAN NOT NULL DEFAULT FALSE,
                paper_trade_id TEXT,
                paper_trade_skip_reason TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        for statement in (
            'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS alert_type TEXT',
            'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS continuation_target TEXT',
            'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS move_stage TEXT',
            (
                'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS '
                'move_from_recent_low_pct NUMERIC'
            ),
            'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS liquidity_label TEXT',
            (
                'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS '
                'exhaustion_risk_level TEXT'
            ),
            'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS confidence TEXT',
            'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS potential_bucket TEXT',
            'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS reason TEXT',
            (
                'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS '
                'recent_price_changes JSONB'
            ),
            (
                'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS '
                'volume_acceleration JSONB'
            ),
            'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS explosive_mover JSONB',
            'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS trade_plan JSONB',
            'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS trade_plan_type TEXT',
            (
                'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS '
                'should_paper_trade BOOLEAN NOT NULL DEFAULT FALSE'
            ),
            'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS scan_run_id TEXT',
            'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS source TEXT',
            'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS telegram_error TEXT',
            (
                'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS '
                'paper_trade_created BOOLEAN NOT NULL DEFAULT FALSE'
            ),
            'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS paper_trade_id TEXT',
            (
                'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS '
                'paper_trade_skip_reason TEXT'
            ),
            (
                'ALTER TABLE alert_history ADD COLUMN IF NOT EXISTS '
                'tradability_score INTEGER'
            ),
        ):
            cursor.execute(statement)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_outcomes (
                alert_id TEXT PRIMARY KEY,
                symbol TEXT,
                alerted_at TIMESTAMPTZ,
                entry_price NUMERIC,
                opportunity_score INTEGER,
                classification TEXT,
                target_bucket TEXT,
                risk_level TEXT,
                checkpoints JSONB,
                max_high_after_alert NUMERIC,
                max_upside_pct NUMERIC,
                min_low_after_alert NUMERIC,
                max_drawdown_pct NUMERIC,
                hit_5_pct BOOLEAN NOT NULL DEFAULT FALSE,
                hit_10_pct BOOLEAN NOT NULL DEFAULT FALSE,
                hit_20_pct BOOLEAN NOT NULL DEFAULT FALSE,
                hit_50_pct BOOLEAN NOT NULL DEFAULT FALSE,
                hit_100_pct BOOLEAN NOT NULL DEFAULT FALSE,
                last_checked_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trades (
                id TEXT PRIMARY KEY,
                alert_id TEXT,
                alert_history_id TEXT,
                source_alert_id TEXT,
                strategy_name TEXT,
                alert_type TEXT,
                trade_plan_type TEXT,
                symbol TEXT,
                opened_at TIMESTAMPTZ,
                closed_at TIMESTAMPTZ,
                entry_price NUMERIC,
                exit_price NUMERIC,
                status TEXT,
                direction TEXT,
                opportunity_score INTEGER,
                classification TEXT,
                target_bucket TEXT,
                continuation_target TEXT,
                move_stage TEXT,
                move_from_recent_low_pct NUMERIC,
                liquidity_label TEXT,
                exhaustion_risk_level TEXT,
                stop_loss_pct NUMERIC,
                take_profit_1_pct NUMERIC,
                take_profit_2_pct NUMERIC,
                take_profit_3_pct NUMERIC,
                max_hold_hours INTEGER,
                simulated_position_size NUMERIC,
                exit_reason TEXT,
                pnl_pct NUMERIC,
                pnl_amount NUMERIC,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cursor.execute(
            """
            ALTER TABLE paper_trades
            ADD COLUMN IF NOT EXISTS strategy_name TEXT
            """
        )
        cursor.execute(
            """
            ALTER TABLE paper_trades
            ADD COLUMN IF NOT EXISTS alert_type TEXT
            """
        )
        cursor.execute(
            """
            ALTER TABLE paper_trades
            ADD COLUMN IF NOT EXISTS trade_plan_type TEXT
            """
        )
        cursor.execute(
            """
            ALTER TABLE paper_trades
            ADD COLUMN IF NOT EXISTS alert_history_id TEXT
            """
        )
        cursor.execute(
            """
            ALTER TABLE paper_trades
            ADD COLUMN IF NOT EXISTS source_alert_id TEXT
            """
        )
        for statement in (
            'ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS peak_price NUMERIC',
            'ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS trailing_stop_price NUMERIC',
            'ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS partial_tp1_hit BOOLEAN NOT NULL DEFAULT FALSE',
            'ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS partial_tp2_hit BOOLEAN NOT NULL DEFAULT FALSE',
            'ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS partial_tp1_price NUMERIC',
            'ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS partial_tp2_price NUMERIC',
            'ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS blended_pnl_pct NUMERIC',
            'ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS tradability_score INTEGER',
            'ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS gross_pnl_pct NUMERIC',
            'ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS net_pnl_pct NUMERIC',
            'ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS net_pnl_amount NUMERIC',
        ):
            cursor.execute(statement)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trade_events (
                paper_trade_id TEXT,
                symbol TEXT,
                event_time TIMESTAMPTZ,
                event_type TEXT,
                price NUMERIC,
                notes TEXT,
                metadata JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_runs (
                id TEXT PRIMARY KEY,
                run_source TEXT,
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at TIMESTAMPTZ,
                status TEXT NOT NULL DEFAULT 'running',
                binance_base_url_order TEXT,
                paper_strategy TEXT,
                metadata JSONB,
                total_active_symbols INTEGER,
                total_scan_universe INTEGER,
                total_alert_candidates INTEGER,
                total_telegram_sent INTEGER,
                total_paper_trades_created INTEGER,
                total_paper_trades_skipped INTEGER,
                error_message TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        for statement in (
            'ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS run_source TEXT',
            (
                'ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS '
                'started_at TIMESTAMPTZ NOT NULL DEFAULT NOW()'
            ),
            'ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ',
            (
                "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS "
                "status TEXT NOT NULL DEFAULT 'running'"
            ),
            (
                'ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS '
                'binance_base_url_order TEXT'
            ),
            'ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS paper_strategy TEXT',
            'ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS metadata JSONB',
            (
                'ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS '
                'total_active_symbols INTEGER'
            ),
            (
                'ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS '
                'total_scan_universe INTEGER'
            ),
            (
                'ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS '
                'total_alert_candidates INTEGER'
            ),
            (
                'ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS '
                'total_telegram_sent INTEGER'
            ),
            (
                'ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS '
                'total_paper_trades_created INTEGER'
            ),
            (
                'ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS '
                'total_paper_trades_skipped INTEGER'
            ),
            'ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS error_message TEXT',
            (
                'ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS '
                'created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()'
            ),
            (
                'ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS '
                'updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()'
            ),
        ):
            cursor.execute(statement)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trade_decisions (
                id TEXT PRIMARY KEY,
                symbol TEXT,
                alert_type TEXT,
                alert_history_id TEXT,
                paper_trade_id TEXT,
                decision TEXT,
                eligible BOOLEAN NOT NULL DEFAULT FALSE,
                reason TEXT,
                strategy_name TEXT,
                trade_plan_type TEXT,
                metadata JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        for statement in (
            'ALTER TABLE paper_trade_decisions ADD COLUMN IF NOT EXISTS symbol TEXT',
            'ALTER TABLE paper_trade_decisions ADD COLUMN IF NOT EXISTS alert_type TEXT',
            (
                'ALTER TABLE paper_trade_decisions ADD COLUMN IF NOT EXISTS '
                'alert_history_id TEXT'
            ),
            (
                'ALTER TABLE paper_trade_decisions ADD COLUMN IF NOT EXISTS '
                'paper_trade_id TEXT'
            ),
            'ALTER TABLE paper_trade_decisions ADD COLUMN IF NOT EXISTS decision TEXT',
            (
                'ALTER TABLE paper_trade_decisions ADD COLUMN IF NOT EXISTS '
                'eligible BOOLEAN NOT NULL DEFAULT FALSE'
            ),
            'ALTER TABLE paper_trade_decisions ADD COLUMN IF NOT EXISTS reason TEXT',
            (
                'ALTER TABLE paper_trade_decisions ADD COLUMN IF NOT EXISTS '
                'strategy_name TEXT'
            ),
            (
                'ALTER TABLE paper_trade_decisions ADD COLUMN IF NOT EXISTS '
                'trade_plan_type TEXT'
            ),
            'ALTER TABLE paper_trade_decisions ADD COLUMN IF NOT EXISTS metadata JSONB',
            (
                'ALTER TABLE paper_trade_decisions ADD COLUMN IF NOT EXISTS '
                'created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()'
            ),
        ):
            cursor.execute(statement)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_send_log (
                id BIGSERIAL PRIMARY KEY,
                alert_id TEXT,
                attempt_number INTEGER NOT NULL,
                http_status INTEGER,
                response_body TEXT,
                sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cursor.execute(
            """
            ALTER TABLE alert_state
            ADD COLUMN IF NOT EXISTS last_price NUMERIC
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS system_health (
                id BIGSERIAL PRIMARY KEY,
                scan_type TEXT NOT NULL,
                completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                metadata JSONB
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS shadow_trades (
                id BIGSERIAL PRIMARY KEY,
                action TEXT NOT NULL,
                symbol TEXT NOT NULL,
                quantity NUMERIC,
                price NUMERIC,
                logged_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                metadata JSONB
            )
            """
        )

    connection.commit()


def persistence_health_check() -> dict:
    """Return a read-only persistence health report without exposing secrets."""
    backend = (PERSISTENCE_BACKEND or "json").strip().lower() or "json"
    report = {
        "backend": backend,
        "supabase_url_configured": bool(SUPABASE_DATABASE_URL),
        "connection_ok": False,
        "counts": {table: None for table in HEALTH_CHECK_TABLES},
        "latest_alert_history": [],
        "latest_scan_runs": [],
        "latest_paper_trade_decisions": [],
        "warnings": [],
    }

    if backend != "supabase":
        report["warnings"].append(
            "Supabase connection not tested because PERSISTENCE_BACKEND is not supabase."
        )
        return report

    if not SUPABASE_DATABASE_URL:
        report["warnings"].append(
            "Supabase backend selected but SUPABASE_DATABASE_URL is not configured."
        )
        return report

    try:
        connection = get_connection()
    except Exception as error:
        report["warnings"].append(
            f"Supabase connection failed: {_safe_error_message(error)}"
        )
        return report

    report["connection_ok"] = True

    try:
        for table_name in HEALTH_CHECK_TABLES:
            report["counts"][table_name] = _health_check_count_table(
                connection,
                table_name,
                report["warnings"],
            )

        report["latest_alert_history"] = _health_check_latest_rows(
            connection,
            "alert_history",
            report["warnings"],
        )
        report["latest_scan_runs"] = _health_check_latest_rows(
            connection,
            "scan_runs",
            report["warnings"],
        )
        report["latest_paper_trade_decisions"] = _health_check_latest_rows(
            connection,
            "paper_trade_decisions",
            report["warnings"],
        )
    finally:
        connection.close()

    return report


def format_persistence_health_check(report: dict) -> str:
    """Format a persistence health report without printing secret values."""
    counts = report.get("counts") or {}
    lines = [
        "Persistence Health Check",
        f"Backend: {report.get('backend', 'unknown')}",
        (
            "SUPABASE_DATABASE_URL configured: "
            f"{str(bool(report.get('supabase_url_configured'))).lower()}"
        ),
        f"Connection OK: {str(bool(report.get('connection_ok'))).lower()}",
        "",
        "Counts:",
    ]

    for table_name in HEALTH_CHECK_TABLES:
        count = counts.get(table_name)
        lines.append(f"- {table_name}: {_format_optional_count(count)}")

    lines.extend(["", "Latest alert_history:"])
    lines.extend(_format_latest_alert_history(report.get("latest_alert_history") or []))
    lines.extend(["", "Latest scan_runs:"])
    lines.extend(_format_latest_scan_runs(report.get("latest_scan_runs") or []))
    lines.extend(["", "Latest paper_trade_decisions:"])
    lines.extend(
        _format_latest_paper_trade_decisions(
            report.get("latest_paper_trade_decisions") or []
        )
    )

    warnings = list(report.get("warnings") or [])

    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"- {_redact_sensitive(str(warning))}" for warning in warnings)

    return "\n".join(lines)


def get_alert_state(symbol: str) -> dict | None:
    """Load one symbol's cooldown state from Supabase."""
    connection = get_connection()

    try:
        with connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT symbol, last_score, last_alerted_at, last_price
                    FROM alert_state
                    WHERE symbol = %s
                    """,
                    (symbol,),
                )
                row = cursor.fetchone()
    finally:
        connection.close()

    if row is None:
        return None

    state = dict(row)
    state["last_alerted_at"] = _to_iso(state.get("last_alerted_at"))
    return state


def upsert_alert_state(
    symbol: str,
    last_score: int,
    last_alerted_at: str,
    last_price: float | None = None,
) -> None:
    """Insert or update one symbol's cooldown state in Supabase."""
    connection = get_connection()

    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO alert_state (symbol, last_score, last_alerted_at, last_price)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (symbol) DO UPDATE
                    SET
                        last_score = EXCLUDED.last_score,
                        last_alerted_at = EXCLUDED.last_alerted_at,
                        last_price = EXCLUDED.last_price,
                        updated_at = NOW()
                    """,
                    (symbol, last_score, last_alerted_at, last_price),
                )
    finally:
        connection.close()


def insert_shadow_trade(record: dict) -> None:
    """Persist a shadow (would-be live) order to shadow_trades."""
    connection = get_connection()

    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO shadow_trades
                        (action, symbol, quantity, price, logged_at, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record.get("action"),
                        record.get("symbol"),
                        record.get("quantity"),
                        record.get("price"),
                        record.get("logged_at"),
                        Json(record.get("metadata") or {}),
                    ),
                )
    finally:
        connection.close()


def write_system_health(scan_type: str, metadata: dict | None = None) -> None:
    """Record a successful scan heartbeat to system_health."""
    connection = get_connection()

    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO system_health (scan_type, metadata)
                    VALUES (%s, %s)
                    """,
                    (scan_type, Json(metadata or {})),
                )
    finally:
        connection.close()


def load_system_health_summary(hours: int = 24) -> dict:
    """Return a summary of system health for the last `hours` hours."""
    connection = get_connection()

    try:
        with connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT scan_type, COUNT(*) AS count,
                           MAX(completed_at) AS last_run
                    FROM system_health
                    WHERE completed_at >= NOW() - INTERVAL '%s hours'
                    GROUP BY scan_type
                    """,
                    (hours,),
                )
                rows = cursor.fetchall()

                cursor.execute(
                    """
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN telegram_sent THEN 1 ELSE 0 END) AS sent
                    FROM alert_history
                    WHERE created_at >= NOW() - INTERVAL '%s hours'
                    """,
                    (hours,),
                )
                alert_row = cursor.fetchone()

                cursor.execute(
                    """
                    SELECT COUNT(*) AS open_count
                    FROM paper_trades WHERE status = 'open'
                    """,
                )
                open_row = cursor.fetchone()

                cursor.execute(
                    """
                    SELECT COALESCE(SUM(pnl_amount), 0) AS pnl_24h
                    FROM paper_trades
                    WHERE status = 'closed'
                      AND closed_at >= NOW() - INTERVAL '%s hours'
                    """,
                    (hours,),
                )
                pnl_row = cursor.fetchone()
    finally:
        connection.close()

    health_by_type = {row["scan_type"]: dict(row) for row in rows}
    return {
        "scans_completed": (health_by_type.get("scan") or {}).get("count", 0),
        "last_scan": (health_by_type.get("scan") or {}).get("last_run"),
        "alerts_total": int((alert_row or {}).get("total") or 0),
        "alerts_sent": int((alert_row or {}).get("sent") or 0),
        "open_paper_trades": int((open_row or {}).get("open_count") or 0),
        "pnl_24h": float((pnl_row or {}).get("pnl_24h") or 0),
        "hours": hours,
    }


def insert_telegram_send_log(
    alert_id: str | None,
    attempt_number: int,
    http_status: int | None,
    response_body: str | None,
) -> None:
    """Write one Telegram send attempt to the structured log table."""
    connection = get_connection()

    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO telegram_send_log
                        (alert_id, attempt_number, http_status, response_body)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (alert_id, attempt_number, http_status, response_body),
                )
    finally:
        connection.close()


def insert_alert_history(record: dict) -> None:
    """Insert an alert history record and ignore duplicate IDs."""
    record_id = record.get("id")

    if not record_id:
        raise ValueError("Alert history record must include an id.")

    connection = get_connection()

    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO alert_history (
                        id,
                        symbol,
                        alerted_at,
                        latest_close,
                        opportunity_score,
                        classification,
                        target_bucket,
                        continuation_target,
                        move_stage,
                        move_from_recent_low_pct,
                        liquidity_label,
                        exhaustion_risk_level,
                        risk_level,
                        alert_type,
                        confidence,
                        potential_bucket,
                        reason,
                        summary,
                        recent_price_changes,
                        volume_acceleration,
                        explosive_mover,
                        trade_plan,
                        trade_plan_type,
                        should_paper_trade,
                        scan_run_id,
                        source,
                        component_scores,
                        volume_signal,
                        momentum_signal,
                        breakout_signal,
                        trend_signal,
                        volatility_signal,
                        telegram_sent,
                        telegram_error,
                        paper_trade_created,
                        paper_trade_id,
                        paper_trade_skip_reason,
                        tradability_score
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        record_id,
                        record.get("symbol"),
                        record.get("alerted_at"),
                        record.get("latest_close"),
                        record.get("opportunity_score"),
                        record.get("classification"),
                        record.get("target_bucket"),
                        record.get("continuation_target"),
                        record.get("move_stage"),
                        record.get("move_from_recent_low_pct"),
                        record.get("liquidity_label"),
                        record.get("exhaustion_risk_level"),
                        record.get("risk_level"),
                        record.get("alert_type"),
                        record.get("confidence"),
                        record.get("potential_bucket"),
                        record.get("reason"),
                        record.get("summary"),
                        _json_param(record.get("recent_price_changes")),
                        _json_param(record.get("volume_acceleration")),
                        _json_param(record.get("explosive_mover")),
                        _json_param(record.get("trade_plan")),
                        record.get("trade_plan_type"),
                        bool(record.get("should_paper_trade")),
                        record.get("scan_run_id"),
                        record.get("source", "scanner"),
                        _json_param(record.get("component_scores")),
                        _json_param(record.get("volume_signal")),
                        _json_param(record.get("momentum_signal")),
                        _json_param(record.get("breakout_signal")),
                        _json_param(record.get("trend_signal")),
                        _json_param(record.get("volatility_signal")),
                        bool(record.get("telegram_sent")),
                        record.get("telegram_error"),
                        bool(record.get("paper_trade_created")),
                        record.get("paper_trade_id"),
                        record.get("paper_trade_skip_reason"),
                        record.get("tradability_score"),
                    ),
                )
    finally:
        connection.close()


def load_alert_history(limit: int | None = None) -> list[dict]:
    """Load alert history records from Supabase."""
    connection = get_connection()

    if limit is not None:
        limit = max(0, int(limit))

    try:
        with connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                if limit is None:
                    cursor.execute(
                        """
                        SELECT
                            id,
                            symbol,
                            alerted_at,
                            latest_close,
                            opportunity_score,
                            classification,
                            target_bucket,
                            continuation_target,
                            move_stage,
                            move_from_recent_low_pct,
                            liquidity_label,
                            exhaustion_risk_level,
                            risk_level,
                            alert_type,
                            confidence,
                            potential_bucket,
                            reason,
                            summary,
                            recent_price_changes,
                            volume_acceleration,
                            explosive_mover,
                            trade_plan,
                            trade_plan_type,
                            should_paper_trade,
                            scan_run_id,
                            source,
                            component_scores,
                            volume_signal,
                            momentum_signal,
                            breakout_signal,
                            trend_signal,
                            volatility_signal,
                            telegram_sent,
                            telegram_error,
                            paper_trade_created,
                            paper_trade_id,
                            paper_trade_skip_reason,
                            tradability_score,
                            created_at
                        FROM alert_history
                        ORDER BY alerted_at ASC, id ASC
                        """
                    )
                else:
                    cursor.execute(
                        """
                        SELECT
                            id,
                            symbol,
                            alerted_at,
                            latest_close,
                            opportunity_score,
                            classification,
                            target_bucket,
                            continuation_target,
                            move_stage,
                            move_from_recent_low_pct,
                            liquidity_label,
                            exhaustion_risk_level,
                            risk_level,
                            alert_type,
                            confidence,
                            potential_bucket,
                            reason,
                            summary,
                            recent_price_changes,
                            volume_acceleration,
                            explosive_mover,
                            trade_plan,
                            trade_plan_type,
                            should_paper_trade,
                            scan_run_id,
                            source,
                            component_scores,
                            volume_signal,
                            momentum_signal,
                            breakout_signal,
                            trend_signal,
                            volatility_signal,
                            telegram_sent,
                            telegram_error,
                            paper_trade_created,
                            paper_trade_id,
                            paper_trade_skip_reason,
                            tradability_score,
                            created_at
                        FROM alert_history
                        ORDER BY alerted_at ASC, id ASC
                        LIMIT %s
                        """,
                        (limit,),
                    )

                rows = cursor.fetchall()
    finally:
        connection.close()

    return [_alert_history_row_to_record(row) for row in rows]


def load_unchecked_alert_history(limit: int | None = None) -> list[dict]:
    """Load alert history rows that have no outcome or an unchecked outcome stub.

    Rows are ordered so that never-checked alerts (no outcome row, or a
    backfilled stub with last_checked_at IS NULL) come first, then oldest
    last_checked_at.  Supply a limit to cap how many are returned per batch.
    """
    connection = get_connection()

    if limit is not None:
        limit = max(0, int(limit))

    try:
        with connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                if limit is None:
                    cursor.execute(
                        """
                        SELECT
                            ah.id,
                            ah.symbol,
                            ah.alerted_at,
                            ah.latest_close,
                            ah.opportunity_score,
                            ah.classification,
                            ah.target_bucket,
                            ah.continuation_target,
                            ah.move_stage,
                            ah.move_from_recent_low_pct,
                            ah.liquidity_label,
                            ah.exhaustion_risk_level,
                            ah.risk_level,
                            ah.alert_type,
                            ah.confidence,
                            ah.potential_bucket,
                            ah.reason,
                            ah.summary,
                            ah.recent_price_changes,
                            ah.volume_acceleration,
                            ah.explosive_mover,
                            ah.trade_plan,
                            ah.trade_plan_type,
                            ah.should_paper_trade,
                            ah.scan_run_id,
                            ah.source,
                            ah.component_scores,
                            ah.volume_signal,
                            ah.momentum_signal,
                            ah.breakout_signal,
                            ah.trend_signal,
                            ah.volatility_signal,
                            ah.telegram_sent,
                            ah.telegram_error,
                            ah.paper_trade_created,
                            ah.paper_trade_id,
                            ah.paper_trade_skip_reason,
                            ah.tradability_score,
                            ah.created_at
                        FROM alert_history ah
                        LEFT JOIN alert_outcomes ao ON ao.alert_id = ah.id
                        WHERE ao.alert_id IS NULL
                           OR ao.last_checked_at IS NULL
                        ORDER BY
                            ao.last_checked_at ASC NULLS FIRST,
                            ah.alerted_at ASC,
                            ah.id ASC
                        """
                    )
                else:
                    cursor.execute(
                        """
                        SELECT
                            ah.id,
                            ah.symbol,
                            ah.alerted_at,
                            ah.latest_close,
                            ah.opportunity_score,
                            ah.classification,
                            ah.target_bucket,
                            ah.continuation_target,
                            ah.move_stage,
                            ah.move_from_recent_low_pct,
                            ah.liquidity_label,
                            ah.exhaustion_risk_level,
                            ah.risk_level,
                            ah.alert_type,
                            ah.confidence,
                            ah.potential_bucket,
                            ah.reason,
                            ah.summary,
                            ah.recent_price_changes,
                            ah.volume_acceleration,
                            ah.explosive_mover,
                            ah.trade_plan,
                            ah.trade_plan_type,
                            ah.should_paper_trade,
                            ah.scan_run_id,
                            ah.source,
                            ah.component_scores,
                            ah.volume_signal,
                            ah.momentum_signal,
                            ah.breakout_signal,
                            ah.trend_signal,
                            ah.volatility_signal,
                            ah.telegram_sent,
                            ah.telegram_error,
                            ah.paper_trade_created,
                            ah.paper_trade_id,
                            ah.paper_trade_skip_reason,
                            ah.tradability_score,
                            ah.created_at
                        FROM alert_history ah
                        LEFT JOIN alert_outcomes ao ON ao.alert_id = ah.id
                        WHERE ao.alert_id IS NULL
                           OR ao.last_checked_at IS NULL
                        ORDER BY
                            ao.last_checked_at ASC NULLS FIRST,
                            ah.alerted_at ASC,
                            ah.id ASC
                        LIMIT %s
                        """,
                        (limit,),
                    )

                rows = cursor.fetchall()
    finally:
        connection.close()

    return [_alert_history_row_to_record(row) for row in rows]


def update_alert_telegram_status(
    alert_history_id: str | None,
    sent: bool,
    error: str | None = None,
) -> None:
    """Update the Telegram delivery status for one persisted alert."""
    if not alert_history_id:
        return

    connection = get_connection()

    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE alert_history
                    SET
                        telegram_sent = %s,
                        telegram_error = %s
                    WHERE id = %s
                    """,
                    (bool(sent), error, alert_history_id),
                )
    finally:
        connection.close()


def update_alert_paper_trade_status(
    alert_history_id: str | None,
    paper_trade_created: bool,
    paper_trade_id: str | None = None,
    skip_reason: str | None = None,
) -> None:
    """Update the paper-trade outcome for one persisted alert."""
    if not alert_history_id:
        return

    connection = get_connection()

    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE alert_history
                    SET
                        paper_trade_created = %s,
                        paper_trade_id = %s,
                        paper_trade_skip_reason = %s
                    WHERE id = %s
                    """,
                    (
                        bool(paper_trade_created),
                        paper_trade_id,
                        skip_reason,
                        alert_history_id,
                    ),
                )
    finally:
        connection.close()


def create_scan_run(metadata: dict | None = None) -> str:
    """Create and persist a scanner run record, returning its ID."""
    metadata = dict(metadata or {})
    scan_run_id = str(metadata.get("id") or f"scan_{uuid4().hex}")
    started_at = metadata.get("timestamp") or _utc_now_iso()

    connection = get_connection()

    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO scan_runs (
                        id,
                        run_source,
                        started_at,
                        status,
                        binance_base_url_order,
                        paper_strategy,
                        metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        scan_run_id,
                        metadata.get("run_source"),
                        started_at,
                        "running",
                        metadata.get("binance_base_url_order"),
                        metadata.get("paper_strategy"),
                        _json_param(metadata),
                    ),
                )
    finally:
        connection.close()

    return scan_run_id


def complete_scan_run(scan_run_id: str | None, summary: dict | None = None) -> None:
    """Mark a scanner run completed with summary counts."""
    if not scan_run_id:
        return

    summary = dict(summary or {})
    connection = get_connection()

    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE scan_runs
                    SET
                        completed_at = NOW(),
                        status = %s,
                        total_active_symbols = %s,
                        total_scan_universe = %s,
                        total_alert_candidates = %s,
                        total_telegram_sent = %s,
                        total_paper_trades_created = %s,
                        total_paper_trades_skipped = %s,
                        metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        summary.get("status", "completed"),
                        summary.get("total_active_symbols"),
                        summary.get("total_scan_universe"),
                        summary.get("total_alert_candidates"),
                        summary.get("total_telegram_sent"),
                        summary.get("total_paper_trades_created"),
                        summary.get("total_paper_trades_skipped"),
                        json.dumps(summary),
                        scan_run_id,
                    ),
                )
    finally:
        connection.close()


def fail_scan_run(scan_run_id: str | None, error_message: str) -> None:
    """Mark a scanner run failed without leaking secret values."""
    if not scan_run_id:
        return

    safe_error = _safe_error_message(Exception(error_message))
    connection = get_connection()

    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE scan_runs
                    SET
                        completed_at = NOW(),
                        status = %s,
                        error_message = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    ("failed", safe_error, scan_run_id),
                )
    finally:
        connection.close()


def insert_paper_trade_decision(record: dict) -> str:
    """Insert a paper-trade decision row for one alert candidate."""
    decision_id = str(record.get("id") or f"decision_{uuid4().hex}")

    connection = get_connection()

    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO paper_trade_decisions (
                        id,
                        symbol,
                        alert_type,
                        alert_history_id,
                        paper_trade_id,
                        decision,
                        eligible,
                        reason,
                        strategy_name,
                        trade_plan_type,
                        metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        decision_id,
                        record.get("symbol"),
                        record.get("alert_type"),
                        record.get("alert_history_id"),
                        record.get("paper_trade_id"),
                        record.get("decision"),
                        bool(record.get("eligible")),
                        record.get("reason"),
                        record.get("strategy_name"),
                        record.get("trade_plan_type"),
                        _json_param(record.get("metadata", {})),
                    ),
                )
    finally:
        connection.close()

    return decision_id


def load_paper_trade_decisions(limit: int | None = None) -> list[dict]:
    """Load paper-trade decision records from Supabase."""
    connection = get_connection()

    if limit is not None:
        limit = max(0, int(limit))

    try:
        with connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                if limit is None:
                    cursor.execute(
                        """
                        SELECT
                            id,
                            symbol,
                            alert_type,
                            alert_history_id,
                            paper_trade_id,
                            decision,
                            eligible,
                            reason,
                            strategy_name,
                            trade_plan_type,
                            metadata,
                            created_at
                        FROM paper_trade_decisions
                        ORDER BY created_at DESC, id ASC
                        """
                    )
                else:
                    cursor.execute(
                        """
                        SELECT
                            id,
                            symbol,
                            alert_type,
                            alert_history_id,
                            paper_trade_id,
                            decision,
                            eligible,
                            reason,
                            strategy_name,
                            trade_plan_type,
                            metadata,
                            created_at
                        FROM paper_trade_decisions
                        ORDER BY created_at DESC, id ASC
                        LIMIT %s
                        """,
                        (limit,),
                    )

                rows = cursor.fetchall()
    finally:
        connection.close()

    return [_paper_trade_decision_row_to_record(row) for row in rows]


def load_scan_runs(limit: int | None = None) -> list[dict]:
    """Load scan run records from Supabase."""
    connection = get_connection()

    if limit is not None:
        limit = max(0, int(limit))

    try:
        with connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                if limit is None:
                    cursor.execute(
                        """
                        SELECT
                            id,
                            run_source,
                            started_at,
                            completed_at,
                            status,
                            binance_base_url_order,
                            paper_strategy,
                            metadata,
                            total_active_symbols,
                            total_scan_universe,
                            total_alert_candidates,
                            total_telegram_sent,
                            total_paper_trades_created,
                            total_paper_trades_skipped,
                            error_message,
                            created_at,
                            updated_at
                        FROM scan_runs
                        ORDER BY started_at DESC, id ASC
                        """
                    )
                else:
                    cursor.execute(
                        """
                        SELECT
                            id,
                            run_source,
                            started_at,
                            completed_at,
                            status,
                            binance_base_url_order,
                            paper_strategy,
                            metadata,
                            total_active_symbols,
                            total_scan_universe,
                            total_alert_candidates,
                            total_telegram_sent,
                            total_paper_trades_created,
                            total_paper_trades_skipped,
                            error_message,
                            created_at,
                            updated_at
                        FROM scan_runs
                        ORDER BY started_at DESC, id ASC
                        LIMIT %s
                        """,
                        (limit,),
                    )

                rows = cursor.fetchall()
    finally:
        connection.close()

    return [_scan_run_row_to_record(row) for row in rows]


def upsert_alert_outcome(record: dict) -> None:
    """Insert or update one alert outcome record in Supabase."""
    alert_id = record.get("alert_id")

    if not alert_id:
        raise ValueError("Alert outcome record must include an alert_id.")

    connection = get_connection()

    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO alert_outcomes (
                        alert_id,
                        symbol,
                        alerted_at,
                        entry_price,
                        opportunity_score,
                        classification,
                        target_bucket,
                        risk_level,
                        checkpoints,
                        max_high_after_alert,
                        max_upside_pct,
                        min_low_after_alert,
                        max_drawdown_pct,
                        hit_5_pct,
                        hit_10_pct,
                        hit_20_pct,
                        hit_50_pct,
                        hit_100_pct,
                        last_checked_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (alert_id) DO UPDATE
                    SET
                        symbol = EXCLUDED.symbol,
                        alerted_at = EXCLUDED.alerted_at,
                        entry_price = EXCLUDED.entry_price,
                        opportunity_score = EXCLUDED.opportunity_score,
                        classification = EXCLUDED.classification,
                        target_bucket = EXCLUDED.target_bucket,
                        risk_level = EXCLUDED.risk_level,
                        checkpoints = EXCLUDED.checkpoints,
                        max_high_after_alert = EXCLUDED.max_high_after_alert,
                        max_upside_pct = EXCLUDED.max_upside_pct,
                        min_low_after_alert = EXCLUDED.min_low_after_alert,
                        max_drawdown_pct = EXCLUDED.max_drawdown_pct,
                        hit_5_pct = EXCLUDED.hit_5_pct,
                        hit_10_pct = EXCLUDED.hit_10_pct,
                        hit_20_pct = EXCLUDED.hit_20_pct,
                        hit_50_pct = EXCLUDED.hit_50_pct,
                        hit_100_pct = EXCLUDED.hit_100_pct,
                        last_checked_at = EXCLUDED.last_checked_at,
                        updated_at = NOW()
                    """,
                    (
                        alert_id,
                        record.get("symbol"),
                        record.get("alerted_at"),
                        _first_present(record, "entry_price", "alert_latest_close"),
                        record.get("opportunity_score"),
                        record.get("classification"),
                        record.get("target_bucket"),
                        record.get("risk_level"),
                        _json_param(record.get("checkpoints", _build_checkpoints(record))),
                        _first_present(record, "max_high_after_alert", "highest_price"),
                        _first_present(record, "max_upside_pct", "highest_return_pct"),
                        record.get("min_low_after_alert"),
                        record.get("max_drawdown_pct"),
                        _first_bool(record, "hit_5_pct", "hit_5pct"),
                        _first_bool(record, "hit_10_pct", "hit_10pct"),
                        _first_bool(record, "hit_20_pct", "hit_20pct"),
                        _first_bool(record, "hit_50_pct", "hit_50pct"),
                        _first_bool(record, "hit_100_pct", "hit_100pct"),
                        _first_present(record, "last_checked_at", "checked_at"),
                    ),
                )
    finally:
        connection.close()


def load_alert_outcomes() -> dict:
    """Load alert outcomes from Supabase as a mapping by alert ID."""
    connection = get_connection()

    try:
        with connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        alert_id,
                        symbol,
                        alerted_at,
                        entry_price,
                        opportunity_score,
                        classification,
                        target_bucket,
                        risk_level,
                        checkpoints,
                        max_high_after_alert,
                        max_upside_pct,
                        min_low_after_alert,
                        max_drawdown_pct,
                        hit_5_pct,
                        hit_10_pct,
                        hit_20_pct,
                        hit_50_pct,
                        hit_100_pct,
                        last_checked_at,
                        updated_at
                    FROM alert_outcomes
                    ORDER BY last_checked_at ASC, alert_id ASC
                    """
                )
                rows = cursor.fetchall()
    finally:
        connection.close()

    return {
        row["alert_id"]: _alert_outcome_row_to_record(row)
        for row in rows
    }


def insert_paper_trade(record: dict) -> None:
    """Insert a simulated paper trade and ignore duplicate IDs."""
    record_id = record.get("id")

    if not record_id:
        raise ValueError("Paper trade record must include an id.")

    connection = get_connection()

    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO paper_trades (
                        id,
                        alert_id,
                        alert_history_id,
                        source_alert_id,
                        strategy_name,
                        alert_type,
                        trade_plan_type,
                        symbol,
                        opened_at,
                        closed_at,
                        entry_price,
                        exit_price,
                        status,
                        direction,
                        opportunity_score,
                        classification,
                        target_bucket,
                        continuation_target,
                        move_stage,
                        move_from_recent_low_pct,
                        liquidity_label,
                        exhaustion_risk_level,
                        stop_loss_pct,
                        take_profit_1_pct,
                        take_profit_2_pct,
                        take_profit_3_pct,
                        max_hold_hours,
                        simulated_position_size,
                        exit_reason,
                        pnl_pct,
                        pnl_amount,
                        tradability_score,
                        gross_pnl_pct,
                        net_pnl_pct,
                        net_pnl_amount
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        record_id,
                        record.get("alert_id"),
                        record.get("alert_history_id"),
                        record.get("source_alert_id"),
                        record.get("strategy_name"),
                        record.get("alert_type"),
                        record.get("trade_plan_type"),
                        record.get("symbol"),
                        record.get("opened_at"),
                        record.get("closed_at"),
                        record.get("entry_price"),
                        record.get("exit_price"),
                        record.get("status"),
                        record.get("direction"),
                        record.get("opportunity_score"),
                        record.get("classification"),
                        record.get("target_bucket"),
                        record.get("continuation_target"),
                        record.get("move_stage"),
                        record.get("move_from_recent_low_pct"),
                        record.get("liquidity_label"),
                        record.get("exhaustion_risk_level"),
                        record.get("stop_loss_pct"),
                        record.get("take_profit_1_pct"),
                        record.get("take_profit_2_pct"),
                        record.get("take_profit_3_pct"),
                        record.get("max_hold_hours"),
                        record.get("simulated_position_size"),
                        record.get("exit_reason"),
                        record.get("pnl_pct"),
                        record.get("pnl_amount"),
                        record.get("tradability_score"),
                        record.get("gross_pnl_pct"),
                        record.get("net_pnl_pct"),
                        record.get("net_pnl_amount"),
                    ),
                )
    finally:
        connection.close()


def get_open_paper_trades() -> list[dict]:
    """Load open simulated paper trades from Supabase."""
    connection = get_connection()

    try:
        with connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        alert_id,
                        alert_history_id,
                        source_alert_id,
                        strategy_name,
                        alert_type,
                        trade_plan_type,
                        symbol,
                        opened_at,
                        closed_at,
                        entry_price,
                        exit_price,
                        status,
                        direction,
                        opportunity_score,
                        classification,
                        target_bucket,
                        continuation_target,
                        move_stage,
                        move_from_recent_low_pct,
                        liquidity_label,
                        exhaustion_risk_level,
                        stop_loss_pct,
                        take_profit_1_pct,
                        take_profit_2_pct,
                        take_profit_3_pct,
                        max_hold_hours,
                        simulated_position_size,
                        pnl_pct,
                        pnl_amount,
                        exit_reason,
                        tradability_score,
                        gross_pnl_pct,
                        net_pnl_pct,
                        net_pnl_amount,
                        created_at,
                        updated_at
                    FROM paper_trades
                    WHERE status = %s
                    ORDER BY opened_at ASC, id ASC
                    """,
                    ("open",),
                )
                rows = cursor.fetchall()
    finally:
        connection.close()

    return [_paper_trade_row_to_record(row) for row in rows]


def get_closed_paper_trades_since(cutoff_iso: str) -> list[dict]:
    """Return closed paper trades with closed_at >= cutoff_iso (for drawdown gate)."""
    connection = get_connection()

    try:
        with connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, symbol, closed_at, pnl_pct, pnl_amount,
                           exit_reason, simulated_position_size
                    FROM paper_trades
                    WHERE status = 'closed' AND closed_at >= %s
                    ORDER BY closed_at DESC
                    """,
                    (cutoff_iso,),
                )
                rows = cursor.fetchall()
    finally:
        connection.close()

    return [dict(row) for row in rows]


def update_paper_trade(trade_id: str, updates: dict) -> None:
    """Update a simulated paper trade by ID."""
    if not trade_id:
        raise ValueError("trade_id is required.")

    if not updates:
        return

    column_by_key = {
        "alert_id": "alert_id",
        "alert_history_id": "alert_history_id",
        "source_alert_id": "source_alert_id",
        "strategy_name": "strategy_name",
        "alert_type": "alert_type",
        "trade_plan_type": "trade_plan_type",
        "symbol": "symbol",
        "opened_at": "opened_at",
        "closed_at": "closed_at",
        "entry_price": "entry_price",
        "exit_price": "exit_price",
        "status": "status",
        "direction": "direction",
        "opportunity_score": "opportunity_score",
        "classification": "classification",
        "target_bucket": "target_bucket",
        "continuation_target": "continuation_target",
        "move_stage": "move_stage",
        "move_from_recent_low_pct": "move_from_recent_low_pct",
        "liquidity_label": "liquidity_label",
        "exhaustion_risk_level": "exhaustion_risk_level",
        "stop_loss_pct": "stop_loss_pct",
        "take_profit_1_pct": "take_profit_1_pct",
        "take_profit_2_pct": "take_profit_2_pct",
        "take_profit_3_pct": "take_profit_3_pct",
        "max_hold_hours": "max_hold_hours",
        "simulated_position_size": "simulated_position_size",
        "exit_reason": "exit_reason",
        "pnl_pct": "pnl_pct",
        "pnl_amount": "pnl_amount",
        "peak_price": "peak_price",
        "trailing_stop_price": "trailing_stop_price",
        "partial_tp1_hit": "partial_tp1_hit",
        "partial_tp2_hit": "partial_tp2_hit",
        "partial_tp1_price": "partial_tp1_price",
        "partial_tp2_price": "partial_tp2_price",
        "blended_pnl_pct": "blended_pnl_pct",
        "tradability_score": "tradability_score",
        "gross_pnl_pct": "gross_pnl_pct",
        "net_pnl_pct": "net_pnl_pct",
        "net_pnl_amount": "net_pnl_amount",
    }
    set_clauses = []
    values = []

    for key, column in column_by_key.items():
        if key in updates:
            set_clauses.append(f"{column} = %s")
            values.append(updates[key])

    set_clauses.append("updated_at = NOW()")
    values.append(trade_id)

    connection = get_connection()

    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE paper_trades
                    SET {", ".join(set_clauses)}
                    WHERE id = %s
                    """,
                    tuple(values),
                )
    finally:
        connection.close()


def insert_paper_trade_event(record: dict) -> None:
    """Insert one simulated paper trade event."""
    paper_trade_id = _first_present(record, "paper_trade_id", "trade_id")

    if not paper_trade_id:
        raise ValueError("Paper trade event record must include a paper_trade_id.")

    connection = get_connection()

    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO paper_trade_events (
                        paper_trade_id,
                        symbol,
                        event_time,
                        event_type,
                        price,
                        notes,
                        metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        paper_trade_id,
                        record.get("symbol"),
                        _first_present(record, "event_time", "occurred_at"),
                        _first_present(record, "type", "event_type"),
                        _paper_trade_event_price(record),
                        _paper_trade_event_notes(record),
                        _json_param(record.get("metadata", record)),
                    ),
                )
    finally:
        connection.close()


def load_paper_trades(limit: int | None = None) -> list[dict]:
    """Load simulated paper trades from Supabase."""
    connection = get_connection()

    if limit is not None:
        limit = max(0, int(limit))

    try:
        with connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                if limit is None:
                    cursor.execute(
                        """
                        SELECT
                            id,
                            alert_id,
                            alert_history_id,
                            source_alert_id,
                            strategy_name,
                            alert_type,
                            trade_plan_type,
                            symbol,
                            opened_at,
                            closed_at,
                            entry_price,
                            exit_price,
                            status,
                            direction,
                            opportunity_score,
                            classification,
                            target_bucket,
                            continuation_target,
                            move_stage,
                            move_from_recent_low_pct,
                            liquidity_label,
                            exhaustion_risk_level,
                            stop_loss_pct,
                            take_profit_1_pct,
                            take_profit_2_pct,
                            take_profit_3_pct,
                            max_hold_hours,
                            simulated_position_size,
                            pnl_pct,
                            pnl_amount,
                            exit_reason,
                            tradability_score,
                            gross_pnl_pct,
                            net_pnl_pct,
                            net_pnl_amount,
                            created_at,
                            updated_at
                        FROM paper_trades
                        ORDER BY opened_at DESC, id ASC
                        """
                    )
                else:
                    cursor.execute(
                        """
                        SELECT
                            id,
                            alert_id,
                            alert_history_id,
                            source_alert_id,
                            strategy_name,
                            alert_type,
                            trade_plan_type,
                            symbol,
                            opened_at,
                            closed_at,
                            entry_price,
                            exit_price,
                            status,
                            direction,
                            opportunity_score,
                            classification,
                            target_bucket,
                            continuation_target,
                            move_stage,
                            move_from_recent_low_pct,
                            liquidity_label,
                            exhaustion_risk_level,
                            stop_loss_pct,
                            take_profit_1_pct,
                            take_profit_2_pct,
                            take_profit_3_pct,
                            max_hold_hours,
                            simulated_position_size,
                            pnl_pct,
                            pnl_amount,
                            exit_reason,
                            tradability_score,
                            gross_pnl_pct,
                            net_pnl_pct,
                            net_pnl_amount,
                            created_at,
                            updated_at
                        FROM paper_trades
                        ORDER BY opened_at DESC, id ASC
                        LIMIT %s
                        """,
                        (limit,),
                    )

                rows = cursor.fetchall()
    finally:
        connection.close()

    return [_paper_trade_row_to_record(row) for row in rows]


def _alert_history_row_to_record(row: dict) -> dict:
    """Map a structured alert_history row into the app's history dictionary."""
    return {
        "id": row.get("id"),
        "symbol": row.get("symbol"),
        "alerted_at": _to_iso(row.get("alerted_at")),
        "latest_close": _to_plain_number(row.get("latest_close")),
        "opportunity_score": row.get("opportunity_score"),
        "classification": row.get("classification"),
        "target_bucket": row.get("target_bucket"),
        "continuation_target": row.get("continuation_target"),
        "move_stage": row.get("move_stage"),
        "move_from_recent_low_pct": _to_plain_number(
            row.get("move_from_recent_low_pct")
        ),
        "liquidity_label": row.get("liquidity_label"),
        "exhaustion_risk_level": row.get("exhaustion_risk_level"),
        "risk_level": row.get("risk_level"),
        "alert_type": row.get("alert_type"),
        "confidence": row.get("confidence"),
        "potential_bucket": row.get("potential_bucket"),
        "reason": row.get("reason"),
        "summary": row.get("summary"),
        "recent_price_changes": _as_json_value(row.get("recent_price_changes")),
        "volume_acceleration": _as_json_value(row.get("volume_acceleration")),
        "explosive_mover": _as_json_value(row.get("explosive_mover")),
        "trade_plan": _as_json_value(row.get("trade_plan")),
        "trade_plan_type": row.get("trade_plan_type"),
        "should_paper_trade": bool(row.get("should_paper_trade")),
        "scan_run_id": row.get("scan_run_id"),
        "source": row.get("source"),
        "component_scores": _as_json_value(row.get("component_scores")),
        "volume_signal": _as_json_value(row.get("volume_signal")),
        "momentum_signal": _as_json_value(row.get("momentum_signal")),
        "breakout_signal": _as_json_value(row.get("breakout_signal")),
        "trend_signal": _as_json_value(row.get("trend_signal")),
        "volatility_signal": _as_json_value(row.get("volatility_signal")),
        "telegram_sent": bool(row.get("telegram_sent")),
        "telegram_error": row.get("telegram_error"),
        "paper_trade_created": bool(row.get("paper_trade_created")),
        "paper_trade_id": row.get("paper_trade_id"),
        "paper_trade_skip_reason": row.get("paper_trade_skip_reason"),
        "tradability_score": row.get("tradability_score"),
        "created_at": _to_iso(row.get("created_at")),
    }


def _alert_outcome_row_to_record(row: dict) -> dict:
    """Map a structured alert_outcomes row into the app's outcome dictionary."""
    record = {
        "alert_id": row.get("alert_id"),
        "symbol": row.get("symbol"),
        "alerted_at": _to_iso(row.get("alerted_at")),
        "checked_at": _to_iso(row.get("last_checked_at")),
        "last_checked_at": _to_iso(row.get("last_checked_at")),
        "alert_latest_close": _to_plain_number(row.get("entry_price")),
        "entry_price": _to_plain_number(row.get("entry_price")),
        "opportunity_score": row.get("opportunity_score"),
        "classification": row.get("classification"),
        "target_bucket": row.get("target_bucket"),
        "risk_level": row.get("risk_level"),
        "checkpoints": _as_json_value(row.get("checkpoints")),
        "highest_price": _to_plain_number(row.get("max_high_after_alert")),
        "highest_return_pct": _to_plain_number(row.get("max_upside_pct")),
        "max_high_after_alert": _to_plain_number(row.get("max_high_after_alert")),
        "max_upside_pct": _to_plain_number(row.get("max_upside_pct")),
        "min_low_after_alert": _to_plain_number(row.get("min_low_after_alert")),
        "max_drawdown_pct": _to_plain_number(row.get("max_drawdown_pct")),
        "updated_at": _to_iso(row.get("updated_at")),
    }

    for threshold in (5, 10, 20, 50, 100):
        db_key = f"hit_{threshold}_pct"
        app_key = f"hit_{threshold}pct"
        record[db_key] = bool(row.get(db_key))
        record[app_key] = bool(row.get(db_key))

    return record


def _paper_trade_row_to_record(row: dict) -> dict:
    """Map a paper_trades row into a JSON-friendly trade dictionary."""
    return {
        "id": row.get("id"),
        "alert_id": row.get("alert_id"),
        "alert_history_id": row.get("alert_history_id"),
        "source_alert_id": row.get("source_alert_id"),
        "strategy_name": row.get("strategy_name"),
        "alert_type": row.get("alert_type"),
        "trade_plan_type": row.get("trade_plan_type"),
        "symbol": row.get("symbol"),
        "opened_at": _to_iso(row.get("opened_at")),
        "closed_at": _to_iso(row.get("closed_at")),
        "entry_price": _to_plain_number(row.get("entry_price")),
        "exit_price": _to_plain_number(row.get("exit_price")),
        "status": row.get("status"),
        "direction": row.get("direction"),
        "opportunity_score": row.get("opportunity_score"),
        "classification": row.get("classification"),
        "target_bucket": row.get("target_bucket"),
        "continuation_target": row.get("continuation_target"),
        "move_stage": row.get("move_stage"),
        "move_from_recent_low_pct": _to_plain_number(
            row.get("move_from_recent_low_pct")
        ),
        "liquidity_label": row.get("liquidity_label"),
        "exhaustion_risk_level": row.get("exhaustion_risk_level"),
        "stop_loss_pct": _to_plain_number(row.get("stop_loss_pct")),
        "take_profit_1_pct": _to_plain_number(row.get("take_profit_1_pct")),
        "take_profit_2_pct": _to_plain_number(row.get("take_profit_2_pct")),
        "take_profit_3_pct": _to_plain_number(row.get("take_profit_3_pct")),
        "max_hold_hours": row.get("max_hold_hours"),
        "simulated_position_size": _to_plain_number(
            row.get("simulated_position_size")
        ),
        "pnl_pct": _to_plain_number(row.get("pnl_pct")),
        "pnl_amount": _to_plain_number(row.get("pnl_amount")),
        "exit_reason": row.get("exit_reason"),
        "tradability_score": row.get("tradability_score"),
        "gross_pnl_pct": _to_plain_number(row.get("gross_pnl_pct")),
        "net_pnl_pct": _to_plain_number(row.get("net_pnl_pct")),
        "net_pnl_amount": _to_plain_number(row.get("net_pnl_amount")),
        "created_at": _to_iso(row.get("created_at")),
        "updated_at": _to_iso(row.get("updated_at")),
    }


def _paper_trade_decision_row_to_record(row: dict) -> dict:
    """Map a paper_trade_decisions row into a JSON-friendly record."""
    return {
        "id": row.get("id"),
        "symbol": row.get("symbol"),
        "alert_type": row.get("alert_type"),
        "alert_history_id": row.get("alert_history_id"),
        "paper_trade_id": row.get("paper_trade_id"),
        "decision": row.get("decision"),
        "eligible": bool(row.get("eligible")),
        "reason": row.get("reason"),
        "strategy_name": row.get("strategy_name"),
        "trade_plan_type": row.get("trade_plan_type"),
        "metadata": _as_json_value(row.get("metadata")),
        "created_at": _to_iso(row.get("created_at")),
    }


def _scan_run_row_to_record(row: dict) -> dict:
    """Map a scan_runs row into a JSON-friendly record."""
    return {
        "id": row.get("id"),
        "run_source": row.get("run_source"),
        "started_at": _to_iso(row.get("started_at")),
        "completed_at": _to_iso(row.get("completed_at")),
        "status": row.get("status"),
        "binance_base_url_order": row.get("binance_base_url_order"),
        "paper_strategy": row.get("paper_strategy"),
        "metadata": _as_json_value(row.get("metadata")),
        "total_active_symbols": row.get("total_active_symbols"),
        "total_scan_universe": row.get("total_scan_universe"),
        "total_alert_candidates": row.get("total_alert_candidates"),
        "total_telegram_sent": row.get("total_telegram_sent"),
        "total_paper_trades_created": row.get("total_paper_trades_created"),
        "total_paper_trades_skipped": row.get("total_paper_trades_skipped"),
        "error_message": row.get("error_message"),
        "created_at": _to_iso(row.get("created_at")),
        "updated_at": _to_iso(row.get("updated_at")),
    }


def _paper_trade_event_price(record: dict) -> Any:
    """Read a trade event price from top-level or nested event details."""
    details = record.get("details") or {}
    event_type = _first_present(record, "event_type", "type")

    if record.get("price") is not None:
        return record.get("price")

    if event_type == "opened":
        return _first_present(record, "entry_price") or details.get("entry_price")

    return (
        _first_present(record, "exit_price", "entry_price")
        or details.get("exit_price")
        or details.get("entry_price")
    )


def _paper_trade_event_notes(record: dict) -> Any:
    """Build a compact note for a paper trade event."""
    if record.get("notes") is not None:
        return record.get("notes")

    details = record.get("details") or {}
    exit_reason = _first_present(record, "exit_reason") or details.get("exit_reason")

    if exit_reason:
        return f"exit_reason={exit_reason}"

    return None


def _health_check_count_table(connection, table_name: str, warnings: list[str]):
    """Return a table count, or None if the health-check query fails."""
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*) AS record_count
                FROM {_health_check_table_name(table_name)}
                """
            )
            row = _fetch_one(cursor)
    except Exception as error:
        _rollback_safely(connection)
        _append_health_check_warning(table_name, error, warnings)
        return None

    if not row:
        return 0

    return int(row.get("record_count", 0) or 0)


def _health_check_latest_rows(
    connection,
    table_name: str,
    warnings: list[str],
) -> list[dict]:
    """Return up to five recent rows from a table, handling missing tables."""
    try:
        order_column = _health_check_order_column(connection, table_name)
        order_clause = (
            f" ORDER BY {order_column} DESC NULLS LAST"
            if order_column is not None
            else ""
        )

        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {_health_check_table_name(table_name)}
                {order_clause}
                LIMIT 5
                """
            )
            rows = cursor.fetchall()
    except Exception as error:
        _rollback_safely(connection)
        _append_health_check_warning(table_name, error, warnings)
        return []

    return [_normalize_record(dict(row)) for row in rows]


def _health_check_order_column(connection, table_name: str) -> str | None:
    """Return the best available column for latest-record ordering."""
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = %s
            """,
            (table_name,),
        )
        rows = cursor.fetchall()

    column_names = {str(row.get("column_name")) for row in rows}

    for column_name in HEALTH_CHECK_ORDER_COLUMNS:
        if column_name in column_names:
            return column_name

    return None


def _health_check_table_name(table_name: str) -> str:
    """Return an internal health-check table name for SQL interpolation."""
    if table_name not in HEALTH_CHECK_TABLES:
        raise ValueError(f"Unsupported health-check table: {table_name}")

    return table_name


def _fetch_one(cursor) -> dict | None:
    """Fetch one row from DB cursors and simple test doubles."""
    if hasattr(cursor, "fetchone"):
        return cursor.fetchone()

    rows = cursor.fetchall()

    if not rows:
        return None

    return rows[0]


def _append_health_check_warning(
    table_name: str,
    error: Exception,
    warnings: list[str],
) -> None:
    """Append a concise health-check warning without leaking secrets."""
    if _is_missing_table_error(error):
        if table_name in {"scan_runs", "paper_trade_decisions"}:
            warning = (
                f"Table missing: {table_name}. "
                "Run the Stage 37 Supabase SQL migration."
            )
        else:
            warning = f"Table missing: {table_name}."
    else:
        warning = (
            f"Could not query {table_name}: {_safe_error_message(error)}"
        )

    if warning not in warnings:
        warnings.append(warning)


def _is_missing_table_error(error: Exception) -> bool:
    """Return whether a database error indicates a missing table."""
    error_name = error.__class__.__name__.lower()
    error_text = str(error).lower()

    return (
        "undefinedtable" in error_name
        or "undefined_table" in error_name
        or "does not exist" in error_text
        or "no such table" in error_text
    )


def _rollback_safely(connection) -> None:
    """Rollback a failed health-check query when the connection supports it."""
    if not hasattr(connection, "rollback"):
        return

    try:
        connection.rollback()
    except Exception:
        return


def _safe_error_message(error: Exception) -> str:
    """Return a sanitized one-line error message."""
    message = str(error).splitlines()[0] or error.__class__.__name__

    if SUPABASE_DATABASE_URL:
        message = message.replace(SUPABASE_DATABASE_URL, "[REDACTED]")

    return str(_redact_sensitive(message))


def _format_optional_count(value: Any) -> str:
    """Format table counts where None means unavailable."""
    if value is None:
        return "Not available"

    return str(value)


def _format_latest_alert_history(records: list[dict]) -> list[str]:
    """Format concise latest alert_history rows."""
    if not records:
        return ["- None"]

    return [
        " | ".join(
            [
                f"- {_format_field(record.get('created_at'))}",
                _format_field(record.get("symbol")),
                _format_field(record.get("alert_type")),
                f"score={_format_field(record.get('opportunity_score'))}",
                f"telegram_sent={_format_bool_field(record.get('telegram_sent'))}",
                (
                    "paper_trade_created="
                    f"{_format_bool_field(record.get('paper_trade_created'))}"
                ),
                (
                    "skip_reason="
                    f"{_format_field(record.get('paper_trade_skip_reason'))}"
                ),
                f"scan_run_id={_format_field(record.get('scan_run_id'))}",
            ]
        )
        for record in records[:5]
    ]


def _format_latest_scan_runs(records: list[dict]) -> list[str]:
    """Format concise latest scan_runs rows."""
    if not records:
        return ["- None"]

    return [
        " | ".join(
            [
                f"- {_format_field(record.get('started_at'))}",
                f"status={_format_field(record.get('status'))}",
                f"universe={_format_field(record.get('total_scan_universe'))}",
                f"alerts={_format_field(record.get('total_alert_candidates'))}",
                (
                    "created="
                    f"{_format_field(record.get('total_paper_trades_created'))}"
                ),
                (
                    "skipped="
                    f"{_format_field(record.get('total_paper_trades_skipped'))}"
                ),
            ]
        )
        for record in records[:5]
    ]


def _format_latest_paper_trade_decisions(records: list[dict]) -> list[str]:
    """Format concise latest paper_trade_decisions rows."""
    if not records:
        return ["- None"]

    return [
        " | ".join(
            [
                f"- {_format_field(record.get('created_at'))}",
                _format_field(record.get("symbol")),
                _format_field(record.get("alert_type")),
                f"decision={_format_field(record.get('decision'))}",
                f"eligible={_format_bool_field(record.get('eligible'))}",
                f"reason={_format_field(record.get('reason'))}",
            ]
        )
        for record in records[:5]
    ]


def _format_field(value: Any) -> str:
    """Format one compact health-check field with redaction."""
    if value is None:
        return "-"

    return str(_redact_sensitive(value))


def _format_bool_field(value: Any) -> str:
    """Format bool-ish health-check fields in lowercase."""
    if value is None:
        return "-"

    return str(bool(value)).lower()


def _normalize_record(record: dict) -> dict:
    """Convert DB row values into JSON-friendly values."""
    return {
        key: _normalize_value(value)
        for key, value in record.items()
    }


def _normalize_value(value: Any) -> Any:
    """Convert common database values into plain Python values."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, dict):
        return {
            key: _normalize_value(nested_value)
            for key, nested_value in value.items()
        }

    if isinstance(value, list):
        return [_normalize_value(item) for item in value]

    return value


def _redact_sensitive(value: Any) -> Any:
    """Redact likely secret values based on key names."""
    if isinstance(value, dict):
        redacted = {}

        for key, nested_value in value.items():
            key_text = str(key).lower()

            if any(part in key_text for part in SENSITIVE_KEY_PARTS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact_sensitive(nested_value)

        return redacted

    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]

    if isinstance(value, str) and SUPABASE_DATABASE_URL:
        return value.replace(SUPABASE_DATABASE_URL, "[REDACTED]")

    return value


def _to_iso(value: Any) -> Any:
    """Convert date/time values to ISO strings for JSON-friendly records."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    return value


def _to_plain_number(value: Any) -> Any:
    """Convert Decimal values returned by Postgres into plain floats."""
    if isinstance(value, Decimal):
        return float(value)

    return value


def _first_present(record: dict, *keys: str) -> Any:
    """Return the first non-None value for one of the given keys."""
    for key in keys:
        if record.get(key) is not None:
            return record[key]

    return None


def _first_bool(record: dict, *keys: str) -> bool:
    """Return the first boolean-like value for one of the given keys."""
    value = _first_present(record, *keys)
    return bool(value)


def _build_checkpoints(record: dict) -> dict:
    """Build a compact JSONB checkpoint summary from app hit flags."""
    return {
        "+5%": _first_bool(record, "hit_5_pct", "hit_5pct"),
        "+10%": _first_bool(record, "hit_10_pct", "hit_10pct"),
        "+20%": _first_bool(record, "hit_20_pct", "hit_20pct"),
        "+50%": _first_bool(record, "hit_50_pct", "hit_50pct"),
        "+100%": _first_bool(record, "hit_100_pct", "hit_100pct"),
    }


def _as_json_value(value: Any) -> Any:
    """Return JSONB values in their decoded Python form."""
    if value is None:
        return None

    if isinstance(value, (dict, list)):
        return value

    return dict(value)


def _json_param(value: Any) -> Any:
    """Wrap JSON values for psycopg2 while keeping tests dependency-light."""
    if Json is None:
        return value

    return Json(value)


def _utc_now_iso() -> str:
    """Return the current UTC timestamp as ISO text."""
    return datetime.now(timezone.utc).isoformat()
