"""Continuation target helpers."""


def calculate_continuation_target(
    opportunity_score: int,
    move_stage_signal: dict,
    volume_signal: dict,
    momentum_signal: dict,
    breakout_signal: dict,
    trend_signal: dict,
    volatility_signal: dict,
    liquidity_signal: dict,
    exhaustion_signal: dict,
) -> dict:
    """Estimate whether an early move can continue toward larger targets."""
    move_pct = _safe_float(move_stage_signal.get("move_from_recent_low_pct"))
    move_stage_score = _safe_score(move_stage_signal)
    volatility_score = _safe_score(volatility_signal)
    liquidity_score = _safe_score(liquidity_signal)
    trend_score = _safe_score(trend_signal)
    exhaustion_level = exhaustion_signal.get("risk_level", "Low")

    if exhaustion_level == "High" and move_pct >= 20:
        target_bucket = "Avoid / late chase"
        confidence = "Low"
    elif (
        opportunity_score >= 85
        and move_stage_score >= 70
        and volatility_score >= 80
        and liquidity_score >= 40
    ):
        target_bucket = "+100% speculative momentum watch"
        confidence = "High"
    elif opportunity_score >= 78 and move_stage_score >= 70 and volatility_score >= 60:
        target_bucket = "+50% high-volatility watch"
        confidence = "Medium"
    elif opportunity_score >= 65 and move_stage_score >= 60:
        target_bucket = "+20% continuation watch"
        confidence = "Medium"
    elif 0 <= move_pct <= 10 and trend_score >= 60:
        target_bucket = "Early move watch"
        confidence = "Low"
    else:
        target_bucket = "No clear continuation setup"
        confidence = "Low"

    return {
        "name": "continuation_target",
        "target_bucket": target_bucket,
        "confidence": confidence,
        "reason": (
            f"{target_bucket}: opportunity score {opportunity_score}, "
            f"move {move_pct:.2f}%, volatility score {volatility_score}, "
            f"liquidity score {liquidity_score}, exhaustion risk {exhaustion_level}."
        ),
    }


def _safe_score(signal: dict | None) -> int:
    """Read a standard indicator score safely."""
    if not signal:
        return 0

    try:
        score = int(signal.get("score", 0))
    except (TypeError, ValueError):
        score = 0

    return max(0, min(score, 100))


def _safe_float(value) -> float:
    """Read a float safely."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
