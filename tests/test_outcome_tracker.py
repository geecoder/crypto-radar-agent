"""Tests for alert outcome tracking."""

from app.analysis import outcome_tracker


class FakeClient:
    """Fake public market-data client for outcome tests."""

    def get_klines(
        self,
        symbol: str,
        interval: str = "15m",
        limit: int = 100,
    ) -> list[list]:
        return [
            [0, "100", "103", "99", "101", "10", 1780000000000],
            [1, "101", "121", "100", "120", "10", 1780003600000],
        ]


def test_check_alert_outcomes_marks_hit_thresholds() -> None:
    alert_history = [
        {
            "id": "BTCUSDT-2026-05-14T00:00:00+00:00",
            "symbol": "BTCUSDT",
            "alerted_at": "2026-05-14T00:00:00+00:00",
            "latest_close": 100.0,
        }
    ]

    outcomes = outcome_tracker.check_alert_outcomes(alert_history, FakeClient())

    assert outcomes == [
        {
            "alert_id": "BTCUSDT-2026-05-14T00:00:00+00:00",
            "symbol": "BTCUSDT",
            "alerted_at": "2026-05-14T00:00:00+00:00",
            "checked_at": outcomes[0]["checked_at"],
            "alert_latest_close": 100.0,
            "highest_price": 121.0,
            "highest_return_pct": 21.0,
            "hit_5pct": True,
            "hit_10pct": True,
            "hit_20pct": True,
            "hit_50pct": False,
            "hit_100pct": False,
        }
    ]


def test_save_alert_outcomes_writes_json(monkeypatch, tmp_path) -> None:
    outcome_file = tmp_path / "data" / "alert_outcomes.json"
    monkeypatch.setattr(outcome_tracker, "OUTCOME_FILE", str(outcome_file))
    outcomes = [{"symbol": "BTCUSDT", "hit_5pct": True}]

    outcome_tracker.save_alert_outcomes(outcomes)

    assert outcome_file.read_text(encoding="utf-8") == (
        "[\n"
        "  {\n"
        '    "symbol": "BTCUSDT",\n'
        '    "hit_5pct": true\n'
        "  }\n"
        "]"
    )


def test_check_alert_outcomes_records_errors() -> None:
    alert_history = [
        {
            "id": "BAD-2026-05-14T00:00:00+00:00",
            "symbol": "",
            "latest_close": None,
        }
    ]

    outcomes = outcome_tracker.check_alert_outcomes(alert_history, FakeClient())

    assert outcomes[0]["alert_id"] == "BAD-2026-05-14T00:00:00+00:00"
    assert outcomes[0]["highest_return_pct"] is None
    assert outcomes[0]["hit_5pct"] is False
    assert outcomes[0]["error"] == "Missing or invalid latest_close."
