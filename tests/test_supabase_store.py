"""Tests for Supabase row-to-dict mapping helpers."""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.storage import supabase_store


def test_alert_history_row_maps_to_app_record_shape() -> None:
    alerted_at = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
    created_at = datetime(2026, 5, 14, 12, 1, tzinfo=timezone.utc)

    record = supabase_store._alert_history_row_to_record(
        {
            "id": "BTCUSDT-2026-05-14T12:00:00+00:00",
            "symbol": "BTCUSDT",
            "alerted_at": alerted_at,
            "latest_close": Decimal("100.25"),
            "opportunity_score": 72,
            "classification": "Watchlist",
            "target_bucket": "+20% momentum setup",
            "risk_level": "Medium",
            "summary": "Watchlist. Some signals are improving.",
            "component_scores": {"volume": 80},
            "volume_signal": {"score": 80},
            "momentum_signal": {"score": 70},
            "breakout_signal": {"score": 65},
            "trend_signal": {"score": 75},
            "volatility_signal": {"score": 60},
            "telegram_sent": True,
            "created_at": created_at,
        }
    )

    assert record["id"] == "BTCUSDT-2026-05-14T12:00:00+00:00"
    assert record["alerted_at"] == alerted_at.isoformat()
    assert record["latest_close"] == 100.25
    assert record["component_scores"] == {"volume": 80}
    assert record["telegram_sent"] is True
    assert record["created_at"] == created_at.isoformat()


def test_alert_outcome_row_maps_to_app_record_shape() -> None:
    checked_at = datetime(2026, 5, 14, 13, 0, tzinfo=timezone.utc)

    record = supabase_store._alert_outcome_row_to_record(
        {
            "alert_id": "BTCUSDT-2026-05-14T12:00:00+00:00",
            "symbol": "BTCUSDT",
            "alerted_at": "2026-05-14T12:00:00+00:00",
            "entry_price": Decimal("100"),
            "opportunity_score": 72,
            "classification": "Watchlist",
            "target_bucket": "+20% momentum setup",
            "risk_level": "Medium",
            "checkpoints": {"+5%": True},
            "max_high_after_alert": Decimal("121"),
            "max_upside_pct": Decimal("21"),
            "min_low_after_alert": Decimal("98"),
            "max_drawdown_pct": Decimal("-2"),
            "hit_5_pct": True,
            "hit_10_pct": True,
            "hit_20_pct": True,
            "hit_50_pct": False,
            "hit_100_pct": False,
            "last_checked_at": checked_at,
            "updated_at": checked_at,
        }
    )

    assert record["alert_id"] == "BTCUSDT-2026-05-14T12:00:00+00:00"
    assert record["checked_at"] == checked_at.isoformat()
    assert record["alert_latest_close"] == 100.0
    assert record["highest_price"] == 121.0
    assert record["highest_return_pct"] == 21.0
    assert record["hit_5pct"] is True
    assert record["hit_5_pct"] is True
    assert record["hit_50pct"] is False


def test_supabase_store_does_not_select_record_column() -> None:
    source = Path(supabase_store.__file__).read_text(encoding="utf-8")

    assert "SELECT record" not in source
    assert "SELECT alert_id, record" not in source
