"""Supabase Postgres persistence helpers."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

try:
    import psycopg2
    from psycopg2.extras import Json, RealDictCursor
except ModuleNotFoundError:
    psycopg2 = None
    Json = None
    RealDictCursor = None

from app.config import SUPABASE_DATABASE_URL


def get_connection():
    """Return a Supabase Postgres connection and ensure tables exist."""
    if not SUPABASE_DATABASE_URL:
        raise RuntimeError("SUPABASE_DATABASE_URL is required for Supabase storage.")

    if psycopg2 is None:
        raise RuntimeError("psycopg2-binary is required for Supabase storage.")

    connection = psycopg2.connect(SUPABASE_DATABASE_URL)
    _ensure_tables(connection)
    return connection


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
                risk_level TEXT,
                summary TEXT,
                component_scores JSONB,
                volume_signal JSONB,
                momentum_signal JSONB,
                breakout_signal JSONB,
                trend_signal JSONB,
                volatility_signal JSONB,
                telegram_sent BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
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
                strategy_name TEXT,
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

    connection.commit()


def get_alert_state(symbol: str) -> dict | None:
    """Load one symbol's cooldown state from Supabase."""
    connection = get_connection()

    try:
        with connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT symbol, last_score, last_alerted_at
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


def upsert_alert_state(symbol: str, last_score: int, last_alerted_at: str) -> None:
    """Insert or update one symbol's cooldown state in Supabase."""
    connection = get_connection()

    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO alert_state (symbol, last_score, last_alerted_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (symbol) DO UPDATE
                    SET
                        last_score = EXCLUDED.last_score,
                        last_alerted_at = EXCLUDED.last_alerted_at,
                        updated_at = NOW()
                    """,
                    (symbol, last_score, last_alerted_at),
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
                        risk_level,
                        summary,
                        component_scores,
                        volume_signal,
                        momentum_signal,
                        breakout_signal,
                        trend_signal,
                        volatility_signal,
                        telegram_sent
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s
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
                        record.get("risk_level"),
                        record.get("summary"),
                        Json(record.get("component_scores")),
                        Json(record.get("volume_signal")),
                        Json(record.get("momentum_signal")),
                        Json(record.get("breakout_signal")),
                        Json(record.get("trend_signal")),
                        Json(record.get("volatility_signal")),
                        bool(record.get("telegram_sent")),
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
                            risk_level,
                            summary,
                            component_scores,
                            volume_signal,
                            momentum_signal,
                            breakout_signal,
                            trend_signal,
                            volatility_signal,
                            telegram_sent,
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
                            risk_level,
                            summary,
                            component_scores,
                            volume_signal,
                            momentum_signal,
                            breakout_signal,
                            trend_signal,
                            volatility_signal,
                            telegram_sent,
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
                        Json(record.get("checkpoints", _build_checkpoints(record))),
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
                        strategy_name,
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
                        pnl_amount
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        record_id,
                        record.get("alert_id"),
                        record.get("strategy_name"),
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
                        strategy_name,
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


def update_paper_trade(trade_id: str, updates: dict) -> None:
    """Update a simulated paper trade by ID."""
    if not trade_id:
        raise ValueError("trade_id is required.")

    if not updates:
        return

    column_by_key = {
        "alert_id": "alert_id",
        "strategy_name": "strategy_name",
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
                        Json(record.get("metadata", record)),
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
                            strategy_name,
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
                            strategy_name,
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
        "risk_level": row.get("risk_level"),
        "summary": row.get("summary"),
        "component_scores": _as_json_value(row.get("component_scores")),
        "volume_signal": _as_json_value(row.get("volume_signal")),
        "momentum_signal": _as_json_value(row.get("momentum_signal")),
        "breakout_signal": _as_json_value(row.get("breakout_signal")),
        "trend_signal": _as_json_value(row.get("trend_signal")),
        "volatility_signal": _as_json_value(row.get("volatility_signal")),
        "telegram_sent": bool(row.get("telegram_sent")),
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
        "strategy_name": row.get("strategy_name"),
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
