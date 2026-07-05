"""Local JSON history for alert candidates."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import USE_SUPABASE
from app.storage import supabase_store

ALERT_HISTORY_FILE = "data/alert_history.json"


def ensure_data_dir() -> None:
    """Create the local data directory if it does not exist."""
    Path(ALERT_HISTORY_FILE).parent.mkdir(parents=True, exist_ok=True)


def load_alert_history(limit: int | None = None) -> list[dict]:
    """Load alert history from disk."""
    if USE_SUPABASE:
        return supabase_store.load_alert_history(limit=limit)

    history_path = Path(ALERT_HISTORY_FILE)

    if not history_path.exists():
        return []

    try:
        with history_path.open("r", encoding="utf-8") as file:
            history = json.load(file)
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(history, list):
        return []

    if limit is not None:
        return history[:max(0, int(limit))]

    return history


def save_alert_history(history: list[dict]) -> None:
    """Save alert history to disk."""
    ensure_data_dir()
    history_path = Path(ALERT_HISTORY_FILE)

    with history_path.open("w", encoding="utf-8") as file:
        json.dump(history, file, indent=2)


def build_alert_history_record(result: dict, telegram_sent: bool) -> dict:
    """Build a JSON-serializable alert history record."""
    opportunity = result.get("opportunity", {})
    symbol = result.get("symbol", "UNKNOWN")
    alerted_at = datetime.now(timezone.utc).isoformat()
    trade_plan = _dict_value(result.get("trade_plan"))

    return {
        "id": f"{symbol}-{alerted_at}",
        "symbol": symbol,
        "alerted_at": alerted_at,
        "latest_close": result.get("latest_close"),
        "opportunity_score": opportunity.get("opportunity_score"),
        "classification": opportunity.get("classification"),
        "target_bucket": opportunity.get("target_bucket"),
        "continuation_target": _continuation_target(result),
        "move_stage": _move_stage(result),
        "move_from_recent_low_pct": _move_from_recent_low_pct(result),
        "liquidity_label": _liquidity_label(result),
        "tradability_score": _tradability_score(result),
        "exhaustion_risk_level": _exhaustion_risk_level(result),
        "risk_level": opportunity.get("risk_level"),
        "alert_type": _alert_type(result),
        "confidence": _confidence(result),
        "potential_bucket": _potential_bucket(result),
        "reason": _reason(result),
        "summary": opportunity.get("summary"),
        "recent_price_changes": result.get("recent_price_changes"),
        "volume_acceleration": result.get("volume_acceleration"),
        "explosive_mover": result.get("explosive_mover"),
        "trade_plan": trade_plan,
        "trade_plan_type": trade_plan.get("trade_plan_type"),
        "should_paper_trade": bool(trade_plan.get("should_paper_trade")),
        "scan_run_id": result.get("scan_run_id"),
        "source": result.get("source", "scanner"),
        "component_scores": opportunity.get("component_scores"),
        "volume_signal": result.get("volume_signal"),
        "momentum_signal": result.get("momentum_signal"),
        "breakout_signal": result.get("breakout_signal"),
        "trend_signal": result.get("trend_signal"),
        "volatility_signal": result.get("volatility_signal"),
        "telegram_sent": bool(telegram_sent),
        "telegram_error": result.get("telegram_error"),
        "paper_trade_created": False,
        "paper_trade_id": result.get("paper_trade_id"),
        "paper_trade_skip_reason": result.get("paper_trade_skip_reason"),
    }


def append_alert_history(result: dict, telegram_sent: bool) -> dict:
    """Append one alert candidate to local history and return the new record."""
    record = build_alert_history_record(result, telegram_sent)

    if USE_SUPABASE:
        supabase_store.insert_alert_history(record)
        return record

    history = load_alert_history()
    history.append(record)
    save_alert_history(history)
    return record


def _dict_value(value: Any) -> dict:
    """Return a dict value when present."""
    return value if isinstance(value, dict) else {}


def _first_present(record: dict, *keys: str) -> Any:
    """Return the first non-None value from a dict."""
    for key in keys:
        if record.get(key) is not None:
            return record[key]

    return None


def _alert_type(result: dict) -> str:
    """Read the final alert type from explosive-mover metadata or top-level data."""
    explosive_mover = _dict_value(result.get("explosive_mover"))

    if explosive_mover.get("should_alert") and explosive_mover.get("alert_type"):
        return str(explosive_mover.get("alert_type"))

    if result.get("alert_type"):
        return str(result.get("alert_type"))

    return "Continuation Alert"


def _continuation_target(result: dict) -> Any:
    """Read continuation target from nested or flattened result data."""
    continuation_target = result.get("continuation_target")

    if isinstance(continuation_target, str):
        return continuation_target

    if isinstance(continuation_target, dict):
        return _first_present(continuation_target, "target_bucket", "bucket")

    return result.get("continuation_target")


def _move_stage(result: dict) -> Any:
    """Read move stage from move_stage_signal, with top-level fallback."""
    move_stage_signal = _dict_value(result.get("move_stage_signal"))

    return move_stage_signal.get("stage") or result.get("move_stage")


def _move_from_recent_low_pct(result: dict) -> Any:
    """Read move-from-low percentage from move_stage_signal or top-level data."""
    move_stage_signal = _dict_value(result.get("move_stage_signal"))

    return (
        move_stage_signal.get("move_from_recent_low_pct")
        if move_stage_signal.get("move_from_recent_low_pct") is not None
        else result.get("move_from_recent_low_pct")
    )


def _liquidity_label(result: dict) -> Any:
    """Read liquidity label from liquidity_signal or top-level data."""
    liquidity_signal = _dict_value(result.get("liquidity_signal"))

    return liquidity_signal.get("label") or result.get("liquidity_label")


def _tradability_score(result: dict) -> Any:
    """Read tradability score from tradability_signal or top-level data."""
    tradability_signal = _dict_value(result.get("tradability_signal"))

    return tradability_signal.get("score") or result.get("tradability_score")


def _exhaustion_risk_level(result: dict) -> Any:
    """Read exhaustion risk level from exhaustion_signal or top-level data."""
    exhaustion_signal = _dict_value(result.get("exhaustion_signal"))

    return exhaustion_signal.get("risk_level") or result.get("exhaustion_risk_level")


def _confidence(result: dict) -> Any:
    """Read alert confidence from final classifier metadata."""
    explosive_mover = _dict_value(result.get("explosive_mover"))
    continuation_target = _dict_value(result.get("continuation_target"))

    return _first_present(result, "confidence") or explosive_mover.get(
        "confidence"
    ) or continuation_target.get("confidence")


def _potential_bucket(result: dict) -> Any:
    """Read potential bucket from final classifier metadata."""
    explosive_mover = _dict_value(result.get("explosive_mover"))

    return (
        _first_present(result, "potential_bucket")
        or explosive_mover.get("potential_bucket")
        or result.get("target_bucket")
    )


def _reason(result: dict) -> Any:
    """Read the clearest reason for why this alert candidate exists."""
    explosive_mover = _dict_value(result.get("explosive_mover"))
    continuation_target = _dict_value(result.get("continuation_target"))
    opportunity = _dict_value(result.get("opportunity"))

    return (
        _first_present(result, "reason")
        or explosive_mover.get("reason")
        or continuation_target.get("reason")
        or opportunity.get("summary")
    )
