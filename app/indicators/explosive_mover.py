"""Explosive mover detection for high-activity market alerts."""

PRICE_CHANGE_PERIODS = {
    "change_15m_pct": 1,
    "change_30m_pct": 2,
    "change_1h_pct": 4,
    "change_2h_pct": 8,
    "change_4h_pct": 16,
    "change_24h_pct": 96,
}


def calculate_recent_price_changes(df) -> dict:
    """Calculate recent percentage changes from 15-minute candles."""
    changes = {"name": "recent_price_changes"}

    for key, candles_back in PRICE_CHANGE_PERIODS.items():
        changes[key] = _price_change_pct(df, candles_back)

    return changes


def calculate_volume_acceleration(df) -> dict:
    """Compare recent volume blocks against the preceding volume blocks."""
    latest_1h_volume, previous_1h_volume, ratio_1h = _volume_block_stats(
        df,
        latest_window=4,
        previous_window=4,
    )
    latest_2h_volume, previous_2h_volume, ratio_2h = _volume_block_stats(
        df,
        latest_window=8,
        previous_window=8,
    )
    score = max(_score_volume_ratio(ratio_1h), _score_volume_ratio(ratio_2h))

    return {
        "name": "volume_acceleration",
        "latest_1h_volume": latest_1h_volume,
        "previous_1h_volume": previous_1h_volume,
        "latest_2h_volume": latest_2h_volume,
        "previous_2h_volume": previous_2h_volume,
        "volume_acceleration_1h_ratio": ratio_1h,
        "volume_acceleration_2h_ratio": ratio_2h,
        "score": score,
        "reason": (
            f"Recent volume acceleration is {ratio_1h:.2f}x over 1h "
            f"and {ratio_2h:.2f}x over 2h."
        ),
    }


def classify_explosive_mover(
    move_stage_signal: dict,
    recent_changes: dict,
    volume_acceleration: dict,
    liquidity_signal: dict,
    exhaustion_signal: dict,
    breakout_signal: dict,
    trend_signal: dict,
    volatility_signal: dict,
) -> dict:
    """Classify whether a symbol deserves a high-activity mover alert."""
    move_pct = _safe_float(move_stage_signal.get("move_from_recent_low_pct"))
    change_1h = _safe_float(recent_changes.get("change_1h_pct"))
    change_2h = _safe_float(recent_changes.get("change_2h_pct"))
    change_4h = _safe_float(recent_changes.get("change_4h_pct"))
    change_24h = _safe_float(recent_changes.get("change_24h_pct"))
    volume_score = _safe_score(volume_acceleration)
    liquidity_score = _safe_score(liquidity_signal)
    trend_score = _safe_score(trend_signal)
    volatility_score = _safe_score(volatility_signal)
    breakout_score = _safe_score(breakout_signal)
    exhaustion_level = str(exhaustion_signal.get("risk_level", "Low"))
    component_scores = {
        "move_from_recent_low_pct": round(move_pct, 2),
        "change_1h_pct": round(change_1h, 2),
        "change_2h_pct": round(change_2h, 2),
        "change_4h_pct": round(change_4h, 2),
        "change_24h_pct": round(change_24h, 2),
        "volume_acceleration": volume_score,
        "liquidity": liquidity_score,
        "exhaustion_risk": _safe_risk_score(exhaustion_signal),
        "breakout": breakout_score,
        "trend": trend_score,
        "volatility": volatility_score,
    }

    if (move_pct > 50 or change_4h >= 30 or change_24h >= 50) and liquidity_score >= 40:
        confidence = "High" if volume_score >= 80 and liquidity_score >= 60 else "Medium"
        return _classification(
            alert_type="Parabolic Watch Alert",
            should_alert=True,
            risk_level="Very High",
            potential_bucket="High-risk parabolic watch",
            confidence=confidence,
            reason=(
                "This is not a clean entry signal. It is a high-risk market "
                "activity alert."
            ),
            component_scores=component_scores,
        )

    if (
        move_pct > 10
        and move_pct <= 30
        and (change_1h >= 5 or change_4h >= 12)
        and volume_score >= 60
        and liquidity_score >= 40
        and trend_score >= 60
        and volatility_score >= 60
    ):
        return _classification(
            alert_type="Active Breakout Alert",
            should_alert=True,
            risk_level="High",
            potential_bucket="+50% high-volatility continuation watch",
            confidence="High" if volume_score >= 80 and breakout_score >= 60 else "Medium",
            reason=(
                "Active breakout conditions are present with accelerated "
                "volume, supportive trend, and elevated volatility."
            ),
            component_scores=component_scores,
        )

    if (
        move_pct >= 3
        and move_pct <= 10
        and (change_1h >= 3 or change_2h >= 5)
        and volume_score >= 40
        and liquidity_score >= 40
        and exhaustion_level != "High"
        and trend_score >= 60
    ):
        return _classification(
            alert_type="Early Pump Alert",
            should_alert=True,
            risk_level="Medium",
            potential_bucket="+20% early continuation watch",
            confidence="High" if volume_score >= 60 and liquidity_score >= 60 else "Medium",
            reason=(
                "Early pump conditions are present with rising price, "
                "accelerating volume, acceptable liquidity, and supportive trend."
            ),
            component_scores=component_scores,
        )

    return _classification(
        alert_type="No explosive mover alert",
        should_alert=False,
        risk_level="Low",
        potential_bucket="No explosive mover setup",
        confidence="Low",
        reason="Explosive mover conditions are not strong enough for a separate alert.",
        component_scores=component_scores,
    )


def _classification(
    alert_type: str,
    should_alert: bool,
    risk_level: str,
    potential_bucket: str,
    confidence: str,
    reason: str,
    component_scores: dict,
) -> dict:
    """Build a stable explosive mover classification payload."""
    return {
        "name": "explosive_mover",
        "alert_type": alert_type,
        "should_alert": should_alert,
        "risk_level": risk_level,
        "potential_bucket": potential_bucket,
        "confidence": confidence,
        "reason": reason,
        "component_scores": component_scores,
    }


def _price_change_pct(df, candles_back: int) -> float:
    """Return percentage change from N candles back to the latest close."""
    if df is None or df.empty or len(df) <= candles_back:
        return 0.0

    start_price = _safe_float(df["close"].iloc[-candles_back - 1])
    latest_price = _safe_float(df["close"].iloc[-1])

    if start_price <= 0:
        return 0.0

    return ((latest_price - start_price) / start_price) * 100


def _volume_block_stats(
    df,
    latest_window: int,
    previous_window: int,
) -> tuple[float, float, float]:
    """Return latest volume, previous volume, and their ratio."""
    required_rows = latest_window + previous_window

    if df is None or df.empty or len(df) < required_rows:
        return 0.0, 0.0, 0.0

    latest_volume = float(df["volume"].iloc[-latest_window:].sum())
    previous_start = -latest_window - previous_window
    previous_end = -latest_window
    previous_volume = float(df["volume"].iloc[previous_start:previous_end].sum())

    if previous_volume <= 0:
        return latest_volume, previous_volume, 0.0

    return latest_volume, previous_volume, latest_volume / previous_volume


def _score_volume_ratio(ratio: float) -> int:
    """Convert a volume acceleration ratio into a signal score."""
    if ratio >= 5:
        return 100
    if ratio >= 3:
        return 80
    if ratio >= 2:
        return 60
    if ratio >= 1.5:
        return 40
    return 10


def _safe_score(signal: dict | None) -> int:
    """Read a standard signal score safely."""
    if not signal:
        return 0

    try:
        score = int(signal.get("score", 0))
    except (TypeError, ValueError):
        score = 0

    return max(0, min(score, 100))


def _safe_risk_score(signal: dict | None) -> int:
    """Read an exhaustion risk score safely."""
    if not signal:
        return 0

    try:
        score = int(signal.get("risk_score", 0))
    except (TypeError, ValueError):
        score = 0

    return max(0, min(score, 100))


def _safe_float(value) -> float:
    """Read a float safely."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
