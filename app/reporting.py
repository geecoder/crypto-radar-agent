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

    lines = [
        "Top opportunity detail:",
        f"Symbol: {result.get('symbol', 'Not available')}",
        f"Latest close: {result.get('latest_close', 'Not available')}",
        f"Opportunity score: {opportunity.get('opportunity_score', 'Not available')}",
        f"Classification: {opportunity.get('classification', 'Not available')}",
        f"Target bucket: {opportunity.get('target_bucket', 'Not available')}",
        f"Risk level: {opportunity.get('risk_level', 'Not available')}",
        f"Summary: {opportunity.get('summary', 'Not available')}",
        "",
        "Signals:",
        _format_signal("Volume signal", result.get("volume_signal")),
        _format_signal("Momentum signal", result.get("momentum_signal")),
        _format_signal("Breakout signal", result.get("breakout_signal")),
        _format_signal("Trend signal", result.get("trend_signal")),
        _format_signal("Volatility signal", result.get("volatility_signal")),
        "",
        "Interpretation:",
        _get_interpretation(opportunity_score),
    ]

    return "\n".join(lines)


def format_alert_message(alert_candidates: list[dict]) -> str:
    """Return a Telegram-friendly HTML alert message for scan candidates."""
    lines = ["<b>🚨 Crypto Radar Alert Candidates</b>"]

    for candidate in alert_candidates:
        opportunity = candidate.get("opportunity", {})
        lines.extend(
            [
                "",
                f"<b>{escape(str(candidate.get('symbol', 'Not available')))}</b>",
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
                f"Latest close: {escape(str(candidate.get('latest_close', 'Not available')))}",
                f"Summary: {escape(str(opportunity.get('summary', 'Not available')))}",
            ]
        )

    lines.extend(
        [
            "",
            "Not financial advice. Use this as a monitoring signal only.",
        ]
    )

    return "\n".join(lines)
