"""Tests for signal performance analysis."""

from app.analysis.signal_analysis import (
    average,
    build_signal_analysis,
    format_signal_analysis,
    get_nested_value,
    is_completed_outcome,
    percentage,
)


def _outcome(
    alert_id: str,
    *,
    symbol: str = "BTCUSDT",
    status: str = "completed",
    score: int = 80,
    upside: float = 20.0,
    drawdown: float = -5.0,
    move_stage: str = "Stage 3 - Confirmed early momentum",
    continuation_target: str = "+20% continuation watch",
    liquidity_label: str = "Strong",
    exhaustion_risk: str = "Low",
    hit_5: bool = True,
    hit_10: bool = True,
    hit_20: bool = False,
    hit_50: bool = False,
    hit_100: bool = False,
) -> dict:
    return {
        "alert_id": alert_id,
        "symbol": symbol,
        "checkpoints": {"+5%": {"status": status}},
        "opportunity_score": score,
        "max_upside_pct": upside,
        "max_drawdown_pct": drawdown,
        "move_stage_signal": {"stage": move_stage},
        "continuation_target": {"target_bucket": continuation_target},
        "liquidity_signal": {"label": liquidity_label},
        "exhaustion_signal": {"risk_level": exhaustion_risk},
        "hit_5_pct": hit_5,
        "hit_10_pct": hit_10,
        "hit_20_pct": hit_20,
        "hit_50_pct": hit_50,
        "hit_100_pct": hit_100,
    }


def test_build_signal_analysis_handles_empty_outcomes() -> None:
    analysis = build_signal_analysis({})
    text = format_signal_analysis(analysis)

    assert analysis["total_outcomes"] == 0
    assert analysis["completed_outcomes"] == 0
    assert analysis["pending_outcomes"] == 0
    assert analysis["by_move_stage"] == {}
    assert analysis["by_score_band"]["0-39"]["count"] == 0
    assert "Crypto Radar Signal Analysis" in text
    assert "Sample size is too small for strong conclusions." in text
    assert "More data is needed before comparing signal groups." in text


def test_pending_outcomes_are_ignored() -> None:
    outcomes = {
        "BTCUSDT-1": _outcome("BTCUSDT-1", status="completed", upside=15),
        "ETHUSDT-1": _outcome("ETHUSDT-1", status="pending", upside=100),
    }

    analysis = build_signal_analysis(outcomes)

    assert analysis["total_outcomes"] == 2
    assert analysis["completed_outcomes"] == 1
    assert analysis["pending_outcomes"] == 1
    assert analysis["by_move_stage"]["Stage 3 - Confirmed early momentum"]["count"] == 1
    assert analysis["by_move_stage"]["Stage 3 - Confirmed early momentum"][
        "average_max_upside_pct"
    ] == 15.0


def test_grouping_by_score_band_and_hit_rates() -> None:
    outcomes = {
        "A": _outcome("A", score=35, hit_5=True, hit_10=False, hit_20=False),
        "B": _outcome("B", score=45, hit_5=True, hit_10=True, hit_20=False),
        "C": _outcome("C", score=65, hit_5=True, hit_10=True, hit_20=True),
        "D": _outcome("D", score=75, hit_5=False, hit_10=False, hit_20=False),
        "E": _outcome("E", score=85, hit_5=True, hit_10=False, hit_20=False),
        "F": _outcome("F", score=95, hit_5=True, hit_10=True, hit_20=True),
    }

    analysis = build_signal_analysis(outcomes)

    assert analysis["by_score_band"]["0-39"]["count"] == 1
    assert analysis["by_score_band"]["40-59"]["count"] == 1
    assert analysis["by_score_band"]["60-69"]["hit_20_rate_pct"] == 100.0
    assert analysis["by_score_band"]["70-79"]["hit_5_rate_pct"] == 0.0
    assert analysis["by_score_band"]["80-89"]["average_opportunity_score"] == 85.0
    assert analysis["by_score_band"]["90-100"]["hit_10_rate_pct"] == 100.0


def test_nested_metadata_and_unknown_group_fallbacks() -> None:
    outcomes = {
        "A": {
            "alert_id": "A",
            "checkpoints": [{"status": "completed"}],
            "opportunity_score": 72,
            "highest_return_pct": 12,
            "max_drawdown_pct": -3,
            "metadata": {
                "move_stage_signal": {"stage": "Stage 2 - Early momentum"},
                "liquidity_signal": {"label": "Good"},
            },
            "target_bucket": "+20% continuation watch",
            "hit_5pct": True,
        },
        "B": {
            "alert_id": "B",
            "checkpoints": [{"status": "completed"}],
            "opportunity_score": 72,
            "max_upside_pct": 5,
            "max_drawdown_pct": -4,
        },
    }

    analysis = build_signal_analysis(outcomes)

    assert analysis["by_move_stage"]["Stage 2 - Early momentum"]["count"] == 1
    assert analysis["by_liquidity_label"]["Good"]["count"] == 1
    assert analysis["by_continuation_target"]["+20% continuation watch"]["count"] == 1
    assert analysis["by_exhaustion_risk_level"]["Unknown"]["count"] == 2
    assert analysis["by_move_stage"]["Unknown"]["count"] == 1


def test_early_observations_identify_best_and_weakest_groups_with_small_sample() -> None:
    outcomes = {}

    for index in range(3):
        outcomes[f"A-{index}"] = _outcome(
            f"A-{index}",
            move_stage="Stage 2 - Early momentum",
            upside=25,
            drawdown=-4,
        )
        outcomes[f"B-{index}"] = _outcome(
            f"B-{index}",
            move_stage="Stage 5 - Extended move",
            upside=8,
            drawdown=-18,
        )

    analysis = build_signal_analysis(outcomes)
    observations = "\n".join(analysis["early_observations"])

    assert analysis["completed_outcomes"] == 6
    assert "Sample size is too small for strong conclusions." in observations
    assert "Best upside group so far: Move Stage / Stage 2 - Early momentum" in observations
    assert "Weakest drawdown group so far: Move Stage / Stage 5 - Extended move" in observations


def test_helper_functions_are_defensive() -> None:
    assert is_completed_outcome({"checkpoints": {"status": "completed"}}) is True
    assert is_completed_outcome({"checkpoints": {"status": "pending"}}) is False
    assert percentage(1, 4) == 25.0
    assert percentage(1, 0) == 0.0
    assert average([1.0, 2.0, 3.0]) == 2.0
    assert average([]) == 0.0
    assert get_nested_value({"a": {"b": 2}}, ["a", "b"]) == 2
    assert get_nested_value({"a": {}}, ["a", "b"], default="x") == "x"
