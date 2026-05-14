"""Local JSON history for alert candidates."""

import json
from datetime import datetime, timezone
from pathlib import Path

ALERT_HISTORY_FILE = "data/alert_history.json"


def ensure_data_dir() -> None:
    """Create the local data directory if it does not exist."""
    Path(ALERT_HISTORY_FILE).parent.mkdir(parents=True, exist_ok=True)


def load_alert_history() -> list[dict]:
    """Load alert history from disk."""
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

    return {
        "id": f"{symbol}-{alerted_at}",
        "symbol": symbol,
        "alerted_at": alerted_at,
        "latest_close": result.get("latest_close"),
        "opportunity_score": opportunity.get("opportunity_score"),
        "classification": opportunity.get("classification"),
        "target_bucket": opportunity.get("target_bucket"),
        "risk_level": opportunity.get("risk_level"),
        "summary": opportunity.get("summary"),
        "component_scores": opportunity.get("component_scores"),
        "volume_signal": result.get("volume_signal"),
        "momentum_signal": result.get("momentum_signal"),
        "breakout_signal": result.get("breakout_signal"),
        "trend_signal": result.get("trend_signal"),
        "volatility_signal": result.get("volatility_signal"),
        "telegram_sent": bool(telegram_sent),
    }


def append_alert_history(result: dict, telegram_sent: bool) -> dict:
    """Append one alert candidate to local history and return the new record."""
    history = load_alert_history()
    record = build_alert_history_record(result, telegram_sent)
    history.append(record)
    save_alert_history(history)
    return record
