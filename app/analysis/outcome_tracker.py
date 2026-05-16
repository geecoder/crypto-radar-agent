"""Alert outcome tracking for saved alert history."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import USE_SUPABASE
from app.storage import supabase_store

OUTCOME_FILE = "data/alert_outcomes.json"
HIT_THRESHOLDS = (5, 10, 20, 50, 100)


def ensure_data_dir() -> None:
    """Create the local data directory if it does not exist."""
    Path(OUTCOME_FILE).parent.mkdir(parents=True, exist_ok=True)


def save_alert_outcomes(outcomes: list[dict]) -> None:
    """Save alert outcome records to disk."""
    if USE_SUPABASE:
        for outcome in outcomes:
            supabase_store.upsert_alert_outcome(outcome)
        return

    ensure_data_dir()
    outcome_path = Path(OUTCOME_FILE)

    with outcome_path.open("w", encoding="utf-8") as file:
        json.dump(outcomes, file, indent=2)


def load_alert_outcomes() -> dict:
    """Load saved alert outcome records by alert ID."""
    if USE_SUPABASE:
        return supabase_store.load_alert_outcomes()

    outcome_path = Path(OUTCOME_FILE)

    if not outcome_path.exists():
        return {}

    try:
        with outcome_path.open("r", encoding="utf-8") as file:
            outcomes = json.load(file)
    except (json.JSONDecodeError, OSError):
        return {}

    if not isinstance(outcomes, list):
        return {}

    return {
        outcome["alert_id"]: outcome
        for outcome in outcomes
        if isinstance(outcome, dict) and outcome.get("alert_id")
    }


def _parse_alerted_at(alerted_at: str | None) -> datetime | None:
    """Parse an alert timestamp as a UTC datetime."""
    if not alerted_at:
        return None

    try:
        parsed_timestamp = datetime.fromisoformat(alerted_at)
    except ValueError:
        return None

    if parsed_timestamp.tzinfo is None:
        return parsed_timestamp.replace(tzinfo=timezone.utc)

    return parsed_timestamp.astimezone(timezone.utc)


def _kline_time_ms(kline: list[Any]) -> int | None:
    """Read the close time from a Binance kline row."""
    try:
        return int(kline[6])
    except (IndexError, TypeError, ValueError):
        return None


def _kline_high(kline: list[Any]) -> float | None:
    """Read the high price from a Binance kline row."""
    try:
        return float(kline[2])
    except (IndexError, TypeError, ValueError):
        return None


def _get_post_alert_high(klines: list[list[Any]], alerted_at: str | None) -> float | None:
    """Return the highest kline high after the alert timestamp."""
    alerted_at_dt = _parse_alerted_at(alerted_at)
    alerted_at_ms = None

    if alerted_at_dt is not None:
        alerted_at_ms = int(alerted_at_dt.timestamp() * 1000)

    highs = []

    for kline in klines:
        kline_time_ms = _kline_time_ms(kline)
        high = _kline_high(kline)

        if high is None:
            continue

        if alerted_at_ms is None or kline_time_ms is None or kline_time_ms >= alerted_at_ms:
            highs.append(high)

    if not highs:
        return None

    return max(highs)


def _build_outcome_record(alert: dict, highest_price: float | None) -> dict:
    """Build one outcome record from an alert history record."""
    checked_at = datetime.now(timezone.utc).isoformat()
    latest_close = alert.get("latest_close")
    outcome = {
        "alert_id": alert.get("id"),
        "symbol": alert.get("symbol"),
        "alerted_at": alert.get("alerted_at"),
        "checked_at": checked_at,
        "alert_latest_close": latest_close,
        "highest_price": highest_price,
        "highest_return_pct": None,
    }

    for threshold in HIT_THRESHOLDS:
        outcome[f"hit_{threshold}pct"] = False

    try:
        entry_price = float(latest_close)
    except (TypeError, ValueError):
        outcome["error"] = "Missing or invalid latest_close."
        return outcome

    if entry_price <= 0:
        outcome["error"] = "latest_close must be greater than zero."
        return outcome

    if highest_price is None:
        outcome["error"] = "No post-alert price data available."
        return outcome

    return_pct = ((highest_price - entry_price) / entry_price) * 100
    outcome["highest_return_pct"] = round(return_pct, 2)

    for threshold in HIT_THRESHOLDS:
        outcome[f"hit_{threshold}pct"] = return_pct >= threshold

    return outcome


def check_alert_outcomes(alert_history: list[dict], client) -> list[dict]:
    """Check saved alert history against current public market data."""
    outcomes = []

    for alert in alert_history:
        symbol = alert.get("symbol")

        if not symbol:
            outcomes.append(_build_outcome_record(alert, highest_price=None))
            continue

        try:
            klines = client.get_klines(symbol, interval="1h", limit=500)
            highest_price = _get_post_alert_high(klines, alert.get("alerted_at"))
            outcome = _build_outcome_record(alert, highest_price)
        except Exception as error:
            outcome = _build_outcome_record(alert, highest_price=None)
            outcome["error"] = str(error)

        outcomes.append(outcome)

    return outcomes
