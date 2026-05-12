"""Opportunity scoring for combined indicator signals."""


def _safe_score(signal: dict) -> int:
    """Read a signal score safely and keep it between 0 and 100."""
    try:
        score = int(signal.get("score", 0))
    except (TypeError, ValueError):
        score = 0

    return max(0, min(score, 100))


def _classify_score(score: int) -> str:
    """Return the plain-English classification for an opportunity score."""
    if score >= 80:
        return "Strong watch"
    if score >= 70:
        return "Watchlist"
    if score >= 60:
        return "Early signal"
    if score >= 40:
        return "Weak signal"
    return "Ignore"


def _get_target_bucket(score: int, momentum_score: int, breakout_score: int) -> str:
    """Return the target bucket for the combined score."""
    if score >= 85 and breakout_score >= 80 and momentum_score >= 80:
        return "+50% speculative setup"
    if score >= 70:
        return "+20% momentum setup"
    if score >= 60:
        return "Early +20% watch"
    return "No clear upside setup"


def _get_risk_level(score: int, target_bucket: str) -> str:
    """Return the risk level for the opportunity score."""
    if "+50%" in target_bucket:
        return "High"
    if score >= 70:
        return "Medium"
    if score >= 40:
        return "Medium-Low"
    return "Low"


def _build_summary(classification: str, component_scores: dict[str, int]) -> str:
    """Build a short plain-English summary for the score result."""
    aligned = all(score >= 60 for score in component_scores.values())

    if aligned:
        return f"{classification}. Volume, momentum, and breakout signals are aligned."

    return f"{classification}. Volume, momentum, and breakout signals are not aligned."


def calculate_opportunity_score(
    volume_signal: dict,
    momentum_signal: dict,
    breakout_signal: dict,
) -> dict:
    """Calculate a weighted opportunity score from basic signal indicators."""
    volume_score = _safe_score(volume_signal)
    momentum_score = _safe_score(momentum_signal)
    breakout_score = _safe_score(breakout_signal)

    opportunity_score = round(
        (volume_score * 0.40)
        + (momentum_score * 0.30)
        + (breakout_score * 0.30)
    )
    classification = _classify_score(opportunity_score)
    target_bucket = _get_target_bucket(
        opportunity_score,
        momentum_score,
        breakout_score,
    )
    risk_level = _get_risk_level(opportunity_score, target_bucket)
    component_scores = {
        "volume": volume_score,
        "momentum": momentum_score,
        "breakout": breakout_score,
    }

    return {
        "opportunity_score": opportunity_score,
        "classification": classification,
        "target_bucket": target_bucket,
        "risk_level": risk_level,
        "summary": _build_summary(classification, component_scores),
        "component_scores": component_scores,
    }
