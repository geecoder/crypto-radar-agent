"""Text reporting helpers for scan results."""

from html import escape


def _safe_opportunity_score(opportunity: dict) -> int:
    """Read an opportunity score safely."""
    try:
        return int(opportunity.get("opportunity_score", 0))
    except (TypeError, ValueError):
        return 0


def _format_signal(name: str, signal: dict | None) -> str:
    """Format one signal line for the detailed report."""
    if not signal:
        return f"{name}: Not available"

    score = signal.get("score", "Not available")
    reason = signal.get("reason", "Not available")
    return f"{name}: score {score} - {reason}"


def _format_pct(value) -> str:
    """Format a percentage value for reports."""
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "Not available"


def _format_ratio(value) -> str:
    """Format a ratio value for reports."""
    try:
        return f"{float(value):.2f}x"
    except (TypeError, ValueError):
        return "Not available"


def _get_alert_type(result: dict) -> str:
    """Read the alert type from a scan result."""
    if result.get("alert_type"):
        return str(result.get("alert_type"))

    explosive_mover = result.get("explosive_mover", {})

    if explosive_mover.get("should_alert"):
        return str(explosive_mover.get("alert_type", "Explosive Mover Alert"))

    return "Continuation Alert"


def _is_explosive_alert_type(alert_type: str) -> bool:
    """Return whether an alert type belongs to the explosive mover lane."""
    return alert_type in {
        "Early Pump Alert",
        "Active Breakout Alert",
        "Parabolic Watch Alert",
    }


def _format_plan_price(value) -> str:
    """Format an optional trade-plan price."""
    if value is None:
        return "Not available"

    return str(value)


def _format_plan_pct(value) -> str:
    """Format an optional trade-plan percentage."""
    if value is None:
        return "Not available"

    try:
        return f"{float(value):g}%"
    except (TypeError, ValueError):
        return str(value)


def _format_trade_plan_lines(trade_plan: dict | None) -> list[str]:
    """Format a trade plan section for Telegram alerts."""
    if not trade_plan:
        return [
            "Trade Plan:",
            "No clean trade plan generated.",
            "Monitoring only.",
            "Paper trade skipped.",
        ]

    if trade_plan.get("trade_plan_type") == "parabolic_watch_only":
        return [
            "Trade Plan:",
            "No clean trade plan generated.",
            "Monitoring only.",
            "Paper trade skipped.",
            (
                "Recommended action: "
                f"{escape(str(trade_plan.get('recommended_action', 'Not available')))}"
            ),
            (
                "Entry approach: "
                f"{escape(str(trade_plan.get('entry_approach', 'Not available')))}"
            ),
            (
                "Invalidation rule: "
                f"{escape(str(trade_plan.get('invalidation_rule', 'Not available')))}"
            ),
            (
                "Risk note: "
                f"{escape(str(trade_plan.get('risk_note', 'Not available')))}"
            ),
        ]

    entry_zone = (
        f"{_format_plan_price(trade_plan.get('entry_zone_low'))} - "
        f"{_format_plan_price(trade_plan.get('entry_zone_high'))}"
    )

    return [
        "Trade Plan:",
        (
            "Recommended action: "
            f"{escape(str(trade_plan.get('recommended_action', 'Not available')))}"
        ),
        (
            "Entry approach: "
            f"{escape(str(trade_plan.get('entry_approach', 'Not available')))}"
        ),
        f"Entry zone: {escape(entry_zone)}",
        (
            "Stop-loss: "
            f"{escape(_format_plan_price(trade_plan.get('stop_loss_price')))} "
            f"({_format_plan_pct(trade_plan.get('stop_loss_pct'))})"
        ),
        (
            "TP1: "
            f"{escape(_format_plan_price(trade_plan.get('take_profit_1_price')))} "
            f"({_format_plan_pct(trade_plan.get('take_profit_1_pct'))})"
        ),
        (
            "TP2: "
            f"{escape(_format_plan_price(trade_plan.get('take_profit_2_price')))} "
            f"({_format_plan_pct(trade_plan.get('take_profit_2_pct'))})"
        ),
        (
            "TP3: "
            f"{escape(_format_plan_price(trade_plan.get('take_profit_3_price')))} "
            f"({_format_plan_pct(trade_plan.get('take_profit_3_pct'))})"
        ),
        f"Max hold: {escape(str(trade_plan.get('max_hold_hours', 'Not available')))}h",
        (
            "Invalidation rule: "
            f"{escape(str(trade_plan.get('invalidation_rule', 'Not available')))}"
        ),
        (
            "Risk note: "
            f"{escape(str(trade_plan.get('risk_note', 'Not available')))}"
        ),
    ]


def _get_interpretation(opportunity_score: int) -> str:
    """Return a short interpretation for an opportunity score."""
    if opportunity_score >= 70:
        return (
            "This is an alert candidate. Signals are sufficiently aligned for "
            "active monitoring."
        )
    if opportunity_score >= 60:
        return (
            "This is an early watch candidate. It needs stronger confirmation "
            "before becoming a high-quality alert."
        )
    if opportunity_score >= 40:
        return (
            "This is a weak setup. Some conditions are developing, but the "
            "signal is not strong enough yet."
        )
    return "This setup is weak. The signals are not sufficiently aligned."


def format_opportunity_table(results: list[dict]) -> str:
    """Return a simple table for opportunity scan results."""
    lines = [
        "Symbol | Score | Classification | Target Bucket | Risk | Latest Close",
        "-" * 78,
    ]

    if not results:
        lines.append("No results.")
        return "\n".join(lines)

    for result in results:
        opportunity = result.get("opportunity", {})
        lines.append(
            f"{result.get('symbol', 'Not available')} | "
            f"{opportunity.get('opportunity_score', 'Not available')} | "
            f"{opportunity.get('classification', 'Not available')} | "
            f"{opportunity.get('target_bucket', 'Not available')} | "
            f"{opportunity.get('risk_level', 'Not available')} | "
            f"{result.get('latest_close', 'Not available')}"
        )

    return "\n".join(lines)


def format_top_opportunity_detail(result: dict) -> str:
    """Return a detailed plain-English breakdown for one scan result."""
    opportunity = result.get("opportunity", {})
    opportunity_score = _safe_opportunity_score(opportunity)
    move_stage = result.get("move_stage_signal", {})
    continuation_target = result.get("continuation_target", {})
    exhaustion_signal = result.get("exhaustion_signal", {})
    liquidity_signal = result.get("liquidity_signal", {})

    lines = [
        "Top opportunity detail:",
        f"Symbol: {result.get('symbol', 'Not available')}",
        f"Latest close: {result.get('latest_close', 'Not available')}",
        f"Opportunity score: {opportunity.get('opportunity_score', 'Not available')}",
        f"Classification: {opportunity.get('classification', 'Not available')}",
        f"Target bucket: {opportunity.get('target_bucket', 'Not available')}",
        f"Risk level: {opportunity.get('risk_level', 'Not available')}",
        f"Summary: {opportunity.get('summary', 'Not available')}",
        f"Move Stage: {move_stage.get('stage', 'Not available')}",
        (
            "Move From Recent Low %: "
            f"{_format_pct(move_stage.get('move_from_recent_low_pct'))}"
        ),
        (
            "Continuation Target: "
            f"{continuation_target.get('target_bucket', 'Not available')}"
        ),
        f"Exhaustion Risk: {exhaustion_signal.get('risk_level', 'Not available')}",
        f"Liquidity Quality: {liquidity_signal.get('label', 'Not available')}",
        "",
        "Signals:",
        _format_signal("Volume signal", result.get("volume_signal")),
        _format_signal("Momentum signal", result.get("momentum_signal")),
        _format_signal("Breakout signal", result.get("breakout_signal")),
        _format_signal("Trend signal", result.get("trend_signal")),
        _format_signal("Volatility signal", result.get("volatility_signal")),
        _format_signal("Move stage signal", result.get("move_stage_signal")),
        _format_signal("Liquidity signal", result.get("liquidity_signal")),
        (
            "Exhaustion risk: "
            f"{exhaustion_signal.get('risk_level', 'Not available')} "
            f"(score {exhaustion_signal.get('risk_score', 'Not available')}) - "
            f"{exhaustion_signal.get('reason', 'Not available')}"
        ),
        "",
        "Interpretation:",
        _get_interpretation(opportunity_score),
    ]

    return "\n".join(lines)


def format_alert_message(alert_candidates: list[dict]) -> str:
    """Return a Telegram-friendly HTML alert message for scan candidates."""
    lines = ["<b>🚨 Crypto Radar Alert Candidates</b>"]

    for candidate in alert_candidates:
        alert_type = _get_alert_type(candidate)
        opportunity = candidate.get("opportunity", {})
        move_stage = candidate.get("move_stage_signal", {})
        continuation_target = candidate.get("continuation_target", {})
        exhaustion_signal = candidate.get("exhaustion_signal", {})
        liquidity_signal = candidate.get("liquidity_signal", {})
        recent_changes = candidate.get("recent_price_changes", {})
        volume_acceleration = candidate.get("volume_acceleration", {})
        trade_plan = candidate.get("trade_plan", {})

        if _is_explosive_alert_type(alert_type):
            explosive_mover = candidate.get("explosive_mover", {})
            lines.extend(
                [
                    "",
                    f"<b>{escape(str(candidate.get('symbol', 'Not available')))}</b>",
                    f"Alert Type: {escape(alert_type)}",
                    f"Latest close: {escape(str(candidate.get('latest_close', 'Not available')))}",
                    (
                        "Opportunity score: "
                        f"{escape(str(opportunity.get('opportunity_score', 'Not available')))}"
                    ),
                    (
                        "Move From Recent Low %: "
                        f"{escape(_format_pct(move_stage.get('move_from_recent_low_pct')))}"
                    ),
                    (
                        "15m change: "
                        f"{escape(_format_pct(recent_changes.get('change_15m_pct')))}"
                    ),
                    (
                        "30m change: "
                        f"{escape(_format_pct(recent_changes.get('change_30m_pct')))}"
                    ),
                    (
                        "1h change: "
                        f"{escape(_format_pct(recent_changes.get('change_1h_pct')))}"
                    ),
                    (
                        "2h change: "
                        f"{escape(_format_pct(recent_changes.get('change_2h_pct')))}"
                    ),
                    (
                        "4h change: "
                        f"{escape(_format_pct(recent_changes.get('change_4h_pct')))}"
                    ),
                    (
                        "24h change: "
                        f"{escape(_format_pct(recent_changes.get('change_24h_pct')))}"
                    ),
                    (
                        "Volume acceleration 1h: "
                        f"{escape(_format_ratio(volume_acceleration.get('volume_acceleration_1h_ratio')))}"
                    ),
                    (
                        "Volume acceleration 2h: "
                        f"{escape(_format_ratio(volume_acceleration.get('volume_acceleration_2h_ratio')))}"
                    ),
                    (
                        "Liquidity Quality: "
                        f"{escape(str(liquidity_signal.get('label', 'Not available')))}"
                    ),
                    (
                        "Exhaustion Risk: "
                        f"{escape(str(exhaustion_signal.get('risk_level', 'Not available')))}"
                    ),
                    (
                        "Potential bucket: "
                        f"{escape(str(explosive_mover.get('potential_bucket', 'Not available')))}"
                    ),
                    (
                        "Confidence: "
                        f"{escape(str(explosive_mover.get('confidence', 'Not available')))}"
                    ),
                    f"Reason: {escape(str(explosive_mover.get('reason', 'Not available')))}",
                ]
            )

            if alert_type == "Parabolic Watch Alert":
                parabolic_paper_eligible = bool(
                    trade_plan.get("parabolic_paper_eligible")
                )
                parabolic_paper_reason = str(
                    trade_plan.get("parabolic_paper_reason")
                    or trade_plan.get("reason")
                    or "Not available"
                )
                lines.extend(
                    [
                        (
                            "High risk. This is not a clean entry signal. "
                            "Avoid chasing vertical candles. Watch for pullback/retest."
                        ),
                        (
                            "Parabolic paper eligible: "
                            f"{'Yes' if parabolic_paper_eligible else 'No'}"
                        ),
                    ]
                )

                if parabolic_paper_eligible:
                    lines.append("High-risk paper simulation may be created.")
                else:
                    lines.append(
                        "Paper trade skipped: "
                        f"{escape(parabolic_paper_reason)}"
                    )

            lines.extend(_format_trade_plan_lines(trade_plan))
            continue

        lines.extend(
            [
                "",
                f"<b>{escape(str(candidate.get('symbol', 'Not available')))}</b>",
                f"Alert Type: {escape(alert_type)}",
                (
                    "Opportunity score: "
                    f"{escape(str(opportunity.get('opportunity_score', 'Not available')))}"
                ),
                (
                    "Classification: "
                    f"{escape(str(opportunity.get('classification', 'Not available')))}"
                ),
                (
                    "Target bucket: "
                    f"{escape(str(opportunity.get('target_bucket', 'Not available')))}"
                ),
                f"Risk level: {escape(str(opportunity.get('risk_level', 'Not available')))}",
                (
                    "Move Stage: "
                    f"{escape(str(move_stage.get('stage', 'Not available')))}"
                ),
                (
                    "Move From Recent Low %: "
                    f"{escape(_format_pct(move_stage.get('move_from_recent_low_pct')))}"
                ),
                (
                    "Continuation Target: "
                    f"{escape(str(continuation_target.get('target_bucket', 'Not available')))}"
                ),
                (
                    "Confidence: "
                    f"{escape(str(continuation_target.get('confidence', 'Not available')))}"
                ),
                (
                    "Exhaustion Risk: "
                    f"{escape(str(exhaustion_signal.get('risk_level', 'Not available')))}"
                ),
                (
                    "Liquidity Quality: "
                    f"{escape(str(liquidity_signal.get('label', 'Not available')))}"
                ),
                f"Latest close: {escape(str(candidate.get('latest_close', 'Not available')))}",
                (
                    "15m change: "
                    f"{escape(_format_pct(recent_changes.get('change_15m_pct')))}"
                ),
                (
                    "30m change: "
                    f"{escape(_format_pct(recent_changes.get('change_30m_pct')))}"
                ),
                (
                    "1h change: "
                    f"{escape(_format_pct(recent_changes.get('change_1h_pct')))}"
                ),
                (
                    "2h change: "
                    f"{escape(_format_pct(recent_changes.get('change_2h_pct')))}"
                ),
                (
                    "4h change: "
                    f"{escape(_format_pct(recent_changes.get('change_4h_pct')))}"
                ),
                (
                    "24h change: "
                    f"{escape(_format_pct(recent_changes.get('change_24h_pct')))}"
                ),
                (
                    "Volume acceleration 1h: "
                    f"{escape(_format_ratio(volume_acceleration.get('volume_acceleration_1h_ratio')))}"
                ),
                (
                    "Volume acceleration 2h: "
                    f"{escape(_format_ratio(volume_acceleration.get('volume_acceleration_2h_ratio')))}"
                ),
                (
                    "Potential bucket: "
                    f"{escape(str(continuation_target.get('target_bucket', 'Not available')))}"
                ),
                (
                    "Reason: "
                    f"{escape(str(continuation_target.get('reason', opportunity.get('summary', 'Not available'))))}"
                ),
                f"Summary: {escape(str(opportunity.get('summary', 'Not available')))}",
            ]
        )
        lines.extend(_format_trade_plan_lines(trade_plan))

    lines.extend(
        [
            "",
            "Not financial advice. Use this as a monitoring signal only.",
        ]
    )

    return "\n".join(lines)
