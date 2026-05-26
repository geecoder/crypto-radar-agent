"""Diagnostic reporting for missed mover analysis."""

from contextlib import redirect_stdout
from io import StringIO

from app.indicators.explosive_mover import evaluate_speculative_early_runner
from app.scanner import scan_symbol

NO_VALID_CONTINUATION_TARGETS = {
    "No clear continuation setup",
    "Avoid / late chase",
}


def diagnose_symbol(
    client,
    symbol: str,
    alert_threshold: int = 60,
    interval: str = "15m",
    limit: int = 100,
) -> dict:
    """Fetch market data for one symbol and calculate scanner diagnostics."""
    normalized_symbol = symbol.strip().upper()
    try:
        with redirect_stdout(StringIO()):
            ticker_24hr = _fetch_symbol_ticker_24hr(client, normalized_symbol)
            result = scan_symbol(
                client,
                normalized_symbol,
                interval=interval,
                limit=limit,
                ticker_24hr=ticker_24hr,
            )
    except Exception as error:
        result = {
            "symbol": normalized_symbol,
            "error": str(error),
        }

    result["diagnostic"] = {
        "alert_threshold": alert_threshold,
        "would_alert": (
            _get_opportunity_score(result) >= alert_threshold
            or _is_explosive_alert(result)
        ),
    }
    return result


def format_diagnostic_report(result: dict, alert_threshold: int = 60) -> str:
    """Build a plain-text diagnostic report for one scan result."""
    if "error" in result:
        return "\n".join(
            [
                "Missed Mover Diagnostic",
                f"Symbol: {result.get('symbol', 'Not available')}",
                "Market data unavailable. Diagnosis skipped.",
                f"Error: {result.get('error', 'Not available')}",
            ]
        )

    opportunity = result.get("opportunity", {})
    move_stage = result.get("move_stage_signal", {})
    liquidity = result.get("liquidity_signal", {})
    exhaustion = result.get("exhaustion_signal", {})
    continuation = result.get("continuation_target", {})
    explosive_mover = result.get("explosive_mover", {})
    recent_changes = result.get("recent_price_changes", {})
    volume_acceleration = result.get("volume_acceleration", {})
    trade_plan = result.get("trade_plan", {})
    component_scores = opportunity.get("component_scores", {})
    score = _get_opportunity_score(result)
    would_alert = score >= alert_threshold or _is_explosive_alert(result)
    parabolic_paper_eligible, parabolic_paper_reason = _parabolic_paper_status(
        result,
        trade_plan,
    )
    explosive_rule_statuses = _explosive_rule_statuses(result)
    speculative_qualified, speculative_reason = _speculative_early_runner_status(
        result
    )
    alert_type = _explosive_alert_type(result)
    early_pump_qualified = (
        explosive_rule_statuses["early_pump"]
        or alert_type == "Early Pump Alert"
    )
    active_breakout_qualified = (
        explosive_rule_statuses["active_breakout"]
        or alert_type == "Active Breakout Alert"
    )
    speculative_qualified = (
        speculative_qualified
        or alert_type == "Speculative Early Runner Alert"
    )
    parabolic_qualified = (
        explosive_rule_statuses["parabolic_watch"]
        or alert_type == "Parabolic Watch Alert"
    )

    lines = [
        "Missed Mover Diagnostic",
        f"Symbol: {result.get('symbol', 'Not available')}",
        f"Latest close: {result.get('latest_close', 'Not available')}",
        f"Opportunity score: {opportunity.get('opportunity_score', 'Not available')}",
        f"Alert threshold: {alert_threshold}",
        f"Would alert? {'Yes' if would_alert else 'No'}",
        f"Classification: {opportunity.get('classification', 'Not available')}",
        f"Target bucket: {opportunity.get('target_bucket', 'Not available')}",
        (
            "Continuation target: "
            f"{continuation.get('target_bucket', 'Not available')}"
        ),
        (
            "Explosive mover alert type: "
            f"{explosive_mover.get('alert_type', 'Not available')}"
        ),
        (
            "Explosive mover should_alert: "
            f"{str(bool(explosive_mover.get('should_alert'))).lower()}"
        ),
        (
            "Explosive mover reason: "
            f"{explosive_mover.get('reason', 'Not available')}"
        ),
        (
            "Would trigger Continuation Alert? "
            f"{_format_bool(score >= alert_threshold)}"
        ),
        (
            "Would trigger Early Pump Alert? "
            f"{_format_bool(early_pump_qualified)}"
        ),
        (
            "Would trigger Active Breakout Alert? "
            f"{_format_bool(active_breakout_qualified)}"
        ),
        (
            "Would trigger Speculative Early Runner Alert? "
            f"{_format_bool(speculative_qualified)}"
        ),
        f"Speculative Early Runner reason: {speculative_reason}",
        (
            "Would trigger Parabolic Watch Alert? "
            f"{_format_bool(parabolic_qualified)}"
        ),
        (
            "Parabolic paper eligible: "
            f"{_format_bool(parabolic_paper_eligible)}"
        ),
        f"Parabolic paper reason: {parabolic_paper_reason}",
        (
            "Would create parabolic paper trade? "
            f"{_format_bool(parabolic_paper_eligible)}"
        ),
        f"Move stage: {move_stage.get('stage', 'Not available')}",
        (
            "Move from recent low %: "
            f"{_format_pct(move_stage.get('move_from_recent_low_pct'))}"
        ),
        f"Liquidity label: {liquidity.get('label', 'Not available')}",
        f"Exhaustion risk: {exhaustion.get('risk_level', 'Not available')}",
        "",
        "Recent price changes:",
        f"- 15m: {_format_pct(recent_changes.get('change_15m_pct'))}",
        f"- 30m: {_format_pct(recent_changes.get('change_30m_pct'))}",
        f"- 1h: {_format_pct(recent_changes.get('change_1h_pct'))}",
        f"- 2h: {_format_pct(recent_changes.get('change_2h_pct'))}",
        f"- 4h: {_format_pct(recent_changes.get('change_4h_pct'))}",
        f"- 24h: {_format_pct(recent_changes.get('change_24h_pct'))}",
        "",
        "Volume acceleration:",
        (
            "- 1h ratio: "
            f"{_format_ratio(volume_acceleration.get('volume_acceleration_1h_ratio'))}"
        ),
        (
            "- 2h ratio: "
            f"{_format_ratio(volume_acceleration.get('volume_acceleration_2h_ratio'))}"
        ),
        "",
        "Trade Plan:",
    ]
    lines.extend(_format_trade_plan_lines(trade_plan))
    lines.extend(["", "Component scores:"])
    lines.extend(_format_component_scores(component_scores))

    rejection_reasons = get_rejection_reasons(result, alert_threshold)
    if rejection_reasons:
        lines.extend(["", "Diagnostics:"])
        lines.extend(rejection_reasons)

    lines.extend(
        [
            "",
            "Recommendation:",
            get_recommendation(result, alert_threshold),
        ]
    )

    return "\n".join(lines)


def get_rejection_reasons(result: dict, alert_threshold: int = 60) -> list[str]:
    """Return diagnostic rejection and weak-confirmation reasons."""
    score = _get_opportunity_score(result)
    liquidity = result.get("liquidity_signal", {})
    exhaustion = result.get("exhaustion_signal", {})
    continuation = result.get("continuation_target", {})
    move_stage = result.get("move_stage_signal", {})
    volume_score = _get_signal_score(result.get("volume_signal"))
    breakout_score = _get_signal_score(result.get("breakout_signal"))
    move_from_recent_low_pct = _safe_float(
        move_stage.get("move_from_recent_low_pct")
    )
    reasons = []

    if score < alert_threshold:
        reasons.append("Rejected: score below alert threshold.")

    if liquidity.get("label") in {"Thin", "Very thin"}:
        reasons.append("Rejected/penalised: liquidity is thin.")

    if exhaustion.get("risk_level") == "High":
        reasons.append("Rejected/penalised: exhaustion risk is high.")

    if continuation.get("target_bucket") in NO_VALID_CONTINUATION_TARGETS:
        reasons.append("Rejected/penalised: no valid continuation target.")

    if volume_score < 40:
        reasons.append("Weak confirmation: volume expansion is insufficient.")

    if breakout_score == 0:
        reasons.append("Weak confirmation: no breakout confirmed.")

    if move_from_recent_low_pct > 20:
        reasons.append("Late move risk: price may already be extended.")

    return reasons


def get_recommendation(result: dict, alert_threshold: int = 60) -> str:
    """Return the final diagnostic recommendation."""
    score = _get_opportunity_score(result)
    alert_type = _explosive_alert_type(result)

    if alert_type == "Parabolic Watch Alert" and score < alert_threshold:
        return "This qualifies as a Parabolic Watch Alert but not as a clean trade setup."

    if alert_type == "Speculative Early Runner Alert" and score < alert_threshold:
        return (
            "This qualifies as a Speculative Early Runner Alert but not as a "
            "clean trade setup."
        )

    if score >= alert_threshold or _is_explosive_alert(result):
        return "This symbol currently qualifies as an alert candidate."

    if alert_threshold - score <= 10:
        return "Near miss. Monitor if volume/breakout improves."

    return "Does not currently qualify."


def _fetch_symbol_ticker_24hr(client, symbol: str) -> dict:
    """Fetch 24-hour ticker data for one symbol from available client methods."""
    if hasattr(client, "get_24hr_ticker"):
        return client.get_24hr_ticker(symbol)

    if not hasattr(client, "get_24hr_tickers"):
        return {}

    for ticker in client.get_24hr_tickers():
        if ticker.get("symbol") == symbol:
            return ticker

    return {}


def _format_component_scores(component_scores: dict) -> list[str]:
    """Format component scores in a stable order."""
    if not component_scores:
        return ["- Not available"]

    ordered_names = [
        "volume",
        "momentum",
        "breakout",
        "trend",
        "volatility",
        "move_stage",
        "liquidity",
        "exhaustion_risk",
    ]
    lines = []

    for name in ordered_names:
        if name in component_scores:
            lines.append(f"- {name}: {component_scores[name]}")

    for name, value in component_scores.items():
        if name not in ordered_names:
            lines.append(f"- {name}: {value}")

    return lines


def _format_trade_plan_lines(trade_plan: dict | None) -> list[str]:
    """Format a trade plan for diagnostic output."""
    if not trade_plan:
        return [
            "- No clean trade plan generated.",
            "- Monitoring only.",
            "- Paper trade skipped.",
        ]

    lines = [
        f"- Type: {trade_plan.get('trade_plan_type', 'Not available')}",
        f"- Recommended action: {trade_plan.get('recommended_action', 'Not available')}",
        f"- Entry approach: {trade_plan.get('entry_approach', 'Not available')}",
    ]

    if trade_plan.get("trade_plan_type") == "parabolic_watch_only":
        lines.extend(
            [
                "- No clean trade plan generated.",
                "- Monitoring only.",
                "- Paper trade skipped.",
            ]
        )
    else:
        lines.extend(
            [
                (
                    "- Entry zone: "
                    f"{_format_optional(trade_plan.get('entry_zone_low'))} - "
                    f"{_format_optional(trade_plan.get('entry_zone_high'))}"
                ),
                (
                    "- Stop-loss: "
                    f"{_format_optional(trade_plan.get('stop_loss_price'))} "
                    f"({_format_pct(trade_plan.get('stop_loss_pct'))})"
                ),
                (
                    "- TP1: "
                    f"{_format_optional(trade_plan.get('take_profit_1_price'))} "
                    f"({_format_pct(trade_plan.get('take_profit_1_pct'))})"
                ),
                (
                    "- TP2: "
                    f"{_format_optional(trade_plan.get('take_profit_2_price'))} "
                    f"({_format_pct(trade_plan.get('take_profit_2_pct'))})"
                ),
                (
                    "- TP3: "
                    f"{_format_optional(trade_plan.get('take_profit_3_price'))} "
                    f"({_format_pct(trade_plan.get('take_profit_3_pct'))})"
                ),
                f"- Max hold: {_format_optional(trade_plan.get('max_hold_hours'))}h",
            ]
        )

    lines.extend(
        [
            f"- Invalidation rule: {trade_plan.get('invalidation_rule', 'Not available')}",
            f"- Risk note: {trade_plan.get('risk_note', 'Not available')}",
            (
                "- Should paper trade: "
                f"{_format_bool(bool(trade_plan.get('should_paper_trade')))}"
            ),
            f"- Reason: {trade_plan.get('reason', 'Not available')}",
        ]
    )
    return lines


def _is_explosive_alert(result: dict) -> bool:
    """Return whether the explosive mover lane wants an alert."""
    return bool(result.get("explosive_mover", {}).get("should_alert"))


def _explosive_alert_type(result: dict) -> str:
    """Read the explosive mover alert type."""
    if result.get("alert_type"):
        return str(result.get("alert_type"))

    return str(result.get("explosive_mover", {}).get("alert_type", ""))


def _parabolic_paper_status(result: dict, trade_plan: dict | None) -> tuple[bool, str]:
    """Return diagnostic parabolic paper eligibility and reason."""
    if isinstance(trade_plan, dict) and "parabolic_paper_eligible" in trade_plan:
        return (
            bool(trade_plan.get("parabolic_paper_eligible")),
            str(
                trade_plan.get("parabolic_paper_reason")
                or trade_plan.get("reason")
                or "Not available"
            ),
        )

    alert_type = result.get("alert_type") or _explosive_alert_type(result)

    if alert_type != "Parabolic Watch Alert":
        return False, "Not a Parabolic Watch Alert."

    from app.trading.paper_trading import should_create_parabolic_paper_trade

    return should_create_parabolic_paper_trade(result)


def _speculative_early_runner_status(result: dict) -> tuple[bool, str]:
    """Return speculative early-runner eligibility and diagnostic reason."""
    status = evaluate_speculative_early_runner(
        result.get("move_stage_signal") or {},
        result.get("recent_price_changes") or {},
        result.get("volume_acceleration") or {},
        result.get("liquidity_signal") or {},
        result.get("exhaustion_signal") or {},
    )

    qualified = bool(status.get("qualified"))
    reason = str(status.get("reason", "Not available"))

    if not qualified and _explosive_alert_type(result) == "Speculative Early Runner Alert":
        reason = str(result.get("explosive_mover", {}).get("reason") or reason)

    return qualified, reason


def _explosive_rule_statuses(result: dict) -> dict:
    """Return independent eligibility flags for explosive alert categories."""
    move_stage = result.get("move_stage_signal") or {}
    recent_changes = result.get("recent_price_changes") or {}
    volume_acceleration = result.get("volume_acceleration") or {}
    liquidity = result.get("liquidity_signal") or {}
    exhaustion = result.get("exhaustion_signal") or {}
    trend = result.get("trend_signal") or {}
    volatility = result.get("volatility_signal") or {}
    move_pct = _safe_float(move_stage.get("move_from_recent_low_pct"))
    change_1h = _safe_float(recent_changes.get("change_1h_pct"))
    change_2h = _safe_float(recent_changes.get("change_2h_pct"))
    change_4h = _safe_float(recent_changes.get("change_4h_pct"))
    change_24h = _safe_float(recent_changes.get("change_24h_pct"))
    volume_score = _get_signal_score(volume_acceleration)
    liquidity_score = _get_signal_score(liquidity)
    trend_score = _get_signal_score(trend)
    volatility_score = _get_signal_score(volatility)
    exhaustion_level = str(exhaustion.get("risk_level", "Low"))

    return {
        "early_pump": (
            move_pct >= 3
            and move_pct <= 10
            and (change_1h >= 3 or change_2h >= 5)
            and volume_score >= 40
            and liquidity_score >= 40
            and exhaustion_level != "High"
            and trend_score >= 60
        ),
        "active_breakout": (
            move_pct > 10
            and move_pct <= 30
            and (change_1h >= 5 or change_4h >= 12)
            and volume_score >= 60
            and liquidity_score >= 40
            and trend_score >= 60
            and volatility_score >= 60
        ),
        "parabolic_watch": (
            (move_pct > 50 or change_4h >= 30 or change_24h >= 50)
            and liquidity_score >= 40
        ),
    }


def _get_opportunity_score(result: dict) -> int:
    """Read the opportunity score safely."""
    try:
        return int(result.get("opportunity", {}).get("opportunity_score", 0))
    except (TypeError, ValueError):
        return 0


def _get_signal_score(signal: dict | None) -> int:
    """Read a standard signal score safely."""
    if not signal:
        return 0

    try:
        return int(signal.get("score", 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value) -> float:
    """Read a float safely."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _format_pct(value) -> str:
    """Format percentage values for diagnostic output."""
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "Not available"


def _format_ratio(value) -> str:
    """Format ratio values for diagnostic output."""
    try:
        return f"{float(value):.2f}x"
    except (TypeError, ValueError):
        return "Not available"


def _format_optional(value) -> str:
    """Format optional scalar values for diagnostics."""
    if value is None:
        return "Not available"

    return str(value)


def _format_bool(value: bool) -> str:
    """Format booleans in the same style as classifier flags."""
    return str(bool(value)).lower()
