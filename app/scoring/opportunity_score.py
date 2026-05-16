"""Opportunity scoring for combined indicator signals."""


def _safe_score(signal: dict | None) -> int:
    """Read a signal score safely and keep it between 0 and 100."""
    if signal is None:
        return 0

    try:
        score = int(signal.get("score", 0))
    except (TypeError, ValueError):
        score = 0

    return max(0, min(score, 100))


def _safe_risk_score(signal: dict | None) -> int:
    """Read an exhaustion risk score safely and keep it between 0 and 100."""
    if signal is None:
        return 0

    try:
        score = int(signal.get("risk_score", 0))
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
    signal_scores = {
        name: score
        for name, score in component_scores.items()
        if name != "exhaustion_risk"
    }
    aligned = all(score >= 60 for score in signal_scores.values())
    strong_count = sum(score >= 60 for score in signal_scores.values())
    exhaustion_risk = component_scores.get("exhaustion_risk", 0)

    if aligned and exhaustion_risk < 60:
        return (
            f"{classification}. Volume, momentum, breakout, trend, volatility, "
            "move stage, and liquidity signals are aligned."
        )

    if exhaustion_risk >= 60:
        return (
            f"{classification}. Signals are improving, but exhaustion risk is high."
        )

    if strong_count == 0:
        return (
            f"{classification}. Signals are weak across volume, momentum, "
            "breakout, trend, volatility, move stage, and liquidity."
        )

    return f"{classification}. Some signals are improving, but the full signal set is not aligned."


def calculate_opportunity_score(
    volume_signal: dict,
    momentum_signal: dict,
    breakout_signal: dict,
    trend_signal: dict | None = None,
    volatility_signal: dict | None = None,
    move_stage_signal: dict | None = None,
    liquidity_signal: dict | None = None,
    exhaustion_signal: dict | None = None,
) -> dict:
    """Calculate a weighted opportunity score from basic signal indicators."""
    volume_score = _safe_score(volume_signal)
    momentum_score = _safe_score(momentum_signal)
    breakout_score = _safe_score(breakout_signal)
    trend_score = _safe_score(trend_signal)
    volatility_score = _safe_score(volatility_signal)
    move_stage_score = _safe_score(move_stage_signal)
    liquidity_score = _safe_score(liquidity_signal)
    exhaustion_risk_score = _safe_risk_score(exhaustion_signal)

    raw_score = (
        (volume_score * 0.20)
        + (momentum_score * 0.20)
        + (breakout_score * 0.15)
        + (trend_score * 0.15)
        + (volatility_score * 0.10)
        + (move_stage_score * 0.15)
        + (liquidity_score * 0.05)
        - (exhaustion_risk_score * 0.20)
    )
    opportunity_score = max(0, min(round(raw_score), 100))
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
        "trend": trend_score,
        "volatility": volatility_score,
        "move_stage": move_stage_score,
        "liquidity": liquidity_score,
        "exhaustion_risk": exhaustion_risk_score,
    }

    return {
        "opportunity_score": opportunity_score,
        "classification": classification,
        "target_bucket": target_bucket,
        "risk_level": risk_level,
        "summary": _build_summary(classification, component_scores),
        "component_scores": component_scores,
    }
