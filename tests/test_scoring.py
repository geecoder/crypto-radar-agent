"""Tests for opportunity scoring."""

from app.scoring.opportunity_score import calculate_opportunity_score


def test_calculate_opportunity_score_weights_indicator_scores() -> None:
    # volume=60 × 0.15 + momentum=40 × 0.22 = 9.0 + 8.8 = 17.8 → 18
    result = calculate_opportunity_score(
        {"score": 60},
        {"score": 40},
        {"score": 0},
    )

    assert result["opportunity_score"] == 18
    assert result["classification"] == "Low signal"
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
    # vol=100×.15 + mom=80×.22 + brk=80×.12 + trn=100×.10 + vlt=100×.22
    # + ms=100×.10 + liq=100×.07 - exh=0
    # = 15 + 17.6 + 9.6 + 10 + 22 + 10 + 7 = 91.2 → 91
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

    assert result["opportunity_score"] == 91
    assert result["classification"] == "Strong watch"
    assert result["target_bucket"] == "+50% speculative setup"
    assert result["risk_level"] == "High"
    assert "aligned" in result["summary"]


def test_calculate_opportunity_score_treats_missing_scores_as_zero() -> None:
    # momentum=70 × 0.22 = 15.4 → 15
    result = calculate_opportunity_score({}, {"score": 70}, {})

    assert result["opportunity_score"] == 15
    assert result["classification"] == "Low signal"
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
    # all=100: 100*(0.15+0.22+0.12+0.10+0.22+0.10+0.07) - 100*0.10
    # = 100*0.98 - 10 = 98 - 10 = 88
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

    assert result["opportunity_score"] == 88
    assert result["component_scores"]["exhaustion_risk"] == 100
