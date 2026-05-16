"""Local alert state for Telegram cooldown and duplicate protection."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import USE_SUPABASE
from app.storage import supabase_store

ALERT_STATE_FILE = "data/alert_state.json"


def ensure_data_dir() -> None:
    """Create the local data directory if it does not exist."""
    Path(ALERT_STATE_FILE).parent.mkdir(parents=True, exist_ok=True)


def load_alert_state() -> dict:
    """Load alert state from disk."""
    state_path = Path(ALERT_STATE_FILE)

    if not state_path.exists():
        return {}

    try:
        with state_path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError):
        return {}


def save_alert_state(state: dict) -> None:
    """Save alert state to disk."""
    ensure_data_dir()
    state_path = Path(ALERT_STATE_FILE)

    with state_path.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)


def _parse_timestamp(timestamp: str) -> datetime:
    """Parse an ISO timestamp and return a timezone-aware UTC datetime."""
    parsed_timestamp = datetime.fromisoformat(timestamp)

    if parsed_timestamp.tzinfo is None:
        return parsed_timestamp.replace(tzinfo=timezone.utc)

    return parsed_timestamp.astimezone(timezone.utc)


def should_send_alert(
    symbol: str,
    current_score: int,
    cooldown_minutes: int = 60,
    score_improvement_threshold: int = 10,
) -> tuple[bool, str]:
    """Return whether an alert should be sent for a symbol."""
    if USE_SUPABASE:
        previous_alert = supabase_store.get_alert_state(symbol)
    else:
        state = load_alert_state()
        previous_alert = state.get(symbol)

    if not previous_alert:
        return True, "No previous alert for symbol."

    try:
        last_score = int(previous_alert.get("last_score", 0))
        last_alerted_at = _parse_timestamp(previous_alert["last_alerted_at"])
    except (KeyError, TypeError, ValueError):
        return True, "No previous alert for symbol."

    cooldown_delta = timedelta(minutes=cooldown_minutes)

    if datetime.now(timezone.utc) - last_alerted_at >= cooldown_delta:
        return True, "Cooldown period has passed."

    if current_score >= last_score + score_improvement_threshold:
        return True, "Score improved materially since last alert."

    return False, "Duplicate alert suppressed during cooldown."


def record_alert(symbol: str, score: int) -> None:
    """Record that an alert was sent for a symbol."""
    last_alerted_at = datetime.now(timezone.utc).isoformat()

    if USE_SUPABASE:
        supabase_store.upsert_alert_state(symbol, score, last_alerted_at)
        return

    state = load_alert_state()
    state[symbol] = {
        "last_alerted_at": last_alerted_at,
        "last_score": score,
    }
    save_alert_state(state)
