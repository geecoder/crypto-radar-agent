"""Tests for speculative early-runner detection and paper handling.

The Speculative Early Runner alert type was retired as a live routing lane
in Block 3 (its move-window and liquidity-carve-out folded into the unified
Early Pump/Active Breakout/Continuation range). `evaluate_speculative_early_runner`
remains as a standalone diagnostic-only function; these tests cover that and
the surrounding reporting/market-filter code that still references the
(historical) alert type."""

from app.binance.market_filter import select_scan_universe
from app.diagnostics import format_diagnostic_report
from app.indicators.explosive_mover import (
    classify_explosive_mover,
    evaluate_speculative_early_runner,
)
from app.reporting import format_alert_message


def _signal(score: int) -> dict:
    return {"score": score}


def _move_signal(move_pct: float) -> dict:
    return {"move_from_recent_low_pct": move_pct, "score": 45}


def _changes(
    change_1h: float = 2.5,
    change_2h: float = 4.5,
    change_4h: float = 6.5,
    change_24h: float = 8,
) -> dict:
    return {
        "change_15m_pct": 0.5,
        "change_30m_pct": 1,
        "change_1h_pct": change_1h,
        "change_2h_pct": change_2h,
        "change_4h_pct": change_4h,
        "change_24h_pct": change_24h,
    }


def _volume_acceleration(
    ratio_1h: float = 1.3,
    ratio_2h: float = 1.1,
    score: int = 10,
) -> dict:
    return {
        "score": score,
        "volume_acceleration_1h_ratio": ratio_1h,
        "volume_acceleration_2h_ratio": ratio_2h,
    }


def _liquidity(label: str = "Thin", score: int = 40) -> dict:
    return {
        "score": score,
        "label": label,
        "quote_volume": 1_500_000,
    }


def _exhaustion(level: str = "Medium") -> dict:
    return {"risk_level": level, "risk_score": 30}


def _speculative_alert() -> dict:
    result = {
        "id": "alert-pond-early",
        "symbol": "PONDUSDT",
        "latest_close": 0.02,
        "alert_type": "Speculative Early Runner Alert",
        "opportunity": {
            "opportunity_score": 55,
            "classification": "High-risk watch",
            "target_bucket": "High-risk early runner watch",
            "risk_level": "High",
            "summary": "Thin-liquidity coin showing early abnormal movement.",
        },
        "move_stage_signal": _move_signal(8),
        "recent_price_changes": _changes(),
        "volume_acceleration": _volume_acceleration(ratio_1h=2.1),
        "liquidity_signal": _liquidity(),
        "exhaustion_signal": _exhaustion(),
        "explosive_mover": {
            "alert_type": "Speculative Early Runner Alert",
            "should_alert": True,
            "potential_bucket": "High-risk early runner watch",
            "confidence": "Low",
            "reason": (
                "Thin-liquidity coin showing early abnormal movement. This is "
                "not a clean continuation setup, but it may be worth monitoring "
                "before it becomes parabolic."
            ),
        },
    }
    # generate_trade_plan() no longer has a branch for this retired alert
    # type (Block 3) — build the trade_plan shape directly, matching what a
    # historical alert_history row's stored trade_plan JSON looks like.
    result["trade_plan"] = {
        "trade_plan_type": "speculative_early_runner",
        "should_paper_trade": True,
        "speculative_paper_eligible": True,
        "speculative_paper_reason": "Speculative early runner paper trade eligible.",
        "risk_note": (
            "High risk. Thin-liquidity early runner. This is not a clean "
            "continuation setup."
        ),
        "reason": "Speculative early runner paper trade eligible.",
    }
    return result


def test_speculative_early_runner_does_not_qualify_with_high_exhaustion() -> None:
    status = evaluate_speculative_early_runner(
        _move_signal(8),
        _changes(),
        _volume_acceleration(),
        _liquidity(),
        _exhaustion("High"),
    )

    assert status["qualified"] is False
    assert "exhaustion risk is High" in status["reason"]


def test_move_above_20_pct_does_not_become_active_breakout() -> None:
    """Active Breakout's window narrowed to 10-20% (was 10-30%) — a 25% move
    with otherwise-qualifying signals now falls through to no explosive alert,
    letting the score-based Continuation Alert fallback (3-50% window) claim
    it instead, rather than a separate lane with its own thresholds."""
    result = classify_explosive_mover(
        _move_signal(25),
        _changes(change_1h=5, change_4h=12, change_24h=18),
        _volume_acceleration(score=60),
        _liquidity(),
        _exhaustion(),
        _signal(60),
        _signal(60),
        _signal(60),
    )

    assert result["alert_type"] == "No explosive mover alert"


def test_telegram_and_diagnostic_output_include_speculative_runner() -> None:
    alert = _speculative_alert()

    message = format_alert_message([alert])
    report = format_diagnostic_report(alert, alert_threshold=60)

    assert "Alert Type: Speculative Early Runner Alert" in message
    assert (
        "High risk. Thin-liquidity early runner. This is not a clean "
        "continuation setup."
    ) in message
    assert "Paper eligibility: Yes" in message
    assert "Would trigger Speculative Early Runner Alert? true" in report
    assert "Speculative Early Runner reason:" in report


def test_scan_universe_force_includes_thin_early_runners() -> None:
    selected = select_scan_universe(
        active_symbols=["PONDUSDT", "BTCUSDT"],
        tickers_24hr=[
            {
                "symbol": "BTCUSDT",
                "quoteVolume": "500000000",
                "priceChangePercent": "1",
                "count": "1000000",
            },
            {
                "symbol": "PONDUSDT",
                "quoteVolume": "1000000",
                "priceChangePercent": "5",
                "count": "1000",
            },
        ],
        max_priority_symbols=1,
        max_universe_symbols=150,
    )

    assert "PONDUSDT" in selected
