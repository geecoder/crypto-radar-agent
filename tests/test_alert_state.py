"""Tests for local alert cooldown state."""

from datetime import datetime, timedelta, timezone
import json

from app.alerts import alert_state


def test_should_send_alert_allows_symbol_with_no_previous_alert(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(alert_state, "ALERT_STATE_FILE", str(tmp_path / "state.json"))

    should_send, reason = alert_state.should_send_alert("BTCUSDT", 70)

    assert should_send is True
    assert reason == "No previous alert for symbol."


def test_should_send_alert_allows_when_cooldown_has_passed(
    monkeypatch,
    tmp_path,
) -> None:
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(alert_state, "ALERT_STATE_FILE", str(state_file))
    old_timestamp = datetime.now(timezone.utc) - timedelta(minutes=61)
    alert_state.save_alert_state(
        {
            "BTCUSDT": {
                "last_alerted_at": old_timestamp.isoformat(),
                "last_score": 80,
            }
        }
    )

    should_send, reason = alert_state.should_send_alert("BTCUSDT", 75)

    assert should_send is True
    assert reason == "Cooldown period has passed."


def test_should_send_alert_allows_when_score_improves_materially(
    monkeypatch,
    tmp_path,
) -> None:
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(alert_state, "ALERT_STATE_FILE", str(state_file))
    recent_timestamp = datetime.now(timezone.utc) - timedelta(minutes=5)
    alert_state.save_alert_state(
        {
            "BTCUSDT": {
                "last_alerted_at": recent_timestamp.isoformat(),
                "last_score": 60,
            }
        }
    )

    should_send, reason = alert_state.should_send_alert("BTCUSDT", 70)

    assert should_send is True
    assert reason == "Score improved materially since last alert."


def test_should_send_alert_suppresses_duplicate_during_cooldown(
    monkeypatch,
    tmp_path,
) -> None:
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(alert_state, "ALERT_STATE_FILE", str(state_file))
    recent_timestamp = datetime.now(timezone.utc) - timedelta(minutes=5)
    alert_state.save_alert_state(
        {
            "BTCUSDT": {
                "last_alerted_at": recent_timestamp.isoformat(),
                "last_score": 70,
            }
        }
    )

    should_send, reason = alert_state.should_send_alert("BTCUSDT", 75)

    assert should_send is False
    assert reason == "Duplicate alert suppressed during cooldown."


def test_record_alert_saves_timestamp_and_score(monkeypatch, tmp_path) -> None:
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(alert_state, "ALERT_STATE_FILE", str(state_file))

    alert_state.record_alert("ETHUSDT", 82)

    saved_state = json.loads(state_file.read_text(encoding="utf-8"))

    assert saved_state["ETHUSDT"]["last_score"] == 82
    assert "last_alerted_at" in saved_state["ETHUSDT"]
