"""Tests for opportunity scoring."""

from app.scoring.opportunity_score import calculate_opportunity_score


def test_calculate_opportunity_score_weights_indicator_scores() -> None:
    result = calculate_opportunity_score(
        {"score": 60},
        {"score": 40},
        {"score": 0},
    )

    assert result["opportunity_score"] == 20
    assert result["classification"] == "Ignore"
    assert result["target_bucket"] == "No clear upside setup"
    assert result["risk_level"] == "Low"
    assert result["component_scores"] == {
        "volume": 60,
        "momentum": 40,
        "breakout": 0,
        "trend": 0,
        "volatility": 0,
        "move_stage": 0,
        "liquidity": 0,
        "exhaustion_risk": 0,
    }


def test_calculate_opportunity_score_returns_plus_50_bucket_for_strong_setup() -> None:
    result = calculate_opportunity_score(
        {"score": 100},
        {"score": 80},
        {"score": 80},
        {"score": 100},
        {"score": 100},
        {"score": 100},
        {"score": 100},
        {"risk_score": 0},
    )

    assert result["opportunity_score"] == 93
    assert result["classification"] == "Strong watch"
    assert result["target_bucket"] == "+50% speculative setup"
    assert result["risk_level"] == "High"
    assert "aligned" in result["summary"]


def test_calculate_opportunity_score_treats_missing_scores_as_zero() -> None:
    result = calculate_opportunity_score({}, {"score": 70}, {})

    assert result["opportunity_score"] == 14
    assert result["classification"] == "Ignore"
    assert result["component_scores"] == {
        "volume": 0,
        "momentum": 70,
        "breakout": 0,
        "trend": 0,
        "volatility": 0,
        "move_stage": 0,
        "liquidity": 0,
        "exhaustion_risk": 0,
    }


def test_calculate_opportunity_score_subtracts_exhaustion_penalty() -> None:
    result = calculate_opportunity_score(
        {"score": 100},
        {"score": 100},
        {"score": 100},
        {"score": 100},
        {"score": 100},
        {"score": 100},
        {"score": 100},
        {"risk_score": 100},
    )

    assert result["opportunity_score"] == 80
    assert result["component_scores"]["exhaustion_risk"] == 100
