"""Simulated paper trading engine for alert candidates.

This module only records hypothetical long trades. It uses public candle data
for evaluation and never places orders or touches private exchange APIs.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.binance.client import klines_to_dataframe
from app.config import USE_SUPABASE
from app.storage import supabase_store
from app.trading.strategy_config import (
    PaperTradingStrategy,
    get_default_paper_trading_strategy,
)

PAPER_TRADES_FILE = "data/paper_trades.json"
PAPER_TRADE_EVENTS_FILE = "data/paper_trade_events.json"
ALLOWED_CONTINUATION_TARGETS = {
    "+20% continuation watch",
    "+50% high-volatility watch",
    "+100% speculative momentum watch",
    "Early move watch",
}
PAPER_TRADE_ALLOWED_ALERT_TYPES = {
    "Continuation Alert",
    "Early Pump Alert",
    "Active Breakout Alert",
}
PARABOLIC_WATCH_ALERT_TYPE = "Parabolic Watch Alert"


def build_paper_trade_from_alert(
    result: dict,
    strategy: PaperTradingStrategy | None = None,
) -> dict:
    """Build a simulated long trade from one alert candidate."""
    strategy = strategy or get_default_paper_trading_strategy()
    opened_at = _utc_now_iso()
    symbol = str(result.get("symbol") or "UNKNOWN")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")

    return {
        "id": f"paper_{symbol}_{timestamp}",
        "alert_id": _first_present(result, "alert_id", "id"),
        "strategy_name": strategy.name,
        "symbol": symbol,
        "alert_type": _get_alert_type(result),
        "opened_at": opened_at,
        "entry_price": result.get("latest_close"),
        "status": "open",
        "direction": "long",
        "opportunity_score": _get_opportunity_value(result, "opportunity_score"),
        "classification": _get_opportunity_value(result, "classification"),
        "target_bucket": _get_opportunity_value(result, "target_bucket"),
        "continuation_target": _get_continuation_target(result),
        "move_stage": _get_move_stage(result),
        "move_from_recent_low_pct": _get_move_from_recent_low_pct(result),
        "liquidity_label": _get_liquidity_label(result),
        "exhaustion_risk_level": _get_exhaustion_risk_level(result),
        "stop_loss_pct": strategy.stop_loss_pct,
        "take_profit_1_pct": strategy.take_profit_1_pct,
        "take_profit_2_pct": strategy.take_profit_2_pct,
        "take_profit_3_pct": strategy.take_profit_3_pct,
        "max_hold_hours": strategy.max_hold_hours,
        "simulated_position_size": strategy.simulated_position_size,
    }


def should_create_paper_trade(
    result: dict,
    strategy: PaperTradingStrategy | None = None,
) -> tuple[bool, str]:
    """Return whether an alert candidate qualifies for a simulated trade."""
    strategy = strategy or get_default_paper_trading_strategy()
    alert_type = _get_alert_type(result)

    if alert_type == PARABOLIC_WATCH_ALERT_TYPE:
        return False, "Parabolic Watch Alert is not eligible for paper trading."

    if alert_type not in PAPER_TRADE_ALLOWED_ALERT_TYPES:
        return False, f"{alert_type} is not eligible for paper trading."

    opportunity_score = _safe_float(_get_opportunity_value(result, "opportunity_score"))

    if opportunity_score < strategy.minimum_opportunity_score:
        return (
            False,
            f"Opportunity score is below {strategy.minimum_opportunity_score}.",
        )

    move_pct = _safe_float(_get_move_from_recent_low_pct(result), default=None)

    if (
        move_pct is None
        or move_pct < strategy.min_move_from_recent_low_pct
        or move_pct > strategy.max_move_from_recent_low_pct
    ):
        return (
            False,
            "Move from recent low must be between "
            f"{strategy.min_move_from_recent_low_pct:g}% and "
            f"{strategy.max_move_from_recent_low_pct:g}%.",
        )

    exhaustion_level = str(_get_exhaustion_risk_level(result) or "").strip()

    if not strategy.allow_high_exhaustion and exhaustion_level.lower() == "high":
        return False, "Exhaustion risk is High."

    liquidity_label = str(_get_liquidity_label(result) or "").strip()

    if not strategy.allow_thin_liquidity and liquidity_label.lower() in {
        "thin",
        "very thin",
    }:
        return False, "Liquidity is too thin for a paper trade."

    continuation_target = _get_continuation_target(result)

    if continuation_target not in ALLOWED_CONTINUATION_TARGETS:
        return False, "Continuation target is not eligible for paper trading."

    return True, "Paper trade eligible."


def create_paper_trades_from_alerts(
    alert_candidates: list[dict],
    strategy: PaperTradingStrategy | None = None,
) -> list[dict]:
    """Create and persist simulated paper trades for eligible alerts."""
    strategy = strategy or get_default_paper_trading_strategy()
    created_trades = []

    for candidate in alert_candidates:
        should_create, _reason = should_create_paper_trade(candidate, strategy)

        if not should_create:
            continue

        trade = build_paper_trade_from_alert(candidate, strategy)
        _insert_paper_trade(trade)
        _insert_paper_trade_event(_build_trade_event(trade, "opened"))
        created_trades.append(trade)

    return created_trades


def evaluate_open_paper_trade(trade: dict, candles_df) -> dict:
    """Evaluate one open paper trade against market candles."""
    entry_price = _safe_float(trade.get("entry_price"), default=None)

    if entry_price is None or entry_price <= 0:
        return {"status": "open"}

    opened_at = _parse_timestamp(trade.get("opened_at"))

    if opened_at is None:
        return {"status": "open"}

    post_open_candles = _candles_after_opened_at(candles_df, opened_at)

    if post_open_candles.empty:
        return {"status": "open"}

    stop_loss_price = _price_at_pct(entry_price, trade.get("stop_loss_pct", -5))
    take_profit_1_price = _price_at_pct(entry_price, trade.get("take_profit_1_pct", 8))
    take_profit_2_price = _price_at_pct(entry_price, trade.get("take_profit_2_pct", 15))
    take_profit_3_price = _price_at_pct(entry_price, trade.get("take_profit_3_pct", 20))
    max_hold_hours = _safe_float(trade.get("max_hold_hours"), default=48) or 48
    expires_at = opened_at + timedelta(hours=max_hold_hours)

    for _index, candle in post_open_candles.iterrows():
        candle_time = _row_timestamp(candle)

        if candle_time is not None and candle_time > expires_at:
            break

        low = _safe_float(candle.get("low"), default=None)
        high = _safe_float(candle.get("high"), default=None)

        if low is not None and low <= stop_loss_price:
            return _build_close_updates(
                trade,
                stop_loss_price,
                "stop_loss",
                candle_time,
            )

        if high is not None and high >= take_profit_3_price:
            return _build_close_updates(
                trade,
                take_profit_3_price,
                "take_profit_3",
                candle_time,
            )

        if high is not None and high >= take_profit_2_price:
            return _build_close_updates(
                trade,
                take_profit_2_price,
                "take_profit_2",
                candle_time,
            )

        if high is not None and high >= take_profit_1_price:
            return _build_close_updates(
                trade,
                take_profit_1_price,
                "take_profit_1",
                candle_time,
            )

    latest_candle = post_open_candles.iloc[-1]
    latest_time = _row_timestamp(latest_candle)

    if latest_time is not None and latest_time >= expires_at:
        latest_close = _safe_float(latest_candle.get("close"), default=None)

        if latest_close is None:
            return {"status": "open"}

        return _build_close_updates(
            trade,
            latest_close,
            "max_hold_expired",
            latest_time,
        )

    return {"status": "open"}


def update_open_paper_trades(client) -> dict:
    """Evaluate all open paper trades and persist any closures."""
    open_trades = _get_open_paper_trades()
    closed_trades = 0
    still_open = 0

    for trade in open_trades:
        symbol = trade.get("symbol")

        if not symbol:
            still_open += 1
            continue

        try:
            klines = client.get_klines(symbol, "15m", 500)
            candles = klines_to_dataframe(klines)
            updates = evaluate_open_paper_trade(trade, candles)
        except Exception:
            still_open += 1
            continue

        if updates.get("status") == "closed":
            _update_paper_trade(str(trade.get("id")), updates)
            closed_trade = {**trade, **updates}
            _insert_paper_trade_event(_build_trade_event(closed_trade, "closed"))
            closed_trades += 1
        else:
            still_open += 1

    return {
        "open_trades_checked": len(open_trades),
        "closed_trades": closed_trades,
        "still_open": still_open,
    }


def _insert_paper_trade(trade: dict) -> None:
    """Persist a paper trade to the configured backend."""
    if USE_SUPABASE:
        supabase_store.insert_paper_trade(trade)
        return

    trades = _load_json_list(PAPER_TRADES_FILE)

    if any(existing.get("id") == trade.get("id") for existing in trades):
        return

    trades.append(trade)
    _save_json_list(PAPER_TRADES_FILE, trades)


def _get_open_paper_trades() -> list[dict]:
    """Load open paper trades from the configured backend."""
    if USE_SUPABASE:
        return supabase_store.get_open_paper_trades()

    return [
        trade
        for trade in _load_json_list(PAPER_TRADES_FILE)
        if trade.get("status") == "open"
    ]


def _update_paper_trade(trade_id: str, updates: dict) -> None:
    """Update a paper trade in the configured backend."""
    if USE_SUPABASE:
        supabase_store.update_paper_trade(trade_id, updates)
        return

    trades = _load_json_list(PAPER_TRADES_FILE)

    for trade in trades:
        if trade.get("id") == trade_id:
            trade.update(updates)
            break

    _save_json_list(PAPER_TRADES_FILE, trades)


def _insert_paper_trade_event(event: dict) -> None:
    """Persist a paper trade event to the configured backend."""
    if USE_SUPABASE:
        supabase_store.insert_paper_trade_event(event)
        return

    events = _load_json_list(PAPER_TRADE_EVENTS_FILE)

    if any(existing.get("id") == event.get("id") for existing in events):
        return

    events.append(event)
    _save_json_list(PAPER_TRADE_EVENTS_FILE, events)


def load_paper_trades(limit: int | None = None) -> list[dict]:
    """Load persisted paper trades from the configured backend."""
    if USE_SUPABASE:
        return supabase_store.load_paper_trades(limit=limit)

    trades = _load_json_list(PAPER_TRADES_FILE)

    if limit is not None:
        return trades[:max(0, int(limit))]

    return trades


def load_all_paper_trades(limit: int | None = None) -> list[dict]:
    """Load all persisted paper trades from the configured backend."""
    return load_paper_trades(limit=limit)


def _build_trade_event(trade: dict, event_type: str) -> dict:
    """Build a JSON-friendly paper trade event."""
    occurred_at = (
        trade.get("closed_at")
        if event_type == "closed"
        else trade.get("opened_at")
    ) or _utc_now_iso()

    return {
        "id": f"event_{trade.get('id')}_{event_type}",
        "trade_id": trade.get("id"),
        "symbol": trade.get("symbol"),
        "type": event_type,
        "occurred_at": occurred_at,
        "details": {
            "entry_price": trade.get("entry_price"),
            "exit_price": trade.get("exit_price"),
            "exit_reason": trade.get("exit_reason"),
            "pnl_pct": trade.get("pnl_pct"),
            "pnl_amount": trade.get("pnl_amount"),
        },
    }


def _build_close_updates(
    trade: dict,
    exit_price: float,
    exit_reason: str,
    closed_at: datetime | None,
) -> dict:
    """Build update fields for a closed paper trade."""
    entry_price = float(trade["entry_price"])
    pnl_pct = ((exit_price - entry_price) / entry_price) * 100
    position_size = _safe_float(trade.get("simulated_position_size"), default=100) or 100

    return {
        "status": "closed",
        "closed_at": _format_timestamp(closed_at) if closed_at else _utc_now_iso(),
        "exit_price": round(float(exit_price), 8),
        "exit_reason": exit_reason,
        "pnl_pct": round(pnl_pct, 2),
        "pnl_amount": round(position_size * (pnl_pct / 100), 2),
    }


def _candles_after_opened_at(candles_df, opened_at: datetime) -> pd.DataFrame:
    """Return candles after the trade opened, sorted oldest first."""
    if candles_df is None or candles_df.empty:
        return pd.DataFrame()

    candles = candles_df.copy()
    time_column = "open_time" if "open_time" in candles.columns else "close_time"

    if time_column not in candles.columns:
        return candles

    candle_times = pd.to_datetime(candles[time_column], utc=True, errors="coerce")
    candles = candles[candle_times >= opened_at]
    candles = candles.assign(_paper_trade_time=candle_times[candle_times >= opened_at])

    return candles.sort_values("_paper_trade_time")


def _row_timestamp(row) -> datetime | None:
    """Read a candle row timestamp as UTC."""
    value = row.get("_paper_trade_time")

    if value is None or pd.isna(value):
        value = row.get("open_time", row.get("close_time"))

    return _parse_timestamp(value)


def _price_at_pct(entry_price: float, pct: Any) -> float:
    """Return a price offset from entry by a percentage."""
    pct_float = _safe_float(pct, default=0) or 0
    return entry_price * (1 + (pct_float / 100))


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse timestamps from strings, pandas values, or datetimes as UTC."""
    if value is None:
        return None

    try:
        parsed = pd.to_datetime(value, utc=True)
    except (TypeError, ValueError):
        return None

    if pd.isna(parsed):
        return None

    return parsed.to_pydatetime()


def _format_timestamp(value: datetime) -> str:
    """Format a timestamp as an ISO UTC string."""
    return value.astimezone(timezone.utc).isoformat()


def _get_opportunity_value(result: dict, key: str) -> Any:
    """Read values from nested opportunity data with top-level fallback."""
    opportunity = result.get("opportunity") or {}

    if opportunity.get(key) is not None:
        return opportunity.get(key)

    return result.get(key)


def _get_alert_type(result: dict) -> str:
    """Read the alert type, defaulting old alert payloads to continuation."""
    if result.get("alert_type") is not None:
        return str(result.get("alert_type"))

    explosive_mover = result.get("explosive_mover") or {}

    if explosive_mover.get("should_alert"):
        return str(explosive_mover.get("alert_type", "Explosive Mover Alert"))

    return "Continuation Alert"


def _get_continuation_target(result: dict) -> str | None:
    """Read the continuation target bucket from a scan result."""
    continuation_target = result.get("continuation_target")

    if isinstance(continuation_target, str):
        return continuation_target

    if not isinstance(continuation_target, dict):
        continuation_target = {}

    return _first_present(continuation_target, "target_bucket", "bucket")


def _get_move_stage(result: dict) -> Any:
    """Read the move stage from nested or flattened alert data."""
    move_stage_signal = result.get("move_stage_signal") or {}

    return _first_present(result, "move_stage") or move_stage_signal.get("stage")


def _get_move_from_recent_low_pct(result: dict) -> Any:
    """Read move-from-low percentage from nested or flattened alert data."""
    move_stage_signal = result.get("move_stage_signal") or {}
    flattened_move_pct = _first_present(result, "move_from_recent_low_pct")

    if flattened_move_pct is not None:
        return flattened_move_pct

    return move_stage_signal.get("move_from_recent_low_pct")


def _get_liquidity_label(result: dict) -> Any:
    """Read the liquidity label from nested or flattened alert data."""
    liquidity_signal = result.get("liquidity_signal") or {}

    return _first_present(result, "liquidity_label") or liquidity_signal.get("label")


def _get_exhaustion_risk_level(result: dict) -> Any:
    """Read exhaustion risk from nested or flattened alert data."""
    exhaustion_signal = result.get("exhaustion_signal") or {}

    return (
        _first_present(result, "exhaustion_risk_level")
        or exhaustion_signal.get("risk_level")
    )


def _first_present(record: dict, *keys: str) -> Any:
    """Return the first non-None value for one of the given keys."""
    for key in keys:
        if record.get(key) is not None:
            return record[key]

    return None


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    """Convert a value to float, returning a default on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_json_list(path: str) -> list[dict]:
    """Load a JSON list from disk."""
    json_path = Path(path)

    if not json_path.exists():
        return []

    try:
        with json_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(data, list):
        return []

    return [item for item in data if isinstance(item, dict)]


def _save_json_list(path: str, records: list[dict]) -> None:
    """Save a JSON list to disk."""
    json_path = Path(path)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(records, file, indent=2)


def _utc_now_iso() -> str:
    """Return the current UTC timestamp as ISO text."""
    return datetime.now(timezone.utc).isoformat()
