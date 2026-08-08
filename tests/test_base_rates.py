"""Tests for historical alert-type follow-through base rates."""

from app.analysis import base_rates


def _alert_history_rows():
    return [
        {"id": "BTCUSDT-1", "alert_type": "Active Breakout Alert"},
        {"id": "BTCUSDT-2", "alert_type": "Active Breakout Alert"},
        {"id": "BTCUSDT-3", "alert_type": "Parabolic Watch Alert"},
        {"id": "BTCUSDT-4", "alert_type": "Continuation Alert"},
        # No matching outcome for this one -- shouldn't appear in the join.
        {"id": "BTCUSDT-5", "alert_type": "Active Breakout Alert"},
    ]


def _alert_outcomes():
    return {
        "BTCUSDT-1": {"hit_5pct": True, "hit_10pct": True, "hit_20pct": False},
        "BTCUSDT-2": {"hit_5pct": True, "hit_10pct": False, "hit_20pct": False},
        "BTCUSDT-3": {"hit_5pct": True, "hit_10pct": True, "hit_20pct": True},
        "BTCUSDT-4": {"hit_5pct": False, "hit_10pct": False, "hit_20pct": False},
        # No matching alert_history row -- shouldn't appear in the join.
        "UNKNOWNUSDT-1": {"hit_5pct": True, "hit_10pct": True, "hit_20pct": True},
    }


def test_join_outcomes_with_alert_type_only_keeps_matched_rows() -> None:
    joined = base_rates.join_outcomes_with_alert_type(_alert_history_rows(), _alert_outcomes())

    alert_ids = {row.get("alert_type") for row in joined}
    assert len(joined) == 4  # BTCUSDT-5 and UNKNOWNUSDT-1 excluded (no match)
    assert "Active Breakout Alert" in alert_ids
    assert "Parabolic Watch Alert" in alert_ids
    assert "Continuation Alert" in alert_ids


def test_compute_hit_rate_by_alert_type_at_10pct_threshold() -> None:
    joined = base_rates.join_outcomes_with_alert_type(_alert_history_rows(), _alert_outcomes())

    stats = base_rates.compute_hit_rate_by_alert_type(joined, hit_threshold_pct=10)

    # Active Breakout: 2 alerts, 1 hit -> 50%.
    assert stats["Active Breakout Alert"]["sample_size"] == 2
    assert stats["Active Breakout Alert"]["hit_count"] == 1
    assert stats["Active Breakout Alert"]["hit_rate_pct"] == 50.0

    # Parabolic Watch: 1 alert, 1 hit -> 100%.
    assert stats["Parabolic Watch Alert"]["sample_size"] == 1
    assert stats["Parabolic Watch Alert"]["hit_rate_pct"] == 100.0

    # Continuation: 1 alert, 0 hits -> 0%.
    assert stats["Continuation Alert"]["hit_rate_pct"] == 0.0


def test_compute_hit_rate_flags_low_confidence_small_samples() -> None:
    joined = base_rates.join_outcomes_with_alert_type(_alert_history_rows(), _alert_outcomes())

    stats = base_rates.compute_hit_rate_by_alert_type(joined, hit_threshold_pct=10)

    # Only 1-2 samples per type here -- well under MIN_SAMPLE_SIZE_FOR_CONFIDENCE.
    assert stats["Active Breakout Alert"]["low_confidence"] is True
    assert stats["Parabolic Watch Alert"]["low_confidence"] is True


def test_compute_hit_rate_not_low_confidence_above_minimum_sample() -> None:
    joined = [
        {"alert_type": "Active Breakout Alert", "hit_10pct": i % 3 == 0}
        for i in range(base_rates.MIN_SAMPLE_SIZE_FOR_CONFIDENCE)
    ]

    stats = base_rates.compute_hit_rate_by_alert_type(joined, hit_threshold_pct=10)

    assert stats["Active Breakout Alert"]["sample_size"] == base_rates.MIN_SAMPLE_SIZE_FOR_CONFIDENCE
    assert stats["Active Breakout Alert"]["low_confidence"] is False


def test_format_base_rate_line_includes_rate_and_sample_size() -> None:
    stats_by_type = {
        "Active Breakout Alert": {
            "sample_size": 34,
            "hit_count": 12,
            "hit_rate_pct": 35.3,
            "low_confidence": False,
        }
    }

    line = base_rates.format_base_rate_line("Active Breakout Alert", stats_by_type)

    assert "35%" in line
    assert "12/34" in line
    assert "+10%" in line
    assert "small sample" not in line


def test_format_base_rate_line_flags_small_sample() -> None:
    stats_by_type = {
        "Parabolic Watch Alert": {
            "sample_size": 3,
            "hit_count": 2,
            "hit_rate_pct": 66.7,
            "low_confidence": True,
        }
    }

    line = base_rates.format_base_rate_line("Parabolic Watch Alert", stats_by_type)

    assert "small sample" in line


def test_format_base_rate_line_handles_missing_alert_type() -> None:
    line = base_rates.format_base_rate_line("Unknown Alert Type", {})

    assert "No historical track record" in line
