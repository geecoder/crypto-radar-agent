"""Advisory trade-plan generation for alert candidates.

This module only produces monitoring and paper-trading guidance. It never
places real orders and never touches private exchange APIs.
"""

from app.trading.strategy_config import (
    PaperTradingStrategy,
    get_parabolic_paper_strategy,
    get_speculative_early_runner_strategy,
)

DEFAULT_MAX_HOLD_HOURS = 48
PAPER_TRADE_BLOCKED_LIQUIDITY_LABELS = {"thin", "very thin"}


def generate_trade_plan(result: dict) -> dict:
    """Generate a structured advisory trade plan from one scan result."""
    symbol = str(result.get("symbol") or "UNKNOWN")
    alert_type = _get_alert_type(result)
    latest_close = _safe_float(result.get("latest_close"), default=0.0) or 0.0

    if alert_type == "Early Pump Alert":
        return _build_directional_plan(
            result=result,
            symbol=symbol,
            alert_type=alert_type,
            latest_close=latest_close,
            trade_plan_type="early_momentum_continuation",
            recommended_action="Monitor for confirmation or pullback",
            entry_approach="Wait for 15m candle confirmation or shallow pullback",
            entry_zone_low_pct=-3,
            stop_loss_pct=-5,
            take_profit_1_pct=8,
            take_profit_2_pct=15,
            take_profit_3_pct=20,
            should_paper_trade=_has_tradeable_liquidity_and_exhaustion(result),
            reason=(
                "Early pump alert plan; paper trade requires liquidity above "
                "Thin and exhaustion risk below High."
            ),
        )

    if alert_type == "Active Breakout Alert":
        return _build_directional_plan(
            result=result,
            symbol=symbol,
            alert_type=alert_type,
            latest_close=latest_close,
            trade_plan_type="active_breakout_continuation",
            recommended_action=(
                "Monitor breakout continuation; avoid chasing large candle tops"
            ),
            entry_approach=(
                "Prefer retest of breakout zone or 15m close above resistance"
            ),
            entry_zone_low_pct=-4,
            stop_loss_pct=-6,
            take_profit_1_pct=10,
            take_profit_2_pct=20,
            take_profit_3_pct=35,
            should_paper_trade=_has_tradeable_liquidity_and_exhaustion(result),
            reason=(
                "Active breakout alert plan; paper trade requires liquidity "
                "above Thin and exhaustion risk below High."
            ),
        )

    if alert_type == "Speculative Early Runner Alert":
        return _build_speculative_early_runner_plan(result, symbol, latest_close)

    if alert_type == "Continuation Alert":
        should_paper_trade, reason = _existing_paper_trading_rules_pass(result)
        return _build_directional_plan(
            result=result,
            symbol=symbol,
            alert_type=alert_type,
            latest_close=latest_close,
            trade_plan_type="standard_continuation",
            recommended_action="Monitor for continuation setup",
            entry_approach="Use confirmation candle or pullback entry",
            entry_zone_low_pct=-2,
            stop_loss_pct=-5,
            take_profit_1_pct=8,
            take_profit_2_pct=15,
            take_profit_3_pct=20,
            should_paper_trade=should_paper_trade,
            reason=reason,
        )

    if alert_type == "Parabolic Watch Alert":
        should_paper_trade, reason, strategy = _parabolic_paper_trade_eligibility(
            result
        )

        if should_paper_trade:
            return {
                **_base_plan(symbol, alert_type, latest_close),
                "trade_plan_type": "parabolic_high_risk_paper",
                "recommended_action": "High-risk paper simulation only",
                "entry_approach": (
                    "Only simulate if momentum re-accelerates or "
                    "pullback/retest holds"
                ),
                "entry_zone_low": round_price(latest_close),
                "entry_zone_high": round_price(latest_close),
                "stop_loss_price": _price_at_pct(
                    latest_close,
                    strategy.stop_loss_pct,
                ),
                "stop_loss_pct": strategy.stop_loss_pct,
                "take_profit_1_price": _price_at_pct(
                    latest_close,
                    strategy.take_profit_1_pct,
                ),
                "take_profit_1_pct": strategy.take_profit_1_pct,
                "take_profit_2_price": _price_at_pct(
                    latest_close,
                    strategy.take_profit_2_pct,
                ),
                "take_profit_2_pct": strategy.take_profit_2_pct,
                "take_profit_3_price": _price_at_pct(
                    latest_close,
                    strategy.take_profit_3_pct,
                ),
                "take_profit_3_pct": strategy.take_profit_3_pct,
                "max_hold_hours": strategy.max_hold_hours,
                "invalidation_rule": (
                    "Paper simulation invalidates if momentum fails, retest "
                    "breaks, or the planned stop is hit."
                ),
                "risk_note": (
                    "High risk. This is not a clean entry signal. Paper "
                    "simulation only; no live trading."
                ),
                "should_paper_trade": True,
                "parabolic_paper_eligible": True,
                "parabolic_paper_reason": reason,
                "reason": reason,
            }

        return _build_parabolic_monitoring_plan(
            symbol=symbol,
            alert_type=alert_type,
            latest_close=latest_close,
            reason=reason,
        )

    return {
        **_base_plan(symbol, alert_type, latest_close),
        "trade_plan_type": "no_trade_plan",
        "recommended_action": "Monitor only",
        "entry_approach": "No alert-specific trade plan is available.",
        "entry_zone_low": None,
        "entry_zone_high": None,
        "stop_loss_price": None,
        "stop_loss_pct": None,
        "take_profit_1_price": None,
        "take_profit_1_pct": None,
        "take_profit_2_price": None,
        "take_profit_2_pct": None,
        "take_profit_3_price": None,
        "take_profit_3_pct": None,
        "max_hold_hours": None,
        "invalidation_rule": "No alert trigger is active.",
        "risk_note": "No clean trade plan generated.",
        "should_paper_trade": False,
        "reason": "No supported alert type is active.",
    }


def round_price(price: float) -> float:
    """Round prices while preserving useful precision for small tokens."""
    price = _safe_float(price, default=0.0) or 0.0

    if price >= 1000:
        return round(price, 2)
    if price >= 1:
        return round(price, 4)
    if price >= 0.01:
        return round(price, 6)
    return round(price, 8)


def _build_directional_plan(
    result: dict,
    symbol: str,
    alert_type: str,
    latest_close: float,
    trade_plan_type: str,
    recommended_action: str,
    entry_approach: str,
    entry_zone_low_pct: float,
    stop_loss_pct: float,
    take_profit_1_pct: float,
    take_profit_2_pct: float,
    take_profit_3_pct: float,
    should_paper_trade: bool,
    reason: str,
) -> dict:
    """Build a plan for alerts that may become paper trades."""
    return {
        **_base_plan(symbol, alert_type, latest_close),
        "trade_plan_type": trade_plan_type,
        "recommended_action": recommended_action,
        "entry_approach": entry_approach,
        "entry_zone_low": _price_at_pct(latest_close, entry_zone_low_pct),
        "entry_zone_high": round_price(latest_close),
        "stop_loss_price": _price_at_pct(latest_close, stop_loss_pct),
        "stop_loss_pct": stop_loss_pct,
        "take_profit_1_price": _price_at_pct(latest_close, take_profit_1_pct),
        "take_profit_1_pct": take_profit_1_pct,
        "take_profit_2_price": _price_at_pct(latest_close, take_profit_2_pct),
        "take_profit_2_pct": take_profit_2_pct,
        "take_profit_3_price": _price_at_pct(latest_close, take_profit_3_pct),
        "take_profit_3_pct": take_profit_3_pct,
        "max_hold_hours": DEFAULT_MAX_HOLD_HOURS,
        "invalidation_rule": _directional_invalidation_rule(result, stop_loss_pct),
        "risk_note": _directional_risk_note(result),
        "should_paper_trade": bool(should_paper_trade),
        "reason": reason,
    }


def _base_plan(symbol: str, alert_type: str, latest_close: float) -> dict:
    """Return fields shared by all trade plans."""
    return {
        "symbol": symbol,
        "alert_type": alert_type,
        "latest_close": round_price(latest_close),
    }


def _build_parabolic_monitoring_plan(
    symbol: str,
    alert_type: str,
    latest_close: float,
    reason: str,
) -> dict:
    """Build a monitoring-only plan for parabolic alerts that fail paper rules."""
    return {
        **_base_plan(symbol, alert_type, latest_close),
        "trade_plan_type": "parabolic_watch_only",
        "recommended_action": "Watch only; do not chase",
        "entry_approach": (
            "Wait for pullback, consolidation, or retest. "
            "No clean entry currently."
        ),
        "entry_zone_low": None,
        "entry_zone_high": None,
        "stop_loss_price": None,
        "stop_loss_pct": None,
        "take_profit_1_price": None,
        "take_profit_1_pct": None,
        "take_profit_2_price": None,
        "take_profit_2_pct": None,
        "take_profit_3_price": None,
        "take_profit_3_pct": None,
        "max_hold_hours": None,
        "invalidation_rule": (
            "No clean trade plan generated. Monitoring only until a "
            "pullback, consolidation, or retest forms."
        ),
        "risk_note": "High risk. This is not a clean entry signal.",
        "should_paper_trade": False,
        "parabolic_paper_eligible": False,
        "parabolic_paper_reason": reason,
        "reason": reason,
    }


def _build_speculative_early_runner_plan(
    result: dict,
    symbol: str,
    latest_close: float,
) -> dict:
    """Build a high-risk paper-only plan for thin-liquidity early runners."""
    strategy = get_speculative_early_runner_strategy()
    should_paper_trade, reason = _speculative_early_runner_paper_eligibility(result)

    return {
        **_base_plan(symbol, "Speculative Early Runner Alert", latest_close),
        "trade_plan_type": "speculative_early_runner",
        "recommended_action": "Watch closely; high-risk early movement",
        "entry_approach": (
            "Only consider paper simulation after confirmation or pullback hold"
        ),
        "entry_zone_low": _price_at_pct(latest_close, -3),
        "entry_zone_high": round_price(latest_close),
        "stop_loss_price": _price_at_pct(latest_close, strategy.stop_loss_pct),
        "stop_loss_pct": strategy.stop_loss_pct,
        "take_profit_1_price": _price_at_pct(
            latest_close,
            strategy.take_profit_1_pct,
        ),
        "take_profit_1_pct": strategy.take_profit_1_pct,
        "take_profit_2_price": _price_at_pct(
            latest_close,
            strategy.take_profit_2_pct,
        ),
        "take_profit_2_pct": strategy.take_profit_2_pct,
        "take_profit_3_price": _price_at_pct(
            latest_close,
            strategy.take_profit_3_pct,
        ),
        "take_profit_3_pct": strategy.take_profit_3_pct,
        "max_hold_hours": strategy.max_hold_hours,
        "invalidation_rule": (
            "Invalidate if price loses the pullback hold, short-term momentum "
            "fades, or the planned stop is hit."
        ),
        "risk_note": (
            "High risk. Thin-liquidity early runner. This is not a clean "
            "continuation setup."
        ),
        "should_paper_trade": should_paper_trade,
        "speculative_paper_eligible": should_paper_trade,
        "speculative_paper_reason": reason,
        "reason": reason,
    }


def _speculative_early_runner_paper_eligibility(result: dict) -> tuple[bool, str]:
    """Return whether a speculative early runner can create a small paper trade."""
    alert_type = _get_alert_type(result)
    opportunity_score = _safe_float(
        _get_opportunity_value(result, "opportunity_score"),
        default=None,
    )
    liquidity_label = _get_liquidity_label(result).strip()
    target_bucket = str(_get_opportunity_value(result, "target_bucket") or "").strip()
    classification = str(
        _get_opportunity_value(result, "classification") or ""
    ).strip()
    exhaustion_level = _get_exhaustion_risk_level(result).strip()
    move_pct = _safe_float(_get_move_from_recent_low_pct(result), default=None)
    change_1h = _safe_float(_get_recent_price_change(result, "change_1h_pct")) or 0
    change_2h = _safe_float(_get_recent_price_change(result, "change_2h_pct")) or 0
    change_4h = _safe_float(_get_recent_price_change(result, "change_4h_pct")) or 0
    volume_acceleration_1h = (
        _safe_float(
            _get_volume_acceleration_ratio(
                result,
                "volume_acceleration_1h_ratio",
            )
        )
        or 0
    )
    volume_acceleration_2h = (
        _safe_float(
            _get_volume_acceleration_ratio(
                result,
                "volume_acceleration_2h_ratio",
            )
        )
        or 0
    )

    if alert_type != "Speculative Early Runner Alert":
        return False, "Rejected speculative runner: alert type is not Speculative Early Runner Alert."

    if opportunity_score is None or opportunity_score < 50:
        return False, "Rejected speculative runner: opportunity score below 50."

    if classification.lower() == "ignore":
        return False, "Rejected speculative runner: classification is Ignore."

    if target_bucket.lower() == "no clear upside setup":
        return False, "Rejected speculative runner: target bucket has no clear upside setup."

    if liquidity_label.lower() == "very thin":
        return False, "Rejected speculative runner: liquidity is Very thin."

    if exhaustion_level.lower() == "high":
        return False, "Rejected speculative runner: exhaustion risk is High."

    if move_pct is None or move_pct < 5 or move_pct > 20:
        return False, "Rejected speculative runner: move from recent low must be between 5% and 20%."

    if not (volume_acceleration_1h >= 2 or volume_acceleration_2h >= 2):
        return False, "Rejected speculative runner: volume acceleration below 2x."

    if not (change_1h >= 2 or change_2h >= 4 or change_4h >= 6):
        return False, "Rejected speculative runner: price change confirmation is too weak."

    return True, "Speculative early runner paper trade eligible."


def _parabolic_paper_trade_eligibility(
    result: dict,
) -> tuple[bool, str, PaperTradingStrategy]:
    """Run the parabolic paper-only eligibility rules without live trading."""
    from app.trading.paper_trading import should_create_parabolic_paper_trade

    strategy = get_parabolic_paper_strategy()
    should_create, reason = should_create_parabolic_paper_trade(result, strategy)

    return should_create, reason, strategy


def _get_alert_type(result: dict) -> str:
    """Read the alert type from an alert or scanner result."""
    if result.get("alert_type"):
        return str(result.get("alert_type"))

    explosive_mover = result.get("explosive_mover") or {}

    if explosive_mover.get("should_alert"):
        return str(explosive_mover.get("alert_type", "Explosive Mover Alert"))

    return "Continuation Alert"


def _has_tradeable_liquidity_and_exhaustion(result: dict) -> bool:
    """Return whether simple risk checks allow a paper trade."""
    liquidity_label = _get_liquidity_label(result).lower()
    exhaustion_level = _get_exhaustion_risk_level(result).lower()

    return (
        liquidity_label not in PAPER_TRADE_BLOCKED_LIQUIDITY_LABELS
        and exhaustion_level != "high"
    )


def _existing_paper_trading_rules_pass(result: dict) -> tuple[bool, str]:
    """Run the existing paper-trading eligibility checks for continuation plans."""
    from app.trading.paper_trading import should_create_paper_trade

    planless_result = {
        key: value
        for key, value in result.items()
        if key != "trade_plan"
    }
    return should_create_paper_trade(planless_result)


def _directional_invalidation_rule(result: dict, stop_loss_pct: float) -> str:
    """Build a plain-English invalidation rule for directional plans."""
    return (
        f"Invalidate if price closes below the planned stop ({stop_loss_pct:g}%) "
        "or if momentum/volume confirmation fails."
    )


def _directional_risk_note(result: dict) -> str:
    """Build a risk note from liquidity and exhaustion context."""
    liquidity_label = _get_liquidity_label(result) or "Not available"
    exhaustion_level = _get_exhaustion_risk_level(result) or "Not available"

    return (
        f"Advisory/paper-trading plan only. Liquidity: {liquidity_label}. "
        f"Exhaustion risk: {exhaustion_level}."
    )


def _price_at_pct(latest_close: float, pct: float) -> float:
    """Return a rounded price offset from latest close by pct."""
    return round_price(latest_close * (1 + (pct / 100)))


def _get_liquidity_label(result: dict) -> str:
    """Read liquidity label from nested or flattened result data."""
    if result.get("liquidity_label") is not None:
        return str(result.get("liquidity_label"))

    liquidity_signal = result.get("liquidity_signal") or {}
    return str(liquidity_signal.get("label", ""))


def _get_exhaustion_risk_level(result: dict) -> str:
    """Read exhaustion risk level from nested or flattened result data."""
    if result.get("exhaustion_risk_level") is not None:
        return str(result.get("exhaustion_risk_level"))

    exhaustion_signal = result.get("exhaustion_signal") or {}
    return str(exhaustion_signal.get("risk_level", ""))


def _get_move_from_recent_low_pct(result: dict):
    """Read move-from-low percentage from nested or flattened result data."""
    if result.get("move_from_recent_low_pct") is not None:
        return result.get("move_from_recent_low_pct")

    move_stage_signal = result.get("move_stage_signal") or {}
    return move_stage_signal.get("move_from_recent_low_pct")


def _get_recent_price_change(result: dict, key: str):
    """Read recent price changes from nested or flattened result data."""
    if result.get(key) is not None:
        return result.get(key)

    recent_changes = result.get("recent_price_changes") or {}
    return recent_changes.get(key)


def _get_volume_acceleration_ratio(result: dict, key: str):
    """Read volume acceleration ratios from nested or flattened result data."""
    if result.get(key) is not None:
        return result.get(key)

    volume_acceleration = result.get("volume_acceleration") or {}
    return volume_acceleration.get(key)


def _get_opportunity_value(result: dict, key: str):
    """Read opportunity values from nested or flattened result data."""
    opportunity = result.get("opportunity") or {}

    if opportunity.get(key) is not None:
        return opportunity.get(key)

    return result.get(key)


def _safe_float(value, default: float | None = 0.0) -> float | None:
    """Convert a value to float, returning default on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
