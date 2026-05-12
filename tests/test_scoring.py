"""Tests for opportunity scoring scaffold."""

from app.scoring.opportunity_score import calculate_opportunity_score


def test_calculate_opportunity_score_returns_neutral_score() -> None:
    assert calculate_opportunity_score() == 0
